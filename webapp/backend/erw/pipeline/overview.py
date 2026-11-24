"""Progress Attribution Dashboard — P0 structural overview snapshot + MD/PDF export."""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.domain.types import Level
from erw.models import Change, Issue, IssueSprint, Project, RiskState, Sprint
from erw.pipeline.chat_lookup import blocker_keys, blocks_keys
from erw.pipeline.digest import SP_COVERAGE, _sprint_line
from erw.pipeline.health_report import write_pdf_from_markdown
from erw.pipeline.overview_shap import (
    compute_project_shap_summary,
    load_latest_issue_shap,
)
from erw.settings import Settings

log = logging.getLogger(__name__)

ActorKind = Literal["person", "blocker", "status"]
TOP_ISSUES = 40
TOP_ACTORS = 20


def _level(name: str | None) -> Level:
    return Level[name] if name in Level.__members__ else Level.LOW


def _p_delay(risk: RiskState | None) -> float | None:
    if risk is None or risk.delay_value is None:
        return None
    return float(risk.delay_value)


def _median(values: list[float | int]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _rank_sum_merge(groups: dict[ActorKind, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge actor kinds by simple rank-sum (lower rank better), then impact desc."""
    scored: dict[str, dict[str, Any]] = {}
    for kind, rows in groups.items():
        ordered = sorted(rows, key=lambda r: (-float(r["impact"]), -int(r["affected_count"]), r["name"]))
        for idx, row in enumerate(ordered, start=1):
            key = f"{kind}:{row['id']}"
            entry = scored.setdefault(
                key,
                {**row, "kind": kind, "_rank_sum": 0, "_kinds": 0},
            )
            entry["_rank_sum"] += idx
            entry["_kinds"] += 1
            # Keep strongest impact seen across kinds (usually one kind per id).
            if float(row["impact"]) > float(entry["impact"]):
                entry["impact"] = row["impact"]
                entry["affected_count"] = row["affected_count"]
                entry["related_risk"] = row["related_risk"]
                entry["suggestion"] = row["suggestion"]
                entry["name"] = row["name"]
                entry["evidence"] = row.get("evidence") or entry.get("evidence")
    merged = list(scored.values())
    merged.sort(key=lambda r: (r["_rank_sum"], -float(r["impact"]), r["name"]))
    out: list[dict[str, Any]] = []
    for rank, row in enumerate(merged[:TOP_ACTORS], start=1):
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        clean["rank"] = rank
        out.append(clean)
    return out


def _status_since(session: Session, issue: Issue, now: datetime) -> datetime:
    """Latest status Change.at, else created_at, else now."""
    last = session.scalars(
        select(Change)
        .where(Change.issue_key == issue.key, Change.field == "status")
        .order_by(Change.at.desc())
        .limit(1)
    ).first()
    if last is not None and last.at is not None:
        return last.at
    if issue.created_at is not None:
        return issue.created_at
    return now


def _days_in_status(session: Session, issue: Issue, now: datetime) -> float:
    since = _status_since(session, issue, now)
    return max(0.0, (now - since).total_seconds() / 86400.0)


def _active_sprint_progress(
    session: Session, project: str, now: datetime
) -> dict[str, Any] | None:
    sprint = session.scalars(
        select(Sprint)
        .join(IssueSprint, IssueSprint.sprint_id == Sprint.id)
        .join(Issue, Issue.key == IssueSprint.issue_key)
        .where(Issue.project_key == project, Issue.deleted_at.is_(None), Sprint.state == "active")
        .order_by(Sprint.start_at.desc())
    ).first()
    if sprint is None:
        return None
    issues = session.scalars(
        select(Issue)
        .join(IssueSprint, IssueSprint.issue_key == Issue.key)
        .where(IssueSprint.sprint_id == sprint.id, Issue.project_key == project, Issue.deleted_at.is_(None))
    ).all()
    if not issues:
        return {
            "id": sprint.id,
            "name": sprint.name or "Sprint",
            "done": 0,
            "committed": 0,
            "done_pct": 0,
            "expected_pct": None,
            "unit": "issues",
        }
    with_sp = [i for i in issues if i.story_points]
    if len(with_sp) / len(issues) >= SP_COVERAGE:
        total = sum(float(i.story_points or 0) for i in with_sp)
        done = sum(float(i.story_points or 0) for i in with_sp if i.status_category == "done")
        unit = "points"
    else:
        total = float(len(issues))
        done = float(sum(1 for i in issues if i.status_category == "done"))
        unit = "issues"
    done_pct = round(100 * done / total) if total else 0
    expected: int | None = None
    if sprint.start_at and sprint.end_at and sprint.end_at > sprint.start_at:
        frac = (now - sprint.start_at) / (sprint.end_at - sprint.start_at)
        expected = round(100 * min(1.0, max(0.0, frac)))
    return {
        "id": sprint.id,
        "name": sprint.name or "Sprint",
        "done": int(round(done)) if unit == "issues" else round(done, 1),
        "committed": int(round(total)) if unit == "issues" else round(total, 1),
        "done_pct": done_pct,
        "expected_pct": expected,
        "unit": unit,
    }


def _person_actors(
    open_rows: list[tuple[Issue, RiskState | None]],
) -> list[dict[str, Any]]:
    by_person: dict[str, list[tuple[Issue, RiskState | None]]] = defaultdict(list)
    for issue, risk in open_rows:
        name = (issue.assignee_name or issue.assignee_id or "").strip()
        if not name:
            continue
        by_person[name].append((issue, risk))
    counts = [len(v) for v in by_person.values()]
    median_open = _median(counts) or 1.0
    actors: list[dict[str, Any]] = []
    for name, rows in by_person.items():
        open_count = len(rows)
        high_blocked = sum(
            1
            for _, risk in rows
            if risk is not None and (_level(risk.level) >= Level.HIGH or risk.blocked)
        )
        overload_ratio = max(1.0, open_count / median_open)
        impact = float(high_blocked) * overload_ratio
        delays = [d for _, r in rows if (d := _p_delay(r)) is not None]
        avg_delay = sum(delays) / len(delays) if delays else 0.0
        suggestion = "rebalance" if overload_ratio > 1.25 else "watch"
        actors.append(
            {
                "id": name,
                "name": name,
                "kind": "person",
                "affected_count": open_count,
                "impact": round(impact, 3),
                "related_risk": {
                    "high_blocked": high_blocked,
                    "avg_p_delay": round(avg_delay, 3) if delays else None,
                    "open_count": open_count,
                    "overload_ratio": round(overload_ratio, 3),
                },
                "suggestion": suggestion,
                "evidence": f"{open_count} open · median {median_open:.0f} · HIGH/blocked {high_blocked}",
            }
        )
    return actors


def _blocker_actors(
    session: Session,
    open_rows: list[tuple[Issue, RiskState | None]],
    open_keys: set[str],
    p_delay_by_key: dict[str, float | None],
) -> list[dict[str, Any]]:
    fanout: dict[str, list[str]] = defaultdict(list)
    for issue, _risk in open_rows:
        downstream = [k for k in blocks_keys(session, issue.key) if k in open_keys]
        if downstream:
            fanout[issue.key] = downstream
    actors: list[dict[str, Any]] = []
    summaries = {i.key: (i.summary or "") for i, _ in open_rows}
    for key, downs in fanout.items():
        fan_out = len(downs)
        delays = [p_delay_by_key[k] for k in downs if p_delay_by_key.get(k) is not None]
        avg_down = (sum(delays) / len(delays)) if delays else 0.0  # type: ignore[arg-type]
        impact = fan_out * (1.0 + float(avg_down))
        high_down = sum(
            1
            for k in downs
            if (p_delay_by_key.get(k) or 0) >= 0.5
        )
        actors.append(
            {
                "id": key,
                "name": key,
                "kind": "blocker",
                "affected_count": fan_out,
                "impact": round(impact, 3),
                "related_risk": {
                    "fan_out": fan_out,
                    "avg_downstream_p_delay": round(float(avg_down), 3) if delays else None,
                    "high_downstream": high_down,
                    "summary": summaries.get(key, ""),
                },
                "suggestion": "escalate",
                "evidence": f"blocks {fan_out} open · avg p_delay {avg_down:.2f}" if delays else f"blocks {fan_out} open",
                "downstream_keys": downs,
            }
        )
    return actors


def _status_actors(
    session: Session,
    open_rows: list[tuple[Issue, RiskState | None]],
    now: datetime,
) -> list[dict[str, Any]]:
    by_status: dict[str, list[tuple[Issue, RiskState | None, float]]] = defaultdict(list)
    for issue, risk in open_rows:
        status = (issue.status or "Unknown").strip() or "Unknown"
        dwell = _days_in_status(session, issue, now)
        by_status[status].append((issue, risk, dwell))
    actors: list[dict[str, Any]] = []
    for status, rows in by_status.items():
        count = len(rows)
        median_dwell = _median([d for _, _, d in rows])
        impact = float(count) * median_dwell
        high = sum(1 for _, r, _ in rows if r is not None and _level(r.level) >= Level.HIGH)
        suggestion = "rút queue" if median_dwell >= 5 else "watch"
        actors.append(
            {
                "id": status,
                "name": status,
                "kind": "status",
                "affected_count": count,
                "impact": round(impact, 3),
                "related_risk": {
                    "count": count,
                    "median_days_in_status": round(median_dwell, 2),
                    "high_count": high,
                },
                "suggestion": suggestion,
                "evidence": f"{count} open · median dwell {median_dwell:.1f}d",
            }
        )
    return actors


def _shap_payload(row) -> dict[str, Any]:
    values = list(row.values or [])
    # Waterfall: keep top by |phi|, preserve sign (red+/cyan- in UI).
    ordered = sorted(values, key=lambda v: -abs(float(v.get("phi") or 0)))
    return {
        "base_value": row.base_value,
        "pred": row.pred,
        "values": ordered[:12],
        "model_tag": row.model_tag,
        "shap_method": row.shap_method,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "feature_version": row.feature_version,
    }


def _build_issue_rows(
    session: Session,
    open_rows: list[tuple[Issue, RiskState | None]],
    now: datetime,
    assignee_open: dict[str, int],
    shap_by_key: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    shap_by_key = shap_by_key or {}
    ranked = sorted(
        open_rows,
        key=lambda pair: (
            -int(_level(pair[1].level if pair[1] else None)),
            -( _p_delay(pair[1]) or 0.0),
            pair[0].key,
        ),
    )
    issues: list[dict[str, Any]] = []
    explain: dict[str, dict[str, Any]] = {}
    today = now.date()
    for issue, risk in ranked[:TOP_ISSUES]:
        blockers = blocker_keys(session, issue.key)
        downs = blocks_keys(session, issue.key)
        dwell = _days_in_status(session, issue, now)
        assignee = (issue.assignee_name or issue.assignee_id or "").strip()
        load = assignee_open.get(assignee, 0) if assignee else 0
        p_delay = _p_delay(risk)
        level = _level(risk.level if risk else None).name if risk and risk.level else None
        overdue = bool(issue.duedate and issue.duedate < today)
        structural: list[dict[str, str]] = []
        if blockers:
            structural.append(
                {
                    "kind": "blocked_by",
                    "label": "Bị chặn bởi",
                    "evidence": ", ".join(blockers[:5]),
                }
            )
        if assignee and load:
            structural.append(
                {
                    "kind": "assignee_load",
                    "label": "Tải assignee",
                    "evidence": f"{assignee} đang giữ {load} việc mở",
                }
            )
        structural.append(
            {
                "kind": "dwell",
                "label": "Dwell status",
                "evidence": f"{issue.status or '—'} · {dwell:.1f} ngày",
            }
        )
        shap_row = shap_by_key.get(issue.key)
        top_shap = None
        shap_payload = None
        if shap_row is not None:
            shap_payload = _shap_payload(shap_row)
            if shap_payload["values"]:
                top_shap = shap_payload["values"][0]["feature"]
        row = {
            "key": issue.key,
            "summary": issue.summary or "",
            "level": level,
            "p_delay": round(p_delay, 4) if p_delay is not None else None,
            "assignee": assignee or "chưa giao",
            "blocked_by": blockers,
            "top_shap_feature": top_shap,
            "deadline": risk.deadline_label if risk else None,
            "deadline_at": risk.deadline_at.isoformat() if risk and risk.deadline_at else None,
            "duedate": issue.duedate.isoformat() if issue.duedate else None,
            "overdue": overdue,
            "status": issue.status,
            "blocked": bool(risk.blocked) if risk else False,
            "days_in_status": round(dwell, 2),
        }
        issues.append(row)
        explain[issue.key] = {
            "key": issue.key,
            "summary": issue.summary or "",
            "level": level,
            "p_delay": row["p_delay"],
            "structural_factors": structural[:3],
            "downstream": downs,
            "shap": shap_payload,
            "shap_status": None if shap_payload else "Chưa có SHAP cho snapshot này",
        }
    return issues, explain


@dataclass
class OverviewSnapshot:
    project: str
    name: str
    as_of: str
    as_of_label: str
    tz: str
    sprint_line: str | None
    sprint: dict[str, Any] | None
    kpi: dict[str, Any]
    actors: list[dict[str, Any]]
    actors_by_kind: dict[str, list[dict[str, Any]]]
    issues: list[dict[str, Any]]
    explain: dict[str, dict[str, Any]]
    risk_distribution: list[dict[str, Any]]
    top_blockers: list[dict[str, Any]]
    shap_available: bool = False
    shap_project: dict[str, Any] | None = None
    shap_project_high: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_overview_snapshot(
    session: Session, project: str, now: datetime, settings: Settings
) -> OverviewSnapshot:
    tz = ZoneInfo(settings.tz)
    local = now.astimezone(tz)
    since = now - timedelta(hours=24)
    today = now.date() if isinstance(now, datetime) else date.today()

    proj = session.get(Project, project)
    name = (proj.name if proj else "") or project

    rows = session.execute(
        select(Issue, RiskState)
        .outerjoin(RiskState, RiskState.issue_key == Issue.key)
        .where(Issue.project_key == project, Issue.deleted_at.is_(None))
    ).all()
    open_rows = [(i, r) for i, r in rows if i.status_category != "done"]
    open_keys = {i.key for i, _ in open_rows}

    high = sum(1 for _, r in open_rows if r is not None and _level(r.level) == Level.HIGH)
    med = sum(1 for _, r in open_rows if r is not None and _level(r.level) == Level.MED)
    blocked = sum(1 for _, r in open_rows if r is not None and r.blocked)
    overdue = sum(1 for i, _ in open_rows if i.duedate is not None and i.duedate < today)
    delays = [d for _, r in open_rows if (d := _p_delay(r)) is not None]
    avg_p_delay = round(sum(delays) / len(delays), 3) if delays else None

    # Rough 24h deltas from level_raised / newly blocked / newly overdue isn't fully
    # stored; use raised_at and created as proxies where available.
    high_raised_24h = sum(
        1
        for _, r in open_rows
        if r is not None
        and _level(r.level) == Level.HIGH
        and r.level_raised_at
        and r.level_raised_at >= since
    )
    new_open_24h = sum(1 for i, _ in open_rows if i.created_at and i.created_at >= since)

    sprint = _active_sprint_progress(session, project, now)
    sprint_line = _sprint_line(session, project, now)

    p_delay_by_key = {i.key: _p_delay(r) for i, r in open_rows}
    person = _person_actors(open_rows)
    blockers = _blocker_actors(session, open_rows, open_keys, p_delay_by_key)
    statuses = _status_actors(session, open_rows, now)

    # Rank within kind
    def _rank_kind(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(rows, key=lambda r: (-float(r["impact"]), -int(r["affected_count"]), r["name"]))
        out = []
        for idx, row in enumerate(ordered[:TOP_ACTORS], start=1):
            out.append({**row, "rank": idx})
        return out

    actors_by_kind = {
        "person": _rank_kind(person),
        "blocker": _rank_kind(blockers),
        "status": _rank_kind(statuses),
    }
    actors_all = _rank_sum_merge(
        {"person": person, "blocker": blockers, "status": statuses}
    )

    assignee_open: dict[str, int] = defaultdict(int)
    for issue, _ in open_rows:
        name_a = (issue.assignee_name or issue.assignee_id or "").strip()
        if name_a:
            assignee_open[name_a] += 1

    shap_by_key, shap_meta = load_latest_issue_shap(session, project)
    issues, explain = _build_issue_rows(
        session, open_rows, now, dict(assignee_open), shap_by_key=shap_by_key
    )

    shap_project = None
    shap_project_high = None
    if shap_by_key:
        stored = [
            {
                "issue_key": k,
                "level": next((r.level for i, r in open_rows if i.key == k and r), None),
                "values": list(row.values or []),
            }
            for k, row in shap_by_key.items()
        ]
        shap_project = compute_project_shap_summary(stored, high_only=False)
        shap_project_high = compute_project_shap_summary(stored, high_only=True)
        if shap_meta:
            shap_project = {**shap_project, **{k: shap_meta[k] for k in ("model_tag", "shap_method", "as_of", "feature_version") if k in shap_meta}}
            shap_project_high = {
                **shap_project_high,
                **{k: shap_meta[k] for k in ("model_tag", "shap_method", "as_of", "feature_version") if k in shap_meta},
            }

    risk_distribution = [
        {"level": "HIGH", "count": high},
        {"level": "MED", "count": med},
        {"level": "LOW", "count": sum(1 for _, r in open_rows if r is not None and _level(r.level) == Level.LOW)},
        {
            "level": "UNSCORED",
            "count": sum(1 for _, r in open_rows if r is None or not r.level),
        },
    ]
    top_blockers = [
        {
            "key": a["id"],
            "name": a["name"],
            "fan_out": a["affected_count"],
            "impact": a["impact"],
            "summary": (a.get("related_risk") or {}).get("summary") or "",
        }
        for a in actors_by_kind["blocker"][:8]
    ]

    kpi = {
        "open": len(open_rows),
        "open_delta_24h": new_open_24h,
        "sprint_done": sprint["done"] if sprint else None,
        "sprint_committed": sprint["committed"] if sprint else None,
        "sprint_done_pct": sprint["done_pct"] if sprint else None,
        "high": high,
        "med": med,
        "high_delta_24h": high_raised_24h,
        "blocked": blocked,
        "overdue": overdue,
        "avg_p_delay": avg_p_delay,
        "forecast_delay": avg_p_delay,
    }

    as_of_label = f"Cập nhật {local:%d/%m/%Y %H:%M} {settings.tz}"
    shap_available = bool(shap_by_key)
    return OverviewSnapshot(
        project=project,
        name=name,
        as_of=now.isoformat(),
        as_of_label=as_of_label,
        tz=settings.tz,
        sprint_line=sprint_line,
        sprint=sprint,
        kpi=kpi,
        actors=actors_all,
        actors_by_kind=actors_by_kind,
        issues=issues,
        explain=explain,
        risk_distribution=risk_distribution,
        top_blockers=top_blockers,
        shap_available=shap_available,
        shap_project=shap_project,
        shap_project_high=shap_project_high,
        meta={
            "model_id": (shap_meta or {}).get("model_tag"),
            "shap_method": (shap_meta or {}).get("shap_method"),
            "feature_version": (shap_meta or {}).get("feature_version"),
            "phase": "P1" if shap_available else "P0",
            "as_of": now.isoformat(),
            "shap_as_of": (shap_meta or {}).get("as_of"),
            "shap_runtime": {
                "max_issues": 80,
                "nsamples": 64,
                "surrogate": "ridge_on_dual_head_p_delay",
                "feature_groups": 10,
                "dual_head_memory_cache": "var/dual_head_memory/{project}/*.npz",
            },
        },
    )


def render_overview_markdown(snap: OverviewSnapshot) -> str:
    k = snap.kpi
    sprint = snap.sprint
    sprint_bit = snap.sprint_line or "Không có sprint active"
    if sprint:
        sprint_bit = (
            f"{sprint['name']}: {sprint['done']}/{sprint['committed']} "
            f"({sprint['done_pct']}% done"
            + (f", kỳ vọng {sprint['expected_pct']}%" if sprint.get("expected_pct") is not None else "")
            + ")"
        )
    lines = [
        "# Progress Attribution — Tổng quan",
        f"## {snap.project} · {snap.name}",
        f"> {snap.as_of_label}",
        "",
        f"**Sprint:** {sprint_bit}",
        "",
        "### KPI",
        f"- Open: {k['open']} (mới 24h: {k['open_delta_24h']})",
        f"- Done (sprint): {k['sprint_done']}/{k['sprint_committed']}" if k.get("sprint_committed") is not None else "- Done (sprint): —",
        f"- HIGH / MED: {k['high']} / {k['med']} (HIGH raised 24h: {k['high_delta_24h']})",
        f"- Blocked: {k['blocked']}",
        f"- Trễ hạn: {k['overdue']} · Forecast delay (avg p_delay): {k['avg_p_delay'] if k['avg_p_delay'] is not None else '—'}",
        "",
        "### Tác nhân ảnh hưởng (top)",
    ]
    if not snap.actors:
        lines.append("- (không có)")
    else:
        for a in snap.actors[:15]:
            kind_vi = {"person": "Người", "blocker": "Issue chặn", "status": "Giai đoạn"}.get(a["kind"], a["kind"])
            lines.append(
                f"- #{a['rank']} **{a['name']}** `{kind_vi}` · ảnh hưởng {a['affected_count']} · "
                f"impact {a['impact']} · gợi ý {a['suggestion']}"
            )
    lines.extend(["", "### Issue rủi ro (top)"])
    if not snap.issues:
        lines.append("- (không có)")
    else:
        for row in snap.issues[:20]:
            level = row.get("level") or "—"
            p_delay = row["p_delay"] if row.get("p_delay") is not None else "—"
            blocked = ", ".join(row.get("blocked_by") or []) or "—"
            lines.append(
                f"- {row['key']} `[{level}]` p_delay={p_delay} · @{row['assignee']} · "
                f"blocked-by {blocked} — {row['summary']}"
            )
    lines.extend(["", "### SHAP (Dual-Head delay)"])
    if snap.shap_available and snap.shap_project:
        sp = snap.shap_project
        lines.append(
            f"- method `{sp.get('shap_method')}` · model `{sp.get('model_tag')}` · as_of {sp.get('as_of')}"
        )
        for f in (sp.get("features") or [])[:10]:
            lines.append(f"- {f['feature']} ({f.get('bucket')}): mean|φ|={f['mean_abs_phi']}")
        lines.append("- Buckets:")
        for b in sp.get("buckets") or []:
            lines.append(f"  - {b['bucket']}: {b['mean_abs_phi']}")
    else:
        lines.append("- (chưa có cache SHAP — chạy Làm mới SHAP / batch)")

    lines.extend(
        [
            "",
            "### Ghi chú",
            "- Structural actors + KernelSHAP quanh Dual-Head delay (cache).",
            f"- meta.phase={snap.meta.get('phase')} · shap_available={snap.shap_available}",
            "",
        ]
    )
    return "\n".join(lines)


def write_overview_pdf(snap: OverviewSnapshot, path: Path) -> bool:
    md = render_overview_markdown(snap)
    return write_pdf_from_markdown(md, path)
