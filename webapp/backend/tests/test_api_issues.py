from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
import respx

from erw.auth import create_session_token, hash_password
from erw.db import utcnow
from erw.models import Action, Change, Issue, Link, Project, ProjectMember, RiskState, Score, Suggestion, User


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
# 1. GET /api/issues/{key}
# ===========================================================================


def test_get_issue_unauthenticated(client):
    resp = client.get("/api/issues/DEMO-1")
    assert resp.status_code == 401


def test_get_issue_not_found(client, auth_users, settings, sample_project):
    login(client, auth_users["pm"], settings)
    resp = client.get("/api/issues/NONEXISTENT-99")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Issue not found"


def test_get_issue_forbidden_for_stranger(client, auth_users, settings, sample_project, session):
    issue = Issue(
        key="DEMO-1",
        project_key="DEMO",
        summary="Test task",
        status="Open",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(issue)
    session.commit()

    login(client, auth_users["stranger"], settings)
    resp = client.get("/api/issues/DEMO-1")
    assert resp.status_code == 403


def test_get_issue_detail_success(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(
        key="DEMO-1",
        project_key="DEMO",
        summary="Implement login feature",
        issuetype="Story",
        priority="High",
        priority_norm=0.8,
        status="In Progress",
        status_category="indeterminate",
        assignee_id="acc-123",
        assignee_name="Alice Dev",
        duedate=date(2026, 11, 20),
        story_points=5.0,
        created_at=now,
        updated_at=now,
        raw={"customfield_100": "custom"},
    )
    rs = RiskState(
        issue_key="DEMO-1",
        level="HIGH",
        prev_level="MED",
        level_raised_at=now,
        delay_value=0.85,
        crit_score=0.92,
        is_critical=True,
        blocked=True,
        deadline_type="sprint",
        deadline_at=now,
        deadline_label="Sprint 3",
        factors=[{"name": "delay", "score": 0.85}],
        last_alerted_level="MED",
        dismissed_at_level=None,
        updated_at=now,
    )
    score = Score(
        issue_key="DEMO-1",
        scorer="delay",
        as_of=now,
        value=0.85,
        level="HIGH",
        is_critical=True,
        deadline_type="sprint",
        deadline_at=now,
        factors=[{"name": "delay", "score": 0.85}],
        extra={"model": "v1"},
    )
    link1 = Link(source_key="DEMO-1", target_key="DEMO-2", type_std="Block", direction="outward")
    link2 = Link(source_key="DEMO-3", target_key="DEMO-1", type_std="Depend", direction="inward")
    change = Change(
        issue_key="DEMO-1",
        change_id="ch-101",
        idx=0,
        at=now,
        field="status",
        from_val="Open",
        to_val="In Progress",
        from_str="Open",
        to_str="In Progress",
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)

    suggestion = Suggestion(
        issue_key="DEMO-1",
        issue_updated_at=now,
        model="qwen3:1.7b",
        output={"summary": "Đề xuất dời deadline", "actions": []},
        valid=True,
        created_at=now,
    )
    session.add(suggestion)
    session.commit()
    session.refresh(suggestion)

    action = Action(
        issue_key="DEMO-1",
        suggestion_id=suggestion.id,
        items=[{"action_type": "adjust_deadline", "value": "2026-11-25"}],
        status="applied",
        confirmed_by=auth_users["pm"].id,
        result={"applied_items": 1},
        created_at=now,
    )
    session.add_all([rs, score, link1, link2, change, action])
    session.commit()

    # Access as viewer
    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/issues/DEMO-1")
    assert resp.status_code == 200
    data = resp.json()

    assert data["issue"]["key"] == "DEMO-1"
    assert data["issue"]["summary"] == "Implement login feature"
    assert data["issue"]["priority"] == "High"
    assert data["issue"]["duedate"] == "2026-11-20"
    assert data["issue"]["story_points"] == 5.0

    assert data["risk_state"]["level"] == "HIGH"
    assert data["risk_state"]["blocked"] is True
    assert data["risk_state"]["is_critical"] is True
    assert data["risk_state"]["dismissed_at_level"] is None

    assert len(data["scores"]) == 1
    assert data["scores"][0]["scorer"] == "delay"

    assert len(data["links"]) == 2
    keys = {(lnk["source_key"], lnk["target_key"]) for lnk in data["links"]}
    assert ("DEMO-1", "DEMO-2") in keys
    assert ("DEMO-3", "DEMO-1") in keys

    assert len(data["recent_changes"]) == 1
    assert data["recent_changes"][0]["field"] == "status"

    assert data["suggestion"]["model"] == "qwen3:1.7b"
    assert data["suggestion"]["valid"] is True

    assert len(data["recent_actions"]) == 1
    assert data["recent_actions"][0]["status"] == "applied"

    # Admin access also succeeds
    login(client, auth_users["admin"], settings)
    resp_admin = client.get("/api/issues/DEMO-1")
    assert resp_admin.status_code == 200


# ===========================================================================
# 2. GET /api/issues/{key}/suggestion
# ===========================================================================


def test_get_suggestion_unauthenticated(client):
    resp = client.get("/api/issues/DEMO-1/suggestion")
    assert resp.status_code == 401


def test_get_suggestion_not_found(client, auth_users, settings, sample_project):
    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/issues/NONEXISTENT-1/suggestion")
    assert resp.status_code == 404


def test_get_suggestion_forbidden_for_stranger(client, auth_users, settings, sample_project, session):
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow())
    session.add(issue)
    session.commit()

    login(client, auth_users["stranger"], settings)
    resp = client.get("/api/issues/DEMO-1/suggestion")
    assert resp.status_code == 403


def test_get_suggestion_pending_202_and_enqueues(client, auth_users, settings, sample_project, session, monkeypatch):
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow(), updated_at=utcnow())
    session.add(issue)
    session.commit()

    enqueued_keys = []

    def mock_enqueue(key, st):
        enqueued_keys.append(key)
        return True

    monkeypatch.setattr("erw.api.issues.enqueue_suggestion", mock_enqueue)

    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/issues/DEMO-1/suggestion")
    assert resp.status_code == 202
    assert resp.json() == {
        "status": "pending",
        "message": "Suggestion generation in progress",
    }
    assert enqueued_keys == ["DEMO-1"]


def test_get_suggestion_ready_200_when_cached(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now, updated_at=now)
    suggestion = Suggestion(
        issue_key="DEMO-1",
        issue_updated_at=now,
        model="qwen3:1.7b",
        output={
            "summary": "Tóm tắt xử lý",
            "explanation": "Giải thích",
            "factors_cited": ["deadline"],
            "actions": [{"action_type": "adjust_deadline", "value": "2026-11-30", "reason": "Trễ hạn"}],
        },
        valid=True,
        created_at=now,
    )
    session.add_all([issue, suggestion])
    session.commit()

    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/issues/DEMO-1/suggestion")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["model"] == "qwen3:1.7b"
    assert data["suggestion"]["summary"] == "Tóm tắt xử lý"
    assert len(data["suggestion"]["actions"]) == 1


def test_get_suggestion_pending_202_when_cached_is_invalid(
    client, auth_users, settings, sample_project, session, monkeypatch
):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now, updated_at=now)
    # Cached suggestion with valid=False
    invalid_sugg = Suggestion(
        issue_key="DEMO-1",
        issue_updated_at=now,
        model="qwen3:1.7b",
        output={"error": "Malformed response"},
        valid=False,
        created_at=now,
    )
    session.add_all([issue, invalid_sugg])
    session.commit()

    enqueued_keys = []
    monkeypatch.setattr("erw.api.issues.enqueue_suggestion", lambda key, st: enqueued_keys.append(key))

    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/issues/DEMO-1/suggestion")
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert enqueued_keys == ["DEMO-1"]


# ===========================================================================
# 3. POST /api/issues/{key}/dismiss
# ===========================================================================


def test_dismiss_risk_unauthenticated(client):
    resp = client.post("/api/issues/DEMO-1/dismiss")
    assert resp.status_code == 401


def test_dismiss_risk_not_found_issue(client, auth_users, settings, sample_project):
    login(client, auth_users["pm"], settings)
    resp = client.post("/api/issues/NONEXISTENT-1/dismiss")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Issue not found"


def test_dismiss_risk_forbidden_for_viewer(client, auth_users, settings, sample_project, session):
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow())
    session.add(issue)
    session.commit()

    login(client, auth_users["viewer"], settings)
    resp = client.post("/api/issues/DEMO-1/dismiss")
    assert resp.status_code == 403


def test_dismiss_risk_not_found_risk_state(client, auth_users, settings, sample_project, session):
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow())
    session.add(issue)
    session.commit()

    login(client, auth_users["pm"], settings)
    resp = client.post("/api/issues/DEMO-1/dismiss")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Risk state not found"


def test_dismiss_risk_success_by_pm(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    rs = RiskState(issue_key="DEMO-1", level="HIGH", dismissed_at_level=None, updated_at=now)
    session.add_all([issue, rs])
    session.commit()

    login(client, auth_users["pm"], settings)
    resp = client.post("/api/issues/DEMO-1/dismiss", json={"reason": "False alarm accepted by client"})
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "dismissed",
        "issue_key": "DEMO-1",
        "dismissed_at_level": "HIGH",
    }

    session.refresh(rs)
    assert rs.dismissed_at_level == "HIGH"


def test_dismiss_risk_success_by_admin(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    rs = RiskState(issue_key="DEMO-1", level="MED", dismissed_at_level=None, updated_at=now)
    session.add_all([issue, rs])
    session.commit()

    login(client, auth_users["admin"], settings)
    resp = client.post("/api/issues/DEMO-1/dismiss")
    assert resp.status_code == 200
    assert resp.json()["dismissed_at_level"] == "MED"

    session.refresh(rs)
    assert rs.dismissed_at_level == "MED"


# ===========================================================================
# 4. POST /api/actions/propose
# ===========================================================================


def test_propose_action_unauthenticated(client):
    resp = client.post("/api/actions/propose", json={"issue_key": "DEMO-1", "items": []})
    assert resp.status_code == 401


def test_propose_action_not_found(client, auth_users, settings, sample_project):
    login(client, auth_users["pm"], settings)
    resp = client.post("/api/actions/propose", json={"issue_key": "NONEXISTENT-1", "items": []})
    assert resp.status_code == 404


def test_propose_action_forbidden_for_viewer(client, auth_users, settings, sample_project, session):
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow())
    session.add(issue)
    session.commit()

    login(client, auth_users["viewer"], settings)
    resp = client.post("/api/actions/propose", json={"issue_key": "DEMO-1", "items": []})
    assert resp.status_code == 403


def test_propose_action_success_by_pm(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    sugg = Suggestion(
        issue_key="DEMO-1",
        issue_updated_at=now,
        model="qwen3:1.7b",
        output={"summary": "Plan"},
        valid=True,
        created_at=now,
    )
    session.add_all([issue, sugg])
    session.commit()

    login(client, auth_users["pm"], settings)
    payload = {
        "issue_key": "DEMO-1",
        "suggestion_id": sugg.id,
        "items": [
            {"action_type": "adjust_deadline", "value": "2026-11-30", "reason": "Slippage"},
            {"action_type": "add_comment", "value": "PM reviewing deadline", "reason": "Note"},
        ],
    }
    resp = client.post("/api/actions/propose", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["issue_key"] == "DEMO-1"
    assert data["status"] == "pending"
    assert len(data["items"]) == 2
    assert "action_id" in data

    # Verify DB
    action = session.get(Action, data["action_id"])
    assert action is not None
    assert action.issue_key == "DEMO-1"
    assert action.status == "pending"
    assert action.suggestion_id == sugg.id
    assert len(action.items) == 2


# ===========================================================================
# 5. POST /api/actions/{id}/confirm
# ===========================================================================


def test_confirm_action_unauthenticated(client):
    resp = client.post("/api/actions/1/confirm", json={"expected_updated": "2026-11-04T12:00:00Z"})
    assert resp.status_code == 401


def test_confirm_action_not_found(client, auth_users, settings, sample_project):
    login(client, auth_users["pm"], settings)
    resp = client.post("/api/actions/999/confirm", json={"expected_updated": "2026-11-04T12:00:00Z"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Action not found"


def test_confirm_action_invalid_timestamp(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    action = Action(issue_key="DEMO-1", items=[], status="pending", created_at=now)
    session.add_all([issue, action])
    session.commit()

    login(client, auth_users["pm"], settings)
    resp = client.post(f"/api/actions/{action.id}/confirm", json={"expected_updated": "invalid-timestamp"})
    assert resp.status_code == 400
    assert "timestamp format" in resp.json()["detail"]


@respx.mock
def test_confirm_action_missing_on_jira_is_404(client, auth_users, settings, sample_project, session):
    now = utcnow()
    action = Action(
        issue_key="DEMO-101",
        items=[{"action_type": "add_comment", "value": "note"}],
        status="pending",
        created_at=now,
    )
    session.add_all([Issue(key="DEMO-101", project_key="DEMO", summary="Local only", created_at=now), action])
    session.commit()
    base = settings.jira_base_url.rstrip("/")
    respx.get(f"{base}/rest/api/3/issue/DEMO-101", params={"fields": "updated"}).mock(
        return_value=httpx.Response(
            404,
            json={"errorMessages": ["Issue does not exist or you do not have permission to see it."], "errors": {}},
        )
    )

    login(client, auth_users["pm"], settings)
    resp = client.post(f"/api/actions/{action.id}/confirm", json={"expected_updated": "2026-11-04T12:00:00Z"})

    assert resp.status_code == 404
    assert "DEMO-101" in resp.json()["detail"]
    session.refresh(action)
    assert action.status == "pending"


def test_confirm_action_forbidden_for_viewer(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    action = Action(issue_key="DEMO-1", items=[], status="pending", created_at=now)
    session.add_all([issue, action])
    session.commit()

    login(client, auth_users["viewer"], settings)
    resp = client.post(f"/api/actions/{action.id}/confirm", json={"expected_updated": "2026-11-04T12:00:00Z"})
    assert resp.status_code == 403


@respx.mock
def test_confirm_action_conflict_409(client, auth_users, settings, sample_project, session):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    action = Action(
        issue_key="DEMO-1",
        items=[{"action_type": "adjust_deadline", "value": "2026-11-30"}],
        status="pending",
        created_at=now,
    )
    session.add_all([issue, action])
    session.commit()

    base = settings.jira_base_url.rstrip("/")
    # Jira says issue was updated at 12:05:00
    respx.get(f"{base}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T12:05:00.000Z"}})
    )

    login(client, auth_users["pm"], settings)
    # PM sent expected_updated at 12:00:00 (5 min diff > 2.0s)
    resp = client.post(f"/api/actions/{action.id}/confirm", json={"expected_updated": "2026-11-04T12:00:00Z"})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["status"] == "conflict"
    assert "current_updated" in detail
    assert "expected_updated" in detail

    session.refresh(action)
    assert action.status == "conflict"


@respx.mock
def test_confirm_action_success_200_applied(client, auth_users, settings, sample_project, session, issue_new):
    now = utcnow()
    issue = Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now)
    action = Action(
        issue_key="DEMO-1",
        items=[
            {"action_type": "adjust_deadline", "value": "2026-11-30", "reason": "Sprint push"},
            {"action_type": "add_comment", "value": "Updated by PM", "reason": "Note"},
        ],
        status="pending",
        created_at=now,
    )
    session.add_all([issue, action])
    session.commit()

    base = settings.jira_base_url.rstrip("/")
    # 1. Jira updated check returns timestamp matching expected within 2s
    respx.get(f"{base}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T12:00:01.000Z"}})
    )
    # 2. Jira update issue call (for adjust_deadline)
    respx.put(f"{base}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(204))
    # 3. Jira comment call
    respx.post(f"{base}/rest/api/3/issue/DEMO-1/comment").mock(return_value=httpx.Response(201, json={"id": "101"}))
    # 4. Jira get issue for sync_issue
    respx.get(f"{base}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(200, json=issue_new))

    login(client, auth_users["pm"], settings)
    resp = client.post(f"/api/actions/{action.id}/confirm", json={"expected_updated": "2026-11-04T12:00:00Z"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "applied"
    assert data["action_id"] == action.id
    assert data["applied_items"] == 2

    session.refresh(action)
    assert action.status == "applied"
    assert action.confirmed_by == auth_users["pm"].id
    assert action.result["applied_items"] == 2


@respx.mock
def test_confirm_action_without_matching_transition_422_and_replay_is_stable(
    client, auth_users, settings, sample_project, session
):
    now = utcnow()
    action = Action(
        issue_key="DEMO-1",
        items=[{"action_type": "change_status", "value": "Done"}],
        status="pending",
        created_at=now,
    )
    session.add_all([Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now), action])
    session.commit()
    base = settings.jira_base_url.rstrip("/")
    respx.get(f"{base}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T12:00:00.000Z"}})
    )
    transitions = respx.get(f"{base}/rest/api/3/issue/DEMO-1/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": [{"id": "11", "name": "Start", "to": {"name": "In Progress"}}]})
    )
    trans_post = respx.post(f"{base}/rest/api/3/issue/DEMO-1/transitions").mock(return_value=httpx.Response(204))

    login(client, auth_users["pm"], settings)
    body = {"expected_updated": "2026-11-04T12:00:00Z"}
    first = client.post(f"/api/actions/{action.id}/confirm", json=body)
    second = client.post(f"/api/actions/{action.id}/confirm", json=body)

    assert first.status_code == second.status_code == 422
    assert first.json()["detail"]["error"] == "transition_not_allowed"
    assert first.json()["detail"]["available"] == ["In Progress"]
    assert second.json() == first.json()
    assert transitions.call_count == 1
    assert not trans_post.called


@respx.mock
def test_confirm_action_twice_applies_once(client, auth_users, settings, sample_project, session, issue_new):
    now = utcnow()
    action = Action(
        issue_key="DEMO-1",
        items=[{"action_type": "add_comment", "value": "note"}],
        status="pending",
        created_at=now,
    )
    session.add_all([Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=now), action])
    session.commit()
    base = settings.jira_base_url.rstrip("/")
    respx.get(f"{base}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T12:00:00.000Z"}})
    )
    comment = respx.post(f"{base}/rest/api/3/issue/DEMO-1/comment").mock(return_value=httpx.Response(201, json={}))
    respx.get(f"{base}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(200, json=issue_new))

    login(client, auth_users["pm"], settings)
    body = {"expected_updated": "2026-11-04T12:00:00Z"}
    first = client.post(f"/api/actions/{action.id}/confirm", json=body)
    second = client.post(f"/api/actions/{action.id}/confirm", json=body)

    assert first.status_code == second.status_code == 200
    assert second.json() == {"status": "applied", "action_id": action.id, "applied_items": 1}
    assert comment.call_count == 1


# ===========================================================================
# 6. GET /api/issues/{key}/transitions
# ===========================================================================


@respx.mock
def test_transitions_lists_jira_transitions_for_pm(client, auth_users, settings, sample_project, session):
    session.add(Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow()))
    session.commit()
    base = settings.jira_base_url.rstrip("/")
    respx.get(f"{base}/rest/api/3/issue/DEMO-1/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": [
            {"id": "31", "name": "Start", "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
        ]})
    )

    login(client, auth_users["pm"], settings)
    resp = client.get("/api/issues/DEMO-1/transitions")

    assert resp.status_code == 200
    assert resp.json() == [{"id": "31", "name": "Start", "to_status": "In Progress", "to_category": "indeterminate"}]


def test_transitions_forbidden_for_viewer(client, auth_users, settings, sample_project, session):
    session.add(Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow()))
    session.commit()
    login(client, auth_users["viewer"], settings)
    assert client.get("/api/issues/DEMO-1/transitions").status_code == 403


def test_transitions_unknown_issue_404(client, auth_users, settings, sample_project):
    login(client, auth_users["pm"], settings)
    assert client.get("/api/issues/DEMO-404/transitions").status_code == 404


@respx.mock
def test_transitions_jira_error_is_502(client, auth_users, settings, sample_project, session):
    session.add(Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow()))
    session.commit()
    base = settings.jira_base_url.rstrip("/")
    respx.get(f"{base}/rest/api/3/issue/DEMO-1/transitions").mock(return_value=httpx.Response(500, text="boom"))

    login(client, auth_users["pm"], settings)
    resp = client.get("/api/issues/DEMO-1/transitions")

    assert resp.status_code == 502
    assert isinstance(resp.json()["detail"], str)


def test_transitions_jira_not_configured_is_502(client, auth_users, settings, sample_project, session):
    session.add(Issue(key="DEMO-1", project_key="DEMO", summary="Task", created_at=utcnow()))
    session.commit()
    settings.jira_base_url = ""

    login(client, auth_users["pm"], settings)
    resp = client.get("/api/issues/DEMO-1/transitions")
    assert resp.status_code == 502, resp.text
