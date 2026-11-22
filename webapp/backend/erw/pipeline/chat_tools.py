from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.auth import get_user_project_role
from erw.integrations.llm import get_cached_suggestion
from erw.models import Issue, ReportFile, User
from erw.pipeline.chat_lookup import (
    LookupKind,
    _answer_assignee,
    _answer_blocked,
    _answer_due,
    _answer_important,
    _answer_issue,
    _answer_open,
    _answer_overdue,
    _answer_risky,
    _answer_sprint,
    classify_question,
)
from erw.pipeline.chat_reports import persist_health_report, report_abs_path, report_dedup_key
from erw.domain.types import Level
from erw.pipeline.digest import collect_digest
from erw.settings import Settings

BOARD_TOOLS = frozenset(
    {
        "lookup_sprint",
        "lookup_blocked",
        "lookup_risky",
        "lookup_issue",
        "lookup_assignee_load",
        "lookup_due",
        "lookup_overdue",
        "lookup_important",
        "lookup_open",
        "get_digest_snapshot",
    }
)

REPORT_TOOLS = frozenset(
    {
        "list_health_reports",
        "get_health_report",
        "generate_health_report",
    }
)

FOUNDATION_TOOLS = BOARD_TOOLS | REPORT_TOOLS | frozenset({"get_issue_suggestion"})

KIND_TO_TOOL: dict[LookupKind, str] = {
    "sprint": "lookup_sprint",
    "blocked": "lookup_blocked",
    "risky": "lookup_risky",
    "issue": "lookup_issue",
    "assignee": "lookup_assignee_load",
    "due": "lookup_due",
    "overdue": "lookup_overdue",
    "important": "lookup_important",
    "open": "lookup_open",
}

REPORT_MARKER_RE = re.compile(r"\[\[report:(\d+)\]\]")
GENERATE_PHRASES = (
    "tạo báo cáo",
    "sinh báo cáo",
    "generate báo cáo",
    "generate daily health",
    "tạo báo cáo sức khỏe",
    "làm báo cáo sức khỏe",
    "báo cáo sức khỏe hôm nay",
)
UPDATE_PHRASES = (
    "cập nhật báo cáo",
    "làm mới báo cáo",
    "update báo cáo",
    "regenerate",
    "tạo lại báo cáo",
    "refresh báo cáo",
)


@dataclass(frozen=True)
class ToolResult:
    name: str
    facts: str
    allowed_keys: frozenset[str]
    payload: dict[str, Any]
    skip_recommendation: bool
    ok: bool
    error: str | None = None


def catalog_for_pm() -> list[dict[str, Any]]:
    """Tool schema for the agent prompt (read-only board + health report tools)."""
    return [
        {"name": "lookup_sprint", "args": {}, "hint_phrases": ["tiến độ sprint", "sprint"]},
        {"name": "lookup_blocked", "args": {}, "hint_phrases": ["bị block", "blocker", "chặn"]},
        {"name": "lookup_risky", "args": {}, "hint_phrases": ["nguy cơ trễ", "ưu tiên", "rủi ro"]},
        {"name": "lookup_issue", "args": {"text": "câu hỏi có mã ISSUE"}, "hint_phrases": ["DEMO-1"]},
        {"name": "lookup_assignee_load", "args": {}, "hint_phrases": ["được giao nhiều", "nhiều việc chưa xong"]},
        {"name": "lookup_due", "args": {}, "hint_phrases": ["sắp đến hạn", "đến hạn"]},
        {"name": "lookup_overdue", "args": {}, "hint_phrases": ["quá hạn", "trễ hạn"]},
        {"name": "lookup_important", "args": {}, "hint_phrases": ["đánh dấu quan trọng", "quan trọng"]},
        {"name": "lookup_open", "args": {}, "hint_phrases": ["tồn đọng", "công việc mở", "chưa xong"]},
        {"name": "get_digest_snapshot", "args": {}, "hint_phrases": ["tổng quan", "digest"]},
        {"name": "get_issue_suggestion", "args": {"issue_key": "DEMO-1"}, "hint_phrases": []},
        {
            "name": "list_health_reports",
            "args": {},
            "hint_phrases": ["danh sách báo cáo", "báo cáo nào"],
        },
        {
            "name": "get_health_report",
            "args": {"report_id": 1},
            "hint_phrases": ["theo báo cáo", "@report", "[[report:"],
        },
        {
            "name": "generate_health_report",
            "args": {"force": False},
            "hint_phrases": list(GENERATE_PHRASES + UPDATE_PHRASES),
        },
    ]


def extract_attached_report_id(text: str) -> int | None:
    match = REPORT_MARKER_RE.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def tool_hint(text: str, project_key: str) -> str | None:
    folded = (text or "").casefold()
    if any(p in folded for p in UPDATE_PHRASES) or any(p in folded for p in GENERATE_PHRASES):
        return "generate_health_report"
    if extract_attached_report_id(text) is not None or "@report" in folded or "theo báo cáo" in folded:
        return "get_health_report"
    kind = classify_question(text, project_key)
    if kind is None:
        return None
    return KIND_TO_TOOL.get(kind)


def _from_answer(name: str, answer) -> ToolResult:
    return ToolResult(
        name=name,
        facts=answer.facts,
        allowed_keys=frozenset(answer.allowed_keys),
        payload=dict(answer.payload),
        skip_recommendation=bool(answer.skip_recommendation),
        ok=True,
    )


def _meta_path(settings: Settings, rel_path: str) -> Path:
    meta_rel = rel_path[:-3] + ".meta.json" if rel_path.endswith(".md") else rel_path + ".meta.json"
    return report_abs_path(settings, meta_rel)


def _load_report_meta(settings: Settings, row: ReportFile) -> dict[str, Any]:
    path = _meta_path(settings, row.rel_path)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
    # Fallback: md body only + keys from text
    from erw.pipeline.chat_lookup import keys_in_text

    try:
        body = report_abs_path(settings, row.rel_path).read_text(encoding="utf-8")
    except Exception:
        body = ""
    return {
        "report_id": row.id,
        "project": row.project_key,
        "report_date": row.report_date,
        "slot_hhmm": row.slot_hhmm,
        "allowed_keys": sorted(keys_in_text(body)),
        "allowed_counts": {},
        "overview": {},
        "facts": {},
        "markdown_excerpt": body[:4000],
    }


def run_tool(
    session: Session,
    name: str,
    args: dict[str, Any] | None,
    project_key: str,
    now: datetime,
    settings: Settings,
    *,
    user_text: str = "",
    user_id: int | None = None,
) -> ToolResult:
    args = args or {}
    if name not in FOUNDATION_TOOLS:
        return ToolResult(name, "", frozenset(), {}, True, False, f"unknown tool: {name}")
    try:
        if name == "lookup_sprint":
            return _from_answer(name, _answer_sprint(session, project_key, now))
        if name == "lookup_blocked":
            return _from_answer(name, _answer_blocked(session, project_key))
        if name == "lookup_risky":
            return _from_answer(name, _answer_risky(session, project_key, now, settings))
        if name == "lookup_assignee_load":
            return _from_answer(name, _answer_assignee(session, project_key))
        if name == "lookup_due":
            return _from_answer(name, _answer_due(session, project_key, now, settings))
        if name == "lookup_overdue":
            return _from_answer(name, _answer_overdue(session, project_key, now, settings))
        if name == "lookup_important":
            return _from_answer(name, _answer_important(session, project_key))
        if name == "lookup_open":
            return _from_answer(name, _answer_open(session, project_key))
        if name == "lookup_issue":
            text = str(args.get("text") or user_text or "")
            return _from_answer(name, _answer_issue(session, project_key, text))
        if name == "get_digest_snapshot":
            snap = collect_digest(session, project_key, now, settings)
            top = [
                {
                    "key": item.key,
                    "level": item.level_name,
                    "assignee": item.assignee,
                    "deadline": item.deadline_label,
                    "summary": item.summary,
                }
                for item in snap.top_risky
            ]
            keys = frozenset(item.key for item in snap.top_risky)
            # A3: VI opener (no English "Digest:"); mirrors Slack build_digest tone.
            facts = (
                f"Nguy cơ trễ: {snap.risky_count} ({snap.raised_24h} tăng bậc 24h) · "
                f"Bị chặn: {snap.blocked_count}."
            )
            if snap.sprint_line:
                facts = f"{facts}\n{snap.sprint_line}"
            for item in snap.top_risky:
                level_vi = Level[item.level_name].label_vi if item.level_name in Level.__members__ else item.level_name
                bits = [item.key, f"mức {level_vi}"]
                if item.deadline_label:
                    bits.append(item.deadline_label)
                bits.append(f"@{item.assignee}")
                facts = f"{facts}\n{' · '.join(bits)}"
            return ToolResult(
                name,
                facts,
                keys,
                {
                    "kind": "digest",
                    "risky_count": snap.risky_count,
                    "raised_24h": snap.raised_24h,
                    "blocked_count": snap.blocked_count,
                    "new_24h": snap.new_24h,
                    "sprint_line": snap.sprint_line,
                    "top_risky": top,
                },
                True,
                True,
            )
        if name == "get_issue_suggestion":
            key = str(args.get("issue_key") or "").upper()
            issue = session.get(Issue, key) if key else None
            if issue is None or issue.project_key != project_key or issue.deleted_at is not None:
                return ToolResult(
                    name,
                    f"Không thấy suggestion cho {key or 'issue'}.",
                    frozenset(),
                    {"kind": "suggestion", "found": False, "issue_key": key},
                    True,
                    True,
                )
            cached = get_cached_suggestion(session, issue.key, issue.updated_at)
            output = cached.output if cached is not None and isinstance(cached.output, dict) else None
            return ToolResult(
                name,
                "",
                frozenset({issue.key}),
                {"kind": "suggestion", "found": output is not None, "issue_key": issue.key, "output": output},
                False,
                True,
            )
        if name == "list_health_reports":
            rows = session.scalars(
                select(ReportFile)
                .where(ReportFile.project_key == project_key, ReportFile.hidden_at.is_(None))
                .order_by(ReportFile.report_date.desc(), ReportFile.slot_hhmm.desc(), ReportFile.id.desc())
                .limit(15)
            ).all()
            lines = [
                f"#{row.id} {row.report_date} {row.slot_hhmm} — {(row.preview or '')[:80]}" for row in rows
            ]
            facts = "Báo cáo sức khỏe gần đây:\n" + ("\n".join(lines) if lines else "(chưa có)")
            return ToolResult(
                name,
                facts,
                frozenset(),
                {
                    "kind": "health_report_list",
                    "reports": [
                        {
                            "id": row.id,
                            "report_date": row.report_date,
                            "slot_hhmm": row.slot_hhmm,
                            "preview": row.preview,
                        }
                        for row in rows
                    ],
                },
                True,
                True,
            )
        if name == "get_health_report":
            report_id = args.get("report_id")
            if report_id is None:
                report_id = extract_attached_report_id(user_text)
            try:
                rid = int(report_id) if report_id is not None else None
            except (TypeError, ValueError):
                rid = None
            if rid is None:
                return ToolResult(
                    name,
                    "Chưa chọn báo cáo. Dùng list_health_reports hoặc đính kèm [[report:id]].",
                    frozenset(),
                    {"kind": "health_report", "found": False},
                    True,
                    True,
                )
            row = session.get(ReportFile, rid)
            if row is None or row.project_key != project_key or row.hidden_at is not None:
                return ToolResult(
                    name,
                    f"Không thấy báo cáo #{rid} trong project {project_key}.",
                    frozenset(),
                    {"kind": "health_report", "found": False, "report_id": rid},
                    True,
                    True,
                )
            meta = _load_report_meta(settings, row)
            keys = frozenset(str(k).upper() for k in meta.get("allowed_keys") or [])
            overview = meta.get("overview") or {}
            facts_parts = [
                f"Báo cáo #{row.id} · {row.report_date} · {row.slot_hhmm}",
                f"Open {overview.get('open_count', '?')} · Risky {overview.get('risky_count', '?')} · "
                f"Blocked {overview.get('blocked_count', '?')}",
                f"allowed_counts={json.dumps(meta.get('allowed_counts') or {}, ensure_ascii=False)}",
            ]
            # Compact facts sections for Q&A grounding
            facts_blob = meta.get("facts") or {}
            for section in ("risk", "bottleneck", "resource", "actions"):
                if section in facts_blob:
                    facts_parts.append(f"{section}: {json.dumps(facts_blob[section], ensure_ascii=False)[:800]}")
            if meta.get("markdown_excerpt") and not facts_blob:
                facts_parts.append(str(meta["markdown_excerpt"])[:1500])
            return ToolResult(
                name,
                "\n".join(facts_parts),
                keys,
                {
                    "kind": "health_report",
                    "found": True,
                    "report_id": row.id,
                    "report_date": row.report_date,
                    "slot_hhmm": row.slot_hhmm,
                    "allowed_counts": meta.get("allowed_counts") or {},
                    "overview": overview,
                },
                False,
                True,
            )
        if name == "generate_health_report":
            if user_id is None:
                return ToolResult(name, "Thiếu user_id.", frozenset(), {}, True, False, "missing user_id")
            user = session.get(User, user_id)
            if user is None:
                return ToolResult(name, "User không tồn tại.", frozenset(), {}, True, False, "no user")
            role = get_user_project_role(session, user, project_key)
            if not (user.is_admin or role == "pm"):
                return ToolResult(
                    name,
                    "Chỉ PM/Admin được tạo báo cáo. Viewer chỉ đọc báo cáo có sẵn.",
                    frozenset(),
                    {"kind": "health_generate", "forbidden": True},
                    True,
                    True,
                )
            local = now.astimezone(ZoneInfo(settings.tz))
            local_day = local.date().isoformat()
            slot_label = f"od-{local:%H%M%S}"
            dedup = report_dedup_key(user_id, project_key, slot_label, local_day)
            message = persist_health_report(
                session,
                settings,
                user_id=user_id,
                project=project_key,
                now=now,
                hhmm=slot_label,
                local_day=local_day,
                dedup=dedup,
            )
            if message is None:
                return ToolResult(
                    name,
                    "Không tạo được (dedup). Thử list_health_reports và mở bản hiện có.",
                    frozenset(),
                    {"kind": "health_generate", "ok": False},
                    True,
                    True,
                )
            row = session.scalar(select(ReportFile).where(ReportFile.message_id == message.id))
            rid = row.id if row else None
            facts = message.body
            if rid:
                facts = f"{facts}\nMở viewer: [[report:{rid}]]"
            return ToolResult(
                name,
                facts,
                frozenset(),
                {
                    "kind": "health_generate",
                    "ok": True,
                    "report_id": rid,
                    "message_id": message.id,
                    "report_date": local_day,
                    "slot_hhmm": slot_label,
                },
                True,
                True,
            )
    except Exception as exc:  # noqa: BLE001 — tool failures stay in agent context
        return ToolResult(name, "", frozenset(), {}, True, False, str(exc))
    return ToolResult(name, "", frozenset(), {}, True, False, f"unhandled tool: {name}")


def render_facts_from_tool_results(results: list[ToolResult]) -> str:
    """Python-rendered facts only — never LLM prose for board numbers."""
    allowed_names = BOARD_TOOLS | REPORT_TOOLS
    parts = [r.facts.strip() for r in results if r.ok and r.facts.strip() and r.name in allowed_names]
    return "\n\n".join(parts)


def union_allowed_keys(results: list[ToolResult]) -> set[str]:
    keys: set[str] = set()
    for result in results:
        if result.ok:
            keys |= {k.upper() for k in result.allowed_keys}
    return keys


def board_tool_succeeded(results: list[ToolResult]) -> bool:
    return any(r.ok and r.name in (BOARD_TOOLS | REPORT_TOOLS) for r in results)
