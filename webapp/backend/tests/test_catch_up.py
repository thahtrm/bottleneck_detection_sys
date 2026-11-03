import json
from datetime import UTC, datetime

from erw.ingest.sync import catch_up
from erw.models import KV, Issue


def _kv(session, key, value):
    session.merge(KV(key=key, value=value))
    session.commit()


def test_catch_up_uses_max_last_webhook_and_catch_up_minus_5_minutes(session, settings, fake_jira, issue_new):
    _kv(session, "last_catch_up_at", "2026-11-04T02:00:00+00:00")
    _kv(session, "last_webhook_at", "2026-11-04T03:00:00+00:00")  # 10:00 in Asia/Saigon, newer than catch-up
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


def test_catch_up_fresh_install_omits_updated_clause(session, settings, fake_jira):
    # fresh install: no last_catch_up_at
    now = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert catch_up(session, fake_jira, settings, now) == 0
    assert fake_jira.search_jqls == ['project in ("DEMO")']
    session.expire_all()
    assert session.get(KV, "last_catch_up_at") is not None


def test_catch_up_uses_last_catch_up_when_webhook_absent(session, settings, fake_jira):
    _kv(session, "last_catch_up_at", "2026-11-04T03:00:00+00:00")
    now = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert catch_up(session, fake_jira, settings, now) == 0
    assert fake_jira.search_jqls == ['project in ("DEMO") AND updated >= "2026/11/04 09:55"']


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


def test_cli_catch_up_registers_dispatch(monkeypatch):
    from erw import cli
    from erw.pipeline import alerts, evaluate

    evaluate._dispatch = None
    monkeypatch.setattr(cli, "init_db", lambda eng: None)
    monkeypatch.setattr(cli, "make_engine", lambda url: None)
    monkeypatch.setattr(cli, "catch_up", lambda s, c, st, now: 0)

    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(cli, "SessionLocal", lambda bind=None: DummySession())
    monkeypatch.setattr(cli, "JiraClient", lambda *a: None)

    ret = cli.main(["catch-up"])
    assert ret == 0
    assert evaluate._dispatch is alerts.dispatch
