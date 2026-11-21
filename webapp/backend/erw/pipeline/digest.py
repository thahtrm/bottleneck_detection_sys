from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.domain.types import Level
from erw.integrations.slack import PREFIX, escape
from erw.models import Issue, IssueSprint, RiskState, Sprint
from erw.settings import Settings

MAX_ITEMS = 5
SP_COVERAGE = 0.8


def _level(name: str | None) -> Level:
    return Level[name] if name in Level.__members__ else Level.LOW


def _sprint_line(session: Session, project: str, now: datetime) -> str | None:
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
        return None
    with_sp = [i for i in issues if i.story_points]
    if len(with_sp) / len(issues) >= SP_COVERAGE:
        total = sum(i.story_points for i in with_sp)
        done = sum(i.story_points for i in with_sp if i.status_category == "done")
    else:
        total = len(issues)
        done = sum(1 for i in issues if i.status_category == "done")
    done_pct = round(100 * done / total) if total else 0
    expected = 0
    if sprint.start_at and sprint.end_at and sprint.end_at > sprint.start_at:
        frac = (now - sprint.start_at) / (sprint.end_at - sprint.start_at)
        expected = round(100 * min(1.0, max(0.0, frac)))
    return f"Tiến độ {escape(sprint.name or 'Sprint')}: {done_pct}% (kỳ vọng {expected}%)"


@dataclass(frozen=True)
class DigestTopItem:
    key: str
    summary: str
    level_name: str
    deadline_label: str | None
    assignee: str
    blocked: bool


@dataclass(frozen=True)
class DigestSnapshot:
    project: str
    day_label: str
    sprint_line: str | None
    risky_count: int
    raised_24h: int
    blocked_count: int
    new_24h: int
    new_critical: int
    top_risky: tuple[DigestTopItem, ...]


def collect_digest(session: Session, project: str, now: datetime, settings: Settings) -> DigestSnapshot:
    tz = ZoneInfo(settings.tz)
    since = now - timedelta(hours=24)
    rows = session.execute(
        select(Issue, RiskState)
        .outerjoin(RiskState, RiskState.issue_key == Issue.key)
        .where(Issue.project_key == project, Issue.deleted_at.is_(None))
    ).all()
    open_rows = [(i, r) for i, r in rows if i.status_category != "done"]
    risky = [(i, r) for i, r in open_rows if r is not None and _level(r.level) >= Level.MED]
    raised = sum(1 for _, r in risky if r.level_raised_at and r.level_raised_at >= since)
    blocked = sum(1 for _, r in open_rows if r is not None and r.blocked)
    new = [(i, r) for i, r in rows if i.created_at and i.created_at >= since]
    new_critical = sum(1 for _, r in new if r is not None and r.is_critical)
    risky.sort(key=lambda p: (-int(_level(p[1].level)), p[1].crit_score is None, -(p[1].crit_score or 0.0)))
    top = tuple(
        DigestTopItem(
            key=issue.key,
            summary=issue.summary or "",
            level_name=_level(rs.level).name,
            deadline_label=rs.deadline_label,
            assignee=issue.assignee_name or issue.assignee_id or "chưa giao",
            blocked=bool(rs.blocked),
        )
        for issue, rs in risky[:MAX_ITEMS]
    )
    return DigestSnapshot(
        project=project,
        day_label=f"{now.astimezone(tz):%d/%m}",
        sprint_line=_sprint_line(session, project, now),
        risky_count=len(risky),
        raised_24h=raised,
        blocked_count=blocked,
        new_24h=len(new),
        new_critical=new_critical,
        top_risky=top,
    )


def build_digest(session: Session, project: str, now: datetime, settings: Settings) -> str:
    snap = collect_digest(session, project, now, settings)
    lines = [f"{PREFIX['digest']}[{project}] {snap.day_label}"]
    if snap.sprint_line:
        lines.append(snap.sprint_line)
    lines.append(
        f"Nguy cơ trễ: {snap.risky_count} ({snap.raised_24h} tăng bậc 24h) · Bị block: {snap.blocked_count} · "
        f"Mới 24h: {snap.new_24h} ({snap.new_critical} critical)"
    )
    jira = settings.jira_base_url.rstrip("/")
    for item in snap.top_risky:
        parts = [f"<{jira}/browse/{item.key}|{item.key}> {escape(item.summary)}", _level(item.level_name).label_vi]
        if item.deadline_label:
            parts.append(escape(item.deadline_label))
        parts.append(f"@{escape(item.assignee)}")
        lines.append("• " + " · ".join(parts))
    lines.append(f"<{settings.web_base_url.rstrip('/')}|Xem tất cả trên Early Risk>")
    return "\n".join(lines)
