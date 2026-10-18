"""Track 5: Hybrid Stacking Meta-Ranker for Task Criticality & Schedule Impact.

Combines predictions from all 4 specialized tracks:
    Y_hybrid = MetaRanker(Y_cpm, Y_cascade, z_tgn, Y_lgb)

Features:
- Non-Negative Constrained Meta-Learner (NNLS / Ridge) fit strictly on Validation.
- Evaluates on frozen Out-of-Time Test Set (data/pilot_spring/criticality_test.parquet).
- Verifies all 4 Hard Constraints:
    1. NDCG@10 >= 0.82
    2. Precision@Top-5% >= 0.75
    3. Spearman rho >= 0.70
    4. Zero Temporal Leakage: True
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls


def run_track5_hybrid(
    cpm_val_path: str = "../worktree-graph-cpm/predictions_val.csv",
    cpm_test_path: str = "../worktree-graph-cpm/predictions_test.csv",
    cascade_val_path: str = "../worktree-cascade-sim/predictions_val.csv",
    cascade_test_path: str = "../worktree-cascade-sim/predictions_test.csv",
    tgn_val_path: str = "../worktree-tgn-dynamic/predictions_val.csv",
    tgn_test_path: str = "../worktree-tgn-dynamic/predictions_test.csv",
    lgb_val_path: str = "../worktree-lgb-ranker/predictions_val.csv",
    lgb_test_path: str = "../worktree-lgb-ranker/predictions_test.csv",
    out_dir: str = "experiments",
) -> None:
    print("=================================================================")
    print("🏆 TRACK 5: HYBRID STACKING META-RANKER CONVERGENCE")
    print("=================================================================")

    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    # 1. Đọc dữ liệu Ground Truth
    val_gt = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
    test_gt = pd.read_parquet("data/pilot_spring/criticality_test.parquet")
    print(f"  • Validation Set: {len(val_gt):,} rows | Test Set: {len(test_gt):,} rows")

    # 2. Thu thập dự đoán từ 4 Tracks cho cả Val và Test
    print("  • Ingesting predictions from all 4 research tracks...", flush=True)

    def load_track_matrix(split: str, cpm_p: str, casc_p: str, tgn_p: str, lgb_p: str, gt_df: pd.DataFrame) -> pd.DataFrame:
        df_cpm = pd.read_csv(cpm_p).set_index("issue_key").loc[gt_df["issue_key"]]
        df_casc = pd.read_csv(casc_p).set_index("issue_key").loc[gt_df["issue_key"]]
        df_tgn = pd.read_csv(tgn_p).set_index("issue_key").loc[gt_df["issue_key"]]
        df_lgb = pd.read_csv(lgb_p).set_index("issue_key").loc[gt_df["issue_key"]]

        def norm_series(s: pd.Series) -> np.ndarray:
            arr = s.values.astype(np.float32)
            denom = arr.max() - arr.min() + 1e-6
            return (arr - arr.min()) / denom

        matrix_df = pd.DataFrame({
            "issue_key": gt_df["issue_key"].values,
            "pred_cpm": norm_series(df_cpm["pred_score"]),
            "pred_cascade": norm_series(df_casc["pred_score"]),
            "pred_tgn": norm_series(df_tgn["pred_score"]),
            "pred_lgb": norm_series(df_lgb["pred_score"]),
        })
        return matrix_df

    val_matrix = load_track_matrix("val", cpm_val_path, cascade_val_path, tgn_val_path, lgb_val_path, val_gt)
    test_matrix = load_track_matrix("test", cpm_test_path, cascade_test_path, tgn_test_path, lgb_test_path, test_gt)

    # 3. Huấn luyện Meta-Ranker trên Validation Set (Non-Negative Least Squares)
    print("  • Fitting Non-Negative Constrained Meta-Ranker on Validation set...", flush=True)
    track_cols = ["pred_cpm", "pred_cascade", "pred_tgn", "pred_lgb"]
    X_val = val_matrix[track_cols].values
    y_val = val_gt["ground_truth_criticality"].values.astype(np.float32)

    weights, norm_res = nnls(X_val, y_val)
    weights = weights / (weights.sum() + 1e-6)

    weights_dict = {
        "Track1_GraphCPM": round(float(weights[0]), 4),
        "Track2_CascadeSim": round(float(weights[1]), 4),
        "Track3_TGN": round(float(weights[2]), 4),
        "Track4_LGBMRanker": round(float(weights[3]), 4),
    }
    print(f"  • Learned Ensemble Meta-Weights: {weights_dict}", flush=True)

    # 4. Dự đoán điểm Hybrid trên Validation Set
    val_preds = X_val @ weights
    val_pred_file = out_p / "predictions_val_hybrid.csv"
    pd.DataFrame({
        "issue_key": val_matrix["issue_key"].values,
        "pred_score": np.round(val_preds, 6),
    }).to_csv(val_pred_file, index=False)
    print(f"  • Saved Validation predictions to {val_pred_file}")

    # Chạy Harness cho Validation Set
    print("\n-----------------------------------------------------------------")
    print("📊 EVALUATING TRACK 5 ON VALIDATION SET")
    print("-----------------------------------------------------------------")
    val_cmd = (
        f".venv/bin/python evaluation_harness_criticality.py "
        f"--track Track5_HybridMeta "
        f"--pred_file {val_pred_file} "
        f"--split val "
        f"--iteration 1"
    )
    os.system(val_cmd)

    # 5. ĐÁNH GIÁ CUỐI CÙNG TRÊN TẬP OUT-OF-TIME TEST SET
    print("\n=================================================================")
    print("🎯 FINAL BLIND EVALUATION ON OUT-OF-TIME TEST SET")
    print("=================================================================")
    X_test = test_matrix[track_cols].values
    test_preds = X_test @ weights
    test_pred_file = out_p / "predictions_test_hybrid.csv"
    pd.DataFrame({
        "issue_key": test_matrix["issue_key"].values,
        "pred_score": np.round(test_preds, 6),
    }).to_csv(test_pred_file, index=False)
    print(f"  • Saved Test predictions to {test_pred_file}")

    # Chạy Harness cho Out-of-Time Test Set
    test_cmd = (
        f".venv/bin/python evaluation_harness_criticality.py "
        f"--track Track5_HybridMeta "
        f"--pred_file {test_pred_file} "
        f"--split test "
        f"--iteration 1"
    )
    os.system(test_cmd)

    # 6. Lưu tóm tắt cấu hình Meta-Learner
    summary = {
        "model": "Hybrid Stacking Meta-Ranker (Track 5)",
        "objective": "Task Criticality & Schedule Impact Multi-View Fusion",
        "ensemble_weights": weights_dict,
        "components": {
            "track1": "Topological DAG & Critical Path Slack Time (CPM)",
            "track2": "Monte Carlo Cascading Schedule Slippage & Survival AFT",
            "track3": "Continuous-Time Temporal Graph Network (TGN) Memory (128d)",
            "track4": "Learning-to-Rank LambdaRank GBDT Multi-Task",
        },
        "evaluation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    summary_file = out_p / "track5_meta_learner_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n✅ [Complete] Saved Meta-Learner summary to {summary_file}")


def main():
    run_track5_hybrid()


if __name__ == "__main__":
    main()
