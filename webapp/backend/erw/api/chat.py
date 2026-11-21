from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erw.auth import get_session, get_user_project_role, require_authenticated_user
from erw.db import utcnow
from erw.kv import get_kv, set_kv
from erw.models import ChatMessage, ReportFile, ReportSlot, User
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
from erw.pipeline.chat_reports import report_abs_path
from erw.pipeline.health_report import pdf_rel_from_md
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


class ChatPrefsBody(BaseModel):
    bubble_enabled: bool | None = None


def _bubble_pref_key(user_id: int) -> str:
    return f"chat.bubble_enabled:{user_id}"


def get_bubble_enabled(session: Session, user_id: int) -> bool:
    raw = get_kv(session, _bubble_pref_key(user_id))
    if raw is None:
        return True
    return raw not in {"0", "false", "False", "no", "off"}


def set_bubble_enabled(session: Session, user_id: int, enabled: bool) -> None:
    set_kv(session, _bubble_pref_key(user_id), "1" if enabled else "0")


def _serialize_report(row: ReportFile) -> dict:
    return {
        "id": row.id,
        "project_key": row.project_key,
        "message_id": row.message_id,
        "slot_hhmm": row.slot_hhmm,
        "report_date": row.report_date,
        "preview": row.preview,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "filename": Path(row.rel_path).name,
        "owner_user_id": row.user_id,
    }


def _owned_report(session: Session, report_id: int, user: User) -> ReportFile | None:
    row = session.get(ReportFile, report_id)
    if row is None or row.user_id != user.id:
        return None
    return row


def _project_report(session: Session, report_id: int, user: User) -> ReportFile | None:
    """Any project member (or admin) may read; hide stays owner-only via _owned_report."""
    row = session.get(ReportFile, report_id)
    if row is None:
        return None
    role = get_user_project_role(session, user, row.project_key)
    if user.is_admin or role in {"pm", "viewer", "admin"}:
        return row
    return None


def _require_project_member(session: Session, user: User, project: str) -> None:
    role = get_user_project_role(session, user, project.strip())
    if user.is_admin or role in {"pm", "viewer", "admin"}:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project membership required")


def _ollama_reachable(settings: Settings) -> bool:
    if not settings.ollama_url:
        return False
    try:
        with httpx.Client(timeout=1.5) as client:
            resp = client.get(f"{settings.ollama_url.rstrip('/')}/api/tags")
            return resp.status_code < 500
    except Exception:
        return False


def _rag_index_present(settings: Settings) -> bool:
    path = Path(settings.rag_index_path)
    if path.is_file():
        return True
    backend = Path(__file__).resolve().parents[1].parent / "var" / "rag" / "faiss.index"
    return backend.is_file()


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


@chat_router.get("/prefs")
def get_prefs(
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    return {"bubble_enabled": get_bubble_enabled(session, user.id)}


@chat_router.put("/prefs")
def put_prefs(
    body: ChatPrefsBody,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    if body.bubble_enabled is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Nothing to update")
    set_bubble_enabled(session, user.id, body.bubble_enabled)
    session.commit()
    return {"bubble_enabled": get_bubble_enabled(session, user.id)}


@chat_router.get("/system-status")
def get_system_status(
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Read-only Settings § LLM / Slack status for PM+admin (no secrets)."""
    kv_llm = get_kv(session, "llm_model")
    return {
        "tz": settings.tz,
        "llm_model": kv_llm if kv_llm is not None else settings.llm_model,
        "embed_model": settings.embed_model,
        "ollama_url_configured": bool(settings.ollama_url),
        "ollama_reachable": _ollama_reachable(settings),
        "rag_index_present": _rag_index_present(settings),
        "slack_webhook_configured": bool(settings.slack_webhook_url),
        "digest_time": settings.digest_time,
        "slack_max_per_hour": settings.slack_max_per_hour if user.is_admin else None,
        "bubble_enabled": get_bubble_enabled(session, user.id),
    }


@chat_router.get("/reports")
def list_reports(
    project: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    # §8.4 A: any project member (viewer/pm) or admin may list project health reports.
    _require_project_member(session, user, project)
    rows = session.scalars(
        select(ReportFile)
        .where(
            ReportFile.project_key == project.strip(),
            ReportFile.hidden_at.is_(None),
        )
        .order_by(ReportFile.report_date.desc(), ReportFile.slot_hhmm.desc(), ReportFile.id.desc())
    ).all()
    return [_serialize_report(row) for row in rows]


@chat_router.get("/reports/{report_id}/download")
def download_report(
    report_id: int,
    format: str = "md",
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    row = _project_report(session, report_id, user)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    fmt = (format or "md").strip().lower()
    if fmt not in {"md", "pdf"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be md or pdf")
    rel = row.rel_path if fmt == "md" else pdf_rel_from_md(row.rel_path)
    try:
        path = report_abs_path(settings, rel)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file missing on disk")
    media = "application/pdf" if fmt == "pdf" else "text/markdown; charset=utf-8"
    return FileResponse(
        path,
        media_type=media,
        filename=Path(rel).name,
    )


def _hide_report_row(session: Session, report_id: int, user: User) -> dict:
    row = _owned_report(session, report_id, user)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    require_chat_access(session, user, row.project_key)
    if row.hidden_at is None:
        row.hidden_at = utcnow()
        session.commit()
    message = session.get(ChatMessage, row.message_id)
    return {
        "ok": True,
        "id": row.id,
        "hidden_at": row.hidden_at.isoformat() if row.hidden_at else None,
        "message_still_present": message is not None and message.kind == "report",
    }


@chat_router.post("/reports/{report_id}/hide")
def hide_report(
    report_id: int,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    return _hide_report_row(session, report_id, user)


@chat_router.delete("/reports/{report_id}")
def soft_hide_report(
    report_id: int,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict:
    """Soft-hide from file manager only; does not delete the chat timeline message."""
    return _hide_report_row(session, report_id, user)

