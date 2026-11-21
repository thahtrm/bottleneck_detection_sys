from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from erw.integrations.llm import get_cached_suggestion
from erw.models import Issue
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

FOUNDATION_TOOLS = BOARD_TOOLS | frozenset({"get_issue_suggestion"})

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
    """Tool schema for the agent prompt (read-only; no schedule/Jira writes)."""
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
    ]


def tool_hint(text: str, project_key: str) -> str | None:
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


def run_tool(
    session: Session,
    name: str,
    args: dict[str, Any] | None,
    project_key: str,
    now: datetime,
    settings: Settings,
    *,
    user_text: str = "",
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
            top = [{"key": item.key, "level": item.level_name} for item in snap.top_risky]
            keys = frozenset(item.key for item in snap.top_risky)
            facts = (
                f"Digest: {snap.risky_count} nguy cơ trễ, {snap.raised_24h} tăng bậc/24h, "
                f"{snap.blocked_count} bị block."
            )
            if snap.sprint_line:
                facts = f"{facts}\n{snap.sprint_line}"
            return ToolResult(
                name,
                facts,
                keys,
                {
                    "kind": "digest",
                    "risky_count": snap.risky_count,
                    "raised_24h": snap.raised_24h,
                    "blocked_count": snap.blocked_count,
                    "sprint_line": snap.sprint_line,
                    "top_risky": top,
                },
                False,
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
    except Exception as exc:  # noqa: BLE001 — tool failures stay in agent context
        return ToolResult(name, "", frozenset(), {}, True, False, str(exc))
    return ToolResult(name, "", frozenset(), {}, True, False, f"unhandled tool: {name}")


def render_facts_from_tool_results(results: list[ToolResult]) -> str:
    """Python-rendered facts only — never LLM prose for board numbers."""
    parts = [r.facts.strip() for r in results if r.ok and r.facts.strip() and r.name in BOARD_TOOLS]
    return "\n\n".join(parts)


def union_allowed_keys(results: list[ToolResult]) -> set[str]:
    keys: set[str] = set()
    for result in results:
        if result.ok:
            keys |= {k.upper() for k in result.allowed_keys}
    return keys


def board_tool_succeeded(results: list[ToolResult]) -> bool:
    return any(r.ok and r.name in BOARD_TOOLS for r in results)
