"""Duration regressors (XGB/RF/LR) on resolved issues for delay MAE (Q4=A)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def load_split(data_dir: Path, split: str, asof: Path | None):
    X = pd.read_parquet(data_dir / f"X_xgb_{split}.parquet")
    lab = pd.read_parquet(data_dir / f"{split}_labels.parquet")
    if asof is not None:
        a = pd.read_parquet(asof)
        m = lab[["uid"]].merge(a.drop(columns=["split"], errors="ignore"), on="uid", how="left")
        cols = [c for c in m.columns if c != "uid"]
        X = pd.concat([X.reset_index(drop=True), m[cols].reset_index(drop=True)], axis=1).fillna(0.0)
    y = lab["duration_days"].values.astype(np.float64)
    mask = lab["is_resolved"].values.astype(int) == 1
    return X, y, mask, lab["uid"].values


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/delay_t0")
    ap.add_argument("--model", choices=["xgb", "rf", "logreg"], required=True)
    ap.add_argument("--snapshot", default="T0_pre")
    ap.add_argument("--asof-parquet", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out = Path(args.output_dir or f"experiments/compare/duration_{args.model}_{args.snapshot}")
    out.mkdir(parents=True, exist_ok=True)
    asof = Path(args.asof_parquet) if args.asof_parquet else None

    X_tr, y_tr, m_tr, uid_tr = load_split(Path(args.data_dir), "train", asof)
    X_va, y_va, m_va, uid_va = load_split(Path(args.data_dir), "val", asof)
    X_te, y_te, m_te, uid_te = load_split(Path(args.data_dir), "test", asof)

    X_fit, y_fit = X_tr.loc[m_tr], y_tr[m_tr]
    print(f"[duration/{args.model}] fit on {len(y_fit):,} resolved train rows, feats={X_fit.shape[1]}")

    if args.model == "xgb":
        model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.7,
            tree_method="hist",
            random_state=args.seed,
            n_jobs=8,
            objective="reg:absoluteerror",
        )
        model.fit(X_fit, y_fit)
    elif args.model == "rf":
        rng = np.random.default_rng(args.seed)
        if len(y_fit) > 300_000:
            idx = rng.choice(len(y_fit), size=300_000, replace=False)
            X_fit, y_fit = X_fit.iloc[idx], y_fit[idx]
        model = RandomForestRegressor(
            n_estimators=100,
            max_depth=18,
            min_samples_leaf=20,
            n_jobs=8,
            random_state=args.seed,
        )
        model.fit(X_fit.fillna(0.0), y_fit)
    else:
        pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("reg", Ridge(alpha=1.0, random_state=args.seed)),
            ]
        )
        rng = np.random.default_rng(args.seed)
        if len(y_fit) > 400_000:
            idx = rng.choice(len(y_fit), size=400_000, replace=False)
            pipe.fit(X_fit.iloc[idx], y_fit[idx])
        else:
            pipe.fit(X_fit, y_fit)
        model = pipe

    def pred(X):
        if args.model == "rf":
            return model.predict(X.fillna(0.0))
        return model.predict(X)

    for split, X, y, uid in [("val", X_va, y_va, uid_va), ("test", X_te, y_te, uid_te)]:
        yp = np.maximum(pred(X), 0.01)
        pd.DataFrame({"uid": uid, "y_true_duration": y, "y_pred_duration": yp}).to_csv(
            out / f"predictions_{split}.csv", index=False
        )
        err = np.abs(yp - y)
        print(f"  {split} MAE={err.mean():.3f} MedAE={np.median(err):.3f}")

    (out / "meta.json").write_text(
        json.dumps({"model": args.model, "snapshot": args.snapshot, "seed": args.seed}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
