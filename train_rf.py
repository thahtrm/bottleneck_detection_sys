"""Pipeline Huấn luyện & Tối ưu hóa Random Forest & Ensemble Bagging Resampling
cho bài toán Dự đoán Nguy cơ Trễ hạn Issue (is_delayed = 1).

Đặc trưng chính:
1. Graph Dependency Centrality (blocks_count, depends_count, has_block_or_depend, num_links, link density).
2. Assignee Workload Congestion Index (assignee_wci, scf, assignee_active_count, cycle_time_gap, personal vs unassigned).
3. NLP Text Complexity (ambiguity_score, summary_len, word_count, char_per_word, ambiguous_words_est).
4. Ensemble Bagging & Resampling:
   - BalancedRandomForestClassifier
   - RandomForestClassifier với class_weight="balanced_subsample"
   - BorderlineSMOTE & SMOTE bên trong imblearn.pipeline.Pipeline
5. Quét ngưỡng tối ưu (Threshold Sweep) trên val.parquet và suy luận trên test.parquet.
6. Lưu Feature Importance vào rf_importance.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Tuple

import numpy as np
import pandas as pd
from imblearn.combine import SMOTETomek
from imblearn.ensemble import BalancedRandomForestClassifier
from imblearn.over_sampling import BorderlineSMOTE, SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Khai thác sâu các đặc trưng phụ thuộc, cấu trúc, tải công việc, văn bản NLP và lịch."""
    d = df.copy()

    # Nhận diện issue unassigned
    is_un = (d["assignee"] == "(unassigned)").astype(int)
    d["is_unassigned"] = is_un

    # 1. Graph Dependency Centrality
    d["is_isolated"] = (d["num_links"] == 0).astype(int)
    d["has_dependencies"] = (d["depends_count"] > 0).astype(int)
    d["link_density"] = d["depends_count"] / (d["num_links"] + 1e-5)
    d["links_per_story_point"] = d["num_links"] / (d["story_points"] + 1.0)
    d["dependency_complexity"] = d["depends_count"] * d["story_points"]

    # 2. Assignee Workload & Historical Capacity
    d["wci_per_active"] = d["assignee_wci"] / (d["assignee_active_count"] + 1.0)
    d["assignee_workload_share"] = d["assignee_active_count"] / (d["project_active_count"] + 1.0)
    d["assignee_experience_flag"] = (d["assignee_hist_completed"] > 50).astype(int)
    d["assignee_new_flag"] = (d["assignee_hist_completed"] == 0).astype(int)
    d["scf_inverted"] = d["assignee_hist_cycle_time"] / (d["planned_duration_days"] + 1e-4)
    d["cycle_time_gap"] = d["assignee_hist_cycle_time"] - d["planned_duration_days"]
    d["is_cycle_exceed"] = (d["assignee_hist_cycle_time"] > d["planned_duration_days"]).astype(int)

    # 3. Reporter Capacity & Historical Delay Risk
    d["reporter_experience_flag"] = (d["reporter_hist_completed"] > 20).astype(int)
    d["reporter_new_flag"] = (d["reporter_hist_completed"] == 0).astype(int)
    d["combined_delay_risk"] = (d["assignee_hist_delay_rate"] + d["reporter_hist_delay_rate"]) / 2.0
    d["delay_rate_diff"] = d["assignee_hist_delay_rate"] - d["reporter_hist_delay_rate"]

    # 4. NLP Text Complexity & Ambiguity
    d["char_per_word"] = d["summary_len"] / (d["word_count"] + 1e-4)
    d["has_ambiguity"] = (d["ambiguity_score"] > 0).astype(int)
    d["is_long_summary"] = (d["summary_len"] > 80).astype(int)
    d["is_short_summary"] = (d["summary_len"] < 30).astype(int)
    d["ambiguous_words_est"] = d["ambiguity_score"] * d["word_count"]

    # 5. Planning, Deadlines & Project Context
    d["is_tight_deadline"] = (d["planned_duration_days"] <= 14.0).astype(int)
    d["is_standard_deadline"] = (d["planned_duration_days"] == 45.0).astype(int)
    d["is_loose_deadline"] = (d["planned_duration_days"] >= 90.0).astype(int)
    d["sp_per_active"] = d["story_points"] / (d["assignee_active_count"] + 1.0)
    d["planned_workload"] = d["story_points"] * d["planned_duration_days"]
    d["unassigned_tight_deadline"] = d["is_unassigned"] * d["is_tight_deadline"]

    # 6. Priority Features
    d["is_blocker_or_critical"] = (d["priority_norm"] >= 0.8).astype(int)
    d["is_high_priority"] = (d["priority_norm"] >= 0.6).astype(int)
    d["is_normal_priority"] = ((d["priority_norm"] >= 0.4) & (d["priority_norm"] < 0.6)).astype(int)
    d["priority_planned_ratio"] = d["priority_norm"] / (d["planned_duration_days"] + 1e-4)

    # 7. Calendar Cyclical Features
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
) -> Tuple[float, float, float, float]:
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
    print("\n" + "=" * 60)
    print("🌲 RANDOM FOREST & ENSEMBLE BAGGING PIPELINE")
    print("=" * 60)

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

    # 2. Khai thác đặc trưng
    print("[Feature Engineering] Generating graph, workload, and NLP features...")
    tr_feat = extract_features(train_df)
    va_feat = extract_features(val_df)
    te_feat = extract_features(test_df)

    # Bỏ các cột ID và cột thời gian trôi dạt phi dừng
    drop_cols = ["issue_key", "is_delayed", "assignee", "reporter", "created_ts", "created_year"]
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
    print(f"[Feature Engineering] Final feature dimension: {len(feature_names)}")

    # 3. Thử nghiệm Resampling & Bagging qua 5-Fold Cross-Validation trên tập Train
    print("\n[Cross-Validation] Benchmarking Resampling & Bagging inside Pipeline (Zero Leakage)...")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)

    cv_pipelines = {
        "RF_BalancedSubsample": ImbPipeline([
            ("rf", RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                          class_weight="balanced_subsample", random_state=random_state, n_jobs=-1))
        ]),
        "BalancedRF": ImbPipeline([
            ("brf", BalancedRandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                                   random_state=random_state, n_jobs=-1))
        ]),
        "SMOTE_RF": ImbPipeline([
            ("smote", SMOTE(random_state=random_state)),
            ("rf", RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                          random_state=random_state, n_jobs=-1))
        ]),
        "BorderlineSMOTE_RF": ImbPipeline([
            ("bsmote", BorderlineSMOTE(random_state=random_state)),
            ("rf", RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                          random_state=random_state, n_jobs=-1))
        ]),
        "SMOTETomek_RF": ImbPipeline([
            ("stomek", SMOTETomek(random_state=random_state)),
            ("rf", RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                          random_state=random_state, n_jobs=-1))
        ]),
    }

    cv_results = {}
    X_tr_arr = X_train.values
    for name, pipe in cv_pipelines.items():
        f1_list, auc_list = [], []
        for tr_idx, vl_idx in skf.split(X_tr_arr, y_train):
            pipe.fit(X_tr_arr[tr_idx], y_train[tr_idx])
            probs = pipe.predict_proba(X_tr_arr[vl_idx])[:, 1]
            preds = (probs >= 0.50).astype(int)
            f1_list.append(f1_score(y_train[vl_idx], preds, zero_division=0))
            auc_list.append(roc_auc_score(y_train[vl_idx], probs))
        mean_f1 = float(np.mean(f1_list))
        mean_auc = float(np.mean(auc_list))
        cv_results[name] = {"cv_f1": round(mean_f1, 4), "cv_roc_auc": round(mean_auc, 4)}
        print(f"  • {name:<22}: CV F1 = {mean_f1:.4f} (+/- {np.std(f1_list):.4f}) | CV ROC-AUC = {mean_auc:.4f}")

    # 4. Tinh chỉnh siêu tham số nếu được yêu cầu
    if tune_hyperparams:
        print("\n[Hyperparameter Tuning] Running RandomizedSearchCV on train.parquet...")
        param_dist = {
            "n_estimators": [200, 300, 400],
            "max_depth": [8, 10, 12, 15],
            "min_samples_split": [2, 5, 10],
            "min_samples_leaf": [2, 5, 10],
            "max_features": ["sqrt", "log2", 0.3],
        }
        base_rf = RandomForestClassifier(class_weight="balanced_subsample", random_state=random_state, n_jobs=-1)
        rsearch = RandomizedSearchCV(
            base_rf,
            param_distributions=param_dist,
            n_iter=15,
            cv=skf,
            scoring="f1",
            random_state=random_state,
            n_jobs=-1,
        )
        rsearch.fit(X_train, y_train)
        print(f"[Hyperparameter Tuning] Best Params: {rsearch.best_params_} (Best F1: {rsearch.best_score_:.4f})")
        best_params = rsearch.best_params_
    else:
        best_params = {
            "n_estimators": 400,
            "max_depth": 12,
            "min_samples_split": 5,
            "min_samples_leaf": 5,
            "max_features": "sqrt",
        }

    # 5. Huấn luyện Ensemble Bagging Resampling gồm:
    # Model A: RandomForestClassifier với class_weight="balanced_subsample"
    # Model B: BalancedRandomForestClassifier (Bagging cân bằng)
    # Model C: BorderlineSMOTE + RandomForestClassifier
    print("\n[Training] Fitting Ensemble Bagging & Resampling models on Train...")
    rf_balanced_subsample = RandomForestClassifier(
        n_estimators=best_params["n_estimators"],
        max_depth=best_params["max_depth"],
        min_samples_split=best_params["min_samples_split"],
        min_samples_leaf=best_params["min_samples_leaf"],
        max_features=best_params["max_features"],
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )
    rf_balanced_subsample.fit(X_train, y_train)

    balanced_rf = BalancedRandomForestClassifier(
        n_estimators=best_params["n_estimators"],
        max_depth=best_params["max_depth"],
        min_samples_leaf=best_params["min_samples_leaf"],
        max_features=best_params["max_features"],
        random_state=random_state,
        n_jobs=-1,
    )
    balanced_rf.fit(X_train, y_train)

    borderline_rf = ImbPipeline([
        ("bsmote", BorderlineSMOTE(random_state=random_state)),
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
    borderline_rf.fit(X_train, y_train)

    # 6. Dự đoán xác suất Ensemble
    val_prob_a = rf_balanced_subsample.predict_proba(X_val)[:, 1]
    val_prob_b = balanced_rf.predict_proba(X_val)[:, 1]
    val_prob_c = borderline_rf.predict_proba(X_val)[:, 1]

    # Weighted ensemble blending
    val_prob = 0.45 * val_prob_a + 0.45 * val_prob_b + 0.10 * val_prob_c

    test_prob_a = rf_balanced_subsample.predict_proba(X_test)[:, 1]
    test_prob_b = balanced_rf.predict_proba(X_test)[:, 1]
    test_prob_c = borderline_rf.predict_proba(X_test)[:, 1]
    test_prob = 0.45 * test_prob_a + 0.45 * test_prob_b + 0.10 * test_prob_c

    # 7. Quét ngưỡng quyết định (Threshold Sweep) trên val.parquet
    print("\n[Threshold Sweep] Finding optimal decision threshold on Validation set...")
    opt_thr, val_f1, val_p, val_r = find_optimal_threshold(y_val, val_prob)
    print(f"  • Optimal Threshold: {opt_thr:.4f}")
    print(f"  • Validation F1:    {val_f1:.4f} (Precision: {val_p:.4f}, Recall: {val_r:.4f})")

    # 8. Đánh giá sơ bộ trên Test Set
    test_preds = (test_prob >= opt_thr).astype(int)
    test_f1 = float(f1_score(y_test, test_preds, zero_division=0))
    test_prec = float(precision_score(y_test, test_preds, zero_division=0))
    test_rec = float(recall_score(y_test, test_preds, zero_division=0))
    test_roc_auc = float(roc_auc_score(y_test, test_prob))
    test_pr_auc = float(average_precision_score(y_test, test_prob))
    test_brier = float(brier_score_loss(y_test, test_prob))

    cm = confusion_matrix(y_test, test_preds)
    tn, fp, fn, tp = [int(v) for v in cm.ravel()]

    print(f"\n[Preliminary Test Metrics @ Thr={opt_thr:.4f}]:")
    print(f"  • Test F1:    {test_f1:.4f}")
    print(f"  • Precision:  {test_prec:.4f}")
    print(f"  • Recall:     {test_rec:.4f}")
    print(f"  • ROC-AUC:    {test_roc_auc:.4f}")
    print(f"  • PR-AUC:     {test_pr_auc:.4f}")
    print(f"  • Brier Loss: {test_brier:.4f}")
    print(f"  • CM: TP={tp}, FP={fp}, TN={tn}, FN={fn}")

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

    # 10. Phân tích Feature Importance và lưu vào rf_importance.json
    print("\n[Feature Importance] Computing Mean Decrease in Impurity (MDI)...")
    importances_a = rf_balanced_subsample.feature_importances_
    importances_b = balanced_rf.feature_importances_
    importances_c = borderline_rf.named_steps["rf"].feature_importances_

    combined_importances = 0.45 * importances_a + 0.45 * importances_b + 0.10 * importances_c
    feat_imp_series = pd.Series(combined_importances, index=feature_names).sort_values(ascending=False)

    importance_dict = {
        "track": "randomforest",
        "n_features": len(feature_names),
        "top_features": {k: round(float(v), 6) for k, v in feat_imp_series.head(40).items()},
        "dependency_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in ["blocks_count", "depends_count", "has_block_or_depend", "num_links", "link_density", "dependency_complexity"]
        },
        "workload_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in ["assignee_wci", "scf", "assignee_active_count", "wci_per_active", "assignee_workload_share", "cycle_time_gap"]
        },
        "nlp_features_importance": {
            k: round(float(feat_imp_series.get(k, 0.0)), 6)
            for k in ["ambiguity_score", "summary_len", "word_count", "char_per_word", "ambiguous_words_est"]
        },
    }

    imp_file = out_dir / "rf_importance.json"
    with open(imp_file, "w", encoding="utf-8") as f:
        json.dump(importance_dict, f, indent=2, ensure_ascii=False)
    print(f"[Artifacts] Saved feature importance analysis to {imp_file}")

    print("\n[Top 15 Most Important Features]:")
    for rank, (feat, val_imp) in enumerate(feat_imp_series.head(15).items(), 1):
        print(f"  {rank:>2}. {feat:<30}: {val_imp:.5f}")

    return {
        "val_f1": val_f1,
        "test_f1": test_f1,
        "test_prec": test_prec,
        "test_rec": test_rec,
        "optimal_threshold": opt_thr,
        "test_roc_auc": test_roc_auc,
        "test_pr_auc": test_pr_auc,
    }


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate Random Forest & Bagging Resampling Pipeline")
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
