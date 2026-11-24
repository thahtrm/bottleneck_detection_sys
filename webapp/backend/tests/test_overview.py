"""P0 Progress Attribution overview collector + API."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from erw.auth import create_session_token, hash_password
from erw.models import Change, Issue, IssueSprint, Link, Project, ProjectMember, RiskState, Sprint, User
from erw.pipeline.overview import collect_overview_snapshot, render_overview_markdown
from erw.settings import Settings


@pytest.fixture
def auth_users(session):
    users = {
        "pm": User(
            email="pm@example.com",
            name="PM",
            password_hash=hash_password("x"),
            is_admin=False,
            created_at=datetime.now(UTC),
        ),
        "viewer": User(
            email="viewer@example.com",
            name="Viewer",
            password_hash=hash_password("x"),
            is_admin=False,
            created_at=datetime.now(UTC),
        ),
        "stranger": User(
            email="stranger@example.com",
            name="Stranger",
            password_hash=hash_password("x"),
            is_admin=False,
            created_at=datetime.now(UTC),
        ),
    }
    session.add_all(users.values())
    session.commit()
    for u in users.values():
        session.refresh(u)
    return users


@pytest.fixture
def demo_world(session, auth_users):
    now = datetime(2026, 11, 24, 11, 0, tzinfo=UTC)
    session.add(Project(key="DEMO", name="Demo Project", tracked=True))
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=auth_users["pm"].id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=auth_users["viewer"].id, role="viewer"),
        ]
    )
    alice = "Alice"
    bob = "Bob"
    rows = [
        Issue(
            key="DEMO-1",
            project_key="DEMO",
            summary="Blocked leaf",
            status="To Do",
            status_category="new",
            assignee_name=alice,
            assignee_id="u1",
            created_at=now - timedelta(days=10),
            updated_at=now,
            duedate=date(2026, 11, 20),
        ),
        Issue(
            key="DEMO-2",
            project_key="DEMO",
            summary="Blocks two",
            status="In Progress",
            status_category="indeterminate",
            assignee_name=alice,
            assignee_id="u1",
            created_at=now - timedelta(days=8),
            updated_at=now,
        ),
        Issue(
            key="DEMO-3",
            project_key="DEMO",
            summary="Downstream of DEMO-2",
            status="In Progress",
            status_category="indeterminate",
            assignee_name=bob,
            assignee_id="u2",
            created_at=now - timedelta(days=5),
            updated_at=now,
        ),
        Issue(
            key="DEMO-4",
            project_key="DEMO",
            summary="Done item",
            status="Done",
            status_category="done",
            assignee_name=bob,
            assignee_id="u2",
            created_at=now - timedelta(days=20),
            resolved_at=now - timedelta(days=1),
            updated_at=now,
        ),
        Issue(
            key="DEMO-5",
            project_key="DEMO",
            summary="Stuck review",
            status="In Review",
            status_category="indeterminate",
            assignee_name=alice,
            assignee_id="u1",
            created_at=now - timedelta(days=12),
            updated_at=now,
        ),
    ]
    risks = [
        RiskState(issue_key="DEMO-1", level="HIGH", delay_value=0.82, blocked=True, updated_at=now),
        RiskState(issue_key="DEMO-2", level="MED", delay_value=0.55, blocked=False, updated_at=now),
        RiskState(issue_key="DEMO-3", level="HIGH", delay_value=0.71, blocked=False, updated_at=now),
        RiskState(issue_key="DEMO-5", level="MED", delay_value=0.40, blocked=False, updated_at=now),
    ]
    session.add_all(rows + risks)
    session.flush()
    # DEMO-2 blocks DEMO-1 and DEMO-3 (direction 1 = outward blocks)
    session.add_all(
        [
            Link(source_key="DEMO-2", target_key="DEMO-1", type_std="Block", direction="1"),
            Link(source_key="DEMO-2", target_key="DEMO-3", type_std="Block", direction="1"),
            Change(
                issue_key="DEMO-5",
                change_id="c1",
                idx=0,
                at=now - timedelta(days=6),
                field="status",
                to_str="In Review",
            ),
            Sprint(id=42, name="Sprint 42", state="active", start_at=now - timedelta(days=7), end_at=now + timedelta(days=7)),
        ]
    )
    session.flush()
    session.add_all(
        [
            IssueSprint(issue_key="DEMO-1", sprint_id=42),
            IssueSprint(issue_key="DEMO-2", sprint_id=42),
            IssueSprint(issue_key="DEMO-3", sprint_id=42),
            IssueSprint(issue_key="DEMO-4", sprint_id=42),
            IssueSprint(issue_key="DEMO-5", sprint_id=42),
        ]
    )
    session.commit()
    return {"now": now}


def login(client, user: User, settings: Settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


def test_collect_overview_actors_and_kpi(session, settings, demo_world):
    snap = collect_overview_snapshot(session, "DEMO", demo_world["now"], settings)
    assert snap.project == "DEMO"
    assert snap.kpi["open"] == 4
    assert snap.kpi["high"] == 2
    assert snap.kpi["blocked"] == 1
    assert snap.kpi["overdue"] == 1
    assert snap.kpi["sprint_committed"] == 5
    assert snap.kpi["sprint_done"] == 1
    assert snap.shap_available is False

    blockers = {a["id"]: a for a in snap.actors_by_kind["blocker"]}
    assert "DEMO-2" in blockers
    assert blockers["DEMO-2"]["affected_count"] == 2
    assert blockers["DEMO-2"]["impact"] > 2.0

    people = {a["id"]: a for a in snap.actors_by_kind["person"]}
    assert "Alice" in people
    assert people["Alice"]["affected_count"] == 3

    statuses = {a["id"]: a for a in snap.actors_by_kind["status"]}
    assert "In Review" in statuses
    assert statuses["In Review"]["related_risk"]["median_days_in_status"] >= 5.0

    keys = [i["key"] for i in snap.issues]
    assert keys[0] in {"DEMO-1", "DEMO-3"}  # HIGH first
    assert "DEMO-1" in snap.explain
    factors = {f["kind"] for f in snap.explain["DEMO-1"]["structural_factors"]}
    assert "blocked_by" in factors
    assert "dwell" in factors
    assert snap.explain["DEMO-1"]["shap"] is None

    md = render_overview_markdown(snap)
    assert "Progress Attribution" in md
    assert "DEMO-2" in md
    assert "KPI" in md


def test_overview_api_ok_and_forbidden(client, auth_users, settings, demo_world):
    resp = client.get("/api/projects/DEMO/overview")
    assert resp.status_code == 401

    login(client, auth_users["stranger"], settings)
    assert client.get("/api/projects/DEMO/overview").status_code == 403

    login(client, auth_users["viewer"], settings)
    ok = client.get("/api/projects/DEMO/overview")
    assert ok.status_code == 200
    body = ok.json()
    assert body["project"] == "DEMO"
    assert body["kpi"]["open"] == 4
    assert body["shap_available"] is False
    assert isinstance(body["actors"], list)
    assert isinstance(body["issues"], list)

    md = client.get("/api/projects/DEMO/overview/export?format=md")
    assert md.status_code == 200
    assert "text/markdown" in md.headers["content-type"]
    assert "Tổng quan" in md.text or "Progress Attribution" in md.text
    assert "attachment" in md.headers.get("content-disposition", "")
