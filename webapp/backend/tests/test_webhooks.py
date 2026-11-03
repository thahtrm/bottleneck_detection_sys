import json

from sqlalchemy import select

from erw import jobs
from erw.integrations.jira import JiraError
from erw.models import KV, Issue, Sprint, Version
from tests.conftest import load_fixture

SECRET = "secret"


def _drain():
    jobs.executor.submit(lambda: None).result()


def _post(client, name):
    return client.post(f"/webhooks/jira/{SECRET}", json=load_fixture(name))


def test_wrong_secret_404(client):
    assert client.post("/webhooks/jira/nope", json={}).status_code == 404


def test_valid_webhook_accepted_and_synced(client, fake_jira, session, issue_new):
    fake_jira.issues["DEMO-1"] = issue_new
    r = _post(client, "wh_issue_created")
    assert r.status_code == 200 and r.json() == {"accepted": True}
    _drain()
    assert session.get(Issue, "DEMO-1") is not None
    assert session.get(KV, "last_webhook_at") is not None


def test_jira_error_goes_to_pending_sync(client, fake_jira, session):
    fake_jira.errors["DEMO-1"] = JiraError(500, "boom")
    _post(client, "wh_issue_created")
    _drain()
    session.expire_all()
    assert json.loads(session.get(KV, "pending_sync").value) == ["DEMO-1"]


def test_unexpected_error_is_logged_not_raised(client, fake_jira, caplog):
    fake_jira.errors["DEMO-1"] = RuntimeError("bug")
    _post(client, "wh_issue_created")
    _drain()
    assert "bug" in caplog.text


def test_issuelink_syncs_both_ends_by_id(client, fake_jira):
    _post(client, "wh_issuelink_created")
    _drain()
    assert fake_jira.get_issue_calls == ["10013", "10014"]


def test_issue_deleted_marks_deleted(client, fake_jira, session, issue_new):
    fake_jira.issues["DEMO-1"] = issue_new
    _post(client, "wh_issue_created")
    client.post(
        f"/webhooks/jira/{SECRET}",
        json={"webhookEvent": "jira:issue_deleted", "issue": {"key": "DEMO-1", "id": "10013"}},
    )
    _drain()
    session.expire_all()
    assert session.get(Issue, "DEMO-1").deleted_at is not None


def test_sprint_event_of_tracked_board_synced(client, fake_jira, session):
    _post(client, "wh_sprint_updated")
    _drain()
    assert session.get(Sprint, 2).board_id == 3
    assert json.loads(session.get(KV, "tracked_boards").value) == [3]


def test_sprint_event_of_untracked_board_ignored(client, fake_jira, session):
    payload = load_fixture("wh_sprint_updated")
    payload["sprint"]["originBoardId"] = 99
    client.post(f"/webhooks/jira/{SECRET}", json=payload)
    _drain()
    assert session.scalars(select(Sprint)).all() == []


def test_sprint_event_triggers_on_synced_for_member_issues(client, fake_jira, session, settings, issue_new, monkeypatch):
    fake_jira.issues["DEMO-1"] = issue_new
    _post(client, "wh_issue_created")  # DEMO-1 is in sprint 2
    calls = []
    monkeypatch.setattr("erw.jobs.on_synced", lambda s, results, now, st: calls.append(results) or [])
    _post(client, "wh_sprint_updated")
    _drain()
    assert [(r.kind, r.key, r.changed_fields) for r in calls[-1]] == [("updated", "DEMO-1", frozenset({"sprint"}))]


def test_version_event_sets_project_key(client, fake_jira, session):
    _post(client, "wh_version_updated")
    _drain()
    v = session.get(Version, 10000)
    assert v is not None and v.project_key == "DEMO"


def test_version_event_of_untracked_project_ignored(client, fake_jira, session):
    payload = load_fixture("wh_version_updated")
    payload["version"]["projectId"] = 777
    client.post(f"/webhooks/jira/{SECRET}", json=payload)
    _drain()
    assert session.scalars(select(Version)).all() == []


def test_partial_failure_keeps_successful_key(client, fake_jira, session, issue_new):
    issue_new["id"] = "10013"
    fake_jira.issues["10013"] = issue_new
    fake_jira.errors["10014"] = JiraError(500, "boom")
    _post(client, "wh_issuelink_created")
    _drain()
    session.expire_all()
    assert session.get(Issue, "DEMO-1") is not None
    assert json.loads(session.get(KV, "pending_sync").value) == ["10014"]


def test_sprint_event_jira_error_queued_in_pending_events(client, fake_jira, session):
    fake_jira.board_ids = lambda key: (_ for _ in ()).throw(JiraError(503, "down"))
    _post(client, "wh_sprint_updated")
    _drain()
    session.expire_all()
    pending = json.loads(session.get(KV, "pending_events").value)
    assert [e["webhookEvent"] for e in pending] == ["sprint_updated"]
    assert session.scalars(select(Sprint)).all() == []


def test_non_object_body_400_but_wrong_secret_404(client):
    assert client.post(f"/webhooks/jira/{SECRET}", json=[1, 2]).status_code == 400
    assert client.post("/webhooks/jira/nope", json=[1, 2]).status_code == 404
