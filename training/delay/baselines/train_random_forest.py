"""Pipeline Huấn luyện & Tối ưu hóa Random Forest & Ensemble Bagging Resampling
với Probability Calibration và Rolling 90-day Velocity Features
cho bài toán Dự đoán Nguy cơ Trễ hạn Issue (is_delayed = 1).

Chức năng:
1. Feature Engineering chuyên sâu:
   - Rolling 90-day Velocity: assignee_90d_completed, assignee_90d_delay_rate, assignee_90d_cycle_time.
   - Project & Reporter 90d Velocity: project_90d_delay_rate, reporter_90d_delay_rate, v.v.
   - Workload & Capacity Dynamics: active_per_completed (#1 SHAP), active_per_90d, load shares.
   - Schedule Compression: scf, scf_90d, cycle_gap_hist, cycle_gap_90d.
   - Ổn định dịch chuyển phân phối Unassigned (Unassigned Drift Stabilization).
   - Graph Dependency Centrality & NLP Text Complexity.
2. Thử nghiệm In-CV Balancing (SMOTE / RandomOverSampler / class_weight="balanced_subsample")
   với TimeSeriesSplit 5-Fold.
3. Tối ưu hóa siêu tham số bằng TimeSeriesSplit.
4. Probability Calibration (CalibratedClassifierCV với isotonic regression trên validation folds)
   để hiệu chuẩn xác suất và giảm thiểu Brier Score.
5. Quét ngưỡng tối ưu trên tập Validation (Threshold Sweep T in [0.10, 0.90]).
6. Xuất kết quả dự đoán và phân tích Feature Importance vào feature_importance.json & rf_importance.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from imblearn.ensemble import BalancedRandomForestClassifier
from imblearn.over_sampling import SMOTE, BorderlineSMOTE, RandomOverSampler
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Khai thác sâu các đặc trưng rolling velocity, tải công việc, tương tác phi tuyến, graph và NLP."""
    d = df.copy()

    # 1. Nhận diện issue unassigned và tỷ lệ phân bổ
    is_un = (d["assignee"] == "(unassigned)").astype(int)
    d["is_unassigned"] = is_un

    # 2. Động thái tải công việc và năng lực xử lý (Workload & Capacity Dynamics)
    d["active_per_completed"] = d["assignee_active_count"] / (d["assignee_hist_completed"] + 1.0)
    d["active_per_90d"] = d["assignee_active_count"] / (d["assignee_90d_completed"] + 1.0)
    d["project_active_per_90d"] = d["project_active_count"] / (d["project_90d_completed"] + 1.0)
    d["assignee_load_share"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)
    d["unassigned_load_share"] = d["unassigned_active_count"] / (d["project_active_count"] + 1.0)
    d["wci_per_active"] = d["assignee_wci"] / (d["assignee_active_count"] + 1.0)
    d["assignee_workload_share"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)

    # 3. Xu hướng vận tốc và độ trôi dạt hiệu suất gần đây (Rolling 90-day Velocity & Trends)
    d["assignee_delay_velocity"] = d["assignee_90d_delay_rate"] - d["assignee_hist_delay_rate"]
    d["assignee_cycle_velocity"] = d["assignee_90d_cycle_time"] - d["assignee_hist_cycle_time"]
    d["reporter_delay_velocity"] = d["reporter_90d_delay_rate"] - d["reporter_hist_delay_rate"]
    d["project_delay_vs_baseline"] = d["project_90d_delay_rate"] - 0.5
    d["combined_90d_delay"] = (d["assignee_90d_delay_rate"] + d["reporter_90d_delay_rate"]) / 2.0
    d["combined_hist_delay"] = (d["assignee_hist_delay_rate"] + d["reporter_hist_delay_rate"]) / 2.0

    # 4. Hệ số nén thời gian và chu kỳ hoàn thành (Schedule Compression & Cycle Time Gaps)
    d["scf_90d"] = d["planned_duration_days"] / (d["assignee_90d_cycle_time"] + 1e-4)
    d["scf_project_90d"] = d["planned_duration_days"] / (d["project_90d_cycle_time"] + 1e-4)
    d["scf_inverted"] = d["assignee_hist_cycle_time"] / (d["planned_duration_days"] + 1e-4)
    d["is_schedule_compressed"] = (d["scf"] < 1.0).astype(int)
    d["is_extreme_compressed"] = (d["scf"] < 0.5).astype(int)
    d["cycle_gap_hist"] = d["assignee_hist_cycle_time"] - d["planned_duration_days"]
    d["cycle_gap_90d"] = d["assignee_90d_cycle_time"] - d["planned_duration_days"]
    d["is_cycle_exceed"] = (d["assignee_hist_cycle_time"] > d["planned_duration_days"]).astype(int)

    # 5. Ổn định hiện tượng dịch chuyển phân phối Unassigned (Unassigned Drift Stabilization)
    d["unassigned_velocity_risk"] = is_un * d["unassigned_90d_delay_rate"]
    d["unassigned_congestion"] = is_un * (d["unassigned_active_count"] / (d["project_active_count"] + 1.0))
    d["unassigned_sp_pressure"] = is_un * d["sp_planned_ratio"]
    d["unassigned_tight_deadline"] = is_un * (d["planned_duration_days"] <= 14.0).astype(int)
    d["unassigned_sp_planned"] = is_un * d["story_points"] * d["planned_duration_days"]

    # 6. Tương tác tải công việc phi tuyến và áp lực deadline (Pressure & Workload Interactions)
    d["pressure_index"] = (d["story_points"] * d["assignee_wci"]) / (d["scf"] * d["planned_duration_days"] + 1e-4)
    d["sp_per_active"] = d["story_points"] / (d["assignee_active_count"] + 1.0)
    d["sp_x_planned"] = d["story_points"] * d["planned_duration_days"]
    d["sp_div_planned"] = d["story_points"] / (d["planned_duration_days"] + 1e-4)
    d["wci_x_scf"] = d["assignee_wci"] * d["scf"]
    d["is_tight_deadline"] = (d["planned_duration_days"] <= 14.0).astype(int)
    d["is_standard_deadline"] = (d["planned_duration_days"] == 45.0).astype(int)
    d["is_loose_deadline"] = (d["planned_duration_days"] >= 90.0).astype(int)

    # 7. Độ ưu tiên và kinh nghiệm nhân sự (Priority & Experience Flags)
    d["is_blocker_or_critical"] = (d["priority_norm"] >= 0.8).astype(int)
    d["is_high_priority"] = (d["priority_norm"] >= 0.6).astype(int)
    d["is_normal_priority"] = ((d["priority_norm"] >= 0.4) & (d["priority_norm"] < 0.6)).astype(int)
    d["priority_planned_ratio"] = d["priority_norm"] / (d["planned_duration_days"] + 1e-4)
    d["assignee_experience_flag"] = (d["assignee_hist_completed"] > 50).astype(int)
    d["assignee_new_flag"] = (d["assignee_hist_completed"] == 0).astype(int)
    d["reporter_experience_flag"] = (d["reporter_hist_completed"] > 20).astype(int)
    d["reporter_new_flag"] = (d["reporter_hist_completed"] == 0).astype(int)

    # 8. Cấu trúc mạng phụ thuộc (Graph Dependency Centrality)
    d["has_links"] = (d["num_links"] > 0).astype(int)
    d["is_isolated"] = (d["num_links"] == 0).astype(int)
    d["has_dependencies"] = (d["depends_count"] > 0).astype(int)
    d["has_blockers"] = (d["blocks_count"] > 0).astype(int)
    d["link_density"] = d["depends_count"] / (d["num_links"] + 1e-5)
    d["links_per_story_point"] = d["num_links"] / (d["story_points"] + 1.0)
    d["dependency_complexity"] = d["depends_count"] * d["story_points"]
    d["dep_density"] = (d["blocks_count"] + 1.0) * (d["depends_count"] + 1.0)

    # 9. Độ phức tạp văn bản và chỉ số mơ hồ (NLP Text Complexity)
    d["char_per_word"] = d["summary_len"] / (d["word_count"] + 1e-4)
    d["has_ambiguity"] = (d["ambiguity_score"] > 0).astype(int)
    d["is_long_summary"] = (d["summary_len"] > 80).astype(int)
    d["is_short_summary"] = (d["summary_len"] < 30).astype(int)
    d["ambiguous_words_est"] = d["ambiguity_score"] * d["word_count"]

    # Keyword indicators trong summary
    if "summary" in d.columns:
        s_lower = d["summary"].fillna("").astype(str).str.lower()
        for kw in ["fix", "bug", "crash", "error", "fail", "test", "release", "leak", "slow", "support"]:
            d[f"kw_{kw}"] = s_lower.str.contains(kw, regex=False).astype(int)

    # 10. Lịch và tính chu kỳ (Calendar Cyclical Features)
    d["month_sin"] = np.sin(2 * np.pi * d["created_month"] / 12)
    d["month_cos"] = np.cos(2 * np.pi * d["created_month"] / 12)
    d["dow_sin"] = np.sin(2 * np.pi * d["created_dayofweek"] / 7)
    d["dow_cos"] = np.cos(2 * np.pi * d["created_dayofweek"] / 7)
    d["is_weekend"] = (d["created_dayofweek"] >= 5).astype(int)

    return d


def find_optimal_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    min_precision: float = 0.70,
    min_recall: float = 0.70,
) -> tuple[float, float, float, float]:
    """Quét ngưỡng quyết định T in [0.05, 0.95] tối ưu hóa F1 trên tập Validation."""
    best_thr = 0.5
    best_f1 = 0.0
    best_p = 0.0
    best_r = 0.0

    candidate_best_thr = 0.5
    candidate_best_f1 = 0.0
    candidate_best_p = 0.0
    candidate_best_r = 0.0

    for thr in np.arange(0.05, 0.95, 0.01):
        preds = (y_prob >= thr).astype(int)
        p = precision_score(y_true, preds, zero_division=0)
        r = recall_score(y_true, preds, zero_division=0)
        f1 = f1_score(y_true, preds, zero_division=0)

        if f1 > candidate_best_f1:
            candidate_best_f1 = f1
            candidate_best_thr = float(thr)
            candidate_best_p = float(p)
            candidate_best_r = float(r)

        if p >= min_precision and r >= min_recall and f1 > best_f1:
            best_f1 = f1
            best_thr = float(thr)
            best_p = float(p)
            best_r = float(r)

    if best_f1 == 0.0:
        best_thr = candidate_best_thr
        best_f1 = candidate_best_f1
        best_p = candidate_best_p
        best_r = candidate_best_r

    return best_thr, best_f1, best_p, best_r


def train_and_evaluate(
    data_dir: str = "data",
    output_dir: str = "experiments/randomforest",
    tune_hyperparams: bool = False,
    random_state: int = 42,
) -> dict[str, Any]:
    print("\n" + "=" * 65)
    print("🌲 RANDOM FOREST & RESAMPLING PIPELINE V2 (CALIBRATED ENSEMBLE)")
    print("=" * 65)

    # 1. Đọc dữ liệu Train / Val / Test
    train_path = Path(data_dir) / "train.parquet"
    val_path = Path(data_dir) / "val.parquet"
    test_path = Path(data_dir) / "test.parquet"

    print(f"[Data] Loading datasets from {data_dir}...")
    train_df = pd.read_parquet(train_path)
    val_df = pd.read_parquet(val_path)
    test_df = pd.read_parquet(test_path)

    print(f"  • Train: {train_df.shape} (delay_rate={train_df['is_delayed'].mean():.4f})")
    print(f"  • Val:   {val_df.shape} (delay_rate={val_df['is_delayed'].mean():.4f})")
    print(f"  • Test:  {test_df.shape} (delay_rate={test_df['is_delayed'].mean():.4f})")

    # 2. Khai thác đặc trưng chuyên sâu
    print("[Feature Engineering] Extracting rolling velocity, workload, and stabilization features...")
    tr_feat = extract_features(train_df)
    va_feat = extract_features(val_df)
    te_feat = extract_features(test_df)

    # Loại bỏ các cột ID, temporal leakage và cột text thô để tránh tạo dummy thưa thớt
    drop_cols = [
        "issue_key",
        "is_delayed",
        "assignee",
        "reporter",
        "created_ts",
        "created_year",
        "summary",
        "priority_raw",
    ]
    feature_cols = [c for c in tr_feat.columns if c not in drop_cols]

    # Mã hóa One-Hot đồng bộ qua kết hợp Train/Val/Test
    combined = pd.concat([tr_feat, va_feat, te_feat], axis=0)
    combined_encoded = pd.get_dummies(combined[feature_cols], drop_first=True)

    n_tr = len(tr_feat)
    n_va = len(va_feat)

    X_train = combined_encoded.iloc[:n_tr].copy()
    y_train = train_df["is_delayed"].values.astype(int)

    X_val = combined_encoded.iloc[n_tr : n_tr + n_va].copy()
    y_val = val_df["is_delayed"].values.astype(int)

    X_test = combined_encoded.iloc[n_tr + n_va :].copy()
    y_test = test_df["is_delayed"].values.astype(int)

    feature_names = list(X_train.columns)
    print(f"[Feature Engineering] Final clean feature dimension: {len(feature_names)}")

    # 3. Đánh giá In-CV Balancing bằng TimeSeriesSplit (5 Folds - Chuẩn phi rò rỉ thời gian)
    print("\n[Cross-Validation] Benchmarking In-CV Resampling & Balancing via 5-Fold TimeSeriesSplit...")
    tscv = TimeSeriesSplit(n_splits=5)

    cv_models = {
        "RF_BalancedSubsample": RandomForestClassifier(
            n_estimators=200, max_depth=10, min_samples_split=6, min_samples_leaf=4,
            class_weight="balanced_subsample", random_state=random_state, n_jobs=-1
        ),
        "BalancedRF": BalancedRandomForestClassifier(
            n_estimators=200, max_depth=10, min_samples_leaf=4,
            random_state=random_state, n_jobs=-1
        ),
        "ROS_RF": ImbPipeline([
            ("ros", RandomOverSampler(random_state=random_state)),
            ("rf", RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_split=6, min_samples_leaf=4, random_state=random_state, n_jobs=-1))
        ]),
        "SMOTE_RF": ImbPipeline([
            ("smote", SMOTE(random_state=random_state)),
            ("rf", RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_split=6, min_samples_leaf=4, random_state=random_state, n_jobs=-1))
        ]),
        "BorderlineSMOTE_RF": ImbPipeline([
            ("bsmote", BorderlineSMOTE(random_state=random_state)),
            ("rf", RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_split=6, min_samples_leaf=4, random_state=random_state, n_jobs=-1))
        ]),
    }

    for name, model in cv_models.items():
        pr_scores, roc_scores = [], []
        for tr_idx, vl_idx in tscv.split(X_train):
            X_tr_f, y_tr_f = X_train.iloc[tr_idx], y_train[tr_idx]
            X_vl_f, y_vl_f = X_train.iloc[vl_idx], y_train[vl_idx]
            model.fit(X_tr_f, y_tr_f)
            probs = model.predict_proba(X_vl_f)[:, 1]
            pr_scores.append(average_precision_score(y_vl_f, probs))
            roc_scores.append(roc_auc_score(y_vl_f, probs))
        print(f"  • {name:<22}: TimeSeries CV PR-AUC = {np.mean(pr_scores):.4f} | ROC-AUC = {np.mean(roc_scores):.4f}")

    # 4. Tinh chỉnh siêu tham số nếu được yêu cầu
    if tune_hyperparams:
        print("\n[Hyperparameter Tuning] Running RandomizedSearchCV with TimeSeriesSplit on Train...")
        param_dist = {
            "n_estimators": [250, 350, 450],
            "max_depth": [8, 10, 12, 14],
            "min_samples_split": [4, 6, 10],
            "min_samples_leaf": [2, 4, 6],
            "max_features": ["sqrt", 0.30, 0.40],
        }
        base_rf = RandomForestClassifier(class_weight="balanced_subsample", random_state=random_state, n_jobs=-1)
        rsearch = RandomizedSearchCV(
            base_rf,
            param_distributions=param_dist,
            n_iter=12,
            cv=tscv,
            scoring="roc_auc",
            random_state=random_state,
            n_jobs=-1,
        )
        rsearch.fit(X_train, y_train)
        print(f"[Hyperparameter Tuning] Best Params: {rsearch.best_params_} (Best ROC-AUC: {rsearch.best_score_:.4f})")
        best_params = rsearch.best_params_
    else:
        best_params = {
            "n_estimators": 350,
            "max_depth": 10,
            "min_samples_split": 6,
            "min_samples_leaf": 4,
            "max_features": 0.25,
        }

    # 5. Huấn luyện các mô hình thành phần & Áp dụng Probability Calibration
    print("\n[Training & Calibration] Fitting models & calibrating probabilities via TimeSeriesSplit...")

    # Model 1: RandomForestClassifier với class_weight="balanced_subsample" + CalibratedClassifierCV
    rf_balanced = RandomForestClassifier(
        n_estimators=best_params["n_estimators"],
        max_depth=best_params["max_depth"],
        min_samples_split=best_params["min_samples_split"],
        min_samples_leaf=best_params["min_samples_leaf"],
        max_features=best_params["max_features"],
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )
    rf_balanced.fit(X_train, y_train)
    cal_rf_balanced = CalibratedClassifierCV(estimator=rf_balanced, method="isotonic", cv=tscv)
    cal_rf_balanced.fit(X_train, y_train)

    # Model 2: RandomOverSampler + RandomForestClassifier + CalibratedClassifierCV
    ros_pipe = ImbPipeline([
        ("ros", RandomOverSampler(random_state=random_state)),
        ("rf", RandomForestClassifier(
            n_estimators=best_params["n_estimators"],
            max_depth=best_params["max_depth"],
            min_samples_split=best_params["min_samples_split"],
            min_samples_leaf=best_params["min_samples_leaf"],
            max_features=best_params["max_features"],
            random_state=random_state,
            n_jobs=-1,
        )),
    ])
    cal_ros = CalibratedClassifierCV(estimator=ros_pipe, method="isotonic", cv=tscv)
    cal_ros.fit(X_train, y_train)

    # Model 3: BalancedRandomForestClassifier (Bagging cân bằng)
    balanced_rf = BalancedRandomForestClassifier(
        n_estimators=best_params["n_estimators"],
        max_depth=best_params["max_depth"],
        min_samples_leaf=best_params["min_samples_leaf"],
        max_features=best_params["max_features"],
        random_state=random_state,
        n_jobs=-1,
    )
    balanced_rf.fit(X_train, y_train)

    # Model 4: SMOTE + RandomForestClassifier + CalibratedClassifierCV
    smote_pipe = ImbPipeline([
        ("smote", SMOTE(random_state=random_state)),
        ("rf", RandomForestClassifier(
            n_estimators=best_params["n_estimators"],
            max_depth=best_params["max_depth"],
            min_samples_split=best_params["min_samples_split"],
            min_samples_leaf=best_params["min_samples_leaf"],
            max_features=best_params["max_features"],
            random_state=random_state,
            n_jobs=-1,
        )),
    ])
    cal_smote = CalibratedClassifierCV(estimator=smote_pipe, method="isotonic", cv=tscv)
    cal_smote.fit(X_train, y_train)

    # 6. Dự đoán xác suất Ensemble kết hợp Calibrated và Bagging Probas
    print("[Ensemble Blending] Aggregating calibrated & bagging probabilities...")
    p_va_cal1 = cal_rf_balanced.predict_proba(X_val)[:, 1]
    p_va_raw1 = rf_balanced.predict_proba(X_val)[:, 1]
    p_va_cal2 = cal_ros.predict_proba(X_val)[:, 1]
    p_va_raw3 = balanced_rf.predict_proba(X_val)[:, 1]
    p_va_cal4 = cal_smote.predict_proba(X_val)[:, 1]

    p_te_cal1 = cal_rf_balanced.predict_proba(X_test)[:, 1]
    p_te_raw1 = rf_balanced.predict_proba(X_test)[:, 1]
    p_te_cal2 = cal_ros.predict_proba(X_test)[:, 1]
    p_te_raw3 = balanced_rf.predict_proba(X_test)[:, 1]
    p_te_cal4 = cal_smote.predict_proba(X_test)[:, 1]

    # Weighted Ensemble Blending
    val_prob = 0.35 * p_va_cal1 + 0.35 * p_va_cal2 + 0.20 * p_va_raw1 + 0.10 * p_va_raw3
    test_prob = 0.35 * p_te_cal1 + 0.35 * p_te_cal2 + 0.20 * p_te_raw1 + 0.10 * p_te_raw3

    # 7. Quét ngưỡng tối ưu (Threshold Sweep T in [0.10, 0.90]) trên tập Validation
    print("\n[Threshold Sweep] Finding optimal decision threshold on Validation set...")
    opt_thr, val_f1, val_p, val_r = find_optimal_threshold(y_val, val_prob)
    print(f"  • Optimal Threshold: {opt_thr:.4f}")
    print(f"  • Validation F1:    {val_f1:.4f} (Precision: {val_p:.4f}, Recall: {val_r:.4f})")

    # 8. Đánh giá trên Out-of-time Test Set
    test_preds = (test_prob >= opt_thr).astype(int)
    test_f1 = float(f1_score(y_test, test_preds, zero_division=0))
    test_prec = float(precision_score(y_test, test_preds, zero_division=0))
    test_rec = float(recall_score(y_test, test_preds, zero_division=0))
    test_roc_auc = float(roc_auc_score(y_test, test_prob))
    test_pr_auc = float(average_precision_score(y_test, test_prob))
    test_brier = float(brier_score_loss(y_test, test_prob))

    cm = confusion_matrix(y_test, test_preds)
    tn, fp, fn, tp = [int(v) for v in cm.ravel()]

    print(f"\n[Test Evaluation Metrics @ Thr={opt_thr:.4f}]:")
    print(f"  • Test F1-Score: {test_f1:.4f}")
    print(f"  • Precision:     {test_prec:.4f}")
    print(f"  • Recall:        {test_rec:.4f}")
    print(f"  • PR-AUC:        {test_pr_auc:.4f}")
    print(f"  • ROC-AUC:       {test_roc_auc:.4f}")
    print(f"  • Brier Score:   {test_brier:.4f}")
    print(f"  • Confusion Matrix: TP={tp}, FP={fp}, TN={tn}, FN={fn}")

    # 9. Xuất kết quả dự đoán ra experiments/randomforest/
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    val_pred_df = pd.DataFrame({"y_true": y_val, "y_prob": np.round(val_prob, 6)})
    val_pred_file = out_dir / "predictions_val.csv"
    val_pred_df.to_csv(val_pred_file, index=False)
    print(f"\n[Artifacts] Saved validation predictions to {val_pred_file}")

    test_pred_df = pd.DataFrame({"y_true": y_test, "y_prob": np.round(test_prob, 6)})
    test_pred_file = out_dir / "predictions_test.csv"
    test_pred_df.to_csv(test_pred_file, index=False)
    print(f"[Artifacts] Saved test predictions to {test_pred_file}")

    # 10. Trích xuất Feature Importance tổng hợp
    print("\n[Feature Importance] Computing aggregated Mean Decrease in Impurity (MDI)...")
    imp_list = []
    # Từ rf_balanced
    imp_list.append(rf_balanced.feature_importances_)
    # Từ balanced_rf
    imp_list.append(balanced_rf.feature_importances_)
    # Từ các fold của cal_rf_balanced
    for entry in cal_rf_balanced.calibrated_classifiers_:
        imp_list.append(entry.estimator.feature_importances_)
    # Từ các fold của cal_ros
    for entry in cal_ros.calibrated_classifiers_:
        base = entry.estimator
        if hasattr(base, "named_steps"):
            imp_list.append(base.named_steps["rf"].feature_importances_)
        else:
            imp_list.append(base.feature_importances_)

    combined_importances = np.mean(imp_list, axis=0)
    feat_imp_series = pd.Series(combined_importances, index=feature_names).sort_values(ascending=False)

    importance_dict = {
        "track": "randomforest",
        "n_features": len(feature_names),
        "top_features": {k: round(float(v), 6) for k, v in feat_imp_series.head(40).items()},
        "rolling_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in [
                "assignee_90d_delay_rate",
                "assignee_90d_cycle_time",
                "project_90d_delay_rate",
                "project_90d_cycle_time",
                "unassigned_90d_delay_rate",
                "unassigned_active_count",
                "active_per_completed",
                "active_per_90d",
            ]
        },
        "dependency_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in ["blocks_count", "depends_count", "has_block_or_depend", "num_links", "link_density", "dependency_complexity"]
        },
        "workload_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in ["assignee_wci", "scf", "scf_90d", "assignee_active_count", "wci_per_active", "assignee_workload_share", "cycle_gap_hist", "cycle_gap_90d"]
        },
        "nlp_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in ["ambiguity_score", "summary_len", "word_count", "char_per_word", "ambiguous_words_est"]
        },
    }

    # Lưu vào cả feature_importance.json và rf_importance.json để tương thích toàn diện
    imp_file = out_dir / "feature_importance.json"
    with open(imp_file, "w", encoding="utf-8") as f:
        json.dump(importance_dict, f, indent=2, ensure_ascii=False)
    print(f"[Artifacts] Saved feature importance analysis to {imp_file}")

    rf_imp_file = out_dir / "rf_importance.json"
    with open(rf_imp_file, "w", encoding="utf-8") as f:
        json.dump(importance_dict, f, indent=2, ensure_ascii=False)
    print(f"[Artifacts] Saved alias feature importance analysis to {rf_imp_file}")

    print("\n[Top 10 Most Important Features]:")
    for rank, (feat, val_imp) in enumerate(feat_imp_series.head(10).items(), 1):
        print(f"  {rank:>2}. {feat:<32}: {val_imp:.5f}")

    return {
        "val_f1": val_f1,
        "test_f1": test_f1,
        "test_prec": test_prec,
        "test_rec": test_rec,
        "optimal_threshold": opt_thr,
        "test_roc_auc": test_roc_auc,
        "test_pr_auc": test_pr_auc,
        "test_brier": test_brier,
        "top_5_features": list(feat_imp_series.head(5).index),
    }


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate Random Forest & Bagging Resampling Pipeline V2")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing train, val, test parquet files")
    parser.add_argument("--output-dir", type=str, default="experiments/randomforest", help="Directory to save predictions and artifacts")
    parser.add_argument("--tune", action="store_true", help="Perform hyperparameter tuning with RandomizedSearchCV")
    parser.add_argument("--seed", type=int, default=42, help="Random state seed")
    args = parser.parse_args()

    train_and_evaluate(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        tune_hyperparams=args.tune,
        random_state=args.seed,
    )


if __name__ == "__main__":
    main()
