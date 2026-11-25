from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from erw import jobs
from erw.auth import (
    get_user_project_role,
    hash_password,
    normalize_project_role,
    require_authenticated_user,
    require_developer,
    require_pm,
    require_viewer,
)
from erw.db import SessionLocal, init_db, make_engine, utcnow
from erw.integrations.jira import JiraClient
from erw.integrations.local_jira import LocalJiraClient, LocalJiraService, make_jira_client
from erw.main import create_app
from erw.models import (
    Action,
    Change,
    ChatAgentRun,
    ChatMemory,
    ChatMessage,
    Component,
    Issue,
    IssueVote,
    IssueWatcher,
    Project,
    ProjectMember,
    ReportFile,
    ReportSlot,
    RiskState,
    User,
)
from erw.settings import Settings


@pytest.fixture
def local_settings():
    return Settings(
        _env_file=None,
        db_url="sqlite://",
        jira_base_url="",
        jira_projects=["DEMO"],
        slack_webhook_url="",
    )


@pytest.fixture
def local_engine(local_settings):
    eng = make_engine(local_settings.db_url)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def local_session(local_engine):
    with SessionLocal(bind=local_engine) as s:
        yield s


@pytest.fixture
def local_client(local_settings, local_engine):
    with TestClient(
        create_app(
            local_settings,
            engine=local_engine,
            catch_up_on_startup=False,
            start_scheduler_on_startup=False,
        )
    ) as c:
        yield c


def _seed_local_users(session):
    now = utcnow()
    admin = User(
        email="admin@local.test",
        name="Admin User",
        password_hash=hash_password("pass"),
        is_admin=True,
        account_id="acc-admin",
        job_title="Engineering Lead",
        department="Platform",
        created_at=now,
    )
    pm = User(
        email="pm@local.test",
        name="PM User",
        password_hash=hash_password("pass"),
        is_admin=False,
        account_id="acc-pm",
        job_title="Product Manager",
        department="Product",
        created_at=now,
    )
    dev = User(
        email="dev@local.test",
        name="Dev User",
        password_hash=hash_password("pass"),
        is_admin=False,
        account_id="acc-dev",
        job_title="Backend Engineer",
        department="Core",
        created_at=now,
    )
    viewer = User(
        email="viewer@local.test",
        name="Viewer User",
        password_hash=hash_password("pass"),
        is_admin=False,
        account_id="acc-viewer",
        created_at=now,
    )
    inactive = User(
        email="inactive@local.test",
        name="Inactive User",
        password_hash=hash_password("pass"),
        is_admin=False,
        is_active=False,
        account_id="acc-inactive",
        created_at=now,
    )
    session.add_all([admin, pm, dev, viewer, inactive])
    session.add(Project(key="DEMO", name="Demo", tracked=True))
    session.flush()
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=dev.id, role="developer"),
            ProjectMember(project_key="DEMO", user_id=viewer.id, role="viewer"),
        ]
    )
    session.commit()
    return {"admin": admin, "pm": pm, "dev": dev, "viewer": viewer, "inactive": inactive}


# ---------------------------------------------------------------------------
# Dual-Mode Config & Factory Routing
# ---------------------------------------------------------------------------


def test_settings_jira_mode_resolution_and_factories(monkeypatch):
    s_default = Settings(_env_file=None)
    assert s_default.jira_mode == "local"
    assert s_default.attachments_dir == "var/attachments"
    assert isinstance(make_jira_client(s_default), LocalJiraClient)

    s_cloud = Settings(_env_file=None, jira_base_url="https://example.atlassian.net")
    assert s_cloud.jira_mode == "jira_cloud"
    assert isinstance(make_jira_client(s_cloud), JiraClient)
    # Mutating jira_base_url mid-test preserves jira_cloud mode (keeps 502 behavior)
    s_cloud.jira_base_url = ""
    assert s_cloud.jira_mode == "jira_cloud"
    assert isinstance(make_jira_client(s_cloud), JiraClient)

    s_override = Settings(_env_file=None, jira_base_url="https://example.atlassian.net", jira_mode="local")
    assert s_override.jira_mode == "local"
    assert isinstance(make_jira_client(s_override), LocalJiraClient)

    # jobs.get_client respects jobs.set_client without overwriting _client
    jobs.configure(s_default, make_engine("sqlite://"))
    jobs.set_client(None)
    c1 = jobs.get_client()
    assert isinstance(c1, LocalJiraClient)
    assert jobs._client is None
    sentinel = object()
    jobs.set_client(sentinel)
    assert jobs.get_client() is sentinel
    jobs.set_client(None)


def test_startup_catch_up_guarded_by_jira_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs.executor, "submit", lambda fn, *a, **kw: calls.append(fn))

    s_local = Settings(_env_file=None, db_url="sqlite://", jira_base_url="https://x.atlassian.net", jira_mode="local")
    eng_local = make_engine(s_local.db_url)
    with TestClient(create_app(s_local, engine=eng_local, catch_up_on_startup=True, start_scheduler_on_startup=False)):
        pass
    assert calls == []
    eng_local.dispose()

    s_cloud = Settings(_env_file=None, db_url="sqlite://", jira_base_url="https://x.atlassian.net")
    eng_cloud = make_engine(s_cloud.db_url)
    with TestClient(create_app(s_cloud, engine=eng_cloud, catch_up_on_startup=True, start_scheduler_on_startup=False)):
        pass
    assert calls == [jobs.run_catch_up]
    eng_cloud.dispose()


# ---------------------------------------------------------------------------
# Auth, UserResponse, AdminSettingsResponse & Inactive Guard
# ---------------------------------------------------------------------------


def test_inactive_user_rejected_by_require_authenticated_user():
    inactive = User(
        id=99,
        email="off@example.com",
        name="Off",
        password_hash="h",
        is_active=False,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(HTTPException) as exc:
        require_authenticated_user(inactive)
    assert exc.value.status_code == 401


def test_auth_responses_and_admin_settings_include_jira_mode(local_client, local_session):
    users = _seed_local_users(local_session)
    resp = local_client.post("/api/auth/login", json={"email": "admin@local.test", "password": "pass"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["jira_mode"] == "local"
    assert data["account_id"] == "acc-admin"
    assert data["job_title"] == "Engineering Lead"
    assert data["department"] == "Platform"
    assert data["timezone"] == "Asia/Ho_Chi_Minh"
    assert data["avatar_color"].startswith("#")

    me_resp = local_client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json() == data

    settings_resp = local_client.get("/api/admin/settings")
    assert settings_resp.status_code == 200
    assert settings_resp.json()["jira_mode"] == "local"

    # Inactive user cannot login
    bad = local_client.post("/api/auth/login", json={"email": users["inactive"].email, "password": "pass"})
    assert bad.status_code == 401


# ---------------------------------------------------------------------------
# Admin User CRUD + DELETE (Guards, Unassignment, Changelog, FK Cleanup)
# ---------------------------------------------------------------------------


def test_admin_user_crud_and_delete_cleanup(local_client, local_session, local_settings):
    users = _seed_local_users(local_session)
    local_client.post("/api/auth/login", json={"email": "admin@local.test", "password": "pass"})

    # Create with explicit password + profile fields
    create_resp = local_client.post(
        "/api/admin/users",
        json={
            "email": "newdev@local.test",
            "name": "New Dev",
            "password": "CustomPassword!1",
            "account_id": "acc-newdev",
            "job_title": "QA Engineer",
            "department": "Quality",
            "timezone": "UTC",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["generated_password"] is None
    assert created["user"]["account_id"] == "acc-newdev"
    assert created["user"]["job_title"] == "QA Engineer"
    assert created["user"]["timezone"] == "UTC"

    # Duplicate account_id -> 409
    dup = local_client.post(
        "/api/admin/users",
        json={"email": "other@local.test", "name": "Other", "account_id": "acc-newdev"},
    )
    assert dup.status_code == 409

    # Login with explicit password works
    assert local_client.post("/api/auth/login", json={"email": "newdev@local.test", "password": "CustomPassword!1"}).status_code == 200

    # Switch back to admin
    local_client.post("/api/auth/login", json={"email": "admin@local.test", "password": "pass"})

    # Patch profile + explicit password conflict
    uid = created["user"]["id"]
    bad_patch = local_client.patch(f"/api/admin/users/{uid}", json={"password": "x", "reset_password": True})
    assert bad_patch.status_code == 400

    patch_resp = local_client.patch(
        f"/api/admin/users/{uid}",
        json={"job_title": "Senior QA", "department": "Release"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["user"]["job_title"] == "Senior QA"

    # Self-delete guard & last-active-admin guard
    self_del = local_client.delete(f"/api/admin/users/{users['admin'].id}")
    assert self_del.status_code == 400

    # Create another admin deactivated; deleting active admin (if tested via second admin) - test last active admin
    second_admin = User(email="a2@local.test", name="A2", password_hash=hash_password("p"), is_admin=True, is_active=False, created_at=utcnow())
    local_session.add(second_admin)
    local_session.commit()
    assert local_client.delete(f"/api/admin/users/{users['admin'].id}").status_code == 400

    # Give dev user issues (active + deleted) and every FK reference
    dev = users["dev"]
    active_issue = LocalJiraService.create_issue(
        local_session,
        project_key="DEMO",
        summary="Owned by dev",
        assignee=dev,
        actor=users["pm"],
        settings=local_settings,
    )
    deleted_issue = LocalJiraService.create_issue(
        local_session,
        project_key="DEMO",
        summary="Deleted owned by dev",
        assignee=dev,
        actor=users["pm"],
        settings=local_settings,
    )
    deleted_issue.deleted_at = utcnow()
    proj = local_session.get(Project, "DEMO")
    proj.lead_user_id = dev.id
    comp = Component(project_key="DEMO", name="Auth", lead_user_id=dev.id)
    local_session.add(comp)
    act = Action(issue_key=active_issue.key, items=[], status="applied", confirmed_by=dev.id, created_at=utcnow())
    local_session.add(act)
    local_session.add(IssueWatcher(issue_key=active_issue.key, user_id=dev.id, created_at=utcnow()))
    local_session.add(IssueVote(issue_key=active_issue.key, user_id=dev.id, created_at=utcnow()))
    msg = ChatMessage(
        user_id=dev.id,
        project_key="DEMO",
        kind="user",
        body="hi",
        recommendation_status="skipped",
        created_at=utcnow(),
    )
    local_session.add(msg)
    local_session.flush()
    local_session.add(ChatAgentRun(message_id=msg.id, status="skipped", created_at=utcnow()))
    local_session.add(
        ReportFile(
            user_id=dev.id,
            project_key="DEMO",
            message_id=msg.id,
            slot_hhmm="0800",
            report_date="2026-11-25",
            rel_path="DEMO/r.md",
            created_at=utcnow(),
        )
    )
    local_session.add(ReportSlot(user_id=dev.id, time_hhmm="08:00"))
    local_session.add(
        ChatMemory(
            user_id=dev.id,
            project_key="DEMO",
            kind="note",
            text="note",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    local_session.commit()

    dev_id = dev.id
    del_resp = local_client.delete(f"/api/admin/users/{dev_id}")
    assert del_resp.status_code == 204

    local_session.expire_all()
    assert local_session.get(User, dev_id) is None
    refreshed_active = local_session.get(Issue, active_issue.key)
    assert refreshed_active.assignee_id is None
    assert refreshed_active.assignee_name is None
    assert refreshed_active.raw["fields"]["assignee"] is None
    assert local_session.get(Issue, deleted_issue.key).assignee_id is None
    assert local_session.get(Project, "DEMO").lead_user_id is None
    assert local_session.get(Component, comp.id).lead_user_id is None
    assert local_session.get(Action, act.id).confirmed_by is None
    assert local_session.get(RiskState, active_issue.key) is not None
    ch = local_session.scalars(
        select(Change).where(Change.issue_key == active_issue.key, Change.field == "assignee")
    ).all()
    assert len(ch) == 1
    assert ch[0].from_val == "acc-dev" and ch[0].to_val is None


# ---------------------------------------------------------------------------
# Two-Tier RBAC, Assignable Users Picker & Quick Switch
# ---------------------------------------------------------------------------


def test_two_tier_rbac_developer_and_member_normalization(local_client, local_session, local_settings):
    users = _seed_local_users(local_session)
    issue = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Task", actor=users["pm"], settings=local_settings
    )
    local_session.commit()

    assert normalize_project_role("member") == "developer"
    assert normalize_project_role("pm") == "pm"

    # Legacy "member" row in DB normalizes to "developer"
    legacy = User(email="legacy@local.test", name="Legacy", password_hash=hash_password("pass"), created_at=utcnow())
    local_session.add(legacy)
    local_session.flush()
    local_session.add(ProjectMember(project_key="DEMO", user_id=legacy.id, role="member"))
    local_session.commit()
    assert get_user_project_role(local_session, legacy, "DEMO") == "developer"
    assert require_viewer("DEMO", user=legacy, session=local_session) is legacy
    assert require_developer("DEMO", user=legacy, session=local_session) is legacy
    with pytest.raises(HTTPException) as exc_pm:
        require_pm("DEMO", user=legacy, session=local_session)
    assert exc_pm.value.status_code == 403

    # Developer can GET transitions and list chat reports, but cannot propose actions, dismiss risk, or manage members
    local_client.post("/api/auth/login", json={"email": "dev@local.test", "password": "pass"})
    assert local_client.get(f"/api/issues/{issue.key}/transitions").status_code == 200
    assert local_client.get("/api/chat/reports?project=DEMO").status_code == 200
    assert local_client.post("/api/actions/propose", json={"issue_key": issue.key, "items": []}).status_code == 403
    assert local_client.post(f"/api/issues/{issue.key}/dismiss").status_code == 403
    assert local_client.post("/api/projects/DEMO/members", json={"email": "admin@local.test", "role": "viewer"}).status_code == 403

    # Viewer gets 403 on transitions
    local_client.post("/api/auth/login", json={"email": "viewer@local.test", "password": "pass"})
    assert local_client.get(f"/api/issues/{issue.key}/transitions").status_code == 403

    # PM can add member with role="member" -> normalized to "developer"; last-PM guard blocks demoting last PM
    local_client.post("/api/auth/login", json={"email": "pm@local.test", "password": "pass"})
    extra = User(email="extra@local.test", name="Extra", password_hash=hash_password("p"), created_at=utcnow())
    local_session.add(extra)
    local_session.commit()
    add_resp = local_client.post("/api/projects/DEMO/members", json={"email": "extra@local.test", "role": "member"})
    assert add_resp.status_code == 201
    assert add_resp.json()["role"] == "developer"

    demote_last_pm = local_client.patch(
        f"/api/projects/DEMO/members/{users['pm'].id}",
        json={"role": "developer"},
    )
    assert demote_last_pm.status_code == 400


def test_assignable_users_picker(local_client, local_session):
    _seed_local_users(local_session)
    outsider = User(email="outsider@local.test", name="Outsider", password_hash=hash_password("pass"), created_at=utcnow())
    local_session.add(outsider)
    local_session.commit()

    # Non-member cannot query picker
    local_client.post("/api/auth/login", json={"email": "outsider@local.test", "password": "pass"})
    assert local_client.get("/api/projects/DEMO/assignable-users").status_code == 403

    # Member sees active project members + active global admin, excludes inactive & outsider
    local_client.post("/api/auth/login", json={"email": "dev@local.test", "password": "pass"})
    resp = local_client.get("/api/projects/DEMO/assignable-users")
    assert resp.status_code == 200
    emails = {item["email"] for item in resp.json()}
    assert emails == {"admin@local.test", "pm@local.test", "dev@local.test", "viewer@local.test"}

    # Query filter by name/email/account_id
    q_resp = local_client.get("/api/projects/DEMO/assignable-users?q=acc-dev")
    assert q_resp.status_code == 200
    assert [u["email"] for u in q_resp.json()] == ["dev@local.test"]


def test_user_search_treats_like_wildcards_as_literals(local_client, local_session):
    _seed_local_users(local_session)
    now = utcnow()
    literal = User(
        email="literal@local.test",
        name="PM Alice 100%",
        password_hash=hash_password("pass"),
        account_id="acc_pm",
        created_at=now,
    )
    decoy = User(
        email="decoy@local.test",
        name="PM Alice 100X",
        password_hash=hash_password("pass"),
        account_id="accXpm",
        created_at=now,
    )
    local_session.add_all([literal, decoy])
    local_session.flush()
    local_session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=literal.id, role="viewer"),
            ProjectMember(project_key="DEMO", user_id=decoy.id, role="viewer"),
        ]
    )
    local_session.commit()

    local_client.post("/api/auth/login", json={"email": "dev@local.test", "password": "pass"})
    percent = local_client.get("/api/projects/DEMO/assignable-users", params={"q": "100%"})
    assert percent.status_code == 200
    assert [u["email"] for u in percent.json()] == ["literal@local.test"]
    underscore = local_client.get("/api/projects/DEMO/assignable-users", params={"q": "acc_pm"})
    assert underscore.status_code == 200
    assert [u["email"] for u in underscore.json()] == ["literal@local.test"]
    plain = local_client.get("/api/projects/DEMO/assignable-users", params={"q": "acc-dev"})
    assert plain.status_code == 200
    assert [u["email"] for u in plain.json()] == ["dev@local.test"]

    local_client.post("/api/auth/login", json={"email": "admin@local.test", "password": "pass"})
    admin_percent = local_client.get("/api/admin/users", params={"q": "100%"})
    assert admin_percent.status_code == 200
    assert [u["email"] for u in admin_percent.json()] == ["literal@local.test"]
    admin_underscore = local_client.get("/api/admin/users", params={"q": "acc_pm"})
    assert admin_underscore.status_code == 200
    assert [u["email"] for u in admin_underscore.json()] == ["literal@local.test"]


def test_demo_users_and_quick_switch_local_vs_cloud(local_client, local_session, client, session):
    users = _seed_local_users(local_session)
    cloud_pm = User(email="cloudpm@example.com", name="Cloud PM", password_hash=hash_password("p"), created_at=utcnow())
    session.add(cloud_pm)
    session.commit()

    # Cloud mode fixture (conftest client has jira_base_url set -> jira_cloud) returns 403
    assert client.get("/api/demo/users").status_code == 403
    assert client.post("/api/auth/quick-switch", json={"user_id": cloud_pm.id}).status_code == 403

    # Local mode returns active users only with project roles
    demo_resp = local_client.get("/api/demo/users")
    assert demo_resp.status_code == 200
    items = demo_resp.json()
    emails = [u["email"] for u in items]
    assert "inactive@local.test" not in emails
    assert set(emails) == {"admin@local.test", "pm@local.test", "dev@local.test", "viewer@local.test"}
    dev_item = next(u for u in items if u["email"] == "dev@local.test")
    assert dev_item["projects"] == [{"project_key": "DEMO", "role": "developer"}]

    # Unknown / inactive user errors
    assert local_client.post("/api/auth/quick-switch", json={"user_id": 99999}).status_code == 404
    assert local_client.post("/api/auth/quick-switch", json={"user_id": users["inactive"].id}).status_code == 400

    # Valid quick switch sets session cookie and updates /api/auth/me
    sw = local_client.post("/api/auth/quick-switch", json={"user_id": users["dev"].id})
    assert sw.status_code == 200
    assert sw.json()["email"] == "dev@local.test"
    assert sw.json()["jira_mode"] == "local"
    assert "erw_session" in local_client.cookies
    me = local_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dev@local.test"
