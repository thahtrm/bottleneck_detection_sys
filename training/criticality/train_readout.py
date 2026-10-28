"""Stage 4 — Readout head on [z_i(T0) || x_static] with the Bipartite Ranking-Aware Margin Loss,
plus the Static-GBDT baseline and ablations. Writes harness-ready prediction CSVs.

Models (all fitted on TRAIN only; VAL used for early stopping / Optuna; TEST touched once):
  gbdt_static        LightGBM regressor on the T0 static features
  mlp_static         readout MLP on static features only (hybrid loss)
  tgn_mse            TGN readout, lambda = 0 (pointwise MSE only)
  tgn_hybrid         TGN readout, MSE + lambda * pairwise margin (gamma*, lambda* from Optuna)
Readout (early_risk_detection.criticality.readout):
          z = Linear(4*128 + 5 -> 128)(memory snapshot)   (TGN embedding module, 128d z_i(T0))
          Linear(In,128) -> BatchNorm1d -> ReLU -> Dropout(0.2) -> Linear(128,64) -> ReLU -> Linear(64,1) -> Sigmoid
Also saves what the CriticalityScorer needs (every tgn_hybrid seed, normalisers, issuetype /
instance lists); export_bundle.py packs them with the TGN memory into a model bundle.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
import torch
import torch.nn.functional as F
from scipy.stats import spearmanr

from early_risk_detection._logging import setup_logging
from early_risk_detection.criticality.readout import Readout, static_matrix

log = logging.getLogger(__name__).info


def quick_metrics(y: np.ndarray, p0: np.ndarray, s: np.ndarray) -> dict:
    k = int(np.ceil(0.05 * len(s)))
    top = np.argsort(s)[-k:]
    top10 = np.argsort(s)[-10:]
    ideal = np.sort(y)[-10:][::-1]
    disc = 1.0 / np.log2(np.arange(2, 12))
    ndcg10 = float(np.sum(y[top10][np.argsort(-s[top10])] * disc) / np.sum(ideal * disc))
    return {"prec5": float(p0[top].mean()), "spearman": float(spearmanr(s, y).statistic), "ndcg10": ndcg10}


def hybrid_loss(pred, y, p0, gamma: float, lam: float, n_pairs: int = 500, gen=None):
    l_mse = F.mse_loss(pred, y)
    if lam <= 0:
        return l_mse
    pos, neg = pred[p0 > 0.5], pred[p0 < 0.5]
    if len(pos) == 0 or len(neg) == 0:
        return l_mse
    ns = min(n_pairs, len(pos) * len(neg))
    ip = torch.randint(0, len(pos), (ns,), device=pred.device, generator=gen)
    ineg = torch.randint(0, len(neg), (ns,), device=pred.device, generator=gen)
    return l_mse + lam * F.relu(gamma - (pos[ip] - neg[ineg])).mean()


class Data:
    """All tensors resident on GPU (static fp32, memory snapshot fp16)."""

    def __init__(self, root: Path, dev: torch.device, z_tag: str = ""):
        df = pd.read_parquet(root / "issues_t0.parquet")
        self.instances = sorted(df["instance"].unique())
        self.types = types = df.loc[df["split"] == "train", "issuetype_t0"].value_counts().index[:30].tolist()
        X, self.names = static_matrix(df, self.instances, types)
        self.split = df["split"].values
        self.uid = (df["instance"] + "|" + df["issue_key"]).values
        self.inst = df["instance"].values
        y = df["ground_truth_criticality"].values.astype(np.float32)
        blk = df["is_blocker_final"].values.astype(np.float32)
        sr = (np.clip(df["slippage_days"].values / df["planned_duration_days"].values, 0, 3) / 3.0).astype(np.float32)
        p0 = df["is_critical_p0"].values.astype(np.float32)
        Zr = np.load(root / f"z_raw_all{z_tag}.npy", mmap_mode="r")
        aux = np.load(root / f"z_aux_all{z_tag}.npy")
        tr = self.split == "train"
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
        X = (X - mu) / sd
        amu, asd = aux[tr].mean(0), aux[tr].std(0) + 1e-6
        self.rows, self.t = {}, {}
        for s in ["train", "val", "test"]:
            r = np.flatnonzero(self.split == s)
            self.rows[s] = r
            z = np.concatenate([np.asarray(Zr[r]), ((aux[r] - amu) / asd).astype(np.float16)], 1)
            self.t[s] = {"x": torch.from_numpy(X[r]).to(dev), "z": torch.from_numpy(z).to(dev),
                         "y": torch.from_numpy(y[r]).to(dev), "p0": torch.from_numpy(p0[r]).to(dev),
                         "blk": torch.from_numpy(blk[r]).to(dev), "sr": torch.from_numpy(sr[r]).to(dev)}
        self.X, self.y, self.p0 = X, y, p0
        self.norm = {"mu": mu, "sd": sd, "amu": amu, "asd": asd}
        self.dev = dev


def train_readout(data: Data, use_z: bool, gamma: float, lam: float, lr: float, epochs: int, seed: int,
                  frac: float = 1.0, batch: int = 2048, dropout: float = 0.2, aux_w: float = 0.0):
    torch.manual_seed(seed)
    gen = torch.Generator(device=data.dev).manual_seed(seed)
    tr = data.t["train"]
    n = len(tr["y"])
    idx_all = torch.arange(n, device=data.dev)
    if frac < 1.0:
        idx_all = idx_all[torch.randperm(n, device=data.dev, generator=gen)[: int(frac * n)]]
    model = Readout(tr["x"].shape[1], use_z, dropout=dropout).to(data.dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    best, best_state, hist = -1.0, None, []
    for ep in range(epochs):
        model.train()
        perm = idx_all[torch.randperm(len(idx_all), device=data.dev, generator=gen)]
        tot = 0.0
        for b in range(0, len(perm), batch):
            i = perm[b:b + batch]
            if len(i) < 2:
                continue
            pred, aux = model(tr["x"][i], tr["z"][i].float() if use_z else None, with_aux=True)
            loss = hybrid_loss(pred, tr["y"][i], tr["p0"][i], gamma, lam, gen=gen)
            if aux_w > 0:
                loss = loss + aux_w * (F.binary_cross_entropy_with_logits(aux[:, 0], tr["blk"][i])
                                       + F.mse_loss(torch.sigmoid(aux[:, 1]), tr["sr"][i]))
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * len(i)
        sch.step()
        vs = predict(model, data, "val", use_z)
        m = quick_metrics(data.y[data.rows["val"]], data.p0[data.rows["val"]], vs)
        score = 0.5 * m["prec5"] + 0.5 * m["spearman"]
        hist.append({"epoch": ep + 1, "train_loss": tot / len(perm), **{f"val_{k}": v for k, v in m.items()}})
        if score > best:
            best, best_state = score, {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model, best, hist


@torch.no_grad()
def predict(model: Readout, data: Data, split: str, use_z: bool) -> np.ndarray:
    model.eval()
    t = data.t[split]
    out = [model(t["x"][b:b + 65536], t["z"][b:b + 65536].float() if use_z else None)
           for b in range(0, len(t["y"]), 65536)]
    return torch.cat(out).cpu().numpy()


@torch.no_grad()
def export_z(model: Readout, data: Data, out: Path) -> None:
    model.eval()
    for s in ["train", "val", "test"]:
        z = data.t[s]["z"]
        zz = torch.cat([model.z(z[b:b + 65536].float()) for b in range(0, len(z), 65536)]).half().cpu().numpy()
        np.save(out / f"z_tgn_{s}.npy", zz)
        log(f"  saved z_tgn_{s}.npy {zz.shape}")


def write_preds(data: Data, name: str, preds: dict, out: Path) -> None:
    d = out / "predictions" / name
    d.mkdir(parents=True, exist_ok=True)
    for s, p in preds.items():
        pd.DataFrame({"issue_key": data.uid[data.rows[s]], "pred_score": np.round(p, 6)}).to_csv(
            d / f"predictions_{s}.csv", index=False)


def memory_pca(data: Data, k: int = 32, seed: int = 0) -> dict[str, np.ndarray]:
    """Unsupervised PCA of the raw TGN memory snapshot (fitted on a train sample only)."""
    from sklearn.decomposition import PCA
    tr = data.t["train"]["z"]
    idx = torch.randperm(len(tr), generator=torch.Generator().manual_seed(seed))[:300_000].to(data.dev)
    pca = PCA(n_components=k, random_state=seed).fit(tr[idx].float().cpu().numpy())
    return {s: np.concatenate([pca.transform(data.t[s]["z"][b:b + 200_000].float().cpu().numpy())
                               for b in range(0, len(data.t[s]["z"]), 200_000)]).astype(np.float32)
            for s in ["train", "val", "test"]}


def run_gbdt(data: Data, seed: int, extra: dict[str, np.ndarray] | None = None, extra_names: list[str] | None = None):
    tr, va = data.rows["train"], data.rows["val"]
    X = {s: data.X[data.rows[s]] if extra is None else np.hstack([data.X[data.rows[s]], extra[s]])
         for s in ["train", "val", "test"]}
    if extra is not None and extra_names is None:
        extra_names = [f"tgn_pc{k}" for k in range(extra["train"].shape[1])]
    names = data.names + (extra_names or [])
    params = {"objective": "regression", "learning_rate": 0.05, "num_leaves": 127, "min_data_in_leaf": 200,
              "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
              "verbose": -1, "seed": seed, "num_threads": 14}
    dtr = lgb.Dataset(X["train"], data.y[tr], feature_name=names)
    dva = lgb.Dataset(X["val"], data.y[va], reference=dtr)
    m = lgb.train(params, dtr, 2000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    imp = sorted(zip(names, m.feature_importance("gain")), key=lambda t: -t[1])[:25]
    return {s: m.predict(X[s], num_iteration=m.best_iteration) for s in ["val", "test"]}, \
        {"best_iteration": m.best_iteration, "top_gain_features": [(n, float(g)) for n, g in imp]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data/tgn_full")
    ap.add_argument("--epochs", type=int, default=18)
    ap.add_argument("--trials", type=int, default=16)
    ap.add_argument("--seeds", type=int, nargs="+", default=[45, 47, 49])
    ap.add_argument("--z_tag", default="", help="which TGN memory snapshot (train_tgn.py --tag)")
    ap.add_argument("--models", nargs="+", default=["gbdt_static", "gbdt_tgn", "mlp_static", "tgn_mse", "tgn_hybrid"])
    ap.add_argument("--params_from", default=None,
                    help="readout_summary.json of an earlier run: reuse its Optuna best params, skip the search")
    args = ap.parse_args()
    setup_logging()
    root = Path(args.data_dir)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    t0 = time.time()
    data = Data(root, dev, args.z_tag)
    log(f"Loaded data: static {data.X.shape[1]} features, z {tuple(data.t['train']['z'].shape)} | "
        + ", ".join(f"{s} {len(r):,}" for s, r in data.rows.items()))
    summary = {"static_features": data.names, "z_tag": args.z_tag}
    np.savez(root / "readout_normalizers.npz", **data.norm)
    (root / "readout_meta.json").write_text(json.dumps(
        {"static_features": data.names, "instances": data.instances, "types": data.types,
         "z_tag": args.z_tag, "seeds": args.seeds}, indent=2))

    if "gbdt_static" in args.models:
        log("[A] Static GBDT baseline (LightGBM)...")
        g_preds, g_info = run_gbdt(data, 42)
        write_preds(data, "gbdt_static", g_preds, root)
        summary["gbdt_static"] = {**g_info, "val": quick_metrics(data.y[data.rows["val"]], data.p0[data.rows["val"]], g_preds["val"])}
        log(f"  GBDT val {summary['gbdt_static']['val']}")
    if "gbdt_tgn" in args.models:
        log("[A2] GBDT on static + PCA-32 of the TGN memory snapshot...")
        t_preds, t_info = run_gbdt(data, 42, extra=memory_pca(data))
        write_preds(data, "gbdt_tgn", t_preds, root)
        summary["gbdt_tgn"] = {**t_info, "val": quick_metrics(data.y[data.rows["val"]], data.p0[data.rows["val"]], t_preds["val"])}
        log(f"  GBDT+TGN val {summary['gbdt_tgn']['val']}")

    if args.params_from:
        bp = json.loads(Path(args.params_from).read_text())["optuna"]["best_params"]
        summary["optuna"] = {"best_params": bp, "reused_from": args.params_from}
        log(f"[B] reusing Optuna best params {bp} from {args.params_from}")
    else:
        log(f"[B] Optuna search for gamma*, lambda*, lr ({args.trials} trials, 35% train subsample, 6 epochs)...")

        def objective(trial):
            g = trial.suggest_float("gamma", 0.05, 0.40)
            lam = trial.suggest_float("lambda", 0.0, 1.5)
            lr = trial.suggest_float("lr", 3e-4, 3e-3, log=True)
            aux_w = trial.suggest_float("aux_w", 0.0, 1.0)
            _, score, _ = train_readout(data, True, g, lam, lr, epochs=6, seed=7, frac=0.35, aux_w=aux_w)
            return score

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.enqueue_trial({"gamma": 0.15, "lambda": 0.20, "lr": 1e-3, "aux_w": 0.0})  # prompt defaults
        study.enqueue_trial({"gamma": 0.15, "lambda": 0.0, "lr": 1e-3, "aux_w": 0.0})   # pure MSE reference
        study.enqueue_trial({"gamma": 0.15, "lambda": 0.20, "lr": 1e-3, "aux_w": 0.5})
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study.optimize(objective, n_trials=args.trials)
        bp = study.best_params
        summary["optuna"] = {"best_params": bp, "best_val_objective": study.best_value,
                             "trials": [{"params": t.params, "value": t.value} for t in study.trials]}
        log(f"  best {bp} -> val objective {study.best_value:.4f}")

    configs = {
        "mlp_static": dict(use_z=False, gamma=bp["gamma"], lam=bp["lambda"], lr=bp["lr"], aux_w=bp["aux_w"]),
        "tgn_mse": dict(use_z=True, gamma=bp["gamma"], lam=0.0, lr=bp["lr"], aux_w=bp["aux_w"]),
        "tgn_hybrid": dict(use_z=True, gamma=bp["gamma"], lam=bp["lambda"], lr=bp["lr"], aux_w=bp["aux_w"]),
    }
    for name, cfg in configs.items():
        if name not in args.models:
            continue
        log(f"[C] {name}: {len(args.seeds)}-seed ensemble, {args.epochs} epochs, {cfg}")
        vals, tests, hists = [], [], []
        for sd in args.seeds:
            m, best, hist = train_readout(data, cfg["use_z"], cfg["gamma"], cfg["lam"], cfg["lr"], args.epochs, sd,
                                          aux_w=cfg["aux_w"])
            vals.append(predict(m, data, "val", cfg["use_z"]))
            tests.append(predict(m, data, "test", cfg["use_z"]))
            hists.append(hist)
            log(f"    seed {sd}: best val objective {best:.4f}")
            if name == "tgn_hybrid":
                torch.save(m.state_dict(), root / f"readout_tgn_hybrid_seed{sd}.pt")
                if sd == args.seeds[0]:
                    export_z(m, data, root)
        preds = {"val": np.mean(vals, 0), "test": np.mean(tests, 0)}
        write_preds(data, name, preds, root)
        summary[name] = {"config": cfg, "history": hists,
                         "val": quick_metrics(data.y[data.rows["val"]], data.p0[data.rows["val"]], preds["val"])}
        log(f"  {name} val {summary[name]['val']}")
    sp = root / "readout_summary.json"
    if sp.exists() and set(args.models) != {"gbdt_static", "gbdt_tgn", "mlp_static", "tgn_mse", "tgn_hybrid"}:
        summary = {**json.loads(sp.read_text()), **summary}  # partial re-run: keep the other models' entries
    sp.write_text(json.dumps(summary, indent=2, default=float))
    log(f"Done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
