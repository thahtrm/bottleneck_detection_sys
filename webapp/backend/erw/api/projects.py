from __future__ import annotations

from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from erw.api.issues import local_mode_or_403
from erw.auth import (
    get_session,
    get_user_project_role,
    normalize_project_role,
    require_admin,
    require_authenticated_user,
    require_pm,
    require_viewer,
)
from erw.db import utcnow
from erw.integrations.jira import JiraError
from erw.integrations.local_jira import LocalJiraService
from erw.models import (
    Component,
    Issue,
    Project,
    ProjectMember,
    ReportFile,
    RiskState,
    Sprint,
    User,
    Version,
    default_avatar_color,
)
from erw.pipeline.chat_reports import persist_health_report, report_dedup_key
from erw.settings import Settings, get_settings
from erw.sql_like import like_contains

MemberRole = Literal["pm", "developer", "viewer"]


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

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, v):
        return normalize_project_role(v)


class ProjectMemberUpdate(BaseModel):
    role: MemberRole

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, v):
        return normalize_project_role(v)


class AssignableUserItem(BaseModel):
    id: int
    account_id: str | None = None
    name: str
    email: str
    avatar_url: str | None = None
    avatar_color: str = "#0052CC"
    job_title: str | None = None
    department: str | None = None
    is_admin: bool
    role: str


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
        role=normalize_project_role(member.role) or member.role,
        is_active=getattr(user, "is_active", True) is not False,
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
    local_day = local.date().isoformat()
    # Seconds → unique artifact per generate/update (§3 A: new file, no overwrite).
    slot_label = f"od-{local:%H%M%S}"
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
    report = session.scalar(select(ReportFile).where(ReportFile.message_id == message.id))
    return {
        "ok": True,
        "message_id": message.id,
        "report_id": report.id if report else None,
        "project": key,
        "report_date": local_day,
        "slot_hhmm": slot_label,
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
    if getattr(target, "is_active", True) is False:
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


@_projects_sub.get("/{key}/assignable-users", response_model=list[AssignableUserItem])
@_projects_sub.get("/{key}/assignable-users/", response_model=list[AssignableUserItem], include_in_schema=False)
def list_assignable_users(
    key: str,
    q: str | None = Query(default=None),
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[AssignableUserItem]:
    _ensure_project(session, key)
    require_viewer(key, user=user, session=session)
    stmt = (
        select(User, ProjectMember.role)
        .outerjoin(
            ProjectMember,
            (ProjectMember.user_id == User.id) & (ProjectMember.project_key == key),
        )
        .where(
            User.is_active.is_(True),
            or_(User.is_admin.is_(True), ProjectMember.user_id.is_not(None)),
        )
    )
    needle = (q or "").strip().lower()
    if needle:
        pattern = like_contains(needle)
        stmt = stmt.where(
            func.lower(User.name).like(pattern, escape="\\")
            | func.lower(User.email).like(pattern, escape="\\")
            | func.lower(func.coalesce(User.account_id, "")).like(pattern, escape="\\")
        )
    stmt = stmt.order_by(func.lower(User.name), func.lower(User.email))
    rows = session.execute(stmt).all()
    items: list[AssignableUserItem] = []
    for u, member_role in rows:
        effective_role = "admin" if u.is_admin else (normalize_project_role(member_role) or "viewer")
        items.append(
            AssignableUserItem(
                id=u.id,
                account_id=u.account_id,
                name=u.name,
                email=u.email,
                avatar_url=u.avatar_url,
                avatar_color=u.avatar_color or default_avatar_color(u.name or u.email),
                job_title=u.job_title,
                department=u.department,
                is_admin=bool(u.is_admin),
                role=effective_role,
            )
        )
    return items


class ProjectWrite(BaseModel):
    key: str
    name: str
    description: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    lead_user_id: int | None = None


class ComponentWrite(BaseModel):
    name: str
    description: str | None = None
    lead_user_id: int | None = None


class ComponentPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    lead_user_id: int | None = None


class VersionWrite(BaseModel):
    name: str
    description: str | None = None
    start_date: str | None = None
    release_date: str | None = None
    released: bool = False


class VersionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    start_date: str | None = None
    release_date: str | None = None
    released: bool | None = None


class SprintWrite(BaseModel):
    name: str
    goal: str | None = None
    start_at: str | None = None
    end_at: str | None = None


class SprintPatch(BaseModel):
    name: str | None = None
    goal: str | None = None
    start_at: str | None = None
    end_at: str | None = None


class RankBody(BaseModel):
    issue_key: str
    sprint_id: int | None = None
    before_key: str | None = None


def _jira_http(exc: JiraError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.body or "Jira error")


def _require_project_creator(session: Session, user: User) -> None:
    if user.is_admin:
        return
    is_pm = session.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.user_id == user.id, ProjectMember.role == "pm")
    )
    if not is_pm:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PM role required to create a project")


def _project_out(project: Project) -> dict[str, Any]:
    return {
        "key": project.key,
        "name": project.name,
        "description": project.description or "",
        "lead_user_id": project.lead_user_id,
        "tracked": project.tracked,
    }


def _component_out(component: Component) -> dict[str, Any]:
    return {
        "id": component.id,
        "project_key": component.project_key,
        "name": component.name,
        "description": component.description or "",
        "lead_user_id": component.lead_user_id,
    }


def _version_out(version: Version) -> dict[str, Any]:
    return {
        "id": version.id,
        "project_key": version.project_key,
        "name": version.name,
        "description": version.description or "",
        "released": bool(version.released),
        "start_date": version.start_date.isoformat() if version.start_date else None,
        "release_date": version.release_date.isoformat() if version.release_date else None,
    }


def _sprint_out(sprint: Sprint) -> dict[str, Any]:
    return {
        "id": sprint.id,
        "project_key": sprint.project_key,
        "name": sprint.name,
        "goal": sprint.goal or "",
        "state": sprint.state,
        "start_at": sprint.start_at.isoformat() if sprint.start_at else None,
        "end_at": sprint.end_at.isoformat() if sprint.end_at else None,
        "complete_at": sprint.complete_at.isoformat() if sprint.complete_at else None,
    }


def _present_fields(model: BaseModel, names: tuple[str, ...]) -> dict[str, Any]:
    payload = model.model_dump(exclude_unset=True)
    return {name: payload[name] for name in names if name in payload}


@_projects_sub.post("", status_code=status.HTTP_201_CREATED)
@_projects_sub.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_project(
    body: ProjectWrite,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _require_project_creator(session, user)
    try:
        project = LocalJiraService.create_project(
            session,
            key=body.key,
            name=body.name,
            description=body.description,
            actor=user,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _project_out(project)


@_projects_sub.patch("/{key}")
def update_project(
    key: str,
    body: ProjectPatch,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        project = LocalJiraService.update_project(session, key, _present_fields(body, ("name", "description", "lead_user_id")))
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _project_out(project)


@_projects_sub.get("/{key}/components")
def list_components(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _ensure_project(session, key)
    require_viewer(key, user=user, session=session)
    try:
        rows = LocalJiraService.list_components(session, key)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    return [_component_out(row) for row in rows]


@_projects_sub.post("/{key}/components", status_code=status.HTTP_201_CREATED)
def create_component(
    key: str,
    body: ComponentWrite,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        component = LocalJiraService.create_component(
            session,
            key,
            name=body.name,
            description=body.description,
            lead_user_id=body.lead_user_id,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _component_out(component)


@_projects_sub.patch("/{key}/components/{component_id}")
def update_component(
    key: str,
    component_id: int,
    body: ComponentPatch,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        component = LocalJiraService.update_component(
            session,
            key,
            component_id,
            _present_fields(body, ("name", "description", "lead_user_id")),
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _component_out(component)


@_projects_sub.delete("/{key}/components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_component(
    key: str,
    component_id: int,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        LocalJiraService.delete_component(session, key, component_id)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@_projects_sub.get("/{key}/versions")
def list_versions(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _ensure_project(session, key)
    require_viewer(key, user=user, session=session)
    try:
        rows = LocalJiraService.list_versions(session, key)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    return [_version_out(row) for row in rows]


@_projects_sub.post("/{key}/versions", status_code=status.HTTP_201_CREATED)
def create_version(
    key: str,
    body: VersionWrite,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        version = LocalJiraService.create_version(
            session,
            key,
            name=body.name,
            description=body.description,
            start_date=body.start_date,
            release_date=body.release_date,
            released=body.released,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _version_out(version)


@_projects_sub.patch("/{key}/versions/{version_id}")
def update_version(
    key: str,
    version_id: int,
    body: VersionPatch,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        version = LocalJiraService.update_version(
            session,
            key,
            version_id,
            _present_fields(body, ("name", "description", "start_date", "release_date", "released")),
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _version_out(version)


@_projects_sub.get("/{key}/workflow")
def get_workflow(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _ensure_project(session, key)
    require_viewer(key, user=user, session=session)
    try:
        return LocalJiraService.get_project_workflow(session, key)
    except JiraError as exc:
        raise _jira_http(exc) from exc


@_projects_sub.put("/{key}/workflow")
def put_workflow(
    key: str,
    body: dict[str, Any],
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        saved = LocalJiraService.replace_workflow(session, key, body)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return saved


@_projects_sub.get("/{key}/sprints")
def list_sprints(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _ensure_project(session, key)
    require_viewer(key, user=user, session=session)
    try:
        rows = LocalJiraService.list_sprints(session, key)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    return [_sprint_out(row) for row in rows]


@_projects_sub.post("/{key}/sprints", status_code=status.HTTP_201_CREATED)
def create_sprint(
    key: str,
    body: SprintWrite,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        sprint = LocalJiraService.create_sprint(
            session,
            key,
            name=body.name,
            goal=body.goal,
            start_at=body.start_at,
            end_at=body.end_at,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _sprint_out(sprint)


@_projects_sub.patch("/{key}/sprints/{sprint_id}")
def update_sprint(
    key: str,
    sprint_id: int,
    body: SprintPatch,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        sprint = LocalJiraService.update_sprint(
            session,
            key,
            sprint_id,
            _present_fields(body, ("name", "goal", "start_at", "end_at")),
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _sprint_out(sprint)


@_projects_sub.post("/{key}/sprints/{sprint_id}/start")
def start_sprint(
    key: str,
    sprint_id: int,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        sprint = LocalJiraService.start_sprint(session, key, sprint_id)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return _sprint_out(sprint)


@_projects_sub.post("/{key}/sprints/{sprint_id}/complete")
def complete_sprint(
    key: str,
    sprint_id: int,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        sprint, moved = LocalJiraService.complete_sprint(session, key, sprint_id, settings=app_settings)
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    payload = _sprint_out(sprint)
    payload["moved_to_backlog"] = moved
    return payload


@_projects_sub.post("/{key}/backlog/rank")
def rank_backlog(
    key: str,
    body: RankBody,
    request: Request,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    app_settings = local_mode_or_403(request, settings)
    _ensure_project(session, key)
    require_pm(key, user=user, session=session)
    try:
        issue = LocalJiraService.rank_backlog(
            session,
            key,
            body.issue_key,
            sprint_id=body.sprint_id,
            before_key=body.before_key,
            actor=user,
            settings=app_settings,
        )
    except JiraError as exc:
        raise _jira_http(exc) from exc
    session.commit()
    return {"issue_key": issue.key, "rank": issue.rank, "sprint_id": body.sprint_id}


@_projects_sub.get("/{key}/board")
def get_board(
    key: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _ensure_project(session, key)
    require_viewer(key, user=user, session=session)
    try:
        return LocalJiraService.get_board(session, key)
    except JiraError as exc:
        raise _jira_http(exc) from exc


router.include_router(_projects_sub)
router.include_router(_admin_sub)
