from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import Depends, FastAPI, HTTPException

from erw.auth import (
    create_session_token,
    get_user_project_role,
    hash_password,
    require_pm,
    require_project_role,
    require_viewer,
)
from erw.models import Issue, Project, ProjectMember, RiskState, User


@pytest.fixture
def auth_users(session):
    u_admin = User(
        email="admin@example.com",
        name="Admin User",
        password_hash=hash_password("admin_pass"),
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    u_pm = User(
        email="pm@example.com",
        name="PM User",
        password_hash=hash_password("pm_pass"),
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    u_viewer = User(
        email="viewer@example.com",
        name="Viewer User",
        password_hash=hash_password("viewer_pass"),
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    u_stranger = User(
        email="stranger@example.com",
        name="Stranger User",
        password_hash=hash_password("stranger_pass"),
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    session.add_all([u_admin, u_pm, u_viewer, u_stranger])
    session.commit()
    for u in (u_admin, u_pm, u_viewer, u_stranger):
        session.refresh(u)
    return {"admin": u_admin, "pm": u_pm, "viewer": u_viewer, "stranger": u_stranger}


@pytest.fixture
def sample_projects(session, auth_users):
    p_demo = Project(key="DEMO", name="Demo Project", tracked=True)
    p_secret = Project(key="SECRET", name="Secret Project", tracked=False)
    session.add_all([p_demo, p_secret])
    session.commit()

    # Assign PM to DEMO, Viewer to DEMO
    m_pm = ProjectMember(project_key="DEMO", user_id=auth_users["pm"].id, role="pm")
    m_viewer = ProjectMember(project_key="DEMO", user_id=auth_users["viewer"].id, role="viewer")
    # Also assign PM to SECRET as viewer
    m_secret = ProjectMember(project_key="SECRET", user_id=auth_users["pm"].id, role="viewer")
    session.add_all([m_pm, m_viewer, m_secret])
    session.commit()

    return {"DEMO": p_demo, "SECRET": p_secret}


def _login(client, user: User, settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


# ---------------------------------------------------------------------------
# 1. Models & Defaults
# ---------------------------------------------------------------------------


def test_project_model_creation(session):
    p = Project(key="ALPHA")
    session.add(p)
    session.commit()
    session.refresh(p)

    assert p.key == "ALPHA"
    assert p.name == ""
    assert p.tracked is True
    assert p.status_map == {}
    assert p.thresholds == {}


def test_project_member_model(session, auth_users, sample_projects):
    m = session.get(ProjectMember, ("DEMO", auth_users["pm"].id))
    assert m is not None
    assert m.project_key == "DEMO"
    assert m.user_id == auth_users["pm"].id
    assert m.role == "pm"


# ---------------------------------------------------------------------------
# 2. RBAC Helpers & Dependency Checks
# ---------------------------------------------------------------------------


def test_get_user_project_role(session, auth_users, sample_projects):
    admin = auth_users["admin"]
    pm = auth_users["pm"]
    viewer = auth_users["viewer"]
    stranger = auth_users["stranger"]

    # Admin always has admin role even if not in ProjectMember
    assert get_user_project_role(session, admin, "DEMO") == "admin"
    assert get_user_project_role(session, admin, "SECRET") == "admin"
    assert get_user_project_role(session, admin, "UNKNOWN") == "admin"

    # Assigned roles
    assert get_user_project_role(session, pm, "DEMO") == "pm"
    assert get_user_project_role(session, pm, "SECRET") == "viewer"
    assert get_user_project_role(session, viewer, "DEMO") == "viewer"

    # Unassigned roles return None
    assert get_user_project_role(session, viewer, "SECRET") is None
    assert get_user_project_role(session, stranger, "DEMO") is None
    assert get_user_project_role(session, stranger, "SECRET") is None


def test_require_pm_permission(session, auth_users, sample_projects):
    admin = auth_users["admin"]
    pm = auth_users["pm"]
    viewer = auth_users["viewer"]
    stranger = auth_users["stranger"]

    # Admin passes
    assert require_pm("DEMO", user=admin, session=session) == admin
    assert require_pm("SECRET", user=admin, session=session) == admin

    # PM passes on DEMO
    assert require_pm("DEMO", user=pm, session=session) == pm

    # PM fails on SECRET where role is "viewer"
    with pytest.raises(HTTPException) as exc_info:
        require_pm("SECRET", user=pm, session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "PM role required for project SECRET"

    # Viewer fails on DEMO
    with pytest.raises(HTTPException) as exc_info:
        require_pm("DEMO", user=viewer, session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "PM role required for project DEMO"

    # Stranger fails on DEMO
    with pytest.raises(HTTPException) as exc_info:
        require_pm("DEMO", user=stranger, session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "PM role required for project DEMO"


def test_require_viewer_permission(session, auth_users, sample_projects):
    admin = auth_users["admin"]
    pm = auth_users["pm"]
    viewer = auth_users["viewer"]
    stranger = auth_users["stranger"]

    # Admin passes on all
    assert require_viewer("DEMO", user=admin, session=session) == admin
    assert require_viewer("SECRET", user=admin, session=session) == admin

    # PM passes on DEMO and SECRET (viewer role on SECRET, pm role on DEMO)
    assert require_viewer("DEMO", user=pm, session=session) == pm
    assert require_viewer("SECRET", user=pm, session=session) == pm

    # Viewer passes on DEMO
    assert require_viewer("DEMO", user=viewer, session=session) == viewer

    # Viewer fails on SECRET
    with pytest.raises(HTTPException) as exc_info:
        require_viewer("SECRET", user=viewer, session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied for project SECRET"

    # Stranger fails on DEMO
    with pytest.raises(HTTPException) as exc_info:
        require_viewer("DEMO", user=stranger, session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied for project DEMO"


def test_require_project_role_callable(session, auth_users, sample_projects):
    dep = require_project_role("DEMO", {"pm"})
    # Positional invocation
    assert dep(auth_users["pm"], session) == auth_users["pm"]
    # Keyword invocation
    assert dep(user=auth_users["admin"], session=session) == auth_users["admin"]

    with pytest.raises(HTTPException) as exc_info:
        dep(user=auth_users["viewer"], session=session)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied for project DEMO"


def test_fastapi_endpoint_rbac_dependencies(client, auth_users, sample_projects, settings):
    # Dynamically attach test endpoints to verify FastAPI dependency injection
    app: FastAPI = client.app

    dep_pm = require_pm("DEMO")
    dep_viewer = require_viewer("DEMO")

    @app.get("/test-rbac/pm/{proj}")
    def pm_endpoint(proj: str, user: User = Depends(dep_pm)):
        return {"status": "ok", "user": user.email}

    @app.get("/test-rbac/viewer/{proj}")
    def viewer_endpoint(proj: str, user: User = Depends(dep_viewer)):
        return {"status": "ok", "user": user.email}

    # 1. Unauthenticated -> 401
    client.cookies.clear()
    assert client.get("/test-rbac/pm/DEMO").status_code == 401
    assert client.get("/test-rbac/viewer/DEMO").status_code == 401

    # 2. Viewer on PM endpoint -> 403
    _login(client, auth_users["viewer"], settings)
    resp = client.get("/test-rbac/pm/DEMO")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "PM role required for project DEMO"

    # 3. Viewer on Viewer endpoint -> 200
    resp = client.get("/test-rbac/viewer/DEMO")
    assert resp.status_code == 200
    assert resp.json()["user"] == "viewer@example.com"

    # 4. PM on PM endpoint -> 200
    _login(client, auth_users["pm"], settings)
    resp = client.get("/test-rbac/pm/DEMO")
    assert resp.status_code == 200
    assert resp.json()["user"] == "pm@example.com"

    # 5. Stranger on Viewer endpoint -> 403
    _login(client, auth_users["stranger"], settings)
    resp = client.get("/test-rbac/viewer/DEMO")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied for project DEMO"


# ---------------------------------------------------------------------------
# 3. GET /api/projects
# ---------------------------------------------------------------------------


def test_get_projects_unauthenticated(client):
    client.cookies.clear()
    resp = client.get("/api/projects")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_get_projects_admin_discovers_settings_and_db_projects(client, session, auth_users, sample_projects, settings):
    # settings.jira_projects has ["DEMO"]
    # sample_projects has DEMO and SECRET
    _login(client, auth_users["admin"], settings)
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()

    keys = [p["key"] for p in data]
    assert "DEMO" in keys
    assert "SECRET" in keys
    for p in data:
        assert p["role"] == "admin"
        assert "stats" in p
        assert p["stats"]["total_issues"] == 0


def test_get_projects_admin_auto_seeds_missing_settings_project(client, session, auth_users, settings):
    # Set jira_projects to include a brand new key NEWPROJ
    settings.jira_projects = ["DEMO", "NEWPROJ"]
    _login(client, auth_users["admin"], settings)

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    keys = [p["key"] for p in data]
    assert "NEWPROJ" in keys

    # Verify NEWPROJ was saved to DB with tracked=True
    p_row = session.get(Project, "NEWPROJ")
    assert p_row is not None
    assert p_row.tracked is True


def test_get_projects_regular_user_filtered(client, auth_users, sample_projects, settings):
    # PM user is assigned to DEMO (pm) and SECRET (viewer)
    _login(client, auth_users["pm"], settings)
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    by_key = {p["key"]: p for p in data}
    assert set(by_key.keys()) == {"DEMO", "SECRET"}
    assert by_key["DEMO"]["role"] == "pm"
    assert by_key["SECRET"]["role"] == "viewer"

    # Viewer user is only assigned to DEMO (viewer)
    _login(client, auth_users["viewer"], settings)
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["key"] == "DEMO"
    assert data[0]["role"] == "viewer"

    # Stranger user has no assignments
    _login(client, auth_users["stranger"], settings)
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_projects_stats_calculation(client, session, auth_users, sample_projects, settings):
    now = datetime.now(UTC)

    # Project DEMO issues
    i1 = Issue(key="DEMO-1", project_key="DEMO", summary="High risk blocked", deleted_at=None)
    i2 = Issue(key="DEMO-2", project_key="DEMO", summary="Med risk not blocked", deleted_at=None)
    i3 = Issue(key="DEMO-3", project_key="DEMO", summary="Low risk not blocked", deleted_at=None)
    i4 = Issue(key="DEMO-4", project_key="DEMO", summary="No risk state", deleted_at=None)
    i5_deleted = Issue(key="DEMO-5", project_key="DEMO", summary="Deleted high risk", deleted_at=now)

    # Project OTHER issue (should not count for DEMO)
    i_other = Issue(key="SECRET-1", project_key="SECRET", summary="Other project high risk", deleted_at=None)

    session.add_all([i1, i2, i3, i4, i5_deleted, i_other])
    session.commit()

    r1 = RiskState(issue_key="DEMO-1", level="HIGH", blocked=True)
    r2 = RiskState(issue_key="DEMO-2", level="MED", blocked=False)
    r3 = RiskState(issue_key="DEMO-3", level="LOW", blocked=False)
    r5_deleted = RiskState(issue_key="DEMO-5", level="HIGH", blocked=True)
    r_other = RiskState(issue_key="SECRET-1", level="HIGH", blocked=True)

    session.add_all([r1, r2, r3, r5_deleted, r_other])
    session.commit()

    _login(client, auth_users["admin"], settings)
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    by_key = {p["key"]: p for p in resp.json()}

    demo_stats = by_key["DEMO"]["stats"]
    assert demo_stats["total_issues"] == 4  # DEMO-1, 2, 3, 4 (excluding DEMO-5)
    assert demo_stats["high_risk_issues"] == 1  # DEMO-1
    assert demo_stats["med_risk_issues"] == 1  # DEMO-2
    assert demo_stats["blocked_issues"] == 1  # DEMO-1

    secret_stats = by_key["SECRET"]["stats"]
    assert secret_stats["total_issues"] == 1  # SECRET-1
    assert secret_stats["high_risk_issues"] == 1
    assert secret_stats["med_risk_issues"] == 0
    assert secret_stats["blocked_issues"] == 1


# ---------------------------------------------------------------------------
# 4. POST /api/admin/projects/{key}/toggle-tracking
# ---------------------------------------------------------------------------


def test_toggle_tracking_unauthenticated(client):
    client.cookies.clear()
    resp = client.post("/api/admin/projects/DEMO/toggle-tracking")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_toggle_tracking_forbidden_for_regular_user(client, auth_users, sample_projects, settings):
    _login(client, auth_users["pm"], settings)
    resp = client.post("/api/admin/projects/DEMO/toggle-tracking")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin privileges required"


def test_toggle_tracking_admin_success(client, session, auth_users, sample_projects, settings):
    _login(client, auth_users["admin"], settings)

    # 1. Existing tracked project DEMO (tracked=True) -> becomes tracked=False
    resp = client.post("/api/admin/projects/DEMO/toggle-tracking")
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "DEMO"
    assert data["tracked"] is False

    # Verify DB
    session.expire_all()
    p_demo = session.get(Project, "DEMO")
    assert p_demo.tracked is False

    # 2. Toggle again -> becomes tracked=True
    resp2 = client.post("/api/admin/projects/DEMO/toggle-tracking")
    assert resp2.status_code == 200
    assert resp2.json()["tracked"] is True

    # 3. Toggle a non-existent project BRANDNEW (created as tracked=True then toggled to False)
    resp3 = client.post("/api/admin/projects/BRANDNEW/toggle-tracking")
    assert resp3.status_code == 200
    assert resp3.json()["key"] == "BRANDNEW"
    assert resp3.json()["tracked"] is False

    # Toggle BRANDNEW again -> True
    resp4 = client.post("/api/admin/projects/BRANDNEW/toggle-tracking")
    assert resp4.status_code == 200
    assert resp4.json()["tracked"] is True
