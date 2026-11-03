import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from erw.db import SessionLocal, init_db, make_engine
from erw.main import create_app
from erw.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "jira"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        db_url="sqlite://",
        jira_base_url="https://example.atlassian.net",
        jira_email="bot@example.com",
        jira_api_token="token",
        jira_projects=["DEMO"],
        jira_webhook_secret="secret",
        public_base_url="https://example.ngrok.test",
        slack_webhook_url="https://hooks.slack.test/x",
    )


@pytest.fixture
def session(settings):
    engine = make_engine(settings.db_url)
    init_db(engine)
    with SessionLocal(bind=engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _demo1() -> dict:
    return load_fixture("rest_issue_demo1")


def derive_issue_new() -> dict:
    """DEMO-1 as just created: status To Do, only the early histories (sprint, duedate, assignee)."""
    d = _demo1()
    d["fields"]["status"] = {
        "name": "To Do",
        "id": "10008",
        "statusCategory": {"id": 2, "key": "new", "name": "To Do"},
    }
    keep = {"10029", "10032", "10034"}
    hist = [h for h in d["changelog"]["histories"] if h["id"] in keep]
    d["changelog"]["histories"] = hist
    d["changelog"]["total"] = len(hist)
    return d


def derive_issue_updated() -> dict:
    """issue_new plus one new history changing status and sprint (status now In Progress)."""
    d = derive_issue_new()
    full = _demo1()
    d["fields"]["status"] = full["fields"]["status"]
    d["fields"]["customfield_10020"] = [
        {"id": 3, "name": "Sprint S4", "state": "future", "boardId": 3},
        *full["fields"]["customfield_10020"],
    ]
    d["changelog"]["histories"].append(
        {
            "id": "10100",
            "created": "2026-11-04T00:09:00.000+0700",
            "items": [
                {"field": "status", "fieldtype": "jira", "from": "10008", "fromString": "To Do", "to": "3", "toString": "In Progress"},
                {"field": "Sprint", "fieldtype": "custom", "from": "2", "fromString": "Sprint S3", "to": "2, 3", "toString": "Sprint S3, Sprint S4"},
            ],
        }
    )
    d["changelog"]["total"] = len(d["changelog"]["histories"])
    return d


def derive_issue_blocked() -> dict:
    """DEMO-3 blocked by DEMO-2 (inward 'is blocked by' side of a Blocks link)."""
    d = copy.deepcopy(derive_issue_new())
    d["key"] = "DEMO-3"
    d["id"] = "10003"
    d["fields"]["issuelinks"] = [
        {
            "id": "10001",
            "type": {"id": "10000", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
            "inwardIssue": {"key": "DEMO-2", "fields": {"summary": "x"}},
        }
    ]
    return d


@pytest.fixture
def issue_new() -> dict:
    return derive_issue_new()


@pytest.fixture
def issue_updated() -> dict:
    return derive_issue_updated()


@pytest.fixture
def issue_blocked() -> dict:
    return derive_issue_blocked()
