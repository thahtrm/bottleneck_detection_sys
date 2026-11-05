from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.ml.duckdb_sync import ensure_work_db, sync_erw_instance
from erw.models import Issue, Score
from erw.pipeline.alerts import dispatch
from erw.pipeline.evaluate import evaluate_all
from erw.settings import Settings

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_batch_lock = _LOCK



class BatchBusy(RuntimeError):
    pass


class Scorers(Protocol):
    def delay(self, db: str, keys: list[str]) -> pd.DataFrame: ...
    def criticality(self, db: str, keys: list[str]) -> pd.DataFrame: ...


class LibraryScorers:
    """Real scorers; uses DualHeadScorer (bundles/tgn_dual_head) by default, loaded on first use."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._dual = self._delay = self._crit = self._emb = None
        self._cached_dual_key: tuple[str, tuple[str, ...]] | None = None
        self._cached_dual_df: pd.DataFrame | None = None

    def _load(self):
        if self._emb is not None:
            return
        from early_risk_detection import CriticalityScorer, DelayRiskScorer, DualHeadScorer
        from early_risk_detection.embeddings import EmbeddingIndex, OllamaEmbedder

        s = self.settings
        self._emb = EmbeddingIndex(s.emb_dir, fallback=OllamaEmbedder(endpoint=f"{s.ollama_url}/api/embed"))
        bdir = Path(s.bundles_dir)
        dual_name = getattr(s, "default_bundle", "tgn_dual_head")
        dual_path = bdir / dual_name
        if (dual_path / "manifest.json").exists():
            self._dual = DualHeadScorer.load(dual_path)
        else:
            self._delay = DelayRiskScorer.load(bdir / "delay")
            self._crit = CriticalityScorer.load(bdir / "criticality")

    def _run_dual(self, db: str, keys: list[str]) -> pd.DataFrame:
        cache_key = (str(db), tuple(keys))
        if self._cached_dual_key == cache_key and self._cached_dual_df is not None:
            df = self._cached_dual_df
            self._cached_dual_key = None
            self._cached_dual_df = None
            return df
        _reset_stream_dir(self.settings)
        stream_dir_path = Path(self.settings.stream_dir)
        stream_dir_path.mkdir(parents=True, exist_ok=True)
        (stream_dir_path / ".erw_stream").touch()
        df = self._dual.score(
            db,
            self._emb,
            issue_keys=keys,
            as_of=None,
            stream_dir=self.settings.stream_dir,
            top_pct=self.settings.criticality_top_pct,
            delay_threshold=self.settings.delay_threshold,
        )
        self._cached_dual_key = cache_key
        self._cached_dual_df = df
        return df

    def delay(self, db: str, keys: list[str]) -> pd.DataFrame:
        self._load()
        if self._dual is not None:
            from early_risk_detection.criticality.dual_head import DELAY_COLUMNS

            df = self._run_dual(db, keys)
            return df[DELAY_COLUMNS].sort_values("p_delay", ascending=False).reset_index(drop=True)
        return self._delay.score(db, self._emb, issue_keys=keys, as_of=None)

    def criticality(self, db: str, keys: list[str]) -> pd.DataFrame:
        self._load()
        if self._dual is not None:
            from early_risk_detection.criticality.dual_head import CRITICALITY_COLUMNS

            df = self._run_dual(db, keys)
            return df[CRITICALITY_COLUMNS].sort_values(["instance", "rank_in_instance"]).reset_index(drop=True)
        return self._crit.score(db, self._emb, issue_keys=keys, stream_dir=self.settings.stream_dir)


def make_unload_llm(settings: Settings) -> Callable[[], None]:
    def unload() -> None:
        try:
            httpx.post(
                f"{settings.ollama_url}/api/generate",
                json={"model": settings.llm_model, "keep_alive": 0},
                timeout=10,
            )
        except Exception:  # best effort
            log.warning("could not unload LLM", exc_info=True)

    return unload


def _reset_stream_dir(settings: Settings) -> None:
    """Delete the library event stream dir, refusing anything that is not clearly one."""
    raw = str(settings.stream_dir).strip()
    if not raw:
        raise ValueError("stream_dir is empty")
    path = Path(raw).resolve()
    protected = [Path.cwd().resolve(), Path(path.anchor), Path.home().resolve()]
    for other in (Path(settings.base_duckdb).parent, Path(settings.bundles_dir), Path(settings.emb_dir)):
        o = other.resolve()
        if path == o or path in o.parents:
            protected.append(path)
    if path in protected:
        raise ValueError(f"refusing to delete unsafe stream_dir: {path}")
    if not path.exists():
        return
    is_stream = not any(path.iterdir()) or (path / "meta.json").exists() or (path / ".erw_stream").exists()
    if not path.is_dir() or not is_stream:
        raise ValueError(f"stream_dir is not an event stream (no meta.json or .erw_stream), refusing to delete: {path}")
    shutil.rmtree(path)


def _key(uid: str) -> str:
    return uid.split("|", 1)[1] if "|" in uid else uid


def run_model_batch(
    session: Session,
    settings: Settings,
    now: datetime,
    scorers: Scorers,
    *,
    unload_llm: Callable[[], None],
    sender=None,
) -> dict:
    if not _LOCK.acquire(blocking=False):
        raise BatchBusy("another model batch is running")
    try:
        unload_llm()
        issues = session.scalars(select(Issue).where(Issue.deleted_at.is_(None)).order_by(Issue.key)).all()
        ensure_work_db(settings)
        sync_erw_instance(settings, [i.raw for i in issues])
        open_keys = [i.key for i in issues if i.status_category != "done"]
        report = {"n_issues": len(open_keys), "delay_s": 0.0, "crit_s": 0.0}
        if open_keys:
            uids = [f"{settings.erw_instance}|{k}" for k in open_keys]
            db = str(settings.work_duckdb)

            t = time.monotonic()
            for r in scorers.delay(db, uids).itertuples(index=False):
                session.add(Score(
                    issue_key=_key(r.uid), scorer="delay_t0", as_of=now, value=float(r.p_delay),
                    extra={"predicted_duration_days": float(r.predicted_duration_days), "is_at_risk": bool(r.is_at_risk)},
                ))
            report["delay_s"] = round(time.monotonic() - t, 2)
            session.commit()

            # event stream is rebuilt every batch: changelog/link events can change at constant issue count
            _reset_stream_dir(settings)
            stream_dir_path = Path(settings.stream_dir)
            stream_dir_path.mkdir(parents=True, exist_ok=True)
            (stream_dir_path / ".erw_stream").touch()
            t = time.monotonic()
            for r in scorers.criticality(db, uids).itertuples(index=False):
                session.add(Score(
                    issue_key=_key(r.uid), scorer="criticality_t0", as_of=now, value=float(r.score),
                    is_critical=bool(r.is_critical), extra={"rank_in_instance": int(r.rank_in_instance)},
                ))
            report["crit_s"] = round(time.monotonic() - t, 2)
            session.commit()

        changes = evaluate_all(session, now, settings)
        dispatch(session, changes, now, settings, sender)
        session.commit()
        return report
    finally:
        _LOCK.release()
