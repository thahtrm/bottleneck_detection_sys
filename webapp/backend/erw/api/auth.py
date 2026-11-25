from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erw.auth import (
    create_session_token,
    get_session,
    normalize_project_role,
    require_authenticated_user,
    verify_password,
)
from erw.models import ProjectMember, User, default_avatar_color
from erw.settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
demo_router = APIRouter(prefix="/api/demo", tags=["demo"])


class LoginRequest(BaseModel):
    email: str
    password: str


class QuickSwitchRequest(BaseModel):
    user_id: int


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    jira_base_url: str = ""
    account_id: str | None = None
    avatar_url: str | None = None
    avatar_color: str = "#0052CC"
    job_title: str | None = None
    department: str | None = None
    timezone: str = "Asia/Ho_Chi_Minh"
    jira_mode: Literal["local", "jira_cloud"] = "local"


class DemoUserProject(BaseModel):
    project_key: str
    role: str


class DemoUserItem(BaseModel):
    id: int
    account_id: str | None = None
    email: str
    name: str
    is_admin: bool
    avatar_url: str | None = None
    avatar_color: str = "#0052CC"
    job_title: str | None = None
    department: str | None = None
    timezone: str = "Asia/Ho_Chi_Minh"
    projects: list[DemoUserProject] = []


def _user_response(user: User, settings: Settings, session: Session) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=bool(user.is_admin),
        jira_base_url=settings.jira_base_url.rstrip("/"),
        account_id=getattr(user, "account_id", None),
        avatar_url=getattr(user, "avatar_url", None),
        avatar_color=getattr(user, "avatar_color", None) or default_avatar_color(user.name or user.email),
        job_title=getattr(user, "job_title", None),
        department=getattr(user, "department", None),
        timezone=getattr(user, "timezone", None) or "Asia/Ho_Chi_Minh",
        jira_mode=getattr(settings, "jira_mode", "local"),
    )


@router.post("/login", response_model=UserResponse)
def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    app_settings = getattr(request.app.state, "settings", None) or settings
    email = req.email.strip()
    user = session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()

    if (
        user is None
        or getattr(user, "is_active", True) is False
        or not verify_password(req.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_session_token(user.id, app_settings.session_secret)
    response.set_cookie(
        key=app_settings.session_cookie_name,
        value=token,
        max_age=app_settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return _user_response(user, app_settings, session)


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    app_settings = getattr(request.app.state, "settings", None) or settings
    response.delete_cookie(
        key=app_settings.session_cookie_name,
        path="/",
    )
    return {"status": "logged_out"}


@router.get("/me", response_model=UserResponse)
def me(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    app_settings = getattr(request.app.state, "settings", None) or settings
    return _user_response(current_user, app_settings, session)


@router.post("/quick-switch", response_model=UserResponse)
@router.post("/quick-switch/", response_model=UserResponse, include_in_schema=False)
def quick_switch(
    req: QuickSwitchRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    app_settings = getattr(request.app.state, "settings", None) or settings
    if getattr(app_settings, "jira_mode", "local") != "local":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quick switch is only available in local mode")
    target = session.get(User, req.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if getattr(target, "is_active", True) is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is disabled")

    token = create_session_token(target.id, app_settings.session_secret)
    response.set_cookie(
        key=app_settings.session_cookie_name,
        value=token,
        max_age=app_settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return _user_response(target, app_settings, session)


@demo_router.get("/users", response_model=list[DemoUserItem])
@demo_router.get("/users/", response_model=list[DemoUserItem], include_in_schema=False)
def list_demo_users(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[DemoUserItem]:
    app_settings = getattr(request.app.state, "settings", None) or settings
    if getattr(app_settings, "jira_mode", "local") != "local":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quick switch is only available in local mode")
    users = list(
        session.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .order_by(User.is_admin.desc(), User.id.asc())
        ).all()
    )
    user_ids = [u.id for u in users]
    members_by_user: dict[int, list[DemoUserProject]] = {uid: [] for uid in user_ids}
    if user_ids:
        members = session.scalars(
            select(ProjectMember)
            .where(ProjectMember.user_id.in_(user_ids))
            .order_by(ProjectMember.project_key.asc())
        ).all()
        for m in members:
            members_by_user.setdefault(m.user_id, []).append(
                DemoUserProject(
                    project_key=m.project_key,
                    role=normalize_project_role(m.role) or m.role,
                )
            )
    return [
        DemoUserItem(
            id=u.id,
            account_id=u.account_id,
            email=u.email,
            name=u.name,
            is_admin=bool(u.is_admin),
            avatar_url=u.avatar_url,
            avatar_color=u.avatar_color or default_avatar_color(u.name or u.email),
            job_title=u.job_title,
            department=u.department,
            timezone=u.timezone or "Asia/Ho_Chi_Minh",
            projects=members_by_user.get(u.id, []),
        )
        for u in users
    ]
