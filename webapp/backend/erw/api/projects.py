from __future__ import annotations

from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from erw.auth import get_session, get_user_project_role, require_admin, require_authenticated_user
from erw.db import utcnow
from erw.models import Issue, Project, ProjectMember, RiskState, User
from erw.pipeline.chat_reports import persist_health_report, report_dedup_key
from erw.settings import Settings, get_settings

MemberRole = Literal["pm", "viewer"]


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


class ProjectMemberItem(BaseModel):
    user_id: int
    email: str
    name: str
    role: str
    is_active: bool


class ProjectMemberCreate(BaseModel):
    email: str
    role: MemberRole = "viewer"


class ProjectMemberUpdate(BaseModel):
    role: MemberRole


def _ensure_project(session: Session, key: str) -> Project:
    project = session.get(Project, key)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _require_project_access(session: Session, user: User, key: str) -> str:
    role = get_user_project_role(session, user, key)
    if user.is_admin:
        return "admin"
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for project")
    return role


def _require_member_manager(session: Session, user: User, key: str) -> None:
    role = _require_project_access(session, user, key)
    if user.is_admin or role == "pm":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PM role required for project")


def _count_pms(session: Session, project_key: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_key == project_key, ProjectMember.role == "pm")
        )
        or 0
    )


def _serialize_member(member: ProjectMember, user: User) -> ProjectMemberItem:
    return ProjectMemberItem(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        is_active=bool(getattr(user, "is_active", True)),
    )


def _guard_last_pm(session: Session, project_key: str, member: ProjectMember, *, removing: bool, new_role: str | None) -> None:
    if member.role != "pm":
        return
    demoting = new_role is not None and new_role != "pm"
    if not removing and not demoting:
        return
    if _count_pms(session, project_key) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove or demote the last PM of this project",
        )


@_projects_sub.post("/{key}/health-report")
@_projects_sub.post("/{key}/health-report/", include_in_schema=False)
def generate_health_report(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """On-demand Daily Project Health Report (PM/Admin). Reuses ReportSlot artifact shape."""
    _ensure_project(session, key)
    role = get_user_project_role(session, user, key)
    if not (user.is_admin or role == "pm"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PM role required for project")
    now = utcnow()
    local = now.astimezone(ZoneInfo(settings.tz))
    hhmm = f"{local:%H:%M}"
    local_day = local.date().isoformat()
    slot_label = f"od-{hhmm}"
    # On-demand dedup per user/project/day+minute; file name uses od- prefix vs schedule.
    dedup = report_dedup_key(user.id, key, slot_label, local_day)
    message = persist_health_report(
        session,
        settings,
        user_id=user.id,
        project=key,
        now=now,
        hhmm=slot_label,
        local_day=local_day,
        dedup=dedup,
    )
    session.commit()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Health report already generated for this slot/day",
        )
    return {
        "ok": True,
        "message_id": message.id,
        "project": key,
        "report_date": local_day,
        "slot_hhmm": hhmm,
    }


@_projects_sub.get("/{key}/members", response_model=list[ProjectMemberItem])
@_projects_sub.get("/{key}/members/", response_model=list[ProjectMemberItem], include_in_schema=False)
def list_members(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[ProjectMemberItem]:
    _ensure_project(session, key)
    _require_project_access(session, user, key)
    rows = session.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_key == key)
        .order_by(func.lower(User.email))
    ).all()
    return [_serialize_member(member, member_user) for member, member_user in rows]


@_projects_sub.post("/{key}/members", response_model=ProjectMemberItem, status_code=status.HTTP_201_CREATED)
@_projects_sub.post(
    "/{key}/members/",
    response_model=ProjectMemberItem,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def add_member(
    key: str,
    body: ProjectMemberCreate,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> ProjectMemberItem:
    _ensure_project(session, key)
    _require_member_manager(session, user, key)
    email = body.email.strip()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")
    target = session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not getattr(target, "is_active", True):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is disabled")
    existing = session.get(ProjectMember, (key, target.id))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member")
    member = ProjectMember(project_key=key, user_id=target.id, role=body.role)
    session.add(member)
    session.commit()
    session.refresh(member)
    return _serialize_member(member, target)


@_projects_sub.patch("/{key}/members/{user_id}", response_model=ProjectMemberItem)
@_projects_sub.patch("/{key}/members/{user_id}/", response_model=ProjectMemberItem, include_in_schema=False)
def update_member(
    key: str,
    user_id: int,
    body: ProjectMemberUpdate,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> ProjectMemberItem:
    _ensure_project(session, key)
    _require_member_manager(session, user, key)
    member = session.get(ProjectMember, (key, user_id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _guard_last_pm(session, key, member, removing=False, new_role=body.role)
    member.role = body.role
    session.commit()
    session.refresh(member)
    return _serialize_member(member, target)


@_projects_sub.delete("/{key}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@_projects_sub.delete("/{key}/members/{user_id}/", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def remove_member(
    key: str,
    user_id: int,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> None:
    _ensure_project(session, key)
    _require_member_manager(session, user, key)
    member = session.get(ProjectMember, (key, user_id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    _guard_last_pm(session, key, member, removing=True, new_role=None)
    session.delete(member)
    session.commit()


router.include_router(_projects_sub)
router.include_router(_admin_sub)
