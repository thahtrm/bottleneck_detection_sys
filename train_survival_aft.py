"""TRACK 2: Pipeline Survival Analysis Accelerated Failure Time (AFT) với Right-Censored Data thực tế.

Mô hình hóa thời gian hoàn thành task T:
    ln(T) = beta^T X + sigma * W
với W ~ Logistic, Normal, hoặc Extreme distribution.

Xử lý Right-Censoring:
- Issue đã đóng: y_lower = y_upper = duration_days.
- Issue đang mở: y_lower = (T_cutoff - T_create) / 86400.0, y_upper = inf.

Quy đổi sang xác suất trễ hạn tại hạn mức planned_duration_days (t_planned):
    P(Delay) = P(T > t_planned) = S(t_planned)
    với z = (ln(t_planned) - ln(T_hat)) / sigma:
    - Logistic: P(Delay) = expit(-z) = 1 / (1 + exp(z))
    - Normal:   P(Delay) = norm.cdf(-z)
    - Extreme:  P(Delay) = exp(-exp(z))
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import time
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from scipy.special import expit
from scipy.stats import norm
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
import xgboost as xgb

from evaluation_harness import evaluate_predictions, find_optimal_threshold
from train_xgboost import extract_all_features

optuna.logging.set_verbosity(optuna.logging.WARNING)


def compute_survival_prob(
    pred_time: np.ndarray,
    planned_time: np.ndarray,
    distribution: str,
    scale: float,
) -> np.ndarray:
    """Tính xác suất trễ hạn P(T > planned_time) từ thời gian dự đoán pred_time của XGBoost AFT."""
    pred_time = np.maximum(1e-3, pred_time)
    planned_time = np.maximum(1e-3, planned_time)
    scale = max(1e-3, scale)

    z = (np.log(planned_time) - np.log(pred_time)) / scale
    z = np.clip(z, -30.0, 30.0)

    if distribution == "logistic":
        prob = expit(-z)
    elif distribution == "normal":
        prob = norm.cdf(-z)
    elif distribution == "extreme":
        prob = np.exp(-np.exp(z))
    else:
        prob = expit(-z)

    return np.clip(prob, 1e-6, 1.0 - 1e-6)


def train_and_evaluate_survival_aft(
    train_file: str = "data/train_censored.parquet",
    val_file: str = "data/val_censored.parquet",
    test_file: str = "data/test_censored.parquet",
    n_trials: int = 35,
    seed: int = 42,
    output_dir: str = "experiments/survival_aft",
):
    print("=================================================================", flush=True)
    print("⏳ TRACK 2: TRAINING SURVIVAL ACCELERATED FAILURE TIME (AFT) MODEL", flush=True)
    print(f"  • Train dataset: {train_file}", flush=True)
    print(f"  • Val dataset:   {val_file}", flush=True)
    print(f"  • Test dataset:  {test_file}", flush=True)
    print(f"  • Optuna trials: {n_trials}", flush=True)
    print("=================================================================", flush=True)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_parquet(train_file)
    val_df = pd.read_parquet(val_file)
    test_df = pd.read_parquet(test_file)

    n_res_tr = int((train_df["is_resolved"] == 1).sum())
    n_cens_tr = int((train_df["is_resolved"] == 0).sum())
    print(f"[Data] Train: {len(train_df):,} rows (Resolved: {n_res_tr:,}, Right-Censored: {n_cens_tr:,})", flush=True)
    print(f"[Data] Val:   {len(val_df):,} rows | Test: {len(test_df):,} rows", flush=True)

    y_lower_tr = train_df["lower_bound"].values.astype(np.float32)
    y_upper_tr = train_df["upper_bound"].values.astype(np.float32)
    is_cens_tr = (train_df["is_resolved"].values == 0)
    created_ts_tr = train_df["created_ts"].values.astype(np.float64)

    y_lower_va = val_df["lower_bound"].values.astype(np.float32)
    y_upper_va = val_df["upper_bound"].values.astype(np.float32)
    y_val_true = val_df["is_delayed"].values.astype(np.int32)
    val_planned = val_df["planned_duration_days"].values.astype(np.float32)

    y_lower_te = test_df["lower_bound"].values.astype(np.float32)
    y_upper_te = test_df["upper_bound"].values.astype(np.float32)
    y_test_true = test_df["is_delayed"].values.astype(np.int32)
    test_planned = test_df["planned_duration_days"].values.astype(np.float32)

    X_train_raw, X_val_raw, X_test_raw = extract_all_features(train_df, val_df, test_df, seed=seed)
    del train_df, val_df, test_df
    gc.collect()

    drop_cols = {"row_id", "issue_key", "summary", "is_delayed", "lower_bound", "upper_bound", "is_resolved", "duration_days", "resolution"}
    feature_cols = [c for c in X_train_raw.columns if c not in drop_cols]
    X_train = X_train_raw[feature_cols]
    X_val = X_val_raw[feature_cols]
    X_test = X_test_raw[feature_cols]
    print(f"[Features] Input feature matrix dimension: {X_train.shape[1]} float32 features.", flush=True)

    max_train_ts = float(created_ts_tr.max())
    age_days_full = ((max_train_ts - created_ts_tr) / 86400.0).astype(np.float32)

    # Tạo tập con đại diện theo thời gian cho Optuna (250K Train, 80K Val) để tái sử dụng DMatrix siêu tốc
    if len(X_train) > 250000:
        step_tr = len(X_train) / 250000.0
        opt_tr_idx = np.unique((np.arange(250000) * step_tr).astype(np.int64))
    else:
        opt_tr_idx = np.arange(len(X_train))

    if len(X_val) > 80000:
        step_va = len(X_val) / 80000.0
        opt_va_idx = np.unique((np.arange(80000) * step_va).astype(np.int64))
    else:
        opt_va_idx = np.arange(len(X_val))

    dtrain_opt = xgb.DMatrix(X_train.iloc[opt_tr_idx])
    dtrain_opt.set_float_info("label_lower_bound", y_lower_tr[opt_tr_idx])
    dtrain_opt.set_float_info("label_upper_bound", y_upper_tr[opt_tr_idx])
    age_days_opt = age_days_full[opt_tr_idx]
    is_cens_opt = is_cens_tr[opt_tr_idx]

    dval_opt = xgb.DMatrix(X_val.iloc[opt_va_idx])
    dval_opt.set_float_info("label_lower_bound", y_lower_va[opt_va_idx])
    dval_opt.set_float_info("label_upper_bound", y_upper_va[opt_va_idx])
    y_val_opt = y_val_true[opt_va_idx]
    val_planned_opt = val_planned[opt_va_idx]

    print(f"\n[Optuna] Searching best Survival AFT hyperparameters ({n_trials} trials)...", flush=True)

    def objective(trial: optuna.Trial) -> float:
        dist = trial.suggest_categorical("aft_loss_distribution", ["logistic", "normal"])
        scale = trial.suggest_float("aft_loss_distribution_scale", 0.5, 3.5, step=0.1)
        max_depth = trial.suggest_int("max_depth", 4, 8)
        learning_rate = trial.suggest_float("learning_rate", 0.02, 0.15, log=True)
        min_child_weight = trial.suggest_float("min_child_weight", 2.0, 25.0)
        subsample = trial.suggest_float("subsample", 0.65, 1.0, step=0.05)
        colsample_bytree = trial.suggest_float("colsample_bytree", 0.55, 1.0, step=0.05)
        reg_alpha = trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True)
        reg_lambda = trial.suggest_float("reg_lambda", 1e-2, 15.0, log=True)
        half_life = trial.suggest_float("half_life_days", 365.0, 3650.0, log=True)
        censored_boost = trial.suggest_float("censored_weight_boost", 0.8, 2.5)

        lam = float(np.log(2.0) / half_life)
        weights = np.exp(-lam * age_days_opt).astype(np.float32)
        weights = weights / np.mean(weights)
        weights[is_cens_opt] *= censored_boost
        dtrain_opt.set_weight(weights)

        params = {
            "objective": "survival:aft",
            "eval_metric": "aft-nloglik",
            "aft_loss_distribution": dist,
            "aft_loss_distribution_scale": scale,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "min_child_weight": min_child_weight,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
            "reg_alpha": reg_alpha,
            "reg_lambda": reg_lambda,
            "random_state": seed,
            "tree_method": "hist",
            "nthread": 8,
        }

        bst = xgb.train(
            params,
            dtrain_opt,
            num_boost_round=400,
            evals=[(dval_opt, "val")],
            early_stopping_rounds=30,
            verbose_eval=False,
        )

        pred_time_val = bst.predict(dval_opt)
        val_prob = compute_survival_prob(pred_time_val, val_planned_opt, dist, scale)
        _, best_val_f1, _, _ = find_optimal_threshold(y_val_opt, val_prob)
        return float(best_val_f1)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    print(f"\n[Optuna] Best Trial Val F1: {study.best_value:.4f}", flush=True)
    print(f"[Optuna] Best Hyperparameters: {best_params}", flush=True)

    del dtrain_opt, dval_opt
    gc.collect()

    # Huấn luyện mô hình cuối cùng trên TOÀN BỘ tập Train Censored
    best_dist = best_params["aft_loss_distribution"]
    best_scale = best_params["aft_loss_distribution_scale"]
    best_half_life = best_params["half_life_days"]
    best_cens_boost = best_params["censored_weight_boost"]

    lam = float(np.log(2.0) / best_half_life)
    final_weights = np.exp(-lam * age_days_full).astype(np.float32)
    final_weights = final_weights / np.mean(final_weights)
    final_weights[is_cens_tr] *= best_cens_boost

    print(f"\n[Training] Fitting Final Survival AFT Model on full Train Censored ({len(X_train):,} rows)...", flush=True)
    dtrain_final = xgb.DMatrix(X_train)
    dtrain_final.set_float_info("label_lower_bound", y_lower_tr)
    dtrain_final.set_float_info("label_upper_bound", y_upper_tr)
    dtrain_final.set_weight(final_weights)

    dval_full = xgb.DMatrix(X_val)
    dval_full.set_float_info("label_lower_bound", y_lower_va)
    dval_full.set_float_info("label_upper_bound", y_upper_va)

    final_xgb_params = {
        "objective": "survival:aft",
        "eval_metric": "aft-nloglik",
        "aft_loss_distribution": best_dist,
        "aft_loss_distribution_scale": best_scale,
        "max_depth": best_params["max_depth"],
        "learning_rate": best_params["learning_rate"],
        "min_child_weight": best_params["min_child_weight"],
        "subsample": best_params["subsample"],
        "colsample_bytree": best_params["colsample_bytree"],
        "reg_alpha": best_params["reg_alpha"],
        "reg_lambda": best_params["reg_lambda"],
        "random_state": seed,
        "tree_method": "hist",
        "nthread": 12,
    }

    final_bst = xgb.train(
        final_xgb_params,
        dtrain_final,
        num_boost_round=650,
        evals=[(dval_full, "val")],
        early_stopping_rounds=40,
        verbose_eval=False,
    )

    pred_time_val = final_bst.predict(dval_full)
    val_probs = compute_survival_prob(pred_time_val, val_planned, best_dist, best_scale)
    del dtrain_final, dval_full
    gc.collect()

    dtest_full = xgb.DMatrix(X_test)
    pred_time_test = final_bst.predict(dtest_full)
    test_probs = compute_survival_prob(pred_time_test, test_planned, best_dist, best_scale)
    del dtest_full
    gc.collect()

    opt_thr, val_f1_opt, val_p, val_r = find_optimal_threshold(y_val_true, val_probs)
    test_preds = (test_probs >= opt_thr).astype(int)
    test_f1 = float(f1_score(y_test_true, test_preds, zero_division=0))
    test_prec = float(precision_score(y_test_true, test_preds, zero_division=0))
    test_rec = float(recall_score(y_test_true, test_preds, zero_division=0))
    test_pr_auc = float(average_precision_score(y_test_true, test_probs))
    test_roc_auc = float(roc_auc_score(y_test_true, test_probs))
    test_brier = float(brier_score_loss(y_test_true, test_probs))

    val_pred_path = out_path / "predictions_val.csv"
    test_pred_path = out_path / "predictions_test.csv"
    pd.DataFrame({"y_true": y_val_true, "y_prob": val_probs, "pred_time": pred_time_val}).to_csv(val_pred_path, index=False)
    pd.DataFrame({"y_true": y_test_true, "y_prob": test_probs, "pred_time": pred_time_test}).to_csv(test_pred_path, index=False)

    summary_metrics = {
        "distribution": best_dist,
        "scale": best_scale,
        "optimal_threshold": opt_thr,
        "val_f1": val_f1_opt,
        "test_f1": test_f1,
        "test_precision": test_prec,
        "test_recall": test_rec,
        "test_pr_auc": test_pr_auc,
        "test_roc_auc": test_roc_auc,
        "test_brier": test_brier,
        "best_hyperparameters": best_params,
        "train_samples": int(len(X_train)),
        "censored_samples": n_cens_tr,
    }
    with open(out_path / "aft_metrics.json", "w") as f:
        json.dump(summary_metrics, f, indent=2)

    evaluate_predictions(
        test_pred_path=str(test_pred_path),
        val_pred_path=str(val_pred_path),
        track="survival_aft",
    )
    return summary_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost Survival AFT with Right-Censored Data (Track 2).")
    parser.add_argument("--train-file", type=str, default="data/train_censored.parquet")
    parser.add_argument("--val-file", type=str, default="data/val_censored.parquet")
    parser.add_argument("--test-file", type=str, default="data/test_censored.parquet")
    parser.add_argument("--trials", type=int, default=35)
    parser.add_argument("--output-dir", type=str, default="experiments/survival_aft")
    args = parser.parse_args()

    train_and_evaluate_survival_aft(
        train_file=args.train_file,
        val_file=args.val_file,
        test_file=args.test_file,
        n_trials=args.trials,
        output_dir=args.output_dir,
    )
