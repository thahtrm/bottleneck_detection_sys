"""TRACK 4: STACKING META-LEARNER & DYNAMIC ENSEMBLE ORCHESTRATION

Mục tiêu:
- Kết hợp đa dạng lỗi (Error Diversity) từ 3 mô hình tốt nhất của 3 Git Worktrees:
  + Subagent 1: XGBoost (Gradient Boosting)
  + Subagent 2: Random Forest (Bagging & Resampling)
  + Subagent 3: Logistic Regression (Advanced Feature Engineering & Splines)
- Khai thác đặc trưng meta: Xác suất cơ sở, độ lệch/bất đồng thuận giữa các mô hình (Model Disagreement),
  tương tác phi tuyến xác suất, và các tín hiệu phần mềm cốt lõi (Priority, Story Points, Workload, Deadline).
- Quét ngưỡng tối ưu trên tập Validation (Fine-grained Threshold Sweep) và áp dụng cố định sang Out-of-time Test set.
- Cập nhật kết quả vào central leaderboard qua evaluation_harness.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import StandardScaler


def build_meta_features(
    raw_df: pd.DataFrame,
    p_xgb: np.ndarray,
    p_rf: np.ndarray,
    p_lr: np.ndarray,
) -> tuple[np.ndarray, list[str]]:
    """Xây dựng không gian đặc trưng Meta-Learning."""
    # 1. Logit transform (log-odds)
    eps = 1e-4
    l_xgb = np.log(np.clip(p_xgb, eps, 1 - eps) / (1.0 - np.clip(p_xgb, eps, 1 - eps)))
    l_rf = np.log(np.clip(p_rf, eps, 1 - eps) / (1.0 - np.clip(p_rf, eps, 1 - eps)))
    l_lr = np.log(np.clip(p_lr, eps, 1 - eps) / (1.0 - np.clip(p_lr, eps, 1 - eps)))

    # 2. Thống kê tổng hợp xác suất
    mean_prob = (p_xgb + p_rf + p_lr) / 3.0
    weighted_blend = 0.45 * p_xgb + 0.40 * p_rf + 0.15 * p_lr
    min_prob = np.minimum.reduce([p_xgb, p_rf, p_lr])
    max_prob = np.maximum.reduce([p_xgb, p_rf, p_lr])
    prob_spread = max_prob - min_prob

    # 3. Độ bất đồng thuận (Model Disagreement)
    diff_xgb_rf = np.abs(p_xgb - p_rf)
    diff_xgb_lr = np.abs(p_xgb - p_lr)
    diff_rf_lr = np.abs(p_rf - p_lr)

    # 4. Tương tác phi tuyến xác suất
    prod_xgb_rf = p_xgb * p_rf
    prod_xgb_lr = p_xgb * p_lr

    # 5. Đặc trưng nghiệp vụ phần mềm ổn định theo thời gian
    is_unassigned = (raw_df["assignee"] == "(unassigned)").astype(float).values
    p_norm = raw_df["priority_norm"].fillna(0.4).values
    sp = raw_df["story_points"].fillna(5.0).values
    planned_days = raw_df["planned_duration_days"].fillna(45.0).values
    sp_ratio = raw_df["sp_planned_ratio"].fillna(0.1).values

    wci = raw_df["assignee_wci"].fillna(0.0).values
    scf = raw_df["scf"].fillna(1.0).values
    rep_delay = raw_df["reporter_hist_delay_rate"].fillna(0.5).values
    ass_delay = raw_df["assignee_hist_delay_rate"].fillna(0.5).values
    proj_active = raw_df["project_active_count"].fillna(100.0).values / 1000.0
    ambiguity = raw_df["ambiguity_score"].fillna(0.0).values
    word_cnt = np.log1p(raw_df["word_count"].fillna(10).values)

    # 6. Rolling 90-day velocity indicators
    a_90d_del = raw_df["assignee_90d_delay_rate"].fillna(0.5).values
    a_90d_cyc = np.log1p(raw_df["assignee_90d_cycle_time"].fillna(30.0).values)
    p_90d_del = raw_df["project_90d_delay_rate"].fillna(0.5).values
    p_90d_cyc = np.log1p(raw_df["project_90d_cycle_time"].fillna(30.0).values)
    u_90d_del = raw_df["unassigned_90d_delay_rate"].fillna(0.5).values

    # 7. Issue Graph & Dependencies
    num_links = raw_df["num_links"].fillna(0).values
    has_dep = raw_df["has_block_or_depend"].fillna(0).values

    feature_matrix = np.column_stack([
        p_xgb,
        p_rf,
        p_lr,
        l_xgb,
        l_rf,
        l_lr,
        mean_prob,
        weighted_blend,
        min_prob,
        max_prob,
        prob_spread,
        diff_xgb_rf,
        diff_xgb_lr,
        diff_rf_lr,
        prod_xgb_rf,
        prod_xgb_lr,
        p_norm,
        sp,
        planned_days,
        sp_ratio,
        wci,
        scf,
        rep_delay,
        ass_delay,
        proj_active,
        ambiguity,
        word_cnt,
        is_unassigned,
        a_90d_del,
        a_90d_cyc,
        p_90d_del,
        p_90d_cyc,
        u_90d_del,
        num_links,
        has_dep,
    ])

    feature_names = [
        "p_xgb",
        "p_rf",
        "p_lr",
        "l_xgb",
        "l_rf",
        "l_lr",
        "mean_prob",
        "weighted_blend",
        "min_prob",
        "max_prob",
        "prob_spread",
        "diff_xgb_rf",
        "diff_xgb_lr",
        "diff_rf_lr",
        "prod_xgb_rf",
        "prod_xgb_lr",
        "priority_norm",
        "story_points",
        "planned_duration_days",
        "sp_planned_ratio",
        "assignee_wci",
        "scf",
        "reporter_hist_delay_rate",
        "assignee_hist_delay_rate",
        "project_active_norm",
        "ambiguity_score",
        "log_word_count",
        "is_unassigned",
        "assignee_90d_delay_rate",
        "assignee_90d_cycle_time",
        "project_90d_delay_rate",
        "project_90d_cycle_time",
        "unassigned_90d_delay_rate",
        "num_links",
        "has_block_or_depend",
    ]

    return feature_matrix, feature_names


def run_stacking_meta_learner(
    out_dir: str = "experiments/stacking",
    leaderboard_path: str = "experiments/leaderboard.json",
):
    print("=======================================================")
    print("🚀 TRACK 4: STACKING META-LEARNER ORCHESTRATION")
    print("=======================================================")

    # 1. Đọc dữ liệu gốc
    val_raw = pd.read_parquet("data/val.parquet")
    test_raw = pd.read_parquet("data/test.parquet")
    train_raw = pd.read_parquet("data/train.parquet")

    y_val = val_raw["is_delayed"].values.astype(int)
    y_test = test_raw["is_delayed"].values.astype(int)

    # 2. Đọc dự đoán xác suất từ 3 tracks
    p_val_xgb = pd.read_csv("experiments/xgboost/predictions_val.csv")["y_prob"].values
    p_test_xgb = pd.read_csv("experiments/xgboost/predictions_test.csv")["y_prob"].values

    p_val_rf = pd.read_csv("experiments/randomforest/predictions_val.csv")["y_prob"].values
    p_test_rf = pd.read_csv("experiments/randomforest/predictions_test.csv")["y_prob"].values

    p_val_lr = pd.read_csv("experiments/logreg/predictions_val.csv")["y_prob"].values
    p_test_lr = pd.read_csv("experiments/logreg/predictions_test.csv")["y_prob"].values

    print("[Data] Loaded predictions from 3 tracks: XGBoost, RandomForest, LogisticRegression")
    print(f"  • Val samples: {len(y_val)} (Delay Rate: {y_val.mean():.4f})")
    print(f"  • Test samples: {len(y_test)} (Delay Rate: {y_test.mean():.4f})")

    # 3. Tạo không gian đặc trưng Meta
    X_val_meta, feat_names = build_meta_features(val_raw, p_val_xgb, p_val_rf, p_val_lr)
    X_test_meta, _ = build_meta_features(test_raw, p_test_xgb, p_test_rf, p_test_lr)

    scaler = StandardScaler()
    X_val_scaled = scaler.fit_transform(X_val_meta)
    X_test_scaled = scaler.transform(X_test_meta)

    # 4. Huấn luyện đa mô hình Meta-Learner & Chọn mô hình tối ưu trên Val
    candidates = {}

    from sklearn.model_selection import StratifiedKFold

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # Candidate A: Regularized Logistic Regression Meta-Learner (K-Fold Ensemble)
    oof_lr = np.zeros(len(y_val))
    test_p_lr = np.zeros(len(y_test))
    for train_idx, fold_idx in skf.split(X_val_scaled, y_val):
        m_lr = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
        m_lr.fit(X_val_scaled[train_idx], y_val[train_idx])
        oof_lr[fold_idx] = m_lr.predict_proba(X_val_scaled[fold_idx])[:, 1]
        test_p_lr += m_lr.predict_proba(X_test_scaled)[:, 1] / 5.0
    candidates["Meta-LogReg-Ensemble"] = (oof_lr, test_p_lr, None)

    # Candidate B: Conservative LightGBM Meta-Learner (K-Fold Ensemble)
    oof_lgb = np.zeros(len(y_val))
    test_p_lgb = np.zeros(len(y_test))
    for train_idx, fold_idx in skf.split(X_val_meta, y_val):
        m_lgb = LGBMClassifier(
            n_estimators=45,
            max_depth=3,
            num_leaves=7,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=1.0,
            reg_lambda=2.0,
            random_state=42,
            verbose=-1,
        )
        m_lgb.fit(X_val_meta[train_idx], y_val[train_idx])
        oof_lgb[fold_idx] = m_lgb.predict_proba(X_val_meta[fold_idx])[:, 1]
        test_p_lgb += m_lgb.predict_proba(X_test_meta)[:, 1] / 5.0
    candidates["Meta-LightGBM-Ensemble"] = (oof_lgb, test_p_lgb, None)

    # Candidate C: Full-fit LightGBM Meta-Learner
    lgbm_full = LGBMClassifier(
        n_estimators=40,
        max_depth=3,
        num_leaves=7,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=1.0,
        reg_lambda=2.0,
        random_state=42,
        verbose=-1,
    )
    lgbm_full.fit(X_val_meta, y_val)
    candidates["Meta-LightGBM-Full"] = (
        lgbm_full.predict_proba(X_val_meta)[:, 1],
        lgbm_full.predict_proba(X_test_meta)[:, 1],
        lgbm_full,
    )

    # Candidate D: Super Ensemble Blend
    base_val = 0.45 * p_val_xgb + 0.40 * p_val_rf + 0.15 * p_val_lr
    base_test = 0.45 * p_test_xgb + 0.40 * p_test_rf + 0.15 * p_test_lr

    p_val_blend = 0.45 * oof_lgb + 0.35 * oof_lr + 0.20 * base_val
    p_test_blend = 0.45 * test_p_lgb + 0.35 * test_p_lr + 0.20 * base_test
    candidates["Super-Stacking-Blend"] = (p_val_blend, p_test_blend, None)

    # 5. Đánh giá và quét ngưỡng tối ưu trên tập Validation
    best_candidate_name = None
    best_val_f1 = 0.0
    best_thr = 0.5
    best_probs_val = None
    best_probs_test = None

    print("\n[Meta-Learner Comparison on Validation Set]:")
    for name, (p_v, p_t, _) in candidates.items():
        opt_thr = 0.5
        opt_f1 = 0.0
        opt_p = 0.0
        opt_r = 0.0

        for thr in np.arange(0.10, 0.90, 0.005):
            preds = (p_v >= thr).astype(int)
            f1 = f1_score(y_val, preds, zero_division=0)
            p = precision_score(y_val, preds, zero_division=0)
            r = recall_score(y_val, preds, zero_division=0)

            if p >= 0.70 and r >= 0.75 and f1 > opt_f1:
                opt_f1 = f1
                opt_thr = float(thr)
                opt_p = p
                opt_r = r

        # Nếu không có ngưỡng thỏa mãn cả 2 ràng buộc cứng cùng lúc
        if opt_f1 == 0.0:
            for thr in np.arange(0.10, 0.90, 0.005):
                preds = (p_v >= thr).astype(int)
                f1 = f1_score(y_val, preds, zero_division=0)
                if f1 > opt_f1:
                    opt_f1 = f1
                    opt_thr = float(thr)
                    opt_p = precision_score(y_val, preds, zero_division=0)
                    opt_r = recall_score(y_val, preds, zero_division=0)

        print(f"  • {name:22s} -> Optimal Thr: {opt_thr:.4f} | Val F1: {opt_f1:.4f} (Prec: {opt_p:.4f}, Rec: {opt_r:.4f})")

        if opt_f1 > best_val_f1:
            best_val_f1 = opt_f1
            best_thr = opt_thr
            best_candidate_name = name
            best_probs_val = p_v
            best_probs_test = p_t

    print(f"\n[Selection] Winning Meta-Architecture: '{best_candidate_name}' với Val F1: {best_val_f1:.4f} tại Thr={best_thr:.4f}")

    # 6. Xuất kết quả dự đoán ra experiments/stacking
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    val_pred_df = pd.DataFrame({
        "issue_key": val_raw["issue_key"].values,
        "y_true": y_val,
        "y_prob": np.round(best_probs_val, 6),
    })
    test_pred_df = pd.DataFrame({
        "issue_key": test_raw["issue_key"].values,
        "y_true": y_test,
        "y_prob": np.round(best_probs_test, 6),
    })

    val_csv = out_path / "predictions_val.csv"
    test_csv = out_path / "predictions_test.csv"
    val_pred_df.to_csv(val_csv, index=False)
    test_pred_df.to_csv(test_csv, index=False)
    print(f"[Export] Saved {val_csv} and {test_csv}")

    # 7. Kích hoạt Evaluation Harness để cập nhật Leaderboard
    from early_risk_detection.evaluation import evaluate_predictions

    eval_result = evaluate_predictions(
        test_pred_path=str(test_csv),
        val_pred_path=str(val_csv),
        track="stacking",
        leaderboard_path=leaderboard_path,
    )

    # 8. Lưu tóm tắt meta-learner
    meta_summary = {
        "winning_architecture": best_candidate_name,
        "optimal_threshold": best_thr,
        "val_f1": best_val_f1,
        "test_metrics": eval_result["test_metrics"],
        "feature_names": feat_names,
    }
    with open(out_path / "meta_learner_summary.json", "w", encoding="utf-8") as f:
        json.dump(meta_summary, f, indent=2, ensure_ascii=False)

    print("\n✅ TRACK 4 STACKING PIPELINE COMPLETED SUCCESSFULLY!")
    return eval_result


if __name__ == "__main__":
    run_stacking_meta_learner()
