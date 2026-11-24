"""P1 KernelSHAP Dual-Head cache + P2 snapshot compare."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from erw.auth import create_session_token, hash_password
from sqlalchemy import select

from erw.models import Issue, IssueShap, Link, Project, ProjectMember, RiskState, User
from erw.pipeline.overview import collect_overview_snapshot
from erw.pipeline.overview_shap import (
    SHAP_METHOD,
    compare_shap_snapshots,
    run_shap_batch,
)
from erw.settings import Settings


@pytest.fixture
def auth_users(session):
    users = {
        "pm": User(
            email="pm@example.com",
            name="PM",
            password_hash=hash_password("x"),
            is_admin=False,
            created_at=datetime.now(UTC),
        ),
        "viewer": User(
            email="viewer@example.com",
            name="Viewer",
            password_hash=hash_password("x"),
            is_admin=False,
            created_at=datetime.now(UTC),
        ),
    }
    session.add_all(users.values())
    session.commit()
    for u in users.values():
        session.refresh(u)
    return users


@pytest.fixture
def demo_world(session, auth_users):
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    session.add(Project(key="DEMO", name="Demo", tracked=True))
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=auth_users["pm"].id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=auth_users["viewer"].id, role="viewer"),
        ]
    )
    issues = []
    for i in range(1, 8):
        issues.append(
            Issue(
                key=f"DEMO-{i}",
                project_key="DEMO",
                summary=f"Issue {i} " + ("blocker" * 5 if i == 2 else "work"),
                status="In Progress" if i % 2 else "To Do",
                status_category="indeterminate",
                assignee_name="Alice" if i <= 4 else "Bob",
                assignee_id="u1" if i <= 4 else "u2",
                priority_norm=0.8 if i <= 3 else 0.2,
                created_at=now - timedelta(days=i + 2),
                updated_at=now,
                duedate=date(2026, 11, 20) if i == 1 else None,
            )
        )
    risks = [
        RiskState(issue_key=f"DEMO-{i}", level="HIGH" if i <= 3 else "MED", delay_value=0.9 - i * 0.08, blocked=(i == 1), updated_at=now)
        for i in range(1, 8)
    ]
    session.add_all(issues + risks)
    session.flush()
    session.add_all(
        [
            Link(source_key="DEMO-2", target_key="DEMO-1", type_std="Block", direction="1"),
            Link(source_key="DEMO-2", target_key="DEMO-3", type_std="Block", direction="1"),
        ]
    )
    session.commit()
    return {"now": now}


def login(client, user: User, settings: Settings) -> None:
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


def test_shap_batch_persists_and_overview_reads(session, settings, demo_world):
    now = demo_world["now"]
    report = run_shap_batch(session, "DEMO", now, settings, nsamples=32, max_issues=10)
    session.commit()
    assert report["n"] >= 5
    assert report["shap_method"] == SHAP_METHOD

    rows = session.scalars(select(IssueShap).where(IssueShap.project_key == "DEMO")).all()
    assert len(rows) == report["n"]
    assert all(r.shap_method == SHAP_METHOD for r in rows)
    assert all(isinstance(r.values, list) and r.values for r in rows)
    assert all("bucket" in r.values[0] for r in rows)

    snap = collect_overview_snapshot(session, "DEMO", now, settings)
    assert snap.shap_available is True
    assert snap.shap_project is not None
    assert snap.shap_project["features"]
    assert snap.shap_project["buckets"]
    assert snap.meta["shap_method"] == SHAP_METHOD
    # At least one explain has waterfall values
    with_shap = [e for e in snap.explain.values() if e.get("shap")]
    assert with_shap
    assert with_shap[0]["shap"]["values"]
    assert any(i.get("top_shap_feature") for i in snap.issues)


def test_shap_compare_needs_two_batches(session, settings, demo_world):
    now = demo_world["now"]
    run_shap_batch(session, "DEMO", now, settings, nsamples=16, max_issues=8)
    session.commit()
    assert compare_shap_snapshots(session, "DEMO") is None

    later = now + timedelta(hours=1)
    # Nudge delay values so second batch differs slightly
    for rs in session.scalars(select(RiskState)).all():
        if rs.delay_value is not None:
            rs.delay_value = min(0.99, float(rs.delay_value) + 0.05)
    session.commit()
    run_shap_batch(session, "DEMO", later, settings, nsamples=16, max_issues=8)
    session.commit()
    cmp = compare_shap_snapshots(session, "DEMO")
    assert cmp is not None
    assert cmp["bucket_delta"]
    assert "note" in cmp


def test_shap_refresh_api_pm_only(client, auth_users, settings, demo_world, monkeypatch):
    queued: list[str] = []

    def _fake_enqueue(project: str) -> None:
        queued.append(project)

    monkeypatch.setattr("erw.jobs.enqueue_overview_shap", _fake_enqueue)

    login(client, auth_users["viewer"], settings)
    assert client.post("/api/projects/DEMO/overview/shap/refresh").status_code == 403

    login(client, auth_users["pm"], settings)
    ok = client.post("/api/projects/DEMO/overview/shap/refresh")
    assert ok.status_code == 200
    assert ok.json()["queued"] is True
    assert queued == ["DEMO"]


def test_compare_api_after_two_batches(client, auth_users, settings, session, demo_world):
    now = demo_world["now"]
    run_shap_batch(session, "DEMO", now, settings, nsamples=16, max_issues=8)
    session.commit()
    run_shap_batch(session, "DEMO", now + timedelta(hours=2), settings, nsamples=16, max_issues=8)
    session.commit()

    login(client, auth_users["viewer"], settings)
    resp = client.get("/api/projects/DEMO/overview/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["bucket_delta"]
