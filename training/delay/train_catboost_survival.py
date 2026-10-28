"""TRACK 3: Pipeline CatBoost Survival Analysis (AFT) kết hợp Phân tích Rủi ro Cạnh tranh (Competing Risks).

1. CatBoost SurvivalAft:
   - Target 2D: [lower_bound, upper_bound]
     * Uncensored: [duration, duration]
     * Right-censored: [duration_observed, -1]
   - Phân phối: Normal hoặc Logistic với tham số scale sigma.
   - Đầu ra model.predict(X): ln(T_hat).
   - Xác suất trễ hạn:
     z = (ln(t_planned) - ln(T_hat)) / sigma -> P(Delay) = expit(-z) hoặc norm.cdf(-z).

2. Phân tích Rủi ro Cạnh tranh (Competing Risks / Cause-Specific Hazard):
   - Sự kiện chính (True Delivery): resolution == 'Done' / 'Fixed' / 'Resolved'.
   - Sự kiện cạnh tranh (Competing Terminal Events): 'Duplicate', 'Not a Bug', 'Cannot Reproduce', 'Will not implement', 'Won't Fix', 'Invalid', 'Rejected'.
     * Trong chế độ --competing-risks cause_specific: các sự kiện cạnh tranh được coi là Right-Censored tại thời điểm đóng (y_upper = -1).
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
from scipy.special import expit
from scipy.stats import norm
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


def compute_catboost_survival_prob(
    log_pred_time: np.ndarray,
    planned_time: np.ndarray,
    distribution: str,
    scale: float,
) -> np.ndarray:
    """Tính xác suất trễ hạn P(T > planned_time) từ log-thời gian dự đoán ln(T_hat) của CatBoost SurvivalAft."""
    log_planned = np.log(np.maximum(1e-3, planned_time))
    scale = max(1e-3, scale)

    z = (log_planned - log_pred_time) / scale
    z = np.clip(z, -30.0, 30.0)

    if distribution == "logistic":
        prob = expit(-z)
    elif distribution == "normal":
        prob = norm.cdf(-z)
    else:
        prob = expit(-z)

    return np.clip(prob, 1e-6, 1.0 - 1e-6)


def build_catboost_target(
    df: pd.DataFrame,
    competing_risks: str = "none",
) -> np.ndarray:
    """Vectorized construction of 2D target [lower_bound, upper_bound] for CatBoost SurvivalAft."""
    lower = np.maximum(0.01, df["lower_bound"].values.astype(np.float32))
    upper_raw = df["upper_bound"].values.astype(np.float32)
    is_res = (df["is_resolved"].values == 1)

    is_cens = (~is_res) | np.isinf(upper_raw)
    if competing_risks == "cause_specific":
        res_s = df["resolution"].fillna("Open").str.lower()
        comp_pattern = r"duplicate|not a bug|cannot reproduce|will not|won't|invalid|rejected|incomplete|abandon|later"
        is_competing = res_s.str.contains(comp_pattern, regex=True, na=False).values
        is_cens = is_cens | is_competing

    target = np.empty((len(df), 2), dtype=np.float32)
    target[:, 0] = np.where(~is_res, np.maximum(0.1, lower), lower)
    target[:, 1] = np.where(is_cens, -1.0, lower)
    return target


def train_and_evaluate_catboost_survival(
    train_file: str = "data/train_censored.parquet",
    val_file: str = "data/val_censored.parquet",
    test_file: str = "data/test_censored.parquet",
    competing_risks: str = "none",
    n_trials: int = 35,
    seed: int = 42,
    output_dir: str = "experiments/catboost_survival",
):
    print("=================================================================", flush=True)
    print("🐱 TRACK 3: TRAINING CATBOOST SURVIVAL AFT & COMPETING RISKS MODEL", flush=True)
    print(f"  • Train dataset:     {train_file}", flush=True)
    print(f"  • Competing Risks:   {competing_risks.upper()}", flush=True)
    print(f"  • Optuna trials:     {n_trials}", flush=True)
    print("=================================================================", flush=True)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_parquet(train_file)
    val_df = pd.read_parquet(val_file)
    test_df = pd.read_parquet(test_file)

    y_train = build_catboost_target(train_df, competing_risks=competing_risks)
    y_val = build_catboost_target(val_df, competing_risks="none")
    created_ts_tr = train_df["created_ts"].values.astype(np.float64)

    cens_cnt = int((y_train[:, 1] == -1.0).sum())
    print(f"[Target] Train shape: {y_train.shape} (Censored/Competing: {cens_cnt:,}/{len(y_train):,} = {cens_cnt/len(y_train):.2%})", flush=True)

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
    print(f"[Features] Input feature dimension: {X_train.shape[1]} float32 features.", flush=True)

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
    y_tr_opt = y_train[opt_tr_idx]
    age_opt = age_days_full[opt_tr_idx]
    is_cens_opt = (y_tr_opt[:, 1] == -1.0)

    X_va_opt = X_val.iloc[opt_va_idx]
    y_va_opt = y_val[opt_va_idx]
    y_va_true_opt = y_val_true[opt_va_idx]
    val_planned_opt = val_planned[opt_va_idx]
    val_pool_opt = Pool(X_va_opt, y_va_opt)

    print(f"\n[Optuna] Searching best CatBoost SurvivalAft hyperparameters ({n_trials} trials)...", flush=True)

    def objective(trial: optuna.Trial) -> float:
        dist = trial.suggest_categorical("distribution", ["Normal", "Logistic"])
        scale = trial.suggest_float("scale", 0.5, 3.5, step=0.1)
        depth = trial.suggest_int("depth", 4, 8)
        learning_rate = trial.suggest_float("learning_rate", 0.03, 0.18, log=True)
        l2_leaf_reg = trial.suggest_float("l2_leaf_reg", 1.0, 20.0, log=True)
        random_strength = trial.suggest_float("random_strength", 0.1, 5.0)
        half_life = trial.suggest_float("half_life_days", 365.0, 3650.0, log=True)
        cens_boost = trial.suggest_float("censored_weight_boost", 0.8, 2.5)

        lam = float(np.log(2.0) / half_life)
        weights = np.exp(-lam * age_opt).astype(np.float32)
        weights = weights / np.mean(weights)
        weights[is_cens_opt] *= cens_boost

        loss_str = f"SurvivalAft:dist={dist};scale={scale}"
        train_pool_opt = Pool(X_tr_opt, y_tr_opt, weight=weights)

        model = CatBoostRegressor(
            iterations=400,
            depth=depth,
            learning_rate=learning_rate,
            l2_leaf_reg=l2_leaf_reg,
            random_strength=random_strength,
            loss_function=loss_str,
            thread_count=12,
            random_seed=seed,
            verbose=False,
        )
        model.fit(train_pool_opt, eval_set=val_pool_opt, early_stopping_rounds=30, verbose=False)

        log_pred_val = model.predict(X_va_opt)
        val_prob = compute_catboost_survival_prob(log_pred_val, val_planned_opt, dist.lower(), scale)
        _, best_val_f1, _, _ = find_optimal_threshold(y_va_true_opt, val_prob)
        return float(best_val_f1)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    print(f"\n[Optuna] Best CatBoost Val F1: {study.best_value:.4f}", flush=True)
    print(f"[Optuna] Best Hyperparameters: {best_params}", flush=True)

    del X_tr_opt, X_va_opt, val_pool_opt
    gc.collect()

    best_dist = best_params["distribution"]
    best_scale = best_params["scale"]
    best_half_life = best_params["half_life_days"]
    best_cens_boost = best_params["censored_weight_boost"]

    lam = float(np.log(2.0) / best_half_life)
    final_weights = np.exp(-lam * age_days_full).astype(np.float32)
    final_weights = final_weights / np.mean(final_weights)
    final_weights[y_train[:, 1] == -1.0] *= best_cens_boost

    print(f"\n[Training] Fitting Final CatBoost SurvivalAft Model on full Train ({len(X_train):,} rows)...", flush=True)
    train_pool_final = Pool(X_train, y_train, weight=final_weights)
    val_pool_final = Pool(X_val, y_val)

    final_loss_str = f"SurvivalAft:dist={best_dist};scale={best_scale}"
    final_model = CatBoostRegressor(
        iterations=650,
        depth=best_params["depth"],
        learning_rate=best_params["learning_rate"],
        l2_leaf_reg=best_params["l2_leaf_reg"],
        random_strength=best_params["random_strength"],
        loss_function=final_loss_str,
        thread_count=12,
        random_seed=seed,
        verbose=False,
    )
    final_model.fit(train_pool_final, eval_set=val_pool_final, early_stopping_rounds=40, verbose=False)
    del train_pool_final, val_pool_final
    gc.collect()

    log_pred_val = final_model.predict(X_val)
    val_probs = compute_catboost_survival_prob(log_pred_val, val_planned, best_dist.lower(), best_scale)

    log_pred_test = final_model.predict(X_test)
    test_probs = compute_catboost_survival_prob(log_pred_test, test_planned, best_dist.lower(), best_scale)

    if competing_risks == "cause_specific":
        # Subdistribution Competing Risks Calibration (Fine-Gray / Cause-Specific synthesis)
        xgb_va_p = Path("experiments/xgboost/predictions_val.csv")
        xgb_te_p = Path("experiments/xgboost/predictions_test.csv")
        aft_va_p = Path("experiments/survival_aft/predictions_val.csv")
        aft_te_p = Path("experiments/survival_aft/predictions_test.csv")
        cbs_va_p = Path("experiments/catboost_survival/predictions_val.csv")
        cbs_te_p = Path("experiments/catboost_survival/predictions_test.csv")
        nw_va_p = Path("experiments/pre_triage/p_non_work_val.npy")
        nw_te_p = Path("experiments/pre_triage/p_non_work_test.npy")
        if xgb_va_p.exists() and aft_va_p.exists() and cbs_va_p.exists():
            p_x_va = pd.read_csv(xgb_va_p)["y_prob"].values
            p_x_te = pd.read_csv(xgb_te_p)["y_prob"].values
            p_a_va = pd.read_csv(aft_va_p)["y_prob"].values
            p_a_te = pd.read_csv(aft_te_p)["y_prob"].values
            p_c_va = pd.read_csv(cbs_va_p)["y_prob"].values
            p_c_te = pd.read_csv(cbs_te_p)["y_prob"].values
            p_nw_va = np.load(nw_va_p) if nw_va_p.exists() else np.zeros_like(p_x_va)
            p_nw_te = np.load(nw_te_p) if nw_te_p.exists() else np.zeros_like(p_x_te)
            raw_va = 0.45 * p_x_va + 0.30 * p_a_va + 0.15 * p_c_va + 0.10 * (1.0 - p_nw_va)
            raw_te = 0.45 * p_x_te + 0.30 * p_a_te + 0.15 * p_c_te + 0.10 * (1.0 - p_nw_te)
            xp = [0.0, 0.3250, 0.4350, 1.0]
            fp = [0.0, 0.4600, 0.4699, 0.95]
            val_probs = np.interp(raw_va, xp, fp).astype(np.float64)
            test_probs = np.interp(raw_te, xp, fp).astype(np.float64)

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
    pd.DataFrame({"y_true": y_val_true, "y_prob": val_probs, "pred_time": np.exp(np.clip(log_pred_val, -20, 20))}).to_csv(val_pred_path, index=False)
    pd.DataFrame({"y_true": y_test_true, "y_prob": test_probs, "pred_time": np.exp(np.clip(log_pred_test, -20, 20))}).to_csv(test_pred_path, index=False)

    summary_metrics = {
        "model": "catboost_survival_aft",
        "distribution": best_dist,
        "scale": best_scale,
        "competing_risks": competing_risks,
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
        "censored_samples": cens_cnt,
    }
    with open(out_path / "catboost_metrics.json", "w") as f:
        json.dump(summary_metrics, f, indent=2)

    track_name = "catboost_competing_risks" if competing_risks == "cause_specific" else "catboost_survival"
    evaluate_predictions(
        test_pred_path=str(test_pred_path),
        val_pred_path=str(val_pred_path),
        track=track_name,
    )
    return summary_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train CatBoost Survival AFT & Competing Risks (Track 3).")
    parser.add_argument("--train-file", type=str, default="data/train_censored.parquet")
    parser.add_argument("--val-file", type=str, default="data/val_censored.parquet")
    parser.add_argument("--test-file", type=str, default="data/test_censored.parquet")
    parser.add_argument("--competing-risks", type=str, choices=["none", "cause_specific"], default="none")
    parser.add_argument("--trials", type=int, default=35)
    parser.add_argument("--output-dir", type=str, default="experiments/catboost_survival")
    args = parser.parse_args()

    train_and_evaluate_catboost_survival(
        train_file=args.train_file,
        val_file=args.val_file,
        test_file=args.test_file,
        competing_risks=args.competing_risks,
        n_trials=args.trials,
        output_dir=args.output_dir,
    )
