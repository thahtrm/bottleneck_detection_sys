"""Train and evaluate TGN Criticality Readout on continuous Project-Change Snapshots.

Unlike Stage 3/4 which only froze memory strictly before T0 (leaving the issue's own 128-d TGN
memory s_issue(T0) == 0), this pipeline snapshots TGNMemory at project/issue change timestamps
t_change in [T0, T_resolved - 1s) while the issue is open (excluding closing status events
scat == 0), and trains a unified multi-snapshot Readout ensemble (seeds 45, 47, 49) that can
score open tasks at ANY point when the project has an update (T0, T3, T5, T7, or active change).
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
import torch.nn.functional as F

from early_risk_detection._logging import setup_logging
from early_risk_detection.criticality.memory import (
    MEM,
    EventStream,
    load_memory,
    snapshot_memory_at_change,
)
from early_risk_detection.criticality.readout import Readout, predict_scores, static_matrix
from early_risk_detection.criticality.stream import load_neighbours
from early_risk_detection.evaluation import evaluate_criticality
from training.criticality.train_readout import hybrid_loss, quick_metrics

log = logging.getLogger(__name__).info


def compute_change_timestamps(
    created: np.ndarray,
    end_ts: np.ndarray,
    ts: np.ndarray,
    u_id: np.ndarray,
    v_id: np.ndarray,
    kind: np.ndarray,
    scat: np.ndarray,
    horizon_days: float | None,
) -> np.ndarray:
    """Return the latest active (non-closing) event timestamp per issue within ``horizon_days`` of T0."""
    n = len(created)
    t_snap = np.copy(created)
    if horizon_days is not None and horizon_days <= 0.0:
        return t_snap
    not_done = scat != 0
    max_open_u = end_ts[u_id] - 1.0
    if horizon_days is not None:
        max_open_u = np.minimum(max_open_u, created[u_id] + horizon_days * 86400.0)
    m_u = not_done & (ts >= created[u_id]) & (ts <= max_open_u)
    np.maximum.at(t_snap, u_id[m_u], ts[m_u])

    v_in = (kind == 4) & (v_id < n)
    v_safe = np.minimum(v_id, n - 1)
    max_open_v = end_ts[v_safe] - 1.0
    if horizon_days is not None:
        max_open_v = np.minimum(max_open_v, created[v_safe] + horizon_days * 86400.0)
    m_v = v_in & (ts >= created[v_safe]) & (ts <= max_open_v)
    np.maximum.at(t_snap, v_id[m_v], ts[m_v])
    return t_snap


def train_multi_snapshot_readout(
    X_tr: torch.Tensor,
    Z_tr_list: list[torch.Tensor],
    y_tr: torch.Tensor,
    p0_tr: torch.Tensor,
    blk_tr: torch.Tensor,
    sr_tr: torch.Tensor,
    X_va: torch.Tensor,
    Z_va_list: list[torch.Tensor],
    y_va: np.ndarray,
    p0_va: np.ndarray,
    gamma: float,
    lam: float,
    lr: float,
    epochs: int,
    seed: int,
    aux_w: float = 0.25,
    batch: int = 2048,
    dropout: float = 0.2,
):
    dev = X_tr.device
    torch.manual_seed(seed)
    gen = torch.Generator(device=dev).manual_seed(seed)
    n = len(y_tr)
    n_horizons = len(Z_tr_list)
    model = Readout(X_tr.shape[1], use_z=True, dropout=dropout).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    best, best_state, hist = -1.0, None, []

    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n, device=dev, generator=gen)
        # Randomly assign each issue in this epoch to one of the project-change snapshots (T0, T3, T7, Active)
        h_choice = torch.randint(0, n_horizons, (n,), device=dev, generator=gen)
        tot = 0.0
        for b in range(0, n, batch):
            i = perm[b : b + batch]
            if len(i) < 2:
                continue
            hc = h_choice[i]
            z_batch = torch.empty((len(i), Z_tr_list[0].shape[1]), dtype=torch.float32, device=dev)
            for h_idx in range(n_horizons):
                m = hc == h_idx
                if m.any():
                    z_batch[m] = Z_tr_list[h_idx][i[m]].float()
            pred, aux = model(X_tr[i], z_batch, with_aux=True)
            loss = hybrid_loss(pred, y_tr[i], p0_tr[i], gamma, lam, gen=gen)
            if aux_w > 0:
                loss = loss + aux_w * (
                    F.binary_cross_entropy_with_logits(aux[:, 0], blk_tr[i])
                    + F.mse_loss(torch.sigmoid(aux[:, 1]), sr_tr[i])
                )
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * len(i)
        sch.step()

        model.eval()
        val_objs = []
        val_metrics_per_h = {}
        with torch.no_grad():
            for h_idx, z_va in enumerate(Z_va_list):
                outs = [
                    model(X_va[b : b + 65536], z_va[b : b + 65536].float())
                    for b in range(0, len(X_va), 65536)
                ]
                vs = torch.cat(outs).cpu().numpy()
                m = quick_metrics(y_va, p0_va, vs)
                val_metrics_per_h[f"h{h_idx}"] = m
                val_objs.append(0.5 * m["prec5"] + 0.5 * m["spearman"])
        score = float(np.mean(val_objs))
        hist.append({"epoch": ep + 1, "train_loss": tot / n, "val_mean_obj": score, **val_metrics_per_h})
        if score > best:
            best = score
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model, best, hist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data/tgn_full_v2")
    ap.add_argument("--memory_pt", default="data/tgn_full_v2/tgn_memory_lr5e-4_e2_s45.pt")
    ap.add_argument("--t0_tag", default="_lr5e-4_e2_s45")
    ap.add_argument("--epochs", type=int, default=18)
    ap.add_argument("--seeds", type=int, nargs="+", default=[45, 47, 49])
    ap.add_argument("--bundle_out", default="bundles/criticality_project_change")
    args = ap.parse_args()

    setup_logging()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    root = Path(args.data_dir)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    t_start = time.time()

    log("[1/4] Loading issues_t0 and event stream metadata...")
    df = pd.read_parquet(root / "issues_t0.parquet")
    meta = json.loads((root / "events/meta.json").read_text())
    created = df["created_ts"].values.astype(np.float64)
    end_ts = created + df["duration_days"].values.astype(np.float64) * 86400.0
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

    horizons = {
        "T0_create": 0.0,
        "T3_change": 3.0,
        "T5_change": 5.0,
        "T7_change": 7.0,
        "T_active_change": None,
    }

    log("[2/4] Extracting leak-free Project-Change TGN snapshots across horizons...")
    snapshots_raw: dict[str, tuple[np.ndarray, np.ndarray, dict]] = {}
    # Also load original pre-T0 snapshot for reference
    z_pre_t0 = np.load(root / f"z_raw_all{args.t0_tag}.npy", mmap_mode="r")
    aux_pre_t0 = np.load(root / f"z_aux_all{args.t0_tag}.npy")
    snapshots_raw["T0_pre"] = (
        z_pre_t0,
        aux_pre_t0,
        {"nonzero_own_memory_rate": float((np.abs(z_pre_t0[:, :MEM].astype(np.float32)).sum(1) > 0).mean())},
    )

    for h_name, h_days in horizons.items():
        t_snap = compute_change_timestamps(created, end_ts, ts, u_id, v_id, kind, scat, h_days)
        z_path = root / f"z_raw_pc_{h_name}.npy"
        Z_h = np.lib.format.open_memmap(z_path, mode="w+", dtype=np.float16, shape=(len(df), 4 * MEM))
        Z_h, aux_h, applied_last = snapshot_memory_at_change(tgn_model, stream, t_snap, neigh, z_out=Z_h)
        Z_h.flush()
        np.save(root / f"z_aux_pc_{h_name}.npy", aux_h)
        Z_h_ro = np.load(z_path, mmap_mode="r")
        viol_snap = int((applied_last > t_snap).sum())
        viol_end = int((applied_last >= end_ts).sum())
        nz_rate = float((np.abs(Z_h_ro[:, :MEM].astype(np.float32)).sum(1) > 0).mean())
        upd_after_t0 = float((t_snap > created).mean())
        assert viol_snap == 0 and viol_end == 0, f"Leakage violation in {h_name}: {viol_snap}, {viol_end}"
        audit_h = {
            "horizon_days": h_days,
            "nonzero_own_memory_rate": nz_rate,
            "updated_after_T0_rate": upd_after_t0,
            "violations_gt_t_snap": viol_snap,
            "violations_ge_end_ts": viol_end,
        }
        log(f"  {h_name:16s}: own_mem!=0 {nz_rate:.2%} | updated>T0 {upd_after_t0:.2%} | leakage=0")
        snapshots_raw[h_name] = (Z_h_ro, aux_h, audit_h)

    del tgn_model
    torch.cuda.empty_cache()

    log("[3/4] Preparing static matrix and multi-snapshot training tensors...")
    instances = sorted(df["instance"].unique())
    types = df.loc[split == "train", "issuetype_t0"].value_counts().index[:30].tolist()
    X, feat_names = static_matrix(df, instances, types)
    tr_mask = split == "train"
    mu, sd = X[tr_mask].mean(0), X[tr_mask].std(0) + 1e-6
    X = ((X - mu) / sd).astype(np.float32)

    # Fit aux normalizer across train snapshots of [T0_pre, T3_change, T7_change, T_active_change]
    train_horizon_keys = ["T0_pre", "T3_change", "T7_change", "T_active_change"]
    aux_concat = np.concatenate([snapshots_raw[k][1][tr_mask] for k in train_horizon_keys], axis=0)
    amu, asd = aux_concat.mean(0), aux_concat.std(0) + 1e-6

    rows = {s: np.flatnonzero(split == s) for s in ["train", "val", "test"]}
    y = df["ground_truth_criticality"].values.astype(np.float32)
    p0 = df["is_critical_p0"].values.astype(np.float32)
    blk = df["is_blocker_final"].values.astype(np.float32)
    sr = (np.clip(df["slippage_days"].values / df["planned_duration_days"].values, 0, 3) / 3.0).astype(np.float32)

    def make_z_split(h_key: str, s: str) -> np.ndarray:
        r = rows[s]
        Zr, aux_r, _ = snapshots_raw[h_key]
        return np.concatenate([np.asarray(Zr[r], dtype=np.float16), ((aux_r[r] - amu) / asd).astype(np.float16)], axis=1)

    X_tr_t = torch.from_numpy(X[rows["train"]]).to(dev)
    y_tr_t = torch.from_numpy(y[rows["train"]]).to(dev)
    p0_tr_t = torch.from_numpy(p0[rows["train"]]).to(dev)
    blk_tr_t = torch.from_numpy(blk[rows["train"]]).to(dev)
    sr_tr_t = torch.from_numpy(sr[rows["train"]]).to(dev)

    Z_tr_list = [torch.from_numpy(make_z_split(k, "train")).to(dev) for k in train_horizon_keys]
    X_va_t = torch.from_numpy(X[rows["val"]]).to(dev)
    Z_va_list = [torch.from_numpy(make_z_split(k, "val")).to(dev) for k in ["T0_pre", "T3_change", "T7_change", "T_active_change"]]

    # Reuse best hyperparameters from readout_summary.json
    prev_summary = json.loads((root / "readout_summary.json").read_text())
    bp = prev_summary["optuna"]["best_params"]
    log(f"Training 3-seed Multi-Snapshot Readout ensemble with params: {bp}")

    models = []
    hists = []
    for sd_val in args.seeds:
        m, best_obj, hist = train_multi_snapshot_readout(
            X_tr_t,
            Z_tr_list,
            y_tr_t,
            p0_tr_t,
            blk_tr_t,
            sr_tr_t,
            X_va_t,
            Z_va_list,
            y[rows["val"]],
            p0[rows["val"]],
            gamma=bp["gamma"],
            lam=bp["lambda"],
            lr=bp["lr"],
            epochs=args.epochs,
            seed=sd_val,
            aux_w=bp["aux_w"],
        )
        models.append(m)
        hists.append(hist)
        log(f"  seed {sd_val}: best multi-horizon val objective = {best_obj:.4f}")

    # Free train tensors from GPU before full evaluation
    del X_tr_t, Z_tr_list, X_va_t, Z_va_list
    torch.cuda.empty_cache()

    log("[4/4] Evaluating across all project-change horizons on VAL and TEST...")
    eval_horizons = ["T0_pre", "T0_create", "T3_change", "T5_change", "T7_change", "T_active_change"]
    eval_results = {}
    pred_dir = root / "predictions_project_change"
    pred_dir.mkdir(parents=True, exist_ok=True)
    lb_path = Path("experiments/leaderboard_tgn_project_change.json")
    if lb_path.exists():
        lb_path.unlink()

    for h_key in eval_horizons:
        h_out = pred_dir / h_key
        h_out.mkdir(parents=True, exist_ok=True)
        eval_results[h_key] = {"audit": snapshots_raw[h_key][2]}
        for s in ["val", "test"]:
            r = rows[s]
            z_s = make_z_split(h_key, s)
            preds = predict_scores(models, X[r], z_s, dev)
            csv_path = h_out / f"predictions_{s}.csv"
            pd.DataFrame({"issue_key": uid[r], "pred_score": np.round(preds, 6)}).to_csv(csv_path, index=False)
            res = evaluate_criticality(
                pred_file=str(csv_path),
                track=f"TGN_ProjectChange_{h_key}",
                split=s,
                ground_truth_file=str(root / f"criticality_{s}.parquet"),
                leaderboard_file=str(lb_path),
                iteration=1,
                target_overrides={"ndcg": 0.85, "prec": 0.75, "rho": 0.70},
                experiment_name="Task_Criticality_Project_Change_2.68M",
            )
            eval_results[h_key][s] = res["metrics"]
        log(
            f"  [{h_key:16s}] VAL: NDCG@10={eval_results[h_key]['val']['ndcg_10']:.4f}, "
            f"Prec@5%={eval_results[h_key]['val']['precision_top5pct']:.4f}, "
            f"Spearman={eval_results[h_key]['val']['spearman_rho']:.4f}, "
            f"ROC-AUC={eval_results[h_key]['val']['roc_auc']:.4f} | "
            f"TEST: NDCG@10={eval_results[h_key]['test']['ndcg_10']:.4f}, "
            f"Prec@5%={eval_results[h_key]['test']['precision_top5pct']:.4f}, "
            f"Spearman={eval_results[h_key]['test']['spearman_rho']:.4f}, "
            f"ROC-AUC={eval_results[h_key]['test']['roc_auc']:.4f}"
        )

    # Save weights and summary report
    for sd_val, m in zip(args.seeds, models):
        torch.save(m.state_dict(), root / f"readout_project_change_seed{sd_val}.pt")
    np.savez(root / "readout_project_change_normalizers.npz", mu=mu, sd=sd, amu=amu, asd=asd)

    report_path = root / "eval_project_change_summary.json"
    report_path.write_text(json.dumps({"results": eval_results, "optuna_params": bp}, indent=2, default=float))
    log(f"Saved complete evaluation report to {report_path} in {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
