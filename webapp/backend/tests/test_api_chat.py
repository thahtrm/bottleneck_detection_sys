from datetime import UTC, datetime, timedelta

import pytest

from erw.auth import create_session_token
from erw.models import ChatMessage, Issue, Project, ProjectMember, ReportSlot, RiskState, Suggestion, User

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


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


def test_messages_require_login(client):
    assert client.get("/api/chat/messages", params={"project": "DEMO"}).status_code == 401


def test_viewer_and_other_pm_are_forbidden(client, settings, chat_world):
    login(client, chat_world["viewer"], settings)
    assert client.get("/api/chat/messages", params={"project": "DEMO"}).status_code == 403
    login(client, chat_world["other"], settings)
    assert client.post("/api/chat/messages", json={"project": "DEMO", "text": "ưu tiên"}).status_code == 403


def test_unmatched_question_still_enqueues_agent(client, settings, chat_world, monkeypatch):
    captured = []
    monkeypatch.setattr("erw.pipeline.chat_agent.submit_to_llm_executor", captured.append)
    monkeypatch.setattr(settings, "ollama_url", "")
    login(client, chat_world["pm"], settings)
    resp = client.post("/api/chat/messages", json={"project": "DEMO", "text": "Thời tiết hôm nay thế nào?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["assistant"]["recommendation_status"] == "pending"
    assert body["assistant"]["body"] == ""
    assert len(captured) == 1
    captured[0]()
    listed = client.get("/api/chat/messages", params={"project": "DEMO"}).json()
    assert listed[-1]["body"] == "Chưa có trong hệ thống."
    assert listed[-1]["recommendation_status"] == "skipped"


def test_admin_can_read_and_post_without_membership(client, settings, chat_world, monkeypatch):
    monkeypatch.setattr("erw.api.chat.enqueue_agent_turn", lambda **kwargs: None)
    login(client, chat_world["admin"], settings)
    posted = client.post("/api/chat/messages", json={"project": "DEMO", "text": "Thời tiết hôm nay thế nào?"})
    assert posted.status_code == 200
    listed = client.get("/api/chat/messages", params={"project": "DEMO"})
    assert listed.status_code == 200
    assert len(listed.json()) == 2


def test_risky_question_stays_pending_until_the_same_row_updates(client, settings, session, chat_world, monkeypatch):
    captured = []
    monkeypatch.setattr("erw.pipeline.chat_agent.submit_to_llm_executor", captured.append)
    monkeypatch.setattr(
        "erw.pipeline.chat_agent.write_recommendation",
        lambda *args, **kwargs: ("Nên xử lý DEMO-1.", "ready"),
    )
    monkeypatch.setattr(settings, "ollama_url", "")
    session.add(
        Issue(
            key="DEMO-1",
            project_key="DEMO",
            summary="A",
            status_category="indeterminate",
            assignee_name="Lan",
            updated_at=NOW,
        )
    )
    session.add(RiskState(issue_key="DEMO-1", level="HIGH", crit_score=0.9, updated_at=NOW))
    session.commit()
    login(client, chat_world["pm"], settings)
    resp = client.post(
        "/api/chat/messages",
        json={"project": "DEMO", "text": "Sáng nay mình nên xử lý gì trước?"},
    )
    assert resp.status_code == 200
    assistant = resp.json()["assistant"]
    assert assistant["recommendation_status"] == "pending"
    assert assistant["body"] == ""
    assert len(captured) == 1
    captured[0]()
    listed = client.get("/api/chat/messages", params={"project": "DEMO"}).json()
    assert len(listed) == 2
    updated = listed[-1]
    assert updated["id"] == assistant["id"]
    assert updated["recommendation_status"] == "ready"
    assert updated["body"].startswith("Đang có")
    assert "Nên xử lý DEMO-1." in updated["body"]
    session.expire_all()
    assert session.query(ChatMessage).count() == 2


def test_ready_suggestion_is_reused_without_ollama(client, settings, session, chat_world, monkeypatch):
    captured = []
    monkeypatch.setattr("erw.pipeline.chat_agent.submit_to_llm_executor", captured.append)
    monkeypatch.setattr(settings, "ollama_url", "")
    session.add(
        Issue(
            key="DEMO-41",
            project_key="DEMO",
            summary="Làm API",
            status_category="indeterminate",
            assignee_name="Lan",
            updated_at=NOW,
        )
    )
    session.add(RiskState(issue_key="DEMO-41", level="HIGH", updated_at=NOW))
    session.add(
        Suggestion(
            issue_key="DEMO-41",
            issue_updated_at=NOW,
            model="gemma",
            output={
                "summary": "Nên xử lý DEMO-41 trước.",
                "actions": [{"action_type": "escalate_blocker", "target": "DEMO-41", "reason": "đang chặn"}],
            },
            valid=True,
            created_at=NOW,
        )
    )
    session.commit()
    login(client, chat_world["pm"], settings)
    resp = client.post("/api/chat/messages", json={"project": "DEMO", "text": "DEMO-41 sao rồi"})
    assert resp.status_code == 200
    assistant = resp.json()["assistant"]
    assert assistant["recommendation_status"] == "pending"
    captured[0]()
    listed = client.get("/api/chat/messages", params={"project": "DEMO"}).json()
    updated = listed[-1]
    assert updated["id"] == assistant["id"]
    assert updated["recommendation_status"] == "ready"
    assert "Nên xử lý DEMO-41 trước." in updated["body"]
    assert "DEMO-41:" in updated["body"]


def test_blank_text_is_rejected(client, settings, session, chat_world):
    login(client, chat_world["pm"], settings)
    resp = client.post("/api/chat/messages", json={"project": "DEMO", "text": "   "})
    assert resp.status_code == 422
    session.expire_all()
    assert session.query(ChatMessage).count() == 0


def test_get_returns_latest_fifty_oldest_first(client, settings, session, chat_world):
    pm = chat_world["pm"]
    other = chat_world["other"]
    for i in range(60):
        session.add(
            ChatMessage(
                user_id=pm.id,
                project_key="DEMO",
                kind="user",
                body=str(i),
                recommendation_status="skipped",
                created_at=NOW + timedelta(seconds=i),
            )
        )
    session.add(
        ChatMessage(
            user_id=other.id,
            project_key="DEMO",
            kind="user",
            body="secret",
            recommendation_status="skipped",
            created_at=NOW,
        )
    )
    session.add(
        ChatMessage(
            user_id=pm.id,
            project_key="OTHER",
            kind="user",
            body="elsewhere",
            recommendation_status="skipped",
            created_at=NOW,
        )
    )
    session.commit()
    login(client, pm, settings)
    listed = client.get("/api/chat/messages", params={"project": "DEMO"}).json()
    assert [row["body"] for row in listed] == [str(i) for i in range(10, 60)]


def test_schedule_requires_login(client):
    assert client.get("/api/chat/schedule").status_code == 401


def test_put_schedule_rejects_fourth_slot_and_bad_clock(client, settings, chat_world):
    login(client, chat_world["pm"], settings)
    assert client.put("/api/chat/schedule", json=["08:00", "09:00", "10:00", "11:00"]).status_code == 422
    assert client.put("/api/chat/schedule", json=["8:00"]).status_code == 422
    assert client.put("/api/chat/schedule", json=["08:00", "08:00"]).status_code == 422
    ok = client.put("/api/chat/schedule", json=["16:30", "08:00"])
    assert ok.status_code == 200
    assert ok.json()["times"] == ["08:00", "16:30"]
    assert client.get("/api/chat/schedule").json()["times"] == ["08:00", "16:30"]
    assert client.put("/api/chat/schedule", json=[]).json()["times"] == []


def test_admin_schedule_does_not_change_pm_slots(client, settings, session, chat_world):
    login(client, chat_world["pm"], settings)
    assert client.put("/api/chat/schedule", json=["08:00"]).status_code == 200
    login(client, chat_world["admin"], settings)
    assert client.put("/api/chat/schedule", json=["09:15"]).status_code == 200
    session.expire_all()
    pm_slots = [row.time_hhmm for row in session.query(ReportSlot).filter_by(user_id=chat_world["pm"].id)]
    admin_slots = [row.time_hhmm for row in session.query(ReportSlot).filter_by(user_id=chat_world["admin"].id)]
    assert pm_slots == ["08:00"]
    assert admin_slots == ["09:15"]
