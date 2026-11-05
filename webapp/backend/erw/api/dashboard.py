from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from erw.api.issues import _serialize_issue, _serialize_risk_state
from erw.auth import get_session, require_authenticated_user, require_viewer
from erw.db import utcnow
from erw.models import Action, Issue, ProjectMember, RiskState, User

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
router = dashboard_router


@dashboard_router.get("/stats")
def get_dashboard_stats(
    project: str | None = None,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project_key = project.strip() if project and project.strip() else None

    if project_key is not None:
        require_viewer(project_key, user=user, session=session)
        base_issue_filters = [Issue.deleted_at.is_(None), Issue.project_key == project_key]
    else:
        if not user.is_admin:
            user_projects = list(
                session.scalars(
                    select(ProjectMember.project_key).where(ProjectMember.user_id == user.id)
                ).all()
            )
            if not user_projects:
                return {
                    "project": None,
                    "total_open_issues": 0,
                    "high_risk_count": 0,
                    "med_risk_count": 0,
                    "increased_risk_24h_count": 0,
                    "blocked_count": 0,
                    "critical_count": 0,
                    "resolved_recent_count": 0,
                    "applied_actions_count": 0,
                }
            base_issue_filters = [Issue.deleted_at.is_(None), Issue.project_key.in_(user_projects)]
        else:
            base_issue_filters = [Issue.deleted_at.is_(None)]

    now = utcnow()
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)

    is_open = Issue.status_category != "done"
    is_done = Issue.status_category == "done"

    issue_stmt = (
        select(
            func.count(case((is_open, 1))).label("total_open_issues"),
            func.count(case((and_(is_open, RiskState.level == "HIGH"), 1))).label("high_risk_count"),
            func.count(case((and_(is_open, RiskState.level == "MED"), 1))).label("med_risk_count"),
            func.count(
                case(
                    (
                        and_(
                            is_open,
                            RiskState.level.in_(["HIGH", "MED"]),
                            RiskState.level_raised_at >= h24,
                        ),
                        1,
                    )
                )
            ).label("increased_risk_24h_count"),
            func.count(case((and_(is_open, RiskState.blocked.is_(True)), 1))).label("blocked_count"),
            func.count(case((and_(is_open, RiskState.is_critical.is_(True)), 1))).label("critical_count"),
            func.count(case((and_(is_done, Issue.resolved_at >= d7), 1))).label("resolved_recent_count"),
        )
        .outerjoin(RiskState, Issue.key == RiskState.issue_key)
        .where(*base_issue_filters)
    )
    row = session.execute(issue_stmt).one()

    action_stmt = (
        select(func.count(Action.id))
        .join(Issue, Action.issue_key == Issue.key)
        .where(
            Action.status == "applied",
            Action.created_at >= d7,
            *base_issue_filters,
        )
    )
    applied_actions_count = session.scalar(action_stmt) or 0

    return {
        "project": project_key,
        "total_open_issues": int(row.total_open_issues or 0),
        "high_risk_count": int(row.high_risk_count or 0),
        "med_risk_count": int(row.med_risk_count or 0),
        "increased_risk_24h_count": int(row.increased_risk_24h_count or 0),
        "blocked_count": int(row.blocked_count or 0),
        "critical_count": int(row.critical_count or 0),
        "resolved_recent_count": int(row.resolved_recent_count or 0),
        "applied_actions_count": int(applied_actions_count or 0),
    }


@dashboard_router.get("/issues")
def list_dashboard_issues(
    project: str | None = None,
    level: str | None = None,
    status_category: str = "active",
    is_critical: bool | None = None,
    blocked: bool | None = None,
    assignee_id: str | None = None,
    q: str | None = None,
    sort_by: str = "risk",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project_key = project.strip() if project and project.strip() else None

    if project_key is not None:
        require_viewer(project_key, user=user, session=session)
        conditions = [Issue.deleted_at.is_(None), Issue.project_key == project_key]
    else:
        if not user.is_admin:
            user_projects = list(
                session.scalars(
                    select(ProjectMember.project_key).where(ProjectMember.user_id == user.id)
                ).all()
            )
            if not user_projects:
                return {
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "items": [],
                }
            conditions = [Issue.deleted_at.is_(None), Issue.project_key.in_(user_projects)]
        else:
            conditions = [Issue.deleted_at.is_(None)]

    sc = (status_category or "").strip().lower()
    if sc == "done":
        conditions.append(Issue.status_category == "done")
    elif sc == "all":
        pass
    else:  # default or "active"
        conditions.append(Issue.status_category != "done")

    if level is not None and level.strip():
        conditions.append(RiskState.level == level.strip().upper())

    if is_critical is not None:
        conditions.append(RiskState.is_critical.is_(is_critical))

    if blocked is not None:
        conditions.append(RiskState.blocked.is_(blocked))

    if assignee_id is not None and assignee_id.strip():
        conditions.append(Issue.assignee_id == assignee_id.strip())

    if q is not None and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Issue.key.ilike(pattern), Issue.summary.ilike(pattern)))

    is_asc = (order or "").strip().lower() == "asc"
    sb = (sort_by or "").strip().lower()

    if sb == "deadline":
        primary_sort = (
            RiskState.deadline_at.asc().nulls_last()
            if is_asc
            else RiskState.deadline_at.desc().nulls_last()
        )
        order_clause = [primary_sort, Issue.updated_at.desc().nulls_last(), Issue.key.asc()]
    elif sb == "updated":
        primary_sort = (
            Issue.updated_at.asc().nulls_last()
            if is_asc
            else Issue.updated_at.desc().nulls_last()
        )
        order_clause = [primary_sort, Issue.key.asc()]
    else:  # default "risk"
        risk_rank = case(
            (RiskState.level == "HIGH", 3),
            (RiskState.level == "MED", 2),
            (RiskState.level == "LOW", 1),
            else_=0,
        )
        primary_sort = risk_rank.asc() if is_asc else risk_rank.desc()
        order_clause = [primary_sort, Issue.updated_at.desc().nulls_last(), Issue.key.asc()]

    total = session.scalar(
        select(func.count(Issue.key))
        .outerjoin(RiskState, Issue.key == RiskState.issue_key)
        .where(*conditions)
    ) or 0

    safe_limit = max(0, limit) if limit >= 0 else 50
    safe_offset = max(0, offset)

    rows = session.execute(
        select(Issue, RiskState)
        .outerjoin(RiskState, Issue.key == RiskState.issue_key)
        .where(*conditions)
        .order_by(*order_clause)
        .offset(safe_offset)
        .limit(safe_limit)
    ).all()

    items = []
    for issue, risk_state in rows:
        item = _serialize_issue(issue)
        item["risk"] = _serialize_risk_state(risk_state)
        items.append(item)

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": items,
    }
