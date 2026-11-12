"""Linear probe of the raw TGN memory snapshot: how much T0 signal does z carry on its own?

Fits a logistic regression on z (train sample) and reports val AP for the future-blocker flag and
P0, so memory variants (epochs, chunk size) can be compared without running the full readout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score, roc_auc_score


def probe(root: Path, n_train: int = 400_000, seed: int = 0, tag: str = "") -> dict:
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    df = pd.read_parquet(root / "issues_t0.parquet", columns=["split", "is_blocker_final", "is_critical_p0"])
    Z = np.load(root / f"z_raw_all{tag}.npy", mmap_mode="r")
    aux = np.load(root / f"z_aux_all{tag}.npy")
    rng = np.random.default_rng(seed)
    tr = np.sort(rng.choice(np.flatnonzero(df.split.values == "train"), n_train, replace=False))
    va = np.flatnonzero(df.split.values == "val")

    def feats(r):
        return torch.from_numpy(np.concatenate([np.asarray(Z[r], np.float32), aux[r]], 1)).to(dev)

    xtr, xva = feats(tr), feats(va)
    mu, sd = xtr.mean(0), xtr.std(0) + 1e-6
    xtr, xva = (xtr - mu) / sd, (xva - mu) / sd
    out = {}
    for target in ["is_blocker_final", "is_critical_p0"]:
        y = torch.from_numpy(df[target].values[tr].astype(np.float32)).to(dev)
        w = torch.zeros(xtr.shape[1], device=dev, requires_grad=True)
        b = torch.zeros(1, device=dev, requires_grad=True)
        opt = torch.optim.LBFGS([w, b], max_iter=200)

        def closure():
            opt.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(xtr @ w + b, y) + 1e-4 * (w ** 2).sum()
            loss.backward()
            return loss

        opt.step(closure)
        s = (xva @ w + b).detach().cpu().numpy()
        yv = df[target].values[va]
        out[target] = {"val_ap": round(float(average_precision_score(yv, s)), 4),
                       "val_auc": round(float(roc_auc_score(yv, s)), 4), "base_rate": round(float(yv.mean()), 4)}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data/tgn_full")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    res = probe(Path(a.data_dir), tag=a.tag)
    print(json.dumps({"tag": a.tag, **res}))
