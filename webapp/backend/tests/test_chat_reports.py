from datetime import UTC, datetime, timedelta

import pytest

from erw import jobs
from erw.models import ChatMessage, Issue, Project, ProjectMember, ReportFile, ReportSlot, RiskState, User
from erw.pipeline.chat_reports import report_abs_path, run_due_reports
from erw.pipeline.digest import collect_digest
from erw.pipeline.health_report import collect_health_snapshot, render_facts_markdown

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)  # Wednesday 08:00 Asia/Ho_Chi_Minh
SATURDAY = datetime(2026, 11, 7, 1, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_reports_dir(tmp_path, settings):
    settings.reports_dir = str(tmp_path / "reports")
    settings.ollama_url = ""


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
    run_due_reports(session, NOW, settings)
    run_due_reports(session, NOW, settings)
    session.flush()
    rows = session.query(ChatMessage).all()
    assert len(rows) == 1
    assert rows[0].dedup_key == f"report:{pm.id}:DEMO:08:00:2026-11-04"
    assert rows[0].kind == "report" and rows[0].recommendation_status == "ready"


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
    run_due_reports(session, NOW, settings)
    keys = sorted(row.dedup_key for row in session.query(ChatMessage).all())
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


def test_health_facts_match_digest_counts(session, settings):
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
    digest = collect_digest(session, "DEMO", NOW, settings)
    msg = session.query(ChatMessage).one()
    assert "Báo cáo sức khỏe" in msg.body
    assert f"Risky {digest.risky_count}" in msg.body
    assert f"Blocked {digest.blocked_count}" in msg.body
    row = session.query(ReportFile).one()
    body = report_abs_path(settings, row.rel_path).read_text(encoding="utf-8")
    assert "## 1. Overview" in body
    assert "## 7. Action recommendations" in body
    assert "DEMO-1" in body
    assert f"Risky: {digest.risky_count}" in body
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    assert snap.allowed_counts["risky_count"] == digest.risky_count
    assert snap.allowed_counts["blocked_count"] == digest.blocked_count
    assert "DEMO-1" in snap.allowed_keys
    facts_only = render_facts_markdown(snap)
    assert "### Facts" in facts_only


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
