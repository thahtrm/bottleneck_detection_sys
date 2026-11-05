from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erw.auth import hash_password
from erw.db import utcnow
from erw.models import (
    Action,
    Change,
    Issue,
    IssueSprint,
    IssueVersion,
    Link,
    Project,
    ProjectMember,
    RiskState,
    Score,
    Sprint,
    Suggestion,
    User,
)


def _upsert_user(
    session: Session,
    email: str,
    name: str,
    password: str,
    is_admin: bool,
) -> User:
    user = session.execute(select(User).where(func.lower(User.email) == email.lower())).scalar_one_or_none()
    now = utcnow()
    if user is None:
        user = User(
            email=email,
            name=name,
            password_hash=hash_password(password),
            is_admin=is_admin,
            created_at=now,
        )
        session.add(user)
        session.flush()
    else:
        user.name = name
        user.password_hash = hash_password(password)
        user.is_admin = is_admin
        session.flush()
    return user


def seed_demo_data(session: Session, reset: bool = False) -> dict[str, Any]:
    """Seed standard users, demo project configuration, and scenario issues into SQLite."""
    now = utcnow()

    if reset:
        # Delete tables according to foreign key order
        for model in (
            Action,
            Suggestion,
            RiskState,
            Score,
            Link,
            IssueSprint,
            IssueVersion,
            Change,
            Sprint,
            Issue,
            ProjectMember,
            Project,
            User,
        ):
            session.query(model).delete()
        session.flush()

    # 1. Initialize Users & Permissions
    _upsert_user(
        session,
        email="admin@earlyrisk.local",
        name="Hệ Thống Quản Trị",
        password="Admin@123456",
        is_admin=True,
    )
    pm_user = _upsert_user(
        session,
        email="pm@earlyrisk.local",
        name="Nguyễn Văn PM",
        password="Pm@123456",
        is_admin=False,
    )
    viewer_user = _upsert_user(
        session,
        email="viewer@earlyrisk.local",
        name="Trần Thị Viewer",
        password="Viewer@123456",
        is_admin=False,
    )

    # 2. Project DEMO & Members
    project = session.get(Project, "DEMO")
    if project is None:
        project = Project(
            key="DEMO",
            name="Dự án Mẫu Scrum (DEMO)",
            tracked=True,
            status_map={},
            thresholds={"p_delay": 0.39, "criticality": 0.05},
        )
        session.add(project)
    else:
        project.name = "Dự án Mẫu Scrum (DEMO)"
        project.tracked = True
        project.status_map = {}
        project.thresholds = {"p_delay": 0.39, "criticality": 0.05}
    session.flush()

    members_to_assign = [
        (pm_user.id, "pm"),
        (viewer_user.id, "viewer"),
    ]
    for uid, role in members_to_assign:
        m = session.get(ProjectMember, ("DEMO", uid))
        if m is None:
            m = ProjectMember(project_key="DEMO", user_id=uid, role=role)
            session.add(m)
        else:
            m.role = role
    session.flush()

    # 3. Sprint sample
    sprint = session.get(Sprint, 101)
    if sprint is None:
        sprint = Sprint(
            id=101,
            board_id=3,
            name="Sprint 1 - Demo",
            state="active",
            start_at=now - timedelta(days=7),
            end_at=now + timedelta(days=7),
        )
        session.add(sprint)
    else:
        sprint.board_id = 3
        sprint.name = "Sprint 1 - Demo"
        sprint.state = "active"
        sprint.start_at = now - timedelta(days=7)
        sprint.end_at = now + timedelta(days=7)
    session.flush()

    # 4. Scenarios
    # Scenario 1: DEMO-101 (High risk due to sprint elapsed & model T0)
    # Scenario 2: DEMO-102 (Blocked by DEMO-105) & DEMO-105 (Sandbox API credentials)
    # Scenario 3: DEMO-103 (Architectural critical task - TGN Memory)
    # Scenario 4: DEMO-104 (LLM Suggestions cached)
    # Scenario 5: DEMO-106 (Safe / Done task)
    issues_data = [
        {
            "key": "DEMO-101",
            "project_key": "DEMO",
            "summary": "Xây dựng API gateway phân quyền JWT",
            "issuetype": "Story",
            "priority": "High",
            "priority_norm": 0.75,
            "status": "In Progress",
            "status_category": "indeterminate",
            "story_points": 8.0,
            "duedate": now.date() + timedelta(days=2),
            "created_at": now - timedelta(days=5),
            "updated_at": now,
        },
        {
            "key": "DEMO-102",
            "project_key": "DEMO",
            "summary": "Tích hợp cổng thanh toán VNPay và kiểm thử E2E",
            "issuetype": "Bug",
            "priority": "Highest",
            "priority_norm": 1.0,
            "status": "Blocked",
            "status_category": "indeterminate",
            "story_points": 13.0,
            "duedate": now.date() - timedelta(days=1),
            "created_at": now - timedelta(days=10),
            "updated_at": now,
        },
        {
            "key": "DEMO-105",
            "project_key": "DEMO",
            "summary": "Chờ cung cấp sandbox API credentials từ đối tác",
            "issuetype": "Task",
            "priority": "High",
            "priority_norm": 0.75,
            "status": "Open",
            "status_category": "new",
            "story_points": 3.0,
            "duedate": now.date() + timedelta(days=1),
            "created_at": now - timedelta(days=4),
            "updated_at": now,
        },
        {
            "key": "DEMO-103",
            "project_key": "DEMO",
            "summary": "Thiết kế cơ chế cache phân tán Redis cho session cluster",
            "issuetype": "Story",
            "priority": "Medium",
            "priority_norm": 0.5,
            "status": "To Do",
            "status_category": "new",
            "story_points": 5.0,
            "duedate": now.date() + timedelta(days=10),
            "created_at": now - timedelta(days=3),
            "updated_at": now,
        },
        {
            "key": "DEMO-104",
            "project_key": "DEMO",
            "summary": "Refactor module ETL đồng bộ dữ liệu khách hàng",
            "issuetype": "Task",
            "priority": "High",
            "priority_norm": 0.75,
            "status": "In Progress",
            "status_category": "indeterminate",
            "story_points": 8.0,
            "duedate": now.date() + timedelta(days=3),
            "created_at": now - timedelta(days=6),
            "updated_at": now,
        },
        {
            "key": "DEMO-106",
            "project_key": "DEMO",
            "summary": "Cập nhật tài liệu hướng dẫn triển khai Docker",
            "issuetype": "Task",
            "priority": "Low",
            "priority_norm": 0.25,
            "status": "Done",
            "status_category": "done",
            "story_points": 2.0,
            "duedate": now.date() - timedelta(days=1),
            "created_at": now - timedelta(days=8),
            "updated_at": now - timedelta(days=1),
            "resolved_at": now - timedelta(days=1),
        },
    ]

    for item in issues_data:
        issue = session.get(Issue, item["key"])
        if issue is None:
            issue = Issue(**item)
            session.add(issue)
        else:
            for k, v in item.items():
                setattr(issue, k, v)
    session.flush()

    # Link DEMO-101 to Sprint 101
    issue_sprint = session.get(IssueSprint, ("DEMO-101", 101))
    if issue_sprint is None:
        issue_sprint = IssueSprint(issue_key="DEMO-101", sprint_id=101)
        session.add(issue_sprint)
    session.flush()

    # Link DEMO-102 blocked by DEMO-105
    link = session.get(Link, ("DEMO-102", "DEMO-105", "is blocked by"))
    if link is None:
        link = Link(
            source_key="DEMO-102",
            target_key="DEMO-105",
            type_std="is blocked by",
            direction="inward",
        )
        session.add(link)
    else:
        link.direction = "inward"
    session.flush()

    # Risk States
    risk_states_data = [
        {
            "issue_key": "DEMO-101",
            "level": "HIGH",
            "delay_value": 0.82,
            "crit_score": 0.45,
            "is_critical": False,
            "blocked": False,
            "deadline_type": "sprint",
            "deadline_label": "Sprint 1 - Demo",
            "deadline_at": now + timedelta(days=7),
            "factors": [
                {
                    "rule": "sprint_elapsed",
                    "detail": "Sprint đã trôi qua 50% nhưng task còn nhiều việc",
                },
                {
                    "rule": "ml_delay",
                    "detail": "Mô hình T0 dự đoán xác suất trễ 82% (ngưỡng 39%)",
                },
            ],
            "updated_at": now,
        },
        {
            "issue_key": "DEMO-102",
            "level": "HIGH",
            "delay_value": 0.65,
            "crit_score": 0.72,
            "is_critical": True,
            "blocked": True,
            "deadline_type": "due_date",
            "deadline_label": "Quá hạn",
            "deadline_at": now - timedelta(days=1),
            "factors": [
                {
                    "rule": "blocked_stale",
                    "detail": "Bị chặn bởi DEMO-105 hơn 3 ngày chưa xử lý",
                }
            ],
            "updated_at": now,
        },
        {
            "issue_key": "DEMO-103",
            "level": "MED",
            "delay_value": 0.28,
            "crit_score": 0.96,
            "is_critical": True,
            "blocked": False,
            "deadline_type": "due_date",
            "deadline_label": "Đúng hạn",
            "deadline_at": now + timedelta(days=10),
            "factors": [
                {
                    "rule": "tgn_criticality",
                    "detail": "Thuộc top 5% task trọng yếu toàn hệ thống theo đồ thị phụ thuộc TGN",
                }
            ],
            "updated_at": now,
        },
        {
            "issue_key": "DEMO-104",
            "level": "HIGH",
            "delay_value": 0.75,
            "crit_score": 0.55,
            "is_critical": False,
            "blocked": False,
            "deadline_type": "due_date",
            "deadline_label": "Gần đến hạn",
            "deadline_at": now + timedelta(days=3),
            "factors": [
                {
                    "rule": "sprint_elapsed",
                    "detail": "Tiến độ chậm hơn cam kết sprint",
                }
            ],
            "updated_at": now,
        },
        {
            "issue_key": "DEMO-106",
            "level": "LOW",
            "delay_value": 0.08,
            "crit_score": 0.12,
            "is_critical": False,
            "blocked": False,
            "deadline_type": None,
            "deadline_label": None,
            "deadline_at": None,
            "factors": [],
            "updated_at": now,
        },
    ]

    for rs_item in risk_states_data:
        rs = session.get(RiskState, rs_item["issue_key"])
        if rs is None:
            rs = RiskState(**rs_item)
            session.add(rs)
        else:
            for k, v in rs_item.items():
                setattr(rs, k, v)
    session.flush()

    # Pre-cached Suggestion for DEMO-104
    suggestion_output = {
        "summary": "Task có nguy cơ trễ hạn sprint do phụ thuộc nhiều module, đề xuất chia nhỏ và dời deadline",
        "actions": [
            {
                "type": "extend_due_date",
                "description": "Gia hạn thêm 3 ngày để hoàn thiện kiểm thử",
                "params": {"days": 3},
            },
            {
                "type": "split_issue",
                "description": "Tách phần đồng bộ lịch sử thành task riêng",
                "params": {"subtask_summary": "Đồng bộ dữ liệu lịch sử ETL"},
            },
        ],
        "rationale": "Khối lượng công việc 8 story points vượt quá thời gian còn lại trong sprint.",
    }
    suggestion = session.execute(
        select(Suggestion).where(
            Suggestion.issue_key == "DEMO-104",
            Suggestion.model == "qwen3:1.7b",
        )
    ).scalar_one_or_none()

    if suggestion is None:
        suggestion = Suggestion(
            issue_key="DEMO-104",
            issue_updated_at=now,
            model="qwen3:1.7b",
            output=suggestion_output,
            valid=True,
            created_at=now,
        )
        session.add(suggestion)
    else:
        suggestion.issue_updated_at = now
        suggestion.output = suggestion_output
        suggestion.valid = True
    session.flush()

    session.commit()

    return {
        "users": 3,
        "projects": 1,
        "project_members": 2,
        "sprints": 1,
        "issues": len(issues_data),
        "risk_states": len(risk_states_data),
        "links": 1,
        "suggestions": 1,
    }
