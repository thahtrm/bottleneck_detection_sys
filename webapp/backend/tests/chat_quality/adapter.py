"""Answer adapter: chat_tools / agent path (not HTTP answer_facts short-circuit)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from erw.settings import Settings

OUT_OF_SCOPE = "Chưa có trong hệ thống."

TOOL_TO_KIND = {
    "lookup_sprint": "sprint",
    "lookup_blocked": "blocked",
    "lookup_risky": "risky",
    "lookup_assignee_load": "assignee",
    "lookup_due": "due",
    "lookup_overdue": "overdue",
    "lookup_important": "important",
    "lookup_open": "open",
    "lookup_issue": "issue",
    "get_digest_snapshot": "digest",
}


@dataclass(frozen=True)
class EvalAnswer:
    """Normalized reply for scoring (facts-only; recommendation ignored)."""

    kind: str | None
    tool: str | None
    facts: str
    allowed_keys: frozenset[str]
    payload: dict[str, Any]
    out_of_scope: bool
    source: str  # "chat_agent" | "chat_tools" | "chat_lookup" | "out_of_scope"
    skip_recommendation: bool = False


def _facts_only(body: str) -> str:
    """Agent may append recommendation after a blank line; score the facts block only."""
    parts = body.split("\n\n", 1)
    return parts[0].strip()


def _from_tool_result(result: Any, *, source: str) -> EvalAnswer:
    payload = dict(getattr(result, "payload", None) or {})
    kind = payload.get("kind") if isinstance(payload.get("kind"), str) else TOOL_TO_KIND.get(result.name)
    return EvalAnswer(
        kind=kind,
        tool=str(result.name),
        facts=str(result.facts or ""),
        allowed_keys=frozenset(str(k).upper() for k in (result.allowed_keys or ())),
        payload=payload,
        out_of_scope=False,
        source=source,
        skip_recommendation=bool(getattr(result, "skip_recommendation", False)),
    )


def _out_of_scope(source: str) -> EvalAnswer:
    return EvalAnswer(
        kind=None,
        tool=None,
        facts=OUT_OF_SCOPE,
        allowed_keys=frozenset(),
        payload={},
        out_of_scope=True,
        source=source,
        skip_recommendation=True,
    )


def _answer_via_chat_tools(
    session: Session,
    project: str,
    text: str,
    now: datetime,
    settings: Settings,
) -> EvalAnswer | None:
    try:
        from erw.pipeline.chat_tools import run_tool, tool_hint
    except ImportError:
        return None

    hint = tool_hint(text, project)
    if hint is None:
        # Same contract as agent when no board tool applies and RAG empty.
        return _out_of_scope("chat_tools")

    result = run_tool(
        session,
        hint,
        {"text": text},
        project,
        now,
        settings,
        user_text=text,
    )
    if not result.ok:
        return EvalAnswer(
            kind=TOOL_TO_KIND.get(hint),
            tool=hint,
            facts=result.error or OUT_OF_SCOPE,
            allowed_keys=frozenset(),
            payload=dict(result.payload or {}),
            out_of_scope=True,
            source="chat_tools",
            skip_recommendation=True,
        )
    return _from_tool_result(result, source="chat_tools")


def _ensure_eval_user(session: Session, project: str, now: datetime) -> int:
    from sqlalchemy import select

    from erw.models import Project, ProjectMember, User

    user = session.scalars(select(User).where(User.email == "chat-quality@example.com")).first()
    if user is None:
        user = User(
            email="chat-quality@example.com",
            name="Chat Quality",
            password_hash="x",
            is_admin=False,
            created_at=now,
        )
        session.add(user)
        session.flush()
    if session.get(Project, project) is None:
        session.add(Project(key=project, name=project))
        session.flush()
    member = session.scalars(
        select(ProjectMember).where(ProjectMember.project_key == project, ProjectMember.user_id == user.id)
    ).first()
    if member is None:
        session.add(ProjectMember(project_key=project, user_id=user.id, role="pm"))
        session.flush()
    return int(user.id)


def _answer_via_agent(
    session: Session,
    project: str,
    text: str,
    now: datetime,
    settings: Settings,
) -> EvalAnswer | None:
    """Exercise chat_agent turn (ollama off → phrase hint → run_tool), score facts only."""
    try:
        from erw.pipeline.chat_agent import OUT_OF_SCOPE as AGENT_OOS
        from erw.pipeline.chat_agent import run_agent_turn
        from erw.pipeline.chat_tools import tool_hint
        from erw.models import ChatMessage
    except ImportError:
        return None

    # Deterministic: no LLM decisions / no recommend network.
    agent_settings = settings.model_copy(update={"ollama_url": ""})
    user_id = _ensure_eval_user(session, project, now)
    user_row = ChatMessage(
        user_id=user_id,
        project_key=project,
        kind="user",
        body=text,
        recommendation_status="skipped",
        created_at=now,
    )
    assistant = ChatMessage(
        user_id=user_id,
        project_key=project,
        kind="assistant",
        body="",
        recommendation_status="pending",
        created_at=now,
    )
    session.add_all([user_row, assistant])
    session.flush()

    run_agent_turn(
        session,
        message_id=assistant.id,
        user_id=user_id,
        project_key=project,
        text=text,
        settings=agent_settings,
        now=now,
    )
    session.refresh(assistant)
    body = (assistant.body or "").strip()
    hint = tool_hint(text, project)
    facts = _facts_only(body)

    if facts == AGENT_OOS or not facts:
        return EvalAnswer(
            kind=None,
            tool=hint,
            facts=AGENT_OOS,
            allowed_keys=frozenset(),
            payload={},
            out_of_scope=True,
            source="chat_agent",
            skip_recommendation=True,
        )

    # Re-run the same board tool the agent would have used for payload/keys discipline.
    from erw.pipeline.chat_tools import run_tool

    if hint is None:
        return EvalAnswer(
            kind=None,
            tool=None,
            facts=facts,
            allowed_keys=frozenset(),
            payload={},
            out_of_scope=False,
            source="chat_agent",
            skip_recommendation=True,
        )

    result = run_tool(session, hint, {"text": text}, project, now, settings, user_text=text)
    answer = _from_tool_result(result, source="chat_agent")
    # Prefer agent-rendered facts block (must match tool facts for board tools).
    return EvalAnswer(
        kind=answer.kind,
        tool=answer.tool,
        facts=result.facts if result.ok else facts,
        allowed_keys=answer.allowed_keys,
        payload=answer.payload,
        out_of_scope=False,
        source="chat_agent",
        skip_recommendation=answer.skip_recommendation,
    )


def _answer_via_lookup_fallback(
    session: Session,
    project: str,
    text: str,
    now: datetime,
    settings: Settings,
) -> EvalAnswer:
    from erw.pipeline.chat_lookup import answer_facts

    kind_to_tool = {kind: tool for tool, kind in TOOL_TO_KIND.items() if tool.startswith("lookup_")}
    answer = answer_facts(session, project, text, now, settings)
    if answer is None:
        return _out_of_scope("out_of_scope")
    return EvalAnswer(
        kind=answer.kind,
        tool=kind_to_tool.get(answer.kind),
        facts=answer.facts,
        allowed_keys=frozenset(answer.allowed_keys),
        payload=dict(answer.payload or {}),
        out_of_scope=False,
        source="chat_lookup",
        skip_recommendation=answer.skip_recommendation,
    )


def get_answer(
    session: Session,
    project: str,
    text: str,
    now: datetime,
    settings: Settings,
    *,
    prefer_agent: bool = True,
) -> EvalAnswer:
    if prefer_agent:
        via_agent = _answer_via_agent(session, project, text, now, settings)
        if via_agent is not None:
            return via_agent

    via_tools = _answer_via_chat_tools(session, project, text, now, settings)
    if via_tools is not None:
        return via_tools

    return _answer_via_lookup_fallback(session, project, text, now, settings)
