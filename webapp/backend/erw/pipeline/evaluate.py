from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.domain.deadline import resolve_deadline
from erw.domain.risk import aggregate
from erw.domain.rules import evaluate_rules
from erw.domain.timeline import build_timeline
from erw.domain.types import Level, ModelSignals, ProjectStats, Thresholds
from erw.ingest.sync import SyncResult
from erw.models import Change, Issue, IssueSprint, IssueVersion, Link, RiskState, Score, Sprint, Version
from erw.settings import Settings

log = logging.getLogger(__name__)

STATS_TTL_SECONDS = 3600.0
_stats_cache: dict[str, tuple[float, ProjectStats]] = {}

# Set to alerts.dispatch by create_app: callable (session, changes, now, settings) -> None.
_dispatch = None


@dataclass(frozen=True)
class RiskChange:
    key: str
    project: str
    prev_level: Level | None
    level: Level
    is_new: bool
    newly_blocked: bool
    became_critical: bool


def clear_stats_cache() -> None:
    _stats_cache.clear()


def project_stats(session: Session, project: str) -> ProjectStats:
    """P75 dwell days per status, from consecutive status changes of the project's issues."""
    hit = _stats_cache.get(project)
    if hit is not None and time.monotonic() - hit[0] < STATS_TTL_SECONDS:
        return hit[1]
    rows = session.execute(
        select(Change.issue_key, Change.at, Change.idx, Change.to_str)
        .join(Issue, Issue.key == Change.issue_key)
        .where(Issue.project_key == project, Change.field == "status")
        .order_by(Change.issue_key, Change.at, Change.idx)
    ).all()
    dwell: dict[str, list[float]] = {}
    prev = None
    for key, at, _idx, to_str in rows:
        if prev is not None and prev[0] == key and prev[2]:
            dwell.setdefault(prev[2], []).append((at - prev[1]).total_seconds() / 86400.0)
        prev = (key, at, to_str)
    stats = ProjectStats({s: float(np.percentile(v, 75)) for s, v in dwell.items()})
    _stats_cache[project] = (time.monotonic(), stats)
    return stats


def latest_model_signals(session: Session, key: str) -> ModelSignals | None:
    def newest(scorer: str) -> Score | None:
        return session.scalars(
            select(Score).where(Score.issue_key == key, Score.scorer == scorer).order_by(Score.as_of.desc(), Score.id.desc())
        ).first()

    delay, crit = newest("delay_t0"), newest("criticality_t0")
    if delay is None and crit is None:
        return None
    issue = session.get(Issue, key)
    finish = None
    if delay is not None and issue is not None and issue.created_at is not None:
        days = (delay.extra or {}).get("predicted_duration_days")
        if days is not None:
            finish = issue.created_at + timedelta(days=float(days))
    return ModelSignals(
        p_delay=delay.value if delay is not None else None,
        predicted_finish=finish,
        is_critical=bool(crit.is_critical) if crit is not None else False,
        crit_score=crit.value if crit is not None else None,
    )


def _blockers(session: Session, issue: Issue, changes: list[Change]) -> list[tuple[str, bool, datetime]]:
    def others(type_std, direction, want):
        col, other = (Link.source_key, Link.target_key) if want == "target" else (Link.target_key, Link.source_key)
        return session.scalars(
            select(other).where(col == issue.key, Link.type_std == type_std, Link.direction == direction)
        ).all()

    blockers = set()
    # Block: X "is blocked by" Y (source=X, dir 0) or Y "blocks" X (source=Y, dir 1)
    blockers |= set(others("Block", "0", "target"))
    blockers |= set(others("Block", "1", "source"))
    # Depend: X "depends on" Y (source=X, dir 1) or Y "is depended on by" X (source=Y, dir 0)
    blockers |= set(others("Depend", "1", "target"))
    blockers |= set(others("Depend", "0", "source"))
    link_times = [c.at for c in changes if c.field == "link"]
    since = min(link_times) if link_times else issue.created_at
    out = []
    for k in sorted(blockers):
        b = session.get(Issue, k)
        done = b is not None and (b.status_category == "done" or b.deleted_at is not None)
        out.append((k, done, since))
    return out


def evaluate_issue(
    session: Session, key: str, now: datetime, settings: Settings, *, is_new: bool = False
) -> RiskChange | None:
    issue = session.get(Issue, key)
    if issue is None:
        return None
    changes = list(session.scalars(select(Change).where(Change.issue_key == key)))
    sprints = list(session.scalars(
        select(Sprint).join(IssueSprint, IssueSprint.sprint_id == Sprint.id).where(IssueSprint.issue_key == key)
    ))
    versions = list(session.scalars(
        select(Version).join(IssueVersion, IssueVersion.version_id == Version.id).where(IssueVersion.issue_key == key)
    ))
    tl = build_timeline(
        issue, changes, sprints, versions, _blockers(session, issue, changes), now,
        status_categories=settings.status_category_overrides,
    )
    deadline = resolve_deadline(tl)
    th = Thresholds()
    factors = evaluate_rules(tl, deadline, now, project_stats(session, issue.project_key), th)
    model = latest_model_signals(session, key)
    level = aggregate(factors, model, deadline, th, settings.model_mode, tl=tl)
    fdicts = [asdict(f) for f in factors]
    blocked = any(f.id == "blocked" for f in factors)

    session.add(Score(
        issue_key=key, scorer="rules_dynamic", as_of=now, value=float(level), level=level.name,
        deadline_type=deadline.type, deadline_at=deadline.at, factors=fdicts,
    ))
    rs = session.get(RiskState, key)
    prev_level = Level[rs.level] if rs is not None and rs.level else None
    prev_blocked = bool(rs.blocked) if rs is not None else False
    prev_critical = bool(rs.is_critical) if rs is not None else False
    is_critical = bool(model.is_critical) if model else False
    if rs is None:
        rs = RiskState(issue_key=key)
        session.add(rs)
    rs.prev_level = rs.level
    rs.level = level.name
    if prev_level is not None and level > prev_level:
        rs.level_raised_at = now
    elif prev_level is not None and level < prev_level:
        rs.level_raised_at = None
    rs.blocked = blocked
    rs.delay_value = model.p_delay if model else None
    rs.crit_score = model.crit_score if model else None
    rs.is_critical = is_critical
    rs.deadline_type = deadline.type
    rs.deadline_at = deadline.at
    rs.deadline_label = deadline.label
    rs.factors = fdicts
    rs.updated_at = now
    session.flush()
    return RiskChange(
        key=key, project=issue.project_key, prev_level=prev_level, level=level, is_new=is_new,
        newly_blocked=blocked and not prev_blocked, became_critical=is_critical and not prev_critical,
    )


def evaluate_all(session: Session, now: datetime, settings: Settings) -> list[RiskChange]:
    keys = session.scalars(
        select(Issue.key).where(Issue.project_key.in_(settings.jira_projects), Issue.deleted_at.is_(None)).order_by(Issue.key)
    ).all()
    changes: list[RiskChange] = []
    for k in keys:
        try:
            with session.begin_nested():
                c = evaluate_issue(session, k, now, settings)
                if c is not None:
                    changes.append(c)
        except Exception:
            log.exception("failed to evaluate issue %s, skipping", k)
    return changes


def on_synced(session: Session, results: list[SyncResult], now: datetime, settings: Settings) -> list[RiskChange]:
    """Re-evaluate risk for synced issues; deleted issues lose their RiskState."""
    changes: list[RiskChange] = []
    synced_keys: set[str] = set()
    for r in results:
        synced_keys.add(r.key)
        if r.kind in ("created", "updated"):
            c = evaluate_issue(session, r.key, now, settings, is_new=r.kind == "created")
            if c is not None:
                changes.append(c)
        elif r.kind == "deleted":
            rs = session.get(RiskState, r.key)
            if rs is not None:
                session.delete(rs)

    if synced_keys:
        linked_rows = session.execute(
            select(Link.source_key, Link.target_key).where(
                Link.type_std.in_(["Block", "Depend"]),
                (Link.source_key.in_(synced_keys)) | (Link.target_key.in_(synced_keys)),
            )
        ).all()
        dep_keys = set()
        for src, tgt in linked_rows:
            if src not in synced_keys:
                dep_keys.add(src)
            if tgt not in synced_keys:
                dep_keys.add(tgt)
        for k in sorted(dep_keys):
            c = evaluate_issue(session, k, now, settings, is_new=False)
            if c is not None:
                changes.append(c)

    if _dispatch is not None:
        _dispatch(session, changes, now, settings)
    session.commit()
    return changes
