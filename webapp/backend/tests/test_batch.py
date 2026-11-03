from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from conftest import load_fixture
from sqlalchemy import select

from erw.ingest.sync import upsert_issue_json
from erw.kv import kv_get
from erw.ml import batch
from erw.ml.batch import BatchBusy, run_model_batch
from erw.models import Issue, Score

NOW = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)


class FakeScorers:
    def __init__(self, keys=("DEMO-1",)):
        self.keys = list(keys)
        self.calls = []

    def delay(self, db, keys):
        self.calls.append(("delay", keys))
        return pd.DataFrame([
            dict(uid=k, p_delay=0.7, predicted_duration_days=30.0, is_at_risk=True) for k in keys
        ])

    def criticality(self, db, keys):
        self.calls.append(("crit", keys))
        return pd.DataFrame([
            dict(uid=k, score=0.9, is_critical=True, rank_in_instance=i + 1) for i, k in enumerate(keys)
        ])


@pytest.fixture
def wsettings(settings, tmp_path):
    from early_risk_detection.data.etl.loader import DuckDBLoader

    base = tmp_path / "base.duckdb"
    DuckDBLoader(str(base)).init_schema()
    return settings.model_copy(update=dict(
        base_duckdb=str(base), work_duckdb=str(tmp_path / "work.duckdb"), stream_dir=str(tmp_path / "stream")))


@pytest.fixture
def seeded(session, wsettings):
    upsert_issue_json(session, load_fixture("rest_issue_demo1"), wsettings)
    session.commit()
    i = session.get(Issue, "DEMO-1")
    i.status_category = "indeterminate"
    session.commit()
    return i


def test_batch_writes_scores_and_reevaluates(session, wsettings, seeded):
    unloaded = []
    rep = run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=lambda: unloaded.append(1))
    assert rep["n_issues"] == 1 and "delay_s" in rep and "crit_s" in rep and unloaded
    scorers = {s.scorer for s in session.scalars(select(Score))}
    assert scorers >= {"delay_t0", "criticality_t0", "rules_dynamic"}
    d = session.scalar(select(Score).where(Score.scorer == "delay_t0"))
    assert d.issue_key == "DEMO-1" and d.value == 0.7 and d.extra["is_at_risk"] is True
    assert d.extra["predicted_duration_days"] == 30.0
    c = session.scalar(select(Score).where(Score.scorer == "criticality_t0"))
    assert c.value == 0.9 and c.is_critical and c.extra["rank_in_instance"] == 1


def test_batch_scores_only_open_issues(session, wsettings, seeded):
    seeded.status_category = "done"
    session.commit()
    fake = FakeScorers()
    rep = run_model_batch(session, wsettings, NOW, fake, unload_llm=lambda: None)
    assert rep["n_issues"] == 0 and fake.calls == []
    assert session.scalars(select(Score).where(Score.scorer == "delay_t0")).all() == []


def test_batch_passes_erw_uids(session, wsettings, seeded):
    fake = FakeScorers()
    run_model_batch(session, wsettings, NOW, fake, unload_llm=lambda: None)
    assert fake.calls[0] == ("delay", ["ERW|DEMO-1"])


def test_stream_dir_removed_when_issue_count_changes(session, wsettings, seeded):
    stream = Path(wsettings.stream_dir)
    run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=lambda: None)
    assert kv_get(session, "last_stream_n_issues") == "1"
    stream.mkdir()
    (stream / "meta.json").write_text("{}")
    run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=lambda: None)
    assert (stream / "meta.json").exists()  # same count: kept
    other = load_fixture("rest_issue_demo1")
    other["key"], other["id"] = "DEMO-2", "10002"
    upsert_issue_json(session, other, wsettings)
    session.commit()
    run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=lambda: None)
    assert not stream.exists()
    assert kv_get(session, "last_stream_n_issues") == "2"


def test_batch_busy_when_locked(session, wsettings, seeded):
    assert batch._LOCK.acquire(blocking=False)
    try:
        with pytest.raises(BatchBusy):
            run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=lambda: None)
    finally:
        batch._LOCK.release()


def test_lock_released_after_failure(session, wsettings, seeded):
    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=boom)
    run_model_batch(session, wsettings, NOW, FakeScorers(), unload_llm=lambda: None)


def test_library_scorers_construct_is_lazy(wsettings):
    s = batch.LibraryScorers(wsettings)  # no bundles/embeddings needed to construct
    assert s._emb is None
