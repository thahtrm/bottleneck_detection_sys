"""Stage 1 — Full-Jira (2.68M issues) delay-risk dataset with T0-safe features + fitted featurizers.

Rows / split are those of the delay study (row_id order = created_ts, instance, issue_key):
  train      resolved issues, first 70%            (XGBoost, non-work models)
  train_cens train + issues still open at the train cutoff, right-censored at the cutoff (AFT, CatBoost)
  val / test next 15% / last 15% of resolved issues  (out-of-time)
Difference from the original study (baselines/build_dataset_v1_final_attrs.py): priority /
issuetype / assignee and link counts are taken AS OF CREATION (early_risk_detection.features.t0);
labels keep the FINAL-attribute definition.

Outputs (--out_dir):      {split}_labels.parquet, X_xgb_{split}.parquet, X_surv_{split}.parquet
Staging bundle (--stage): text_features.npz, xgb_* / surv_* featurizer state
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from numpy.lib.format import open_memmap

from early_risk_detection._logging import setup_logging
from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.features import DelayFeaturizer, TextRiskFeatures, chronological_features
from early_risk_detection.delay.scorer import KIND
from early_risk_detection.features.t0 import chronological_split, load_issues_t0, load_timed_links

log = logging.getLogger(__name__).info

LABELS = ["row_id", "uid", "created_ts", "is_delayed", "lower_bound", "upper_bound", "is_resolved", "resolution",
          "duration_days", "planned_duration_days", "planned_duration_label"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default="data/jira.duckdb")
    ap.add_argument("--emb_dir", default="data")
    ap.add_argument("--out_dir", default="data/delay_t0")
    ap.add_argument("--stage", default="bundles/staging/delay")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    setup_logging()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stage = ModelBundle.staging(args.stage, KIND)
    t0 = time.time()

    con = duckdb.connect(args.duckdb, read_only=True)
    log("[1/5] Issues with T0 attributes + leak-safe links...")
    df, links = load_issues_t0(con), load_timed_links(con)
    con.close()
    log("[2/5] O(N) chronological workload simulation...")
    base = chronological_features(df, links)
    base["uid"] = base["instance"] + "|" + base["issue_key"]

    split = chronological_split(df)
    res = base["is_resolved"].values == 1
    tr_res, tr_all = (split == "train") & res, split == "train"
    cutoff = float(base["created_ts"].values[tr_res].max())
    log(f"  train {tr_res.sum():,} (+{(tr_all & ~res).sum():,} censored) | val {(split == 'val').sum():,} | "
        f"test {(split == 'test').sum():,} | delay rate train {base.is_delayed.values[tr_res].mean():.4f}")

    log("[3/5] Text features: SVD16 + semantic delay risk, fitted on a train sample...")
    row_to_unique = np.load(Path(args.emb_dir) / "emb_row_to_unique_all.npy")
    emb = open_memmap(Path(args.emb_dir) / "emb_unique_all_fp16.npy", mode="r")
    assert len(row_to_unique) == len(base)
    rng = np.random.default_rng(args.seed)
    fit_rows = np.sort(rng.choice(np.flatnonzero(tr_res), size=min(200_000, int(tr_res.sum())), replace=False))
    text = TextRiskFeatures().fit(emb[row_to_unique[fit_rows]], base["is_delayed"].values[fit_rows], seed=args.seed)
    text.save(stage)
    active = np.flatnonzero(split != "none")
    tf = pd.concat([text.transform(emb[row_to_unique[active[c:c + 200_000]]], base.iloc[active[c:c + 200_000]])
                    for c in range(0, len(active), 200_000)])
    base = base.join(tf)

    sets = {"train": base[tr_res].reset_index(drop=True), "val": base[split == "val"].reset_index(drop=True),
            "test": base[split == "test"].reset_index(drop=True)}
    cens = base[tr_all].reset_index(drop=True)
    open_m = cens["is_resolved"].values == 0
    lb = np.maximum(0.1, (cutoff - cens.loc[open_m, "created_ts"].values) / 86400.0).astype(np.float32)
    cens.loc[open_m, "lower_bound"] = lb
    cens.loc[open_m, "upper_bound"] = np.inf
    cens.loc[open_m, "is_delayed"] = (lb > cens.loc[open_m, "planned_duration_label"].values).astype(np.int8)
    sets["train_cens"] = cens
    for name, d in sets.items():
        d[LABELS].to_parquet(out / f"{name}_labels.parquet", index=False)

    log("[4/5] Tabular featurizer for the classifiers (fit on resolved train)...")
    fx = DelayFeaturizer(seed=args.seed)
    fx.fit_transform(sets["train"]).to_parquet(out / "X_xgb_train.parquet", index=False)
    for s in ["val", "test"]:
        fx.transform(sets[s]).to_parquet(out / f"X_xgb_{s}.parquet", index=False)
    fx.save(stage, "xgb")
    log("[5/5] Tabular featurizer for the survival models (fit on censored train)...")
    fs = DelayFeaturizer(seed=args.seed)
    fs.fit_transform(sets["train_cens"]).to_parquet(out / "X_surv_train_cens.parquet", index=False)
    for s in ["val", "test"]:
        fs.transform(sets[s]).to_parquet(out / f"X_surv_{s}.parquet", index=False)
    fs.save(stage, "surv")
    (out / "dataset_meta.json").write_text(json.dumps({
        "train_cutoff_ts": cutoff, "n": {k: len(v) for k, v in sets.items()},
        "n_features": {"xgb": len(fx.columns), "surv": len(fs.columns)}}, indent=2))
    log(f"Done in {time.time() - t0:.0f}s -> {out}, {stage.path}")


if __name__ == "__main__":
    main()
