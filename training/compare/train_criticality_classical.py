"""Criticality LR/RF/XGB: regress ground_truth_criticality then rank (Q5=A).

Uses static T0 features from issues_t0 (+ optional as-of tabular). No TGN z.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from early_risk_detection.criticality.readout import static_matrix
from early_risk_detection.evaluation.multihead_compare import (
    criticality_entry,
    evaluate_criticality_pred,
    upsert_leaderboard,
)


def repo_tip() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/tgn_full_v2")
    ap.add_argument("--model", choices=["xgb", "rf", "logreg"], required=True)
    ap.add_argument("--snapshot", default="T0_pre")
    ap.add_argument("--asof-parquet", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--leaderboard", default="experiments/leaderboard_multihead_vs_classical.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    root = Path(args.data_dir)
    out = Path(args.output_dir or f"experiments/compare/crit_{args.model}_{args.snapshot}")
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(root / "issues_t0.parquet")
    instances = sorted(df["instance"].unique())
    types = df.loc[df["split"] == "train", "issuetype_t0"].value_counts().index[:30].tolist()
    X, names = static_matrix(df, instances, types)
    y = df["ground_truth_criticality"].values.astype(np.float32)
    uid = (df["instance"].astype(str) + "|" + df["issue_key"].astype(str)).values
    split = df["split"].values

    if args.asof_parquet:
        asof = pd.read_parquet(args.asof_parquet)
        # asof rows follow issues_t0 row order when built by build_snapshot_asof_features
        feat_cols = [c for c in asof.columns if c not in ("uid", "split")]
        # align by uid to be safe
        base = pd.DataFrame({"uid": uid})
        m = base.merge(asof[["uid"] + feat_cols], on="uid", how="left").fillna(0.0)
        X = np.concatenate([X, m[feat_cols].values.astype(np.float32)], axis=1)

    tr = split == "train"
    va = split == "val"
    te = split == "test"
    X_tr, y_tr = X[tr], y[tr]

    print(f"[crit/{args.model}/{args.snapshot}] train {X_tr.shape}")
    if args.model == "xgb":
        model = xgb.XGBRegressor(
            n_estimators=400,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.7,
            tree_method="hist",
            random_state=args.seed,
            n_jobs=8,
            objective="reg:squarederror",
        )
        model.fit(X_tr, y_tr, eval_set=[(X[va], y[va])], verbose=False)
        pred = model.predict
    elif args.model == "rf":
        rng = np.random.default_rng(args.seed)
        n = len(y_tr)
        if n > 300_000:
            idx = rng.choice(n, size=300_000, replace=False)
            X_fit, y_fit = X_tr[idx], y_tr[idx]
        else:
            X_fit, y_fit = X_tr, y_tr
        model = RandomForestRegressor(
            n_estimators=120,
            max_depth=18,
            min_samples_leaf=20,
            n_jobs=8,
            random_state=args.seed,
        )
        model.fit(X_fit, y_fit)
        pred = model.predict
    else:
        pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("reg", Ridge(alpha=1.0, random_state=args.seed)),
            ]
        )
        rng = np.random.default_rng(args.seed)
        n = len(y_tr)
        if n > 400_000:
            idx = rng.choice(n, size=400_000, replace=False)
            pipe.fit(X_tr[idx], y_tr[idx])
        else:
            pipe.fit(X_tr, y_tr)
        model = pipe
        pred = model.predict

    scores_te = pred(X[te])
    pred_csv = out / "criticality_test.csv"
    # evaluate_criticality expects issue_key column; harness joins on issue_key — Dual-Head uses uid-like keys
    # Existing dual CSVs use issue_key = "Instance|KEY"
    pd.DataFrame({"issue_key": uid[te], "pred_score": scores_te}).to_csv(pred_csv, index=False)
    pd.DataFrame({"issue_key": uid[va], "pred_score": pred(X[va])}).to_csv(out / "criticality_val.csv", index=False)

    res = evaluate_criticality_pred(
        pred_csv,
        root / "criticality_test.parquet",
        track=f"ClassicalCrit_{args.model}_{args.snapshot}",
        leaderboard_file="experiments/leaderboard_multihead_crit_scratch.json",
    )
    entry = criticality_entry(
        model=args.model if args.model != "logreg" else "logreg",
        snapshot=args.snapshot,
        crit_metrics=res["metrics"],
        repo_tip=repo_tip(),
        seed=args.seed,
        notes="regress GT criticality then rank; static T0" + (" + asof" if args.asof_parquet else ""),
    )
    upsert_leaderboard(args.leaderboard, [entry])
    m = res["metrics"]
    print(
        f"DONE crit {args.model}@{args.snapshot} "
        f"NDCG-g={m.get('ndcg_10_global')} NDCG-grp={m.get('ndcg_10_grouped')} P@5%={m.get('precision_top5pct')}"
    )


if __name__ == "__main__":
    main()
