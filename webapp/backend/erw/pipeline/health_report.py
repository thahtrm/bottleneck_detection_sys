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


def _bullets(items: list[str]) -> str:
    if not items:
        return "- (không có)\n"
    return "".join(f"- {line}\n" for line in items)


def render_facts_markdown(snap: HealthSnapshot) -> str:
    o = snap.facts["overview"]
    p = snap.facts["progress"]
    r = snap.facts["risk"]
    b = snap.facts["bottleneck"]
    d = snap.facts["dependency"]
    res = snap.facts["resource"]
    a = snap.facts["actions"]

    parts: list[str] = [
        f"# Báo cáo sức khỏe dự án — {snap.project} — {snap.day_iso}",
        f"> TZ {snap.tz} · Generated {snap.generated_at}",
        "",
        "## 1. Overview",
        "### Facts",
        f"- Dự án: **{o['name']}** (`{o['project']}`)",
        f"- Sprint: {o['sprint_line'] or 'Không có sprint active'}",
        f"- Open: {o['open_count']} · Done: {o['done_count']}",
        f"- Risk HIGH/MED: {o['high_count']}/{o['med_count']} · Risky: {o['risky_count']} "
        f"(+{o['raised_24h']} tăng bậc 24h) · Blocked: {o['blocked_count']}",
        f"- Mới 24h: {o['new_24h']} (critical: {o['new_critical']})",
        "",
        "## 2. Today’s progress",
        "### Facts",
        f"- Created 24h: {p['created_count']} · Resolved: {p['resolved_count']} · Updated: {p['updated_count']} · "
        f"Status transitions: {p['transition_count']}",
    ]
    parts.append("Created:")
    parts.append(
        _bullets([f"{x['key']} — {x['summary']}" for x in p["created"]]).rstrip()
        if p["created"]
        else "- (không có)"
    )
    parts.append("Resolved:")
    parts.append(
        _bullets([f"{x['key']} — {x['summary']}" for x in p["resolved"]]).rstrip()
        if p["resolved"]
        else "- (không có)"
    )
    parts.append("Status transitions:")
    parts.append(
        _bullets([f"{x['key']}: {x['from']} → {x['to']}" for x in p["status_transitions"]]).rstrip()
        if p["status_transitions"]
        else "- (không có)"
    )
    parts.extend(["", "## 3. Risk alerts", "### Facts", f"- Risky open: {r['risky_count']} (raised 24h: {r['raised_24h']})"])
    parts.append(
        _bullets(
            [
                f"{x['key']} [{x['level']}] {x['summary']} · {x['deadline'] or 'chưa hạn'} · @{x['assignee']}"
                + (" · blocked" if x["blocked"] else "")
                for x in r["top"]
            ]
        ).rstrip()
        if r["top"]
        else "- (không có)"
    )
    parts.extend(["", "## 4. Bottleneck analysis", "### Facts", f"- Blocked open: {b['blocked_count']}"])
    parts.append(
        _bullets(
            [
                f"{x['key']} — {x['summary']} · @{x['assignee']}"
                + (f" · blockers {', '.join(x['blockers'])}" if x["blockers"] else "")
                for x in b["blocked"]
            ]
        ).rstrip()
        if b["blocked"]
        else "- (không có)"
    )
    parts.append("Top blockers by fan-out:")
    parts.append(
        _bullets([f"{x['key']} → {x['downstream']} downstream" for x in b["top_blockers_by_fanout"]]).rstrip()
        if b["top_blockers_by_fanout"]
        else "- (không có)"
    )
    parts.extend(["", "## 5. Dependency impact", "### Facts", f"- Links touching HIGH/blocked: {d['link_count']}"])
    parts.append(
        _bullets([f"{x['source']} —{x['type']}→ {x['target']}" for x in d["links"]]).rstrip()
        if d["links"]
        else "- (không có)"
    )
    parts.extend(
        [
            "",
            "## 6. Resource allocation",
            "### Facts",
            f"- Unassigned open: {res['unassigned']} · Median open/assignee: {res['median_open']}",
        ]
    )
    parts.append(
        _bullets([f"{x['name']}: {x['open_count']} việc ({', '.join(x['keys'])})" for x in res["assignees"]]).rstrip()
        if res["assignees"]
        else "- (không có)"
    )
    parts.extend(["", "## 7. Action recommendations", "### Facts (ứng viên)"])
    parts.append(
        _bullets([f"{x['key']} — {x['reason']}: {x['detail']}" for x in a["candidates"]]).rstrip()
        if a["candidates"]
        else "- (không có)"
    )
    parts.append("")
    return "\n".join(parts) + "\n"


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
    if not narratives:
        return facts_md
    mapping = {
        "## 1. Overview": "overview",
        "## 2. Today’s progress": "progress",
        "## 3. Risk alerts": "risk",
        "## 4. Bottleneck analysis": "bottleneck",
        "## 5. Dependency impact": "dependency",
        "## 6. Resource allocation": "resource",
        "## 7. Action recommendations": "actions",
    }
    lines = facts_md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        sid = mapping.get(line.strip())
        if sid and narratives.get(sid):
            # Insert narrative after Facts block: find next ### Facts then skip until next ## or end
            i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                out.append(lines[i])
                i += 1
            out.append("### Nhận định")
            out.append(narratives[sid])
            out.append("")
            continue
        i += 1
    return "\n".join(out).rstrip() + "\n"


def md_to_simple_html(md: str) -> str:
    chunks: list[str] = ['<html><head><meta charset="utf-8"></head><body>']
    in_list = False
    for raw in md.splitlines():
        line = raw.rstrip()
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
        elif line.startswith("### "):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("> "):
            if in_list:
                chunks.append("</ul>")
                in_list = False
            chunks.append(f"<p><em>{escape(line[2:])}</em></p>")
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
    chunks.append("</body></html>")
    return "\n".join(chunks)


def write_pdf_from_markdown(md: str, path: Path) -> bool:
    if pisa is None:
        log.warning("xhtml2pdf not installed; skip PDF")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    html = md_to_simple_html(md)
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


def build_health_markdown(session: Session, project: str, now: datetime, settings: Settings) -> tuple[str, HealthSnapshot]:
    snap = collect_health_snapshot(session, project, now, settings)
    facts_md = render_facts_markdown(snap)
    narratives = narrate_health(snap, settings)
    body = merge_narrative(facts_md, narratives)
    return body, snap
