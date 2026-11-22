"""Re-evaluate Dual-Head from existing prediction CSVs (no full retrain).

Writes unified leaderboard entries for primary snapshots with mean MAE + Q7 thresholds.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from early_risk_detection.evaluation.multihead_compare import (
    PRIMARY_SNAPSHOTS,
    criticality_entry,
    delay_entry,
    eval_delay_dual_protocol,
    evaluate_criticality_pred,
    upsert_leaderboard,
)


def repo_tip() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/tgn_full_v2")
    ap.add_argument("--pred-root", default="data/tgn_full_v2/predictions_dual_head")
    ap.add_argument("--leaderboard", default="experiments/leaderboard_multihead_vs_classical.json")
    ap.add_argument("--snapshots", nargs="+", default=list(PRIMARY_SNAPSHOTS))
    ap.add_argument("--side-crit-lb", default="experiments/leaderboard_multihead_crit_scratch.json")
    args = ap.parse_args()

    root = Path(args.data_dir)
    pred_root = Path(args.pred_root)
    tip = repo_tip()
    issues = pd.read_parquet(root / "issues_t0.parquet", columns=["instance", "issue_key", "duration_days", "is_resolved"])
    issues["uid"] = issues["instance"].astype(str) + "|" + issues["issue_key"].astype(str)
    dur_map = issues.set_index("uid")["duration_days"]
    res_map = issues.set_index("uid")["is_resolved"]

    entries = []
    for snap in args.snapshots:
        hdir = pred_root / snap
        delay_val = pd.read_csv(hdir / "delay_val.csv")
        delay_test = pd.read_csv(hdir / "delay_test.csv")
        true_dur = delay_test["uid"].map(dur_map).values.astype(np.float64)
        resolved = delay_test["uid"].map(res_map).fillna(1).values.astype(int) == 1
        pred_dur = delay_test["pred_duration_days"].values.astype(np.float64)
        dmet = eval_delay_dual_protocol(
            delay_val["y_true"].values.astype(int),
            delay_val["y_prob"].values.astype(float),
            delay_test["y_true"].values.astype(int),
            delay_test["y_prob"].values.astype(float),
            pred_dur_test=pred_dur,
            true_dur_test=true_dur,
            resolved_mask_test=resolved,
        )
        entries.append(
            delay_entry(
                model="dual_tgn",
                snapshot=snap,
                delay_metrics=dmet,
                repo_tip=tip,
                seed=None,
                notes="reeval existing dual-head CSVs; static X frozen + z at snapshot",
            )
        )

        crit = evaluate_criticality_pred(
            hdir / "criticality_test.csv",
            root / "criticality_test.parquet",
            track=f"DualTGN_Crit_{snap}_reeval",
            leaderboard_file=args.side_crit_lb,
        )
        entries.append(
            criticality_entry(
                model="dual_tgn",
                snapshot=snap,
                crit_metrics=crit["metrics"],
                repo_tip=tip,
                notes="reeval existing dual-head CSVs",
            )
        )
        print(
            f"[{snap}] delay ROC={dmet['test_primary']['roc_auc']:.4f} "
            f"PR={dmet['test_primary']['pr_auc']:.4f} R={dmet['test_primary']['recall']:.4f} "
            f"MAE={dmet['mae']} | crit NDCG-g={crit['metrics'].get('ndcg_10_grouped')} "
            f"P@5%={crit['metrics'].get('precision_top5pct')}"
        )

    upsert_leaderboard(args.leaderboard, entries)
    print(f"Updated {args.leaderboard} with {len(entries)} dual_tgn entries")


if __name__ == "__main__":
    main()
