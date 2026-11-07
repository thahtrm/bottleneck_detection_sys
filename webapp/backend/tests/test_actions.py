import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from erw.db import utcnow
from erw.domain.actions import execute_action
from erw.integrations.jira import JiraClient, JiraError, Transition, match_transition
from erw.models import Action, Issue, User

BASE = "https://example.atlassian.net"


@pytest.fixture
def jira_client(monkeypatch):
    monkeypatch.setattr("erw.integrations.jira.BACKOFF_SECONDS", (0, 0, 0))
    with httpx.Client() as http:
        yield JiraClient(BASE, "bot@example.com", "tok", http=http)


@pytest.fixture
def pm_user(session) -> User:
    user = User(
        email="pm.alice@example.com",
        name="Alice PM",
        password_hash="hash",
        is_admin=False,
        created_at=utcnow(),
    )
    session.add(user)
    session.commit()
    return user


# ---------------------------------------------------------------------------
# JiraClient write methods tests
# ---------------------------------------------------------------------------


@respx.mock
def test_jira_get_issue_updated(jira_client):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T05:30:00.000+0700"}})
    )
    updated = jira_client.get_issue_updated("DEMO-1")
    assert updated.tzinfo == UTC
    assert updated == datetime(2026, 11, 3, 22, 30, 0, tzinfo=UTC)


@respx.mock
def test_jira_get_issue_updated_zulu(jira_client):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T12:00:00.000Z"}})
    )
    updated = jira_client.get_issue_updated("DEMO-1")
    assert updated == datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)


@respx.mock
def test_jira_get_issue_updated_404_raises(jira_client):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-99").mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(JiraError) as exc:
        jira_client.get_issue_updated("DEMO-99")
    assert exc.value.status == 404


@respx.mock
def test_jira_get_issue_updated_missing_field_raises(jira_client):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(200, json={"fields": {}}))
    with pytest.raises(JiraError) as exc:
        jira_client.get_issue_updated("DEMO-1")
    assert exc.value.status == 404


@respx.mock
def test_jira_update_issue(jira_client):
    route = respx.put(f"{BASE}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(204))
    jira_client.update_issue("DEMO-1", {"duedate": "2026-11-30"})
    assert route.called
    assert json.loads(route.calls.last.request.content) == {"fields": {"duedate": "2026-11-30"}}


@respx.mock
def test_jira_add_comment(jira_client):
    route = respx.post(f"{BASE}/rest/api/3/issue/DEMO-1/comment").mock(
        return_value=httpx.Response(201, json={"id": "10050"})
    )
    jira_client.add_comment("DEMO-1", "Test comment body")
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Test comment body"}],
                }
            ],
        }
    }


@respx.mock
def test_jira_get_transitions_parses_target_status(jira_client):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1/transitions").mock(
        return_value=httpx.Response(
            200,
            json={
                "transitions": [
                    {"id": 11, "name": "Start", "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
                    {"id": "21", "name": "Close Issue", "to": {"name": "Done"}},
                ]
            },
        )
    )
    assert jira_client.get_transitions("DEMO-1") == [
        Transition(id="11", name="Start", to_status="In Progress", to_category="indeterminate"),
        Transition(id="21", name="Close Issue", to_status="Done", to_category=None),
    ]


_TRANSITIONS = [
    Transition(id="11", name="Start", to_status="In Progress", to_category="indeterminate"),
    Transition(id="21", name="Close Issue", to_status="Done", to_category="done"),
    Transition(id="31", name="Resolve", to_status="Closed", to_category="done"),
]


@pytest.mark.parametrize(
    ("target", "expected_id"),
    [("in progress", "11"), ("DONE", "21"), ("resolve", "31"), ("Unknown", None)],
)
def test_match_transition_prefers_target_status_then_transition_name(target, expected_id):
    found = match_transition(_TRANSITIONS, target)
    assert (found.id if found else None) == expected_id


@respx.mock
def test_jira_transition_issue(jira_client):
    route = respx.post(f"{BASE}/rest/api/3/issue/DEMO-1/transitions").mock(return_value=httpx.Response(204))
    jira_client.transition_issue("DEMO-1", "31")
    assert route.called
    assert json.loads(route.calls.last.request.content) == {"transition": {"id": "31"}}


# ---------------------------------------------------------------------------
# execute_action tests
# ---------------------------------------------------------------------------


def test_execute_action_not_found_raises(session, jira_client, pm_user, settings):
    with pytest.raises(ValueError, match="Action 999 not found"):
        execute_action(
            session=session,
            jira_client=jira_client,
            action_id=999,
            expected_updated=utcnow(),
            confirmed_by_user=pm_user,
            settings=settings,
        )


@respx.mock
def test_execute_action_conflict_detected(session, jira_client, pm_user, settings):
    action = Action(
        issue_key="DEMO-1",
        items=[{"action_type": "adjust_deadline", "value": "2026-11-20"}],
        status="pending",
        created_at=utcnow(),
    )
    session.add(action)
    session.commit()

    # Jira has updated timestamp 5 minutes after expected
    jira_updated_str = "2026-11-04T10:05:00.000Z"
    expected_dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)

    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json={"fields": {"updated": jira_updated_str}})
    )

    res = execute_action(
        session=session,
        jira_client=jira_client,
        action_id=action.id,
        expected_updated=expected_dt,
        confirmed_by_user=pm_user,
        settings=settings,
    )

    assert res["status"] == "conflict"
    assert "current_updated" in res
    assert "expected_updated" in res

    # Verify DB state
    session.refresh(action)
    assert action.status == "conflict"
    assert action.result["error"] == "conflict"
    assert action.confirmed_by is None


@respx.mock
def test_execute_action_success_all_items_and_pm_attribution(
    session, jira_client, pm_user, settings, issue_new
):
    action = Action(
        issue_key="DEMO-1",
        items=[
            {"action_type": "adjust_deadline", "value": "2026-11-25", "reason": "Dời deadline sprint"},
            {"action_type": "change_assignee", "value": "acc-pm-10", "reason": "Reassign cho lead"},
            {"action_type": "change_status", "value": "In Progress", "reason": "Bắt đầu làm"},
            {"action_type": "add_comment", "value": "Họp thống nhất kế hoạch", "reason": "Ghi chú"},
            {"action_type": "escalate_blocker", "target": "DEMO-99", "reason": "Chặn deploy", "value": None},
        ],
        status="pending",
        created_at=utcnow(),
    )
    session.add(action)
    session.commit()

    updated_iso = "2026-11-04T10:00:01.000Z"
    expected_dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)  # 1s diff <= 2s

    # 1. Jira updated check
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": updated_iso}})
    )

    # 2. Jira update issue calls (duedate, assignee)
    put_route = respx.put(f"{BASE}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(204))

    # 3. Jira transitions
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1/transitions").mock(
        return_value=httpx.Response(
            200, json={"transitions": [{"id": "21", "to": {"name": "In Progress"}}]}
        )
    )
    trans_route = respx.post(f"{BASE}/rest/api/3/issue/DEMO-1/transitions").mock(
        return_value=httpx.Response(204)
    )

    # 4. Jira comments
    comment_route = respx.post(f"{BASE}/rest/api/3/issue/DEMO-1/comment").mock(
        return_value=httpx.Response(201, json={"id": "999"})
    )

    # 5. sync_issue GET /rest/api/3/issue/DEMO-1
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json=issue_new)
    )

    class SpySlack:
        def __init__(self):
            self.posts = []

        def post(self, text: str) -> None:
            self.posts.append(text)

    spy_slack = SpySlack()

    res = execute_action(
        session=session,
        jira_client=jira_client,
        action_id=action.id,
        expected_updated=expected_dt,
        confirmed_by_user=pm_user,
        settings=settings,
        sender=spy_slack,
    )

    # Return value
    assert res["status"] == "applied"
    assert res["action_id"] == action.id
    assert res["applied_items"] == 5

    # Check DB action
    session.refresh(action)
    assert action.status == "applied"
    assert action.confirmed_by == pm_user.id
    assert action.result["applied_items"] == 5
    assert "applied_at" in action.result

    # Check Jira PUT calls (adjust_deadline and change_assignee)
    assert put_route.call_count == 2
    put_bodies = [json.loads(c.request.content) for c in put_route.calls]
    assert {"fields": {"duedate": "2026-11-25"}} in put_bodies
    assert {"fields": {"assignee": {"accountId": "acc-pm-10"}}} in put_bodies

    # Check Jira transition
    assert trans_route.call_count == 1
    assert json.loads(trans_route.calls.last.request.content) == {"transition": {"id": "21"}}

    # Check Jira comments (add_comment and escalate_blocker)
    assert comment_route.call_count == 2
    comments = []
    for c in comment_route.calls:
        data = json.loads(c.request.content)
        comments.append(data["body"]["content"][0]["content"][0]["text"])

    expected_attribution = "*(xác nhận bởi PM Alice PM qua Early Risk)*"
    # First comment
    assert "Họp thống nhất kế hoạch" in comments[0]
    assert expected_attribution in comments[0]
    # Second comment (escalate blocker)
    assert "DEMO-99" in comments[1]
    assert "Chặn deploy" in comments[1]
    assert expected_attribution in comments[1]

    # Check Slack message
    assert len(spy_slack.posts) == 1
    assert "[Đã xử lý] [DEMO]" in spy_slack.posts[0]
    assert "<http://localhost:8000/issues/DEMO-1|DEMO-1>" in spy_slack.posts[0]
    assert "đã được cập nhật bởi PM Alice PM." in spy_slack.posts[0]

    # Check sync_issue upserted issue into DB
    synced_issue = session.get(Issue, "DEMO-1")
    assert synced_issue is not None
    assert synced_issue.key == "DEMO-1"


@respx.mock
def test_execute_action_unassigned_and_target_fallback(session, jira_client, pm_user, settings, issue_new):
    action = Action(
        issue_key="DEMO-1",
        items=[
            {"action_type": "change_assignee", "value": "unassigned"},
            {"action_type": "adjust_deadline", "target": "2026-11-28", "value": "Dời ngày cuối"},
        ],
        status="pending",
        created_at=utcnow(),
    )
    session.add(action)
    session.commit()

    now_iso = "2026-11-04T10:00:00.000Z"
    now_dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)

    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": now_iso}})
    )
    put_route = respx.put(f"{BASE}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(204))
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json=issue_new)
    )

    res = execute_action(
        session=session,
        jira_client=jira_client,
        action_id=action.id,
        expected_updated=now_dt,
        confirmed_by_user=pm_user,
        settings=settings,
    )
    assert res["status"] == "applied"
    assert put_route.call_count == 2
    bodies = [json.loads(c.request.content) for c in put_route.calls]
    assert {"fields": {"assignee": None}} in bodies
    assert {"fields": {"duedate": "2026-11-28"}} in bodies


@respx.mock
def test_execute_action_slack_webhook_used_when_sender_is_none(
    session, jira_client, pm_user, settings, issue_new
):
    action = Action(
        issue_key="DEMO-1",
        items=[],
        status="pending",
        created_at=utcnow(),
    )
    session.add(action)
    session.commit()

    settings.slack_webhook_url = "https://hooks.slack.com/services/T/B/X"
    now_iso = "2026-11-04T10:00:00.000Z"
    now_dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)

    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": now_iso}})
    )
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(200, json=issue_new)
    )
    slack_route = respx.post("https://hooks.slack.com/services/T/B/X").mock(
        return_value=httpx.Response(200, text="ok")
    )

    res = execute_action(
        session=session,
        jira_client=jira_client,
        action_id=action.id,
        expected_updated=now_dt,
        confirmed_by_user=pm_user,
        settings=settings,
        sender=None,
    )
    assert res["status"] == "applied"
    assert slack_route.called
    body = json.loads(slack_route.calls.last.request.content)
    assert "[Đã xử lý] [DEMO]" in body["text"]


@respx.mock
def test_execute_action_failure_marks_failed_status(session, jira_client, pm_user, settings):
    action = Action(
        issue_key="DEMO-1",
        items=[{"action_type": "adjust_deadline", "value": "2026-11-20"}],
        status="pending",
        created_at=utcnow(),
    )
    session.add(action)
    session.commit()

    now_iso = "2026-11-04T10:00:00.000Z"
    now_dt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)

    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": now_iso}})
    )
    # Jira returns 500 on PUT
    respx.put(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    with pytest.raises(JiraError):
        execute_action(
            session=session,
            jira_client=jira_client,
            action_id=action.id,
            expected_updated=now_dt,
            confirmed_by_user=pm_user,
            settings=settings,
        )

    session.refresh(action)
    assert action.status == "failed"
    assert "error" in action.result


def _pending(session, items) -> Action:
    action = Action(issue_key="DEMO-1", items=items, status="pending", created_at=utcnow())
    session.add(action)
    session.commit()
    return action


def _confirm(session, jira_client, pm_user, settings, action):
    return execute_action(
        session=session,
        jira_client=jira_client,
        action_id=action.id,
        expected_updated=datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC),
        confirmed_by_user=pm_user,
        settings=settings,
    )


@respx.mock
def test_execute_action_status_without_transition_fails_before_any_jira_write(session, jira_client, pm_user, settings):
    action = _pending(session, [
        {"action_type": "adjust_deadline", "value": "2026-11-25"},
        {"action_type": "change_status", "value": "Done"},
        {"action_type": "add_comment", "value": "note"},
    ])
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1", params={"fields": "updated"}).mock(
        return_value=httpx.Response(200, json={"fields": {"updated": "2026-11-04T10:00:00.000Z"}})
    )
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": [
            {"id": "11", "name": "Start", "to": {"name": "In Progress"}},
            {"id": "12", "name": "Pause", "to": {"name": "To Do"}},
        ]})
    )
    put_route = respx.put(f"{BASE}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(204))
    comment_route = respx.post(f"{BASE}/rest/api/3/issue/DEMO-1/comment").mock(return_value=httpx.Response(201))
    trans_route = respx.post(f"{BASE}/rest/api/3/issue/DEMO-1/transitions").mock(return_value=httpx.Response(204))

    res = _confirm(session, jira_client, pm_user, settings, action)

    expected = {"error": "transition_not_allowed", "target": "Done", "available": ["In Progress", "To Do"]}
    assert res == {"status": "failed", **expected}
    assert not put_route.called and not comment_route.called and not trans_route.called
    session.refresh(action)
    assert action.status == "failed"
    assert action.result == expected


@respx.mock
def test_execute_action_repeat_confirm_returns_stored_outcome_without_jira(session, jira_client, pm_user, settings):
    applied = Action(
        issue_key="DEMO-1", items=[{"action_type": "add_comment", "value": "x"}], status="applied",
        result={"applied_items": 1, "applied_at": "2026-11-04T10:00:00+00:00"}, created_at=utcnow(),
    )
    conflicted = Action(
        issue_key="DEMO-1", items=[], status="conflict", created_at=utcnow(),
        result={"error": "conflict", "current_updated": "a", "expected_updated": "b"},
    )
    failed = Action(
        issue_key="DEMO-1", items=[], status="failed", created_at=utcnow(),
        result={"error": "transition_not_allowed", "target": "Done", "available": []},
    )
    session.add_all([applied, conflicted, failed])
    session.commit()
    any_jira = respx.route(host="example.atlassian.net").mock(return_value=httpx.Response(500))

    assert _confirm(session, jira_client, pm_user, settings, applied) == {
        "status": "applied", "action_id": applied.id, "applied_items": 1,
    }
    assert _confirm(session, jira_client, pm_user, settings, conflicted) == {
        "status": "conflict", "current_updated": "a", "expected_updated": "b",
    }
    assert _confirm(session, jira_client, pm_user, settings, failed) == {
        "status": "failed", "error": "transition_not_allowed", "target": "Done", "available": [],
    }
    assert not any_jira.called
