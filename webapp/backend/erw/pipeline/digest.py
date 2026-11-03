from __future__ import annotations

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


def build_digest(session: Session, project: str, now: datetime, settings: Settings) -> str:
    tz = ZoneInfo(settings.tz)
    lines = [f"{PREFIX['digest']}[{project}] {now.astimezone(tz):%d/%m}"]
    sprint_line = _sprint_line(session, project, now)
    if sprint_line:
        lines.append(sprint_line)

    since = now - timedelta(hours=24)
    rows = session.execute(
        select(Issue, RiskState)
        .outerjoin(RiskState, RiskState.issue_key == Issue.key)
        .where(Issue.project_key == project, Issue.deleted_at.is_(None))
    ).all()
    open_rows = [(i, r) for i, r in rows if i.status_category != "done"]
    risky = [(i, r) for i, r in open_rows if r is not None and _level(r.level) >= Level.MED]
    raised = sum(
        1
        for _, r in risky
        if r.prev_level is not None and _level(r.level) > _level(r.prev_level) and r.updated_at and r.updated_at >= since
    )
    blocked = sum(1 for _, r in open_rows if r is not None and r.blocked)
    new = [(i, r) for i, r in rows if i.created_at and i.created_at >= since]
    new_critical = sum(1 for _, r in new if r is not None and r.is_critical)
    lines.append(
        f"Nguy cơ trễ: {len(risky)} ({raised} tăng bậc 24h) · Bị block: {blocked} · Mới 24h: {len(new)} ({new_critical} critical)"
    )

    risky.sort(key=lambda p: (-int(_level(p[1].level)), p[1].crit_score is None, -(p[1].crit_score or 0.0)))
    jira = settings.jira_base_url.rstrip("/")
    for issue, rs in risky[:MAX_ITEMS]:
        parts = [f"<{jira}/browse/{issue.key}|{issue.key}> {escape(issue.summary or '')}", _level(rs.level).label_vi]
        if rs.deadline_label:
            parts.append(escape(rs.deadline_label))
        parts.append(f"@{escape(issue.assignee_name or issue.assignee_id or 'chưa giao')}")
        lines.append("• " + " · ".join(parts))
    lines.append(f"<{settings.web_base_url.rstrip('/')}|Xem tất cả trên Early Risk>")
    return "\n".join(lines)
