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

from erw.models import ChatMessage, ProjectMember, ReportFile, ReportSlot
from erw.pipeline.health_report import (
    build_health_markdown,
    pdf_rel_from_md,
    write_pdf_from_markdown,
)
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
    pdf_rel = pdf_rel_from_md(rel)
    try:
        write_pdf_from_markdown(body, report_abs_path(settings, pdf_rel))
    except Exception:
        log.exception("pdf sibling failed for %s", rel)
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


def write_report_meta(settings: Settings, rel_path: str, meta: dict) -> None:
    """Sidecar JSON next to md for chat Q&A allowlists (no invent)."""
    meta_rel = rel_path[:-3] + ".meta.json" if rel_path.endswith(".md") else rel_path + ".meta.json"
    path = report_abs_path(settings, meta_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def persist_health_report(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    project: str,
    now: datetime,
    hhmm: str,
    local_day: str,
    dedup: str,
) -> ChatMessage | None:
    """Build 7-section health report, write ChatMessage + md/pdf files. Returns message or None if dup."""
    existing = session.scalar(select(ChatMessage.id).where(ChatMessage.dedup_key == dedup))
    if existing is not None:
        return None
    body, snap = build_health_markdown(session, project, now, settings)
    # Timeline keeps a short pointer; full content lives on disk.
    summary_lines = [
        f"Báo cáo sức khỏe {snap.day_label} [{project}].",
        f"Open {snap.facts['overview']['open_count']} · Risky {snap.facts['overview']['risky_count']} · "
        f"Blocked {snap.facts['overview']['blocked_count']}.",
        "Chi tiết 7 mục trong file Báo cáo (md/pdf).",
    ]
    message = ChatMessage(
        user_id=user_id,
        project_key=project,
        kind="report",
        body="\n".join(summary_lines),
        recommendation_status="ready",
        created_at=now,
        dedup_key=dedup,
    )
    try:
        with session.begin_nested():
            session.add(message)
            session.flush()
    except IntegrityError:
        return None
    report_row = None
    try:
        report_row = write_report_file(
            session,
            settings,
            user_id=user_id,
            project=project,
            message_id=message.id,
            body=body,
            hhmm=hhmm,
            local_day=local_day,
            created_at=now,
        )
        if report_row is not None:
            write_report_meta(
                settings,
                report_row.rel_path,
                {
                    "report_id": report_row.id,
                    "project": project,
                    "report_date": local_day,
                    "slot_hhmm": hhmm,
                    "allowed_keys": sorted(snap.allowed_keys),
                    "allowed_counts": snap.allowed_counts,
                    "overview": snap.facts.get("overview", {}),
                    "facts": snap.facts,
                },
            )
            message.body = "\n".join(summary_lines) + f"\n[[report:{report_row.id}]]"
    except OSError:
        log.exception(
            "failed to write health report file user=%s project=%s day=%s slot=%s",
            user_id,
            project,
            local_day,
            hhmm,
        )
    return message


def run_due_reports(session: Session, now: datetime, settings: Settings) -> list[DueReport]:
    """Weekday slots → one health report artifact per PM project (upgrade of short digest)."""
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
            message = persist_health_report(
                session,
                settings,
                user_id=slot.user_id,
                project=project,
                now=now,
                hhmm=hhmm,
                local_day=local_day,
                dedup=dedup,
            )
            if message is None:
                continue
            # Narrative already embedded in file; no agent follow-up enqueue.
    return due
