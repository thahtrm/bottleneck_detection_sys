from __future__ import annotations

from datetime import UTC, datetime

import pytest

from erw.auth import create_session_token, hash_password
from erw.models import Project, ProjectMember, User


@pytest.fixture
def world(session):
    admin = User(
        email="admin@example.com",
        name="Admin",
        password_hash=hash_password("admin_pass"),
        is_admin=True,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    pm = User(
        email="pm@example.com",
        name="PM",
        password_hash=hash_password("pm_pass"),
        is_admin=False,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    viewer = User(
        email="viewer@example.com",
        name="Viewer",
        password_hash=hash_password("viewer_pass"),
        is_admin=False,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    outsider = User(
        email="out@example.com",
        name="Out",
        password_hash=hash_password("out_pass"),
        is_admin=False,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add_all([admin, pm, viewer, outsider, Project(key="DEMO", name="Demo", tracked=True)])
    session.flush()
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=viewer.id, role="viewer"),
        ]
    )
    session.commit()
    for row in (admin, pm, viewer, outsider):
        session.refresh(row)
    return {"admin": admin, "pm": pm, "viewer": viewer, "outsider": outsider}


def login(client, user: User, settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


def test_admin_users_crud_and_inactive_login(client, world, settings, session):
    login(client, world["admin"], settings)
    listed = client.get("/api/admin/users")
    assert listed.status_code == 200
    assert len(listed.json()) >= 4

    created = client.post(
        "/api/admin/users",
        json={"email": "new@example.com", "name": "New User", "is_admin": False},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["generated_password"]
    user_id = body["user"]["id"]
    password = body["generated_password"]

    client.cookies.clear()
    ok = client.post("/api/auth/login", json={"email": "new@example.com", "password": password})
    assert ok.status_code == 200

    login(client, world["admin"], settings)
    disabled = client.patch(f"/api/admin/users/{user_id}", json={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["user"]["is_active"] is False

    client.cookies.clear()
    blocked = client.post("/api/auth/login", json={"email": "new@example.com", "password": password})
    assert blocked.status_code == 401

    login(client, world["admin"], settings)
    reset = client.patch(f"/api/admin/users/{world['pm'].id}", json={"reset_password": True})
    assert reset.status_code == 200
    assert reset.json()["generated_password"]


def test_members_crud_and_last_pm_guard(client, world, settings, session):
    login(client, world["viewer"], settings)
    listed = client.get("/api/projects/DEMO/members")
    assert listed.status_code == 200
    assert {row["email"] for row in listed.json()} == {"pm@example.com", "viewer@example.com"}
    assert client.post("/api/projects/DEMO/members", json={"email": "out@example.com", "role": "viewer"}).status_code == 403

    login(client, world["pm"], settings)
    added = client.post("/api/projects/DEMO/members", json={"email": "out@example.com", "role": "viewer"})
    assert added.status_code == 201

    # Cannot demote/remove sole PM
    assert (
        client.patch(f"/api/projects/DEMO/members/{world['pm'].id}", json={"role": "viewer"}).status_code
        == 400
    )
    assert client.delete(f"/api/projects/DEMO/members/{world['pm'].id}").status_code == 400

    # Promote outsider then demote original PM ok
    assert (
        client.patch(f"/api/projects/DEMO/members/{world['outsider'].id}", json={"role": "pm"}).status_code
        == 200
    )
    assert (
        client.patch(f"/api/projects/DEMO/members/{world['pm'].id}", json={"role": "viewer"}).status_code
        == 200
    )
    login(client, world["outsider"], settings)
    assert client.delete(f"/api/projects/DEMO/members/{world['viewer'].id}").status_code == 204

    # Non-member cannot list
    alone = User(
        email="alone@example.com",
        name="Alone",
        password_hash=hash_password("x"),
        is_admin=False,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(alone)
    session.commit()
    session.refresh(alone)
    login(client, alone, settings)
    assert client.get("/api/projects/DEMO/members").status_code == 403
