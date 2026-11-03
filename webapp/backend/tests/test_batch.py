from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from conftest import load_fixture
from sqlalchemy import select

from erw.ingest.sync import upsert_issue_json
from erw.ml import batch
from erw.ml.batch import BatchBusy, run_model_batch
from erw.models import Issue, Score

NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


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


def test_stream_dir_removed_before_criticality_every_batch(session, wsettings, seeded):
    stream = Path(wsettings.stream_dir)
    seen_meta = []
    seen_sentinel = []

    class Probe(FakeScorers):
        def criticality(self, db, keys):
            seen_meta.append((stream / "meta.json").exists())
            seen_sentinel.append((stream / ".erw_stream").exists())
            return super().criticality(db, keys)

    for _ in range(2):  # constant issue count both times
        stream.mkdir(exist_ok=True)
        (stream / "meta.json").write_text("{}")
        run_model_batch(session, wsettings, NOW, Probe(), unload_llm=lambda: None)
    assert seen_meta == [False, False]
    assert seen_sentinel == [True, True]


def test_reset_stream_dir_accepts_sentinel_with_partial_files(wsettings):
    import shutil

    from erw.ml.batch import _reset_stream_dir

    stream = Path(wsettings.stream_dir)
    stream.mkdir(parents=True, exist_ok=True)
    (stream / ".erw_stream").touch()
    (stream / "events.parquet").write_text("dummy")
    (stream / "part.tmp").write_text("partial")
    _reset_stream_dir(wsettings)
    assert not stream.exists()

    # rejecting arbitrary dirs without sentinel or meta.json
    stream.mkdir(parents=True, exist_ok=True)
    (stream / "random.txt").write_text("data")
    with pytest.raises(ValueError, match="not an event stream"):
        _reset_stream_dir(wsettings)
    assert stream.exists()
    shutil.rmtree(stream)


def test_soft_deleted_issue_excluded_from_sync_and_scoring(session, wsettings, seeded):
    import duckdb

    other = load_fixture("rest_issue_demo1")
    other["key"], other["id"] = "DEMO-2", "10002"
    upsert_issue_json(session, other, wsettings)
    session.get(Issue, "DEMO-2").status_category = "indeterminate"
    session.get(Issue, "DEMO-2").deleted_at = NOW
    session.commit()
    fake = FakeScorers()
    rep = run_model_batch(session, wsettings, NOW, fake, unload_llm=lambda: None)
    assert rep["n_issues"] == 1 and fake.calls[0] == ("delay", ["ERW|DEMO-1"])
    con = duckdb.connect(wsettings.work_duckdb, read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM issues WHERE instance='ERW'").fetchone()[0] == 1
    finally:
        con.close()


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


def test_reset_stream_dir_refuses_unsafe_paths(wsettings, tmp_path):
    for bad in (".", "", str(Path(wsettings.base_duckdb).parent), str(tmp_path.parent)):
        with pytest.raises(ValueError):
            batch._reset_stream_dir(wsettings.model_copy(update={"stream_dir": bad}))
    assert Path(wsettings.base_duckdb).exists()


def test_reset_stream_dir_refuses_foreign_dir(wsettings, tmp_path):
    d = tmp_path / "foreign"
    d.mkdir()
    (d / "x.txt").write_text("keep")
    with pytest.raises(ValueError, match="foreign"):
        batch._reset_stream_dir(wsettings.model_copy(update={"stream_dir": str(d)}))
    assert (d / "x.txt").exists()


def test_reset_stream_dir_deletes_event_stream_and_empty(wsettings, tmp_path):
    d = tmp_path / "stream"
    d.mkdir()
    (d / "meta.json").write_text("{}")
    (d / "a.npy").write_text("x")
    batch._reset_stream_dir(wsettings)
    assert not d.exists()
    batch._reset_stream_dir(wsettings)  # missing: no-op
    d.mkdir()
    batch._reset_stream_dir(wsettings)  # empty: removed
    assert not d.exists()
