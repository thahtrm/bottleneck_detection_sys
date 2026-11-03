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
