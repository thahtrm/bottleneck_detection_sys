from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from erw.api.issues import _serialize_issue, _serialize_risk_state
from erw.auth import get_session, require_authenticated_user, require_viewer
from erw.db import utcnow
from erw.models import Action, Issue, Link, ProjectMember, RiskState, User

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


@dashboard_router.get("/graph")
def get_dashboard_graph(
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
                    "summary": {
                        "total_nodes": 0,
                        "total_edges": 0,
                        "bottlenecks_count": 0,
                        "overdue_count": 0,
                        "high_risk_count": 0,
                        "blocked_count": 0,
                        "critical_count": 0,
                        "done_count": 0,
                    },
                    "nodes": [],
                    "edges": [],
                }
            base_issue_filters = [Issue.deleted_at.is_(None), Issue.project_key.in_(user_projects)]
        else:
            base_issue_filters = [Issue.deleted_at.is_(None)]

    # Fetch issues with RiskState
    stmt = (
        select(Issue, RiskState)
        .outerjoin(RiskState, Issue.key == RiskState.issue_key)
        .where(*base_issue_filters)
    )
    rows = session.execute(stmt).all()

    issue_dict: dict[str, tuple[Issue, RiskState | None]] = {
        issue.key: (issue, rs) for issue, rs in rows
    }
    issue_keys = set(issue_dict.keys())

    if not issue_keys:
        return {
            "project": project_key,
            "summary": {
                "total_nodes": 0,
                "total_edges": 0,
                "bottlenecks_count": 0,
                "overdue_count": 0,
                "high_risk_count": 0,
                "blocked_count": 0,
                "critical_count": 0,
                "done_count": 0,
            },
            "nodes": [],
            "edges": [],
        }

    # Fetch links referencing any of the issues
    link_stmt = select(Link).where(
        (Link.source_key.in_(issue_keys)) | (Link.target_key.in_(issue_keys))
    )
    raw_links = list(session.scalars(link_stmt).all())

    # Check if external referenced issues exist in DB and load them
    external_keys = ({l.source_key for l in raw_links} | {l.target_key for l in raw_links}) - issue_keys
    if external_keys:
        extra_rows = session.execute(
            select(Issue, RiskState)
            .outerjoin(RiskState, Issue.key == RiskState.issue_key)
            .where(Issue.key.in_(external_keys), Issue.deleted_at.is_(None))
        ).all()
        for issue, rs in extra_rows:
            issue_dict[issue.key] = (issue, rs)
            issue_keys.add(issue.key)

    # Normalize links direction (Blocker/Prerequisite -> Blocked/Dependent)
    blocking_map: dict[str, set[str]] = defaultdict(set)
    blocked_by_map: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    edges_list = []
    seen_edge_ids = set()

    for link in raw_links:
        s_key = link.source_key
        t_key = link.target_key
        if s_key not in issue_keys or t_key not in issue_keys:
            continue

        raw_type = (link.type_std or "").strip()
        type_lower = raw_type.lower()
        is_blocking = False
        edge_label = raw_type or "Liên kết"

        # Determine normalized dependency flow (from prerequisite -> to dependent)
        if type_lower in ("is blocked by", "blocked by", "depends on") or link.direction == "inward":
            from_key = t_key
            to_key = s_key
            is_blocking = True
            edge_label = "Chặn"
        elif type_lower in ("blocks", "is depended on by") or link.direction == "outward":
            from_key = s_key
            to_key = t_key
            is_blocking = True
            edge_label = "Chặn"
        else:
            from_key = s_key
            to_key = t_key
            if "block" in type_lower:
                is_blocking = True
                edge_label = "Chặn"
            elif "relat" in type_lower:
                edge_label = "Liên quan"
            elif "cause" in type_lower:
                edge_label = "Gây ra"
            elif "duplicat" in type_lower:
                edge_label = "Trùng lặp"

        edge_id = f"{from_key}->{to_key}"
        if edge_id in seen_edge_ids:
            continue
        seen_edge_ids.add(edge_id)

        blocking_map[from_key].add(to_key)
        blocked_by_map[to_key].add(from_key)
        out_degree[from_key] += 1
        in_degree[to_key] += 1

        edges_list.append({
            "id": edge_id,
            "from": from_key,
            "to": to_key,
            "label": edge_label,
            "type_std": raw_type,
            "direction": link.direction,
            "is_blocking": is_blocking,
        })

    # Calculate status, overdue, and bottlenecks
    now = utcnow()
    today = now.date()

    overdue_keys = set()
    overdue_days_map: dict[str, int] = {}
    bottleneck_keys = set()
    bottleneck_score_map: dict[str, float] = {}

    for key, (issue, rs) in issue_dict.items():
        is_done = issue.status_category == "done"
        is_od = False
        od_days = 0

        if not is_done:
            if issue.duedate and issue.duedate < today:
                is_od = True
                od_days = (today - issue.duedate).days
            elif rs and rs.deadline_at:
                dl_date = rs.deadline_at.date() if isinstance(rs.deadline_at, datetime) else rs.deadline_at
                if dl_date < today:
                    is_od = True
                    od_days = max(od_days, (today - dl_date).days)

        if is_od:
            overdue_keys.add(key)
            overdue_days_map[key] = od_days

        # Bottleneck detection
        blocks_count = len(blocking_map[key])
        is_high_risk = rs.level == "HIGH" if rs else False
        is_crit = bool(rs.is_critical) if rs else False
        is_blked = bool(rs.blocked) if rs else False

        is_bn = (
            not is_done
            and blocks_count >= 1
            and (blocks_count >= 2 or is_od or is_high_risk or is_crit or is_blked)
        )
        if is_bn:
            bottleneck_keys.add(key)
            mult = 1.0
            if is_od:
                mult += 1.5 + min(od_days * 0.2, 2.0)
            if is_high_risk:
                mult += 1.0
            if is_crit:
                mult += 1.5
            if is_blked:
                mult += 0.8
            bottleneck_score_map[key] = round(blocks_count * mult, 2)

    # Compute Critical Path among open tasks (DAG longest path)
    open_keys = {k for k, (iss, _) in issue_dict.items() if iss.status_category != "done"}
    open_in_degree = {k: 0 for k in open_keys}
    for u in open_keys:
        for v in blocking_map[u]:
            if v in open_keys:
                open_in_degree[v] = open_in_degree.get(v, 0) + 1

    queue = deque([k for k, deg in open_in_degree.items() if deg == 0])
    dist = {k: 1 for k in open_keys}
    pred: dict[str, str | None] = {k: None for k in open_keys}

    while queue:
        curr = queue.popleft()
        for nxt in blocking_map[curr]:
            if nxt in open_keys:
                if dist[curr] + 1 > dist[nxt]:
                    dist[nxt] = dist[curr] + 1
                    pred[nxt] = curr
                open_in_degree[nxt] -= 1
                if open_in_degree[nxt] == 0:
                    queue.append(nxt)

    critical_path_keys = set()
    if dist:
        max_dist = max(dist.values())
        if max_dist >= 2:
            for end_node, d in dist.items():
                if d == max_dist:
                    step: str | None = end_node
                    while step is not None:
                        critical_path_keys.add(step)
                        step = pred.get(step)

    # Enrich edges with highlight attributes
    for edge in edges_list:
        from_k = edge["from"]
        to_k = edge["to"]
        edge["is_bottleneck_edge"] = from_k in bottleneck_keys
        edge["is_overdue_edge"] = from_k in overdue_keys
        edge["is_critical_path"] = from_k in critical_path_keys and to_k in critical_path_keys

    # Build node objects
    nodes_list = []
    high_risk_count = 0
    blocked_count = 0
    critical_count = 0
    done_count = 0

    for key, (issue, rs) in issue_dict.items():
        is_done = issue.status_category == "done"
        if is_done:
            done_count += 1
        level = rs.level if rs and rs.level else "LOW"
        if not is_done and level == "HIGH":
            high_risk_count += 1
        is_crit = bool(rs.is_critical) if rs else False
        if not is_done and is_crit:
            critical_count += 1
        is_blked = bool(rs.blocked) if rs else False
        if not is_done and is_blked:
            blocked_count += 1

        is_od = key in overdue_keys
        od_days = overdue_days_map.get(key, 0)
        is_bn = key in bottleneck_keys
        bn_score = bottleneck_score_map.get(key, 0.0)

        nodes_list.append({
            "id": key,
            "key": key,
            "project_key": issue.project_key,
            "summary": issue.summary,
            "issuetype": issue.issuetype,
            "priority": issue.priority,
            "priority_norm": issue.priority_norm,
            "status": issue.status,
            "status_category": issue.status_category,
            "assignee_id": issue.assignee_id,
            "assignee_name": issue.assignee_name,
            "duedate": issue.duedate.isoformat() if issue.duedate else None,
            "story_points": issue.story_points,
            "level": level,
            "delay_value": rs.delay_value if rs and rs.delay_value is not None else 0.0,
            "crit_score": rs.crit_score if rs and rs.crit_score is not None else 0.0,
            "is_critical": is_crit,
            "blocked": is_blked,
            "deadline_label": rs.deadline_label if rs else None,
            "deadline_at": rs.deadline_at.isoformat() if rs and rs.deadline_at else None,
            "factors": rs.factors if rs and rs.factors else [],
            "is_overdue": is_od,
            "overdue_days": od_days,
            "is_bottleneck": is_bn,
            "bottleneck_score": bn_score,
            "blocks_count": len(blocking_map[key]),
            "blocked_by_count": len(blocked_by_map[key]),
            "blocks_keys": sorted(list(blocking_map[key])),
            "blocked_by_keys": sorted(list(blocked_by_map[key])),
            "in_degree": in_degree[key],
            "out_degree": out_degree[key],
            "is_critical_path": key in critical_path_keys,
        })

    nodes_list.sort(key=lambda n: (n["is_bottleneck"], n["is_overdue"], n["delay_value"]), reverse=True)

    summary = {
        "total_nodes": len(nodes_list),
        "total_edges": len(edges_list),
        "bottlenecks_count": len(bottleneck_keys),
        "overdue_count": len(overdue_keys),
        "high_risk_count": high_risk_count,
        "blocked_count": blocked_count,
        "critical_count": critical_count,
        "done_count": done_count,
    }

    return {
        "project": project_key,
        "summary": summary,
        "nodes": nodes_list,
        "edges": edges_list,
    }
