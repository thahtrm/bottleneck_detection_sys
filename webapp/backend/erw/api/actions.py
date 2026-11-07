from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from erw.auth import get_session, require_authenticated_user, require_pm
from erw.db import utcnow
from erw.domain.actions import execute_action
from erw.integrations.jira import JiraClient, JiraError
from erw.models import Action, Issue, User
from erw.settings import Settings, get_settings

actions_router = APIRouter(prefix="/api/actions", tags=["actions"])
router = actions_router

_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def get_jira_client(settings: Settings = Depends(get_settings)) -> JiraClient:
    from erw import jobs

    client = getattr(jobs, "_client", None)
    if client is not None:
        return client
    return JiraClient(settings)


class ProposeActionRequest(BaseModel):
    issue_key: str
    suggestion_id: int | None = None
    items: list[dict[str, Any]] = []


class ConfirmActionRequest(BaseModel):
    expected_updated: str


def _parse_timestamp(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = _TZ_NO_COLON.sub(r"\1:\2", s)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@actions_router.post("/propose", status_code=status.HTTP_201_CREATED)
def propose_action(
    body: ProposeActionRequest,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
):
    issue = session.get(Issue, body.issue_key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_pm(issue.project_key, user=user, session=session)

    action = Action(
        issue_key=body.issue_key,
        suggestion_id=body.suggestion_id,
        items=body.items,
        status="pending",
        created_at=utcnow(),
    )
    session.add(action)
    session.commit()
    session.refresh(action)

    return {
        "action_id": action.id,
        "issue_key": action.issue_key,
        "items": action.items,
        "status": action.status,
    }


@actions_router.post("/{id}/confirm")
def confirm_action(
    id: int,
    body: ConfirmActionRequest,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    jira_client: JiraClient = Depends(get_jira_client),
):
    action = session.get(Action, id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")

    issue = session.get(Issue, action.issue_key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_pm(issue.project_key, user=user, session=session)

    try:
        exp_dt = _parse_timestamp(body.expected_updated)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid expected_updated timestamp format",
        ) from None

    try:
        result = execute_action(
            session=session,
            jira_client=jira_client,
            action_id=action.id,
            expected_updated=exp_dt,
            confirmed_by_user=user,
            settings=settings,
        )
    except JiraError as e:
        if e.status == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Công việc {action.issue_key} không có trên Jira, "
                    "hoặc tài khoản kết nối không có quyền xem."
                ),
            ) from None
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không ghi được lên Jira: {e}",
        ) from None
    if result["status"] == "conflict":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    if result["status"] != "applied":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result)
    return result
