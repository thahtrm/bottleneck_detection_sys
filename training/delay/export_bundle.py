"""Stage 7 — Freeze the staging directory filled by stages 1-6 into a ``delay`` model bundle.

Bundle contents (read by early_risk_detection.delay.DelayRiskScorer):
  text_features.npz, {xgb,surv}_featurizer.json / _target_encoding.parquet / _tfidf.json / _tfidf_svd.npz
  xgb_fold{0..4}.ubj, aft.ubj, cbs.cbm, cbs_cr.cbm (+ *_config.json)
  nonwork.ubj, early_nonwork.ubj, gate_config.json, blend_gate.json
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.scorer import KIND

REQUIRED = ["text_features.npz", "xgb_featurizer.json", "surv_featurizer.json", "xgb_fold0.ubj", "aft.ubj",
            "cbs.cbm", "cbs_cr.cbm", "nonwork.ubj", "early_nonwork.ubj", "gate_config.json", "blend_gate.json"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="bundles/staging/delay")
    ap.add_argument("--out", default="bundles/delay")
    ap.add_argument("--data_dir", default="data/delay_t0")
    ap.add_argument("--leaderboard", default="experiments/leaderboard_delay_t0.json")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    stage = Path(args.stage)
    missing = [f for f in REQUIRED if not (stage / f).exists()]
    if missing:
        raise SystemExit(f"staging bundle incomplete, missing {missing}")
    out = Path(args.out)
    if out.exists():
        if not args.overwrite:
            raise SystemExit(f"{out} exists (pass --overwrite)")
        shutil.rmtree(out)
    shutil.copytree(stage, out)
    b = ModelBundle.staging(out, KIND)
    meta = json.loads((Path(args.data_dir) / "dataset_meta.json").read_text())
    b.manifest["config"] = {"model": "delay_official_t0", "features": "T0 (as of creation)",
                            "train_cutoff_ts": meta["train_cutoff_ts"], "n_train": meta["n"],
                            "n_features": meta["n_features"], "xgb_folds": len(list(out.glob("xgb_fold*.ubj")))}
    lb = Path(args.leaderboard)
    metrics = {}
    if lb.exists():
        board = json.loads(lb.read_text())
        for track in ["delay_official_t0", "delay_blend_t0"]:
            if track in board:
                metrics[track] = {"threshold": board[track]["optimal_threshold"],
                                  **{k: v for k, v in board[track]["test_metrics"].items() if k != "confusion_matrix"}}
    print(b.finalize(metrics))


if __name__ == "__main__":
    main()
