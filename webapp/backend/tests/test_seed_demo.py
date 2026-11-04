from __future__ import annotations

from sqlalchemy import select

from erw import cli
from erw.auth import verify_password
from erw.db import SessionLocal, make_engine
from erw.demo.seed import seed_demo_data
from erw.models import (
    Issue,
    IssueSprint,
    Link,
    Project,
    ProjectMember,
    RiskState,
    Sprint,
    Suggestion,
    User,
)
from erw.settings import Settings


def test_seed_demo_data_basic(session):
    summary = seed_demo_data(session, reset=False)
    assert summary["users"] == 3
    assert summary["projects"] == 1
    assert summary["project_members"] == 2
    assert summary["sprints"] == 1
    assert summary["issues"] == 6
    assert summary["risk_states"] == 5
    assert summary["links"] == 1
    assert summary["suggestions"] == 1

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

    # 3. Sprint
    sprint = session.get(Sprint, 101)
    assert sprint is not None
    assert sprint.board_id == 3
    assert sprint.name == "Sprint 1 - Demo"
    assert sprint.state == "active"
    assert sprint.start_at is not None
    assert sprint.end_at is not None

    # 4. Scenarios & RiskStates
    assert session.query(RiskState).count() == 5
    assert session.query(Issue).count() == 6

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

    link = session.get(Link, ("DEMO-102", "DEMO-105", "is blocked by"))
    assert link is not None
    assert link.direction == "inward"

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
    assert sugg.model == "qwen3:1.7b"
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


def test_seed_demo_idempotency_and_reset(session):
    # First seed
    seed_demo_data(session, reset=False)
    assert session.query(Issue).count() == 6
    assert session.query(RiskState).count() == 5
    assert session.query(User).count() == 3

    # Second seed without reset should succeed and not duplicate
    seed_demo_data(session, reset=False)
    assert session.query(Issue).count() == 6
    assert session.query(RiskState).count() == 5
    assert session.query(User).count() == 3

    # Seed with reset=True should wipe and re-seed without FK errors
    summary_reset = seed_demo_data(session, reset=True)
    assert summary_reset["issues"] == 6
    assert summary_reset["risk_states"] == 5
    assert summary_reset["users"] == 3
    assert session.query(Issue).count() == 6
    assert session.query(RiskState).count() == 5
    assert session.query(User).count() == 3


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
        assert s.query(User).count() == 3
        assert s.query(Issue).count() == 6
        assert s.query(RiskState).count() == 5

    # 2. Run CLI seed-demo --reset
    ret_reset = cli.main(["seed-demo", "--reset"])
    assert ret_reset == 0

    with SessionLocal(bind=engine) as s:
        assert s.query(User).count() == 3
        assert s.query(Issue).count() == 6
        assert s.query(RiskState).count() == 5
