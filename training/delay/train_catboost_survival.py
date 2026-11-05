"""Delay model components 3-4 — CatBoost SurvivalAft on right-censored T0 features.

--competing-risks none            P(T > planned) of the all-cause model (a blend input)
--competing-risks cause_specific  non-work closures (duplicate, invalid, won't fix ...) censored at
                                  closing time; its predicted delivery time is reported by the scorer
Saves {cbs,cbs_cr}.cbm + *_config.json to the staging bundle and predictions_{val,test}.csv.
The 4-model blend that used to be hard-coded here lives in fit_blend_gate.py.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from early_risk_detection._logging import setup_logging
from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.scorer import KIND
from early_risk_detection.delay.survival import survival_delay_prob
from early_risk_detection.evaluation import evaluate_predictions, find_optimal_threshold

log = logging.getLogger(__name__).info
optuna.logging.set_verbosity(optuna.logging.WARNING)


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
    data_dir: str = "data/delay_t0",
    stage_dir: str = "bundles/staging/delay",
    competing_risks: str = "none",
    n_trials: int = 35,
    seed: int = 42,
    output_dir: str = "experiments/delay_t0/catboost_survival",
    params_from: str | None = None,
    leaderboard: str = "experiments/leaderboard_delay_t0.json",
):

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    d = Path(data_dir)
    train_df = pd.read_parquet(d / "train_cens_labels.parquet")
    val_df = pd.read_parquet(d / "val_labels.parquet")
    test_df = pd.read_parquet(d / "test_labels.parquet")

    y_train = build_catboost_target(train_df, competing_risks=competing_risks)
    y_val = build_catboost_target(val_df, competing_risks="none")
    created_ts_tr = train_df["created_ts"].values.astype(np.float64)

    cens_cnt = int((y_train[:, 1] == -1.0).sum())
    log(f"[Target] Train shape: {y_train.shape} (Censored/Competing: {cens_cnt:,}/{len(y_train):,} = {cens_cnt/len(y_train):.2%})")

    y_val_true = val_df["is_delayed"].values.astype(np.int32)
    val_planned = val_df["planned_duration_days"].values.astype(np.float32)

    y_test_true = test_df["is_delayed"].values.astype(np.int32)
    test_planned = test_df["planned_duration_days"].values.astype(np.float32)

    X_train = pd.read_parquet(d / "X_surv_train_cens.parquet")
    X_val = pd.read_parquet(d / "X_surv_val.parquet")
    X_test = pd.read_parquet(d / "X_surv_test.parquet")
    val_uid, test_uid = val_df["uid"].values, test_df["uid"].values
    del train_df, val_df, test_df
    gc.collect()
    log(f"[Features] Input feature dimension: {X_train.shape[1]} float32 features.")

    max_train_ts = float(created_ts_tr.max())
    age_days_full = ((max_train_ts - created_ts_tr) / 86400.0).astype(np.float32)

    if params_from:
        best_params = json.loads(Path(params_from).read_text())["best_hyperparameters"]
        log(f"[Params] reusing {best_params} from {params_from}")
    else:
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

        log(f"\n[Optuna] Searching best CatBoost SurvivalAft hyperparameters ({n_trials} trials)...")

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
            val_prob = survival_delay_prob(log_pred_val, val_planned_opt, dist.lower(), scale)
            _, best_val_f1, _, _ = find_optimal_threshold(y_va_true_opt, val_prob)
            return float(best_val_f1)

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
        study.optimize(objective, n_trials=n_trials)

        best_params = study.best_params
        log(f"\n[Optuna] Best CatBoost Val F1: {study.best_value:.4f}")
        log(f"[Optuna] Best Hyperparameters: {best_params}")

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

    log(f"\n[Training] Fitting Final CatBoost SurvivalAft Model on full Train ({len(X_train):,} rows)...")
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

    stage = ModelBundle.staging(stage_dir, KIND)
    model_name = "cbs_cr" if competing_risks == "cause_specific" else "cbs"
    final_model.save_model(str(stage.file(f"{model_name}.cbm")))
    stage.save_json(f"{model_name}_config.json", {"distribution": best_dist, "scale": best_scale,
                                                  "competing_risks": competing_risks})
    log_pred_val = final_model.predict(X_val)
    val_probs = survival_delay_prob(log_pred_val, val_planned, best_dist.lower(), best_scale)

    log_pred_test = final_model.predict(X_test)
    test_probs = survival_delay_prob(log_pred_test, test_planned, best_dist.lower(), best_scale)

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
    pd.DataFrame({"uid": val_uid, "y_true": y_val_true, "y_prob": val_probs, "pred_time": np.exp(np.clip(log_pred_val, -20, 20))}).to_csv(val_pred_path, index=False)
    pd.DataFrame({"uid": test_uid, "y_true": y_test_true, "y_prob": test_probs, "pred_time": np.exp(np.clip(log_pred_test, -20, 20))}).to_csv(test_pred_path, index=False)

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

    track_name = "catboost_competing_risks_t0" if competing_risks == "cause_specific" else "catboost_survival_t0"
    evaluate_predictions(
        test_pred_path=str(test_pred_path),
        val_pred_path=str(val_pred_path),
        track=track_name,
        leaderboard_path=leaderboard,
    )
    return summary_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the CatBoost survival / competing-risks components.")
    parser.add_argument("--data-dir", type=str, default="data/delay_t0")
    parser.add_argument("--stage", type=str, default="bundles/staging/delay")
    parser.add_argument("--competing-risks", type=str, choices=["none", "cause_specific"], default="none")
    parser.add_argument("--trials", type=int, default=35)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--params-from", type=str, default=None, help="catboost_metrics.json of an earlier run")
    parser.add_argument("--leaderboard", type=str, default="experiments/leaderboard_delay_t0.json")
    args = parser.parse_args()
    setup_logging()
    out = args.output_dir or ("experiments/delay_t0/catboost_competing_risks" if args.competing_risks == "cause_specific"
                              else "experiments/delay_t0/catboost_survival")
    train_and_evaluate_catboost_survival(data_dir=args.data_dir, stage_dir=args.stage, competing_risks=args.competing_risks,
                                         n_trials=args.trials, output_dir=out, params_from=args.params_from,
                                         leaderboard=args.leaderboard)
