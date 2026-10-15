"""Pipeline Gradient Boosting (XGBoost) chuyên sâu cho dự đoán nguy cơ trễ hạn Issue.

Chức năng:
1. Feature Engineering chuyên sâu:
   - Tương tác phi tuyến giữa WCI, SCF, Story Points, Planned Duration.
   - Tỷ lệ tải công việc, độ trễ lịch sử (assignee, reporter).
   - Mật độ tương tác graph dependency.
   - Độ mơ hồ yêu cầu (ambiguity_score) và độ phức tạp văn bản.
2. Tối ưu hàm mất mát chi phí với scale_pos_weight.
3. Bayesian Hyperparameter Optimization bằng Optuna với 5-Fold TimeSeriesSplit trên train.parquet.
4. Huấn luyện 5-Fold Stratified Ensemble với các siêu tham số tối ưu.
5. Xuất predictions_val.csv và predictions_test.csv.
6. Tính toán SHAP values và trích xuất Top 10 đặc trưng quan trọng nhất vào shap_summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit

optuna.logging.set_verbosity(optuna.logging.WARNING)


def build_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tạo các đặc trưng chuyên sâu và tương tác phi tuyến theo yêu cầu kỹ thuật."""
    d = df.copy()

    # 1. Assignment indicators & workload ratios
    d["is_unassigned"] = (d["assignee"] == "(unassigned)").astype(int)
    d["is_unassigned_reporter"] = (d["reporter"] == "(unassigned)").astype(int)
    d["assignee_load_ratio"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)
    d["active_per_completed"] = d["assignee_active_count"] / (d["assignee_hist_completed"] + 1.0)
    d["log_assignee_active"] = np.log1p(np.maximum(0, d["assignee_active_count"]))
    d["log_project_active"] = np.log1p(np.maximum(0, d["project_active_count"]))
    d["log_assignee_completed"] = np.log1p(np.maximum(0, d["assignee_hist_completed"]))
    d["log_reporter_completed"] = np.log1p(np.maximum(0, d["reporter_hist_completed"]))

    # 2. Tương tác phi tuyến giữa WCI, SCF, Story Points và Planned Duration
    d["wci_x_scf"] = d["assignee_wci"] * d["scf"]
    d["wci_div_scf"] = d["assignee_wci"] / (d["scf"] + 1e-4)
    d["sp_x_scf"] = d["story_points"] * d["scf"]
    d["sp_div_scf"] = d["story_points"] / (d["scf"] + 1e-4)
    d["sp_x_planned"] = d["story_points"] * d["planned_duration_days"]
    d["sp_div_planned"] = d["story_points"] / (d["planned_duration_days"] + 1e-4)
    d["wci_x_planned"] = d["assignee_wci"] * d["planned_duration_days"]
    d["wci_div_planned"] = d["assignee_wci"] / (d["planned_duration_days"] + 1e-4)
    d["wci_x_sp"] = d["assignee_wci"] * d["story_points"]
    d["wci_div_sp"] = d["assignee_wci"] / (d["story_points"] + 1e-4)
    d["pressure_index"] = (d["story_points"] * d["assignee_wci"]) / (d["scf"] * d["planned_duration_days"] + 1e-4)
    d["scf_sq"] = d["scf"] ** 2
    d["log_scf"] = np.log1p(np.maximum(0, d["scf"]))
    d["log_wci"] = np.log1p(np.maximum(0, d["assignee_wci"]))
    d["is_compressed"] = (d["scf"] < 1.0).astype(int)
    d["is_extreme_compressed"] = (d["scf"] < 0.5).astype(int)
    d["is_high_wci"] = (d["assignee_wci"] > 50).astype(int)
    d["is_low_wci"] = (d["assignee_wci"] < 10).astype(int)

    # 3. Tỷ lệ tải công việc, độ trễ lịch sử
    d["mean_hist_delay"] = (d["assignee_hist_delay_rate"] + d["reporter_hist_delay_rate"]) / 2.0
    d["diff_hist_delay"] = d["assignee_hist_delay_rate"] - d["reporter_hist_delay_rate"]
    d["prod_hist_delay"] = d["assignee_hist_delay_rate"] * d["reporter_hist_delay_rate"]
    d["assignee_delay_risk"] = d["assignee_hist_delay_rate"] * d["log_assignee_completed"]
    d["reporter_delay_risk"] = d["reporter_hist_delay_rate"] * d["log_reporter_completed"]
    d["cycle_vs_planned"] = d["assignee_hist_cycle_time"] / (d["planned_duration_days"] + 1e-4)
    d["cycle_minus_planned"] = d["assignee_hist_cycle_time"] - d["planned_duration_days"]

    # 4. Mật độ tương tác graph dependency
    d["total_deps"] = d["blocks_count"] + d["depends_count"]
    d["has_links"] = (d["num_links"] > 0).astype(int)
    d["has_blocks"] = (d["blocks_count"] > 0).astype(int)
    d["has_depends"] = (d["depends_count"] > 0).astype(int)
    d["dep_density"] = (d["blocks_count"] + 1.0) * (d["depends_count"] + 1.0)
    d["links_per_sp"] = d["num_links"] / (d["story_points"] + 1e-4)

    # 5. Đặc trưng độ mơ hồ yêu cầu và độ dài văn bản
    d["chars_per_word"] = d["summary_len"] / np.maximum(1, d["word_count"])
    d["has_ambiguity"] = (d["ambiguity_score"] > 0).astype(int)
    d["high_ambiguity"] = (d["ambiguity_score"] > 0.1).astype(int)
    d["ambiguity_words"] = d["ambiguity_score"] * d["word_count"]
    d["sp_per_word"] = d["story_points"] / np.maximum(1, d["word_count"])

    # 6. Priority & Calendar
    d["is_high_priority"] = (d["priority_norm"] >= 0.8).astype(int)
    d["is_low_priority"] = (d["priority_norm"] <= 0.4).astype(int)
    d["sin_month"] = np.sin(2 * np.pi * d["created_month"] / 12.0)
    d["cos_month"] = np.cos(2 * np.pi * d["created_month"] / 12.0)
    d["sin_dow"] = np.sin(2 * np.pi * d["created_dayofweek"] / 7.0)
    d["cos_dow"] = np.cos(2 * np.pi * d["created_dayofweek"] / 7.0)

    # 7. Categoricals mã hóa
    for col in ["project", "issuetype", "issuetype_theme"]:
        d[col] = d[col].astype("category").cat.codes

    drops = ["issue_key", "created_ts", "created_year", "priority_raw", "assignee", "reporter", "is_delayed"]
    feat_cols = [c for c in d.columns if c not in drops]
    return d[feat_cols]


def optimize_hyperparameters(
    X: pd.DataFrame,
    y: np.ndarray,
    n_trials: int = 35,
    seed: int = 42,
) -> dict:
    """Tối ưu hóa siêu tham số Bayesian bằng Optuna với 5-Fold TimeSeriesSplit."""
    print(f"\n[Optuna] Starting Bayesian Optimization ({n_trials} trials, 5-Fold TimeSeriesSplit)...")

    tscv = TimeSeriesSplit(n_splits=5)
    default_scale_pos = float((len(y) - y.sum()) / y.sum())

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 300, step=25),
            "max_depth": trial.suggest_int("max_depth", 3, 6),
            "learning_rate": trial.suggest_float("learning_rate", 0.015, 0.08, log=True),
            "subsample": trial.suggest_float("subsample", 0.70, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.65, 0.90),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 5.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 15.0, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 2, 7),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.85 * default_scale_pos, 1.20 * default_scale_pos),
            "random_state": seed,
            "n_jobs": -1,
            "eval_metric": "logloss",
        }

        pr_auc_scores = []
        for train_idx, val_idx in tscv.split(X):
            X_tr, y_tr = X.iloc[train_idx], y[train_idx]
            X_va, y_va = X.iloc[val_idx], y[val_idx]

            model = xgb.XGBClassifier(**params)
            model.fit(X_tr, y_tr)
            preds_prob = model.predict_proba(X_va)[:, 1]
            score = average_precision_score(y_va, preds_prob)
            pr_auc_scores.append(score)

        return float(np.mean(pr_auc_scores))

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    print(f"\n[Optuna] Optimization finished! Best Mean PR-AUC: {study.best_value:.4f}")
    print("[Optuna] Best parameters:")
    for k, v in study.best_params.items():
        print(f"  • {k}: {v}")

    return study.best_params


def compute_shap_analysis(
    models: list[xgb.XGBClassifier],
    X_val: pd.DataFrame,
    out_path: str = "experiments/xgboost/shap_summary.json",
    top_k: int = 10,
) -> list[dict]:
    """Tính SHAP values trên validation set và lưu Top 10 đặc trưng quan trọng nhất."""
    print(f"\n[SHAP] Computing SHAP values across ensemble on validation set ({len(X_val)} samples)...")
    all_shap = []
    for model in models:
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_val)
        all_shap.append(np.abs(shap_vals))

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

    print(f"[SHAP] Top {top_k} features saved to {out_file.resolve()}:")
    for rank, item in enumerate(top_features, 1):
        print(f"  {rank:2d}. {item['feature']:30s} : {item['mean_abs_shap']:.5f}")

    return top_features


def main():
    parser = argparse.ArgumentParser(description="Train and Optimize XGBoost Pipeline for Issue Delay Prediction")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing train.parquet, val.parquet, test.parquet")
    parser.add_argument("--output-dir", type=str, default="experiments/xgboost", help="Directory to save predictions and SHAP summary")
    parser.add_argument("--n-trials", type=int, default=35, help="Number of Optuna trials")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--skip-tuning", action="store_true", help="Skip Optuna and use pre-optimized default parameters")

    args = parser.parse_args()
    data_path = Path(args.data_dir)
    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("=================================================================")
    print("🚀 TRAINING GRADIENT BOOSTING (XGBOOST) PIPELINE")
    print("=================================================================")

    # 1. Load Data
    t0 = time.time()
    train_df = pd.read_parquet(data_path / "train.parquet")
    val_df = pd.read_parquet(data_path / "val.parquet")
    test_df = pd.read_parquet(data_path / "test.parquet")
    print(f"[Data] Loaded Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)} in {time.time()-t0:.2f}s")

    y_train = train_df["is_delayed"].values
    y_val = val_df["is_delayed"].values
    y_test = test_df["is_delayed"].values

    # 2. Feature Engineering
    print("[Feature Engineering] Generating nonlinear and domain-specific features...")
    X_train = build_engineered_features(train_df)
    X_val = build_engineered_features(val_df)
    X_test = build_engineered_features(test_df)
    print(f"[Feature Engineering] Extracted {X_train.shape[1]} features.")

    # 3. Hyperparameter Optimization
    if args.skip_tuning:
        print("[Optuna] Using pre-optimized parameters from Bayesian search.")
        best_params = {
            "n_estimators": 150,
            "max_depth": 4,
            "learning_rate": 0.02,
            "subsample": 0.85,
            "colsample_bytree": 0.75,
            "reg_alpha": 0.05,
            "reg_lambda": 5.0,
            "min_child_weight": 4,
            "scale_pos_weight": 1.0,
        }
    else:
        best_params = optimize_hyperparameters(X_train, y_train, n_trials=args.n_trials, seed=args.seed)

    best_params["random_state"] = args.seed
    best_params["n_jobs"] = -1
    best_params["eval_metric"] = "logloss"

    # 4. Huấn luyện 5-Fold Stratified Ensemble trên train.parquet
    print("\n[Training] Fitting 5-Fold Stratified XGBoost Ensemble on train.parquet...")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    models = []
    y_val_prob = np.zeros(len(val_df))
    y_test_prob = np.zeros(len(test_df))

    for fold, (tr_idx, val_idx) in enumerate(skf.split(X_train, y_train)):
        fold_params = best_params.copy()
        fold_params["random_state"] = args.seed + fold

        clf = xgb.XGBClassifier(**fold_params)
        clf.fit(X_train.iloc[tr_idx], y_train[tr_idx])
        models.append(clf)

        y_val_prob += clf.predict_proba(X_val)[:, 1] / 5.0
        y_test_prob += clf.predict_proba(X_test)[:, 1] / 5.0

    print(f"[Inference] Ensemble completed. Val ROC-AUC: {roc_auc_score(y_val, y_val_prob):.4f}, Test ROC-AUC: {roc_auc_score(y_test, y_test_prob):.4f}")

    # 5. Lưu predictions_val.csv và predictions_test.csv
    val_pred_file = out_path / "predictions_val.csv"
    test_pred_file = out_path / "predictions_test.csv"

    pd.DataFrame({"y_true": y_val, "y_prob": y_val_prob}).to_csv(val_pred_file, index=False)
    pd.DataFrame({"y_true": y_test, "y_prob": y_test_prob}).to_csv(test_pred_file, index=False)
    print(f"[Export] Saved validation predictions to {val_pred_file.resolve()}")
    print(f"[Export] Saved test predictions to {test_pred_file.resolve()}")

    # 6. Phân tích SHAP values
    shap_file = out_path / "shap_summary.json"
    compute_shap_analysis(models, X_val, out_path=str(shap_file), top_k=10)

    print("\n=================================================================")
    print("✅ XGBoost Training Pipeline Finished Successfully!")
    print("=================================================================")


if __name__ == "__main__":
    main()
