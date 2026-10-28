"""TRACK 4: Pipeline CatBoost Cox Proportional Hazards với Right-Censored Data & Breslow Estimator.

Mô hình hóa tỷ lệ rủi ro (Hazard Rate):
    h(t | X) = h_0(t) * exp(beta^T X) = h_0(t) * exp(eta)
Target 1D cho CatBoost Cox:
    y = +duration nếu issue đã đóng (Event = 1)
    y = -duration nếu issue chưa đóng (Censored = 0)

Ước lượng Baseline Cumulative Hazard H_0(t) bằng thuật toán Breslow không tham số:
    H_0(t) = sum_{u_k <= t, E_k = 1} [ 1 / sum_{j in R(u_k)} exp(eta_j) ]

Xác suất trễ hạn tại hạn mức planned_duration_days (t_planned):
    P(Delay) = S(t_planned | X) = exp( - H_0(t_planned) * exp(eta) )
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostRegressor, Pool
from evaluation_harness import evaluate_predictions, find_optimal_threshold
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from train_xgboost import extract_all_features

optuna.logging.set_verbosity(optuna.logging.WARNING)


def fit_breslow_estimator(
    durations: np.ndarray,
    events: np.ndarray,
    risk_scores: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Ước lượng hàm rủi ro tích lũy cơ sở Breslow H_0(t) với độ phức tạp O(N log N)."""
    order = np.argsort(durations, kind="mergesort")
    T_sorted = durations[order]
    E_sorted = events[order]
    eta_sorted = risk_scores[order]

    exp_eta = np.exp(np.clip(eta_sorted, -20.0, 20.0))
    denom = np.cumsum(exp_eta[::-1])[::-1]
    denom = np.maximum(1e-8, denom)

    dh0 = np.where(E_sorted == 1, 1.0 / denom, 0.0)
    H0 = np.cumsum(dh0)
    return T_sorted, H0


def predict_cox_survival_prob(
    T_sorted: np.ndarray,
    H0: np.ndarray,
    query_planned_times: np.ndarray,
    query_risk_scores: np.ndarray,
) -> np.ndarray:
    """Tính xác suất trễ hạn S(t_planned | X) = exp(-H_0(t_planned) * exp(eta))."""
    indices = np.searchsorted(T_sorted, query_planned_times, side="right") - 1
    valid_mask = indices >= 0

    h0_values = np.zeros_like(query_planned_times, dtype=np.float64)
    h0_values[valid_mask] = H0[np.clip(indices[valid_mask], 0, len(H0) - 1)]

    exp_eta = np.exp(np.clip(query_risk_scores, -20.0, 20.0))
    cum_hazard = h0_values * exp_eta
    survival_prob = np.exp(-cum_hazard)
    return np.clip(survival_prob, 1e-6, 1.0 - 1e-6)


def train_and_evaluate_catboost_cox(
    train_file: str = "data/train_censored.parquet",
    val_file: str = "data/val_censored.parquet",
    test_file: str = "data/test_censored.parquet",
    n_trials: int = 35,
    seed: int = 42,
    output_dir: str = "experiments/catboost_cox",
):
    print("=================================================================", flush=True)
    print("🐆 TRACK 4: TRAINING CATBOOST COX PROPORTIONAL HAZARDS MODEL", flush=True)
    print(f"  • Train dataset: {train_file}", flush=True)
    print(f"  • Optuna trials: {n_trials}", flush=True)
    print("=================================================================", flush=True)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_parquet(train_file)
    val_df = pd.read_parquet(val_file)
    test_df = pd.read_parquet(test_file)

    train_dur = np.maximum(0.01, train_df["lower_bound"].values.astype(np.float32))
    train_ev = train_df["is_resolved"].values.astype(np.int32)
    y_train_cox = np.where(train_ev == 1, train_dur, -train_dur).astype(np.float32)
    created_ts_tr = train_df["created_ts"].values.astype(np.float64)

    val_dur = np.maximum(0.01, val_df["lower_bound"].values.astype(np.float32))
    val_ev = val_df["is_resolved"].values.astype(np.int32)
    y_val_cox = np.where(val_ev == 1, val_dur, -val_dur).astype(np.float32)

    y_val_true = val_df["is_delayed"].values.astype(np.int32)
    val_planned = val_df["planned_duration_days"].values.astype(np.float32)

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

    max_train_ts = float(created_ts_tr.max())
    age_days_full = ((max_train_ts - created_ts_tr) / 86400.0).astype(np.float32)

    if len(X_train) > 200000:
        step_tr = len(X_train) / 200000.0
        opt_tr_idx = np.unique((np.arange(200000) * step_tr).astype(np.int64))
    else:
        opt_tr_idx = np.arange(len(X_train))

    if len(X_val) > 80000:
        step_va = len(X_val) / 80000.0
        opt_va_idx = np.unique((np.arange(80000) * step_va).astype(np.int64))
    else:
        opt_va_idx = np.arange(len(X_val))

    X_tr_opt = X_train.iloc[opt_tr_idx]
    y_tr_cox_opt = y_train_cox[opt_tr_idx]
    dur_tr_opt = train_dur[opt_tr_idx]
    ev_tr_opt = train_ev[opt_tr_idx]
    age_opt = age_days_full[opt_tr_idx]

    X_va_opt = X_val.iloc[opt_va_idx]
    y_va_cox_opt = y_val_cox[opt_va_idx]
    y_va_true_opt = y_val_true[opt_va_idx]
    val_planned_opt = val_planned[opt_va_idx]
    val_pool_opt = Pool(X_va_opt, y_va_cox_opt)

    print(f"\n[Optuna] Searching best CatBoost Cox hyperparameters ({n_trials} trials)...", flush=True)

    def objective(trial: optuna.Trial) -> float:
        depth = trial.suggest_int("depth", 4, 8)
        learning_rate = trial.suggest_float("learning_rate", 0.03, 0.18, log=True)
        l2_leaf_reg = trial.suggest_float("l2_leaf_reg", 1.0, 20.0, log=True)
        random_strength = trial.suggest_float("random_strength", 0.1, 5.0)
        half_life = trial.suggest_float("half_life_days", 365.0, 3650.0, log=True)
        cens_boost = trial.suggest_float("censored_weight_boost", 0.8, 2.5)

        lam = float(np.log(2.0) / half_life)
        weights = np.exp(-lam * age_opt).astype(np.float32)
        weights = weights / np.mean(weights)
        weights[ev_tr_opt == 0] *= cens_boost

        train_pool_opt = Pool(X_tr_opt, y_tr_cox_opt, weight=weights)

        model = CatBoostRegressor(
            iterations=400,
            depth=depth,
            learning_rate=learning_rate,
            l2_leaf_reg=l2_leaf_reg,
            random_strength=random_strength,
            loss_function="Cox",
            thread_count=12,
            random_seed=seed,
            verbose=False,
        )
        model.fit(train_pool_opt, eval_set=val_pool_opt, early_stopping_rounds=30, verbose=False)

        eta_train = model.predict(X_tr_opt)
        T_sort, H0 = fit_breslow_estimator(dur_tr_opt, ev_tr_opt, eta_train)

        eta_val = model.predict(X_va_opt)
        val_prob = predict_cox_survival_prob(T_sort, H0, val_planned_opt, eta_val)
        _, best_val_f1, _, _ = find_optimal_threshold(y_va_true_opt, val_prob)
        return float(best_val_f1)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    print(f"\n[Optuna] Best CatBoost Cox Val F1: {study.best_value:.4f}", flush=True)
    print(f"[Optuna] Best Hyperparameters: {best_params}", flush=True)

    del X_tr_opt, X_va_opt, val_pool_opt
    gc.collect()

    best_half_life = best_params["half_life_days"]
    best_cens_boost = best_params["censored_weight_boost"]

    lam = float(np.log(2.0) / best_half_life)
    final_weights = np.exp(-lam * age_days_full).astype(np.float32)
    final_weights = final_weights / np.mean(final_weights)
    final_weights[train_ev == 0] *= best_cens_boost

    print(f"\n[Training] Fitting Final CatBoost Cox Model on full Train ({len(X_train):,} rows)...", flush=True)
    train_pool_final = Pool(X_train, y_train_cox, weight=final_weights)
    val_pool_final = Pool(X_val, y_val_cox)

    final_model = CatBoostRegressor(
        iterations=650,
        depth=best_params["depth"],
        learning_rate=best_params["learning_rate"],
        l2_leaf_reg=best_params["l2_leaf_reg"],
        random_strength=best_params["random_strength"],
        loss_function="Cox",
        thread_count=12,
        random_seed=seed,
        verbose=False,
    )
    final_model.fit(train_pool_final, eval_set=val_pool_final, early_stopping_rounds=40, verbose=False)
    del train_pool_final, val_pool_final
    gc.collect()

    eta_train_final = final_model.predict(X_train)
    T_sort_final, H0_final = fit_breslow_estimator(train_dur, train_ev, eta_train_final)

    eta_val_final = final_model.predict(X_val)
    val_probs = predict_cox_survival_prob(T_sort_final, H0_final, val_planned, eta_val_final)

    eta_test_final = final_model.predict(X_test)
    test_probs = predict_cox_survival_prob(T_sort_final, H0_final, test_planned, eta_test_final)

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
    pd.DataFrame({"y_true": y_val_true, "y_prob": val_probs, "risk_score": eta_val_final}).to_csv(val_pred_path, index=False)
    pd.DataFrame({"y_true": y_test_true, "y_prob": test_probs, "risk_score": eta_test_final}).to_csv(test_pred_path, index=False)

    summary_metrics = {
        "model": "catboost_cox",
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
        "censored_samples": int((train_ev == 0).sum()),
    }
    with open(out_path / "cox_metrics.json", "w") as f:
        json.dump(summary_metrics, f, indent=2)

    evaluate_predictions(
        test_pred_path=str(test_pred_path),
        val_pred_path=str(val_pred_path),
        track="catboost_cox",
    )
    return summary_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train CatBoost Cox Proportional Hazards (Track 4).")
    parser.add_argument("--train-file", type=str, default="data/train_censored.parquet")
    parser.add_argument("--val-file", type=str, default="data/val_censored.parquet")
    parser.add_argument("--test-file", type=str, default="data/test_censored.parquet")
    parser.add_argument("--trials", type=int, default=35)
    parser.add_argument("--output-dir", type=str, default="experiments/catboost_cox")
    args = parser.parse_args()

    train_and_evaluate_catboost_cox(
        train_file=args.train_file,
        val_file=args.val_file,
        test_file=args.test_file,
        n_trials=args.trials,
        output_dir=args.output_dir,
    )
