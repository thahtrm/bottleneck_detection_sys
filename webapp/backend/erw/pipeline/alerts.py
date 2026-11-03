from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erw.domain.types import Level
from erw.integrations.slack import SlackSender, format_alert
from erw.models import Issue, Notification, RiskState
from erw.pipeline.evaluate import RiskChange
from erw.settings import Settings

log = logging.getLogger(__name__)

AlertKind = Literal["risk_new", "risk_up", "blocked", "critical", "handled", "digest"]
NotifyStatus = Literal["sent", "duplicate", "rate_limited", "failed", "disabled"]


@dataclass(frozen=True)
class AlertSpec:
    kind: AlertKind
    issue_key: str | None
    project: str
    level: Level | None
    dedup_key: str


def alerts_for(change: RiskChange) -> list[AlertSpec]:
    def spec(kind: AlertKind, dedup: str | None = None) -> AlertSpec:
        return AlertSpec(kind, change.key, change.project, change.level, dedup or f"{kind}:{change.key}:{change.level.name}")

    out = []
    if change.is_new:
        if change.level == Level.HIGH:
            out.append(spec("risk_new"))
    elif change.prev_level is not None and change.level > change.prev_level:
        out.append(spec("risk_up"))
    if change.newly_blocked:
        out.append(spec("blocked"))  # dispatch refines the dedup key with the blocker keys
    if change.became_critical:
        out.append(spec("critical"))
    return out


def notify(
    session: Session, spec: AlertSpec, text: str, sender, now: datetime, max_per_hour: int
) -> NotifyStatus:
    """Send once per dedup_key, honouring an hourly cap. `sender=None` records status 'disabled'."""
    row = session.scalar(select(Notification).where(Notification.dedup_key == spec.dedup_key))
    if row is not None and row.status == "sent":
        return "duplicate"
    if row is None:
        row = Notification(kind=spec.kind, issue_key=spec.issue_key, project_key=spec.project, dedup_key=spec.dedup_key)
        session.add(row)
    row.text = text
    sent = session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.status == "sent", Notification.sent_at > now - timedelta(minutes=60)
        )
    )
    if sender is None:
        status: NotifyStatus = "disabled"
    elif sent >= max_per_hour:
        status = "rate_limited"
    else:
        try:
            sender.post(text)
            status = "sent"
        except Exception:
            log.exception("Slack post failed for %s", spec.dedup_key)
            status = "failed"
    row.status = status
    row.sent_at = now if status == "sent" else None
    session.flush()
    return status


def dispatch(
    session: Session, changes: list[RiskChange], now: datetime, settings: Settings, sender=None
) -> None:
    if sender is None and settings.slack_webhook_url:
        sender = SlackSender(settings.slack_webhook_url)
    for change in changes:
        specs = alerts_for(change)
        if not specs:
            continue
        issue, rs = session.get(Issue, change.key), session.get(RiskState, change.key)
        if issue is None or rs is None:
            continue
        sent_any = False
        for spec in specs:
            if spec.kind == "blocked":
                value = next((f.get("value") for f in (rs.factors or []) if f.get("id") == "blocked"), "")
                spec = AlertSpec(spec.kind, spec.issue_key, spec.project, spec.level, f"blocked:{change.key}:{value}")
            status = notify(session, spec, format_alert(spec, issue, rs, settings), sender, now, settings.slack_max_per_hour)
            sent_any = sent_any or status == "sent"
        if sent_any:
            rs.last_alerted_level = change.level.name
    session.flush()
