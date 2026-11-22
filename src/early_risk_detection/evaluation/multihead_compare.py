"""Unified MultiHead-vs-Classical leaderboard schema and metric adapters.

Protocol (approved plan, Q1=B′ / Q2–Q8=A):
  primary snapshots: T0_pre, T3_change, T7_change, T_active_change
  delay threshold: val Recall>=0.80 preferred, else Max-F1; report both
  delay MAE: mean abs duration error on resolved issues (MedAE secondary)
"""
from __future__ import annotations

import json
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

from .criticality import evaluate_criticality
from .delay import (
    duration_abs_errors,
    find_threshold_max_f1,
    find_threshold_recall_ge,
)

PRIMARY_SNAPSHOTS = ("T0_pre", "T3_change", "T7_change", "T_active_change")
SNAPSHOT_DOCS = {
    "T0_pre": "Pre-create / pre-T0 memory snapshot (horizon_days=-1)",
    "T3_change": "Latest active (non-closing) event within 3 days of T0",
    "T7_change": "Latest active (non-closing) event within 7 days of T0",
    "T_active_change": (
        "Latest active event before resolution (horizon_days=None); "
        "repo name for in-progress / currently-active project-change snapshot"
    ),
}
EXPERIMENT_NAME = "MultiHead_vs_Classical_OOT"
DEFAULT_LEADERBOARD = "experiments/leaderboard_multihead_vs_classical.json"


def _metrics_at(y_true: np.ndarray, y_prob: np.ndarray, thr: float) -> dict[str, Any]:
    pred = (y_prob >= thr).astype(int)
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(y_true, pred).ravel()]
    return {
        "threshold": round(float(thr), 4),
        "f1_score": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4),
        "brier_score": round(float(brier_score_loss(y_true, np.clip(y_prob, 0.0, 1.0))), 4),
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def eval_delay_dual_protocol(
    y_val_true: np.ndarray,
    y_val_prob: np.ndarray,
    y_test_true: np.ndarray,
    y_test_prob: np.ndarray,
    pred_dur_test: np.ndarray | None = None,
    true_dur_test: np.ndarray | None = None,
    resolved_mask_test: np.ndarray | None = None,
    min_recall: float = 0.80,
) -> dict[str, Any]:
    """Delay metrics with Q7 protocol + mean MAE / MedAE."""
    max_f1_thr, *_ = find_threshold_max_f1(y_val_true, y_val_prob)
    rec_thr, _, _, _, rec_ok = find_threshold_recall_ge(y_val_true, y_val_prob, min_recall=min_recall)
    primary_thr = rec_thr if rec_ok else max_f1_thr
    primary_protocol = "val_recall_ge_0.80" if rec_ok else "val_max_f1_fallback"

    out: dict[str, Any] = {
        "protocol": {
            "primary": primary_protocol,
            "min_recall": min_recall,
            "val_recall_constraint_met": bool(rec_ok),
            "primary_threshold": round(float(primary_thr), 4),
            "max_f1_threshold": round(float(max_f1_thr), 4),
        },
        "val_max_f1": _metrics_at(y_val_true, y_val_prob, max_f1_thr),
        "test_max_f1": _metrics_at(y_test_true, y_test_prob, max_f1_thr),
        "val_high_recall": _metrics_at(y_val_true, y_val_prob, rec_thr),
        "test_high_recall": _metrics_at(y_test_true, y_test_prob, rec_thr),
        "test_primary": _metrics_at(y_test_true, y_test_prob, primary_thr),
    }

    if pred_dur_test is not None and true_dur_test is not None:
        mae, medae, n = duration_abs_errors(pred_dur_test, true_dur_test, resolved_mask_test)
        out["mean_abs_duration_error_days"] = round(mae, 4) if np.isfinite(mae) else None
        out["median_abs_duration_error_days"] = round(medae, 4) if np.isfinite(medae) else None
        out["duration_n_resolved"] = n
        # Backward-compatible alias used by older dual-head summaries (was MedAE).
        out["mae"] = out["mean_abs_duration_error_days"]
        out["medae"] = out["median_abs_duration_error_days"]
    else:
        out["mean_abs_duration_error_days"] = None
        out["median_abs_duration_error_days"] = None
        out["duration_n_resolved"] = 0
        out["mae"] = None
        out["medae"] = None
    return out


def delay_entry(
    *,
    model: str,
    snapshot: str,
    delay_metrics: dict[str, Any],
    repo_tip: str,
    seed: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    primary = delay_metrics.get("test_primary") or delay_metrics.get("test_high_recall") or {}
    return {
        "experiment_name": EXPERIMENT_NAME,
        "repo_tip": repo_tip,
        "split": "test",
        "snapshot": snapshot,
        "model": model,
        "task": "delay_risk",
        "seed": seed,
        "metrics": {
            "roc_auc": primary.get("roc_auc"),
            "pr_auc": primary.get("pr_auc"),
            "recall": primary.get("recall"),
            "precision": primary.get("precision"),
            "f1_score": primary.get("f1_score"),
            "mae": delay_metrics.get("mae"),
            "medae": delay_metrics.get("medae"),
            "threshold": primary.get("threshold"),
        },
        "protocol": delay_metrics.get("protocol"),
        "detail": {
            "test_max_f1": delay_metrics.get("test_max_f1"),
            "test_high_recall": delay_metrics.get("test_high_recall"),
            "duration_n_resolved": delay_metrics.get("duration_n_resolved"),
        },
        "notes": notes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def criticality_entry(
    *,
    model: str,
    snapshot: str,
    crit_metrics: dict[str, Any],
    repo_tip: str,
    seed: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "experiment_name": EXPERIMENT_NAME,
        "repo_tip": repo_tip,
        "split": "test",
        "snapshot": snapshot,
        "model": model,
        "task": "criticality",
        "seed": seed,
        "metrics": {
            "ndcg_10_global": crit_metrics.get("ndcg_10_global", crit_metrics.get("ndcg_10")),
            "ndcg_10_grouped": crit_metrics.get("ndcg_10_grouped"),
            "precision_top5pct": crit_metrics.get("precision_top5pct"),
            "tp_top5": crit_metrics.get("tp_top5"),
            "k_top5": crit_metrics.get("k_top5"),
            "spearman_rho": crit_metrics.get("spearman_rho"),
        },
        "notes": notes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def upsert_leaderboard(path: str | Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge entries keyed by (task, model, snapshot, seed). Never clobber unrelated history files."""
    lb_path = Path(path)
    lb_path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any]
    if lb_path.exists():
        doc = json.loads(lb_path.read_text(encoding="utf-8"))
    else:
        doc = {
            "experiment_name": EXPERIMENT_NAME,
            "primary_snapshots": list(PRIMARY_SNAPSHOTS),
            "snapshot_docs": SNAPSHOT_DOCS,
            "protocol": {
                "q1": "B_prime_multi_snapshot_primary",
                "q2": "A_reeval_no_full_retrain",
                "q3": "A_shared_X_xgb",
                "q4": "A_duration_regressors",
                "q5": "A_regress_then_rank",
                "q6": "A_no_lightgbm_main_table",
                "q7": "A_val_recall_ge_0.80_else_max_f1",
                "q8": "A_full_16_ecosystems",
            },
            "entries": [],
        }
    by_key: dict[tuple, dict] = {}
    for e in doc.get("entries", []):
        key = (e.get("task"), e.get("model"), e.get("snapshot"), e.get("seed"))
        by_key[key] = e
    for e in entries:
        key = (e.get("task"), e.get("model"), e.get("snapshot"), e.get("seed"))
        by_key[key] = e
    doc["entries"] = sorted(by_key.values(), key=lambda e: (e.get("task") or "", e.get("snapshot") or "", e.get("model") or ""))
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    lb_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc


def load_delay_pred_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    need = {"y_true", "y_prob"}
    if not need.issubset(df.columns):
        raise ValueError(f"{path} must contain {need}")
    return df


def evaluate_criticality_pred(
    pred_csv: str | Path,
    ground_truth: str | Path,
    track: str,
    leaderboard_file: str | Path | None = None,
) -> dict[str, Any]:
    """Thin wrapper; writes optional side leaderboard only if path given."""
    kwargs: dict[str, Any] = {
        "pred_file": str(pred_csv),
        "track": track,
        "split": "test",
        "ground_truth_file": str(ground_truth),
        "iteration": 1,
        "target_overrides": {"ndcg": 0.85, "prec": 0.75, "rho": 0.70},
        "experiment_name": EXPERIMENT_NAME,
    }
    if leaderboard_file is not None:
        kwargs["leaderboard_file"] = str(leaderboard_file)
    return evaluate_criticality(**kwargs)
