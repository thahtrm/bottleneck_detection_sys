from __future__ import annotations

import logging
import secrets
import string
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from erw import jobs
from erw.auth import hash_password, require_admin
from erw.db import get_session, utcnow
from erw.demo.seed import seed_demo_data
from erw.integrations.local_jira import LocalJiraService
from erw.kv import get_kv, set_kv
from erw.ml.batch import _batch_lock
from erw.models import (
    Action,
    ChatAgentRun,
    ChatMemory,
    ChatMessage,
    Component,
    Issue,
    IssueVote,
    IssueWatcher,
    Project,
    ProjectMember,
    ReportFile,
    ReportSlot,
    User,
    default_avatar_color,
)
from erw.settings import Settings, get_settings
from erw.sql_like import like_contains

log = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_temp_password(length: int = 16) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


class AdminSettingsResponse(BaseModel):
    jira_mode: str = "local"
    jira_base_url: str
    webhook_url: str
    last_webhook_at: str | None
    last_catch_up_at: str | None
    llm_model: str
    delay_threshold: float
    criticality_top_pct: float
    model_mode: str
    tracked_projects: list[str]


class AdminSettingsUpdate(BaseModel):
    delay_threshold: float | None = None
    criticality_top_pct: float | None = None
    llm_model: str | None = None


def _build_settings_response(session: Session, settings: Settings) -> AdminSettingsResponse:
    last_webhook_at = get_kv(session, "last_webhook_at")
    last_catch_up_at = get_kv(session, "last_catch_up_at")

    kv_delay = get_kv(session, "delay_threshold")
    delay_threshold = float(kv_delay) if kv_delay is not None else float(settings.delay_threshold)

    kv_crit = get_kv(session, "criticality_top_pct")
    criticality_top_pct = float(kv_crit) if kv_crit is not None else float(settings.criticality_top_pct)

    kv_llm = get_kv(session, "llm_model")
    llm_model = kv_llm if kv_llm is not None else settings.llm_model

    has_any_project = session.scalars(select(Project.key).limit(1)).first() is not None
    if has_any_project:
        tracked_projects = sorted(session.scalars(select(Project.key).where(Project.tracked.is_(True))).all())
    else:
        tracked_projects = sorted(settings.jira_projects)

    webhook_url = ""
    if settings.public_base_url and settings.jira_webhook_secret:
        base = settings.public_base_url.rstrip("/")
        webhook_url = f"{base}/webhooks/jira/***"

    return AdminSettingsResponse(
        jira_mode=getattr(settings, "jira_mode", "local"),
        jira_base_url=settings.jira_base_url,
        webhook_url=webhook_url,
        last_webhook_at=last_webhook_at,
        last_catch_up_at=last_catch_up_at,
        llm_model=llm_model,
        delay_threshold=delay_threshold,
        criticality_top_pct=criticality_top_pct,
        model_mode=settings.model_mode,
        tracked_projects=tracked_projects,
    )


@admin_router.get("/settings", response_model=AdminSettingsResponse)
@admin_router.get("/settings/", response_model=AdminSettingsResponse, include_in_schema=False)
def get_settings_endpoint(
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminSettingsResponse:
    return _build_settings_response(session, settings)


@admin_router.post("/settings", response_model=AdminSettingsResponse)
@admin_router.post("/settings/", response_model=AdminSettingsResponse, include_in_schema=False)
def update_settings_endpoint(
    body: AdminSettingsUpdate,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminSettingsResponse:
    if body.delay_threshold is not None:
        set_kv(session, "delay_threshold", str(body.delay_threshold))
    if body.criticality_top_pct is not None:
        set_kv(session, "criticality_top_pct", str(body.criticality_top_pct))
    if body.llm_model is not None:
        set_kv(session, "llm_model", str(body.llm_model))
    session.commit()
    return _build_settings_response(session, settings)


@admin_router.post("/run-batch", status_code=status.HTTP_202_ACCEPTED)
@admin_router.post("/run-batch/", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
def run_batch_endpoint(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if _batch_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"status": "busy", "message": "Batch scoring is already running"},
        )
    background_tasks.add_task(jobs.executor.submit, jobs._morning_body)
    return {"status": "started", "message": "Batch scoring started in background"}


class AdminUserItem(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    is_active: bool
    created_at: str | None
    project_count: int
    account_id: str | None = None
    avatar_url: str | None = None
    avatar_color: str = "#0052CC"
    job_title: str | None = None
    department: str | None = None
    timezone: str = "Asia/Ho_Chi_Minh"


class AdminUserCreate(BaseModel):
    email: str
    name: str
    is_admin: bool = False
    password: str | None = None
    is_active: bool = True
    account_id: str | None = None
    avatar_url: str | None = None
    avatar_color: str | None = None
    job_title: str | None = None
    department: str | None = None
    timezone: str = "Asia/Ho_Chi_Minh"


class AdminUserUpdate(BaseModel):
    email: str | None = None
    name: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    reset_password: bool = False
    password: str | None = None
    account_id: str | None = None
    avatar_url: str | None = None
    avatar_color: str | None = None
    job_title: str | None = None
    department: str | None = None
    timezone: str | None = None


class AdminUserMutationResponse(BaseModel):
    user: AdminUserItem
    generated_password: str | None = None


def _project_counts(session: Session) -> dict[int, int]:
    rows = session.execute(
        select(ProjectMember.user_id, func.count())
        .group_by(ProjectMember.user_id)
    ).all()
    return {int(uid): int(count) for uid, count in rows}


def _serialize_admin_user(user: User, project_count: int) -> AdminUserItem:
    created = user.created_at.isoformat() if user.created_at else None
    return AdminUserItem(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=bool(user.is_admin),
        is_active=getattr(user, "is_active", True) is not False,
        created_at=created,
        project_count=project_count,
        account_id=getattr(user, "account_id", None),
        avatar_url=getattr(user, "avatar_url", None),
        avatar_color=getattr(user, "avatar_color", None) or default_avatar_color(user.name or user.email),
        job_title=getattr(user, "job_title", None),
        department=getattr(user, "department", None),
        timezone=getattr(user, "timezone", None) or "Asia/Ho_Chi_Minh",
    )


def _count_active_admins(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True), User.is_active.is_(True))
        )
        or 0
    )


@admin_router.get("/users", response_model=list[AdminUserItem])
@admin_router.get("/users/", response_model=list[AdminUserItem], include_in_schema=False)
def list_users(
    q: str | None = Query(default=None),
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[AdminUserItem]:
    stmt = select(User).order_by(func.lower(User.email))
    needle = (q or "").strip().lower()
    if needle:
        pattern = like_contains(needle)
        stmt = stmt.where(
            func.lower(User.email).like(pattern, escape="\\")
            | func.lower(User.name).like(pattern, escape="\\")
            | func.lower(func.coalesce(User.account_id, "")).like(pattern, escape="\\")
        )
    users = list(session.scalars(stmt).all())
    counts = _project_counts(session)
    return [_serialize_admin_user(item, counts.get(item.id, 0)) for item in users]


@admin_router.post("/users", response_model=AdminUserMutationResponse, status_code=status.HTTP_201_CREATED)
@admin_router.post("/users/", response_model=AdminUserMutationResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_user(
    body: AdminUserCreate,
    actor: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> AdminUserMutationResponse:
    email = body.email.strip()
    name = body.name.strip()
    if not email or not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email and name are required")
    existing = session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")

    acct = body.account_id.strip() if body.account_id is not None else None
    if acct == "":
        acct = None
    if acct is not None:
        dup_acct = session.execute(select(User).where(User.account_id == acct)).scalar_one_or_none()
        if dup_acct is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this account_id already exists")

    if body.password is not None:
        if not body.password.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password cannot be empty")
        password = body.password
        generated_password: str | None = None
    else:
        password = generate_temp_password()
        generated_password = password

    row = User(
        email=email,
        name=name,
        password_hash=hash_password(password),
        is_admin=bool(body.is_admin),
        is_active=bool(body.is_active),
        account_id=acct,
        avatar_url=body.avatar_url,
        avatar_color=body.avatar_color or default_avatar_color(name or email),
        job_title=body.job_title,
        department=body.department,
        timezone=(body.timezone or "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh",
        created_at=utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return AdminUserMutationResponse(user=_serialize_admin_user(row, 0), generated_password=generated_password)


@admin_router.patch("/users/{user_id}", response_model=AdminUserMutationResponse)
@admin_router.patch("/users/{user_id}/", response_model=AdminUserMutationResponse, include_in_schema=False)
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    actor: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> AdminUserMutationResponse:
    row = session.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.email is not None:
        email = body.email.strip()
        if not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email cannot be empty")
        dup_email = session.execute(
            select(User).where(func.lower(User.email) == email.lower(), User.id != row.id)
        ).scalar_one_or_none()
        if dup_email is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")
        row.email = email

    if body.account_id is not None:
        acct = body.account_id.strip()
        if not acct:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id cannot be empty")
        dup_acct = session.execute(
            select(User).where(User.account_id == acct, User.id != row.id)
        ).scalar_one_or_none()
        if dup_acct is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this account_id already exists")
        row.account_id = acct

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name cannot be empty")
        row.name = name

    if body.avatar_url is not None:
        row.avatar_url = body.avatar_url or None
    if body.avatar_color is not None:
        row.avatar_color = body.avatar_color or default_avatar_color(row.name or row.email)
    if body.job_title is not None:
        row.job_title = body.job_title or None
    if body.department is not None:
        row.department = body.department or None
    if body.timezone is not None:
        tz = body.timezone.strip()
        if not tz:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Timezone cannot be empty")
        row.timezone = tz

    becoming_inactive = body.is_active is False and (getattr(row, "is_active", True) is not False)
    demoting_admin = body.is_admin is False and bool(row.is_admin)
    if (becoming_inactive or demoting_admin) and row.is_admin and _count_active_admins(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable or demote the last active admin",
        )
    if becoming_inactive and row.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account",
        )

    if body.is_admin is not None:
        row.is_admin = bool(body.is_admin)
    if body.is_active is not None:
        row.is_active = bool(body.is_active)

    if body.password is not None and body.reset_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot specify both password and reset_password",
        )

    generated: str | None = None
    if body.password is not None:
        if not body.password.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password cannot be empty")
        row.password_hash = hash_password(body.password)
    elif body.reset_password:
        generated = generate_temp_password()
        row.password_hash = hash_password(generated)

    session.commit()
    session.refresh(row)
    counts = _project_counts(session)
    return AdminUserMutationResponse(
        user=_serialize_admin_user(row, counts.get(row.id, 0)),
        generated_password=generated,
    )


@admin_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@admin_router.delete("/users/{user_id}/", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def delete_user(
    user_id: int,
    request: Request,
    actor: User = Depends(require_admin),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    row = session.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if row.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    if row.is_admin and getattr(row, "is_active", True) is not False and _count_active_admins(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last active admin",
        )

    app_settings = getattr(request.app.state, "settings", None) or settings
    account_ids = {aid for aid in (getattr(row, "account_id", None), f"local-{row.id}") if aid}
    if account_ids:
        owned_issues = list(session.scalars(select(Issue).where(Issue.assignee_id.in_(account_ids))).all())
        for iss in owned_issues:
            if iss.deleted_at is not None:
                iss.assignee_id = None
                iss.assignee_name = None
            else:
                LocalJiraService.update_issue(
                    session,
                    iss.key,
                    {"assignee": None},
                    actor=actor,
                    settings=app_settings,
                )

    session.execute(update(Project).where(Project.lead_user_id == row.id).values(lead_user_id=None))
    session.execute(update(Component).where(Component.lead_user_id == row.id).values(lead_user_id=None))
    session.execute(update(Action).where(Action.confirmed_by == row.id).values(confirmed_by=None))

    session.execute(delete(ProjectMember).where(ProjectMember.user_id == row.id))
    session.execute(delete(IssueWatcher).where(IssueWatcher.user_id == row.id))
    session.execute(delete(IssueVote).where(IssueVote.user_id == row.id))

    msg_ids = list(session.scalars(select(ChatMessage.id).where(ChatMessage.user_id == row.id)).all())
    if msg_ids:
        session.execute(delete(ChatAgentRun).where(ChatAgentRun.message_id.in_(msg_ids)))
        session.execute(
            delete(ReportFile).where(or_(ReportFile.user_id == row.id, ReportFile.message_id.in_(msg_ids)))
        )
    else:
        session.execute(delete(ReportFile).where(ReportFile.user_id == row.id))
    session.execute(delete(ChatMessage).where(ChatMessage.user_id == row.id))
    session.execute(delete(ReportSlot).where(ReportSlot.user_id == row.id))
    session.execute(delete(ChatMemory).where(ChatMemory.user_id == row.id))

    session.delete(row)
    session.commit()


@admin_router.post("/demo/reset")
def reset_demo_data(
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = getattr(request.app.state, "settings", None) or settings
    if getattr(app_settings, "jira_mode", "local") != "local":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only available in local mode")
    summary = seed_demo_data(session, reset=True)
    session.commit()
    return summary
