from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erw.auth import create_session_token, get_session, require_authenticated_user, verify_password
from erw.models import User
from erw.settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    jira_base_url: str = ""


def _user_response(user: User, settings: Settings) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        jira_base_url=settings.jira_base_url.rstrip("/"),
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

    if user is None or not verify_password(req.password, user.password_hash):
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
    return _user_response(user, app_settings)


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
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    app_settings = getattr(request.app.state, "settings", None) or settings
    return _user_response(current_user, app_settings)
