from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from erw import jobs
from erw.auth import require_admin
from erw.db import get_session
from erw.kv import get_kv, set_kv
from erw.ml.batch import _batch_lock
from erw.models import Project, User
from erw.settings import Settings, get_settings

log = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminSettingsResponse(BaseModel):
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
