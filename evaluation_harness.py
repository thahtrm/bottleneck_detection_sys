"""Script Đánh giá Bất biến (Immutable Evaluation Harness) cho Hệ thống Dự đoán Nguy cơ Trễ hạn Issue.

Chức năng:
- Nhận file dự đoán: --predictions (test set) và tùy chọn --val-predictions (val set để sweep ngưỡng tối ưu).
- Hoặc nhận trực tiếp --track <track_name> với đường dẫn mặc định trong thư mục kết quả của track.
- Tính toán toàn diện: PR-AUC, ROC-AUC, Optimal F1-Score, Precision, Recall, Brier Score, Confusion Matrix.
- Cập nhật bảng xếp hạng trung tâm: experiments/leaderboard.json.
- Kiểm tra các ràng buộc: F1 > 0.80, Precision >= 0.75, Recall >= 0.80.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def find_optimal_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    min_precision: float = 0.70,
    min_recall: float = 0.70,
) -> tuple[float, float, float, float]:
    """Quét ngưỡng quyết định T in [0.05, 0.95] để tối đa hóa F1 trên tập Validation."""
    best_thr = 0.5
    best_f1 = 0.0
    best_p = 0.0
    best_r = 0.0

    # Ưu tiên các ngưỡng thỏa mãn cả min_precision và min_recall
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

    # Nếu không có ngưỡng nào thỏa mãn cả 2 ràng buộc cứng cùng lúc, dùng best F1 chung
    if best_f1 == 0.0:
        best_thr = candidate_best_thr
        best_f1 = candidate_best_f1
        best_p = candidate_best_p
        best_r = candidate_best_r

    return best_thr, best_f1, best_p, best_r


def evaluate_predictions(
    test_pred_path: str,
    val_pred_path: str | None = None,
    track: str = "custom",
    threshold: float | None = None,
    leaderboard_path: str = "experiments/leaderboard.json",
) -> dict[str, Any]:
    print(f"\n=======================================================")
    print(f"📊 IMMUTABLE EVALUATION HARNESS - TRACK: {track.upper()}")
    print(f"=======================================================")

    # 1. Đọc test predictions
    test_df = pd.read_csv(test_pred_path)
    if "y_true" not in test_df.columns or "y_prob" not in test_df.columns:
        raise ValueError(f"File {test_pred_path} phải chứa cột 'y_true' và 'y_prob'.")

    y_test_true = test_df["y_true"].values.astype(int)
    y_test_prob = test_df["y_prob"].values.astype(float)

    # 2. Xác định ngưỡng tối ưu
    optimal_thr = 0.5
    val_f1_opt = 0.0
    if val_pred_path and os.path.exists(val_pred_path):
        val_df = pd.read_csv(val_pred_path)
        if "y_true" in val_df.columns and "y_prob" in val_df.columns:
            y_val_true = val_df["y_true"].values.astype(int)
            y_val_prob = val_df["y_prob"].values.astype(float)
            optimal_thr, val_f1_opt, val_p, val_r = find_optimal_threshold(y_val_true, y_val_prob)
            print(f"[Val Sweep] Optimal Threshold: {optimal_thr:.4f} (Val F1: {val_f1_opt:.4f}, Prec: {val_p:.4f}, Rec: {val_r:.4f})")
    elif threshold is not None:
        optimal_thr = threshold
        print(f"[Threshold] Using specified threshold: {optimal_thr:.4f}")
    else:
        print(f"[Threshold] No val file or threshold specified. Defaulting to 0.50")

    # 3. Tính toán metrics trên tập Test (Out-of-time Test Set)
    y_test_pred = (y_test_prob >= optimal_thr).astype(int)

    test_f1 = float(f1_score(y_test_true, y_test_pred, zero_division=0))
    test_prec = float(precision_score(y_test_true, y_test_pred, zero_division=0))
    test_rec = float(recall_score(y_test_true, y_test_pred, zero_division=0))
    test_pr_auc = float(average_precision_score(y_test_true, y_test_prob))
    test_roc_auc = float(roc_auc_score(y_test_true, y_test_prob))
    test_brier = float(brier_score_loss(y_test_true, y_test_prob))

    cm = confusion_matrix(y_test_true, y_test_pred)
    tn, fp, fn, tp = [int(v) for v in cm.ravel()]

    is_f1_passed = test_f1 >= 0.80
    is_prec_passed = test_prec >= 0.75
    is_rec_passed = test_rec >= 0.80
    is_all_passed = is_f1_passed and is_prec_passed and is_rec_passed

    results = {
        "track": track,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "optimal_threshold": round(optimal_thr, 4),
        "val_f1_at_optimal_threshold": round(val_f1_opt, 4),
        "test_metrics": {
            "f1_score": round(test_f1, 4),
            "precision": round(test_prec, 4),
            "recall": round(test_rec, 4),
            "pr_auc": round(test_pr_auc, 4),
            "roc_auc": round(test_roc_auc, 4),
            "brier_score": round(test_brier, 4),
            "confusion_matrix": {
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
            },
        },
        "target_status": {
            "f1_target_passed (>= 0.80)": is_f1_passed,
            "precision_constraint_passed (>= 0.75)": is_prec_passed,
            "recall_constraint_passed (>= 0.80)": is_rec_passed,
            "all_constraints_met": is_all_passed,
        },
    }

    print("\n📈 TEST EVALUATION RESULTS:")
    print(f"  • F1-Score:    {test_f1:.4f} {'✅ [TARGET MET]' if is_f1_passed else '❌ [BELOW 0.80]'}")
    print(f"  • Precision:   {test_prec:.4f} {'✅ (>= 0.75)' if is_prec_passed else '❌ (< 0.75)'}")
    print(f"  • Recall:      {test_rec:.4f} {'✅ (>= 0.80)' if is_rec_passed else '❌ (< 0.80)'}")
    print(f"  • PR-AUC:      {test_pr_auc:.4f}")
    print(f"  • ROC-AUC:     {test_roc_auc:.4f}")
    print(f"  • Brier Score: {test_brier:.4f}")
    print(f"  • Confusion Matrix: TP={tp}, FP={fp}, TN={tn}, FN={fn}")
    print(f"  • Overall Status: {'🎉 MISSION ACCOMPLISHED!' if is_all_passed else '⚠️ CONVERGENCE NEEDED'}")

    # 4. Ghi vào bảng xếp hạng trung tâm experiments/leaderboard.json
    lb_path = Path(leaderboard_path)
    lb_path.parent.mkdir(parents=True, exist_ok=True)

    leaderboard = {}
    if lb_path.exists():
        try:
            with open(lb_path, "r", encoding="utf-8") as f:
                leaderboard = json.load(f)
        except Exception:
            leaderboard = {}

    leaderboard[track] = results

    with open(lb_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2, ensure_ascii=False)
    print(f"\n[Leaderboard] Updated results in {lb_path.resolve()}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Immutable Evaluation Harness for Issue Delay Prediction")
    parser.add_argument("--predictions", type=str, help="Path to test set predictions CSV")
    parser.add_argument("--val-predictions", type=str, default=None, help="Path to validation set predictions CSV")
    parser.add_argument("--track", type=str, default="custom", help="Track name (xgboost, randomforest, logreg, stacking)")
    parser.add_argument("--threshold", type=float, default=None, help="Optional manual decision threshold")
    parser.add_argument("--leaderboard", type=str, default="experiments/leaderboard.json", help="Path to leaderboard JSON")

    args = parser.parse_args()

    # Tự động suy luận đường dẫn nếu chỉ truyền --track
    if not args.predictions and args.track:
        default_pred = f"experiments/{args.track}/predictions_test.csv"
        default_val = f"experiments/{args.track}/predictions_val.csv"
        if os.path.exists(default_pred):
            args.predictions = default_pred
            if os.path.exists(default_val):
                args.val_predictions = default_val

    if not args.predictions:
        parser.error("--predictions <path_to_csv> is required.")

    evaluate_predictions(
        test_pred_path=args.predictions,
        val_pred_path=args.val_predictions,
        track=args.track,
        threshold=args.threshold,
        leaderboard_path=args.leaderboard,
    )


if __name__ == "__main__":
    main()
