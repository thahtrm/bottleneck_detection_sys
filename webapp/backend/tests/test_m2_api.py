from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from erw.auth import hash_password
from erw.db import SessionLocal, init_db, make_engine, utcnow
from erw.main import create_app
from erw.models import Link, Project, ProjectMember, User
from erw.settings import Settings


@pytest.fixture
def local_settings(tmp_path):
    return Settings(
        _env_file=None,
        db_url="sqlite://",
        jira_base_url="",
        jira_projects=["DEMO"],
        slack_webhook_url="",
        attachments_dir=str(tmp_path / "attachments"),
    )


@pytest.fixture
def local_engine(local_settings):
    eng = make_engine(local_settings.db_url)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def local_session(local_engine):
    with SessionLocal(bind=local_engine) as s:
        yield s


@pytest.fixture
def local_client(local_settings, local_engine):
    with TestClient(
        create_app(
            local_settings,
            engine=local_engine,
            catch_up_on_startup=False,
            start_scheduler_on_startup=False,
        )
    ) as c:
        yield c


def _seed_local_users(session):
    now = utcnow()
    admin = User(
        email="admin@local.test",
        name="Admin User",
        password_hash=hash_password("pass"),
        is_admin=True,
        account_id="acc-admin",
        job_title="Engineering Lead",
        department="Platform",
        created_at=now,
    )
    pm = User(
        email="pm@local.test",
        name="PM User",
        password_hash=hash_password("pass"),
        is_admin=False,
        account_id="acc-pm",
        job_title="Product Manager",
        department="Product",
        created_at=now,
    )
    dev = User(
        email="dev@local.test",
        name="Dev User",
        password_hash=hash_password("pass"),
        is_admin=False,
        account_id="acc-dev",
        job_title="Backend Engineer",
        department="Core",
        created_at=now,
    )
    viewer = User(
        email="viewer@local.test",
        name="Viewer User",
        password_hash=hash_password("pass"),
        is_admin=False,
        account_id="acc-viewer",
        created_at=now,
    )
    inactive = User(
        email="inactive@local.test",
        name="Inactive User",
        password_hash=hash_password("pass"),
        is_admin=False,
        is_active=False,
        account_id="acc-inactive",
        created_at=now,
    )
    session.add_all([admin, pm, dev, viewer, inactive])
    session.add(Project(key="DEMO", name="Demo", tracked=True))
    session.flush()
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=dev.id, role="developer"),
            ProjectMember(project_key="DEMO", user_id=viewer.id, role="viewer"),
        ]
    )
    session.commit()
    return {"admin": admin, "pm": pm, "dev": dev, "viewer": viewer, "inactive": inactive}


def _login(client, email: str) -> None:
    resp = client.post("/api/auth/login", json={"email": email, "password": "pass"})
    assert resp.status_code == 200


def _create_issue(client, summary: str, **extra) -> dict:
    body = {"project_key": "DEMO", "summary": summary, "issuetype": "Task", "priority": "Medium"}
    body.update(extra)
    resp = client.post("/api/issues", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_viewer_forbidden_and_developer_can_create(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "viewer@local.test")
    denied = local_client.post("/api/issues", json={"project_key": "DEMO", "summary": "Nope"})
    assert denied.status_code == 403

    _login(local_client, "dev@local.test")
    created = _create_issue(local_client, "Developer task", description="notes", labels=["api"])
    assert created["key"] == "DEMO-1"
    assert created["summary"] == "Developer task"


def test_patch_conflict_transition_and_soft_delete(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "dev@local.test")
    created = _create_issue(local_client, "Lock me")
    stale = created["updated_at"]

    renamed = local_client.patch(
        f"/api/issues/{created['key']}",
        json={"fields": {"summary": "Locked"}, "expected_updated": stale},
    )
    assert renamed.status_code == 200
    assert renamed.json()["summary"] == "Locked"

    conflict = local_client.patch(
        f"/api/issues/{created['key']}",
        json={"fields": {"summary": "Too late"}, "expected_updated": stale},
    )
    assert conflict.status_code == 409

    moved = local_client.post(f"/api/issues/{created['key']}/transitions", json={"transition_id": "61"})
    assert moved.status_code == 200
    assert moved.json()["status"] == "Done"

    _login(local_client, "viewer@local.test")
    hidden = local_client.get("/api/issues", params={"project": "DEMO"})
    assert hidden.status_code == 200
    assert created["key"] in {row["key"] for row in hidden.json()["issues"]}

    _login(local_client, "dev@local.test")
    forbidden = local_client.delete(f"/api/issues/{created['key']}")
    assert forbidden.status_code == 403

    _login(local_client, "pm@local.test")
    deleted = local_client.delete(f"/api/issues/{created['key']}")
    assert deleted.status_code == 204
    listed = local_client.get("/api/issues", params={"project": "DEMO"})
    assert created["key"] not in {row["key"] for row in listed.json()["issues"]}


def test_relate_link_stays_one_row(local_client, local_session):
    users = _seed_local_users(local_session)
    _login(local_client, "dev@local.test")
    left = _create_issue(local_client, "Left")
    right = _create_issue(local_client, "Right")
    first = local_client.post(
        f"/api/issues/{left['key']}/links",
        json={"target_key": right["key"], "link_type": "relates to"},
    )
    assert first.status_code == 200
    second = local_client.post(
        f"/api/issues/{right['key']}/links",
        json={"target_key": left["key"], "link_type": "relates to"},
    )
    assert second.status_code == 200
    assert second.json()["source_key"] == first.json()["source_key"]
    assert second.json()["target_key"] == first.json()["target_key"]
    assert second.json()["type_std"] == "Relate"

    detail = local_client.get(f"/api/issues/{left['key']}")
    assert detail.status_code == 200
    assert len(detail.json()["links"]) == 1

    with SessionLocal(bind=local_session.get_bind()) as check:
        count = check.scalar(select(func.count()).select_from(Link))
    assert count == 1
    assert users["dev"].account_id == "acc-dev"

    removed = local_client.request(
        "DELETE",
        f"/api/issues/{left['key']}/links",
        json={"target_key": right["key"], "link_type": "relates to"},
    )
    assert removed.status_code == 204
    after = local_client.get(f"/api/issues/{left['key']}")
    assert after.json()["links"] == []


def test_comment_mention_edit_delete_and_activity(local_client, local_session):
    _seed_local_users(local_session)
    now = utcnow()
    other = User(
        email="dev2@local.test",
        name="Dev Two",
        password_hash=hash_password("pass"),
        account_id="acc-dev2",
        created_at=now,
    )
    local_session.add(other)
    local_session.flush()
    local_session.add(ProjectMember(project_key="DEMO", user_id=other.id, role="developer"))
    local_session.commit()

    _login(local_client, "dev@local.test")
    issue = _create_issue(local_client, "Discuss")
    created = local_client.post(
        f"/api/issues/{issue['key']}/comments",
        json={"body": "ping @acc-pm and @acc-inactive"},
    )
    assert created.status_code == 201
    comment = created.json()
    assert comment["mentions"] == ["acc-pm"]
    assert comment["edited"] is False

    edited = local_client.patch(
        f"/api/issues/{issue['key']}/comments/{comment['id']}",
        json={"body": "edited @acc-dev"},
    )
    assert edited.status_code == 200
    assert edited.json()["edited"] is True
    assert edited.json()["mentions"] == ["acc-dev"]

    _login(local_client, "dev2@local.test")
    forbidden = local_client.patch(
        f"/api/issues/{issue['key']}/comments/{comment['id']}",
        json={"body": "nope"},
    )
    assert forbidden.status_code == 403

    _login(local_client, "pm@local.test")
    by_pm = local_client.patch(
        f"/api/issues/{issue['key']}/comments/{comment['id']}",
        json={"body": "pm edit"},
    )
    assert by_pm.status_code == 200
    assert by_pm.json()["body"] == "pm edit"

    _login(local_client, "dev@local.test")
    removed = local_client.delete(f"/api/issues/{issue['key']}/comments/{comment['id']}")
    assert removed.status_code == 204

    _login(local_client, "viewer@local.test")
    feed = local_client.get(f"/api/issues/{issue['key']}/activity", params={"kind": "comments"})
    assert feed.status_code == 200
    assert feed.json()["items"] == []

    history = local_client.get(f"/api/issues/{issue['key']}/activity", params={"kind": "history", "order": "asc"})
    assert history.status_code == 200
    assert isinstance(history.json()["items"], list)


def test_worklog_changes_time_spent(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "dev@local.test")
    issue = _create_issue(local_client, "Log time")
    estimated = local_client.patch(
        f"/api/issues/{issue['key']}",
        json={"fields": {"remaining_estimate_seconds": 60}},
    )
    assert estimated.status_code == 200

    logged = local_client.post(
        f"/api/issues/{issue['key']}/worklogs",
        json={"time_spent": "1h", "comment": "worked"},
    )
    assert logged.status_code == 201
    body = logged.json()
    assert body["time_spent_seconds"] == 3600
    assert body["issue_time_spent_seconds"] == 3600
    assert body["remaining_estimate_seconds"] == 0

    feed = local_client.get(f"/api/issues/{issue['key']}/activity", params={"kind": "worklog"})
    assert feed.status_code == 200
    assert feed.json()["items"][0]["time_spent_seconds"] == 3600


def test_watch_and_vote_are_idempotent(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "dev@local.test")
    issue = _create_issue(local_client, "Watch me")
    key = issue["key"]

    first = local_client.post(f"/api/issues/{key}/watch")
    again = local_client.post(f"/api/issues/{key}/watch")
    assert first.status_code == 200
    assert again.status_code == 200
    assert first.json()["watch_count"] == 1
    assert again.json()["watch_count"] == 1
    cleared = local_client.delete(f"/api/issues/{key}/watch")
    assert cleared.json()["watch_count"] == 0
    assert cleared.json()["watching"] is False

    voted = local_client.post(f"/api/issues/{key}/vote")
    voted_again = local_client.post(f"/api/issues/{key}/vote")
    assert voted.json()["vote_count"] == 1
    assert voted_again.json()["vote_count"] == 1
    local_client.delete(f"/api/issues/{key}/vote")
    assert local_client.delete(f"/api/issues/{key}/vote").json()["vote_count"] == 0


def test_clone_and_move(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "pm@local.test")
    other = local_client.post("/api/projects", json={"key": "OTHER", "name": "Other"})
    assert other.status_code == 201
    assert other.json()["lead_user_id"] is not None

    _login(local_client, "dev@local.test")
    source = _create_issue(
        local_client,
        "Clone source",
        description="body",
        labels=["keep"],
        issuetype="Task",
        priority="High",
    )
    local_client.post(f"/api/issues/{source['key']}/comments", json={"body": "not copied"})
    local_client.post(
        f"/api/issues/{source['key']}/links",
        json={"target_key": _create_issue(local_client, "Link target")["key"], "link_type": "relates to"},
    )
    cloned = local_client.post(f"/api/issues/{source['key']}/clone", json={})
    assert cloned.status_code == 201
    copy = cloned.json()
    assert copy["key"] != source["key"]
    assert copy["project_key"] == "DEMO"
    assert copy["summary"] == "Clone source"
    assert copy["description"] == "body"
    assert copy["issuetype"] == "Task"
    assert copy["priority"] == "High"
    assert copy["labels"] == ["keep"]
    comments = local_client.get(f"/api/issues/{copy['key']}/activity", params={"kind": "comments"})
    assert comments.json()["items"] == []
    assert local_client.get(f"/api/issues/{copy['key']}").json()["links"] == []

    retyped = local_client.post(f"/api/issues/{source['key']}/move", json={"issuetype": "Bug"})
    assert retyped.status_code == 200
    assert retyped.json()["key"] == source["key"]
    assert retyped.json()["issuetype"] == "Bug"

    parent = _create_issue(local_client, "Parent")
    sub = _create_issue(local_client, "Child", issuetype="Sub-task", parent_key=parent["key"])
    blocked = local_client.post(f"/api/issues/{sub['key']}/move", json={"project_key": "OTHER"})
    assert blocked.status_code == 422
    assert local_client.get(f"/api/issues/{sub['key']}").json()["issue"]["key"] == sub["key"]

    moved = local_client.post(f"/api/issues/{source['key']}/move", json={"project_key": "OTHER"})
    assert moved.status_code == 200
    assert moved.json()["project_key"] == "OTHER"
    assert moved.json()["key"].startswith("OTHER-")
    assert moved.json()["summary"] == "Clone source"


def test_attachment_roundtrip(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "dev@local.test")
    issue = _create_issue(local_client, "With file")
    uploaded = local_client.post(
        f"/api/issues/{issue['key']}/attachments",
        files={"file": ("note.txt", b"hello-m2", "text/plain")},
    )
    assert uploaded.status_code == 201
    attachment_id = uploaded.json()["id"]
    assert uploaded.json()["filename"] == "note.txt"
    assert uploaded.json()["size_bytes"] == len(b"hello-m2")

    _login(local_client, "viewer@local.test")
    downloaded = local_client.get(f"/api/issues/{issue['key']}/attachments/{attachment_id}")
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello-m2"


def test_navigator_escapes_like_wildcards(local_client, local_session):
    _seed_local_users(local_session)
    _login(local_client, "dev@local.test")
    alpha = _create_issue(local_client, "Alpha task")
    beta = _create_issue(local_client, "Beta task")

    _login(local_client, "viewer@local.test")
    wildcard = local_client.get("/api/issues", params={"project": "DEMO", "q": "%"})
    assert wildcard.status_code == 200
    summaries = {row["summary"] for row in wildcard.json()["issues"]}
    assert "Alpha task" not in summaries
    assert "Beta task" not in summaries

    matched = local_client.get("/api/issues", params={"project": "DEMO", "q": "alpha", "issuetype": "Task"})
    keys = {row["key"] for row in matched.json()["issues"]}
    assert alpha["key"] in keys
    assert beta["key"] not in keys


def test_project_sprint_board_and_catalog(local_client, local_session):
    users = _seed_local_users(local_session)
    _login(local_client, "viewer@local.test")
    assert local_client.post("/api/projects", json={"key": "OPS", "name": "Ops"}).status_code == 403
    _login(local_client, "dev@local.test")
    assert local_client.post("/api/projects", json={"key": "OPS", "name": "Ops"}).status_code == 403

    _login(local_client, "pm@local.test")
    created = local_client.post("/api/projects", json={"key": "OPS", "name": "Ops", "description": "work"})
    assert created.status_code == 201
    assert created.json()["lead_user_id"] == users["pm"].id
    assert created.json()["description"] == "work"

    renamed = local_client.patch("/api/projects/OPS", json={"name": "Operations"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Operations"

    component = local_client.post("/api/projects/OPS/components", json={"name": "API", "description": "edge"})
    assert component.status_code == 201
    component_id = component.json()["id"]
    patched = local_client.patch(f"/api/projects/OPS/components/{component_id}", json={"description": "http"})
    assert patched.json()["description"] == "http"
    listed = local_client.get("/api/projects/OPS/components")
    assert listed.json()[0]["name"] == "API"
    assert local_client.delete(f"/api/projects/OPS/components/{component_id}").status_code == 204
    assert local_client.get("/api/projects/OPS/components").json() == []

    version = local_client.post("/api/projects/OPS/versions", json={"name": "1.0"})
    assert version.status_code == 201
    version_id = version.json()["id"]
    released = local_client.patch(f"/api/projects/OPS/versions/{version_id}", json={"released": True})
    assert released.json()["released"] is True
    assert local_client.get("/api/projects/OPS/versions").json()[0]["released"] is True

    current = local_client.get("/api/projects/DEMO/workflow")
    assert current.status_code == 200
    assert any(row["name"] == "To Do" for row in current.json()["statuses"])
    rejected = local_client.put(
        "/api/projects/DEMO/workflow",
        json={
            "statuses": [{"name": "To Do", "category": "new"}],
            "transitions": [{"id": "9", "from": ["Missing"], "to": "To Do"}],
        },
    )
    assert rejected.status_code == 400
    saved = local_client.put(
        "/api/projects/OPS/workflow",
        json={
            "statuses": [
                {"name": "Ready", "category": "new"},
                {"name": "Finished", "category": "done"},
            ],
            "transitions": [{"id": "9", "from": ["Ready"], "to": "Finished"}],
        },
    )
    assert saved.status_code == 200
    names = {row["name"] for row in local_client.get("/api/projects/OPS/workflow").json()["statuses"]}
    assert names == {"Ready", "Finished"}

    _login(local_client, "dev@local.test")
    assert local_client.post("/api/projects/DEMO/sprints", json={"name": "Denied"}).status_code == 403

    _login(local_client, "pm@local.test")
    open_issue = _create_issue(local_client, "Open work")
    done_issue = _create_issue(local_client, "Finished work")
    assert local_client.post(f"/api/issues/{done_issue['key']}/transitions", json={"transition_id": "61"}).status_code == 200

    sprint = local_client.post("/api/projects/DEMO/sprints", json={"name": "Sprint 1", "goal": "ship"})
    assert sprint.status_code == 201
    sprint_id = sprint.json()["id"]
    assert local_client.patch(f"/api/projects/DEMO/sprints/{sprint_id}", json={"goal": "ship it"}).json()["goal"] == "ship it"
    started = local_client.post(f"/api/projects/DEMO/sprints/{sprint_id}/start")
    assert started.status_code == 200
    assert started.json()["state"] == "active"

    second = local_client.post("/api/projects/DEMO/sprints", json={"name": "Sprint 2"})
    assert local_client.post(f"/api/projects/DEMO/sprints/{second.json()['id']}/start").status_code == 409

    for issue in (open_issue, done_issue):
        ranked = local_client.post(
            "/api/projects/DEMO/backlog/rank",
            json={"issue_key": issue["key"], "sprint_id": sprint_id, "before_key": None},
        )
        assert ranked.status_code == 200

    completed = local_client.post(f"/api/projects/DEMO/sprints/{sprint_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["state"] == "closed"
    assert open_issue["key"] in completed.json()["moved_to_backlog"]
    assert done_issue["key"] not in completed.json()["moved_to_backlog"]

    done_raw = local_client.get(f"/api/issues/{done_issue['key']}").json()["issue"]["raw"]["fields"]["customfield_10020"]
    open_raw = local_client.get(f"/api/issues/{open_issue['key']}").json()["issue"]["raw"]["fields"]["customfield_10020"]
    assert done_raw
    assert open_raw == []

    board = local_client.get("/api/projects/DEMO/board")
    assert board.status_code == 200
    columns = board.json()["columns"]
    assert any(open_issue["key"] in {card["key"] for card in column["issues"]} for column in columns)
    done_column = next(column for column in columns if column["name"] == "Done")
    assert done_issue["key"] in {card["key"] for card in done_column["issues"]}

    sprints = local_client.get("/api/projects/DEMO/sprints")
    assert any(row["id"] == sprint_id and row["state"] == "closed" for row in sprints.json())
