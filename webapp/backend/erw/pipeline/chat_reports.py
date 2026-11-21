from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erw.domain.types import Level
from erw.models import ChatMessage, ProjectMember, ReportFile, ReportSlot
from erw.pipeline.chat_lookup import blocker_keys, blocks_keys, issue_fact_line, keys_in_text
from erw.pipeline.digest import collect_digest
from erw.settings import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DueReport:
    message_id: int
    user_prompt: str
    allowed_keys: frozenset[str]


def report_dedup_key(user_id: int, project: str, hhmm: str, local_day: str) -> str:
    return f"report:{user_id}:{project}:{hhmm}:{local_day}"


def reports_root(settings: Settings) -> Path:
    """Absolute reports root. Absolute settings win; default `var/reports` → backend/var/reports."""
    configured = Path(settings.reports_dir)
    if configured.is_absolute():
        return configured
    if configured == Path("var/reports"):
        return Path(__file__).resolve().parents[2] / "var" / "reports"
    return configured


def report_rel_path(user_id: int, project: str, local_day: str, hhmm: str) -> str:
    stamp = hhmm.replace(":", "")
    return f"{user_id}/{project}/{local_day}-{stamp}.md"


def report_abs_path(settings: Settings, rel_path: str) -> Path:
    root = reports_root(settings).resolve()
    full = (root / rel_path).resolve()
    if full != root and root not in full.parents:
        raise ValueError("report path escapes reports_dir")
    return full


def write_report_file(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    project: str,
    message_id: int,
    body: str,
    hhmm: str,
    local_day: str,
    created_at: datetime,
) -> ReportFile | None:
    rel = report_rel_path(user_id, project, local_day, hhmm)
    abs_path = report_abs_path(settings, rel)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(body, encoding="utf-8")
    preview = body.strip().splitlines()[0] if body.strip() else ""
    if len(preview) > 160:
        preview = preview[:157] + "..."
    row = ReportFile(
        user_id=user_id,
        project_key=project,
        message_id=message_id,
        slot_hhmm=hhmm,
        report_date=local_day,
        rel_path=rel,
        preview=preview,
        created_at=created_at,
        hidden_at=None,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        log.warning("report file metadata duplicate for message_id=%s path=%s", message_id, rel)
        return None
    return row


def _report_body(session: Session, project: str, now: datetime, settings: Settings) -> tuple[str, dict, frozenset[str]]:
    snap = collect_digest(session, project, now, settings)
    lines = [f"Báo cáo {snap.day_label} [{project}]."]
    if snap.sprint_line:
        lines.append(snap.sprint_line if snap.sprint_line.endswith(".") else f"{snap.sprint_line}.")
    lines.append(
        f"Nguy cơ trễ: {snap.risky_count} ({snap.raised_24h} tăng bậc 24 giờ). "
        f"Bị block: {snap.blocked_count}. Mới 24 giờ: {snap.new_24h} ({snap.new_critical} critical)."
    )
    listed = []
    for item in snap.top_risky:
        level = Level[item.level_name].label_vi if item.level_name in Level.__members__ else item.level_name
        line = issue_fact_line(
            item.key,
            item.assignee,
            level,
            item.deadline_label,
            item.blocked,
            blocks_keys(session, item.key),
            blocker_keys(session, item.key) if item.blocked else [],
        )
        lines.append(line)
        listed.append({"key": item.key, "line": line})
    facts = "\n".join(lines)
    payload = {
        "kind": "report",
        "project": project,
        "risky_count": snap.risky_count,
        "raised_24h": snap.raised_24h,
        "blocked_count": snap.blocked_count,
        "new_24h": snap.new_24h,
        "new_critical": snap.new_critical,
        "issues": listed,
    }
    return facts, payload, keys_in_text(facts)


def run_due_reports(session: Session, now: datetime, settings: Settings) -> list[DueReport]:
    local = now.astimezone(ZoneInfo(settings.tz))
    if local.weekday() >= 5:
        return []
    hhmm = f"{local:%H:%M}"
    local_day = local.date().isoformat()
    slots = session.scalars(select(ReportSlot).where(ReportSlot.time_hhmm == hhmm)).all()
    due: list[DueReport] = []
    for slot in slots:
        projects = session.scalars(
            select(ProjectMember.project_key).where(ProjectMember.user_id == slot.user_id, ProjectMember.role == "pm")
        ).all()
        for project in projects:
            dedup = report_dedup_key(slot.user_id, project, hhmm, local_day)
            existing = session.scalar(select(ChatMessage.id).where(ChatMessage.dedup_key == dedup))
            if existing is not None:
                continue
            facts, payload, allowed = _report_body(session, project, now, settings)
            message = ChatMessage(
                user_id=slot.user_id,
                project_key=project,
                kind="report",
                body=facts,
                recommendation_status="pending",
                created_at=now,
                dedup_key=dedup,
            )
            try:
                with session.begin_nested():
                    session.add(message)
                    session.flush()
            except IntegrityError:
                continue
            try:
                write_report_file(
                    session,
                    settings,
                    user_id=slot.user_id,
                    project=project,
                    message_id=message.id,
                    body=facts,
                    hhmm=hhmm,
                    local_day=local_day,
                    created_at=now,
                )
            except OSError:
                log.exception(
                    "failed to write report file user=%s project=%s day=%s slot=%s",
                    slot.user_id,
                    project,
                    local_day,
                    hhmm,
                )
            due.append(DueReport(message.id, json.dumps(payload, ensure_ascii=False), allowed))
    return due
