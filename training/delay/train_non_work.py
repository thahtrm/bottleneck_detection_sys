"""Delay model component 5 — pre-triage non-work models (re-implementation of the study's gate).

Labels (FINAL resolution, resolved issues only):
  non-work       resolution matches gate.NONWORK_PATTERN (duplicate, invalid, won't fix, ...)
  early non-work non-work AND closed within --early_days of creation
Models (XGBoost, fitted on the resolved train split):
  nonwork.ubj        P(non-work | 264 delay features)                    -> blend input (1 - p)
  early_nonwork.ubj  P(early non-work | delay features + causal non-work rates + semantic kNN)
                                                                          -> pre-triage gate
Writes gate_{val,test}.parquet (uid, probabilities, gate signals) for fit_blend_gate.py and
gate_config.json + both models to the staging bundle.
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
import torch
import xgboost as xgb
from numpy.lib.format import open_memmap
from sklearn.metrics import average_precision_score, roc_auc_score

from early_risk_detection._logging import setup_logging
from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.gate import (
    CAUSAL_NW_COLUMNS,
    SEM_KNN_COLUMNS,
    causal_nonwork_features,
    nonwork_labels,
    semantic_knn_features,
)
from early_risk_detection.delay.scorer import KIND
from early_risk_detection.features.t0 import load_issues_t0

log = logging.getLogger(__name__).info

PARAMS = {"n_estimators": 300, "max_depth": 7, "learning_rate": 0.08, "subsample": 0.85, "colsample_bytree": 0.7,
          "min_child_weight": 10, "reg_lambda": 5.0, "tree_method": "hist", "n_jobs": -1, "eval_metric": "logloss"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default="data/jira.duckdb")
    ap.add_argument("--emb_dir", default="data")
    ap.add_argument("--data_dir", default="data/delay_t0")
    ap.add_argument("--stage", default="bundles/staging/delay")
    ap.add_argument("--early_days", type=float, default=7.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    setup_logging()
    d = Path(args.data_dir)
    stage = ModelBundle.staging(args.stage, KIND)
    t0 = time.time()

    con = duckdb.connect(args.duckdb, read_only=True)
    df = load_issues_t0(con)
    con.close()
    nonwork = nonwork_labels(df["resolution"]) * (df["is_resolved"].values == 1)
    lab = {s: pd.read_parquet(d / f"{s}_labels.parquet") for s in ["train", "val", "test"]}
    rows = {s: lab[s]["row_id"].values.astype(np.int64) for s in lab}
    prior = float(nonwork[rows["train"]].mean())
    log(f"non-work rate: train {prior:.4f} | val {nonwork[rows['val']].mean():.4f} | test {nonwork[rows['test']].mean():.4f}")

    cfg = {"prior": prior, "early_days": args.early_days, "smoothing": 5.0, "window_days": 90.0,
           "active_window": 256, "resolved_pool": 4096, "k": 10, "dup_sim": 0.90}
    log("[1/3] Causal rolling non-work rates...")
    causal = causal_nonwork_features(df, nonwork, prior, smoothing=cfg["smoothing"], window_days=cfg["window_days"])
    log("[2/3] Semantic kNN over Ollama embeddings (GPU)...")
    row_to_unique = np.load(Path(args.emb_dir) / "emb_row_to_unique_all.npy")
    emb = open_memmap(Path(args.emb_dir) / "emb_unique_all_fp16.npy", mode="r")

    def get_emb(r: np.ndarray) -> np.ndarray:
        u = row_to_unique[r]
        o = np.argsort(u)
        out = np.empty((len(r), emb.shape[1]), np.float16)
        out[o] = emb[u[o]]
        return out

    q = np.concatenate([rows["train"], rows["val"], rows["test"]])
    sem_q = semantic_knn_features(df, nonwork, get_emb, query_rows=q, prior=prior,
                                  active_window=cfg["active_window"], resolved_pool=cfg["resolved_pool"],
                                  k=cfg["k"], dup_sim=cfg["dup_sim"],
                                  device=torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    sem = np.zeros((len(df), 4), np.float32)
    sem[q] = sem_q
    log(f"  semantic kNN done in {time.time() - t0:.0f}s")

    log("[3/3] Non-work models...")
    X = {s: pd.read_parquet(d / f"X_xgb_{s}.parquet") for s in ["train", "val", "test"]}
    dur = (df["resolved_ts"].values - df["created_ts"].values) / 86400.0
    early = (nonwork == 1) & (dur <= args.early_days)

    def gate_x(s: str) -> pd.DataFrame:
        r = rows[s]
        extra = pd.DataFrame(np.hstack([causal[r], sem[r]]), columns=CAUSAL_NW_COLUMNS + SEM_KNN_COLUMNS,
                             index=X[s].index)
        return pd.concat([X[s], extra], axis=1)

    m_nw = xgb.XGBClassifier(**PARAMS, random_state=args.seed).fit(X["train"], nonwork[rows["train"]])
    m_nw.save_model(stage.file("nonwork.ubj"))
    m_early = xgb.XGBClassifier(**PARAMS, random_state=args.seed).fit(gate_x("train"), early[rows["train"]])
    m_early.save_model(stage.file("early_nonwork.ubj"))
    stage.save_json("gate_config.json", cfg)

    report = {"config": cfg}
    for s in ["val", "test"]:
        r = rows[s]
        p_nw = m_nw.predict_proba(X[s])[:, 1]
        p_early = m_early.predict_proba(gate_x(s))[:, 1]
        out = pd.DataFrame({"uid": lab[s]["uid"], "p_non_work": p_nw, "p_early_non_work": p_early})
        for j, c in enumerate(CAUSAL_NW_COLUMNS):
            out[c] = causal[r, j]
        for j, c in enumerate(SEM_KNN_COLUMNS):
            out[c] = sem[r, j]
        out.to_parquet(d / f"gate_{s}.parquet", index=False)
        report[s] = {"non_work_roc_auc": roc_auc_score(nonwork[r], p_nw), "non_work_pr_auc": average_precision_score(nonwork[r], p_nw),
                     "early_roc_auc": roc_auc_score(early[r], p_early), "early_pr_auc": average_precision_score(early[r], p_early),
                     "early_rate": float(early[r].mean())}
        log(f"  {s}: {report[s]}")
    (d / "non_work_report.json").write_text(json.dumps(report, indent=2, default=float))
    log(f"Done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
