from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erw.models import ChatMessage, ProjectMember

URGENT_KINDS = frozenset({"risk_new", "risk_up", "blocked", "critical"})


def urgent_dedup_key(user_id: int, alert_dedup: str) -> str:
    return f"urgent:{user_id}:{alert_dedup}"


def insert_urgent_messages(session: Session, spec, text: str, now: datetime) -> int:
    """Insert one skipped urgent chat row per PM. Specs outside the four urgent kinds insert nothing."""
    if spec.kind not in URGENT_KINDS:
        return 0
    members = session.scalars(
        select(ProjectMember).where(ProjectMember.project_key == spec.project, ProjectMember.role == "pm")
    ).all()
    inserted = 0
    for member in members:
        dedup = urgent_dedup_key(member.user_id, spec.dedup_key)
        existing = session.scalar(select(ChatMessage.id).where(ChatMessage.dedup_key == dedup))
        if existing is not None:
            continue
        message = ChatMessage(
            user_id=member.user_id,
            project_key=spec.project,
            kind="urgent",
            body=text,
            recommendation_status="skipped",
            created_at=now,
            dedup_key=dedup,
        )
        try:
            with session.begin_nested():
                session.add(message)
                session.flush()
        except IntegrityError:
            continue
        inserted += 1
    return inserted
