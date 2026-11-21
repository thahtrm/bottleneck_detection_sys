from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erw.auth import get_session, get_user_project_role, require_authenticated_user
from erw.db import utcnow
from erw.models import ChatMessage, ReportSlot, User
from erw.pipeline.chat_agent import enqueue_agent_turn
from erw.pipeline.chat_memory import (
    EDITABLE_KINDS,
    create_memory,
    delete_memory,
    get_owned_memory,
    list_memories,
    serialize_memory,
    update_memory,
)
from erw.settings import Settings, get_settings

chat_router = APIRouter(prefix="/api/chat", tags=["chat"])
router = chat_router


class PostChatBody(BaseModel):
    project: str
    text: str


class MemoryCreateBody(BaseModel):
    project: str
    kind: Literal["preference", "note"]
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryPatchBody(BaseModel):
    text: str | None = None
    metadata: dict[str, Any] | None = None


def require_chat_access(session: Session, user: User, project: str) -> None:
    if not project or not project.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Project is required")
    role = get_user_project_role(session, user, project)
    if user.is_admin or role == "pm":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Access denied for project {project}")


def _serialize(message: ChatMessage) -> dict:
    created = message.created_at.isoformat() if message.created_at else None
    return {
        "id": message.id,
        "project_key": message.project_key,
        "kind": message.kind,
        "body": message.body,
        "recommendation_status": message.recommendation_status,
        "created_at": created,
    }


def _store_pair(session: Session, user: User, project: str, text: str) -> tuple[ChatMessage, ChatMessage]:
    now = utcnow()
    user_row = ChatMessage(
        user_id=user.id,
        project_key=project,
        kind="user",
        body=text,
        recommendation_status="skipped",
        created_at=now,
        dedup_key=None,
    )
    assistant_row = ChatMessage(
        user_id=user.id,
        project_key=project,
        kind="assistant",
        body="",
        recommendation_status="pending",
        created_at=now,
        dedup_key=None,
    )
    session.add(user_row)
    session.add(assistant_row)
    session.commit()
    return user_row, assistant_row


@chat_router.get("/messages")
def list_messages(
    project: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    require_chat_access(session, user, project)
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id, ChatMessage.project_key == project)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(50)
    ).all()
    return [_serialize(row) for row in reversed(rows)]


@chat_router.post("/messages")
def post_message(
    body: PostChatBody,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    text = body.text or ""
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Text is required")
    project = body.project.strip()
    require_chat_access(session, user, project)
    app_settings = getattr(request.app.state, "settings", None) or settings
    user_row, assistant_row = _store_pair(session, user, project, text.strip())
    enqueue_agent_turn(
        message_id=assistant_row.id,
        user_id=user.id,
        project_key=project,
        text=text.strip(),
        settings=app_settings,
        engine=request.app.state.engine,
    )
    return {"user": _serialize(user_row), "assistant": _serialize(assistant_row)}


@chat_router.get("/memories")
def get_memories(
    project: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    require_chat_access(session, user, project)
    rows = list_memories(session, user.id, project.strip(), kinds=EDITABLE_KINDS)
    return [serialize_memory(row) for row in rows]


@chat_router.post("/memories")
def post_memory(
    body: MemoryCreateBody,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    project = body.project.strip()
    require_chat_access(session, user, project)
    if not body.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Text is required")
    row = create_memory(session, user.id, project, body.kind, body.text, body.metadata)
    session.commit()
    return serialize_memory(row)


@chat_router.patch("/memories/{memory_id}")
def patch_memory(
    memory_id: int,
    body: MemoryPatchBody,
    project: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    require_chat_access(session, user, project)
    row = get_owned_memory(session, memory_id, user.id, project.strip())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    if row.kind not in EDITABLE_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Episode is not editable")
    if body.text is None and body.metadata is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Nothing to update")
    if body.text is not None and not body.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Text is required")
    update_memory(session, row, text=body.text, metadata=body.metadata)
    session.commit()
    return serialize_memory(row)


@chat_router.delete("/memories/{memory_id}")
def remove_memory(
    memory_id: int,
    project: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    require_chat_access(session, user, project)
    row = get_owned_memory(session, memory_id, user.id, project.strip())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    if row.kind not in EDITABLE_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Episode is not editable")
    delete_memory(session, row)
    session.commit()
    return {"ok": True}


HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleError(ValueError):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def replace_schedule(session: Session, user_id: int, times: list[str]) -> list[str]:
    if len(times) > 3:
        raise ScheduleError("Tối đa 3 mốc giờ.")
    seen: set[str] = set()
    for item in times:
        if HHMM_RE.fullmatch(item) is None:
            raise ScheduleError("Giờ phải là HH:MM.")
        if item in seen:
            raise ScheduleError("Mốc giờ bị trùng.")
        seen.add(item)
    session.execute(delete(ReportSlot).where(ReportSlot.user_id == user_id))
    for item in times:
        session.add(ReportSlot(user_id=user_id, time_hhmm=item))
    session.commit()
    return sorted(times)


@chat_router.get("/schedule")
def get_schedule(
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    rows = session.scalars(select(ReportSlot).where(ReportSlot.user_id == user.id)).all()
    return {"times": sorted(row.time_hhmm for row in rows)}


@chat_router.put("/schedule")
def put_schedule(
    times: Annotated[list[str], Body()],
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    try:
        saved = replace_schedule(session, user.id, times)
    except ScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail) from exc
    return {"times": saved}
