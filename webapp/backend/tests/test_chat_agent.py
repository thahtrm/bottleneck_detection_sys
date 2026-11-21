from datetime import UTC, datetime

from erw.models import ChatMemory, ChatMessage, Issue, Project, ProjectMember, RiskState, User
from erw.pipeline.chat_agent import OUT_OF_SCOPE, run_agent_turn
from erw.settings import Settings

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def _setup(session):
    user = User(email="pm@example.com", name="PM", password_hash="x", is_admin=False, created_at=NOW)
    session.add(user)
    session.flush()
    session.add(Project(key="DEMO", name="Demo"))
    session.flush()
    session.add(ProjectMember(project_key="DEMO", user_id=user.id, role="pm"))
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
    session.add(RiskState(issue_key="DEMO-1", level="HIGH", crit_score=0.9, blocked=True, updated_at=NOW))
    session.commit()
    return user


def _pending(session, user, text: str) -> ChatMessage:
    user_row = ChatMessage(
        user_id=user.id,
        project_key="DEMO",
        kind="user",
        body=text,
        recommendation_status="skipped",
        created_at=NOW,
    )
    assistant = ChatMessage(
        user_id=user.id,
        project_key="DEMO",
        kind="assistant",
        body="",
        recommendation_status="pending",
        created_at=NOW,
    )
    session.add_all([user_row, assistant])
    session.commit()
    return assistant


def test_agent_uses_tools_without_http_answer_facts(session, settings, monkeypatch):
    user = _setup(session)
    monkeypatch.setattr(settings, "ollama_url", "")
    monkeypatch.setattr(
        "erw.pipeline.chat_agent.write_recommendation",
        lambda *a, **k: ("Nên xử lý DEMO-1.", "ready"),
    )
    assistant = _pending(session, user, "issue bị block")
    run_agent_turn(
        session,
        message_id=assistant.id,
        user_id=user.id,
        project_key="DEMO",
        text="issue bị block",
        settings=settings,
        now=NOW,
    )
    session.commit()
    session.refresh(assistant)
    assert assistant.body.startswith("Đang có")
    assert "DEMO-1" in assistant.body
    assert "Nên xử lý DEMO-1." in assistant.body
    assert assistant.recommendation_status == "ready"


def test_agent_out_of_scope_without_board_tool(session, settings, monkeypatch):
    user = _setup(session)
    monkeypatch.setattr(settings, "ollama_url", "")
    assistant = _pending(session, user, "thời tiết hôm nay")
    run_agent_turn(
        session,
        message_id=assistant.id,
        user_id=user.id,
        project_key="DEMO",
        text="thời tiết hôm nay",
        settings=settings,
        now=NOW,
    )
    session.commit()
    session.refresh(assistant)
    assert assistant.body == OUT_OF_SCOPE
    assert assistant.recommendation_status == "skipped"


def test_agent_keeps_facts_when_recommend_fails(session, settings, monkeypatch):
    user = _setup(session)
    monkeypatch.setattr(settings, "ollama_url", "")
    monkeypatch.setattr(
        "erw.pipeline.chat_agent.write_recommendation",
        lambda *a, **k: ("Chưa tạo được đề xuất bám dữ liệu.", "failed"),
    )
    assistant = _pending(session, user, "nguy cơ trễ")
    run_agent_turn(
        session,
        message_id=assistant.id,
        user_id=user.id,
        project_key="DEMO",
        text="nguy cơ trễ",
        settings=settings,
        now=NOW,
    )
    session.commit()
    session.refresh(assistant)
    assert assistant.body.startswith("Đang có")
    assert "Chưa tạo được đề xuất" in assistant.body
    assert assistant.recommendation_status == "failed"


def test_agent_does_not_write_episode_on_out_of_scope(session, settings, monkeypatch):
    user = _setup(session)
    monkeypatch.setattr(settings, "ollama_url", "")
    assistant = _pending(session, user, "thời tiết hôm nay")
    run_agent_turn(
        session,
        message_id=assistant.id,
        user_id=user.id,
        project_key="DEMO",
        text="thời tiết hôm nay",
        settings=settings,
        now=NOW,
    )
    session.commit()
    episodes = session.query(ChatMemory).filter_by(user_id=user.id, kind="episode").all()
    assert episodes == []


def test_agent_writes_episode_after_board_facts(session, settings, monkeypatch):
    user = _setup(session)
    monkeypatch.setattr(settings, "ollama_url", "")
    monkeypatch.setattr(
        "erw.pipeline.chat_agent.write_recommendation",
        lambda *a, **k: ("", "skipped"),
    )
    assistant = _pending(session, user, "issue bị block")
    run_agent_turn(
        session,
        message_id=assistant.id,
        user_id=user.id,
        project_key="DEMO",
        text="issue bị block",
        settings=settings,
        now=NOW,
    )
    session.commit()
    episodes = session.query(ChatMemory).filter_by(user_id=user.id, kind="episode").all()
    assert len(episodes) == 1
    assert "DEMO-1" in episodes[0].text
