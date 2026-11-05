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

from ..bundle import BundleError, ModelBundle
from ..embeddings import embed_issues
from ..features.t0 import add_t0_features, issue_durations, load_issues_t0, load_timed_links, select_issues
from .dual_head import DEFAULT_BUNDLE_PATH, DUAL_HEAD_KIND, DualHeadScorer
from .memory import EventStream, load_memory, snapshot_memory, snapshot_memory_at_change
from .readout import Readout, predict_scores, static_matrix
from .stream import build_event_stream, load_neighbours

logger = logging.getLogger(__name__)

KIND = "criticality"


class CriticalityScorer:
    def __init__(self, bundle: ModelBundle, device: str | torch.device | None = None):
        self.bundle = bundle
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        if bundle.kind == DUAL_HEAD_KIND:
            self._dual: DualHeadScorer | None = DualHeadScorer(bundle, self.device)
            return
        self._dual = None
        cfg = bundle.config
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
    def load(
        cls,
        path: str | Path = DEFAULT_BUNDLE_PATH,
        device: str | torch.device | None = None,
    ) -> CriticalityScorer:
        b = ModelBundle.load(path)
        if b.kind not in (KIND, DUAL_HEAD_KIND):
            raise BundleError(f"{path} is a '{b.kind}' bundle, expected '{DUAL_HEAD_KIND}' or '{KIND}'")
        return cls(b, device)

    def score(self, duckdb_path: str | Path, embeddings, issue_keys: list[str] | None = None,
              as_of: float | pd.Timestamp | None = None, open_only: bool = True,
              stream_dir: str | Path | None = None, top_pct: float | None = None,
              at_project_change: bool | None = None) -> pd.DataFrame:
        """Score issues of a Jira DuckDB (schema of ``early_risk_detection.data.etl``).

        embeddings  ``EmbeddingIndex`` / ``OllamaEmbedder`` (anything with ``get(df)`` or ``__call__(texts)``).
        issue_keys  ``"instance|issue_key"`` uids to score; default: every issue open at ``as_of``.
        as_of       epoch seconds / timestamp used to decide which issues are open (default: now).
        stream_dir  where the event stream memmaps are written; reuse it across calls on the same DB.
        top_pct     fraction flagged critical per instance (default: the bundle's, 5%).
        at_project_change  if True, freeze memory at the latest active project/issue change up to
                           ``as_of`` rather than strictly before T0 (defaults to bundle config).

        Returns one row per scored issue: ``uid, instance, issue_key, project, created_ts, score,
        rank_in_instance, is_critical``.
        """
        if self._dual is not None:
            return self._dual.score_criticality(
                duckdb_path,
                embeddings=embeddings,
                issue_keys=issue_keys,
                as_of=as_of,
                open_only=open_only,
                stream_dir=stream_dir,
                top_pct=top_pct,
                at_project_change=at_project_change,
            )
        cfg = self.bundle.config
        top_pct = cfg["top_pct"] if top_pct is None else top_pct
        if at_project_change is None:
            at_project_change = bool(cfg.get("project_change_mode", False))
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
                z = self._memory_snapshots(df, sel, sdir, as_of=as_of, at_project_change=at_project_change)
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
    def _memory_snapshots(self, df: pd.DataFrame, sel: np.ndarray, sdir: Path,
                          as_of: float | pd.Timestamp | None = None,
                          at_project_change: bool = False) -> np.ndarray:
        import json

        meta = json.loads((sdir / "meta.json").read_text())
        if meta["n_issue"] != len(df):
            raise ValueError(f"stream in {sdir} was built for {meta['n_issue']:,} issues, database has {len(df):,}")
        stream = EventStream(sdir, self.bundle.config["chunk"], self.device)
        model = load_memory(self.bundle.file("tgn_memory.pt"), meta["n_nodes"], self.device)
        created = df["created_ts"].values.astype(np.float64)
        logger.info(f"Replaying {meta['n_events']:,} events for {len(sel):,} snapshots on {self.device}...")
        if not at_project_change:
            Z, aux, applied_max = snapshot_memory(model, stream, created, load_neighbours(sdir), rows=sel)
            assert np.all(applied_max < created[sel]), "temporal leakage in memory snapshot"
        else:
            dur = issue_durations(df)
            end_ts = created + dur.astype(np.float64) * 86400.0
            cutoff = end_ts - 1.0
            if as_of is not None:
                as_of_ts = float(pd.Timestamp(as_of).timestamp() if not isinstance(as_of, (int, float)) else as_of)
                cutoff = np.minimum(cutoff, as_of_ts)
            ts = np.load(sdir / "ts.npy", mmap_mode="r")
            u_id = np.load(sdir / "u_id.npy", mmap_mode="r")
            v_id = np.load(sdir / "v_id.npy", mmap_mode="r")
            kind = np.load(sdir / "kind.npy", mmap_mode="r")
            scat = np.load(sdir / "scat.npy", mmap_mode="r")
            n = len(df)
            t_snap = np.copy(created)
            m_u = (scat != 0) & (ts >= created[u_id]) & (ts <= cutoff[u_id])
            np.maximum.at(t_snap, u_id[m_u], ts[m_u])
            v_in = (kind == 4) & (v_id < n)
            v_safe = np.minimum(v_id, n - 1)
            m_v = v_in & (ts >= created[v_safe]) & (ts <= cutoff[v_safe])
            np.maximum.at(t_snap, v_id[m_v], ts[m_v])
            Z, aux, applied_last = snapshot_memory_at_change(model, stream, t_snap, load_neighbours(sdir), rows=sel)
            assert np.all(applied_last <= t_snap[sel]) and np.all(applied_last < end_ts[sel]), "temporal leakage in project-change snapshot"
        del model
        return np.concatenate([Z, ((aux - self.amu) / self.asd).astype(np.float16)], 1)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["uid", "instance", "issue_key", "project", "created_ts", "score",
                                 "rank_in_instance", "is_critical"])
