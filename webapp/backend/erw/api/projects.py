from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from erw.auth import get_session, get_user_project_role, require_admin, require_authenticated_user
from erw.models import Issue, Project, ProjectMember, RiskState, User
from erw.settings import Settings, get_settings


class ProjectStats(BaseModel):
    total_issues: int
    high_risk_issues: int
    med_risk_issues: int
    blocked_issues: int


class ProjectListItem(BaseModel):
    key: str
    name: str
    tracked: bool
    role: str
    stats: ProjectStats


class ProjectResponse(BaseModel):
    key: str
    name: str
    tracked: bool
    status_map: dict[str, Any] = {}
    thresholds: dict[str, Any] = {}


def get_project_stats(session: Session, project_key: str) -> dict[str, int]:
    stmt = (
        select(
            func.count(Issue.key).label("total_issues"),
            func.count(case((RiskState.level == "HIGH", 1))).label("high_risk_issues"),
            func.count(case((RiskState.level == "MED", 1))).label("med_risk_issues"),
            func.count(case((RiskState.blocked.is_(True), 1))).label("blocked_issues"),
        )
        .outerjoin(RiskState, Issue.key == RiskState.issue_key)
        .where(
            Issue.project_key == project_key,
            Issue.deleted_at.is_(None),
        )
    )
    row = session.execute(stmt).one()
    return {
        "total_issues": int(row.total_issues or 0),
        "high_risk_issues": int(row.high_risk_issues or 0),
        "med_risk_issues": int(row.med_risk_issues or 0),
        "blocked_issues": int(row.blocked_issues or 0),
    }


router = APIRouter()
projects_router = router

_projects_sub = APIRouter(prefix="/api/projects", tags=["projects"])
_admin_sub = APIRouter(prefix="/api/admin/projects", tags=["admin-projects"])


@_projects_sub.get("", response_model=list[ProjectListItem])
@_projects_sub.get("/", response_model=list[ProjectListItem], include_in_schema=False)
def list_projects(
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ProjectListItem]:
    app_settings = getattr(request.app.state, "settings", None) or settings
    if user.is_admin:
        existing = {p.key: p for p in session.execute(select(Project)).scalars().all()}
        added = False
        for key in app_settings.jira_projects:
            if key not in existing:
                new_p = Project(key=key, name="", tracked=True)
                session.add(new_p)
                existing[key] = new_p
                added = True
        if added:
            session.commit()
        projects = sorted(existing.values(), key=lambda p: p.key)
    else:
        members = session.execute(
            select(ProjectMember).where(ProjectMember.user_id == user.id)
        ).scalars().all()
        projects = []
        for m in members:
            p = session.get(Project, m.project_key)
            if p is None:
                p = Project(key=m.project_key, name="", tracked=True)
                session.add(p)
                session.commit()
            projects.append(p)
        projects.sort(key=lambda p: p.key)

    items = []
    for p in projects:
        role = get_user_project_role(session, user, p.key) or "viewer"
        stats = get_project_stats(session, p.key)
        items.append(
            ProjectListItem(
                key=p.key,
                name=p.name,
                tracked=p.tracked,
                role=role,
                stats=ProjectStats(**stats),
            )
        )
    return items


@_admin_sub.post("/{key}/toggle-tracking", response_model=ProjectResponse)
@_projects_sub.post("/{key}/toggle-tracking", response_model=ProjectResponse, include_in_schema=False)
def toggle_tracking(
    key: str,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ProjectResponse:
    p = session.get(Project, key)
    if p is None:
        p = Project(key=key, name="", tracked=True)
        session.add(p)
    p.tracked = not p.tracked
    session.commit()
    session.refresh(p)
    return ProjectResponse(
        key=p.key,
        name=p.name,
        tracked=p.tracked,
        status_map=p.status_map or {},
        thresholds=p.thresholds or {},
    )


router.include_router(_projects_sub)
router.include_router(_admin_sub)
