import json
from datetime import UTC, datetime

from erw.ingest.sync import catch_up
from erw.models import KV, Issue


def _kv(session, key, value):
    session.merge(KV(key=key, value=value))
    session.commit()


def test_catch_up_uses_last_webhook_minus_5_minutes(session, settings, fake_jira, issue_new):
    _kv(session, "last_webhook_at", "2026-11-04T03:00:00+00:00")  # 10:00 in Asia/Saigon
    _kv(session, "pending_sync", json.dumps(["DEMO-9"]))
    fake_jira.search_result = ["DEMO-1"]
    fake_jira.issues["DEMO-1"] = issue_new
    now = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    n = catch_up(session, fake_jira, settings, now)
    assert n == 2
    assert fake_jira.search_jqls == ['project in ("DEMO") AND updated >= "2026/11/04 09:55"']
    assert sorted(fake_jira.get_issue_calls) == ["DEMO-1", "DEMO-9"]
    session.expire_all()
    assert session.get(Issue, "DEMO-1") is not None
    assert json.loads(session.get(KV, "pending_sync").value) == [] or session.get(KV, "pending_sync") is None
    assert session.get(KV, "last_catch_up_at") is not None


def test_catch_up_without_last_webhook_looks_back_one_day(session, settings, fake_jira):
    now = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert catch_up(session, fake_jira, settings, now) == 0
    assert 'updated >= "2026/11/03 11:55"' in fake_jira.search_jqls[0]


def test_catch_up_replays_pending_events(session, settings, fake_jira):
    from erw.models import Sprint
    from tests.conftest import load_fixture

    ev = load_fixture("wh_sprint_updated")
    _kv(session, "pending_events", json.dumps([ev]))
    now = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    catch_up(session, fake_jira, settings, now)
    session.expire_all()
    assert session.get(Sprint, 2) is not None
    assert json.loads(session.get(KV, "pending_events").value) == []

    # replay that fails again stays queued
    fake_jira.board_ids = lambda k: (_ for _ in ()).throw(__import__("erw.integrations.jira", fromlist=["x"]).JiraError(503))
    session.merge(KV(key="tracked_boards", value=None)); session.commit()
    _kv(session, "pending_events", json.dumps([ev]))
    catch_up(session, fake_jira, settings, now)
    session.expire_all()
    assert len(json.loads(session.get(KV, "pending_events").value)) == 1
