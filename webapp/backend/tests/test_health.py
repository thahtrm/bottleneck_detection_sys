from datetime import UTC, datetime

from sqlalchemy import inspect

from erw.models import Issue


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_init_db_creates_tables(session):
    names = set(inspect(session.bind).get_table_names())
    assert {"issues", "changes", "links", "sprints", "issue_sprints", "versions", "issue_versions",
            "scores", "risk_state", "notifications", "kv"} <= names


def test_datetime_roundtrip_is_utc_aware(session):
    t = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    session.add(Issue(key="DEMO-1", project_key="DEMO", created_at=t))
    session.commit()
    session.expire_all()
    got = session.get(Issue, "DEMO-1").created_at
    assert got == t and got.tzinfo is not None


def test_settings_parse_env(monkeypatch):
    from erw.settings import Settings

    monkeypatch.setenv("JIRA_PROJECTS", "DEMO,PAY")
    monkeypatch.setenv("PM_NAME_BY_PROJECT", '{"DEMO":"Trần Bình"}')
    s = Settings(_env_file=None)
    assert s.jira_projects == ["DEMO", "PAY"]
    assert s.pm_name_by_project == {"DEMO": "Trần Bình"}
    assert s.model_mode == "shadow" and s.db_url == "sqlite:///var/erw.db"
