from __future__ import annotations

from datetime import UTC, datetime

import pytest

from erw import jobs
from erw.auth import create_session_token, hash_password
from erw.db import utcnow
from erw.jobs import pregenerate_top_risky_suggestions
from erw.kv import set_kv
from erw.ml.batch import _batch_lock
from erw.models import Issue, Project, RiskState, Suggestion, User


@pytest.fixture
def auth_users(session):
    u_admin = User(
        email="admin@example.com",
        name="Admin User",
        password_hash=hash_password("admin_pass"),
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    u_pm = User(
        email="pm@example.com",
        name="PM User",
        password_hash=hash_password("pm_pass"),
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    u_viewer = User(
        email="viewer@example.com",
        name="Viewer User",
        password_hash=hash_password("viewer_pass"),
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    session.add_all([u_admin, u_pm, u_viewer])
    session.commit()
    for u in (u_admin, u_pm, u_viewer):
        session.refresh(u)
    return {"admin": u_admin, "pm": u_pm, "viewer": u_viewer}


def _login(client, user: User, settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


# ---------------------------------------------------------------------------
# 1. GET /api/admin/settings
# ---------------------------------------------------------------------------


def test_get_settings_unauthenticated(client):
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 401


def test_get_settings_forbidden_for_non_admin(client, auth_users, settings):
    _login(client, auth_users["pm"], settings)
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 403

    _login(client, auth_users["viewer"], settings)
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 403


def test_get_settings_success(client, auth_users, settings, session):
    _login(client, auth_users["admin"], settings)

    set_kv(session, "last_webhook_at", "2026-11-04T05:00:00Z")
    set_kv(session, "last_catch_up_at", "2026-11-04T05:05:00Z")
    session.add(Project(key="ALPHA", name="Alpha Project", tracked=True))
    session.add(Project(key="BETA", name="Beta Project", tracked=False))
    session.commit()

    resp = client.get("/api/admin/settings")
    assert resp.status_code == 200
    data = resp.json()

    assert data["jira_base_url"] == settings.jira_base_url
    assert data["webhook_url"] == f"{settings.public_base_url}/webhooks/jira/***"
    assert data["last_webhook_at"] == "2026-11-04T05:00:00Z"
    assert data["last_catch_up_at"] == "2026-11-04T05:05:00Z"
    assert data["llm_model"] == "gemma4:e4b"
    assert data["delay_threshold"] == 0.39
    assert data["criticality_top_pct"] == 0.05
    assert data["model_mode"] == settings.model_mode
    assert data["tracked_projects"] == ["ALPHA"]


def test_get_settings_unconfigured_webhook_empty(client, auth_users, settings):
    settings.jira_webhook_secret = ""
    _login(client, auth_users["admin"], settings)

    resp = client.get("/api/admin/settings")
    assert resp.status_code == 200
    assert resp.json()["webhook_url"] == ""


# ---------------------------------------------------------------------------
# 2. POST /api/admin/settings
# ---------------------------------------------------------------------------


def test_post_settings_unauthenticated(client):
    resp = client.post("/api/admin/settings", json={"delay_threshold": 0.45})
    assert resp.status_code == 401


def test_post_settings_forbidden_for_non_admin(client, auth_users, settings):
    _login(client, auth_users["pm"], settings)
    resp = client.post("/api/admin/settings", json={"delay_threshold": 0.45})
    assert resp.status_code == 403


def test_post_settings_updates_kv_and_reflects_in_get(client, auth_users, settings):
    _login(client, auth_users["admin"], settings)

    payload = {
        "delay_threshold": 0.48,
        "criticality_top_pct": 0.08,
        "llm_model": "llama3:8b",
    }
    resp = client.post("/api/admin/settings", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["delay_threshold"] == 0.48
    assert data["criticality_top_pct"] == 0.08
    assert data["llm_model"] == "llama3:8b"

    # Subsequent GET reflects the updated values
    get_resp = client.get("/api/admin/settings")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["delay_threshold"] == 0.48
    assert get_data["criticality_top_pct"] == 0.08
    assert get_data["llm_model"] == "llama3:8b"

    # Partial update only changes specified field
    part_resp = client.post("/api/admin/settings", json={"delay_threshold": 0.55})
    assert part_resp.status_code == 200
    part_data = part_resp.json()
    assert part_data["delay_threshold"] == 0.55
    assert part_data["criticality_top_pct"] == 0.08
    assert part_data["llm_model"] == "llama3:8b"


# ---------------------------------------------------------------------------
# 3. POST /api/admin/run-batch
# ---------------------------------------------------------------------------


def test_post_run_batch_unauthenticated(client):
    resp = client.post("/api/admin/run-batch")
    assert resp.status_code == 401


def test_post_run_batch_forbidden_for_non_admin(client, auth_users, settings):
    _login(client, auth_users["pm"], settings)
    resp = client.post("/api/admin/run-batch")
    assert resp.status_code == 403


def test_post_run_batch_success(client, auth_users, settings, monkeypatch):
    _login(client, auth_users["admin"], settings)
    calls = []
    monkeypatch.setattr(jobs.executor, "submit", lambda fn: calls.append(fn))

    resp = client.post("/api/admin/run-batch")
    assert resp.status_code == 202
    assert resp.json() == {
        "status": "started",
        "message": "Batch scoring started in background",
    }
    assert len(calls) == 1
    assert calls[0] == jobs._morning_body


def test_post_run_batch_busy_returns_409(client, auth_users, settings):
    _login(client, auth_users["admin"], settings)

    with _batch_lock:
        resp = client.post("/api/admin/run-batch")

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "status": "busy",
        "message": "Batch scoring is already running",
    }


# ---------------------------------------------------------------------------
# 4. pregenerate_top_risky_suggestions
# ---------------------------------------------------------------------------


def test_pregenerate_top_risky_suggestions_ranking_and_caching(session, settings, monkeypatch):
    now = utcnow()
    session.add(Project(key="DEMO", name="Demo", tracked=True))

    # Helper to insert an issue + risk_state
    def _add_issue(key, level, crit, delay, status_cat="indeterminate", deleted=False):
        issue = Issue(
            key=key,
            project_key="DEMO",
            summary=f"Summary {key}",
            status="In Progress" if status_cat != "done" else "Done",
            status_category=status_cat,
            updated_at=now,
            created_at=now,
            deleted_at=now if deleted else None,
        )
        risk = RiskState(
            issue_key=key,
            level=level,
            crit_score=crit,
            delay_value=delay,
            updated_at=now,
        )
        session.add_all([issue, risk])

    # 3 HIGH risk open issues
    _add_issue("DEMO-1", "HIGH", 0.90, 0.70)
    _add_issue("DEMO-2", "HIGH", 0.95, 0.60)
    _add_issue("DEMO-3", "HIGH", 0.80, 0.85)

    # 3 MED risk open issues
    _add_issue("DEMO-4", "MED", 0.99, 0.50)
    _add_issue("DEMO-5", "MED", 0.88, 0.40)
    _add_issue("DEMO-6", "MED", 0.70, 0.30)  # should rank 6th, not in top 5!

    # Excluded issues
    _add_issue("DEMO-DONE", "HIGH", 0.99, 0.99, status_cat="done")
    _add_issue("DEMO-DEL", "HIGH", 0.99, 0.99, deleted=True)
    _add_issue("DEMO-LOW", "LOW", 0.99, 0.99)
    session.commit()

    generated_keys: list[str] = []

    def mock_generate(s, key, st):
        generated_keys.append(key)
        # Create a real valid Suggestion in DB matching issue updated_at
        issue = s.get(Issue, key)
        sugg = Suggestion(
            issue_key=key,
            issue_updated_at=issue.updated_at,
            model=st.llm_model,
            output={"summary": f"Sugg for {key}", "actions": []},
            valid=True,
            created_at=utcnow(),
        )
        s.add(sugg)
        s.commit()
        return sugg

    monkeypatch.setattr("erw.jobs.generate_suggestion", mock_generate)

    # First run: should generate top 5
    count = pregenerate_top_risky_suggestions(session, settings)
    assert count == 5
    # Ranking order:
    # 1. HIGH sorted by crit_score desc: DEMO-2 (0.95), DEMO-1 (0.90), DEMO-3 (0.80)
    # 2. MED sorted by crit_score desc: DEMO-4 (0.99), DEMO-5 (0.88)
    assert generated_keys == ["DEMO-2", "DEMO-1", "DEMO-3", "DEMO-4", "DEMO-5"]

    # Second run: suggestions are cached, so count must be 0
    generated_keys.clear()
    count_cached = pregenerate_top_risky_suggestions(session, settings)
    assert count_cached == 0
    assert generated_keys == []


def test_pregenerate_top_risky_suggestions_multi_project(session, settings, monkeypatch):
    now = utcnow()
    session.add(Project(key="PRJ1", name="Proj 1", tracked=True))
    session.add(Project(key="PRJ2", name="Proj 2", tracked=True))
    session.add(Project(key="SKIP", name="Proj Skip", tracked=False))

    def _add(key, prj):
        issue = Issue(
            key=key,
            project_key=prj,
            status_category="indeterminate",
            updated_at=now,
            created_at=now,
        )
        risk = RiskState(issue_key=key, level="HIGH", crit_score=0.9, delay_value=0.5)
        session.add_all([issue, risk])

    _add("PRJ1-1", "PRJ1")
    _add("PRJ1-2", "PRJ1")
    _add("PRJ2-1", "PRJ2")
    _add("SKIP-1", "SKIP")
    session.commit()

    generated: list[str] = []

    def mock_gen(s, key, st):
        generated.append(key)
        issue = s.get(Issue, key)
        sugg = Suggestion(
            issue_key=key,
            issue_updated_at=issue.updated_at,
            model=st.llm_model,
            output={},
            valid=True,
            created_at=utcnow(),
        )
        s.add(sugg)
        s.commit()
        return sugg

    monkeypatch.setattr("erw.jobs.generate_suggestion", mock_gen)

    count = pregenerate_top_risky_suggestions(session, settings)
    assert count == 3
    assert set(generated) == {"PRJ1-1", "PRJ1-2", "PRJ2-1"}
    assert "SKIP-1" not in generated


def test_morning_body_invokes_pregenerate(settings, engine, monkeypatch):
    jobs.configure(settings, engine)
    calls = []

    monkeypatch.setattr(jobs, "run_catch_up", lambda: calls.append("catch_up"))
    monkeypatch.setattr("erw.ml.batch.LibraryScorers", lambda s: object())
    monkeypatch.setattr("erw.ml.batch.make_unload_llm", lambda s: (lambda: None))
    monkeypatch.setattr("erw.ml.batch.run_model_batch", lambda *a, **k: calls.append("batch") or {})
    monkeypatch.setattr(
        jobs,
        "pregenerate_top_risky_suggestions",
        lambda session, st: (calls.append("pregenerate") or 0),
    )

    jobs._morning_body()
    assert calls == ["catch_up", "batch", "pregenerate"]
