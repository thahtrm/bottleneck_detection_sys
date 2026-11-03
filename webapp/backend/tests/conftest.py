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
        slack_webhook_url="",
    )


@pytest.fixture
def engine(settings):
    """One engine per test, shared by `session`, `client` and the background jobs."""
    eng = make_engine(settings.db_url)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with SessionLocal(bind=engine) as s:
        yield s


@pytest.fixture
def client(settings, engine):
    with TestClient(create_app(settings, engine=engine, catch_up_on_startup=False, start_scheduler_on_startup=False)) as c:
        yield c


class FakeJira:
    """Test double of JiraClient; install with jobs.set_client()."""

    def __init__(self):
        self.issues: dict[str, dict] = {}
        self.errors: dict[str, Exception] = {}
        self.get_issue_calls: list[str] = []
        self.search_jqls: list[str] = []
        self.search_result: list[str] = []
        self.boards = {"DEMO": [3]}
        self.project_ids = {"DEMO": 10002}
        self.tz = "Asia/Saigon"

    def get_issue(self, key):
        self.get_issue_calls.append(key)
        if key in self.errors:
            raise self.errors[key]
        return self.issues.get(key)

    def search_keys(self, jql):
        self.search_jqls.append(jql)
        return list(self.search_result)

    def board_ids(self, project_key):
        return list(self.boards.get(project_key, []))

    def project_id(self, key):
        return self.project_ids[key]

    def myself(self):
        return {"timeZone": self.tz}


@pytest.fixture
def fake_jira():
    from erw import jobs

    fake = FakeJira()
    jobs.set_client(fake)
    yield fake
    jobs.set_client(None)


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


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    from erw.pipeline import evaluate

    evaluate.clear_stats_cache()
    yield
    evaluate.clear_stats_cache()


@pytest.fixture(autouse=True)
def _restore_dispatch():
    from erw.pipeline import evaluate

    prev = evaluate._dispatch
    yield
    evaluate._dispatch = prev
