"""Batch scoring of delay risk from a Jira DuckDB with a trained ``delay`` bundle.

Pipeline (every step is the code the training scripts used):
  T0 features (O(N) workload simulation over the whole database) -> text features (SVD16 +
  semantic risk) -> two fitted tabular featurizers -> XGBoost 5-fold ensemble, XGBoost AFT,
  CatBoost AFT -> 4-model blend with (1 - P(non-work)) -> pre-triage gate (P(early non-work)
  from causal non-work rates + semantic kNN) -> decision threshold.
The competing-risks CatBoost model supplies the predicted delivery time.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import torch
import xgboost as xgb

from ..bundle import BundleError, ModelBundle
from ..criticality.dual_head import DEFAULT_BUNDLE_PATH, DUAL_HEAD_KIND, DualHeadScorer
from ..embeddings import embed_issues
from ..features.t0 import load_issues_t0, load_timed_links, select_issues
from .features import DelayFeaturizer, TextRiskFeatures, chronological_features
from .gate import (
    CAUSAL_NW_COLUMNS,
    SEM_KNN_COLUMNS,
    causal_nonwork_features,
    gate_mask,
    nonwork_labels,
    semantic_knn_features,
)
from .survival import blend, survival_delay_prob

logger = logging.getLogger(__name__)

KIND = "delay"


class DelayRiskScorer:
    def __init__(self, bundle: ModelBundle, device: str | torch.device | None = None):
        self.bundle = bundle
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        if bundle.kind == DUAL_HEAD_KIND:
            self._dual: DualHeadScorer | None = DualHeadScorer(bundle, self.device)
            return
        self._dual = None
        from catboost import CatBoostRegressor

        self.text = TextRiskFeatures.load(bundle)
        self.fx = DelayFeaturizer.load(bundle, "xgb")
        self.fs = DelayFeaturizer.load(bundle, "surv")
        self.xgb_folds = []
        for f in sorted(bundle.path.glob("xgb_fold*.ubj")):
            m = xgb.XGBClassifier()
            m.load_model(f)
            self.xgb_folds.append(m)
        self.aft = xgb.Booster()
        self.aft.load_model(bundle.file("aft.ubj"))
        self.aft_cfg = bundle.load_json("aft_config.json")
        self.cbs, self.cbs_cr = CatBoostRegressor(), CatBoostRegressor()
        self.cbs.load_model(str(bundle.file("cbs.cbm")))
        self.cbs_cr.load_model(str(bundle.file("cbs_cr.cbm")))
        self.cbs_cfg = bundle.load_json("cbs_config.json")
        self.nonwork, self.early = xgb.XGBClassifier(), xgb.XGBClassifier()
        self.nonwork.load_model(bundle.file("nonwork.ubj"))
        self.early.load_model(bundle.file("early_nonwork.ubj"))
        self.gate_cfg = bundle.load_json("gate_config.json")
        self.blend_cfg = bundle.load_json("blend_gate.json")

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_BUNDLE_PATH,
        device: str | torch.device | None = None,
    ) -> DelayRiskScorer:
        b = ModelBundle.load(path)
        if b.kind not in (KIND, DUAL_HEAD_KIND):
            raise BundleError(f"{path} is a '{b.kind}' bundle, expected '{DUAL_HEAD_KIND}' or '{KIND}'")
        return cls(b, device)

    @property
    def threshold(self) -> float:
        if self._dual is not None:
            return self._dual.threshold
        return float(self.blend_cfg["threshold"])

    def score(self, duckdb_path: str | Path, embeddings, issue_keys: list[str] | None = None,
              as_of: float | pd.Timestamp | None = None, open_only: bool = True,
              stream_dir: str | Path | None = None,
              at_project_change: bool | None = None) -> pd.DataFrame:
        """Delay risk of issues of a Jira DuckDB (schema of ``early_risk_detection.data.etl``).

        embeddings  ``EmbeddingIndex`` / ``OllamaEmbedder``; also used for the semantic kNN
                    candidates (recent issues of the same projects).
        issue_keys  ``"instance|issue_key"`` uids; default: every issue open at ``as_of`` (default now).

        Returns ``uid, instance, issue_key, project, created_ts, planned_duration_days,
        predicted_duration_days, p_delay, is_at_risk, p_delay_raw, gated, p_non_work,
        p_early_non_work, max_sim_resolved``. ``stream_dir`` is accepted for CLI symmetry.
        """
        if self._dual is not None:
            return self._dual.score_delay(
                duckdb_path,
                embeddings=embeddings,
                issue_keys=issue_keys,
                as_of=as_of,
                open_only=open_only,
                stream_dir=stream_dir,
                at_project_change=at_project_change,
            )
        con = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            logger.info("Loading issues and T0 attributes...")
            df, links = load_issues_t0(con), load_timed_links(con)
        finally:
            con.close()
        sel = select_issues(df, issue_keys, as_of, open_only)
        logger.info(f"{len(df):,} issues in database, {len(sel):,} selected for scoring")
        if len(sel) == 0:
            return pd.DataFrame(columns=_COLUMNS)
        logger.info("Workload simulation (T0 features)...")
        base = chronological_features(df, links)
        sub = base.iloc[sel].reset_index(drop=True)
        emb = embed_issues(embeddings, df.iloc[sel].reset_index(drop=True))
        sub = sub.join(self.text.transform(emb, sub))
        Xx, Xs = self.fx.transform(sub), self.fs.transform(sub)

        p_xgb = np.mean([m.predict_proba(Xx)[:, 1] for m in self.xgb_folds], 0)
        planned = sub["planned_duration_days"].values.astype(np.float32)
        pred_aft = self.aft.predict(xgb.DMatrix(Xs))
        p_aft = survival_delay_prob(np.log(np.maximum(1e-3, pred_aft)), planned,
                                    self.aft_cfg["distribution"], self.aft_cfg["scale"])
        p_cbs = survival_delay_prob(self.cbs.predict(Xs), planned, self.cbs_cfg["distribution"], self.cbs_cfg["scale"])
        pred_time = np.exp(np.clip(self.cbs_cr.predict(Xs), -20, 20))
        p_nw = self.nonwork.predict_proba(Xx)[:, 1]

        logger.info("Pre-triage gate signals...")
        g = self.gate_cfg
        nw = nonwork_labels(df["resolution"]) * (df["is_resolved"].values == 1)
        causal = causal_nonwork_features(df, nw, g["prior"], smoothing=g["smoothing"], window_days=g["window_days"])[sel]
        sem = semantic_knn_features(
            df, nw, lambda rows: embed_issues(embeddings, df.iloc[rows].reset_index(drop=True)), query_rows=sel,
            prior=g["prior"], active_window=g["active_window"], resolved_pool=g["resolved_pool"], k=g["k"],
            dup_sim=g["dup_sim"], device=self.device)
        extra = pd.DataFrame(np.hstack([causal, sem]), columns=CAUSAL_NW_COLUMNS + SEM_KNN_COLUMNS, index=Xx.index)
        p_early = self.early.predict_proba(pd.concat([Xx, extra], axis=1))[:, 1]

        b = self.blend_cfg
        p_raw = blend(p_xgb, p_aft, p_cbs, p_nw, b["weights"], b["knots_x"], b["knots_y"])
        gated = gate_mask(p_early, sem[:, 2], b["gate_p_threshold"], b["gate_sim_threshold"])
        p = np.where(gated, p_raw * b["damp"], p_raw)
        out = pd.DataFrame({
            "uid": sub["uid"] if "uid" in sub else sub["instance"] + "|" + sub["issue_key"],
            "instance": sub["instance"], "issue_key": sub["issue_key"], "project": df["project"].values[sel],
            "created_ts": sub["created_ts"], "planned_duration_days": planned,
            "predicted_duration_days": pred_time.astype(np.float32), "p_delay": p,
            "is_at_risk": p >= self.threshold, "p_delay_raw": p_raw, "gated": gated,
            "p_non_work": p_nw, "p_early_non_work": p_early, "max_sim_resolved": sem[:, 2]})
        return out.sort_values("p_delay", ascending=False).reset_index(drop=True)


_COLUMNS = ["uid", "instance", "issue_key", "project", "created_ts", "planned_duration_days", "predicted_duration_days",
            "p_delay", "is_at_risk", "p_delay_raw", "gated", "p_non_work", "p_early_non_work", "max_sim_resolved"]
