from datetime import UTC, datetime

from erw.integrations.llm import ActionItem
from erw.models import ChatMessage, User
from erw.pipeline.chat_recommend import (
    FAILED_RECOMMENDATION,
    enqueue_message_recommendation,
    recommendation_from_stored,
    validate_recommendation,
    write_recommendation,
)

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def test_validator_rejects_unknown_action_and_outside_issue():
    bad_type = ActionItem(action_type="delete_issue", target="DEMO-1", reason="x")
    outside = ActionItem(action_type="add_comment", target="DEMO-99", reason="x")
    assert validate_recommendation("Nên xử lý DEMO-1.", [bad_type], {"DEMO-1"}) is False
    assert validate_recommendation("Nên xử lý DEMO-99.", [outside], {"DEMO-1"}) is False
    assert validate_recommendation("Nên xử lý DEMO-99.", [], {"DEMO-1"}) is False


def test_validator_rejects_fourth_action():
    actions = [ActionItem(action_type="add_comment", target="DEMO-1", reason=str(i)) for i in range(4)]
    assert validate_recommendation("DEMO-1", actions, {"DEMO-1"}) is False


def test_validator_accepts_one_allowed_action():
    action = ActionItem(action_type="escalate_blocker", target="DEMO-1", reason="đang chặn")
    assert validate_recommendation("Nên xử lý DEMO-1.", [action], {"DEMO-1"}) is True


def test_write_recommendation_skips_when_ollama_unset(monkeypatch, settings):
    def boom(*args, **kwargs):
        raise AssertionError("Ollama should not be called")

    monkeypatch.setattr("erw.pipeline.chat_recommend.call_ollama_chat", boom)
    text, status = write_recommendation("prompt", {"DEMO-1"}, settings.model_copy(update={"ollama_url": ""}))
    assert text == FAILED_RECOMMENDATION
    assert status == "failed"


def test_write_recommendation_rejects_outside_issue(monkeypatch, settings):
    monkeypatch.setattr(
        "erw.pipeline.chat_recommend.call_ollama_chat",
        lambda *args, **kwargs: {
            "text": "Nên xử lý DEMO-99.",
            "actions": [{"action_type": "add_comment", "target": "DEMO-99", "value": None, "reason": "x"}],
        },
    )
    text, status = write_recommendation("prompt", {"DEMO-1"}, settings)
    assert text == FAILED_RECOMMENDATION
    assert status == "failed"


def test_write_recommendation_accepts_grounded_json(monkeypatch, settings):
    monkeypatch.setattr(
        "erw.pipeline.chat_recommend.call_ollama_chat",
        lambda *args, **kwargs: {
            "text": "Nên xử lý DEMO-1.",
            "actions": [
                {"action_type": "escalate_blocker", "target": "DEMO-1", "value": None, "reason": "đang chặn"}
            ],
        },
    )
    text, status = write_recommendation("prompt", {"DEMO-1"}, settings)
    assert status == "ready"
    assert text == "Nên xử lý DEMO-1."


def test_recommendation_from_stored_uses_summary():
    output = {
        "summary": "Nên xử lý DEMO-1 trước.",
        "actions": [{"action_type": "escalate_blocker", "target": "DEMO-1", "value": None, "reason": "đang chặn"}],
    }
    text, status = recommendation_from_stored(output, {"DEMO-1"})
    assert status == "ready"
    assert "Nên xử lý DEMO-1 trước." in text


def test_enqueue_updates_the_same_message(session, settings, engine, monkeypatch):
    user = User(email="pm@example.com", name="PM", password_hash="x", is_admin=False, created_at=NOW)
    session.add(user)
    session.flush()
    msg = ChatMessage(
        user_id=user.id,
        project_key="DEMO",
        kind="assistant",
        body="Đang có 1 issue nguy cơ trễ, 0 tăng bậc trong 24 giờ.",
        recommendation_status="pending",
        created_at=NOW,
        dedup_key=None,
    )
    session.add(msg)
    session.commit()
    captured = []
    monkeypatch.setattr("erw.pipeline.chat_recommend.submit_to_llm_executor", captured.append)
    monkeypatch.setattr(
        "erw.pipeline.chat_recommend.write_recommendation",
        lambda *args, **kwargs: ("Nên xử lý DEMO-1.", "ready"),
    )
    enqueue_message_recommendation(msg.id, "prompt", {"DEMO-1"}, settings, engine)
    assert len(captured) == 1
    session.expire_all()
    assert session.get(ChatMessage, msg.id).recommendation_status == "pending"
    captured[0]()
    captured[0]()
    session.expire_all()
    row = session.get(ChatMessage, msg.id)
    assert row.recommendation_status == "ready"
    assert row.body.startswith("Đang có 1 issue nguy cơ trễ")
    assert row.body.count("Nên xử lý DEMO-1.") == 1
    assert session.query(ChatMessage).count() == 1
