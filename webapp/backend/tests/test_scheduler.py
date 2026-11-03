from datetime import UTC, datetime

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
            assert j.misfire_grace_time == 3 * 3600

        mb_fields = {f.name: str(f) for f in jobs_["morning_batch"].trigger.fields}
        assert mb_fields["day_of_week"] == "mon-fri"
        h_mb, m_mb = (str(int(x)) for x in settings.batch_time.split(":"))
        assert mb_fields["hour"] == h_mb
        assert mb_fields["minute"] == m_mb

        dd_fields = {f.name: str(f) for f in jobs_["daily_digest"].trigger.fields}
        assert dd_fields["day_of_week"] == "mon-fri"
        h_dd, m_dd = (str(int(x)) for x in settings.digest_time.split(":"))
        assert dd_fields["hour"] == h_dd
        assert dd_fields["minute"] == m_dd
    finally:
        s.shutdown(wait=False)


def test_morning_job_runs_catch_up_then_batch_and_survives_errors(settings, engine, monkeypatch):
    calls = []
    jobs.configure(settings, engine)
    monkeypatch.setattr(jobs, "run_catch_up", lambda: calls.append("catch_up"))
    import erw.ml.batch as batch
    import erw.pipeline.alerts as alerts
    import erw.pipeline.evaluate as evaluate

    monkeypatch.setattr(batch, "LibraryScorers", lambda s: object())
    monkeypatch.setattr(batch, "make_unload_llm", lambda s: (lambda: None))
    monkeypatch.setattr(evaluate, "evaluate_all", lambda s, n, st: (calls.append("evaluate_all") or []))
    monkeypatch.setattr(alerts, "dispatch", lambda s, c, n, st: calls.append("dispatch"))

    def boom(*a, **k):
        calls.append("batch")
        raise RuntimeError("fail")

    monkeypatch.setattr(batch, "run_model_batch", boom)
    jobs.morning_job()  # must not raise
    assert calls == ["catch_up", "batch", "evaluate_all", "dispatch"]

    calls.clear()

    def busy(*a, **k):
        calls.append("batch_busy")
        raise batch.BatchBusy("busy")

    monkeypatch.setattr(batch, "run_model_batch", busy)
    jobs.morning_job()
    assert calls == ["catch_up", "batch_busy", "evaluate_all", "dispatch"]


def test_digest_job_records_notification_per_project(settings, engine, session):
    jobs.configure(settings, engine)
    jobs.digest_job(datetime(2026, 11, 4, 1, 0, tzinfo=UTC))
    jobs.digest_job(datetime(2026, 11, 4, 1, 0, tzinfo=UTC))
    rows = session.query(Notification).all()
    assert [(r.kind, r.dedup_key, r.status) for r in rows] == [("digest", "digest:DEMO:2026-11-04", "disabled")]


def test_lifespan_starts_and_stops_scheduler(settings, engine):
    app = create_app(settings, engine=engine, catch_up_on_startup=False, start_scheduler_on_startup=True)
    with TestClient(app):
        assert app.state.scheduler.running
    assert not app.state.scheduler.running
    # executor still usable by later tests
    assert jobs.executor.submit(lambda: 1).result() == 1
