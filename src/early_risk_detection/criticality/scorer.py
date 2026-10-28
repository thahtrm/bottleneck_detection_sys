"""Batch scoring of task criticality from a Jira DuckDB with a trained ``criticality`` bundle.

Every score is the model's view of the issue AT ITS CREATION TIME T0: T0-safe static features,
plus the TGN memory of the issue / reporter / assignee / project frozen just before T0. The
whole database is replayed (history and memory need it); only the selected issues are scored.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import torch

from ..bundle import ModelBundle
from ..embeddings import embed_issues
from ..features.t0 import add_t0_features, issue_durations, load_issues_t0, load_timed_links, select_issues
from .memory import EventStream, load_memory, snapshot_memory
from .readout import Readout, predict_scores, static_matrix
from .stream import build_event_stream, load_neighbours

logger = logging.getLogger(__name__)

KIND = "criticality"


class CriticalityScorer:
    def __init__(self, bundle: ModelBundle, device: str | torch.device | None = None):
        self.bundle = bundle
        cfg = bundle.config
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        st = bundle.load_arrays("normalizers.npz")
        self.mu, self.sd, self.amu, self.asd = st["mu"], st["sd"], st["amu"], st["asd"]
        self.svd_components = st["svd_components"]
        self.instances, self.types = cfg["instances"], cfg["types"]
        self.backoff = cfg["propensity_backoff"]
        self.readouts = []
        for name in cfg["readout_files"]:
            m = Readout(len(cfg["static_features"]), use_z=True, dropout=cfg["dropout"]).to(self.device)
            m.load_state_dict(torch.load(bundle.file(name), map_location=self.device))
            self.readouts.append(m.eval())

    @classmethod
    def load(cls, path: str | Path, device: str | torch.device | None = None) -> CriticalityScorer:
        return cls(ModelBundle.load(path, kind=KIND), device)

    def score(self, duckdb_path: str | Path, embeddings, issue_keys: list[str] | None = None,
              as_of: float | pd.Timestamp | None = None, open_only: bool = True,
              stream_dir: str | Path | None = None, top_pct: float | None = None) -> pd.DataFrame:
        """Score issues of a Jira DuckDB (schema of ``early_risk_detection.data.etl``).

        embeddings  ``EmbeddingIndex`` / ``OllamaEmbedder`` (anything with ``get(df)`` or ``__call__(texts)``).
        issue_keys  ``"instance|issue_key"`` uids to score; default: every issue open at ``as_of``.
        as_of       epoch seconds / timestamp used to decide which issues are open (default: now).
        stream_dir  where the event stream memmaps are written; reuse it across calls on the same DB.
        top_pct     fraction flagged critical per instance (default: the bundle's, 5%).

        Returns one row per scored issue: ``uid, instance, issue_key, project, created_ts, score,
        rank_in_instance, is_critical``.
        """
        cfg = self.bundle.config
        top_pct = cfg["top_pct"] if top_pct is None else top_pct
        con = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            logger.info("Loading issues and T0 attributes...")
            df = load_issues_t0(con)
            links = load_timed_links(con)
            sel = select_issues(df, issue_keys, as_of, open_only)
            logger.info(f"{len(df):,} issues in database, {len(sel):,} selected for scoring")
            if len(sel) == 0:
                return _empty()
            logger.info("T0 features...")
            add_t0_features(df, links, issue_durations(df), backoff=self.backoff)
            with tempfile.TemporaryDirectory() as tmp:
                sdir = Path(stream_dir) if stream_dir else Path(tmp)
                if not (sdir / "meta.json").exists():
                    logger.info(f"Building event stream in {sdir}...")
                    build_event_stream(con, df, sdir)
                z = self._memory_snapshots(df, sel, sdir)
        finally:
            con.close()

        sub = df.iloc[sel].reset_index(drop=True)
        text_emb = embed_issues(embeddings, sub).astype(np.float32)
        svd = text_emb @ self.svd_components.T
        for k in range(svd.shape[1]):
            sub[f"svd_{k}"] = svd[:, k]
        x, _ = static_matrix(sub, self.instances, self.types)
        x = ((x - self.mu) / self.sd).astype(np.float32)
        scores = predict_scores(self.readouts, x, z, self.device)

        out = pd.DataFrame({"uid": sub["instance"] + "|" + sub["issue_key"], "instance": sub["instance"],
                            "issue_key": sub["issue_key"], "project": sub["project"],
                            "created_ts": sub["created_ts"], "score": scores})
        out["rank_in_instance"] = out.groupby("instance")["score"].rank(ascending=False, method="first").astype(int)
        n_inst = out.groupby("instance")["score"].transform("size")
        out["is_critical"] = out["rank_in_instance"] <= np.ceil(top_pct * n_inst)
        return out.sort_values(["instance", "rank_in_instance"]).reset_index(drop=True)

    # ------------------------------------------------------------------------------------------
    def _memory_snapshots(self, df: pd.DataFrame, sel: np.ndarray, sdir: Path) -> np.ndarray:
        import json

        meta = json.loads((sdir / "meta.json").read_text())
        if meta["n_issue"] != len(df):
            raise ValueError(f"stream in {sdir} was built for {meta['n_issue']:,} issues, database has {len(df):,}")
        stream = EventStream(sdir, self.bundle.config["chunk"], self.device)
        model = load_memory(self.bundle.file("tgn_memory.pt"), meta["n_nodes"], self.device)
        created = df["created_ts"].values.astype(np.float64)
        logger.info(f"Replaying {meta['n_events']:,} events for {len(sel):,} snapshots on {self.device}...")
        Z, aux, applied_max = snapshot_memory(model, stream, created, load_neighbours(sdir), rows=sel)
        assert np.all(applied_max < created[sel]), "temporal leakage in memory snapshot"
        del model
        return np.concatenate([Z, ((aux - self.amu) / self.asd).astype(np.float16)], 1)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["uid", "instance", "issue_key", "project", "created_ts", "score",
                                 "rank_in_instance", "is_critical"])
