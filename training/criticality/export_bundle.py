"""Stage 6 — Pack the trained tgn_hybrid model into a ``criticality`` bundle for the library.

Bundle contents (read by early_risk_detection.criticality.CriticalityScorer):
  tgn_memory.pt              TGN memory weights (message MLP, GRU, link decoder)
  readout_seed{S}.pt         tgn_hybrid readout of every ensemble seed
  normalizers.npz            static mu/sd, memory-aux mu/sd (train rows), SVD16 components
  manifest.json              config (feature lists, chunk size, back-off means) + test metrics
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from early_risk_detection.bundle import ModelBundle
from early_risk_detection.criticality.scorer import KIND


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data/tgn_full")
    ap.add_argument("--out", default="bundles/criticality")
    ap.add_argument("--leaderboard", default="experiments/leaderboard_jira_full.json")
    ap.add_argument("--track", default="JiraFull_tgn_hybrid", help="leaderboard track holding the metrics")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    root = Path(args.data_dir)
    meta = json.loads((root / "readout_meta.json").read_text())
    summary = json.loads((root / "readout_summary.json").read_text())
    report = json.loads((root / f"tgn_memory_report{meta['z_tag']}.json").read_text())
    readout_files = [f"readout_seed{s}.pt" for s in meta["seeds"]]
    config = {
        "model": "tgn_hybrid",
        "z_tag": meta["z_tag"],
        "chunk": report["config"]["chunk"],
        "seeds": meta["seeds"],
        "readout_files": readout_files,
        "dropout": 0.2,
        "static_features": meta["static_features"],
        "instances": meta["instances"],
        "types": meta["types"],
        "propensity_backoff": json.loads((root / "propensity_backoff.json").read_text()),
        "top_pct": 0.05,
        "readout_hyperparams": summary["tgn_hybrid"]["config"],
        "memory_training": {k: report["config"][k] for k in ["epochs", "lr", "seed"]},
        "train_cutoff_ts": report["leakage_audit"]["train_cutoff_ts"],
    }
    b = ModelBundle.create(args.out, KIND, config, overwrite=args.overwrite)
    b.copy_in(root / f"tgn_memory{meta['z_tag']}.pt", "tgn_memory.pt")
    for s, name in zip(meta["seeds"], readout_files):
        b.copy_in(root / f"readout_tgn_hybrid_seed{s}.pt", name)
    norm = dict(np.load(root / "readout_normalizers.npz"))
    norm["svd_components"] = np.load(root / "svd16.npz")["components"]
    b.save_arrays("normalizers.npz", **norm)

    metrics = {}
    lb = Path(args.leaderboard)
    if lb.exists():
        for e in json.loads(lb.read_text())["leaderboard"]:
            if e["track"] == args.track:
                metrics[e["split"]] = {k: e["metrics"][k] for k in
                                       ["ndcg_10_grouped", "precision_top5pct", "recall_top5pct", "spearman_rho",
                                        "roc_auc", "pr_auc"]}
    print(b.finalize(metrics))


if __name__ == "__main__":
    main()
