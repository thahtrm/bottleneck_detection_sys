from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx

from erw.domain.types import Level

if TYPE_CHECKING:
    from erw.models import Issue, RiskState
    from erw.pipeline.alerts import AlertSpec
    from erw.settings import Settings

log = logging.getLogger(__name__)

PREFIX = {
    "risk_new": "[Nguy cơ trễ]",
    "risk_up": "[Tăng rủi ro]",
    "blocked": "[Bị block]",
    "critical": "[Quan trọng]",
    "handled": "[Đã xử lý]",
    "digest": "[Tổng hợp ngày]",
}
PM_KINDS = frozenset({"risk_up", "critical"})
MAX_ATTEMPTS = 3
MAX_FACTORS = 3


class SlackError(Exception):
    pass


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlackSender:
    def __init__(self, url: str, *, http: httpx.Client | None = None, backoff: float = 1.0):
        self.url = url
        self._http = http or httpx.Client(timeout=10)
        self._backoff = backoff

    def post(self, text: str) -> None:
        last = ""
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = self._http.post(self.url, json={"text": text})
            except httpx.TransportError as e:
                last = f"transport error: {e}"
            else:
                if resp.status_code < 300:
                    return
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code != 429 and resp.status_code < 500:
                    raise SlackError(last)
            if attempt < MAX_ATTEMPTS - 1 and self._backoff:
                time.sleep(self._backoff * (attempt + 1))
        raise SlackError(f"Slack post failed after {MAX_ATTEMPTS} attempts: {last}")


def format_alert(spec: AlertSpec, issue: Issue, rs: RiskState, settings: Settings) -> str:
    level = spec.level if spec.level is not None else (Level[rs.level] if rs.level else None)
    jira = settings.jira_base_url.rstrip("/")
    web = settings.web_base_url.rstrip("/")
    parts = [f"<{jira}/browse/{issue.key}|{issue.key}> {escape(issue.summary or '')}"]
    if level is not None:
        pct = f" {round(rs.delay_value * 100)}%" if rs.delay_value is not None else ""
        parts.append(f"{level.label_vi}{pct}")
    if rs.deadline_label:
        parts.append(escape(rs.deadline_label))
    if spec.kind in PM_KINDS:
        pm = settings.pm_name_by_project.get(issue.project_key)
        if pm:
            parts.append(f"@{escape(pm)}")
    else:
        who = issue.assignee_name or issue.assignee_id or "chưa giao"
        parts.append(f"@{escape(who)}")
    lines = [f"{PREFIX[spec.kind]}[{issue.project_key}] " + " · ".join(parts)]
    factors = [f for f in (rs.factors or [])][:MAX_FACTORS]
    if factors:
        reasons = "; ".join(escape(f"{(f.get('label') or '')} {(f.get('value') or '')}".strip()) for f in factors)
        lines.append(f"Lý do: {reasons}")
    lines.append(f"<{web}/issues/{issue.key}|Mở trên Early Risk>")
    return "\n".join(lines)
