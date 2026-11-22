"""Train delay LR / RF / XGB on shared X_xgb_* (+ optional as-of snapshot features).

Q3=A: shared 264-d X_xgb matrix. Post-T0: concatenate classical as-of tabular (not TGN z).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from early_risk_detection.evaluation.multihead_compare import (
    delay_entry,
    eval_delay_dual_protocol,
    upsert_leaderboard,
)


def repo_tip() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def load_xy(data_dir: Path, asof_path: Path | None) -> dict[str, dict]:
    out = {}
    for split in ["train", "val", "test"]:
        X = pd.read_parquet(data_dir / f"X_xgb_{split}.parquet")
        lab = pd.read_parquet(data_dir / f"{split}_labels.parquet")
        if asof_path is not None:
            asof = pd.read_parquet(asof_path)
            # align by uid
            merged = lab[["uid"]].merge(asof.drop(columns=["split"], errors="ignore"), on="uid", how="left")
            feat_cols = [c for c in merged.columns if c != "uid"]
            X = pd.concat([X.reset_index(drop=True), merged[feat_cols].reset_index(drop=True)], axis=1)
            X = X.fillna(0.0)
        out[split] = {
            "X": X,
            "y": lab["is_delayed"].values.astype(np.int32),
            "uid": lab["uid"].values,
            "duration": lab["duration_days"].values.astype(np.float64),
            "resolved": lab["is_resolved"].values.astype(np.int32) == 1,
        }
    return out


def train_model(kind: str, X_tr: pd.DataFrame, y_tr: np.ndarray, seed: int):
    if kind == "xgb":
        params_path = Path("experiments/delay_t0/xgboost/xgb_params.json")
        if params_path.exists():
            blob = json.loads(params_path.read_text())
            params = {**blob["params"], "tree_method": "hist", "random_state": seed, "n_jobs": 8, "eval_metric": "logloss"}
        else:
            params = {
                "n_estimators": 200,
                "max_depth": 6,
                "learning_rate": 0.05,
                "subsample": 0.8,
                "colsample_bytree": 0.7,
                "tree_method": "hist",
                "random_state": seed,
                "n_jobs": 8,
                "eval_metric": "logloss",
            }
        model = xgb.XGBClassifier(**params)
        model.fit(X_tr, y_tr)
        return model
    if kind == "rf":
        # Subsample for tractability on ~1.6M rows
        n = len(y_tr)
        rng = np.random.default_rng(seed)
        if n > 400_000:
            idx = rng.choice(n, size=400_000, replace=False)
            X_fit, y_fit = X_tr.iloc[idx], y_tr[idx]
        else:
            X_fit, y_fit = X_tr, y_tr
        model = RandomForestClassifier(
            n_estimators=120,
            max_depth=18,
            min_samples_leaf=20,
            class_weight="balanced_subsample",
            n_jobs=8,
            random_state=seed,
        )
        model.fit(X_fit.fillna(0.0), y_fit)
        return model
    if kind == "logreg":
        pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler(with_mean=True)),
                (
                    "clf",
                    LogisticRegression(
                        penalty="l2",
                        C=0.5,
                        max_iter=200,
                        class_weight="balanced",
                        solver="lbfgs",
                        random_state=seed,
                        n_jobs=8,
                    ),
                ),
            ]
        )
        # Subsample for LR speed/memory
        n = len(y_tr)
        rng = np.random.default_rng(seed)
        if n > 500_000:
            idx = rng.choice(n, size=500_000, replace=False)
            pipe.fit(X_tr.iloc[idx], y_tr[idx])
        else:
            pipe.fit(X_tr, y_tr)
        return pipe
    raise ValueError(kind)


def predict_proba(model, X: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X.fillna(0.0) if isinstance(model, RandomForestClassifier) else X)[:, 1]
    raise TypeError(type(model))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/delay_t0")
    ap.add_argument("--model", choices=["xgb", "rf", "logreg"], required=True)
    ap.add_argument("--snapshot", default="T0_pre")
    ap.add_argument("--asof-parquet", default=None, help="X_asof_<snap>.parquet; omit for pure T0")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--leaderboard", default="experiments/leaderboard_multihead_vs_classical.json")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--duration-pred-dir", default=None, help="optional dir with duration predictions_{val,test}.csv")
    args = ap.parse_args()

    out = Path(args.output_dir or f"experiments/compare/delay_{args.model}_{args.snapshot}")
    out.mkdir(parents=True, exist_ok=True)
    asof = Path(args.asof_parquet) if args.asof_parquet else None
    data = load_xy(Path(args.data_dir), asof)
    print(f"[delay/{args.model}/{args.snapshot}] train {data['train']['X'].shape}")

    model = train_model(args.model, data["train"]["X"], data["train"]["y"], args.seed)
    probs = {s: predict_proba(model, data[s]["X"]) for s in ["val", "test"]}
    for s in ["val", "test"]:
        pd.DataFrame({"uid": data[s]["uid"], "y_true": data[s]["y"], "y_prob": probs[s]}).to_csv(
            out / f"predictions_{s}.csv", index=False
        )

    pred_dur = true_dur = resolved = None
    if args.duration_pred_dir:
        ddir = Path(args.duration_pred_dir)
        dte = pd.read_csv(ddir / "predictions_test.csv")
        # align by uid
        te = pd.DataFrame({"uid": data["test"]["uid"]}).merge(dte, on="uid", how="left")
        pred_dur = te["y_pred_duration"].values.astype(np.float64)
        true_dur = data["test"]["duration"]
        resolved = data["test"]["resolved"]

    dmet = eval_delay_dual_protocol(
        data["val"]["y"],
        probs["val"],
        data["test"]["y"],
        probs["test"],
        pred_dur_test=pred_dur,
        true_dur_test=true_dur,
        resolved_mask_test=resolved,
    )
    (out / "metrics.json").write_text(json.dumps(dmet, indent=2), encoding="utf-8")
    entry = delay_entry(
        model=args.model if args.model != "logreg" else "logreg",
        snapshot=args.snapshot,
        delay_metrics=dmet,
        repo_tip=repo_tip(),
        seed=args.seed,
        notes=("shared X_xgb" + (" + asof tabular" if asof else "")),
    )
    upsert_leaderboard(args.leaderboard, [entry])
    print(
        f"DONE {args.model}@{args.snapshot} ROC={dmet['test_primary']['roc_auc']:.4f} "
        f"PR={dmet['test_primary']['pr_auc']:.4f} R={dmet['test_primary']['recall']:.4f} MAE={dmet['mae']}"
    )


if __name__ == "__main__":
    main()
