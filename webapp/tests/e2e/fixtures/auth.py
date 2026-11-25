from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.auth import create_session_token, hash_password
from erw.db import utcnow
from erw.models import Project, ProjectMember, User

from .capabilities import has_column, has_route, require_capability, supports_member_role


@dataclass(frozen=True)
class E2EAccountSpec:
    role_key: str
    email: str
    name: str
    password: str
    is_admin: bool
    project_role: str | None
    account_id: str
    job_title: str
    department: str
    avatar_color: str


E2E_ACCOUNTS: dict[str, E2EAccountSpec] = {
    "admin": E2EAccountSpec(
        role_key="admin",
        email="admin@e2e.local",
        name="E2E Admin",
        password="Admin@E2E123",
        is_admin=True,
        project_role=None,
        account_id="local-admin",
        job_title="Workspace Administrator",
        department="Platform",
        avatar_color="#1f77b4",
    ),
    "pm": E2EAccountSpec(
        role_key="pm",
        email="pm@e2e.local",
        name="E2E PM",
        password="Pm@E2E123",
        is_admin=False,
        project_role="pm",
        account_id="local-pm",
        job_title="Engineering Manager",
        department="Delivery",
        avatar_color="#2ca02c",
    ),
    "developer": E2EAccountSpec(
        role_key="developer",
        email="dev@e2e.local",
        name="E2E Developer",
        password="Dev@E2E123",
        is_admin=False,
        project_role="developer",
        account_id="local-dev",
        job_title="Senior Software Engineer",
        department="Core",
        avatar_color="#ff7f0e",
    ),
    "viewer": E2EAccountSpec(
        role_key="viewer",
        email="viewer@e2e.local",
        name="E2E Viewer",
        password="Viewer@E2E123",
        is_admin=False,
        project_role="viewer",
        account_id="local-viewer",
        job_title="Stakeholder",
        department="Product",
        avatar_color="#9467bd",
    ),
    "outsider": E2EAccountSpec(
        role_key="outsider",
        email="outsider@e2e.local",
        name="E2E Outsider",
        password="Outsider@E2E123",
        is_admin=False,
        project_role=None,
        account_id="local-outsider",
        job_title="External Contractor",
        department="External",
        avatar_color="#8c564b",
    ),
}


def create_e2e_user(
    session: Session,
    *,
    email: str,
    name: str,
    password: str = "Pass@E2E123",
    is_admin: bool = False,
    is_active: bool = True,
    account_id: str | None = None,
    avatar_url: str | None = None,
    avatar_color: str | None = None,
    job_title: str | None = None,
    department: str | None = None,
    timezone: str = "Asia/Ho_Chi_Minh",
) -> User:
    """Create or update a test user safely across pre-M1 and post-M1 User schemas."""
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        kwargs: dict[str, Any] = {
            "email": email,
            "name": name,
            "password_hash": hash_password(password),
            "is_admin": is_admin,
            "is_active": is_active,
            "created_at": utcnow(),
        }
        optional_fields = {
            "account_id": account_id or email.split("@")[0],
            "avatar_url": avatar_url,
            "avatar_color": avatar_color,
            "job_title": job_title,
            "department": department,
            "timezone": timezone,
        }
        for col, val in optional_fields.items():
            if val is not None and has_column(User, col):
                kwargs[col] = val
        user = User(**kwargs)
        session.add(user)
    else:
        user.name = name
        user.password_hash = hash_password(password)
        user.is_admin = is_admin
        user.is_active = is_active
        optional_updates = {
            "account_id": account_id,
            "avatar_url": avatar_url,
            "avatar_color": avatar_color,
            "job_title": job_title,
            "department": department,
            "timezone": timezone,
        }
        for col, val in optional_updates.items():
            if val is not None and has_column(User, col):
                setattr(user, col, val)
    session.flush()
    return user


def ensure_e2e_project(session: Session, project_key: str = "DEMO", name: str = "Demo Project") -> Project:
    proj = session.get(Project, project_key)
    if proj is None:
        proj = Project(key=project_key, name=name, tracked=True)
        session.add(proj)
        session.flush()
    return proj


def seed_e2e_accounts(
    session: Session,
    *,
    project_key: str = "DEMO",
    include_developer_member: bool | None = None,
) -> dict[str, User]:
    """Provision standard E2E role accounts and memberships for project_key."""
    ensure_e2e_project(session, project_key=project_key)
    if include_developer_member is None:
        include_developer_member = supports_member_role("developer")

    users: dict[str, User] = {}
    for role_key, spec in E2E_ACCOUNTS.items():
        user = create_e2e_user(
            session,
            email=spec.email,
            name=spec.name,
            password=spec.password,
            is_admin=spec.is_admin,
            is_active=True,
            account_id=spec.account_id,
            job_title=spec.job_title,
            department=spec.department,
            avatar_color=spec.avatar_color,
        )
        users[role_key] = user

        if spec.project_role is not None:
            if spec.project_role == "developer" and not include_developer_member:
                continue
            member = session.get(ProjectMember, (project_key, user.id))
            if member is None:
                session.add(ProjectMember(project_key=project_key, user_id=user.id, role=spec.project_role))
            else:
                member.role = spec.project_role

    session.commit()
    return users


def login_as(client: TestClient, email: str, password: str) -> dict[str, Any]:
    """Authenticate a TestClient via POST /api/auth/login and return parsed user payload."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed for {email}: {resp.status_code} {resp.text}"
    return resp.json()


def mint_session_cookie(client: TestClient, user: User, settings: Any) -> str:
    """Directly sign and attach an erw_session cookie onto client without hitting /api/auth/login."""
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)
    return token


def quick_switch(client: TestClient, user_id: int):
    """Switch active session user via POST /api/auth/quick-switch (guarded until M1 lands)."""
    require_capability(
        has_route(client.app, "POST", "/api/auth/quick-switch"),
        "POST /api/auth/quick-switch endpoint not implemented yet",
    )
    return client.post("/api/auth/quick-switch", json={"user_id": user_id})


@pytest.fixture
def e2e_accounts(e2e_session: Session) -> dict[str, User]:
    return seed_e2e_accounts(e2e_session, project_key="DEMO")


def _make_role_client(e2e_app, role_key: str, e2e_accounts: dict[str, User]):
    spec = E2E_ACCOUNTS[role_key]
    if role_key == "developer":
        require_capability(
            supports_member_role("developer"),
            "ProjectMember role 'developer' not supported yet",
        )
    assert role_key in e2e_accounts
    with TestClient(e2e_app) as client:
        login_as(client, spec.email, spec.password)
        yield client


@pytest.fixture
def admin_client(e2e_app, e2e_accounts):
    yield from _make_role_client(e2e_app, "admin", e2e_accounts)


@pytest.fixture
def pm_client(e2e_app, e2e_accounts):
    yield from _make_role_client(e2e_app, "pm", e2e_accounts)


@pytest.fixture
def developer_client(e2e_app, e2e_accounts):
    yield from _make_role_client(e2e_app, "developer", e2e_accounts)


@pytest.fixture
def viewer_client(e2e_app, e2e_accounts):
    yield from _make_role_client(e2e_app, "viewer", e2e_accounts)


@pytest.fixture
def outsider_client(e2e_app, e2e_accounts):
    yield from _make_role_client(e2e_app, "outsider", e2e_accounts)
