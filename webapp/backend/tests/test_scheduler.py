from datetime import datetime, timezone

from fastapi.testclient import TestClient

from erw import jobs
from erw.jobs import start_scheduler
from erw.main import create_app
from erw.models import Notification


def test_scheduler_registers_jobs_in_tz(settings):
    s = start_scheduler(settings)
    try:
        jobs_ = {j.id: j for j in s.get_jobs()}
        assert set(jobs_) == {"morning_batch", "daily_digest"}
        assert str(s.timezone) == "Asia/Ho_Chi_Minh"
        for j in jobs_.values():
            assert j.max_instances == 1 and j.coalesce is True
        assert "mon-fri" in str(jobs_["daily_digest"].trigger) or "day_of_week='mon-fri'" in str(jobs_["daily_digest"].trigger)
    finally:
        s.shutdown(wait=False)


def test_morning_job_runs_catch_up_then_batch_and_survives_errors(settings, engine, monkeypatch):
    calls = []
    jobs.configure(settings, engine)
    monkeypatch.setattr(jobs, "run_catch_up", lambda: calls.append("catch_up"))
    import erw.ml.batch as batch

    monkeypatch.setattr(batch, "LibraryScorers", lambda s: object())
    monkeypatch.setattr(batch, "make_unload_llm", lambda s: (lambda: None))

    def boom(*a, **k):
        calls.append("batch")
        raise RuntimeError("fail")

    monkeypatch.setattr(batch, "run_model_batch", boom)
    jobs.morning_job()  # must not raise
    assert calls == ["catch_up", "batch"]

    def busy(*a, **k):
        raise batch.BatchBusy("busy")

    monkeypatch.setattr(batch, "run_model_batch", busy)
    jobs.morning_job()


def test_digest_job_records_notification_per_project(settings, engine, session):
    jobs.configure(settings, engine)
    jobs.digest_job(datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc))
    jobs.digest_job(datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc))
    rows = session.query(Notification).all()
    assert [(r.kind, r.dedup_key, r.status) for r in rows] == [("digest", "digest:DEMO:2026-11-04", "disabled")]


def test_lifespan_starts_and_stops_scheduler(settings, engine):
    app = create_app(settings, engine=engine, catch_up_on_startup=False, start_scheduler_on_startup=True)
    with TestClient(app):
        assert app.state.scheduler.running
    assert not app.state.scheduler.running
    # executor still usable by later tests
    assert jobs.executor.submit(lambda: 1).result() == 1
