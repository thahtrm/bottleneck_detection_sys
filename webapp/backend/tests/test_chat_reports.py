from datetime import UTC, datetime, timedelta

from erw import jobs
from erw.models import ChatMessage, Issue, Project, ProjectMember, ReportSlot, RiskState, User
from erw.pipeline.chat_reports import run_due_reports
from erw.pipeline.digest import collect_digest

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)  # Wednesday 08:00 Asia/Ho_Chi_Minh
SATURDAY = datetime(2026, 11, 7, 1, 0, tzinfo=UTC)


def _user(session, email, admin=False) -> User:
    user = User(email=email, name=email, password_hash="x", is_admin=admin, created_at=NOW)
    session.add(user)
    session.flush()
    return user


def _membership(session, user: User, project: str, role: str) -> None:
    if session.get(Project, project) is None:
        session.add(Project(key=project, name=project))
        session.flush()
    session.add(ProjectMember(project_key=project, user_id=user.id, role=role))
    session.flush()


def test_same_minute_does_not_duplicate_report(session, settings):
    pm = _user(session, "pm@example.com")
    _membership(session, pm, "DEMO", "pm")
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()
    first = run_due_reports(session, NOW, settings)
    second = run_due_reports(session, NOW, settings)
    session.flush()
    assert len(first) == 1 and second == []
    rows = session.query(ChatMessage).all()
    assert len(rows) == 1
    assert rows[0].dedup_key == f"report:{pm.id}:DEMO:08:00:2026-11-04"
    assert rows[0].kind == "report" and rows[0].recommendation_status == "pending"


def test_saturday_slot_inserts_nothing(session, settings):
    pm = _user(session, "pm@example.com")
    _membership(session, pm, "DEMO", "pm")
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()
    assert run_due_reports(session, SATURDAY, settings) == []
    assert session.query(ChatMessage).count() == 0


def test_empty_schedule_inserts_nothing(session, settings):
    pm = _user(session, "pm@example.com")
    _membership(session, pm, "DEMO", "pm")
    session.flush()
    assert run_due_reports(session, NOW, settings) == []


def test_one_slot_reports_each_pm_project(session, settings):
    pm = _user(session, "pm@example.com")
    _membership(session, pm, "DEMO", "pm")
    _membership(session, pm, "OTHER", "pm")
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()
    due = run_due_reports(session, NOW, settings)
    keys = sorted(row.dedup_key for row in session.query(ChatMessage).all())
    assert len(due) == 2
    assert keys == [
        f"report:{pm.id}:DEMO:08:00:2026-11-04",
        f"report:{pm.id}:OTHER:08:00:2026-11-04",
    ]


def test_viewer_slot_inserts_nothing(session, settings):
    viewer = _user(session, "viewer@example.com")
    _membership(session, viewer, "DEMO", "viewer")
    session.add(ReportSlot(user_id=viewer.id, time_hhmm="08:00"))
    session.flush()
    assert run_due_reports(session, NOW, settings) == []


def test_report_facts_use_digest_counts(session, settings):
    pm = _user(session, "pm@example.com")
    _membership(session, pm, "DEMO", "pm")
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.add(
        Issue(
            key="DEMO-1",
            project_key="DEMO",
            summary="Việc",
            status_category="indeterminate",
            assignee_name="Lan",
            created_at=NOW - timedelta(days=2),
        )
    )
    session.add(RiskState(issue_key="DEMO-1", level="HIGH", blocked=True, updated_at=NOW))
    session.flush()
    run_due_reports(session, NOW, settings)
    snap = collect_digest(session, "DEMO", NOW, settings)
    body = session.query(ChatMessage).one().body
    assert f"Nguy cơ trễ: {snap.risky_count} ({snap.raised_24h} tăng bậc 24 giờ)." in body
    assert f"Bị block: {snap.blocked_count}." in body
    assert "DEMO-1" in body


def test_digest_job_does_not_write_chat(settings, engine, session):
    jobs.configure(settings, engine)
    jobs.digest_job(NOW)
    session.expire_all()
    assert session.query(ChatMessage).count() == 0


def test_report_job_runs_due_reports(settings, engine, monkeypatch):
    jobs.configure(settings, engine)
    seen = []
    monkeypatch.setattr("erw.jobs.run_due_reports", lambda session, now, settings: seen.append(now) or [])
    jobs.report_job(NOW)
    assert seen == [NOW]
