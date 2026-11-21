from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.db import utcnow
from erw.models import ChatMemory, ChatMessage

MemoryKind = Literal["preference", "note", "episode"]
EDITABLE_KINDS = frozenset({"preference", "note"})


def serialize_memory(row: ChatMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_key": row.project_key,
        "kind": row.kind,
        "text": row.text,
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_memories(
    session: Session,
    user_id: int,
    project_key: str,
    *,
    kinds: set[str] | None = None,
    limit: int = 50,
) -> list[ChatMemory]:
    stmt = (
        select(ChatMemory)
        .where(ChatMemory.user_id == user_id, ChatMemory.project_key == project_key)
        .order_by(ChatMemory.updated_at.desc(), ChatMemory.id.desc())
        .limit(limit)
    )
    if kinds is not None:
        stmt = stmt.where(ChatMemory.kind.in_(kinds))
    return list(session.scalars(stmt).all())


def load_user_project_memory(session: Session, user_id: int, project_key: str, *, limit: int = 20) -> list[ChatMemory]:
    """Prefer durable prefs/notes; keep a short episode tail so episodes cannot drown them."""
    pref_limit = max(1, min(10, limit))
    episode_limit = max(0, min(5, limit - pref_limit))
    prefs = list_memories(session, user_id, project_key, kinds={"preference", "note"}, limit=pref_limit)
    if episode_limit <= 0:
        return prefs
    episodes = list_memories(session, user_id, project_key, kinds={"episode"}, limit=episode_limit)
    return prefs + episodes


def load_session_messages(
    session: Session,
    user_id: int,
    project_key: str,
    *,
    limit: int = 16,
) -> list[ChatMessage]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.project_key == project_key)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def create_memory(
    session: Session,
    user_id: int,
    project_key: str,
    kind: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> ChatMemory:
    if kind not in EDITABLE_KINDS and kind != "episode":
        raise ValueError(f"unsupported memory kind: {kind}")
    moment = now or utcnow()
    row = ChatMemory(
        user_id=user_id,
        project_key=project_key,
        kind=kind,
        text=text.strip(),
        metadata_json=metadata or {},
        created_at=moment,
        updated_at=moment,
    )
    session.add(row)
    session.flush()
    return row


def update_memory(
    session: Session,
    row: ChatMemory,
    *,
    text: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ChatMemory:
    if text is not None:
        row.text = text.strip()
    if metadata is not None:
        row.metadata_json = metadata
    row.updated_at = now or utcnow()
    session.flush()
    return row


def delete_memory(session: Session, row: ChatMemory) -> None:
    session.delete(row)
    session.flush()


def get_owned_memory(session: Session, memory_id: int, user_id: int, project_key: str) -> ChatMemory | None:
    row = session.get(ChatMemory, memory_id)
    if row is None or row.user_id != user_id or row.project_key != project_key:
        return None
    return row


def write_episode(
    session: Session,
    user_id: int,
    project_key: str,
    text: str,
    *,
    related_keys: list[str] | None = None,
    now: datetime | None = None,
) -> ChatMemory:
    return create_memory(
        session,
        user_id,
        project_key,
        "episode",
        text,
        {"related_keys": related_keys or []},
        now=now,
    )


def format_memories_for_prompt(rows: list[ChatMemory]) -> str:
    if not rows:
        return ""
    lines = []
    for row in rows:
        lines.append(f"- [{row.kind}] {row.text.strip()}")
    return "Ghi nhớ user–project:\n" + "\n".join(lines)
