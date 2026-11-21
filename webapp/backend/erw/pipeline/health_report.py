"""Daily Project Health Report — 7-section facts + optional AI narrative + PDF."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from erw.domain.types import Level
from erw.integrations.llm import call_ollama_chat
from erw.models import Change, Issue, Link, Project, RiskState
from erw.pipeline.chat_lookup import blocker_keys, blocks_keys, keys_in_text
from erw.pipeline.digest import collect_digest
from erw.settings import Settings

try:
    from xhtml2pdf import pisa
except Exception:  # optional dep at runtime / test envs without PDF extras
    pisa = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
TOP_N = 8
SECTION_IDS = (
    "overview",
    "progress",
    "risk",
    "bottleneck",
    "dependency",
    "resource",
    "actions",
)

# xhtml2pdf only allows font files under the document base dir (/app/webapp/backend).
_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
_FONT_CANDIDATES = (
    _FONT_DIR / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
_FONT_BOLD_CANDIDATES = (
    _FONT_DIR / "DejaVuSans-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


def _pdf_font_css() -> str:
    """Embed a Unicode-capable face so Vietnamese narrative glyphs render in PDF."""
    regular = next((p for p in _FONT_CANDIDATES if p.is_file()), None)
    bold = next((p for p in _FONT_BOLD_CANDIDATES if p.is_file()), None)
    if regular is None:
        return "body { font-family: Helvetica, Arial, sans-serif; }"
    # Prefer plain filesystem paths; file:// URIs are blocked by xhtml2pdf resource policy.
    faces = [
        "@font-face {"
        "font-family: ReportSans;"
        f"src: url('{regular}');"
        "font-weight: normal;"
        "}"
    ]
    if bold is not None:
        faces.append(
            "@font-face {"
            "font-family: ReportSans;"
            f"src: url('{bold}');"
            "font-weight: bold;"
            "}"
        )
    return "\n".join(faces) + "\nbody { font-family: ReportSans, Helvetica, Arial, sans-serif; }"


@dataclass
class HealthSnapshot:
    project: str
    day_iso: str
    day_label: str
    tz: str
    generated_at: str
    facts: dict[str, Any]
    allowed_keys: frozenset[str] = field(default_factory=frozenset)
    allowed_counts: dict[str, int] = field(default_factory=dict)


def _level(name: str | None) -> Level:
    return Level[name] if name in Level.__members__ else Level.LOW


def collect_health_snapshot(session: Session, project: str, now: datetime, settings: Settings) -> HealthSnapshot:
    tz = ZoneInfo(settings.tz)
    local = now.astimezone(tz)
    since = now - timedelta(hours=24)
    digest = collect_digest(session, project, now, settings)

    rows = session.execute(
        select(Issue, RiskState)
        .outerjoin(RiskState, RiskState.issue_key == Issue.key)
        .where(Issue.project_key == project, Issue.deleted_at.is_(None))
    ).all()

    open_rows = [(i, r) for i, r in rows if i.status_category != "done"]
    done_rows = [(i, r) for i, r in rows if i.status_category == "done"]
    high = sum(1 for _, r in open_rows if r is not None and _level(r.level) == Level.HIGH)
    med = sum(1 for _, r in open_rows if r is not None and _level(r.level) == Level.MED)

    created_24h = [i for i, _ in rows if i.created_at and i.created_at >= since]
    resolved_24h = [i for i, _ in rows if i.resolved_at and i.resolved_at >= since]
    updated_24h = [
        i
        for i, _ in rows
        if i.updated_at and i.updated_at >= since and i not in created_24h and i not in resolved_24h
    ]

    status_changes = session.scalars(
        select(Change)
        .join(Issue, Issue.key == Change.issue_key)
        .where(
            Issue.project_key == project,
            Change.field == "status",
            Change.at >= since,
        )
        .order_by(Change.at.desc())
        .limit(40)
    ).all()

    blocked_rows = [(i, r) for i, r in open_rows if r is not None and r.blocked]
    fanout: Counter[str] = Counter()
    for issue, _risk in open_rows:
        for target in blocks_keys(session, issue.key):
            fanout[issue.key] += 1
            _ = target
    top_blockers = fanout.most_common(TOP_N)

    dep_lines: list[dict[str, str]] = []
    focus = {i.key for i, r in open_rows if r is not None and (_level(r.level) >= Level.HIGH or r.blocked)}
    if focus:
        links = session.scalars(
            select(Link).where(or_(Link.source_key.in_(focus), Link.target_key.in_(focus)))
        ).all()
        for link in links[:40]:
            dep_lines.append(
                {
                    "source": link.source_key,
                    "target": link.target_key,
                    "type": link.type_std or "relates",
                }
            )

    load: dict[str, list[str]] = defaultdict(list)
    unassigned = 0
    for issue, _risk in open_rows:
        name = (issue.assignee_name or issue.assignee_id or "").strip()
        if not name:
            unassigned += 1
        else:
            load[name].append(issue.key)
    load_sorted = sorted(load.items(), key=lambda item: (-len(item[1]), item[0].casefold()))
    counts = [len(v) for _, v in load_sorted]
    median = sorted(counts)[len(counts) // 2] if counts else 0

    action_candidates: list[dict[str, str]] = []
    for issue, risk in blocked_rows[:TOP_N]:
        action_candidates.append(
            {
                "key": issue.key,
                "reason": "blocked",
                "detail": f"Bị block · {risk.deadline_label or 'chưa có hạn'}",
            }
        )
    for item in digest.top_risky:
        if item.key not in {a["key"] for a in action_candidates}:
            action_candidates.append(
                {
                    "key": item.key,
                    "reason": "risk",
                    "detail": f"{item.level_name} · {item.deadline_label or 'chưa có hạn'}",
                }
            )
    for name, keys in load_sorted[:3]:
        if median and len(keys) > median + 1:
            action_candidates.append(
                {
                    "key": keys[0],
                    "reason": "overload",
                    "detail": f"{name} đang giữ {len(keys)} việc mở (median {median})",
                }
            )

    proj = session.get(Project, project)
    facts = {
        "overview": {
            "project": project,
            "name": (proj.name if proj else "") or project,
            "sprint_line": digest.sprint_line,
            "open_count": len(open_rows),
            "done_count": len(done_rows),
            "high_count": high,
            "med_count": med,
            "blocked_count": digest.blocked_count,
            "risky_count": digest.risky_count,
            "raised_24h": digest.raised_24h,
            "new_24h": digest.new_24h,
            "new_critical": digest.new_critical,
        },
        "progress": {
            "created": [{"key": i.key, "summary": i.summary or ""} for i in created_24h[:TOP_N]],
            "resolved": [{"key": i.key, "summary": i.summary or ""} for i in resolved_24h[:TOP_N]],
            "updated": [{"key": i.key, "summary": i.summary or ""} for i in updated_24h[:TOP_N]],
            "status_transitions": [
                {
                    "key": c.issue_key,
                    "from": c.from_str or c.from_val or "",
                    "to": c.to_str or c.to_val or "",
                }
                for c in status_changes[:TOP_N]
            ],
            "created_count": len(created_24h),
            "resolved_count": len(resolved_24h),
            "updated_count": len(updated_24h),
            "transition_count": len(status_changes),
        },
        "risk": {
            "risky_count": digest.risky_count,
            "raised_24h": digest.raised_24h,
            "top": [
                {
                    "key": item.key,
                    "summary": item.summary,
                    "level": item.level_name,
                    "deadline": item.deadline_label,
                    "assignee": item.assignee,
                    "blocked": item.blocked,
                }
                for item in digest.top_risky
            ],
        },
        "bottleneck": {
            "blocked_count": len(blocked_rows),
            "blocked": [
                {
                    "key": i.key,
                    "summary": i.summary or "",
                    "assignee": i.assignee_name or i.assignee_id or "chưa giao",
                    "blockers": blocker_keys(session, i.key),
                    "blocks": blocks_keys(session, i.key),
                }
                for i, _r in blocked_rows[:TOP_N]
            ],
            "top_blockers_by_fanout": [{"key": k, "downstream": n} for k, n in top_blockers],
        },
        "dependency": {"links": dep_lines, "link_count": len(dep_lines)},
        "resource": {
            "unassigned": unassigned,
            "median_open": median,
            "assignees": [
                {"name": name, "open_count": len(keys), "keys": keys[:TOP_N]} for name, keys in load_sorted[:TOP_N]
            ],
        },
        "actions": {"candidates": action_candidates[:TOP_N]},
    }

    blob = json.dumps(facts, ensure_ascii=False)
    allowed = frozenset(keys_in_text(blob))
    allowed_counts = {
        "open_count": len(open_rows),
        "done_count": len(done_rows),
        "high_count": high,
        "med_count": med,
        "blocked_count": digest.blocked_count,
        "risky_count": digest.risky_count,
        "raised_24h": digest.raised_24h,
        "new_24h": digest.new_24h,
        "new_critical": digest.new_critical,
        "created_count": len(created_24h),
        "resolved_count": len(resolved_24h),
        "updated_count": len(updated_24h),
        "transition_count": len(status_changes),
        "unassigned": unassigned,
        "median_open": median,
        "link_count": len(dep_lines),
    }
    return HealthSnapshot(
        project=project,
        day_iso=local.date().isoformat(),
        day_label=f"{local:%d/%m/%Y}",
        tz=settings.tz,
        generated_at=now.isoformat(),
        facts=facts,
        allowed_keys=allowed,
        allowed_counts=allowed_counts,
    )


SECTION_TITLES = {
    "overview": "1. Overview",
    "progress": "2. Today’s progress",
    "risk": "3. Risk alerts",
    "bottleneck": "4. Bottleneck analysis",
    "dependency": "5. Dependency impact",
    "resource": "6. Resource allocation",
    "actions": "7. Action recommendations",
}


def _bullets(items: list[str]) -> str:
    if not items:
        return "- (không có)\n"
    return "".join(f"- {line}\n" for line in items)


def overall_status(snap: HealthSnapshot) -> tuple[str, str]:
    """Return (code, label) from deterministic overview counts."""
    o = snap.facts["overview"]
    if int(o.get("high_count") or 0) > 0 or int(o.get("blocked_count") or 0) > 0:
        return "AT_RISK", "At risk"
    if int(o.get("risky_count") or 0) > 0 or int(o.get("med_count") or 0) > 0:
        return "WATCH", "Watch"
    return "HEALTHY", "Healthy"


def _section_facts_blocks(snap: HealthSnapshot) -> dict[str, list[str]]:
    o = snap.facts["overview"]
    p = snap.facts["progress"]
    r = snap.facts["risk"]
    b = snap.facts["bottleneck"]
    d = snap.facts["dependency"]
    res = snap.facts["resource"]
    a = snap.facts["actions"]
    return {
        "overview": [
            f"- Dự án: **{o['name']}** (`{o['project']}`)",
            f"- Sprint: {o['sprint_line'] or 'Không có sprint active'}",
            f"- Open: {o['open_count']} · Done: {o['done_count']}",
            f"- Risk HIGH/MED: {o['high_count']}/{o['med_count']} · Risky: {o['risky_count']} "
            f"(+{o['raised_24h']} tăng bậc 24h) · Blocked: {o['blocked_count']}",
            f"- Mới 24h: {o['new_24h']} (critical: {o['new_critical']})",
        ],
        "progress": [
            f"- Created 24h: {p['created_count']} · Resolved: {p['resolved_count']} · "
            f"Updated: {p['updated_count']} · Status transitions: {p['transition_count']}",
            "Created:",
            _bullets([f"{x['key']} — {x['summary']}" for x in p["created"]]).rstrip()
            if p["created"]
            else "- (không có)",
            "Resolved:",
            _bullets([f"{x['key']} — {x['summary']}" for x in p["resolved"]]).rstrip()
            if p["resolved"]
            else "- (không có)",
            "Status transitions:",
            _bullets([f"{x['key']}: {x['from']} → {x['to']}" for x in p["status_transitions"]]).rstrip()
            if p["status_transitions"]
            else "- (không có)",
        ],
        "risk": [
            f"- Risky open: {r['risky_count']} (raised 24h: {r['raised_24h']})",
            _bullets(
                [
                    f"{x['key']} `[{x['level']}]` {x['summary']} · {x['deadline'] or 'chưa hạn'} · @{x['assignee']}"
                    + (" · `BLOCKED`" if x["blocked"] else "")
                    for x in r["top"]
                ]
            ).rstrip()
            if r["top"]
            else "- (không có)",
        ],
        "bottleneck": [
            f"- Blocked open: {b['blocked_count']}",
            _bullets(
                [
                    f"{x['key']} — {x['summary']} · @{x['assignee']}"
                    + (f" · blockers {', '.join(x['blockers'])}" if x["blockers"] else "")
                    for x in b["blocked"]
                ]
            ).rstrip()
            if b["blocked"]
            else "- (không có)",
            "Top blockers by fan-out:",
            _bullets([f"{x['key']} → {x['downstream']} downstream" for x in b["top_blockers_by_fanout"]]).rstrip()
            if b["top_blockers_by_fanout"]
            else "- (không có)",
        ],
        "dependency": [
            f"- Links touching HIGH/blocked: {d['link_count']}",
            _bullets([f"{x['source']} —{x['type']}→ {x['target']}" for x in d["links"]]).rstrip()
            if d["links"]
            else "- (không có)",
        ],
        "resource": [
            f"- Unassigned open: {res['unassigned']} · Median open/assignee: {res['median_open']}",
            _bullets([f"{x['name']}: {x['open_count']} việc ({', '.join(x['keys'])})" for x in res["assignees"]]).rstrip()
            if res["assignees"]
            else "- (không có)",
        ],
        "actions": [
            _bullets([f"{x['key']} — {x['reason']}: {x['detail']}" for x in a["candidates"]]).rstrip()
            if a["candidates"]
            else "- (không có)",
        ],
    }


def render_facts_markdown(snap: HealthSnapshot) -> str:
    """Facts-only markdown (tests + LLM-down path). Modern card-oriented structure."""
    return render_health_markdown(snap, {})


def render_health_markdown(snap: HealthSnapshot, narratives: dict[str, str] | None = None) -> str:
    """Human-readable md: hero + KPI grid + numbered sections + AI insight callouts."""
    narratives = narratives or {}
    o = snap.facts["overview"]
    status_code, status_label = overall_status(snap)
    blocks = _section_facts_blocks(snap)
    parts: list[str] = [
        "# Daily Project Health Report",
        f"## {snap.project} · {o['name']}",
        f"> {snap.day_label} · TZ {snap.tz} · Generated {snap.generated_at}",
        "",
        f"**Overall status:** `{status_code}` {status_label}",
        f"**Sprint:** {o['sprint_line'] or 'Không có sprint active'}",
        "",
        "### KPI Snapshot",
        "",
        "| Open | Done | Risky | Blocked | HIGH | MED |",
        "| :---: | :---: | :---: | :---: | :---: | :---: |",
        f"| {o['open_count']} | {o['done_count']} | {o['risky_count']} | {o['blocked_count']} | "
        f"{o['high_count']} | {o['med_count']} |",
        "",
        f"_Raised 24h: {o['raised_24h']} · New 24h: {o['new_24h']} (critical {o['new_critical']})_",
        "",
        "---",
        "",
    ]
    for sid in SECTION_IDS:
        title = SECTION_TITLES[sid]
        parts.append(f"## {title}")
        parts.append("### Facts" + (" (ứng viên)" if sid == "actions" else ""))
        parts.extend(blocks[sid])
        insight = (narratives.get(sid) or "").strip()
        if insight:
            parts.append("")
            parts.append("### AI Insight")
            parts.append(f"> {insight}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _strip_disallowed(text: str, allowed_keys: frozenset[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return key if key in allowed_keys else ""

    cleaned = KEY_RE.sub(repl, text)
    return "\n".join(line for line in cleaned.splitlines() if line.strip())


def narrate_health(snap: HealthSnapshot, settings: Settings) -> dict[str, str]:
    """Return {section_id: narrative}. Empty dict on failure."""
    if not settings.ollama_url:
        return {}
    system = (
        "You write short Vietnamese PM narratives for a daily project health report. "
        "Reply JSON object with keys: overview, progress, risk, bottleneck, dependency, resource, actions. "
        "Each value is 1-3 sentences. ONLY mention issue keys present in facts.allowed_keys. "
        "Do not invent counts; use only numbers present in facts. If unsure, omit."
    )
    prompt = json.dumps(
        {
            "facts": snap.facts,
            "allowed_keys": sorted(snap.allowed_keys),
            "allowed_counts": snap.allowed_counts,
        },
        ensure_ascii=False,
    )
    try:
        raw = call_ollama_chat(prompt, system, settings.llm_model, settings.ollama_url)
    except Exception:
        log.exception("health narrative LLM failed")
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for sid in SECTION_IDS:
        value = raw.get(sid)
        if isinstance(value, str) and value.strip():
            out[sid] = _strip_disallowed(value.strip(), snap.allowed_keys)
    return out


def merge_narrative(facts_md: str, narratives: dict[str, str]) -> str:
    """Backward-compatible: if facts_md already full template, re-render is preferred via snap."""
    if not narratives:
        return facts_md
    # Legacy path: append insights after each ## N. heading block.
    mapping = {f"## {title}": sid for sid, title in SECTION_TITLES.items()}
    lines = facts_md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        sid = mapping.get(line.strip())
        if sid and narratives.get(sid):
            i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                out.append(lines[i])
                i += 1
            if not any(x.strip() == "### AI Insight" for x in out[-12:]):
                out.append("### AI Insight")
                out.append(f"> {narratives[sid]}")
                out.append("")
            continue
        i += 1
    return "\n".join(out).rstrip() + "\n"


def _badge_html(code: str, label: str) -> str:
    colors = {
        "AT_RISK": ("#d93025", "#ffffff"),
        "WATCH": ("#e37400", "#ffffff"),
        "HEALTHY": ("#188038", "#ffffff"),
        "HIGH": ("#d93025", "#ffffff"),
        "MED": ("#e37400", "#ffffff"),
        "LOW": ("#188038", "#ffffff"),
        "BLOCKED": ("#5f6368", "#ffffff"),
    }
    bg, fg = colors.get(code, ("#1a73e8", "#ffffff"))
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'background:{bg};color:{fg};font-size:11px;font-weight:700;'
        f'letter-spacing:0.04em;text-transform:uppercase;">{escape(label)}</span>'
    )


def _level_badge(level: str) -> str:
    return _badge_html(level, level)


def _ul_html(items: list[str]) -> str:
    if not items:
        return "<p class='muted'>(không có)</p>"
    lis = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<ul>{lis}</ul>"


def render_health_html(snap: HealthSnapshot, narratives: dict[str, str] | None = None) -> str:
    """Card + KPI grid + numbered sections for xhtml2pdf (table-based layout)."""
    narratives = narratives or {}
    o = snap.facts["overview"]
    p = snap.facts["progress"]
    r = snap.facts["risk"]
    b = snap.facts["bottleneck"]
    d = snap.facts["dependency"]
    res = snap.facts["resource"]
    a = snap.facts["actions"]
    status_code, status_label = overall_status(snap)

    def kpi_cell(label: str, value: Any, accent: str = "#1a73e8") -> str:
        return (
            "<td width='16%' style='border:1px solid #e8eaed;border-radius:8px;padding:12px 8px;"
            "text-align:center;background:#ffffff;'>"
            f"<div style='font-size:22px;font-weight:800;color:{accent};'>{escape(str(value))}</div>"
            f"<div style='font-size:10px;font-weight:700;letter-spacing:0.06em;color:#5f6368;"
            f"text-transform:uppercase;margin-top:4px;'>{escape(label)}</div>"
            "</td>"
        )

    risk_rows = []
    for item in r["top"]:
        badges = _level_badge(item["level"])
        if item["blocked"]:
            badges += " " + _badge_html("BLOCKED", "Blocked")
        risk_rows.append(
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #e8eaed;font-family:monospace;font-weight:700;'>"
            f"{escape(item['key'])}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #e8eaed;'>{badges}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #e8eaed;'>{escape(item['summary'])}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #e8eaed;color:#5f6368;'>"
            f"{escape(item['deadline'] or 'chưa hạn')}<br/>@{escape(item['assignee'])}</td>"
            "</tr>"
        )

    def section(num: int, title: str, sid: str, body_html: str) -> str:
        insight = (narratives.get(sid) or "").strip()
        insight_html = ""
        if insight:
            insight_html = (
                "<div style='margin-top:12px;padding:12px 14px;border-left:4px solid #20beff;"
                "background:#e8f7ff;border-radius:0 8px 8px 0;'>"
                "<div style='font-size:10px;font-weight:800;letter-spacing:0.08em;color:#1a73e8;"
                "text-transform:uppercase;margin-bottom:6px;'>AI Insight</div>"
                f"<div style='font-size:12px;line-height:1.45;color:#202124;'>{escape(insight)}</div>"
                "</div>"
            )
        return (
            "<div style='margin:18px 0 0 0;padding:16px;border:1px solid #e8eaed;border-radius:12px;"
            "background:#ffffff;'>"
            "<table width='100%'><tr>"
            f"<td width='36' valign='top'><div style='width:28px;height:28px;border-radius:14px;"
            f"background:#1a73e8;color:#fff;text-align:center;line-height:28px;font-weight:800;"
            f"font-size:13px;'>{num}</div></td>"
            f"<td valign='middle'><div style='font-size:15px;font-weight:800;color:#202124;'>"
            f"{escape(title)}</div></td>"
            "</tr></table>"
            f"<div style='margin-top:10px;'>{body_html}</div>"
            f"{insight_html}"
            "</div>"
        )

    overview_body = (
        f"<p><strong>Dự án:</strong> {escape(o['name'])} "
        f"(<span style='font-family:monospace;'>{escape(o['project'])}</span>)</p>"
        f"<p><strong>Sprint:</strong> {escape(o['sprint_line'] or 'Không có sprint active')}</p>"
        f"<p>Open {o['open_count']} · Done {o['done_count']} · "
        f"HIGH/MED {o['high_count']}/{o['med_count']} · "
        f"Risky {o['risky_count']} (+{o['raised_24h']} raised 24h) · Blocked {o['blocked_count']}</p>"
        f"<p class='muted'>Mới 24h: {o['new_24h']} (critical {o['new_critical']})</p>"
    )
    progress_body = (
        f"<p>Created {p['created_count']} · Resolved {p['resolved_count']} · "
        f"Updated {p['updated_count']} · Transitions {p['transition_count']}</p>"
        + "<p><strong>Created</strong></p>"
        + _ul_html([f"{x['key']} — {x['summary']}" for x in p["created"]])
        + "<p><strong>Resolved</strong></p>"
        + _ul_html([f"{x['key']} — {x['summary']}" for x in p["resolved"]])
        + "<p><strong>Status transitions</strong></p>"
        + _ul_html([f"{x['key']}: {x['from']} → {x['to']}" for x in p["status_transitions"]])
    )
    risk_body = (
        f"<p>Risky open: <strong>{r['risky_count']}</strong> (raised 24h: {r['raised_24h']})</p>"
        + (
            "<table width='100%' cellpadding='0' cellspacing='0'>"
            "<tr style='background:#f8f9fa;'>"
            "<th align='left' style='padding:8px;font-size:10px;color:#5f6368;'>KEY</th>"
            "<th align='left' style='padding:8px;font-size:10px;color:#5f6368;'>STATUS</th>"
            "<th align='left' style='padding:8px;font-size:10px;color:#5f6368;'>SUMMARY</th>"
            "<th align='left' style='padding:8px;font-size:10px;color:#5f6368;'>DUE / OWNER</th>"
            "</tr>"
            + "".join(risk_rows)
            + "</table>"
            if risk_rows
            else "<p class='muted'>(không có)</p>"
        )
    )
    bottleneck_body = (
        f"<p>Blocked open: <strong>{b['blocked_count']}</strong></p>"
        + _ul_html(
            [
                f"{x['key']} — {x['summary']} · @{x['assignee']}"
                + (f" · blockers {', '.join(x['blockers'])}" if x["blockers"] else "")
                for x in b["blocked"]
            ]
        )
        + "<p><strong>Top blockers by fan-out</strong></p>"
        + _ul_html([f"{x['key']} → {x['downstream']} downstream" for x in b["top_blockers_by_fanout"]])
    )
    dependency_body = (
        f"<p>Links touching HIGH/blocked: <strong>{d['link_count']}</strong></p>"
        + _ul_html([f"{x['source']} —{x['type']}→ {x['target']}" for x in d["links"]])
    )
    resource_body = (
        f"<p>Unassigned: <strong>{res['unassigned']}</strong> · "
        f"Median open/assignee: <strong>{res['median_open']}</strong></p>"
        + _ul_html([f"{x['name']}: {x['open_count']} việc ({', '.join(x['keys'])})" for x in res["assignees"]])
    )
    actions_body = _ul_html([f"{x['key']} — {x['reason']}: {x['detail']}" for x in a["candidates"]])

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  @page {{ margin: 1.4cm; }}
  {_pdf_font_css()}
  body {{ color: #202124; font-size: 12px; }}
  .card {{ border: 1px solid #dadce0; border-radius: 16px; padding: 20px; background: #fff; }}
  .hero {{ background: linear-gradient(135deg, #e8f7ff 0%, #ffffff 55%, #fff8e1 100%);
           border: 1px solid #e8eaed; border-radius: 16px; padding: 20px; margin-bottom: 16px; }}
  .muted {{ color: #5f6368; font-size: 11px; }}
  ul {{ margin: 6px 0 6px 18px; padding: 0; }}
  li {{ margin: 3px 0; line-height: 1.4; }}
  p {{ margin: 6px 0; line-height: 1.45; }}
</style></head><body>
<div class="card">
  <div class="hero">
    <div style="font-size:11px;font-weight:800;letter-spacing:0.12em;color:#1a73e8;text-transform:uppercase;">
      Daily Project Health
    </div>
    <div style="font-size:22px;font-weight:800;margin:6px 0 4px 0;">{escape(snap.project)} · {escape(o['name'])}</div>
    <div class="muted">{escape(snap.day_label)} · TZ {escape(snap.tz)} · Generated {escape(snap.generated_at)}</div>
    <div style="margin-top:12px;">{_badge_html(status_code, status_label)}
      <span style="margin-left:10px;color:#5f6368;font-size:12px;">
        Sprint: {escape(o['sprint_line'] or 'Không có sprint active')}
      </span>
    </div>
  </div>

  <div style="font-size:11px;font-weight:800;letter-spacing:0.08em;color:#5f6368;text-transform:uppercase;margin:4px 0 8px 0;">
    KPI Snapshot
  </div>
  <table width="100%" cellspacing="6" cellpadding="0" style="margin-bottom:8px;">
    <tr>
      {kpi_cell("Open", o["open_count"], "#1a73e8")}
      {kpi_cell("Done", o["done_count"], "#188038")}
      {kpi_cell("Risky", o["risky_count"], "#e37400")}
      {kpi_cell("Blocked", o["blocked_count"], "#5f6368")}
      {kpi_cell("HIGH", o["high_count"], "#d93025")}
      {kpi_cell("MED", o["med_count"], "#e37400")}
    </tr>
  </table>
  <p class="muted">Raised 24h: {o["raised_24h"]} · New 24h: {o["new_24h"]} (critical {o["new_critical"]})</p>

  {section(1, "Overview", "overview", overview_body)}
  {section(2, "Today’s progress", "progress", progress_body)}
  {section(3, "Risk alerts", "risk", risk_body)}
  {section(4, "Bottleneck analysis", "bottleneck", bottleneck_body)}
  {section(5, "Dependency impact", "dependency", dependency_body)}
  {section(6, "Resource allocation", "resource", resource_body)}
  {section(7, "Action recommendations", "actions", actions_body)}
</div>
</body></html>
"""


def write_pdf_from_health(
    snap: HealthSnapshot,
    narratives: dict[str, str] | None,
    path: Path,
) -> bool:
    if pisa is None:
        log.warning("xhtml2pdf not installed; skip PDF")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_health_html(snap, narratives)
    try:
        with path.open("wb") as handle:
            result = pisa.CreatePDF(html, dest=handle, encoding="utf-8")
        if result.err:
            log.warning("PDF render errors for %s", path)
            return False
        return True
    except Exception:
        log.exception("PDF write failed for %s", path)
        return False


def write_pdf_from_markdown(md: str, path: Path) -> bool:
    """Fallback when snapshot unavailable — minimal styled HTML from md markers."""
    if pisa is None:
        log.warning("xhtml2pdf not installed; skip PDF")
        return False
    # Prefer regenerating is better; keep lightweight converter for tests/old paths.
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        '<html><head><meta charset="utf-8"/><style>',
        _pdf_font_css(),
        "body{color:#202124;font-size:12px;}"
        "h1{color:#1a73e8;} h2{color:#202124;border-bottom:1px solid #dadce0;padding-bottom:4px;}"
        ".insight{border-left:4px solid #20beff;background:#e8f7ff;padding:8px 12px;margin:8px 0;}"
        "table{border-collapse:collapse;width:100%;margin:8px 0;}"
        "th,td{border:1px solid #e8eaed;padding:8px;text-align:center;}"
        "th{background:#f8f9fa;font-size:10px;color:#5f6368;}"
        "</style></head><body>",
    ]
    in_list = False
    in_table = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("|") and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                chunks.append("<table>")
                in_table = True
                chunks.append("<tr>" + "".join(f"<th>{escape(c)}</th>" for c in cells) + "</tr>")
            else:
                chunks.append("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            chunks.append("</table>")
            in_table = False
        if line.startswith("|") and "---" in line:
            continue
        if line.startswith("# "):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("### AI Insight"):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append("<div class='insight'><strong>AI Insight</strong>")
        elif line.startswith("### "):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("> "):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<p>{escape(line[2:])}</p></div>")
        elif line.startswith("- "):
            if not in_list:
                chunks.append("<ul>")
                in_list = True
            chunks.append(f"<li>{escape(line[2:])}</li>")
        elif not line.strip():
            if in_list:
                chunks.append("</ul>")
                in_list = False
        else:
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<p>{escape(line)}</p>")
    if in_list:
        chunks.append("</ul>")
    if in_table:
        chunks.append("</table>")
    chunks.append("</body></html>")
    html = "\n".join(chunks)
    try:
        with path.open("wb") as handle:
            result = pisa.CreatePDF(html, dest=handle, encoding="utf-8")
        if result.err:
            log.warning("PDF render errors for %s", path)
            return False
        return True
    except Exception:
        log.exception("PDF write failed for %s", path)
        return False


def pdf_rel_from_md(rel_path: str) -> str:
    if rel_path.endswith(".md"):
        return rel_path[:-3] + ".pdf"
    return rel_path + ".pdf"


def build_health_markdown(
    session: Session, project: str, now: datetime, settings: Settings
) -> tuple[str, HealthSnapshot, dict[str, str]]:
    snap = collect_health_snapshot(session, project, now, settings)
    narratives = narrate_health(snap, settings)
    body = render_health_markdown(snap, narratives)
    return body, snap, narratives
