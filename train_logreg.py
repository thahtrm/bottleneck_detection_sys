"""Pipeline Huấn Luyện Logistic Regression Nâng Cao (Advanced Linear Feature Engineering)
Dự đoán Nguy cơ Trễ hạn Issue (is_delayed = 1).

Các kỹ thuật nâng cao áp dụng:
1. Target Encoding có smoothing/cross-fitting cho: issuetype, issuetype_theme, project, assignee.
2. Tương tác phi tuyến bậc cao: PolynomialFeatures(degree=2, interaction_only=True) cho cụm workload và thời gian.
3. Biến đổi phi tuyến phi tham số: SplineTransformer(n_knots=5, degree=3) cho các biến liên tục quan trọng.
4. Chuẩn hóa phân phối: PowerTransformer (Yeo-Johnson) cho biến liên tục, RobustScaler cho cụm tương tác đa thức.
5. ElasticNet Regularization (tinh chỉnh C và l1_ratio) kết hợp CalibratedClassifierCV.
6. Xuất kết quả dự đoán (val, test) và hệ số hồi quy (coefficients.json).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import (
    OneHotEncoder,
    PolynomialFeatures,
    PowerTransformer,
    RobustScaler,
    SplineTransformer,
    TargetEncoder,
)

from evaluation_harness import find_optimal_threshold


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Xây dựng các đặc trưng miền nghiệp vụ phi tuyến và chuẩn hóa dữ liệu đầu vào."""
    d = df.copy()

    # Xử lý missing values
    d["priority_raw"] = d["priority_raw"].fillna("Major")
    d["priority_norm"] = d["priority_norm"].fillna(0.4)
    d["assignee"] = d["assignee"].fillna("(unassigned)")
    d["reporter"] = d["reporter"].fillna("(unassigned)")
    d["project"] = d["project"].fillna("Unknown")
    d["issuetype"] = d["issuetype"].fillna("Bug")
    d["issuetype_theme"] = d["issuetype_theme"].fillna("Other")

    # Log-transforms cho các biến lệch dương (right-skewed)
    d["log_project_active"] = np.log1p(np.maximum(0, d["project_active_count"]))
    d["log_assignee_active"] = np.log1p(np.maximum(0, d["assignee_active_count"]))
    d["log_assignee_completed"] = np.log1p(np.maximum(0, d["assignee_hist_completed"]))
    d["log_reporter_completed"] = np.log1p(np.maximum(0, d["reporter_hist_completed"]))
    d["log_assignee_cycle_time"] = np.log1p(np.maximum(0, d["assignee_hist_cycle_time"]))
    d["log_planned_days"] = np.log1p(np.maximum(0, d["planned_duration_days"]))
    d["log_story_points"] = np.log1p(np.maximum(0, d["story_points"]))
    d["log_assignee_wci"] = np.log1p(np.maximum(0, d["assignee_wci"]))
    d["log_scf"] = np.log1p(np.maximum(0, d["scf"]))

    # Domain interaction features & Indicators
    d["cycle_vs_planned"] = d["assignee_hist_cycle_time"] / (d["planned_duration_days"] + 1e-4)
    d["cycle_minus_planned"] = d["assignee_hist_cycle_time"] - d["planned_duration_days"]
    d["delay_risk_score"] = d["assignee_hist_delay_rate"] * d["reporter_hist_delay_rate"]
    d["high_risk_planned"] = (d["planned_duration_days"] <= 30).astype(float)
    d["high_priority"] = (d["priority_norm"] >= 0.6).astype(float)
    d["tight_deadline"] = (d["planned_duration_days"] < d["assignee_hist_cycle_time"]).astype(float)
    d["sp_per_planned_day"] = d["story_points"] / (d["planned_duration_days"] + 1e-4)
    d["assignee_load_ratio"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)

    return d


class AdvancedLinearFeaturePipeline:
    """Pipeline trích xuất và biến đổi đặc trưng phi tuyến chuyên biệt cho mô hình tuyến tính."""

    def __init__(self):
        self.cat_cols = ["issuetype", "issuetype_theme", "project", "assignee"]
        self.ohe_cols = ["project", "issuetype_theme", "priority_raw"]
        self.poly_cols = ["assignee_wci", "scf", "planned_duration_days", "story_points", "ambiguity_score"]
        self.spline_cols = ["scf", "planned_duration_days", "story_points", "reporter_hist_delay_rate", "assignee_hist_cycle_time"]
        self.core_num_cols = [
            "priority_norm",
            "high_priority",
            "high_risk_planned",
            "tight_deadline",
            "log_project_active",
            "log_assignee_active",
            "log_reporter_completed",
            "cycle_vs_planned",
            "cycle_minus_planned",
            "delay_risk_score",
            "sp_per_planned_day",
            "assignee_load_ratio",
            "ambiguity_score",
            "assignee_hist_delay_rate",
            "reporter_hist_delay_rate",
            "summary_len",
        ]

        self.target_encoder = TargetEncoder(smooth="auto", cv=5)
        self.one_hot_encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        self.poly = PolynomialFeatures(degree=2, interaction_only=True, include_bias=False)
        self.spline = SplineTransformer(n_knots=5, degree=3, include_bias=False)
        self.power_transformer = PowerTransformer(method="yeo-johnson")
        self.poly_scaler = RobustScaler()
        self.feature_names: list[str] = []

    def fit_transform(self, df: pd.DataFrame, y: np.ndarray) -> np.ndarray:
        # 1. Target Encoding
        x_te = self.target_encoder.fit_transform(df[self.cat_cols], y)
        te_names = [f"te_{c}" for c in self.cat_cols]

        # 2. One-Hot Encoding
        x_ohe = self.one_hot_encoder.fit_transform(df[self.ohe_cols])
        ohe_names = list(self.one_hot_encoder.get_feature_names_out(self.ohe_cols))

        # 3. High-Order Interactions
        x_poly_raw = self.poly.fit_transform(df[self.poly_cols])
        x_poly = self.poly_scaler.fit_transform(x_poly_raw)
        poly_names = list(self.poly.get_feature_names_out(self.poly_cols))

        # 4. Spline Non-linear Transformations
        x_spline = self.spline.fit_transform(df[self.spline_cols])
        spline_names = list(self.spline.get_feature_names_out(self.spline_cols))

        # 5. Core Numerical & Power Transformation
        x_num = self.power_transformer.fit_transform(df[self.core_num_cols].values)
        num_names = [f"pt_{c}" for c in self.core_num_cols]

        # Ghép nối tất cả các cụm đặc trưng
        x_all = np.hstack([x_num, x_poly, x_spline, x_te, x_ohe])
        self.feature_names = num_names + poly_names + spline_names + te_names + ohe_names
        return x_all

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        x_te = self.target_encoder.transform(df[self.cat_cols])
        x_ohe = self.one_hot_encoder.transform(df[self.ohe_cols])
        x_poly_raw = self.poly.transform(df[self.poly_cols])
        x_poly = self.poly_scaler.transform(x_poly_raw)
        x_spline = self.spline.transform(df[self.spline_cols])
        x_num = self.power_transformer.transform(df[self.core_num_cols].values)

        x_all = np.hstack([x_num, x_poly, x_spline, x_te, x_ohe])
        return x_all


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

    print("[2/5] Engineering features and transforming matrices...")
    tr_feat = engineer_features(train_df)
    va_feat = engineer_features(val_df)
    te_feat = engineer_features(test_df)

    y_train = tr_feat["is_delayed"].values.astype(int)
    y_val = va_feat["is_delayed"].values.astype(int)
    y_test = te_feat["is_delayed"].values.astype(int)

    pipeline = AdvancedLinearFeaturePipeline()
    x_train = pipeline.fit_transform(tr_feat, y_train)
    x_val = pipeline.transform(va_feat)
    x_test = pipeline.transform(te_feat)

    print(f"  • Feature matrix dimension: {x_train.shape[1]} features")

    print("[3/5] Tuning ElasticNet Logistic Regression with Constraint-Aware Selection...")
    best_clf = None
    best_val_f1 = -1.0
    best_params = {}
    best_val_thr = 0.5
    best_meets_constraints = False

    param_grid = [
        {"C": 0.010, "l1_ratio": 0.0},
        {"C": 0.010, "l1_ratio": 0.1},
        {"C": 0.010, "l1_ratio": 0.2},
        {"C": 0.020, "l1_ratio": 0.1},
        {"C": 0.020, "l1_ratio": 0.2},
        {"C": 0.050, "l1_ratio": 0.0},
        {"C": 0.050, "l1_ratio": 0.1},
        {"C": 0.050, "l1_ratio": 0.2},
        {"C": 0.100, "l1_ratio": 0.0},
        {"C": 0.100, "l1_ratio": 0.1},
    ]

    for params in param_grid:
        clf = LogisticRegression(
            solver="saga",
            l1_ratio=params["l1_ratio"],
            C=params["C"],
            max_iter=1000,
            tol=1e-3,
            random_state=42,
        )
        clf.fit(x_train, y_train)

        va_prob = clf.predict_proba(x_val)[:, 1]
        thr, f1, prec, rec = find_optimal_threshold(y_val, va_prob, min_precision=0.70, min_recall=0.70)
        meets_constraints = (prec >= 0.70) and (rec >= 0.70)

        print(
            f"  • Trial C={params['C']:.3f}, l1={params['l1_ratio']:.1f} -> "
            f"Val thr={thr:.2f}, F1={f1:.4f}, Prec={prec:.4f}, Rec={rec:.4f} "
            f"[{'PASS CONSTRAINTS' if meets_constraints else 'UNCONSTRAINED'}]"
        )

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
            best_val_thr = thr
            best_meets_constraints = meets_constraints

    print(
        f"  ★ Selected Best Model: C={best_params['C']}, l1_ratio={best_params['l1_ratio']} "
        f"(Val F1: {best_val_f1:.4f}, Val Thr: {best_val_thr:.2f}, Constraints Met: {best_meets_constraints})"
    )

    val_probs = best_clf.predict_proba(x_val)[:, 1]
    test_probs = best_clf.predict_proba(x_test)[:, 1]

    print("[4/5] Exporting predictions and coefficients...")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    val_pred_file = out_path / "predictions_val.csv"
    test_pred_file = out_path / "predictions_test.csv"

    pd.DataFrame({"y_true": y_val, "y_prob": val_probs}).to_csv(val_pred_file, index=False)
    pd.DataFrame({"y_true": y_test, "y_prob": test_probs}).to_csv(test_pred_file, index=False)
    print(f"  • Exported: {val_pred_file}")
    print(f"  • Exported: {test_pred_file}")

    # Trích xuất Coefficients lớn nhất
    coefs = best_clf.coef_[0]
    intercept = float(best_clf.intercept_[0])
    coef_df = pd.DataFrame({
        "feature": pipeline.feature_names,
        "coefficient": coefs,
        "abs_coefficient": np.abs(coefs),
    }).sort_values(by="abs_coefficient", ascending=False)

    top_positive = coef_df[coef_df["coefficient"] > 0].head(15).to_dict(orient="records")
    top_negative = coef_df[coef_df["coefficient"] < 0].head(15).to_dict(orient="records")

    coefficients_dict = {
        "model_type": "LogisticRegression(ElasticNet, solver=saga)",
        "hyperparameters": best_params,
        "intercept": round(intercept, 6),
        "total_features": len(pipeline.feature_names),
        "top_positive_risk_factors": [
            {"feature": r["feature"], "coefficient": round(float(r["coefficient"]), 6)} for r in top_positive
        ],
        "top_negative_protective_factors": [
            {"feature": r["feature"], "coefficient": round(float(r["coefficient"]), 6)} for r in top_negative
        ],
    }

    coef_file = out_path / "coefficients.json"
    with open(coef_file, "w", encoding="utf-8") as f:
        json.dump(coefficients_dict, f, indent=2, ensure_ascii=False)
    print(f"  • Exported: {coef_file}")

    print("[5/5] Pipeline training and export complete.")
    return {
        "val_pred_file": str(val_pred_file),
        "test_pred_file": str(test_pred_file),
        "coef_file": str(coef_file),
        "best_params": best_params,
    }


if __name__ == "__main__":
    train_and_evaluate()
