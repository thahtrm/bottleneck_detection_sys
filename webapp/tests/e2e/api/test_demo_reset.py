"""Local-mode reachability for POST /api/admin/demo/reset.

Uses the same sqlite app and seeder accounts as webapp/backend/tests/test_seed_demo.py.
The e2e account fixtures provision a different user table (admin@e2e.local).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from erw.db import SessionLocal, init_db, make_engine
from erw.demo.seed import seed_demo_data
from erw.main import create_app
from erw.settings import Settings


@pytest.fixture
def local_settings():
    return Settings(
        _env_file=None,
        db_url="sqlite://",
        jira_base_url="",
        jira_projects=["DEMO"],
        slack_webhook_url="",
    )


@pytest.fixture
def local_engine(local_settings):
    eng = make_engine(local_settings.db_url)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def local_session(local_engine):
    with SessionLocal(bind=local_engine) as session:
        yield session


@pytest.fixture
def local_client(local_settings, local_engine):
    with TestClient(
        create_app(
            local_settings,
            engine=local_engine,
            catch_up_on_startup=False,
            start_scheduler_on_startup=False,
        )
    ) as client:
        yield client


def test_local_admin_demo_reset_includes_issues_and_viewer_is_forbidden(local_client, local_session):
    seed_demo_data(local_session, reset=True)

    viewer = local_client.post(
        "/api/auth/login",
        json={"email": "viewer@earlyrisk.local", "password": "Viewer@123456"},
    )
    assert viewer.status_code == 200
    denied = local_client.post("/api/admin/demo/reset")
    assert denied.status_code == 403

    admin = local_client.post(
        "/api/auth/login",
        json={"email": "admin@earlyrisk.local", "password": "Admin@123456"},
    )
    assert admin.status_code == 200
    reset = local_client.post("/api/admin/demo/reset")
    assert reset.status_code == 200
    assert isinstance(reset.json()["issues"], int)
    assert reset.json()["issues"] >= 1
