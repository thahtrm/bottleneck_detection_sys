from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from erw import cli
from erw.auth import verify_password
from erw.db import SessionLocal, init_db, make_engine, utcnow
from erw.demo.seed import seed_demo_data
from erw.integrations.local_jira import LocalJiraService
from erw.main import create_app
from erw.models import (
    Attachment,
    Change,
    Comment,
    Component,
    Issue,
    IssueComponent,
    IssueSprint,
    IssueVote,
    IssueWatcher,
    Link,
    Project,
    ProjectMember,
    RiskState,
    Sprint,
    Suggestion,
    User,
    Version,
    Worklog,
)
from erw.settings import Settings


def test_seed_demo_data_basic(session):
    summary = seed_demo_data(session, reset=False)
    assert summary["users"] == 8
    assert summary["projects"] == 1
    assert summary["project_members"] == 7
    assert summary["sprints"] == 3
    assert summary["versions"] == 2
    assert summary["components"] == 1
    assert summary["issues"] == 8
    assert summary["risk_states"] == 5
    assert summary["links"] == 1
    assert summary["suggestions"] == 1
    assert summary["comments"] == 1
    assert summary["changes"] == 1
    assert summary["worklogs"] == 1

    # 1. Users & Passwords
    admin = session.execute(select(User).where(User.email == "admin@earlyrisk.local")).scalar_one_or_none()
    assert admin is not None
    assert admin.name == "Hệ Thống Quản Trị"
    assert admin.is_admin is True
    assert verify_password("Admin@123456", admin.password_hash) is True

    pm = session.execute(select(User).where(User.email == "pm@earlyrisk.local")).scalar_one_or_none()
    assert pm is not None
    assert pm.name == "Nguyễn Văn PM"
    assert pm.is_admin is False
    assert verify_password("Pm@123456", pm.password_hash) is True

    viewer = session.execute(select(User).where(User.email == "viewer@earlyrisk.local")).scalar_one_or_none()
    assert viewer is not None
    assert viewer.name == "Trần Thị Viewer"
    assert viewer.is_admin is False
    assert verify_password("Viewer@123456", viewer.password_hash) is True

    # 2. Project & Members
    project = session.get(Project, "DEMO")
    assert project is not None
    assert project.name == "Dự án Mẫu Scrum (DEMO)"
    assert project.tracked is True
    assert project.thresholds == {"p_delay": 0.39, "criticality": 0.05}

    pm_member = session.get(ProjectMember, ("DEMO", pm.id))
    assert pm_member is not None
    assert pm_member.role == "pm"

    viewer_member = session.get(ProjectMember, ("DEMO", viewer.id))
    assert viewer_member is not None
    assert viewer_member.role == "viewer"

    developers = []
    for email in (
        "an@earlyrisk.local",
        "binh@earlyrisk.local",
        "chi@earlyrisk.local",
        "dung@earlyrisk.local",
    ):
        dev = session.execute(select(User).where(User.email == email)).scalar_one()
        assert verify_password("Dev@123456", dev.password_hash) is True
        member = session.get(ProjectMember, ("DEMO", dev.id))
        assert member is not None
        assert member.role == "developer"
        developers.append(dev)
    assert len(developers) >= 4

    qa = session.execute(select(User).where(User.email == "qa@earlyrisk.local")).scalar_one()
    assert qa.job_title == "QA Engineer"
    assert verify_password("Qa@123456", qa.password_hash) is True
    qa_member = session.get(ProjectMember, ("DEMO", qa.id))
    assert qa_member is not None
    assert qa_member.role == "viewer"

    # 3. Sprint
    sprint = session.get(Sprint, 101)
    assert sprint is not None
    assert sprint.board_id == 3
    assert sprint.name == "Sprint 1 - Demo"
    assert sprint.state == "active"
    assert sprint.start_at is not None
    assert sprint.end_at is not None
    states = {row.state for row in session.scalars(select(Sprint))}
    assert {"closed", "active", "future"} <= states

    versions = list(session.scalars(select(Version).where(Version.project_key == "DEMO")))
    assert any(v.released for v in versions)
    assert any(not v.released for v in versions)

    component = session.execute(select(Component).where(Component.project_key == "DEMO")).scalar_one()
    assert component.name == "API"
    assert session.get(IssueComponent, ("DEMO-101", component.id)) is not None

    # 4. Scenarios & RiskStates
    assert session.query(RiskState).count() == 5
    assert session.query(Issue).count() == 8
    types = {row.issuetype for row in session.scalars(select(Issue).where(Issue.project_key == "DEMO"))}
    assert {"Epic", "Story", "Bug", "Sub-task"} <= types
    subtask = session.get(Issue, "DEMO-117")
    assert subtask is not None
    assert subtask.parent_key == "DEMO-101"
    assert session.get(Issue, "DEMO-101").issuetype == "Story"
    active_ids = {row.id for row in session.scalars(select(Sprint).where(Sprint.state == "active"))}
    story_sprints = session.scalars(select(IssueSprint).where(IssueSprint.issue_key == "DEMO-101")).all()
    assert any(row.sprint_id in active_ids for row in story_sprints)
    assert session.get(Issue, "DEMO-103").issuetype == "Story"
    assert session.scalars(select(IssueSprint).where(IssueSprint.issue_key == "DEMO-103")).all() == []

    # Scenario 1 (DEMO-101: Sprint elapsed & ML Delay)
    iss_101 = session.get(Issue, "DEMO-101")
    assert iss_101 is not None
    assert iss_101.summary == "Xây dựng API gateway phân quyền JWT"
    assert iss_101.status == "In Progress"
    assert iss_101.story_points == 8.0
    rs_101 = session.get(RiskState, "DEMO-101")
    assert rs_101 is not None
    assert rs_101.level == "HIGH"
    assert rs_101.delay_value == 0.82
    assert rs_101.crit_score == 0.45
    assert rs_101.is_critical is False
    assert rs_101.blocked is False
    assert rs_101.deadline_type == "sprint"
    assert rs_101.deadline_label == "Sprint 1 - Demo"
    assert session.get(IssueSprint, ("DEMO-101", 101)) is not None

    # Scenario 2 (DEMO-102: Blocked by DEMO-105)
    iss_102 = session.get(Issue, "DEMO-102")
    assert iss_102 is not None
    assert iss_102.status == "Blocked"
    assert iss_102.priority == "Highest"
    assert iss_102.story_points == 13.0
    rs_102 = session.get(RiskState, "DEMO-102")
    assert rs_102 is not None
    assert rs_102.level == "HIGH"
    assert rs_102.delay_value == 0.65
    assert rs_102.crit_score == 0.72
    assert rs_102.is_critical is True
    assert rs_102.blocked is True
    assert rs_102.deadline_label == "Quá hạn"

    link = session.get(Link, ("DEMO-102", "DEMO-105", "Block"))
    assert link is not None
    assert link.direction == "0"

    iss_105 = session.get(Issue, "DEMO-105")
    assert iss_105 is not None
    assert iss_105.summary == "Chờ cung cấp sandbox API credentials từ đối tác"
    assert iss_105.status == "Open"
    assert iss_105.status_category == "new"

    # Scenario 3 (DEMO-103: Critical TGN Memory)
    iss_103 = session.get(Issue, "DEMO-103")
    assert iss_103 is not None
    assert iss_103.status == "To Do"
    rs_103 = session.get(RiskState, "DEMO-103")
    assert rs_103 is not None
    assert rs_103.level == "MED"
    assert rs_103.delay_value == 0.28
    assert rs_103.crit_score == 0.96
    assert rs_103.is_critical is True
    assert rs_103.blocked is False

    # Scenario 4 (DEMO-104: LLM Suggestion cached)
    iss_104 = session.get(Issue, "DEMO-104")
    assert iss_104 is not None
    assert iss_104.status == "In Progress"
    rs_104 = session.get(RiskState, "DEMO-104")
    assert rs_104 is not None
    assert rs_104.level == "HIGH"
    assert rs_104.delay_value == 0.75

    sugg = session.execute(select(Suggestion).where(Suggestion.issue_key == "DEMO-104")).scalar_one_or_none()
    assert sugg is not None
    assert sugg.model == "gemma4:e4b"
    assert sugg.valid is True
    assert "actions" in sugg.output
    assert len(sugg.output["actions"]) == 2
    assert sugg.output["actions"][0]["type"] == "extend_due_date"
    assert sugg.output["actions"][1]["type"] == "split_issue"

    # Scenario 5 (DEMO-106: Done / Low risk)
    iss_106 = session.get(Issue, "DEMO-106")
    assert iss_106 is not None
    assert iss_106.status == "Done"
    assert iss_106.status_category == "done"
    assert iss_106.resolved_at is not None
    rs_106 = session.get(RiskState, "DEMO-106")
    assert rs_106 is not None
    assert rs_106.level == "LOW"
    assert rs_106.delay_value == 0.08
    assert rs_106.crit_score == 0.12

    pm_account = pm.account_id
    comment = session.scalars(select(Comment).where(Comment.issue_key == "DEMO-101")).first()
    assert comment is not None
    assert pm_account is not None
    assert f"@{pm_account}" in comment.body
    assert session.query(Change).count() >= 1
    assert session.query(Worklog).count() >= 1


def _demo_keys_and_emails(session):
    keys = session.scalars(select(Issue.key).where(Issue.project_key == "DEMO").order_by(Issue.key)).all()
    emails = session.scalars(select(User.email).order_by(User.email)).all()
    return list(keys), list(emails)


def test_seed_demo_idempotency_and_reset(session):
    # First seed
    seed_demo_data(session, reset=False)
    assert session.query(Issue).count() == 8
    assert session.query(RiskState).count() == 5
    assert session.query(User).count() == 8

    # Second seed without reset should succeed and not duplicate
    seed_demo_data(session, reset=False)
    assert session.query(Issue).count() == 8
    assert session.query(RiskState).count() == 5
    assert session.query(User).count() == 8

    admin = session.execute(select(User).where(User.email == "admin@earlyrisk.local")).scalar_one()
    now = utcnow()
    session.add(Attachment(
        issue_key="DEMO-101",
        author_id=admin.account_id,
        author_name=admin.name,
        filename="note.txt",
        mime_type="text/plain",
        size_bytes=4,
        storage_path="demo/note.txt",
        created_at=now,
    ))
    session.add(IssueWatcher(issue_key="DEMO-101", user_id=admin.id, created_at=now))
    session.add(IssueVote(issue_key="DEMO-101", user_id=admin.id, created_at=now))
    session.commit()

    # Seed with reset=True should wipe children, then users and projects, without FK errors
    summary_reset = seed_demo_data(session, reset=True)
    assert summary_reset["issues"] == 8
    assert summary_reset["risk_states"] == 5
    assert summary_reset["users"] == 8
    assert session.query(Issue).count() == 8
    assert session.query(RiskState).count() == 5
    assert session.query(User).count() == 8
    assert session.query(Attachment).count() == 0
    assert session.query(IssueWatcher).count() == 0
    assert session.query(IssueVote).count() == 0

    first_keys, first_emails = _demo_keys_and_emails(session)
    second = seed_demo_data(session, reset=True)
    second_keys, second_emails = _demo_keys_and_emails(session)
    assert second["issues"] == summary_reset["issues"]
    assert second_keys == first_keys
    assert second_emails == first_emails


def test_block_link_marks_issue_blocked(session):
    seed_demo_data(session, reset=True)
    LocalJiraService.evaluate_with_neighbors(session, ["DEMO-102"], utcnow(), None)
    risk = session.get(RiskState, "DEMO-102")
    assert risk is not None
    assert risk.blocked is True


def test_cli_seed_demo(tmp_path, monkeypatch):
    db_file = tmp_path / "test_cli_seed.db"
    cli_settings = Settings(
        _env_file=None,
        db_url=f"sqlite:///{db_file}",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: cli_settings)

    # 1. Run CLI seed-demo
    ret = cli.main(["seed-demo"])
    assert ret == 0

    engine = make_engine(cli_settings.db_url)
    with SessionLocal(bind=engine) as s:
        assert s.query(User).count() == 8
        assert s.query(Issue).count() == 8
        assert s.query(RiskState).count() == 5

    # 2. Run CLI seed-demo --reset
    ret_reset = cli.main(["seed-demo", "--reset"])
    assert ret_reset == 0

    with SessionLocal(bind=engine) as s:
        assert s.query(User).count() == 8
        assert s.query(Issue).count() == 8
        assert s.query(RiskState).count() == 5


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


def test_admin_demo_reset_is_local_only_and_idempotent(local_client, local_session, client, session):
    seed_demo_data(session, reset=True)
    cloud_login = client.post(
        "/api/auth/login",
        json={"email": "admin@earlyrisk.local", "password": "Admin@123456"},
    )
    assert cloud_login.status_code == 200
    forbidden = client.post("/api/admin/demo/reset")
    assert forbidden.status_code == 403

    seed_demo_data(local_session, reset=True)
    login = local_client.post(
        "/api/auth/login",
        json={"email": "admin@earlyrisk.local", "password": "Admin@123456"},
    )
    assert login.status_code == 200
    pm_login = local_client.post(
        "/api/auth/login",
        json={"email": "pm@earlyrisk.local", "password": "Pm@123456"},
    )
    assert pm_login.status_code == 200
    denied = local_client.post("/api/admin/demo/reset")
    assert denied.status_code == 403

    local_client.post(
        "/api/auth/login",
        json={"email": "admin@earlyrisk.local", "password": "Admin@123456"},
    )
    first = local_client.post("/api/admin/demo/reset")
    assert first.status_code == 200
    body = first.json()
    assert body["users"] == 8
    assert body["issues"] == 8
    local_session.expire_all()
    first_keys = local_session.scalars(
        select(Issue.key).where(Issue.project_key == "DEMO").order_by(Issue.key)
    ).all()

    second = local_client.post("/api/admin/demo/reset")
    assert second.status_code == 200
    local_session.expire_all()
    second_keys = local_session.scalars(
        select(Issue.key).where(Issue.project_key == "DEMO").order_by(Issue.key)
    ).all()
    assert list(second_keys) == list(first_keys)
    assert second.json()["issues"] == body["issues"]
