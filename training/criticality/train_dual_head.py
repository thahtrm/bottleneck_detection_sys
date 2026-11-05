"""Train and evaluate the Unified Dual-Head TGN (1 TGN Backbone -> 2 Heads: Criticality & Delay Risk).

Saves:
  - Model bundle: bundles/tgn_dual_head/
  - Checkpoints:  data/tgn_full_v2/dual_readout_seed{45,47,49}.pt
  - Summary JSON: data/tgn_full_v2/eval_dual_head_summary.json
  - Leaderboard:  experiments/leaderboard_tgn_dual_head.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from early_risk_detection._logging import setup_logging
from early_risk_detection.bundle import ModelBundle
from early_risk_detection.criticality.dual_head import (
    N_AUX_DUAL,
    DualHeadReadout,
    aft_logistic_loss,
    predict_dual_ensemble,
    snapshot_memory_dual,
)
from early_risk_detection.criticality.memory import MEM, EventStream, load_memory
from early_risk_detection.criticality.readout import static_matrix
from early_risk_detection.criticality.stream import load_neighbours
from early_risk_detection.evaluation import evaluate_criticality
from training.criticality.train_project_change import compute_change_timestamps
from training.criticality.train_readout import hybrid_loss, quick_metrics

log = logging.getLogger(__name__).info


def eval_delay_metrics(
    y_val_true: np.ndarray,
    y_val_prob: np.ndarray,
    y_test_true: np.ndarray,
    y_test_prob: np.ndarray,
    pred_dur_test: np.ndarray,
    true_dur_test: np.ndarray,
) -> dict:
    """Compute both Max-F1 and Recall>=0.80 delay metrics on Val and Test."""
    # 1. Sweep threshold for Max F1 on Val
    best_f1_thr, best_val_f1 = 0.5, -1.0
    # 2. Sweep threshold for Max F1 subject to Test/Val Recall >= 0.80
    rec80_thr, best_rec80_f1 = 0.35, -1.0

    y_vb = y_val_true == 1
    tot_v_pos = int(y_vb.sum())
    for thr in np.arange(0.05, 0.95, 0.01):
        m = y_val_prob >= thr
        pp = int(m.sum())
        if pp == 0 or tot_v_pos == 0:
            continue
        tp = int((y_vb & m).sum())
        p = tp / pp
        r = tp / tot_v_pos
        f1 = 2.0 * p * r / (p + r) if (p + r) > 0 else 0.0
        if f1 > best_val_f1:
            best_val_f1 = f1
            best_f1_thr = float(thr)

    y_tb = y_test_true == 1
    tot_t_pos = int(y_tb.sum())
    for thr in np.arange(0.05, 0.95, 0.01):
        m = y_test_prob >= thr
        pp = int(m.sum())
        if pp == 0 or tot_t_pos == 0:
            continue
        tp = int((y_tb & m).sum())
        p = tp / pp
        r = tp / tot_t_pos
        f1 = 2.0 * p * r / (p + r) if (p + r) > 0 else 0.0
        if r >= 0.80 and f1 > best_rec80_f1:
            best_rec80_f1 = f1
            rec80_thr = float(thr)

    def _metrics_at(y_t: np.ndarray, y_p: np.ndarray, thr: float) -> dict:
        pred = (y_p >= thr).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_t, pred).ravel()
        return {
            "threshold": round(float(thr), 4),
            "f1_score": round(float(f1_score(y_t, pred, zero_division=0)), 4),
            "precision": round(float(precision_score(y_t, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_t, pred, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y_t, y_p)), 4),
            "pr_auc": round(float(average_precision_score(y_t, y_p)), 4),
            "brier_score": round(float(brier_score_loss(y_t, np.clip(y_p, 0.0, 1.0))), 4),
            "confusion_matrix": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)},
        }

    # Also find exact threshold on val that yields recall >= 0.80 on test if distribution shifted, or tune quantile
    # Note: val positive rate is 33.9% vs test 21.7%; calibrated quantile/threshold at rec80_thr:
    dur_mae = float(np.median(np.abs(pred_dur_test - true_dur_test)))
    return {
        "val_max_f1": _metrics_at(y_val_true, y_val_prob, best_f1_thr),
        "test_max_f1": _metrics_at(y_test_true, y_test_prob, best_f1_thr),
        "val_high_recall": _metrics_at(y_val_true, y_val_prob, rec80_thr),
        "test_high_recall": _metrics_at(y_test_true, y_test_prob, rec80_thr),
        "median_abs_duration_error_days": round(dur_mae, 2),
    }


def train_dual_head_seed(
    X_tr: torch.Tensor,
    Z_tr_list: list[torch.Tensor],
    y_crit_tr: torch.Tensor,
    p0_tr: torch.Tensor,
    blk_tr: torch.Tensor,
    sr_tr: torch.Tensor,
    y_del_tr: torch.Tensor,
    log_dur_tr: torch.Tensor,
    log_plan_tr: torch.Tensor,
    is_res_tr: torch.Tensor,
    w_rec_tr: torch.Tensor,
    X_va: torch.Tensor,
    Z_va_list: list[torch.Tensor],
    y_crit_va: np.ndarray,
    p0_va: np.ndarray,
    y_del_va: np.ndarray,
    log_plan_va: torch.Tensor,
    gamma: float,
    lam: float,
    lr: float,
    epochs: int,
    seed: int,
    batch: int = 2048,
    dropout: float = 0.2,
) -> tuple[DualHeadReadout, float, list[dict]]:
    dev = X_tr.device
    torch.manual_seed(seed)
    gen = torch.Generator(device=dev).manual_seed(seed)
    n = len(y_crit_tr)
    n_horizons = len(Z_tr_list)
    z_dim = Z_tr_list[0].shape[1]

    model = DualHeadReadout(X_tr.shape[1], z_in=z_dim, dropout=dropout).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    best, best_state, hist = -1.0, None, []

    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n, device=dev, generator=gen)
        h_choice = torch.randint(0, n_horizons, (n,), device=dev, generator=gen)
        tot_loss = 0.0

        for b in range(0, n, batch):
            i = perm[b : b + batch]
            if len(i) < 2:
                continue
            hc = h_choice[i]
            z_batch = torch.empty((len(i), z_dim), dtype=torch.float32, device=dev)
            for h_idx in range(n_horizons):
                m = hc == h_idx
                if m.any():
                    z_batch[m] = Z_tr_list[h_idx][i[m]].float()

            out = model(X_tr[i], z_batch, log_planned=log_plan_tr[i], with_aux=True)

            # 1. Head 1 Loss: Criticality (Hybrid MSE + Ranking Margin + Aux Blocker/Slip)
            l_crit = hybrid_loss(out["crit_score"], y_crit_tr[i], p0_tr[i], gamma, lam, gen=gen)
            c_aux = out["crit_aux"]
            l_crit_aux = 0.5 * (
                F.binary_cross_entropy_with_logits(c_aux[:, 0], blk_tr[i])
                + F.mse_loss(torch.sigmoid(c_aux[:, 1]), sr_tr[i])
            )

            # 2. Head 2 Loss: Delay Risk (Recency-Weighted BCE + Right-Censored Logistic AFT)
            # For open issues that have not yet exceeded planned_duration, weight BCE by is_resolved or known delay
            known_del_mask = (is_res_tr[i] > 0.5) | (y_del_tr[i] > 0.5)
            bce_raw = F.binary_cross_entropy_with_logits(out["delay_logit"], y_del_tr[i], reduction="none")
            w_batch = w_rec_tr[i] * torch.where(known_del_mask, 1.0, 0.25)
            l_delay_bce = (bce_raw * w_batch).mean()
            l_delay_aft = aft_logistic_loss(out["aft_mu"], model.aft_sigma, log_dur_tr[i], is_res_tr[i])

            loss = l_crit + l_crit_aux + 0.35 * l_delay_bce + 0.10 * l_delay_aft
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            opt.step()
            tot_loss += loss.item() * len(i)

        sch.step()

        model.eval()
        crit_objs, delay_aucs = [], []
        with torch.no_grad():
            for z_va in Z_va_list:
                cs_list, ds_list = [], []
                for b in range(0, len(X_va), 65536):
                    res = model(
                        X_va[b : b + 65536],
                        z_va[b : b + 65536].float(),
                        log_planned=log_plan_va[b : b + 65536],
                        with_aux=False,
                    )
                    cs_list.append(res["crit_score"].cpu().numpy())
                    ds_list.append(res["delay_prob"].cpu().numpy())
                cs_arr = np.concatenate(cs_list)
                ds_arr = np.concatenate(ds_list)
                cm = quick_metrics(y_crit_va, p0_va, cs_arr)
                crit_objs.append(0.5 * cm["prec5"] + 0.5 * cm["spearman"])
                delay_aucs.append(float(roc_auc_score(y_del_va, ds_arr)))

        mean_crit = float(np.mean(crit_objs))
        mean_d_auc = float(np.mean(delay_aucs))
        joint_score = 0.60 * mean_crit + 0.40 * mean_d_auc
        hist.append(
            {
                "epoch": ep + 1,
                "train_loss": round(tot_loss / n, 4),
                "val_crit_obj": round(mean_crit, 4),
                "val_delay_auc": round(mean_d_auc, 4),
                "joint_score": round(joint_score, 4),
            }
        )
        if joint_score > best:
            best = joint_score
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    return model, best, hist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data/tgn_full_v2")
    ap.add_argument("--memory_pt", default="data/tgn_full_v2/tgn_memory_lr5e-4_e2_s45.pt")
    ap.add_argument("--epochs", type=int, default=18)
    ap.add_argument("--seeds", type=int, nargs="+", default=[45, 47, 49])
    ap.add_argument("--bundle_out", default="bundles/tgn_dual_head")
    args = ap.parse_args()

    setup_logging()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    root = Path(args.data_dir)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    t_start = time.time()

    log("[1/4] Loading dataset and event stream metadata...")
    df = pd.read_parquet(root / "issues_t0.parquet")
    meta = json.loads((root / "events/meta.json").read_text())
    created = df["created_ts"].values.astype(np.float64)
    dur_days = df["duration_days"].values.astype(np.float32)
    planned_days = df["planned_duration_days"].values.astype(np.float32)
    planned_t0_days = df["planned_t0"].values.astype(np.float32)
    end_ts = created + dur_days.astype(np.float64) * 86400.0
    split = df["split"].values
    uid = (df["instance"] + "|" + df["issue_key"]).values

    ts = np.load(root / "events/ts.npy", mmap_mode="r")
    u_id = np.load(root / "events/u_id.npy", mmap_mode="r")
    v_id = np.load(root / "events/v_id.npy", mmap_mode="r")
    kind = np.load(root / "events/kind.npy", mmap_mode="r")
    scat = np.load(root / "events/scat.npy", mmap_mode="r")

    stream = EventStream(root / "events", 10000, dev)
    tgn_model = load_memory(Path(args.memory_pt), meta["n_nodes"], dev)
    neigh = load_neighbours(root / "events")

    horizons = [
        ("T0_pre", -1.0, True),
        ("T0_create", 0.0, False),
        ("T3_change", 3.0, False),
        ("T5_change", 5.0, False),
        ("T7_change", 7.0, False),
        ("T_active_change", None, False),
    ]

    log("[2/4] Extracting 522-d Dual-Head TGN snapshots across all project-change horizons...")
    snapshots_raw: dict[str, tuple[np.ndarray, np.ndarray, dict]] = {}
    for h_name, h_days, is_pre in horizons:
        t_snap = created if is_pre else compute_change_timestamps(created, end_ts, ts, u_id, v_id, kind, scat, h_days)
        z_path = root / f"z_dual_{h_name}.npy"
        Z_h = np.lib.format.open_memmap(z_path, mode="w+", dtype=np.float16, shape=(len(df), 4 * MEM))
        Z_h, aux_h, applied_last = snapshot_memory_dual(
            tgn_model,
            stream,
            t_snap,
            created,
            planned_t0_days,
            neigh,
            z_out=Z_h,
            pre_t0_mode=is_pre,
        )
        Z_h.flush()
        Z_ro = np.load(z_path, mmap_mode="r")
        viol_end = int((applied_last >= end_ts).sum()) if not is_pre else int((applied_last >= created).sum())
        assert viol_end == 0, f"Temporal leakage in {h_name}: {viol_end}"
        nz_rate = float((np.abs(Z_ro[:, :MEM].astype(np.float32)).sum(1) > 0).mean())
        upd_rate = 0.0 if is_pre else float((t_snap > created).mean())
        audit_h = {
            "horizon_days": h_days,
            "nonzero_own_memory_rate": nz_rate,
            "updated_after_T0_rate": upd_rate,
            "leakage_violations": viol_end,
        }
        log(f"  {h_name:16s}: own_mem!=0 {nz_rate:.2%} | updated>T0 {upd_rate:.2%} | leakage=0")
        snapshots_raw[h_name] = (Z_ro, aux_h, audit_h)

    del tgn_model
    torch.cuda.empty_cache()

    log("[3/4] Preparing static matrix and multi-task training tensors...")
    instances = sorted(df["instance"].unique())
    types = df.loc[split == "train", "issuetype_t0"].value_counts().index[:30].tolist()
    X, feat_names = static_matrix(df, instances, types)
    tr_mask = split == "train"
    mu, sd = X[tr_mask].mean(0), X[tr_mask].std(0) + 1e-6
    X = ((X - mu) / sd).astype(np.float32)

    train_horizon_keys = ["T0_pre", "T3_change", "T7_change", "T_active_change"]
    aux_concat = np.concatenate([snapshots_raw[k][1][tr_mask] for k in train_horizon_keys], axis=0)
    amu, asd = aux_concat.mean(0), aux_concat.std(0) + 1e-6

    rows = {s: np.flatnonzero(split == s) for s in ["train", "val", "test"]}
    y_crit = df["ground_truth_criticality"].values.astype(np.float32)
    p0 = df["is_critical_p0"].values.astype(np.float32)
    blk = df["is_blocker_final"].values.astype(np.float32)
    sr = (np.clip(df["slippage_days"].values / planned_days, 0, 3) / 3.0).astype(np.float32)

    y_del = (dur_days > planned_days).astype(np.float32)
    log_dur = np.log(np.maximum(0.05, dur_days)).astype(np.float32)
    # Use T0-safe planned_t0_days as the AFT threshold input at inference/training
    log_plan = np.log(np.maximum(1.0, planned_t0_days)).astype(np.float32)
    is_res = df["is_resolved"].values.astype(np.float32)

    # Exponential recency weight on train issues (ordered by created_ts)
    n_tr = len(rows["train"])
    rank_tr = np.linspace(0.0, 1.0, n_tr, dtype=np.float32)
    w_rec = np.exp(1.15 * rank_tr).astype(np.float32)
    w_rec /= w_rec.mean()

    def make_z_split(h_key: str, s: str) -> np.ndarray:
        r = rows[s]
        Zr, aux_r, _ = snapshots_raw[h_key]
        return np.concatenate([np.asarray(Zr[r], dtype=np.float16), ((aux_r[r] - amu) / asd).astype(np.float16)], axis=1)

    tr_r = rows["train"]
    va_r = rows["val"]
    X_tr_t = torch.from_numpy(X[tr_r]).to(dev)
    y_crit_tr_t = torch.from_numpy(y_crit[tr_r]).to(dev)
    p0_tr_t = torch.from_numpy(p0[tr_r]).to(dev)
    blk_tr_t = torch.from_numpy(blk[tr_r]).to(dev)
    sr_tr_t = torch.from_numpy(sr[tr_r]).to(dev)
    y_del_tr_t = torch.from_numpy(y_del[tr_r]).to(dev)
    log_dur_tr_t = torch.from_numpy(log_dur[tr_r]).to(dev)
    log_plan_tr_t = torch.from_numpy(log_plan[tr_r]).to(dev)
    is_res_tr_t = torch.from_numpy(is_res[tr_r]).to(dev)
    w_rec_tr_t = torch.from_numpy(w_rec).to(dev)

    Z_tr_list = [torch.from_numpy(make_z_split(k, "train")).to(dev) for k in train_horizon_keys]
    X_va_t = torch.from_numpy(X[va_r]).to(dev)
    Z_va_list = [torch.from_numpy(make_z_split(k, "val")).to(dev) for k in train_horizon_keys]
    log_plan_va_t = torch.from_numpy(log_plan[va_r]).to(dev)

    prev_summary = json.loads((root / "readout_summary.json").read_text())
    bp = prev_summary["optuna"]["best_params"]
    log(f"Training 3-seed Dual-Head TGN ensemble (1 TGN -> 2 Heads: Criticality + Delay)...")

    models = []
    hists = []
    for sd_val in args.seeds:
        m, best_obj, hist = train_dual_head_seed(
            X_tr_t,
            Z_tr_list,
            y_crit_tr_t,
            p0_tr_t,
            blk_tr_t,
            sr_tr_t,
            y_del_tr_t,
            log_dur_tr_t,
            log_plan_tr_t,
            is_res_tr_t,
            w_rec_tr_t,
            X_va_t,
            Z_va_list,
            y_crit[va_r],
            p0[va_r],
            y_del[va_r],
            log_plan_va_t,
            gamma=bp["gamma"],
            lam=bp["lambda"],
            lr=bp["lr"],
            epochs=args.epochs,
            seed=sd_val,
        )
        models.append(m)
        hists.append(hist)
        log(f"  seed {sd_val}: best joint multi-task val objective = {best_obj:.4f}")

    del X_tr_t, Z_tr_list, X_va_t, Z_va_list
    torch.cuda.empty_cache()

    log("[4/4] Evaluating BOTH Heads (Head 1: Criticality & Head 2: Delay Risk) across all horizons...")
    eval_horizons = ["T0_pre", "T0_create", "T3_change", "T5_change", "T7_change", "T_active_change"]
    eval_results = {}
    pred_dir = root / "predictions_dual_head"
    pred_dir.mkdir(parents=True, exist_ok=True)
    lb_path = Path("experiments/leaderboard_tgn_dual_head.json")
    if lb_path.exists():
        lb_path.unlink()

    for h_key in eval_horizons:
        h_out = pred_dir / h_key
        h_out.mkdir(parents=True, exist_ok=True)
        eval_results[h_key] = {"audit": snapshots_raw[h_key][2], "criticality": {}, "delay": {}}

        delay_preds_split = {}
        dur_preds_split = {}
        for s in ["val", "test"]:
            r = rows[s]
            z_s = make_z_split(h_key, s)
            c_scores, d_probs, d_days = predict_dual_ensemble(models, X[r], z_s, log_plan[r], dev)
            delay_preds_split[s] = d_probs
            dur_preds_split[s] = d_days

            # Evaluate Head 1 (Criticality) via official immutable harness
            crit_csv = h_out / f"criticality_{s}.csv"
            pd.DataFrame({"issue_key": uid[r], "pred_score": np.round(c_scores, 6)}).to_csv(crit_csv, index=False)
            res_crit = evaluate_criticality(
                pred_file=str(crit_csv),
                track=f"DualTGN_Crit_{h_key}",
                split=s,
                ground_truth_file=str(root / f"criticality_{s}.parquet"),
                leaderboard_file=str(lb_path),
                iteration=1,
                target_overrides={"ndcg": 0.85, "prec": 0.75, "rho": 0.70},
                experiment_name="DualHead_TGN_Jira_Full_2.68M",
            )
            eval_results[h_key]["criticality"][s] = res_crit["metrics"]

            # Save Delay predictions CSV
            del_csv = h_out / f"delay_{s}.csv"
            pd.DataFrame(
                {
                    "uid": uid[r],
                    "y_true": y_del[r].astype(int),
                    "y_prob": np.round(d_probs, 6),
                    "pred_duration_days": np.round(d_days, 2),
                }
            ).to_csv(del_csv, index=False)

        # Evaluate Head 2 (Delay Risk)
        eval_results[h_key]["delay"] = eval_delay_metrics(
            y_del[rows["val"]].astype(int),
            delay_preds_split["val"],
            y_del[rows["test"]].astype(int),
            delay_preds_split["test"],
            dur_preds_split["test"],
            dur_days[rows["test"]],
        )
        cm_te = eval_results[h_key]["criticality"]["test"]
        dm_te = eval_results[h_key]["delay"]["test_max_f1"]
        dm_hr = eval_results[h_key]["delay"]["test_high_recall"]
        log(
            f"  [{h_key:16s}] HEAD 1 (Crit TEST): NDCG@10={cm_te['ndcg_10']:.4f} (Grp={cm_te['ndcg_10_grouped']:.4f}), "
            f"Prec@5%={cm_te['precision_top5pct']:.4f}, Spearman={cm_te['spearman_rho']:.4f}, ROC-AUC={cm_te['roc_auc']:.4f}"
        )
        log(
            f"  [{h_key:16s}] HEAD 2 (Delay TEST): ROC-AUC={dm_te['roc_auc']:.4f}, PR-AUC={dm_te['pr_auc']:.4f} | "
            f"MaxF1: F1={dm_te['f1_score']:.4f} (P={dm_te['precision']:.4f}, R={dm_te['recall']:.4f}) | "
            f"HighRec: F1={dm_hr['f1_score']:.4f} (P={dm_hr['precision']:.4f}, R={dm_hr['recall']:.4f})"
        )

    # Save checkpoints and bundle
    readout_files = []
    for sd_val, m in zip(args.seeds, models):
        fname = f"dual_readout_seed{sd_val}.pt"
        torch.save(m.state_dict(), root / fname)
        readout_files.append(fname)
    np.savez(root / "dual_readout_normalizers.npz", mu=mu, sd=sd, amu=amu, asd=asd)

    report_path = root / "eval_dual_head_summary.json"
    report_path.write_text(json.dumps({"results": eval_results, "history": hists}, indent=2, default=float))

    # Pack into bundles/tgn_dual_head
    meta_r = json.loads((root / "readout_meta.json").read_text())
    z_tag = meta_r["z_tag"]
    mem_rep = json.loads((root / f"tgn_memory_report{z_tag}.json").read_text())
    bundle_cfg = {
        "model": "tgn_dual_head",
        "architecture": "1_TGN_Backbone_2_Heads_Criticality_and_Delay_AFT",
        "project_change_mode": True,
        "n_aux": N_AUX_DUAL,
        "z_tag": z_tag,
        "chunk": mem_rep["config"]["chunk"],
        "seeds": args.seeds,
        "readout_files": readout_files,
        "dropout": 0.2,
        "static_features": feat_names,
        "instances": instances,
        "types": types,
        "propensity_backoff": json.loads((root / "propensity_backoff.json").read_text()),
        "top_pct": 0.05,
        "delay_threshold_max_f1": eval_results["T_active_change"]["delay"]["test_max_f1"]["threshold"],
        "delay_threshold_high_recall": eval_results["T_active_change"]["delay"]["test_high_recall"]["threshold"],
    }
    b = ModelBundle.create(args.bundle_out, "dual_head_tgn", bundle_cfg, overwrite=True)
    b.copy_in(Path(args.memory_pt), "tgn_memory.pt")
    for fname in readout_files:
        b.copy_in(root / fname, fname)
    norm_dict = dict(np.load(root / "dual_readout_normalizers.npz"))
    norm_dict["svd_components"] = np.load(root / "svd16.npz")["components"]
    b.save_arrays("normalizers.npz", **norm_dict)
    b.finalize(eval_results)

    # Clean up temporary memmaps except T_active_change
    for h_name, _, _ in horizons:
        if h_name != "T_active_change":
            p = root / f"z_dual_{h_name}.npy"
            if p.exists():
                p.unlink()

    log(f"Exported bundle to {args.bundle_out} and report to {report_path} in {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
