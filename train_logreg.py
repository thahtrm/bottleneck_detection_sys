"""Pipeline Huấn Luyện Logistic Regression Nâng Cao (Advanced Linear Pipeline & Splines)
Dự đoán Nguy cơ Trễ hạn Issue (is_delayed = 1).

Các kỹ thuật nâng cao áp dụng:
1. Chuẩn hóa phi tuyến: Yeo-Johnson PowerTransformer cho các đặc trưng lệch (WCI, cycle time, workload, project active).
2. Biến đổi phi tuyến B-splines: SplineTransformer(n_knots=5, degree=3) cho các biến liên tục quan trọng
   (sp_planned_ratio, scf, project_active_count, priority_norm).
3. Tương tác phi tuyến bậc cao: PolynomialFeatures(degree=2, interaction_only=True) cho cụm tải trọng và thời gian.
4. One-hot encoding với drop='first' cho categorical (project, issuetype_theme, issuetype, priority_raw).
5. TF-IDF n-grams từ trường summary (top 30 features quan trọng).
6. Tối ưu hóa ElasticNet (C, l1_ratio) bằng Optuna với TimeSeriesSplit trên train set.
7. Hiệu chuẩn xác suất bằng Platt scaling (CalibratedClassifierCV với FrozenEstimator).
8. Quét ngưỡng tối ưu trên tập Validation thỏa mãn ràng buộc Precision >= 0.70 và Recall >= 0.70.
9. Xuất kết quả dự đoán (val, test) và hệ số hồi quy (top_coefficients.json).
"""
from __future__ import annotations

import argparse
import json
import os
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import (
    OneHotEncoder,
    PolynomialFeatures,
    PowerTransformer,
    SplineTransformer,
    StandardScaler,
)

from evaluation_harness import find_optimal_threshold

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)


def engineer_domain_features(df: pd.DataFrame) -> pd.DataFrame:
    """Xây dựng các đặc trưng miền nghiệp vụ phi tuyến và xử lý missing values."""
    d = df.copy()

    # Xử lý missing values
    d["priority_raw"] = d["priority_raw"].fillna("Major")
    d["priority_norm"] = d["priority_norm"].fillna(0.4)
    d["assignee"] = d["assignee"].fillna("(unassigned)")
    d["reporter"] = d["reporter"].fillna("(unassigned)")
    d["project"] = d["project"].fillna("Unknown")
    d["issuetype"] = d["issuetype"].fillna("Bug")
    d["issuetype_theme"] = d["issuetype_theme"].fillna("Other")
    d["summary"] = d["summary"].fillna("")

    # 1. Assignment indicators & Workload dynamics
    d["is_unassigned"] = (d["assignee"] == "(unassigned)").astype(float)
    d["is_unassigned_reporter"] = (d["reporter"] == "(unassigned)").astype(float)
    d["assignee_load_ratio"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)
    d["active_per_completed"] = d["assignee_active_count"] / (d["assignee_hist_completed"] + 1.0)

    # 2. Cycle time vs Planned duration
    d["cycle_vs_planned"] = d["assignee_hist_cycle_time"] / (d["planned_duration_days"] + 1e-4)
    d["cycle_minus_planned"] = d["assignee_hist_cycle_time"] - d["planned_duration_days"]
    d["delay_risk_score"] = d["assignee_hist_delay_rate"] * d["reporter_hist_delay_rate"]
    d["delay_risk_90d"] = d["assignee_90d_delay_rate"] * d["reporter_90d_delay_rate"]
    d["high_risk_planned"] = (d["planned_duration_days"] <= 30).astype(float)
    d["high_priority"] = (d["priority_norm"] >= 0.6).astype(float)
    d["tight_deadline"] = (d["planned_duration_days"] < d["assignee_hist_cycle_time"]).astype(float)
    d["sp_per_planned_day"] = d["story_points"] / (d["planned_duration_days"] + 1e-4)

    # 3. Unassigned Drift Mitigation (Interactions with task size and rolling 90d delay)
    d["unassigned_risk_90d"] = d["is_unassigned"] * d["unassigned_90d_delay_rate"]

    # 4. Graph dependencies
    d["total_deps"] = (d["blocks_count"] + d["depends_count"]).astype(float)

    # 5. Log-transforms cho các biến lệch dương
    d["log_project_active"] = np.log1p(np.maximum(0, d["project_active_count"]))
    d["log_assignee_active"] = np.log1p(np.maximum(0, d["assignee_active_count"]))
    d["log_assignee_completed"] = np.log1p(np.maximum(0, d["assignee_hist_completed"]))
    d["log_reporter_completed"] = np.log1p(np.maximum(0, d["reporter_hist_completed"]))
    d["log_assignee_cycle_time"] = np.log1p(np.maximum(0, d["assignee_hist_cycle_time"]))
    d["log_planned_days"] = np.log1p(np.maximum(0, d["planned_duration_days"]))
    d["log_story_points"] = np.log1p(np.maximum(0, d["story_points"]))
    d["log_assignee_wci"] = np.log1p(np.maximum(0, d["assignee_wci"]))
    d["log_scf"] = np.log1p(np.maximum(0, d["scf"]))

    return d


class AdvancedLinearFeaturePipeline:
    """Pipeline trích xuất và biến đổi đặc trưng phi tuyến chuyên biệt cho mô hình tuyến tính."""

    def __init__(self):
        # 1. B-splines cho các biến liên tục quan trọng
        self.spline_cols = ["sp_planned_ratio", "scf", "project_active_count", "priority_norm"]
        self.spline = SplineTransformer(n_knots=5, degree=3, include_bias=False, extrapolation="linear")

        # 2. Polynomial interaction cho cụm tải trọng và thời gian
        self.poly_cols = [
            "assignee_wci",
            "scf",
            "planned_duration_days",
            "story_points",
            "ambiguity_score",
            "active_per_completed",
        ]
        self.poly = PolynomialFeatures(degree=2, interaction_only=True, include_bias=False)

        # 3. Yeo-Johnson PowerTransformer cho các biến lệch
        self.skew_cols = [
            "assignee_wci",
            "assignee_hist_cycle_time",
            "assignee_90d_cycle_time",
            "project_90d_cycle_time",
            "project_active_count",
            "assignee_active_count",
            "unassigned_active_count",
            "assignee_hist_completed",
            "assignee_90d_completed",
            "reporter_hist_completed",
            "reporter_90d_completed",
            "project_90d_completed",
            "planned_duration_days",
            "story_points",
            "sp_planned_product",
            "summary_len",
            "word_count",
            "active_per_completed",
            "cycle_vs_planned",
            "cycle_minus_planned",
        ]
        self.power_transformer = PowerTransformer(method="yeo-johnson")

        # 4. Normalized core numeric & domain indicators
        self.norm_cols = [
            "priority_norm",
            "sp_planned_ratio",
            "scf",
            "assignee_hist_delay_rate",
            "assignee_90d_delay_rate",
            "reporter_hist_delay_rate",
            "reporter_90d_delay_rate",
            "project_90d_delay_rate",
            "unassigned_90d_delay_rate",
            "delay_risk_score",
            "delay_risk_90d",
            "ambiguity_score",
            "num_links",
            "has_block_or_depend",
            "total_deps",
            "is_unassigned",
            "is_unassigned_reporter",
            "unassigned_risk_90d",
            "high_risk_planned",
            "high_priority",
            "tight_deadline",
            "sp_per_planned_day",
            "log_project_active",
            "log_assignee_active",
            "log_assignee_completed",
            "log_reporter_completed",
            "log_assignee_cycle_time",
            "log_planned_days",
            "log_story_points",
            "log_assignee_wci",
            "log_scf",
        ]

        # 5. One-Hot Encoding cho Categorical
        self.ohe_cols = ["project", "issuetype_theme", "issuetype", "priority_raw"]
        self.one_hot_encoder = OneHotEncoder(drop="first", sparse_output=False, handle_unknown="ignore")

        # 6. TF-IDF n-grams từ Summary (top 30 features)
        self.tfidf = TfidfVectorizer(max_features=30, ngram_range=(1, 2), stop_words="english", sublinear_tf=True)

        # 7. Standard Scaler toàn bộ đặc trưng
        self.scaler = StandardScaler()
        self.feature_names: list[str] = []

    def fit_transform(self, df: pd.DataFrame) -> np.ndarray:
        # 1. Spline
        x_spline = self.spline.fit_transform(df[self.spline_cols])
        sp_names = list(self.spline.get_feature_names_out(self.spline_cols))

        # 2. Polynomial
        x_poly = self.poly.fit_transform(df[self.poly_cols])
        poly_names = list(self.poly.get_feature_names_out(self.poly_cols))

        # 3. Power Transformer
        x_pt = self.power_transformer.fit_transform(df[self.skew_cols])
        pt_names = [f"pt_{c}" for c in self.skew_cols]

        # 4. Normalized core
        x_norm = df[self.norm_cols].values

        # 5. One-Hot
        x_ohe = self.one_hot_encoder.fit_transform(df[self.ohe_cols])
        ohe_names = list(self.one_hot_encoder.get_feature_names_out(self.ohe_cols))

        # 6. TF-IDF
        x_tfidf = self.tfidf.fit_transform(df["summary"]).toarray()
        tf_names = [f"tfidf_{w}" for w in self.tfidf.get_feature_names_out()]

        # Concatenate & Scale
        x_raw = np.hstack([x_spline, x_poly, x_pt, x_norm, x_ohe, x_tfidf])
        self.feature_names = sp_names + poly_names + pt_names + self.norm_cols + ohe_names + tf_names

        x_scaled = self.scaler.fit_transform(x_raw)
        return x_scaled

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        x_spline = self.spline.transform(df[self.spline_cols])
        x_poly = self.poly.transform(df[self.poly_cols])
        x_pt = self.power_transformer.transform(df[self.skew_cols])
        x_norm = df[self.norm_cols].values
        x_ohe = self.one_hot_encoder.transform(df[self.ohe_cols])
        x_tfidf = self.tfidf.transform(df["summary"]).toarray()

        x_raw = np.hstack([x_spline, x_poly, x_pt, x_norm, x_ohe, x_tfidf])
        x_scaled = self.scaler.transform(x_raw)
        return x_scaled


def optimize_elasticnet_hyperparameters(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    n_trials: int = 30,
) -> tuple[dict[str, Any], LogisticRegression]:
    """Tối ưu hóa ElasticNet (C, l1_ratio) bằng Optuna với TimeSeriesSplit trên train set."""
    print("  • Running Bayesian Optimization (Optuna) with 4-Fold TimeSeriesSplit on Train...")
    tscv = TimeSeriesSplit(n_splits=4)

    best_score = -1.0
    best_candidate_params = {"C": 0.02, "l1_ratio": 0.5}

    def objective(trial: optuna.Trial) -> float:
        c = trial.suggest_float("C", 0.001, 0.05, log=True)
        l1 = trial.suggest_float("l1_ratio", 0.05, 0.7)

        fold_scores = []
        for tr_idx, val_idx in tscv.split(x_train):
            clf = LogisticRegression(
                solver="saga",
                C=c,
                l1_ratio=l1,
                max_iter=500,
                random_state=42,
            )
            clf.fit(x_train[tr_idx], y_train[tr_idx])
            val_probs = clf.predict_proba(x_train[val_idx])[:, 1]
            score = average_precision_score(y_train[val_idx], val_probs)
            fold_scores.append(score)

        return float(np.mean(fold_scores))

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials)

    print(f"  • Optuna Best CV PR-AUC: {study.best_value:.4f} with params: {study.best_params}")

    # Danh sách các ứng viên kết hợp từ Optuna và lưới mở rộng tinh chỉnh
    candidate_list = [
        study.best_params,
        {"C": 0.020, "l1_ratio": 0.50},
        {"C": 0.015, "l1_ratio": 0.50},
        {"C": 0.010, "l1_ratio": 0.20},
        {"C": 0.008, "l1_ratio": 0.30},
        {"C": 0.005, "l1_ratio": 0.20},
        {"C": 0.003, "l1_ratio": 0.20},
    ]

    best_clf = None
    best_val_f1 = -1.0
    best_params = {}
    best_meets_constraints = False

    for params in candidate_list:
        clf = LogisticRegression(
            solver="saga",
            C=params["C"],
            l1_ratio=params["l1_ratio"],
            max_iter=1000,
            tol=1e-3,
            random_state=42,
        )
        clf.fit(x_train, y_train)

        va_prob = clf.predict_proba(x_val)[:, 1]
        thr, f1, prec, rec = find_optimal_threshold(y_val, va_prob, min_precision=0.70, min_recall=0.70)
        meets_constraints = (prec >= 0.70) and (rec >= 0.70)

        is_better = False
        if meets_constraints and not best_meets_constraints:
            is_better = True
        elif meets_constraints == best_meets_constraints:
            if f1 > best_val_f1:
                is_better = True

        if is_better:
            best_val_f1 = f1
            best_clf = clf
            best_params = params
            best_meets_constraints = meets_constraints

    print(
        f"  ★ Selected Best ElasticNet: C={best_params['C']:.4f}, l1_ratio={best_params['l1_ratio']:.4f} "
        f"(Val F1: {best_val_f1:.4f}, Constraints Met: {best_meets_constraints})"
    )

    return best_params, best_clf


def train_and_evaluate(
    data_dir: str = "data",
    output_dir: str = "experiments/logreg",
) -> dict[str, Any]:
    print("[1/5] Loading datasets...")
    train_df = pd.read_parquet(f"{data_dir}/train.parquet")
    val_df = pd.read_parquet(f"{data_dir}/val.parquet")
    test_df = pd.read_parquet(f"{data_dir}/test.parquet")

    print(f"  • Train: {len(train_df)} rows, base delay rate = {train_df['is_delayed'].mean():.4f}")
    print(f"  • Val:   {len(val_df)} rows, base delay rate = {val_df['is_delayed'].mean():.4f}")
    print(f"  • Test:  {len(test_df)} rows, base delay rate = {test_df['is_delayed'].mean():.4f}")

    print("[2/5] Engineering domain features and executing transformation pipelines...")
    tr_feat = engineer_domain_features(train_df)
    va_feat = engineer_domain_features(val_df)
    te_feat = engineer_domain_features(test_df)

    y_train = tr_feat["is_delayed"].values.astype(int)
    y_val = va_feat["is_delayed"].values.astype(int)
    y_test = te_feat["is_delayed"].values.astype(int)

    pipeline = AdvancedLinearFeaturePipeline()
    x_train = pipeline.fit_transform(tr_feat)
    x_val = pipeline.transform(va_feat)
    x_test = pipeline.transform(te_feat)

    print(f"  • Transformed feature space dimension: {x_train.shape[1]} features")

    print("[3/5] Hyperparameter optimization and probability calibration...")
    best_params, base_clf = optimize_elasticnet_hyperparameters(x_train, y_train, x_val, y_val, n_trials=30)

    # Hiệu chuẩn xác suất bằng Platt scaling (CalibratedClassifierCV với FrozenEstimator)
    calibrated_clf = CalibratedClassifierCV(FrozenEstimator(base_clf), method="sigmoid")
    calibrated_clf.fit(x_train, y_train)

    val_probs = calibrated_clf.predict_proba(x_val)[:, 1]
    test_probs = calibrated_clf.predict_proba(x_test)[:, 1]

    # Quét ngưỡng tối ưu trên tập Validation
    val_thr, val_f1, val_p, val_r = find_optimal_threshold(y_val, val_probs, min_precision=0.70, min_recall=0.70)
    print(f"  • Optimal Validation Threshold: {val_thr:.2f} (F1: {val_f1:.4f}, Prec: {val_p:.4f}, Rec: {val_r:.4f})")

    print("[4/5] Exporting predictions and model coefficients...")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    val_pred_file = out_path / "predictions_val.csv"
    test_pred_file = out_path / "predictions_test.csv"

    pd.DataFrame({"y_true": y_val, "y_prob": val_probs}).to_csv(val_pred_file, index=False)
    pd.DataFrame({"y_true": y_test, "y_prob": test_probs}).to_csv(test_pred_file, index=False)
    print(f"  • Exported: {val_pred_file}")
    print(f"  • Exported: {test_pred_file}")

    # Trích xuất hệ số hồi quy (Coefficients)
    coefs = base_clf.coef_[0]
    intercept = float(base_clf.intercept_[0])
    coef_df = pd.DataFrame({
        "feature": pipeline.feature_names,
        "coefficient": coefs,
        "abs_coefficient": np.abs(coefs),
    }).sort_values(by="abs_coefficient", ascending=False)

    top_positive = coef_df[coef_df["coefficient"] > 0].head(15).to_dict(orient="records")
    top_negative = coef_df[coef_df["coefficient"] < 0].head(15).to_dict(orient="records")

    top_coefficients_dict = {
        "model_type": "LogisticRegression(ElasticNet + Splines + PowerTransformer + TFIDF + CalibratedClassifierCV)",
        "hyperparameters": {
            "C": float(best_params["C"]),
            "l1_ratio": float(best_params["l1_ratio"]),
            "solver": "saga",
            "calibration": "sigmoid (Platt scaling)",
        },
        "intercept": round(intercept, 6),
        "total_features": len(pipeline.feature_names),
        "top_positive_risk_factors": [
            {"feature": r["feature"], "coefficient": round(float(r["coefficient"]), 6)} for r in top_positive
        ],
        "top_negative_protective_factors": [
            {"feature": r["feature"], "coefficient": round(float(r["coefficient"]), 6)} for r in top_negative
        ],
    }

    # Xuất file top_coefficients.json và coefficients.json
    top_coef_file = out_path / "top_coefficients.json"
    coef_file = out_path / "coefficients.json"

    with open(top_coef_file, "w", encoding="utf-8") as f:
        json.dump(top_coefficients_dict, f, indent=2, ensure_ascii=False)
    with open(coef_file, "w", encoding="utf-8") as f:
        json.dump(top_coefficients_dict, f, indent=2, ensure_ascii=False)

    print(f"  • Exported: {top_coef_file}")
    print(f"  • Exported: {coef_file}")

    print("[5/5] Pipeline training and export complete.")
    return {
        "val_pred_file": str(val_pred_file),
        "test_pred_file": str(test_pred_file),
        "top_coef_file": str(top_coef_file),
        "coef_file": str(coef_file),
        "best_params": best_params,
        "val_f1": val_f1,
        "val_threshold": val_thr,
    }


if __name__ == "__main__":
    train_and_evaluate()
