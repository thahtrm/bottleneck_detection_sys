from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.api.actions import get_jira_client
from erw.auth import get_session, require_authenticated_user, require_pm, require_viewer
from erw.integrations.jira import JiraClient, JiraError
from erw.integrations.llm import enqueue_suggestion, get_cached_suggestion
from erw.models import Action, Change, Issue, Link, RiskState, Score, Suggestion, User
from erw.settings import Settings, get_settings

issues_router = APIRouter(prefix="/api/issues", tags=["issues"])
router = issues_router


class DismissRequest(BaseModel):
    reason: str | None = None


def _serialize_issue(issue: Issue) -> dict[str, Any]:
    return {
        "key": issue.key,
        "project_key": issue.project_key,
        "summary": issue.summary,
        "issuetype": issue.issuetype,
        "priority": issue.priority,
        "priority_norm": issue.priority_norm,
        "status": issue.status,
        "status_category": issue.status_category,
        "assignee_id": issue.assignee_id,
        "assignee_name": issue.assignee_name,
        "duedate": issue.duedate.isoformat() if issue.duedate else None,
        "story_points": issue.story_points,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "raw": issue.raw,
    }


def _serialize_risk_state(rs: RiskState | None) -> dict[str, Any] | None:
    if rs is None:
        return None
    return {
        "issue_key": rs.issue_key,
        "level": rs.level,
        "prev_level": rs.prev_level,
        "level_raised_at": rs.level_raised_at.isoformat() if rs.level_raised_at else None,
        "delay_value": rs.delay_value,
        "crit_score": rs.crit_score,
        "is_critical": rs.is_critical,
        "blocked": rs.blocked,
        "deadline_type": rs.deadline_type,
        "deadline_at": rs.deadline_at.isoformat() if rs.deadline_at else None,
        "deadline_label": rs.deadline_label,
        "factors": rs.factors,
        "last_alerted_level": rs.last_alerted_level,
        "dismissed_at_level": rs.dismissed_at_level,
        "updated_at": rs.updated_at.isoformat() if rs.updated_at else None,
    }


def _serialize_suggestion(s: Suggestion | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "issue_key": s.issue_key,
        "issue_updated_at": s.issue_updated_at.isoformat() if s.issue_updated_at else None,
        "model": s.model,
        "output": s.output,
        "valid": s.valid,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _serialize_action(a: Action) -> dict[str, Any]:
    return {
        "id": a.id,
        "issue_key": a.issue_key,
        "suggestion_id": a.suggestion_id,
        "items": a.items,
        "status": a.status,
        "confirmed_by": a.confirmed_by,
        "result": a.result,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _serialize_link(link: Link) -> dict[str, Any]:
    return {
        "source_key": link.source_key,
        "target_key": link.target_key,
        "type_std": link.type_std,
        "direction": link.direction,
    }


def _serialize_change(c: Change) -> dict[str, Any]:
    return {
        "id": c.id,
        "issue_key": c.issue_key,
        "change_id": c.change_id,
        "idx": c.idx,
        "at": c.at.isoformat() if c.at else None,
        "field": c.field,
        "from_val": c.from_val,
        "to_val": c.to_val,
        "from_str": c.from_str,
        "to_str": c.to_str,
    }


def _serialize_score(s: Score) -> dict[str, Any]:
    return {
        "id": s.id,
        "scorer": s.scorer,
        "as_of": s.as_of.isoformat() if s.as_of else None,
        "value": s.value,
        "level": s.level,
        "is_critical": s.is_critical,
        "deadline_type": s.deadline_type,
        "deadline_at": s.deadline_at.isoformat() if s.deadline_at else None,
        "factors": s.factors,
        "extra": s.extra,
    }


@issues_router.get("/{key}")
def get_issue_detail(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
):
    issue = session.get(Issue, key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_viewer(issue.project_key, user=user, session=session)

    risk_state = session.get(RiskState, key)

    scores = session.scalars(
        select(Score)
        .where(Score.issue_key == key)
        .order_by(Score.as_of.desc(), Score.id.desc())
        .limit(10)
    ).all()

    links = session.scalars(
        select(Link).where((Link.source_key == key) | (Link.target_key == key))
    ).all()

    changes = session.scalars(
        select(Change)
        .where(Change.issue_key == key)
        .order_by(Change.at.desc(), Change.id.desc())
        .limit(10)
    ).all()

    latest_suggestion = session.scalars(
        select(Suggestion)
        .where(Suggestion.issue_key == key)
        .order_by(Suggestion.id.desc())
    ).first()

    recent_actions = session.scalars(
        select(Action)
        .where(Action.issue_key == key)
        .order_by(Action.id.desc())
        .limit(10)
    ).all()

    return {
        "issue": _serialize_issue(issue),
        "risk_state": _serialize_risk_state(risk_state),
        "scores": [_serialize_score(s) for s in scores],
        "suggestion": _serialize_suggestion(latest_suggestion),
        "recent_actions": [_serialize_action(a) for a in recent_actions],
        "links": [_serialize_link(link) for link in links],
        "recent_changes": [_serialize_change(c) for c in changes],
    }


@issues_router.get("/{key}/suggestion")
def get_issue_suggestion(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    issue = session.get(Issue, key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_viewer(issue.project_key, user=user, session=session)

    cached = get_cached_suggestion(session, key, issue.updated_at)
    if cached is not None and cached.valid:
        created_at_val = (
            cached.created_at.isoformat()
            if isinstance(cached.created_at, datetime)
            else str(cached.created_at)
        )
        return {
            "status": "ready",
            "suggestion": cached.output,
            "model": cached.model,
            "created_at": created_at_val,
        }

    enqueue_suggestion(key, settings)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "pending", "message": "Suggestion generation in progress"},
    )


@issues_router.post("/{key}/dismiss")
def dismiss_issue_risk(
    key: str,
    body: DismissRequest | None = None,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
):
    issue = session.get(Issue, key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_pm(issue.project_key, user=user, session=session)

    rs = session.get(RiskState, key)
    if rs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk state not found")

    rs.dismissed_at_level = rs.level
    session.commit()
    return {
        "status": "dismissed",
        "issue_key": key,
        "dismissed_at_level": rs.level,
    }


@issues_router.get("/{key}/transitions")
def list_issue_transitions(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    jira_client: JiraClient = Depends(get_jira_client),
) -> list[dict[str, Any]]:
    issue = session.get(Issue, key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_pm(issue.project_key, user=user, session=session)
    try:
        transitions = jira_client.get_transitions(key)
    except (JiraError, httpx.HTTPError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không lấy được danh sách chuyển trạng thái từ Jira: {e}",
        ) from None
    return [
        {"id": t.id, "name": t.name, "to_status": t.to_status, "to_category": t.to_category}
        for t in transitions
    ]
