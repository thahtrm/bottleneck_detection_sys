from datetime import UTC, datetime
from pathlib import Path

import pytest

from erw.auth import create_session_token
from erw.models import ChatMessage, Project, ProjectMember, ReportFile, ReportSlot, User
from erw.pipeline.chat_reports import report_abs_path, run_due_reports

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)  # Wednesday 08:00 Asia/Ho_Chi_Minh


@pytest.fixture
def reports_dir(tmp_path, settings):
    root = tmp_path / "reports"
    root.mkdir()
    settings.reports_dir = str(root)
    return root


@pytest.fixture
def chat_world(session):
    admin = User(email="admin@example.com", name="Admin", password_hash="x", is_admin=True, created_at=NOW)
    pm = User(email="pm@example.com", name="PM", password_hash="x", is_admin=False, created_at=NOW)
    viewer = User(email="viewer@example.com", name="Viewer", password_hash="x", is_admin=False, created_at=NOW)
    other = User(email="other@example.com", name="Other", password_hash="x", is_admin=False, created_at=NOW)
    session.add_all([admin, pm, viewer, other])
    session.flush()
    session.add_all([Project(key="DEMO", name="Demo"), Project(key="OTHER", name="Other")])
    session.flush()
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=viewer.id, role="viewer"),
            ProjectMember(project_key="OTHER", user_id=other.id, role="pm"),
        ]
    )
    session.commit()
    return {"admin": admin, "pm": pm, "viewer": viewer, "other": other}


def login(client, user: User, settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


def test_run_due_reports_writes_disk_and_metadata(session, settings, reports_dir):
    pm = User(email="pm@example.com", name="PM", password_hash="x", is_admin=False, created_at=NOW)
    session.add(pm)
    session.flush()
    session.add(Project(key="DEMO", name="Demo"))
    session.flush()
    session.add(ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"))
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()

    due = run_due_reports(session, NOW, settings)
    session.commit()
    assert len(due) == 1
    msg = session.query(ChatMessage).one()
    assert msg.kind == "report"
    row = session.query(ReportFile).one()
    assert row.message_id == msg.id
    assert row.hidden_at is None
    assert row.slot_hhmm == "08:00"
    assert row.report_date == "2026-11-04"
    path = report_abs_path(settings, row.rel_path)
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == msg.body
    assert path == reports_dir / str(pm.id) / "DEMO" / "2026-11-04-0800.md"


def test_list_download_and_soft_hide_keep_timeline(client, settings, session, chat_world, reports_dir):
    pm = chat_world["pm"]
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()
    run_due_reports(session, NOW, settings)
    session.commit()
    row = session.query(ReportFile).one()
    msg_id = row.message_id

    login(client, pm, settings)
    listed = client.get("/api/chat/reports", params={"project": "DEMO"})
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == row.id
    assert items[0]["filename"] == "2026-11-04-0800.md"
    assert "Báo cáo" in items[0]["preview"]

    dl = client.get(f"/api/chat/reports/{row.id}/download")
    assert dl.status_code == 200
    assert "Báo cáo" in dl.text
    assert "text/markdown" in dl.headers.get("content-type", "")

    hide = client.post(f"/api/chat/reports/{row.id}/hide")
    assert hide.status_code == 200
    body = hide.json()
    assert body["ok"] is True
    assert body["message_still_present"] is True

    assert client.get("/api/chat/reports", params={"project": "DEMO"}).json() == []
    session.expire_all()
    assert session.get(ChatMessage, msg_id) is not None
    assert session.get(ChatMessage, msg_id).kind == "report"
    assert session.get(ReportFile, row.id).hidden_at is not None
    assert report_abs_path(settings, row.rel_path).is_file()

    # DELETE alias also soft-hides (idempotent)
    again = client.delete(f"/api/chat/reports/{row.id}")
    assert again.status_code == 200
    assert again.json()["ok"] is True


def test_viewer_cannot_list_reports(client, settings, session, chat_world, reports_dir):
    pm = chat_world["pm"]
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()
    run_due_reports(session, NOW, settings)
    session.commit()
    login(client, chat_world["viewer"], settings)
    assert client.get("/api/chat/reports", params={"project": "DEMO"}).status_code == 403


def test_other_user_cannot_hide_foreign_report(client, settings, session, chat_world, reports_dir):
    pm = chat_world["pm"]
    session.add(ReportSlot(user_id=pm.id, time_hhmm="08:00"))
    session.flush()
    run_due_reports(session, NOW, settings)
    session.commit()
    report_id = session.query(ReportFile).one().id
    login(client, chat_world["other"], settings)
    assert client.post(f"/api/chat/reports/{report_id}/hide").status_code == 404


def test_bubble_prefs_default_on_and_persist(client, settings, chat_world):
    login(client, chat_world["pm"], settings)
    assert client.get("/api/chat/prefs").json() == {"bubble_enabled": True}
    put = client.put("/api/chat/prefs", json={"bubble_enabled": False})
    assert put.status_code == 200
    assert put.json() == {"bubble_enabled": False}
    assert client.get("/api/chat/prefs").json() == {"bubble_enabled": False}
    assert client.put("/api/chat/prefs", json={}).status_code == 422


def test_system_status_exposes_safe_fields(client, settings, chat_world, monkeypatch):
    monkeypatch.setattr("erw.api.chat._ollama_reachable", lambda _s: False)
    login(client, chat_world["pm"], settings)
    resp = client.get("/api/chat/system-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tz"] == settings.tz
    assert data["llm_model"] == settings.llm_model
    assert data["embed_model"] == settings.embed_model
    assert data["ollama_reachable"] is False
    assert data["slack_webhook_configured"] is False
    assert data["digest_time"] == settings.digest_time
    assert data["slack_max_per_hour"] is None  # PM does not get rate limit
    assert data["bubble_enabled"] is True

    login(client, chat_world["admin"], settings)
    admin = client.get("/api/chat/system-status").json()
    assert admin["slack_max_per_hour"] == settings.slack_max_per_hour
