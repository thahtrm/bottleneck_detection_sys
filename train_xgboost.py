"""Pipeline Gradient Boosting (XGBoost) Chuyên Sâu v2 cho Dự đoán Nguy cơ Trễ hạn Issue.

Chức năng:
1. Feature Engineering chuyên sâu:
   - Trích xuất TF-IDF n-grams (1, 2) và SVD semantic embedding từ cột `summary` (fit train, transform val/test).
   - Tương tác phi tuyến: WCI x SCF, pressure index, queue clearing estimates, active_per_completed.
   - Chuyển đổi log (log1p) cho các trường độ lớn (workload, completions, durations, SP).
   - Tích hợp các đặc trưng động lực học 90 ngày (rolling 90d delay rates, cycle times, velocities, momentum).
   - Mã hóa One-Hot và Target Encoding mượt hóa (Laplace smoothing) ngoài mẫu (out-of-fold).
2. Tối ưu hóa siêu tham số Bayesian bằng Optuna (35-50 trials) với 5-Fold TimeSeriesSplit trên train.parquet.
3. Huấn luyện 5-Fold Stratified Ensemble trên train.parquet với các siêu tham số tối ưu.
4. Xuất predictions_val.csv và predictions_test.csv.
5. Tính toán SHAP values trên validation set và xuất Top 10 đặc trưng quan trọng nhất vào shap_summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Tuple

import numpy as np
import optuna
import pandas as pd
import shap
import xgboost as xgb
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score, brier_score_loss
from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit

optuna.logging.set_verbosity(optuna.logging.WARNING)


def compute_target_encoding(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    cat_cols: list[str],
    target_col: str = "is_delayed",
    n_splits: int = 5,
    smoothing: float = 10.0,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Tính toán Target Encoding mượt hóa Out-of-fold trên tập Train, ánh xạ sang Val và Test."""
    global_mean = float(train_df[target_col].mean())
    te_train_dict = {}
    te_val_dict = {}
    te_test_dict = {}

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    for col in cat_cols:
        # 1. Out-of-fold cho train
        oof_series = pd.Series(index=train_df.index, dtype=float)
        for tr_idx, val_idx in skf.split(train_df, train_df[target_col]):
            fold_tr = train_df.iloc[tr_idx]
            stats = fold_tr.groupby(col)[target_col].agg(["count", "mean"])
            smoothed = (stats["count"] * stats["mean"] + smoothing * global_mean) / (stats["count"] + smoothing)
            mapped = train_df.iloc[val_idx][col].map(smoothed).fillna(global_mean)
            oof_series.iloc[val_idx] = mapped
        te_train_dict[f"{col}_te"] = oof_series.values

        # 2. Toàn bộ train để ánh xạ val và test
        stats = train_df.groupby(col)[target_col].agg(["count", "mean"])
        smoothed = (stats["count"] * stats["mean"] + smoothing * global_mean) / (stats["count"] + smoothing)
        te_val_dict[f"{col}_te"] = val_df[col].map(smoothed).fillna(global_mean).values
        te_test_dict[f"{col}_te"] = test_df[col].map(smoothed).fillna(global_mean).values

    encoded_train = pd.DataFrame(te_train_dict, index=train_df.index)
    encoded_val = pd.DataFrame(te_val_dict, index=val_df.index)
    encoded_test = pd.DataFrame(te_test_dict, index=test_df.index)

    return encoded_train, encoded_val, encoded_test


def extract_all_features(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Khai phá và kỹ thuật hóa toàn diện các đặc trưng tabular, NLP, rolling velocity và tương tác phi tuyến."""
    print("[Feature Engineering] Generating domain-specific, nonlinear, and rolling features...")
    dfs = [train_df, val_df, test_df]
    processed_dfs = []

    for d in dfs:
        feats = {}

        # 1. Assignment & Workload Ratios
        is_unass = (d["assignee"] == "(unassigned)").astype(int)
        feats["is_unassigned"] = is_unass
        feats["is_unassigned_reporter"] = (d["reporter"] == "(unassigned)").astype(int)
        feats["assignee_load_ratio"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)
        feats["active_per_completed"] = d["assignee_active_count"] / (d["assignee_hist_completed"] + 1.0)
        feats["active_per_completed_90d"] = d["assignee_active_count"] / (d["assignee_90d_completed"] + 1.0)
        feats["project_active_per_completed"] = d["project_active_count"] / (d["project_90d_completed"] + 1.0)
        feats["unassigned_pressure"] = d["unassigned_active_count"] / (d["project_active_count"] + 1.0)
        feats["is_assignee_overloaded"] = (d["assignee_active_count"] > 10).astype(int)
        feats["is_assignee_fresh"] = (d["assignee_hist_completed"] == 0).astype(int)
        feats["is_assignee_experienced"] = (d["assignee_hist_completed"] >= 30).astype(int)

        # 2. Queue Clearing Estimates
        feats["queue_clearing_estimate"] = d["assignee_active_count"] * d["assignee_90d_cycle_time"]
        feats["queue_clearing_ratio"] = feats["queue_clearing_estimate"] / (d["planned_duration_days"] + 1e-4)
        feats["hist_queue_clearing_estimate"] = d["assignee_active_count"] * d["assignee_hist_cycle_time"]
        feats["hist_queue_clearing_ratio"] = feats["hist_queue_clearing_estimate"] / (d["planned_duration_days"] + 1e-4)
        feats["project_queue_clearing_estimate"] = d["project_active_count"] * d["project_90d_cycle_time"]
        feats["project_queue_clearing_ratio"] = feats["project_queue_clearing_estimate"] / (d["planned_duration_days"] + 1e-4)

        # 3. Chuyển đổi Log (Log1p) cho các trường độ lớn
        feats["log_assignee_active"] = np.log1p(np.maximum(0, d["assignee_active_count"]))
        feats["log_project_active"] = np.log1p(np.maximum(0, d["project_active_count"]))
        feats["log_unassigned_active"] = np.log1p(np.maximum(0, d["unassigned_active_count"]))
        feats["log_assignee_completed"] = np.log1p(np.maximum(0, d["assignee_hist_completed"]))
        feats["log_assignee_90d_completed"] = np.log1p(np.maximum(0, d["assignee_90d_completed"]))
        feats["log_reporter_completed"] = np.log1p(np.maximum(0, d["reporter_hist_completed"]))
        feats["log_reporter_90d_completed"] = np.log1p(np.maximum(0, d["reporter_90d_completed"]))
        feats["log_project_90d_completed"] = np.log1p(np.maximum(0, d["project_90d_completed"]))
        feats["log_story_points"] = np.log1p(np.maximum(0, d["story_points"]))
        feats["log_planned_duration"] = np.log1p(np.maximum(0, d["planned_duration_days"]))
        feats["log_wci"] = np.log1p(np.maximum(0, d["assignee_wci"]))
        feats["log_scf"] = np.log1p(np.maximum(0, d["scf"]))
        feats["log_cycle_time_90d"] = np.log1p(np.maximum(0, d["assignee_90d_cycle_time"]))
        feats["log_project_cycle_time_90d"] = np.log1p(np.maximum(0, d["project_90d_cycle_time"]))

        # 4. Tương tác Phi Tuyến: WCI x SCF, Pressure Index, Ratios
        feats["wci_x_scf"] = d["assignee_wci"] * d["scf"]
        feats["wci_div_scf"] = d["assignee_wci"] / (d["scf"] + 1e-4)
        feats["sp_x_scf"] = d["story_points"] * d["scf"]
        feats["sp_div_scf"] = d["story_points"] / (d["scf"] + 1e-4)
        feats["sp_x_planned"] = d["story_points"] * d["planned_duration_days"]
        feats["sp_div_planned"] = d["story_points"] / (d["planned_duration_days"] + 1e-4)
        feats["wci_x_planned"] = d["assignee_wci"] * d["planned_duration_days"]
        feats["wci_div_planned"] = d["assignee_wci"] / (d["planned_duration_days"] + 1e-4)
        feats["wci_x_sp"] = d["assignee_wci"] * d["story_points"]
        feats["wci_div_sp"] = d["assignee_wci"] / (d["story_points"] + 1e-4)
        feats["pressure_index"] = (d["story_points"] * d["assignee_wci"]) / (d["scf"] * d["planned_duration_days"] + 1e-4)
        feats["scf_sq"] = d["scf"] ** 2
        feats["is_compressed"] = (d["scf"] < 1.0).astype(int)
        feats["is_extreme_compressed"] = (d["scf"] < 0.5).astype(int)
        feats["is_high_wci"] = (d["assignee_wci"] > 50).astype(int)
        feats["is_low_wci"] = (d["assignee_wci"] < 10).astype(int)

        # 5. Động lực học 90 ngày (Rolling 90-day Velocity & Momentum)
        scf_90d = d["planned_duration_days"] / (d["assignee_90d_cycle_time"] + 1e-4)
        feats["scf_90d"] = scf_90d
        feats["wci_x_scf_90d"] = d["assignee_wci"] * scf_90d
        feats["pressure_index_90d"] = (d["story_points"] * d["assignee_wci"]) / (scf_90d * d["planned_duration_days"] + 1e-4)
        feats["assignee_delay_velocity"] = d["assignee_90d_delay_rate"] - d["assignee_hist_delay_rate"]
        feats["assignee_cycle_velocity"] = d["assignee_90d_cycle_time"] - d["assignee_hist_cycle_time"]
        feats["reporter_delay_velocity"] = d["reporter_90d_delay_rate"] - d["reporter_hist_delay_rate"]
        feats["project_delay_velocity"] = d["project_90d_delay_rate"] - d["assignee_hist_delay_rate"]
        feats["project_cycle_vs_assignee"] = d["project_90d_cycle_time"] - d["assignee_90d_cycle_time"]
        feats["assignee_vs_project_delay"] = d["assignee_90d_delay_rate"] - d["project_90d_delay_rate"]
        feats["rolling_mean_delay"] = (d["assignee_90d_delay_rate"] + d["reporter_90d_delay_rate"] + d["project_90d_delay_rate"]) / 3.0
        feats["rolling_max_delay"] = np.maximum(d["assignee_90d_delay_rate"], np.maximum(d["reporter_90d_delay_rate"], d["project_90d_delay_rate"]))
        feats["rolling_min_delay"] = np.minimum(d["assignee_90d_delay_rate"], np.minimum(d["reporter_90d_delay_rate"], d["project_90d_delay_rate"]))
        feats["cycle_vs_planned_90d"] = d["assignee_90d_cycle_time"] / (d["planned_duration_days"] + 1e-4)
        feats["cycle_minus_planned_90d"] = d["assignee_90d_cycle_time"] - d["planned_duration_days"]
        feats["proj_cycle_vs_planned_90d"] = d["project_90d_cycle_time"] / (d["planned_duration_days"] + 1e-4)
        feats["proj_cycle_minus_planned_90d"] = d["project_90d_cycle_time"] - d["planned_duration_days"]
        feats["cycle_vs_planned_hist"] = d["assignee_hist_cycle_time"] / (d["planned_duration_days"] + 1e-4)
        feats["cycle_minus_planned_hist"] = d["assignee_hist_cycle_time"] - d["planned_duration_days"]
        feats["is_cycle_exceed_90d"] = (d["assignee_90d_cycle_time"] > d["planned_duration_days"]).astype(int)
        feats["is_cycle_exceed_hist"] = (d["assignee_hist_cycle_time"] > d["planned_duration_days"]).astype(int)
        feats["mean_hist_delay"] = (d["assignee_hist_delay_rate"] + d["reporter_hist_delay_rate"]) / 2.0
        feats["diff_hist_delay"] = d["assignee_hist_delay_rate"] - d["reporter_hist_delay_rate"]
        feats["prod_hist_delay"] = d["assignee_hist_delay_rate"] * d["reporter_hist_delay_rate"]
        feats["assignee_delay_risk"] = d["assignee_hist_delay_rate"] * feats["log_assignee_completed"]
        feats["reporter_delay_risk"] = d["reporter_hist_delay_rate"] * feats["log_reporter_completed"]

        # Các trường số gốc từ dataset
        raw_num_cols = [
            "priority_norm", "planned_duration_days", "story_points", "sp_planned_ratio", "sp_planned_product",
            "assignee_active_count", "assignee_hist_completed", "assignee_hist_cycle_time", "assignee_hist_delay_rate",
            "assignee_90d_completed", "assignee_90d_delay_rate", "assignee_90d_cycle_time", "assignee_wci", "scf",
            "reporter_hist_completed", "reporter_hist_delay_rate", "reporter_90d_completed", "reporter_90d_delay_rate",
            "project_active_count", "project_90d_completed", "project_90d_delay_rate", "project_90d_cycle_time",
            "unassigned_active_count", "unassigned_90d_delay_rate",
        ]
        for col in raw_num_cols:
            if col in d.columns:
                feats[col] = d[col].values

        # 6. Graph Dependency Network
        feats["total_deps"] = (d["blocks_count"] + d["depends_count"]).values
        feats["has_links"] = (d["num_links"] > 0).astype(int).values
        feats["has_blocks"] = (d["blocks_count"] > 0).astype(int).values
        feats["has_depends"] = (d["depends_count"] > 0).astype(int).values
        feats["dep_density"] = ((d["blocks_count"] + 1.0) * (d["depends_count"] + 1.0)).values
        feats["links_per_sp"] = (d["num_links"] / (d["story_points"] + 1e-4)).values
        feats["is_isolated"] = (d["num_links"] == 0).astype(int).values
        feats["blocks_count"] = d["blocks_count"].values
        feats["depends_count"] = d["depends_count"].values
        feats["num_links"] = d["num_links"].values

        # 7. Text Complexity & Ambiguity
        feats["summary_len"] = d["summary_len"].values
        feats["word_count"] = d["word_count"].values
        feats["ambiguity_score"] = d["ambiguity_score"].values
        feats["chars_per_word"] = (d["summary_len"] / np.maximum(1, d["word_count"])).values
        feats["has_ambiguity"] = (d["ambiguity_score"] > 0).astype(int).values
        feats["high_ambiguity"] = (d["ambiguity_score"] > 0.1).astype(int).values
        feats["ambiguity_words"] = (d["ambiguity_score"] * d["word_count"]).values
        feats["sp_per_word"] = (d["story_points"] / np.maximum(1, d["word_count"])).values
        feats["is_long_summary"] = (d["summary_len"] > 80).astype(int).values
        feats["is_short_summary"] = (d["summary_len"] < 30).astype(int).values

        # 8. Calendar & Deadline Flags
        feats["is_high_priority"] = (d["priority_norm"] >= 0.8).astype(int).values
        feats["is_low_priority"] = (d["priority_norm"] <= 0.4).astype(int).values
        feats["is_tight_deadline"] = (d["planned_duration_days"] <= 14.0).astype(int).values
        feats["is_medium_deadline"] = (d["planned_duration_days"] == 30.0).astype(int).values
        feats["is_loose_deadline"] = (d["planned_duration_days"] >= 45.0).astype(int).values
        feats["priority_planned_ratio"] = (d["priority_norm"] / (d["planned_duration_days"] + 1e-4)).values
        feats["priority_sp_ratio"] = (d["priority_norm"] / (d["story_points"] + 1e-4)).values
        feats["sin_month"] = np.sin(2 * np.pi * d["created_month"] / 12.0).values
        feats["cos_month"] = np.cos(2 * np.pi * d["created_month"] / 12.0).values
        feats["sin_dow"] = np.sin(2 * np.pi * d["created_dayofweek"] / 7.0).values
        feats["cos_dow"] = np.cos(2 * np.pi * d["created_dayofweek"] / 7.0).values
        feats["is_weekend"] = (d["created_dayofweek"] >= 5).astype(int).values

        processed_dfs.append(pd.DataFrame(feats, index=d.index))

    p_train, p_val, p_test = processed_dfs

    # 9. One-Hot Encoding cho categoricals chuẩn hóa theo tập Train
    cat_cols = ["project", "issuetype", "issuetype_theme"]
    for col in cat_cols:
        tr_dummies = pd.get_dummies(train_df[col], prefix=col, dtype=int)
        va_dummies = pd.get_dummies(val_df[col], prefix=col, dtype=int).reindex(columns=tr_dummies.columns, fill_value=0)
        te_dummies = pd.get_dummies(test_df[col], prefix=col, dtype=int).reindex(columns=tr_dummies.columns, fill_value=0)

        p_train = pd.concat([p_train, tr_dummies], axis=1)
        p_val = pd.concat([p_val, va_dummies], axis=1)
        p_test = pd.concat([p_test, te_dummies], axis=1)

    # 10. Out-of-fold Smoothed Target Encoding
    te_train, te_val, te_test = compute_target_encoding(
        train_df, val_df, test_df,
        cat_cols=["project", "issuetype", "issuetype_theme", "priority_raw"],
        target_col="is_delayed",
        seed=seed,
    )
    p_train = pd.concat([p_train, te_train], axis=1)
    p_val = pd.concat([p_val, te_val], axis=1)
    p_test = pd.concat([p_test, te_test], axis=1)

    # 11. Trích xuất TF-IDF n-grams (1, 2) từ summary (chỉ fit trên train.parquet)
    print("[NLP] Extracting TF-IDF n-grams (1, 2) and SVD semantic embeddings from summary...")
    tfidf = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=40,
        stop_words="english",
        sublinear_tf=True,
    )
    tr_tfidf_mat = tfidf.fit_transform(train_df["summary"].fillna(""))
    va_tfidf_mat = tfidf.transform(val_df["summary"].fillna(""))
    te_tfidf_mat = tfidf.transform(test_df["summary"].fillna(""))

    tfidf_feat_names = [f"tfidf_{feat.replace(' ', '_')}" for feat in tfidf.get_feature_names_out()]
    tr_tfidf_df = pd.DataFrame(tr_tfidf_mat.toarray(), columns=tfidf_feat_names, index=train_df.index)
    va_tfidf_df = pd.DataFrame(va_tfidf_mat.toarray(), columns=tfidf_feat_names, index=val_df.index)
    te_tfidf_df = pd.DataFrame(te_tfidf_mat.toarray(), columns=tfidf_feat_names, index=test_df.index)

    # TruncatedSVD semantic components
    svd = TruncatedSVD(n_components=8, random_state=seed)
    tr_svd_mat = svd.fit_transform(tr_tfidf_mat)
    va_svd_mat = svd.transform(va_tfidf_mat)
    te_svd_mat = svd.transform(te_tfidf_mat)
    svd_feat_names = [f"svd_summary_{i}" for i in range(8)]
    tr_svd_df = pd.DataFrame(tr_svd_mat, columns=svd_feat_names, index=train_df.index)
    va_svd_df = pd.DataFrame(va_svd_mat, columns=svd_feat_names, index=val_df.index)
    te_svd_df = pd.DataFrame(te_svd_mat, columns=svd_feat_names, index=test_df.index)

    p_train = pd.concat([p_train, tr_tfidf_df, tr_svd_df], axis=1)
    p_val = pd.concat([p_val, va_tfidf_df, va_svd_df], axis=1)
    p_test = pd.concat([p_test, te_tfidf_df, te_svd_df], axis=1)

    print(f"[Feature Engineering] Successfully extracted {p_train.shape[1]} engineered features.", flush=True)
    return p_train, p_val, p_test


def optimize_hyperparameters(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    created_ts: np.ndarray,
    n_trials: int = 40,
    seed: int = 42,
) -> Tuple[dict, float]:
    """Tối ưu hóa siêu tham số Bayesian bằng Optuna với 5-Fold TimeSeriesSplit trên train.parquet."""
    print(f"\n[Optuna] Starting Bayesian Hyperparameter Optimization ({n_trials} trials, 5-Fold TimeSeriesSplit)...")

    tscv = TimeSeriesSplit(n_splits=5)
    default_scale_pos = float((len(y_train) - y_train.sum()) / y_train.sum())

    # Chuẩn hóa mốc thời gian để hỗ trợ recency sample weights
    ts_norm = (created_ts - created_ts.min()) / (created_ts.max() - created_ts.min() + 1e-4)

    def objective(trial: optuna.Trial) -> float:
        recency_alpha = trial.suggest_float("recency_alpha", 0.0, 1.5)
        sw = np.exp(recency_alpha * ts_norm)
        sw = sw / sw.mean()

        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 220, step=20),
            "max_depth": trial.suggest_int("max_depth", 3, 5),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.07, log=True),
            "subsample": trial.suggest_float("subsample", 0.70, 0.90),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.55, 0.80),
            "colsample_bylevel": trial.suggest_float("colsample_bylevel", 0.65, 0.90),
            "min_child_weight": trial.suggest_int("min_child_weight", 4, 12),
            "gamma": trial.suggest_float("gamma", 0.0, 2.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-2, 3.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 10.0, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.85 * default_scale_pos, 1.20 * default_scale_pos),
            "random_state": seed,
            "n_jobs": 4,
            "eval_metric": "logloss",
        }

        pr_auc_scores = []
        for tr_idx, va_idx in tscv.split(X_train):
            X_tr, y_tr = X_train.iloc[tr_idx], y_train[tr_idx]
            X_va, y_va = X_train.iloc[va_idx], y_train[va_idx]
            sw_tr = sw[tr_idx]

            clf = xgb.XGBClassifier(**params)
            clf.fit(X_tr, y_tr, sample_weight=sw_tr)
            preds_prob = clf.predict_proba(X_va)[:, 1]
            score = average_precision_score(y_va, preds_prob)
            pr_auc_scores.append(score)

        return float(np.mean(pr_auc_scores))

    def print_callback(study: optuna.Study, trial: optuna.Trial):
        print(
            f"  [Optuna Trial {trial.number + 1:2d}/{n_trials}] PR-AUC: {trial.value:.4f} "
            f"(Best so far: {study.best_value:.4f})",
            flush=True,
        )

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, callbacks=[print_callback])

    best_trial = study.best_trial
    best_recency_alpha = best_trial.params.pop("recency_alpha", 0.0)
    best_params = best_trial.params

    print(f"\n[Optuna] Optimization finished! Best Mean PR-AUC: {study.best_value:.4f}")
    print(f"[Optuna] Best recency_alpha: {best_recency_alpha:.4f}")
    print("[Optuna] Best parameters:")
    for k, v in best_params.items():
        print(f"  • {k}: {v}")

    return best_params, best_recency_alpha


def compute_shap_analysis(
    models: list[xgb.XGBClassifier],
    X_val: pd.DataFrame,
    out_path: str = "experiments/xgboost/shap_summary.json",
    top_k: int = 10,
) -> list[dict]:
    """Tính toán SHAP values trên validation set và lưu Top 10 đặc trưng quan trọng nhất."""
    print(f"\n[SHAP] Computing SHAP values across ensemble on validation set ({len(X_val)} samples)...", flush=True)
    all_shap = []
    for model in models:
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_val)
        all_shap.append(np.abs(shap_vals))

    # Trung bình giá trị tuyệt đối SHAP qua các mô hình trong ensemble và qua các mẫu validation
    mean_abs_shap = np.mean(np.mean(all_shap, axis=0), axis=0)
    feat_names = list(X_val.columns)

    shap_df = pd.DataFrame({
        "feature": feat_names,
        "mean_abs_shap": mean_abs_shap,
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    top_features = shap_df.head(top_k).to_dict(orient="records")

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(top_features, f, indent=2, ensure_ascii=False)

    print(f"[SHAP] Top {top_k} features saved to {out_file.resolve()}:", flush=True)
    for rank, item in enumerate(top_features, 1):
        print(f"  {rank:2d}. {item['feature']:35s} : {item['mean_abs_shap']:.5f}", flush=True)

    return top_features


def main():
    parser = argparse.ArgumentParser(description="Train and Optimize XGBoost Pipeline v2 for Issue Delay Prediction")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing train.parquet, val.parquet, test.parquet")
    parser.add_argument("--output-dir", type=str, default="experiments/xgboost", help="Directory to save predictions and SHAP summary")
    parser.add_argument("--n-trials", type=int, default=35, help="Number of Optuna trials")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--skip-tuning", action="store_true", help="Skip Optuna and use pre-optimized default parameters")

    args = parser.parse_args()
    data_path = Path(args.data_dir)
    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("=================================================================", flush=True)
    print("🚀 TRAINING GRADIENT BOOSTING (XGBOOST) PIPELINE V2", flush=True)
    print("=================================================================", flush=True)

    # 1. Đọc dữ liệu
    t0 = time.time()
    train_df = pd.read_parquet(data_path / "train.parquet")
    val_df = pd.read_parquet(data_path / "val.parquet")
    test_df = pd.read_parquet(data_path / "test.parquet")
    print(f"[Data] Loaded Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)} in {time.time()-t0:.2f}s", flush=True)

    y_train = train_df["is_delayed"].values
    y_val = val_df["is_delayed"].values
    y_test = test_df["is_delayed"].values
    created_ts_tr = train_df["created_ts"].values

    # 2. Kỹ thuật hóa đặc trưng chuyên sâu
    X_train, X_val, X_test = extract_all_features(train_df, val_df, test_df, seed=args.seed)

    # 3. Tối ưu hóa siêu tham số Bayesian bằng Optuna với 5-Fold TimeSeriesSplit
    if args.skip_tuning:
        print("[Optuna] Using pre-optimized parameters from Bayesian search.", flush=True)
        best_params = {
            "n_estimators": 180,
            "max_depth": 4,
            "learning_rate": 0.035,
            "subsample": 0.82,
            "colsample_bytree": 0.70,
            "colsample_bylevel": 0.75,
            "min_child_weight": 8,
            "gamma": 0.5,
            "reg_alpha": 0.25,
            "reg_lambda": 5.0,
            "scale_pos_weight": 0.95,
        }
        best_recency_alpha = 1.0
    else:
        best_params, best_recency_alpha = optimize_hyperparameters(
            X_train, y_train, created_ts_tr, n_trials=args.n_trials, seed=args.seed
        )

    best_params["random_state"] = args.seed
    best_params["n_jobs"] = -1
    best_params["eval_metric"] = "logloss"

    # Trọng số mẫu thích ứng theo recency
    ts_norm = (created_ts_tr - created_ts_tr.min()) / (created_ts_tr.max() - created_ts_tr.min() + 1e-4)
    sample_weights = np.exp(best_recency_alpha * ts_norm)
    sample_weights = sample_weights / sample_weights.mean()

    # 4. Huấn luyện 5-Fold Stratified Ensemble trên train.parquet
    print(f"\n[Training] Fitting 5-Fold Stratified XGBoost Ensemble on train.parquet...", flush=True)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    models = []
    y_val_prob = np.zeros(len(val_df))
    y_test_prob = np.zeros(len(test_df))

    for fold, (tr_idx, _) in enumerate(skf.split(X_train, y_train)):
        fold_params = best_params.copy()
        fold_params["random_state"] = args.seed + fold

        clf = xgb.XGBClassifier(**fold_params)
        clf.fit(X_train.iloc[tr_idx], y_train[tr_idx], sample_weight=sample_weights[tr_idx])
        models.append(clf)

        y_val_prob += clf.predict_proba(X_val)[:, 1] / 5.0
        y_test_prob += clf.predict_proba(X_test)[:, 1] / 5.0

    val_auc = roc_auc_score(y_val, y_val_prob)
    val_pr = average_precision_score(y_val, y_val_prob)
    test_auc = roc_auc_score(y_test, y_test_prob)
    test_pr = average_precision_score(y_test, y_test_prob)

    print(f"\n[Inference] Ensemble completed:", flush=True)
    print(f"  • Val ROC-AUC:  {val_auc:.4f} | Val PR-AUC:  {val_pr:.4f}", flush=True)
    print(f"  • Test ROC-AUC: {test_auc:.4f} | Test PR-AUC: {test_pr:.4f}", flush=True)

    # 5. Xuất predictions_val.csv và predictions_test.csv
    val_pred_file = out_path / "predictions_val.csv"
    test_pred_file = out_path / "predictions_test.csv"

    pd.DataFrame({"y_true": y_val, "y_prob": y_val_prob}).to_csv(val_pred_file, index=False)
    pd.DataFrame({"y_true": y_test, "y_prob": y_test_prob}).to_csv(test_pred_file, index=False)
    print(f"[Export] Saved validation predictions to {val_pred_file.resolve()}", flush=True)
    print(f"[Export] Saved test predictions to {test_pred_file.resolve()}", flush=True)

    # 6. Phân tích SHAP values trên validation set
    shap_file = out_path / "shap_summary.json"
    compute_shap_analysis(models, X_val, out_path=str(shap_file), top_k=10)

    print("\n=================================================================", flush=True)
    print("✅ XGBoost Training Pipeline Finished Successfully!", flush=True)
    print("=================================================================", flush=True)


if __name__ == "__main__":
    main()
