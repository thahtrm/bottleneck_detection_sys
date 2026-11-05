from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from erw.auth import create_session_token, hash_password
from erw.db import utcnow
from erw.models import Action, Issue, Project, ProjectMember, RiskState, User


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
def sample_project(session, auth_users):
    p_demo = Project(key="DEMO", name="Demo Project", tracked=True)
    session.add(p_demo)
    session.commit()

    m_pm = ProjectMember(project_key="DEMO", user_id=auth_users["pm"].id, role="pm")
    m_viewer = ProjectMember(project_key="DEMO", user_id=auth_users["viewer"].id, role="viewer")
    session.add_all([m_pm, m_viewer])
    session.commit()
    return p_demo


def login(client, user: User, settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


# ===========================================================================
# 1. GET /api/dashboard/stats
# ===========================================================================


def test_stats_unauthenticated(client):
    resp = client.get("/api/dashboard/stats")
    assert resp.status_code == 401


def test_stats_forbidden_project(client, auth_users, settings, sample_project):
    login(client, auth_users["stranger"], settings)
    resp = client.get("/api/dashboard/stats?project=DEMO")
    assert resp.status_code == 403


def test_stats_no_projects_for_regular_user(client, auth_users, settings, session):
    login(client, auth_users["stranger"], settings)
    resp = client.get("/api/dashboard/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] is None
    assert data["total_open_issues"] == 0
    assert data["high_risk_count"] == 0
    assert data["med_risk_count"] == 0
    assert data["increased_risk_24h_count"] == 0
    assert data["blocked_count"] == 0
    assert data["critical_count"] == 0
    assert data["resolved_recent_count"] == 0
    assert data["applied_actions_count"] == 0


def test_stats_metrics_calculation(client, auth_users, settings, sample_project, session):
    now = utcnow()

    # 1. Open HIGH risk, raised 2h ago (in 24h), critical, blocked
    i1 = Issue(key="DEMO-1", project_key="DEMO", summary="Issue 1", status_category="new", updated_at=now)
    r1 = RiskState(
        issue_key="DEMO-1",
        level="HIGH",
        level_raised_at=now - timedelta(hours=2),
        is_critical=True,
        blocked=True,
    )

    # 2. Open MED risk, raised 10h ago (in 24h), not critical, not blocked
    i2 = Issue(key="DEMO-2", project_key="DEMO", summary="Issue 2", status_category="indeterminate", updated_at=now)
    r2 = RiskState(
        issue_key="DEMO-2",
        level="MED",
        level_raised_at=now - timedelta(hours=10),
        is_critical=False,
        blocked=False,
    )

    # 3. Open MED risk, raised 48h ago (NOT in 24h)
    i3 = Issue(key="DEMO-3", project_key="DEMO", summary="Issue 3", status_category="indeterminate", updated_at=now)
    r3 = RiskState(
        issue_key="DEMO-3",
        level="MED",
        level_raised_at=now - timedelta(hours=48),
        is_critical=False,
        blocked=False,
    )

    # 4. Open LOW risk
    i4 = Issue(key="DEMO-4", project_key="DEMO", summary="Issue 4", status_category="new", updated_at=now)
    r4 = RiskState(issue_key="DEMO-4", level="LOW", level_raised_at=now - timedelta(hours=1))

    # 5. Open with NO RiskState row
    i5 = Issue(key="DEMO-5", project_key="DEMO", summary="Issue 5", status_category="new", updated_at=now)

    # 6. Done, resolved 2 days ago (in 7d), had HIGH risk
    i6 = Issue(
        key="DEMO-6",
        project_key="DEMO",
        summary="Issue 6",
        status_category="done",
        resolved_at=now - timedelta(days=2),
        updated_at=now,
    )
    r6 = RiskState(issue_key="DEMO-6", level="HIGH")

    # 7. Done, resolved 10 days ago (NOT in 7d)
    i7 = Issue(
        key="DEMO-7",
        project_key="DEMO",
        summary="Issue 7",
        status_category="done",
        resolved_at=now - timedelta(days=10),
        updated_at=now,
    )

    # 8. Soft-deleted issue, HIGH risk, blocked -> should be completely ignored
    i8 = Issue(
        key="DEMO-8",
        project_key="DEMO",
        summary="Issue 8",
        status_category="new",
        deleted_at=now - timedelta(hours=1),
        updated_at=now,
    )
    r8 = RiskState(issue_key="DEMO-8", level="HIGH", blocked=True, is_critical=True)

    session.add_all([i1, r1, i2, r2, i3, r3, i4, r4, i5, i6, r6, i7, i8, r8])
    session.commit()

    # Actions:
    # Action 1: applied 3 days ago on DEMO-1 -> counted
    a1 = Action(
        issue_key="DEMO-1",
        status="applied",
        created_at=now - timedelta(days=3),
    )
    # Action 2: applied 10 days ago on DEMO-1 -> not counted (> 7d)
    a2 = Action(
        issue_key="DEMO-1",
        status="applied",
        created_at=now - timedelta(days=10),
    )
    # Action 3: pending 1 day ago on DEMO-1 -> not counted (not applied)
    a3 = Action(
        issue_key="DEMO-1",
        status="pending",
        created_at=now - timedelta(days=1),
    )
    # Action 4: applied 1 day ago on soft-deleted DEMO-8 -> not counted
    a4 = Action(
        issue_key="DEMO-8",
        status="applied",
        created_at=now - timedelta(days=1),
    )
    session.add_all([a1, a2, a3, a4])
    session.commit()

    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/dashboard/stats?project=DEMO")
    assert resp.status_code == 200
    data = resp.json()

    assert data["project"] == "DEMO"
    assert data["total_open_issues"] == 5
    assert data["high_risk_count"] == 1
    assert data["med_risk_count"] == 2
    assert data["increased_risk_24h_count"] == 2
    assert data["blocked_count"] == 1
    assert data["critical_count"] == 1
    assert data["resolved_recent_count"] == 1
    assert data["applied_actions_count"] == 1


def test_stats_project_isolation_and_admin(client, auth_users, settings, sample_project, session):
    now = utcnow()
    p_other = Project(key="OTHER", name="Other Project", tracked=True)
    session.add(p_other)
    session.commit()

    # DEMO has 1 open HIGH issue
    i_demo = Issue(key="DEMO-10", project_key="DEMO", summary="Demo task", status_category="new", updated_at=now)
    r_demo = RiskState(issue_key="DEMO-10", level="HIGH")

    # OTHER has 2 open HIGH issues
    i_other1 = Issue(key="OTHER-1", project_key="OTHER", summary="Other 1", status_category="new", updated_at=now)
    r_other1 = RiskState(issue_key="OTHER-1", level="HIGH")
    i_other2 = Issue(key="OTHER-2", project_key="OTHER", summary="Other 2", status_category="new", updated_at=now)
    r_other2 = RiskState(issue_key="OTHER-2", level="HIGH")

    session.add_all([i_demo, r_demo, i_other1, r_other1, i_other2, r_other2])
    session.commit()

    # Regular viewer (member of DEMO only) queries /stats without project param:
    login(client, auth_users["viewer"], settings)
    resp_viewer = client.get("/api/dashboard/stats")
    assert resp_viewer.status_code == 200
    data_viewer = resp_viewer.json()
    assert data_viewer["project"] is None
    assert data_viewer["high_risk_count"] == 1
    assert data_viewer["total_open_issues"] == 1

    # Admin queries /stats without project param: sees all projects
    login(client, auth_users["admin"], settings)
    resp_admin = client.get("/api/dashboard/stats")
    assert resp_admin.status_code == 200
    data_admin = resp_admin.json()
    assert data_admin["project"] is None
    assert data_admin["high_risk_count"] == 3
    assert data_admin["total_open_issues"] == 3

    # Admin queries with project=OTHER:
    resp_admin_other = client.get("/api/dashboard/stats?project=OTHER")
    assert resp_admin_other.status_code == 200
    assert resp_admin_other.json()["project"] == "OTHER"
    assert resp_admin_other.json()["high_risk_count"] == 2


# ===========================================================================
# 2. GET /api/dashboard/issues
# ===========================================================================


def test_issues_unauthenticated(client):
    resp = client.get("/api/dashboard/issues")
    assert resp.status_code == 401


def test_issues_forbidden_project(client, auth_users, settings, sample_project):
    login(client, auth_users["stranger"], settings)
    resp = client.get("/api/dashboard/issues?project=DEMO")
    assert resp.status_code == 403


def test_issues_no_projects_for_regular_user(client, auth_users, settings, session):
    login(client, auth_users["stranger"], settings)
    resp = client.get("/api/dashboard/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_issues_filter_status_category(client, auth_users, settings, sample_project, session):
    now = utcnow()
    i_act = Issue(key="DEMO-ACT", project_key="DEMO", summary="Active issue", status_category="indeterminate", updated_at=now)
    i_done = Issue(key="DEMO-DONE", project_key="DEMO", summary="Done issue", status_category="done", updated_at=now)
    i_del = Issue(
        key="DEMO-DEL",
        project_key="DEMO",
        summary="Deleted issue",
        status_category="indeterminate",
        deleted_at=now,
        updated_at=now,
    )
    session.add_all([i_act, i_done, i_del])
    session.commit()

    login(client, auth_users["viewer"], settings)

    # 1. Default (active): excludes done and soft-deleted
    resp = client.get("/api/dashboard/issues?project=DEMO")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [it["key"] for it in data["items"]] == ["DEMO-ACT"]

    # 2. status_category=done: only done issues
    resp_done = client.get("/api/dashboard/issues?project=DEMO&status_category=done")
    assert resp_done.status_code == 200
    data_done = resp_done.json()
    assert data_done["total"] == 1
    assert [it["key"] for it in data_done["items"]] == ["DEMO-DONE"]

    # 3. status_category=all: both active and done, still excludes soft-deleted
    resp_all = client.get("/api/dashboard/issues?project=DEMO&status_category=all")
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["total"] == 2
    keys = {it["key"] for it in data_all["items"]}
    assert keys == {"DEMO-ACT", "DEMO-DONE"}


def test_issues_filter_level_blocked_critical_assignee(client, auth_users, settings, sample_project, session):
    now = utcnow()
    i1 = Issue(
        key="DEMO-1",
        project_key="DEMO",
        summary="Task 1",
        status_category="new",
        assignee_id="user_alice",
        updated_at=now,
    )
    r1 = RiskState(issue_key="DEMO-1", level="HIGH", blocked=True, is_critical=True)

    i2 = Issue(
        key="DEMO-2",
        project_key="DEMO",
        summary="Task 2",
        status_category="new",
        assignee_id="user_bob",
        updated_at=now,
    )
    r2 = RiskState(issue_key="DEMO-2", level="MED", blocked=False, is_critical=False)

    i3 = Issue(
        key="DEMO-3",
        project_key="DEMO",
        summary="Task 3",
        status_category="new",
        assignee_id="user_alice",
        updated_at=now,
    )
    r3 = RiskState(issue_key="DEMO-3", level="LOW", blocked=True, is_critical=False)

    session.add_all([i1, r1, i2, r2, i3, r3])
    session.commit()

    login(client, auth_users["viewer"], settings)

    # Filter level=HIGH
    resp = client.get("/api/dashboard/issues?project=DEMO&level=HIGH")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["key"] == "DEMO-1"

    # Filter blocked=true
    resp_blocked = client.get("/api/dashboard/issues?project=DEMO&blocked=true")
    assert resp_blocked.status_code == 200
    assert resp_blocked.json()["total"] == 2
    assert {it["key"] for it in resp_blocked.json()["items"]} == {"DEMO-1", "DEMO-3"}

    # Filter blocked=false
    resp_unblocked = client.get("/api/dashboard/issues?project=DEMO&blocked=false")
    assert resp_unblocked.status_code == 200
    assert resp_unblocked.json()["total"] == 1
    assert resp_unblocked.json()["items"][0]["key"] == "DEMO-2"

    # Filter is_critical=true
    resp_crit = client.get("/api/dashboard/issues?project=DEMO&is_critical=true")
    assert resp_crit.status_code == 200
    assert resp_crit.json()["total"] == 1
    assert resp_crit.json()["items"][0]["key"] == "DEMO-1"

    # Filter assignee_id=user_alice
    resp_assignee = client.get("/api/dashboard/issues?project=DEMO&assignee_id=user_alice")
    assert resp_assignee.status_code == 200
    assert resp_assignee.json()["total"] == 2
    assert {it["key"] for it in resp_assignee.json()["items"]} == {"DEMO-1", "DEMO-3"}


def test_issues_search_q(client, auth_users, settings, sample_project, session):
    now = utcnow()
    i1 = Issue(key="DEMO-10", project_key="DEMO", summary="Fix memory leak in parser", status_category="new", updated_at=now)
    i2 = Issue(key="DEMO-11", project_key="DEMO", summary="Database index migration", status_category="new", updated_at=now)
    i3 = Issue(key="BUG-99", project_key="DEMO", summary="Unhandled exception on startup", status_category="new", updated_at=now)

    session.add_all([i1, i2, i3])
    session.commit()

    login(client, auth_users["viewer"], settings)

    # Search in summary
    resp = client.get("/api/dashboard/issues?project=DEMO&q=memory")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["key"] == "DEMO-10"

    # Search in key
    resp_key = client.get("/api/dashboard/issues?project=DEMO&q=BUG-99")
    assert resp_key.status_code == 200
    assert resp_key.json()["total"] == 1
    assert resp_key.json()["items"][0]["key"] == "BUG-99"

    # Case-insensitive
    resp_ci = client.get("/api/dashboard/issues?project=DEMO&q=leak")
    assert resp_ci.status_code == 200
    assert resp_ci.json()["total"] == 1
    assert resp_ci.json()["items"][0]["key"] == "DEMO-10"


def test_issues_sort_by_risk(client, auth_users, settings, sample_project, session):
    now = utcnow()
    i_low = Issue(key="DEMO-LOW", project_key="DEMO", summary="Low risk", status_category="new", updated_at=now)
    r_low = RiskState(issue_key="DEMO-LOW", level="LOW")

    i_med = Issue(key="DEMO-MED", project_key="DEMO", summary="Med risk", status_category="new", updated_at=now)
    r_med = RiskState(issue_key="DEMO-MED", level="MED")

    i_high = Issue(key="DEMO-HIGH", project_key="DEMO", summary="High risk", status_category="new", updated_at=now)
    r_high = RiskState(issue_key="DEMO-HIGH", level="HIGH")

    i_none = Issue(key="DEMO-NONE", project_key="DEMO", summary="No risk row", status_category="new", updated_at=now)

    session.add_all([i_low, r_low, i_med, r_med, i_high, r_high, i_none])
    session.commit()

    login(client, auth_users["viewer"], settings)

    # 1. sort_by=risk, order=desc (default)
    resp_desc = client.get("/api/dashboard/issues?project=DEMO&sort_by=risk&order=desc")
    assert resp_desc.status_code == 200
    keys_desc = [it["key"] for it in resp_desc.json()["items"]]
    assert keys_desc[0] == "DEMO-HIGH"
    assert keys_desc[1] == "DEMO-MED"
    assert keys_desc[2] == "DEMO-LOW"
    assert keys_desc[3] == "DEMO-NONE"

    # 2. sort_by=risk, order=asc
    resp_asc = client.get("/api/dashboard/issues?project=DEMO&sort_by=risk&order=asc")
    assert resp_asc.status_code == 200
    keys_asc = [it["key"] for it in resp_asc.json()["items"]]
    assert keys_asc[-1] == "DEMO-HIGH"
    assert keys_asc[-2] == "DEMO-MED"


def test_issues_sort_by_deadline_and_updated(client, auth_users, settings, sample_project, session):
    now = utcnow()
    d1 = now + timedelta(days=1)
    d2 = now + timedelta(days=5)

    i1 = Issue(key="DEMO-1", project_key="DEMO", summary="Issue 1", status_category="new", updated_at=now - timedelta(hours=2))
    r1 = RiskState(issue_key="DEMO-1", deadline_at=d2)

    i2 = Issue(key="DEMO-2", project_key="DEMO", summary="Issue 2", status_category="new", updated_at=now - timedelta(hours=1))
    r2 = RiskState(issue_key="DEMO-2", deadline_at=d1)

    i3 = Issue(key="DEMO-3", project_key="DEMO", summary="Issue 3", status_category="new", updated_at=now)
    r3 = RiskState(issue_key="DEMO-3", deadline_at=None)

    session.add_all([i1, r1, i2, r2, i3, r3])
    session.commit()

    login(client, auth_users["viewer"], settings)

    # Sort deadline asc (earliest first, nulls last)
    resp_dl = client.get("/api/dashboard/issues?project=DEMO&sort_by=deadline&order=asc")
    assert resp_dl.status_code == 200
    keys_dl = [it["key"] for it in resp_dl.json()["items"]]
    assert keys_dl == ["DEMO-2", "DEMO-1", "DEMO-3"]

    # Sort updated desc (most recent first)
    resp_up = client.get("/api/dashboard/issues?project=DEMO&sort_by=updated&order=desc")
    assert resp_up.status_code == 200
    keys_up = [it["key"] for it in resp_up.json()["items"]]
    assert keys_up == ["DEMO-3", "DEMO-2", "DEMO-1"]


def test_issues_pagination_and_item_structure(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issues = []
    risks = []
    for i in range(15):
        key = f"DEMO-{i:02d}"
        iss = Issue(
            key=key,
            project_key="DEMO",
            summary=f"Task {i}",
            status_category="new",
            updated_at=now - timedelta(minutes=i),
        )
        rs = RiskState(
            issue_key=key,
            level="HIGH" if i < 5 else "LOW",
            delay_value=0.5 if i < 5 else 0.1,
            is_critical=(i == 0),
            blocked=(i == 1),
        )
        issues.append(iss)
        risks.append(rs)

    session.add_all(issues + risks)
    session.commit()

    login(client, auth_users["viewer"], settings)

    # Page 1: limit 5, offset 0
    resp_p1 = client.get("/api/dashboard/issues?project=DEMO&limit=5&offset=0")
    assert resp_p1.status_code == 200
    d1 = resp_p1.json()
    assert d1["total"] == 15
    assert d1["limit"] == 5
    assert d1["offset"] == 0
    assert len(d1["items"]) == 5

    # Check item structure and nested risk
    item0 = d1["items"][0]
    assert "key" in item0
    assert "project_key" in item0
    assert "summary" in item0
    assert "status_category" in item0
    assert "risk" in item0
    assert item0["risk"]["level"] == "HIGH"
    assert "delay_value" in item0["risk"]
    assert "is_critical" in item0["risk"]
    assert "blocked" in item0["risk"]

    # Page 2: limit 5, offset 5
    resp_p2 = client.get("/api/dashboard/issues?project=DEMO&limit=5&offset=5")
    assert resp_p2.status_code == 200
    d2 = resp_p2.json()
    assert d2["total"] == 15
    assert len(d2["items"]) == 5

    keys_p1 = {it["key"] for it in d1["items"]}
    keys_p2 = {it["key"] for it in d2["items"]}
    assert keys_p1.isdisjoint(keys_p2)

    # Page 4: offset 15 (beyond items)
    resp_p4 = client.get("/api/dashboard/issues?project=DEMO&limit=5&offset=15")
    assert resp_p4.status_code == 200
    d4 = resp_p4.json()
    assert d4["total"] == 15
    assert len(d4["items"]) == 0


def test_issues_admin_and_viewer_project_permissions(client, auth_users, settings, sample_project, session):
    now = utcnow()
    p_other = Project(key="OTHER", name="Other Project", tracked=True)
    session.add(p_other)
    session.commit()

    i_demo = Issue(key="DEMO-1", project_key="DEMO", summary="Demo task", status_category="new", updated_at=now)
    i_other = Issue(key="OTHER-1", project_key="OTHER", summary="Other task", status_category="new", updated_at=now)
    session.add_all([i_demo, i_other])
    session.commit()

    # Viewer (only DEMO) with no project param -> sees only DEMO-1
    login(client, auth_users["viewer"], settings)
    resp_viewer = client.get("/api/dashboard/issues")
    assert resp_viewer.status_code == 200
    assert resp_viewer.json()["total"] == 1
    assert resp_viewer.json()["items"][0]["key"] == "DEMO-1"

    # Admin with no project param -> sees DEMO-1 and OTHER-1
    login(client, auth_users["admin"], settings)
    resp_admin = client.get("/api/dashboard/issues")
    assert resp_admin.status_code == 200
    assert resp_admin.json()["total"] == 2
    keys_admin = {it["key"] for it in resp_admin.json()["items"]}
    assert keys_admin == {"DEMO-1", "OTHER-1"}
