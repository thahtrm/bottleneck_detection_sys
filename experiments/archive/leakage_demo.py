"""Diagnostic ONLY — how much do the Spring-pilot's future-inclusive graph features inflate scores?

Adds the pilot's leaky inputs (final Block/Depend out-degree = blocks_count, and the CPM
quantities behind structural_criticality_t0: blast radius, slack, inverted PageRank — all computed
on the FINAL link graph) to the static GBDT. The predictions go to
predictions/LEAKY_gbdt_pilot_features/ and must never be reported as a valid model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch

from build_dataset import log
from train_readout import Data, quick_metrics, run_gbdt, write_preds

LEAKY = ["blocks_count_final", "blast_radius", "slack_time", "inverted_pagerank"]


def main() -> None:
    root = Path("../data/tgn_full")
    data = Data(root, torch.device("cuda"))
    df = pd.read_parquet(root / "issues_t0.parquet", columns=LEAKY)
    extra = {s: df.values[data.rows[s]].astype(np.float32) for s in ["train", "val", "test"]}
    preds, info = run_gbdt(data, 42, extra=extra, extra_names=LEAKY)
    write_preds(data, "LEAKY_gbdt_pilot_features", preds, root)
    log(f"LEAKY val {quick_metrics(data.y[data.rows['val']], data.p0[data.rows['val']], preds['val'])}")
    log(f"LEAKY top features {info['top_gain_features'][:6]}")


if __name__ == "__main__":
    main()
