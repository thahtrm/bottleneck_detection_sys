from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erw.domain.types import Level
from erw.models import ChatMessage, ProjectMember, ReportSlot
from erw.pipeline.chat_lookup import blocker_keys, blocks_keys, issue_fact_line, keys_in_text
from erw.pipeline.digest import collect_digest
from erw.settings import Settings


@dataclass(frozen=True)
class DueReport:
    message_id: int
    user_prompt: str
    allowed_keys: frozenset[str]


def report_dedup_key(user_id: int, project: str, hhmm: str, local_day: str) -> str:
    return f"report:{user_id}:{project}:{hhmm}:{local_day}"


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
            due.append(DueReport(message.id, json.dumps(payload, ensure_ascii=False), allowed))
    return due
