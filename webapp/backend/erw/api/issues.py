from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.api.actions import get_jira_client
from erw.auth import get_session, require_authenticated_user, require_developer, require_pm, require_viewer
from erw.integrations.jira import JiraClient, JiraError
from erw.integrations.llm import enqueue_suggestion, get_cached_suggestion
from erw.integrations.local_jira import LocalJiraService
from erw.models import Action, Change, Issue, Link, RiskState, Score, Suggestion, User
from erw.settings import Settings, get_settings

issues_router = APIRouter(prefix="/api/issues", tags=["issues"])
router = issues_router


class DismissRequest(BaseModel):
    reason: str | None = None


class CreateIssueRequest(BaseModel):
    project_key: str
    summary: str
    issuetype: str = "Task"
    priority: str = "Medium"
    description: str = ""
    parent_key: str | None = None
    assignee: str | None = None
    duedate: str | None = None
    story_points: float | None = None
    labels: list[str] | None = None


class UpdateIssueRequest(BaseModel):
    fields: dict[str, Any] = {}
    expected_updated: str | None = None
    expected_version: int | None = None


class TransitionRequest(BaseModel):
    transition_id: str | int


class LinkRequest(BaseModel):
    target_key: str
    link_type: str


class CloneRequest(BaseModel):
    summary: str | None = None


class MoveRequest(BaseModel):
    project_key: str | None = None
    issuetype: str | None = None


class CommentBody(BaseModel):
    body: str


class WorklogBody(BaseModel):
    time_spent: str | int | float
    started_at: str | None = None
    comment: str | None = None


def local_mode_or_403(request: Request, settings: Settings) -> Settings:
    app_settings = getattr(request.app.state, "settings", None) or settings
    if getattr(app_settings, "jira_mode", "local") != "local":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only available in local mode")
    return app_settings


def _issue_or_404(session: Session, key: str) -> Issue:
    issue = session.get(Issue, key)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    return issue


def _jira_http(exc: JiraError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.body or "Jira error")


def _issue_out(issue: Issue) -> dict[str, Any]:
    data = _serialize_issue(issue)
    data.update(
        {
            "description": issue.description,
            "labels": list(issue.labels or []),
            "version": issue.version,
            "rank": issue.rank,
            "time_spent_seconds": issue.time_spent_seconds,
            "remaining_estimate_seconds": issue.remaining_estimate_seconds,
            "deleted_at": issue.deleted_at.isoformat() if issue.deleted_at else None,
        }
    )
    return data


def _comment_out(comment: Any) -> dict[str, Any]:
    return {
        "id": comment.id,
        "issue_key": comment.issue_key,
        "author_id": comment.author_id,
        "author_name": comment.author_name,
        "body": comment.body,
        "mentions": list(comment.mentions or []),
        "edited": bool(comment.edited),
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
        "deleted_at": comment.deleted_at.isoformat() if comment.deleted_at else None,
    }


def _link_out(link: Link) -> dict[str, Any]:
    return {
        "source_key": link.source_key,
        "target_key": link.target_key,
        "type_std": link.type_std,
        "direction": link.direction,
    }


def _multipart_file(body: bytes, content_type: str) -> tuple[str, bytes, str | None]:
    marker = "boundary="
    if marker not in content_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expected a multipart file")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    delimiter = b"--" + boundary.encode("utf-8")
    for chunk in body.split(delimiter):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if b"\r\n\r\n" not in chunk:
            continue
        header_blob, data = chunk.split(b"\r\n\r\n", 1)
        header_text = header_blob.decode("utf-8", errors="replace")
        if "filename=" not in header_text:
            continue
        filename = "file"
        mime: str | None = None
        for line in header_text.split("\r\n"):
            lower = line.lower()
            if lower.startswith("content-disposition") and "filename=" in line:
                filename = line.split("filename=", 1)[1].strip().strip('"')
            elif lower.startswith("content-type:"):
                mime = line.split(":", 1)[1].strip() or None
        if data.endswith(b"\r\n"):
            data = data[:-2]
        return filename, data, mime
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File part is required")


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


@issues_router.post("", status_code=status.HTTP_201_CREATED)
@issues_router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_issue(
    body: CreateIssueRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = getattr(request.app.state, "settings", None) or settings
    if getattr(app_settings, "jira_mode", "local") != "local":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Issue create is only available in local mode")
    require_developer(body.project_key, user=user, session=session)
    try:
        issue = LocalJiraService.create_issue(
            session,
            project_key=body.project_key,
            summary=body.summary,
            issuetype=body.issuetype,
            priority=body.priority,
            description=body.description,
            parent_key=body.parent_key,
            assignee=body.assignee,
            duedate=body.duedate,
            story_points=body.story_points,
            labels=body.labels,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.body or "Jira error") from exc
    session.commit()
    return _serialize_issue(issue)


@issues_router.get("")
@issues_router.get("/", include_in_schema=False)
def list_issues(
    request: Request,
    project: str,
    q: str | None = None,
    issuetype: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    sprint_id: int | None = None,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_viewer(project, user=user, session=session)
    status_name = request.query_params.get("status") or None
    try:
        found = LocalJiraService.search_issues(
            session,
            project_key=project,
            q=q,
            status=status_name,
            issuetype=issuetype,
            priority=priority,
            assignee=assignee,
            sprint_id=sprint_id,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    return {"issues": [_issue_out(issue) for issue in found]}


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
    require_developer(issue.project_key, user=user, session=session)
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


@issues_router.patch("/{key}")
def update_issue(
    key: str,
    body: UpdateIssueRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        updated = LocalJiraService.update_issue(
            session,
            key,
            body.fields,
            actor=user,
            settings=app_settings,
            expected_version=body.expected_version,
            expected_updated=body.expected_updated,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _issue_out(updated)


@issues_router.post("/{key}/transitions")
def transition_issue(
    key: str,
    body: TransitionRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        updated = LocalJiraService.transition_issue(
            session,
            key,
            str(body.transition_id),
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _issue_out(updated)


@issues_router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_issue(
    key: str,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_pm(issue.project_key, user=user, session=session)
    try:
        LocalJiraService.soft_delete_issue(session, key, actor=user, settings=app_settings)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@issues_router.post("/{key}/links")
def create_link(
    key: str,
    body: LinkRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        link = LocalJiraService.add_link(
            session,
            key,
            body.target_key,
            body.link_type,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _link_out(link)


@issues_router.delete("/{key}/links", status_code=status.HTTP_204_NO_CONTENT)
def remove_link(
    key: str,
    body: LinkRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        removed = LocalJiraService.delete_link(
            session,
            key,
            body.target_key,
            body.link_type,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@issues_router.post("/{key}/clone", status_code=status.HTTP_201_CREATED)
def clone_issue(
    key: str,
    body: CloneRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        cloned = LocalJiraService.clone_issue(
            session,
            key,
            summary=body.summary,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _issue_out(cloned)


@issues_router.post("/{key}/move")
def move_issue(
    key: str,
    body: MoveRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        moved = LocalJiraService.move_issue(
            session,
            key,
            project_key=body.project_key,
            issuetype=body.issuetype,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _issue_out(moved)


def _watch_vote(
    session: Session,
    key: str,
    user: User,
    *,
    remove: bool,
    vote: bool,
) -> dict[str, Any]:
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        if vote:
            count = (
                LocalJiraService.unvote_issue(session, key, actor=user)
                if remove
                else LocalJiraService.vote_issue(session, key, actor=user)
            )
        else:
            count = (
                LocalJiraService.unwatch_issue(session, key, actor=user)
                if remove
                else LocalJiraService.watch_issue(session, key, actor=user)
            )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    if vote:
        return {"vote_count": count, "voted": not remove}
    return {"watch_count": count, "watching": not remove}


@issues_router.post("/{key}/watch")
def watch_issue(
    key: str,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    return _watch_vote(session, key, user, remove=False, vote=False)


@issues_router.delete("/{key}/watch")
def unwatch_issue(
    key: str,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    return _watch_vote(session, key, user, remove=True, vote=False)


@issues_router.post("/{key}/vote")
def vote_issue(
    key: str,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    return _watch_vote(session, key, user, remove=False, vote=True)


@issues_router.delete("/{key}/vote")
def unvote_issue(
    key: str,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    return _watch_vote(session, key, user, remove=True, vote=True)


@issues_router.post("/{key}/comments", status_code=status.HTTP_201_CREATED)
def create_comment(
    key: str,
    body: CommentBody,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        comment = LocalJiraService.add_comment(session, key, body.body, actor=user, settings=app_settings)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _comment_out(comment)


@issues_router.patch("/{key}/comments/{comment_id}")
def edit_comment(
    key: str,
    comment_id: int,
    body: CommentBody,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        comment = LocalJiraService.update_comment(
            session,
            key,
            comment_id,
            body.body,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _comment_out(comment)


@issues_router.delete("/{key}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_comment(
    key: str,
    comment_id: int,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        LocalJiraService.delete_comment(session, key, comment_id, actor=user, settings=app_settings)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@issues_router.get("/{key}/activity")
def list_activity(
    key: str,
    kind: str = "all",
    order: str = "desc",
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    issue = _issue_or_404(session, key)
    require_viewer(issue.project_key, user=user, session=session)
    try:
        items = LocalJiraService.list_activity(session, key, kind=kind, order=order)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    return {"items": items}


@issues_router.post("/{key}/worklogs", status_code=status.HTTP_201_CREATED)
def create_worklog(
    key: str,
    body: WorklogBody,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    try:
        worklog = LocalJiraService.add_worklog(
            session,
            key,
            body.time_spent,
            started_at=body.started_at,
            comment=body.comment,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    session.refresh(issue)
    return {
        "id": worklog.id,
        "issue_key": worklog.issue_key,
        "time_spent_seconds": worklog.time_spent_seconds,
        "comment": worklog.comment,
        "issue_time_spent_seconds": issue.time_spent_seconds,
        "remaining_estimate_seconds": issue.remaining_estimate_seconds,
    }


@issues_router.post("/{key}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    key: str,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    issue = _issue_or_404(session, key)
    require_developer(issue.project_key, user=user, session=session)
    filename, content, mime_type = _multipart_file(await request.body(), request.headers.get("content-type", ""))
    try:
        attachment = LocalJiraService.add_attachment(
            session,
            key,
            filename=filename,
            content=content,
            mime_type=mime_type,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return {
        "id": attachment.id,
        "issue_key": attachment.issue_key,
        "filename": attachment.filename,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
    }


@issues_router.get("/{key}/attachments/{attachment_id}")
def download_attachment(
    key: str,
    attachment_id: int,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    issue = _issue_or_404(session, key)
    require_viewer(issue.project_key, user=user, session=session)
    try:
        attachment = LocalJiraService.get_attachment(session, key, attachment_id)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    root = Path(settings.attachments_dir).resolve()
    path = Path(attachment.storage_path).resolve()
    if path != root and root not in path.parents or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return FileResponse(path, media_type=attachment.mime_type or "application/octet-stream", filename=attachment.filename)
