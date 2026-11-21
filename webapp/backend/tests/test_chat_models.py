from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from erw.models import ChatMessage, ReportSlot, User


def _user(session) -> User:
    user = User(
        email="pm@example.com",
        name="PM",
        password_hash="x",
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    return user


def test_chat_tables_exist(session):
    bind = session.get_bind()
    names = set(inspect(bind).get_table_names())
    assert {"chat_messages", "report_slots", "chat_memories", "chat_rag_chunks", "chat_agent_runs"} <= names
    indexes = {ix["name"] for ix in inspect(bind).get_indexes("chat_messages")}
    assert "ix_chat_messages_user_project_created" in indexes
    mem_indexes = {ix["name"] for ix in inspect(bind).get_indexes("chat_memories")}
    assert "ix_chat_memories_user_project_kind" in mem_indexes


def test_report_slot_pair_is_unique(session):
    user = _user(session)
    session.add(ReportSlot(user_id=user.id, time_hhmm="08:00"))
    session.flush()
    session.add(ReportSlot(user_id=user.id, time_hhmm="08:00"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_null_dedup_keys_can_repeat(session):
    user = _user(session)
    now = datetime.now(UTC)
    session.add_all(
        [
            ChatMessage(
                user_id=user.id,
                project_key="DEMO",
                kind="user",
                body="một",
                recommendation_status="skipped",
                created_at=now,
                dedup_key=None,
            ),
            ChatMessage(
                user_id=user.id,
                project_key="DEMO",
                kind="assistant",
                body="hai",
                recommendation_status="skipped",
                created_at=now,
                dedup_key=None,
            ),
        ]
    )
    session.flush()
    assert session.query(ChatMessage).count() == 2


def test_duplicate_dedup_key_rejected(session):
    user = _user(session)
    now = datetime.now(UTC)
    session.add(
        ChatMessage(
            user_id=user.id,
            project_key="DEMO",
            kind="urgent",
            body="x",
            recommendation_status="skipped",
            created_at=now,
            dedup_key="urgent:1:risk_up:DEMO-1:HIGH",
        )
    )
    session.flush()
    session.add(
        ChatMessage(
            user_id=user.id,
            project_key="DEMO",
            kind="urgent",
            body="y",
            recommendation_status="skipped",
            created_at=now,
            dedup_key="urgent:1:risk_up:DEMO-1:HIGH",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
