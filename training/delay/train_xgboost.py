"""Delay model component 1 — XGBoost binary classifier (5-fold ensemble) on T0 features.

Reads the matrices of build_dataset.py, tunes with Optuna (TimeSeriesSplit, PR-AUC) unless
--params_from is given, saves the fold models to the staging bundle and writes
predictions_{val,test}.csv (uid, y_true, y_prob).
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit

from early_risk_detection._logging import setup_logging
from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.scorer import KIND
from early_risk_detection.evaluation import evaluate_predictions

log = logging.getLogger(__name__).info
optuna.logging.set_verbosity(optuna.logging.WARNING)


def optimize_hyperparameters(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    created_ts: np.ndarray,
    n_trials: int = 35,
    seed: int = 42,
) -> tuple[dict, float]:
    """Tối ưu hóa siêu tham số Bayesian bằng Optuna (TimeSeriesSplit)."""
    log(f"\n[Optuna] Starting Bayesian Hyperparameter Optimization ({n_trials} trials)...")

    # Nếu tập Train quá lớn (>250K dòng), lấy mẫu phân tầng theo trật tự thời gian để tuning nhanh & chuẩn xác
    if len(X_train) > 250000:
        step = len(X_train) / 250000.0
        sub_idx = np.unique((np.arange(250000) * step).astype(np.int64))
        X_opt = X_train.iloc[sub_idx].reset_index(drop=True)
        y_opt = y_train[sub_idx]
        ts_opt = created_ts[sub_idx]
        n_splits = 3
    else:
        X_opt = X_train
        y_opt = y_train
        ts_opt = created_ts
        n_splits = 5

    tscv = TimeSeriesSplit(n_splits=n_splits)
    default_scale_pos = float((len(y_opt) - y_opt.sum()) / max(1, y_opt.sum()))
    ts_norm = (ts_opt - ts_opt.min()) / (ts_opt.max() - ts_opt.min() + 1e-4)

    def objective(trial: optuna.Trial) -> float:
        recency_alpha = trial.suggest_float("recency_alpha", 0.0, 1.5)
        sw = np.exp(recency_alpha * ts_norm).astype(np.float32)
        sw = sw / sw.mean()

        params = {
            "n_estimators": trial.suggest_int("n_estimators", 120, 260, step=20),
            "max_depth": trial.suggest_int("max_depth", 4, 7),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10, log=True),
            "subsample": trial.suggest_float("subsample", 0.70, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.55, 0.85),
            "colsample_bylevel": trial.suggest_float("colsample_bylevel", 0.65, 0.95),
            "min_child_weight": trial.suggest_int("min_child_weight", 4, 20),
            "gamma": trial.suggest_float("gamma", 0.0, 2.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-2, 5.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 15.0, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.80 * default_scale_pos, 1.25 * default_scale_pos),
            "tree_method": "hist",
            "random_state": seed,
            "n_jobs": 8,
            "eval_metric": "logloss",
        }

        pr_auc_scores = []
        for tr_idx, va_idx in tscv.split(X_opt):
            X_tr, y_tr = X_opt.iloc[tr_idx], y_opt[tr_idx]
            X_va, y_va = X_opt.iloc[va_idx], y_opt[va_idx]
            sw_tr = sw[tr_idx]

            clf = xgb.XGBClassifier(**params)
            clf.fit(X_tr, y_tr, sample_weight=sw_tr)
            preds_prob = clf.predict_proba(X_va)[:, 1]
            score = average_precision_score(y_va, preds_prob)
            pr_auc_scores.append(score)

        return float(np.mean(pr_auc_scores))

    def print_callback(study: optuna.Study, trial: optuna.Trial):
        if (trial.number + 1) % 5 == 0 or trial.number == 0:
            log(
                f"  [Optuna Trial {trial.number + 1:2d}/{n_trials}] PR-AUC: {trial.value:.4f} "
                f"(Best so far: {study.best_value:.4f})"
            )

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, callbacks=[print_callback])

    best_trial = study.best_trial
    best_recency_alpha = best_trial.params.pop("recency_alpha", 0.0)
    best_params = best_trial.params

    log(f"\n[Optuna] Optimization finished! Best Mean PR-AUC: {study.best_value:.4f}")
    return best_params, best_recency_alpha


def compute_shap_analysis(
    models: list[xgb.XGBClassifier],
    X_val: pd.DataFrame,
    out_path: str = "experiments/xgboost/shap_summary.json",
    top_k: int = 10,
) -> list[dict]:
    """Tính toán SHAP values trên mẫu đại diện của validation set và lưu Top 10 đặc trưng quan trọng nhất."""
    if len(X_val) > 10000:
        X_shap = X_val.sample(n=10000, random_state=42)
    else:
        X_shap = X_val

    log(f"\n[SHAP] Computing SHAP values across ensemble ({len(X_shap):,} samples)...")
    all_shap = []
    for model in models:
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_shap)
        all_shap.append(np.abs(shap_vals))

    mean_abs_shap = np.mean(np.mean(all_shap, axis=0), axis=0)
    feat_names = list(X_val.columns)

    shap_df = pd.DataFrame({
        "feature": feat_names,
        "mean_abs_shap": [float(v) for v in mean_abs_shap],
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    top_features = shap_df.head(top_k).to_dict(orient="records")

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(top_features, f, indent=2, ensure_ascii=False)

    log(f"[SHAP] Top {top_k} features saved to {out_file.resolve()}:")
    for rank, item in enumerate(top_features, 1):
        log(f"  {rank:2d}. {item['feature']:35s} : {item['mean_abs_shap']:.5f}")

    return top_features


def main():
    parser = argparse.ArgumentParser(description="Train the XGBoost component of the delay model")
    parser.add_argument("--data-dir", type=str, default="data/delay_t0")
    parser.add_argument("--stage", type=str, default="bundles/staging/delay")
    parser.add_argument("--output-dir", type=str, default="experiments/delay_t0/xgboost")
    parser.add_argument("--leaderboard", type=str, default="experiments/leaderboard_delay_t0.json")
    parser.add_argument("--n-trials", type=int, default=35)
    parser.add_argument("--params-from", type=str, default=None, help="xgb_params.json of an earlier run")
    parser.add_argument("--no-shap", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    setup_logging()
    d, out_path = Path(args.data_dir), Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    stage = ModelBundle.staging(args.stage, KIND)

    lab = {s: pd.read_parquet(d / f"{s}_labels.parquet") for s in ["train", "val", "test"]}
    X_train, X_val, X_test = (pd.read_parquet(d / f"X_xgb_{s}.parquet") for s in ["train", "val", "test"])
    y_train = lab["train"]["is_delayed"].values.astype(np.int32)
    created_ts_tr = lab["train"]["created_ts"].values
    log(f"[Data] Train {X_train.shape}, Val {X_val.shape}, Test {X_test.shape}")

    if args.params_from:
        p = json.loads(Path(args.params_from).read_text())
        best_params, best_recency_alpha = p["params"], p["recency_alpha"]
    else:
        best_params, best_recency_alpha = optimize_hyperparameters(
            X_train, y_train, created_ts_tr, n_trials=args.n_trials, seed=args.seed)
    (out_path / "xgb_params.json").write_text(json.dumps({"params": best_params, "recency_alpha": best_recency_alpha}, indent=2))
    best_params = {**best_params, "tree_method": "hist", "random_state": args.seed, "n_jobs": -1, "eval_metric": "logloss"}

    ts_norm = (created_ts_tr - created_ts_tr.min()) / (created_ts_tr.max() - created_ts_tr.min() + 1e-4)
    sample_weights = np.exp(best_recency_alpha * ts_norm).astype(np.float32)
    sample_weights = sample_weights / sample_weights.mean()

    log(f"[Training] 5-fold stratified XGBoost ensemble on {len(X_train):,} rows...")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    models = []
    probs = {"val": np.zeros(len(X_val)), "test": np.zeros(len(X_test))}
    for fold, (tr_idx, _) in enumerate(skf.split(np.zeros(len(y_train)), y_train)):
        clf = xgb.XGBClassifier(**{**best_params, "random_state": args.seed + fold})
        clf.fit(X_train.iloc[tr_idx], y_train[tr_idx], sample_weight=sample_weights[tr_idx])
        clf.save_model(stage.file(f"xgb_fold{fold}.ubj"))
        models.append(clf)
        probs["val"] += clf.predict_proba(X_val)[:, 1] / 5.0
        probs["test"] += clf.predict_proba(X_test)[:, 1] / 5.0
        log(f"  fold {fold} done")
    for s in ["val", "test"]:
        pd.DataFrame({"uid": lab[s]["uid"], "y_true": lab[s]["is_delayed"], "y_prob": probs[s]}).to_csv(
            out_path / f"predictions_{s}.csv", index=False)
    if not args.no_shap:
        compute_shap_analysis(models, X_val, out_path=str(out_path / "shap_summary.json"), top_k=10)
    evaluate_predictions(test_pred_path=str(out_path / "predictions_test.csv"),
                         val_pred_path=str(out_path / "predictions_val.csv"), track="xgboost_t0",
                         leaderboard_path=args.leaderboard)


if __name__ == "__main__":
    main()
