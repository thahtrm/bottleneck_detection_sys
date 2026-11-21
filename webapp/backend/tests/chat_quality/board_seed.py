"""Deterministic DEMO board used by chat-quality fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from erw.models import Issue, IssueSprint, Link, Project, RiskState, Sprint

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
PROJECT = "DEMO"


def _issue(
    session: Session,
    key: str,
    *,
    level: str = "MED",
    blocked: bool = False,
    assignee: str | None = "An",
    summary: str = "Việc",
    crit: float = 0.1,
    raised: bool = False,
    cat: str = "indeterminate",
    duedate: date | None = None,
    deadline_at: datetime | None = None,
    critical: bool = False,
    deleted: bool = False,
) -> None:
    session.add(
        Issue(
            key=key,
            project_key=PROJECT,
            summary=summary,
            status_category=cat,
            assignee_name=assignee,
            duedate=duedate,
            created_at=NOW - timedelta(days=3),
            deleted_at=NOW if deleted else None,
        )
    )
    if deleted:
        return
    session.add(
        RiskState(
            issue_key=key,
            level=level,
            blocked=blocked,
            crit_score=crit,
            is_critical=critical,
            deadline_label="hạn mai" if deadline_at or duedate else None,
            deadline_at=deadline_at,
            level_raised_at=NOW - timedelta(hours=2) if raised else None,
            updated_at=NOW,
        )
    )


def seed_quality_board(session: Session) -> datetime:
    """Populate a rich DEMO board; returns frozen `now` for lookups."""
    if session.get(Project, PROJECT) is None:
        session.add(Project(key=PROJECT, name="Demo"))
        session.flush()
    session.add(
        Sprint(
            id=1,
            name="Sprint 24",
            state="active",
            start_at=NOW - timedelta(days=5),
            end_at=NOW + timedelta(days=5),
        )
    )
    # High-risk / blocked cluster
    _issue(session, "DEMO-41", level="HIGH", blocked=True, assignee="Lan", summary="Làm API", crit=0.9, raised=True)
    _issue(session, "DEMO-18", level="LOW", assignee="Minh", summary="Docs", crit=0.05)
    session.add(Link(source_key="DEMO-41", target_key="DEMO-18", type_std="Block", direction="1"))
    for n, crit in enumerate((0.5, 0.4, 0.3, 0.2, 0.15), start=1):
        _issue(session, f"DEMO-{n}", level="MED", assignee="Lan", crit=crit, raised=(n == 1), summary=f"Task {n}")
    # Due / overdue / important / open mix
    _issue(session, "DEMO-6", assignee="Minh", crit=0.12, duedate=date(2026, 11, 5), summary="Due soon")
    _issue(session, "DEMO-7", assignee="An", crit=0.11, duedate=date(2026, 11, 2), summary="Overdue")
    _issue(session, "DEMO-8", assignee="An", crit=0.1, duedate=date(2026, 11, 24), summary="Far due")
    _issue(session, "DEMO-9", level="HIGH", critical=True, assignee="Lan", crit=0.85, summary="Important")
    _issue(session, "DEMO-10", cat="done", assignee="Lan", crit=0.99, summary="Done")
    _issue(session, "DEMO-11", deleted=True, assignee="Lan", summary="Deleted")
    session.flush()
    session.add(IssueSprint(issue_key="DEMO-1", sprint_id=1))
    session.add(IssueSprint(issue_key="DEMO-41", sprint_id=1))
    session.flush()
    return NOW
