from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from erw.api.issues import _serialize_issue, _serialize_risk_state
from erw.auth import get_session, require_authenticated_user, require_viewer
from erw.db import utcnow
from erw.models import (
    Action,
    Change,
    Issue,
    IssueSprint,
    IssueVersion,
    Link,
    ProjectMember,
    RiskState,
    Sprint,
    User,
    Version,
)

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


UNASSIGNED_PERSON_ID = "person:__unassigned__"
_BLOCKER_FIRST = frozenset({"blocks", "is depended on by"})
_BLOCKER_SECOND = frozenset({"is blocked by", "blocked by", "depends on"})
_INWARD = frozenset({"0", "inward"})
_EDGE_LABELS = {"blocks": "Chặn", "relates": "Liên quan", "duplicates": "Trùng lặp", "causes": "Gây ra"}


def _classify_link(type_std: str, direction: str | None) -> tuple[str, bool]:
    """Return (edge kind, True when the link's target is the blocker)."""
    t = type_std.strip().lower()
    if t in _BLOCKER_SECOND:
        return "blocks", True
    if t in _BLOCKER_FIRST:
        return "blocks", False
    inward = direction in _INWARD
    if "block" in t:
        return "blocks", inward
    if "depend" in t:
        # Outward Depend reads "source depends on target", so the target blocks.
        return "blocks", not inward
    if "relat" in t:
        return "relates", False
    if "duplicat" in t or "clone" in t:
        return "duplicates", False
    if "cause" in t:
        return "causes", False
    return "other", False


def _is_open(node: dict[str, Any]) -> bool:
    return node["status_category"] != "done"


def _p90(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def _person_load(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    people: dict[str, dict[str, Any]] = {}
    for node in nodes:
        pid = node["person_id"]
        unassigned = pid == UNASSIGNED_PERSON_ID
        person = people.setdefault(pid, {
            "id": pid,
            "kind": "unassigned" if unassigned else "person",
            "name": "Chưa phân công" if unassigned else (node["assignee_name"] or node["assignee_id"]),
            "open_count": 0,
            "high_risk_count": 0,
            "overdue_count": 0,
        })
        if _is_open(node):
            person["open_count"] += 1
            person["high_risk_count"] += node["level"] == "HIGH"
            person["overdue_count"] += node["is_overdue"]

    real = [p for p in people.values() if p["kind"] == "person"]
    threshold = _p90([p["open_count"] for p in real])
    use_threshold = len(real) >= 3
    for p in people.values():
        p["is_overloaded"] = p["kind"] == "person" and (
            (use_threshold and p["open_count"] > threshold) or p["high_risk_count"] >= 2
        )
    ordered = sorted(
        people.values(),
        key=lambda p: (p["kind"] != "unassigned", -p["high_risk_count"], -p["open_count"], p["name"]),
    )
    return ordered, threshold


def _deadlines(
    memberships: list[tuple[str, str, str, date | None, str]],
    nodes_by_key: dict[str, dict[str, Any]],
    today: date,
) -> list[dict[str, Any]]:
    deadlines: dict[str, dict[str, Any]] = {}
    for did, kind, name, end_date, issue_key in memberships:
        d = deadlines.setdefault(did, {
            "id": did,
            "kind": kind,
            "name": name,
            "end_date": end_date.isoformat() if end_date else None,
            "days_left": (end_date - today).days if end_date else None,
            "open_count": 0,
            "high_risk_count": 0,
        })
        node = nodes_by_key[issue_key]
        if _is_open(node):
            d["open_count"] += 1
            d["high_risk_count"] += node["level"] == "HIGH"
    for d in deadlines.values():
        d["at_risk"] = d["days_left"] is not None and d["days_left"] <= 3 and d["high_risk_count"] >= 1
    return sorted(deadlines.values(), key=lambda d: (d["days_left"] is None, d["days_left"] or 0, d["id"]))


def _critical_path(open_keys: set[str], blocking_map: dict[str, set[str]]) -> list[str]:
    """Longest blocking chain among open issues, in blocker-to-dependent order."""
    in_degree = dict.fromkeys(open_keys, 0)
    for u in open_keys:
        for v in blocking_map.get(u, ()):
            if v in open_keys:
                in_degree[v] += 1

    queue = deque(sorted(k for k, deg in in_degree.items() if deg == 0))
    dist = dict.fromkeys(open_keys, 1)
    pred: dict[str, str] = {}
    while queue:
        curr = queue.popleft()
        for nxt in sorted(blocking_map.get(curr, ())):
            if nxt not in open_keys:
                continue
            if dist[curr] + 1 > dist[nxt]:
                dist[nxt] = dist[curr] + 1
                pred[nxt] = curr
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if not dist:
        return []
    end = min(dist, key=lambda k: (-dist[k], k))
    if dist[end] < 2:
        return []
    chain = [end]
    while chain[-1] in pred:
        chain.append(pred[chain[-1]])
    return chain[::-1]


def _reopen_counts(session: Session, keys: set[str]) -> dict[str, int]:
    rows = session.execute(
        select(Change.issue_key, func.count())
        .where(
            Change.issue_key.in_(keys),
            Change.field == "status",
            func.lower(Change.to_str).like("%reopen%"),
        )
        .group_by(Change.issue_key)
    ).all()
    return {key: int(n) for key, n in rows}


def _deadline_memberships(session: Session, keys: set[str]) -> list[tuple[str, str, str, date | None, str]]:
    sprint_rows = session.execute(
        select(IssueSprint.issue_key, Sprint)
        .join(Sprint, Sprint.id == IssueSprint.sprint_id)
        .where(IssueSprint.issue_key.in_(keys), or_(Sprint.state.is_(None), Sprint.state != "closed"))
    ).all()
    version_rows = session.execute(
        select(IssueVersion.issue_key, Version)
        .join(Version, Version.id == IssueVersion.version_id)
        .where(IssueVersion.issue_key.in_(keys), Version.released.isnot(True))
    ).all()
    return [
        (f"sprint:{s.id}", "sprint", s.name or f"Sprint {s.id}", s.end_at.date() if s.end_at else None, key)
        for key, s in sprint_rows
    ] + [
        (f"version:{v.id}", "version", v.name or f"Version {v.id}", v.release_date, key)
        for key, v in version_rows
    ]


def _empty_graph(project_key: str | None) -> dict[str, Any]:
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
            "overloaded_count": 0,
            "unassigned_count": 0,
        },
        "nodes": [],
        "edges": [],
        "people": [],
        "deadlines": [],
        "critical_path": [],
        "overload_threshold": 0,
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
                return _empty_graph(None)
            base_issue_filters = [Issue.deleted_at.is_(None), Issue.project_key.in_(user_projects)]
        else:
            base_issue_filters = [Issue.deleted_at.is_(None)]

    rows = session.execute(
        select(Issue, RiskState)
        .outerjoin(RiskState, Issue.key == RiskState.issue_key)
        .where(*base_issue_filters)
    ).all()

    issue_dict: dict[str, tuple[Issue, RiskState | None]] = {
        issue.key: (issue, rs) for issue, rs in rows
    }
    issue_keys = set(issue_dict.keys())

    if not issue_keys:
        return _empty_graph(project_key)

    raw_links = list(session.scalars(
        select(Link).where((Link.source_key.in_(issue_keys)) | (Link.target_key.in_(issue_keys)))
    ).all())

    external_keys = ({lk.source_key for lk in raw_links} | {lk.target_key for lk in raw_links}) - issue_keys
    if external_keys:
        extra_rows = session.execute(
            select(Issue, RiskState)
            .outerjoin(RiskState, Issue.key == RiskState.issue_key)
            .where(Issue.key.in_(external_keys), Issue.deleted_at.is_(None))
        ).all()
        for issue, rs in extra_rows:
            issue_dict[issue.key] = (issue, rs)
            issue_keys.add(issue.key)

    blocking_map: dict[str, set[str]] = defaultdict(set)
    blocked_by_map: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    edges_list = []
    seen_edge_ids = set()

    for link in raw_links:
        if link.source_key not in issue_keys or link.target_key not in issue_keys:
            continue

        raw_type = (link.type_std or "").strip()
        kind, target_blocks = _classify_link(raw_type, link.direction)
        from_key, to_key = (
            (link.target_key, link.source_key) if target_blocks else (link.source_key, link.target_key)
        )

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
            "label": _EDGE_LABELS.get(kind, raw_type or "Liên kết"),
            "type_std": raw_type,
            "direction": link.direction,
            "kind": kind,
            "is_blocking": kind == "blocks",
        })

    today = utcnow().date()

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

    open_keys = {k for k, (iss, _) in issue_dict.items() if iss.status_category != "done"}
    critical_path = _critical_path(open_keys, blocking_map)
    critical_path_keys = set(critical_path)
    critical_pairs = set(zip(critical_path, critical_path[1:], strict=False))

    reopen_counts = _reopen_counts(session, issue_keys)
    memberships = _deadline_memberships(session, issue_keys)
    deadline_ids_by_key: dict[str, list[str]] = defaultdict(list)
    for did, _kind, _name, _end, key in memberships:
        deadline_ids_by_key[key].append(did)

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

        nodes_list.append({
            "id": key,
            "key": key,
            "kind": "issue",
            "project_key": issue.project_key,
            "summary": issue.summary,
            "issuetype": issue.issuetype,
            "priority": issue.priority,
            "priority_norm": issue.priority_norm,
            "status": issue.status,
            "status_category": issue.status_category,
            "assignee_id": issue.assignee_id,
            "assignee_name": issue.assignee_name,
            "person_id": f"person:{issue.assignee_id}" if issue.assignee_id else UNASSIGNED_PERSON_ID,
            "duedate": issue.duedate.isoformat() if issue.duedate else None,
            "story_points": issue.story_points,
            "level": level,
            "delay_value": rs.delay_value if rs and rs.delay_value is not None else 0.0,
            "crit_score": rs.crit_score if rs and rs.crit_score is not None else 0.0,
            "is_critical": is_crit,
            "blocked": is_blked,
            "deadline_label": rs.deadline_label if rs else None,
            "deadline_at": rs.deadline_at.isoformat() if rs and rs.deadline_at else None,
            "deadline_ids": sorted(deadline_ids_by_key[key]),
            "factors": rs.factors if rs and rs.factors else [],
            "is_overdue": key in overdue_keys,
            "overdue_days": overdue_days_map.get(key, 0),
            "is_bottleneck": key in bottleneck_keys,
            "bottleneck_score": bottleneck_score_map.get(key, 0.0),
            "reopen_count": reopen_counts.get(key, 0),
            "blocks_count": len(blocking_map[key]),
            "blocked_by_count": len(blocked_by_map[key]),
            "blocks_keys": sorted(blocking_map[key]),
            "blocked_by_keys": sorted(blocked_by_map[key]),
            "in_degree": in_degree[key],
            "out_degree": out_degree[key],
            "is_critical_path": key in critical_path_keys,
        })

    nodes_list.sort(key=lambda n: (n["is_bottleneck"], n["is_overdue"], n["delay_value"]), reverse=True)
    nodes_by_key = {n["key"]: n for n in nodes_list}

    for edge in edges_list:
        source = nodes_by_key[edge["from"]]
        edge["is_bottleneck_edge"] = edge["from"] in bottleneck_keys
        edge["is_overdue_edge"] = edge["from"] in overdue_keys
        edge["is_critical_path"] = (edge["from"], edge["to"]) in critical_pairs
        edge["propagates_risk"] = (
            edge["kind"] == "blocks"
            and _is_open(source)
            and (source["is_overdue"] or source["level"] == "HIGH")
        )

    people, overload_threshold = _person_load(nodes_list)
    deadlines = _deadlines(memberships, nodes_by_key, today)

    summary = {
        "total_nodes": len(nodes_list),
        "total_edges": len(edges_list),
        "bottlenecks_count": len(bottleneck_keys),
        "overdue_count": len(overdue_keys),
        "high_risk_count": high_risk_count,
        "blocked_count": blocked_count,
        "critical_count": critical_count,
        "done_count": done_count,
        "overloaded_count": sum(p["is_overloaded"] for p in people),
        "unassigned_count": next((p["open_count"] for p in people if p["kind"] == "unassigned"), 0),
    }

    return {
        "project": project_key,
        "summary": summary,
        "nodes": nodes_list,
        "edges": edges_list,
        "people": people,
        "deadlines": deadlines,
        "critical_path": critical_path,
        "overload_threshold": overload_threshold,
    }
