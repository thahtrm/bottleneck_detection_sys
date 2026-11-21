from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from erw.db import SessionLocal, utcnow
from erw.integrations.llm import call_ollama_chat, submit_to_llm_executor
from erw.models import ChatAgentRun, ChatMessage, Issue, RiskState
from erw.pipeline.chat_memory import (
    format_memories_for_prompt,
    load_session_messages,
    load_user_project_memory,
    write_episode,
)
from erw.pipeline.chat_rag import format_rag_for_prompt, retrieve
from erw.pipeline.chat_recommend import (
    FAILED_RECOMMENDATION,
    recommendation_from_stored,
    write_recommendation,
)
from erw.pipeline.chat_tools import (
    BOARD_TOOLS,
    FOUNDATION_TOOLS,
    REPORT_TOOLS,
    ToolResult,
    board_tool_succeeded,
    catalog_for_pm,
    extract_attached_report_id,
    render_facts_from_tool_results,
    run_tool,
    tool_hint,
    union_allowed_keys,
)
from erw.settings import Settings

log = logging.getLogger(__name__)

OUT_OF_SCOPE = "Chưa có trong hệ thống."
NO_BOARD_DATA = "Chưa lấy được dữ liệu bảng."


def _agent_system(tool_hint_name: str | None) -> str:
    catalog = json.dumps(catalog_for_pm(), ensure_ascii=False)
    hint = f"Gợi ý tool (không bắt buộc): {tool_hint_name}." if tool_hint_name else "Không có gợi ý phrase."
    return (
        "Bạn là trợ lý PM Early Risk cho đúng một project. "
        "Muốn số liệu board/sprint/risk/issue/báo cáo sức khỏe → phải gọi tool. Cấm bịa mã issue, count, deadline.\n"
        "Hỏi theo báo cáo đã đính kèm → get_health_report. "
        "Tạo/cập nhật báo cáo sức khỏe → generate_health_report (artifact mới).\n"
        "RAG chỉ là hướng dẫn quy trình; nếu xung đột với tool → tin tool.\n"
        "Không hứa đã ghi Jira/Slack. Không đổi lịch báo cáo.\n"
        "Ngoài phạm vi → sẽ trả lời đúng: Chưa có trong hệ thống.\n"
        f"{hint}\n"
        f"Tools được phép: {catalog}\n"
        "Mỗi bước trả đúng một JSON object, không markdown:\n"
        '{"tool":"<name>","args":{...}} hoặc {"done":true}\n'
        "Khi đã đủ dữ liệu board/report (hoặc câu chỉ hỏi quy trình), trả {\"done\":true}."
    )


def _decide_step(
    prompt: str,
    system: str,
    settings: Settings,
    client: httpx.Client | None,
) -> dict[str, Any] | None:
    if not settings.ollama_url:
        return None
    try:
        return call_ollama_chat(prompt, system, settings.llm_model, settings.ollama_url, client)
    except Exception:
        log.warning("agent step LLM failed", exc_info=True)
        return None


def _parse_decision(raw: dict[str, Any] | None) -> tuple[str | None, dict[str, Any], bool]:
    """Return (tool_name, args, done)."""
    if not raw:
        return None, {}, False
    if raw.get("done") is True:
        return None, {}, True
    tool = raw.get("tool")
    if isinstance(tool, str) and tool.strip():
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        return tool.strip(), args, False
    return None, {}, True


def _with_recommendation(facts: str, recommendation: str) -> str:
    return f"{facts.rstrip()}\n\n{recommendation.strip()}"


def _issue_prompt(session: Session, issue_key: str | None) -> str | None:
    if not issue_key:
        return None
    issue = session.get(Issue, issue_key)
    if issue is None:
        return None
    risk = session.get(RiskState, issue.key)
    factors = []
    if risk is not None and risk.factors:
        for factor in risk.factors:
            if isinstance(factor, dict):
                label = factor.get("label") or factor.get("name") or factor.get("id")
                if label:
                    factors.append(str(label))
            elif isinstance(factor, str):
                factors.append(factor)
    return json.dumps(
        {
            "issue_key": issue.key,
            "summary": issue.summary,
            "level": risk.level if risk else None,
            "factors": factors,
        },
        ensure_ascii=False,
    )


def _compose_recommendation(
    session: Session,
    results: list[ToolResult],
    allowed_keys: set[str],
    settings: Settings,
    client: httpx.Client | None,
) -> tuple[str, str]:
    if any(r.ok and r.skip_recommendation for r in results if r.name in BOARD_TOOLS | REPORT_TOOLS):
        return "", "skipped"
    for result in results:
        if result.name != "get_issue_suggestion" or not result.ok:
            continue
        output = result.payload.get("output")
        if isinstance(output, dict):
            text, status = recommendation_from_stored(output, allowed_keys)
            return text, status
    issue_key = None
    for result in results:
        if result.name == "lookup_issue" and result.ok:
            issue_key = result.payload.get("key")
            break
    user_prompt = _issue_prompt(session, issue_key) if issue_key else None
    if user_prompt is None:
        payload_bits = [r.payload for r in results if r.ok and r.name in BOARD_TOOLS | REPORT_TOOLS]
        user_prompt = json.dumps(payload_bits, ensure_ascii=False) if payload_bits else ""
    if not user_prompt:
        return "", "skipped"
    text, status = write_recommendation(user_prompt, allowed_keys, settings, client)
    return text, status


def run_agent_turn(
    session: Session,
    *,
    message_id: int,
    user_id: int,
    project_key: str,
    text: str,
    settings: Settings,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> None:
    message = session.get(ChatMessage, message_id)
    if message is None or message.recommendation_status != "pending":
        return
    moment = now or utcnow()
    run = ChatAgentRun(
        message_id=message_id,
        status="running",
        steps_json=[],
        error=None,
        created_at=moment,
    )
    session.add(run)
    session.flush()

    hint = tool_hint(text, project_key)
    attached_report_id = extract_attached_report_id(text)
    memories = load_user_project_memory(session, user_id, project_key)
    session_msgs = load_session_messages(session, user_id, project_key, limit=settings.agent_session_limit)
    rag_chunks = retrieve(session, text, project_key, settings, k=4)
    system = _agent_system(hint)
    context_parts = [
        format_memories_for_prompt(memories),
        format_rag_for_prompt(rag_chunks),
        "Hội thoại gần:",
    ]
    for row in session_msgs:
        if row.id == message_id:
            continue
        context_parts.append(f"{row.kind}: {row.body[:500]}")
    context_parts.append(f"user: {text}")
    context_blob = "\n".join(p for p in context_parts if p)

    results: list[ToolResult] = []
    steps: list[dict[str, Any]] = []
    used_tools: set[str] = set()
    max_steps = max(1, int(settings.agent_max_steps))
    done = False

    for step_i in range(max_steps):
        if done:
            break
        decision_raw = _decide_step(
            f"{context_blob}\n\nBước {step_i + 1}. Chọn tool hoặc done. Đã gọi: {sorted(used_tools)}",
            system,
            settings,
            client,
        )
        tool_name, args, is_done = _parse_decision(decision_raw)
        if is_done and tool_name is None:
            steps.append({"step": step_i + 1, "decision": "done", "raw": decision_raw})
            done = True
            break
        if tool_name is None:
            # LLM failed or malformed — deterministic phrase hint once
            if hint and hint not in used_tools:
                tool_name = hint
                args = {}
                if hint == "get_health_report" and attached_report_id is not None:
                    args = {"report_id": attached_report_id}
                steps.append({"step": step_i + 1, "decision": "hint_fallback", "tool": tool_name})
            else:
                steps.append({"step": step_i + 1, "decision": "stop", "raw": decision_raw})
                done = True
                break
        if tool_name not in FOUNDATION_TOOLS:
            steps.append({"step": step_i + 1, "decision": "reject", "tool": tool_name})
            context_blob += f"\ntool_error: {tool_name} không được phép."
            continue
        if tool_name in used_tools and tool_name != "lookup_issue":
            steps.append({"step": step_i + 1, "decision": "skip_dup", "tool": tool_name})
            done = True
            break
        if tool_name == "get_health_report" and not args.get("report_id") and attached_report_id is not None:
            args = {**args, "report_id": attached_report_id}
        result = run_tool(
            session,
            tool_name,
            args,
            project_key,
            moment,
            settings,
            user_text=text,
            user_id=user_id,
        )
        results.append(result)
        used_tools.add(tool_name)
        steps.append(
            {
                "step": step_i + 1,
                "tool": tool_name,
                "ok": result.ok,
                "error": result.error,
                "payload_kind": result.payload.get("kind"),
            }
        )
        context_blob += f"\ntool:{tool_name} ok={result.ok} facts={result.facts[:400]}"
        if (
            tool_name == "lookup_issue"
            and result.ok
            and result.payload.get("found") is not False
            and result.payload.get("key")
        ):
            sug = run_tool(
                session,
                "get_issue_suggestion",
                {"issue_key": result.payload["key"]},
                project_key,
                moment,
                settings,
                user_text=text,
            )
            results.append(sug)
            used_tools.add("get_issue_suggestion")
            steps.append({"step": step_i + 1, "tool": "get_issue_suggestion", "ok": sug.ok})
        if hint and tool_name == hint:
            # After fulfilling the phrase hint, stop unless model continues next loop
            done = True

    # If LLM never ran a tool but phrase maps to one, force that board tool
    if not board_tool_succeeded(results) and hint and hint in (BOARD_TOOLS | REPORT_TOOLS):
        ensure_args: dict[str, Any] = {}
        if hint == "get_health_report" and attached_report_id is not None:
            ensure_args = {"report_id": attached_report_id}
        result = run_tool(
            session,
            hint,
            ensure_args,
            project_key,
            moment,
            settings,
            user_text=text,
            user_id=user_id,
        )
        results.append(result)
        steps.append({"step": "ensure", "tool": hint, "ok": result.ok})
        if (
            hint == "lookup_issue"
            and result.ok
            and result.payload.get("found") is not False
            and result.payload.get("key")
        ):
            sug = run_tool(
                session,
                "get_issue_suggestion",
                {"issue_key": result.payload["key"]},
                project_key,
                moment,
                settings,
                user_text=text,
            )
            results.append(sug)
            steps.append({"step": "ensure", "tool": "get_issue_suggestion", "ok": sug.ok})

    needs_board = hint is not None and hint in (BOARD_TOOLS | REPORT_TOOLS)
    facts = render_facts_from_tool_results(results)
    allowed = union_allowed_keys(results)
    rag_only = bool(rag_chunks) and not needs_board and not board_tool_succeeded(results)

    if needs_board and not board_tool_succeeded(results):
        body = NO_BOARD_DATA
        status = "skipped"
    elif not facts and not rag_only and not board_tool_succeeded(results):
        body = OUT_OF_SCOPE
        status = "skipped"
    elif rag_only and not facts:
        cites = "\n".join(f"[source: {c.source_uri}] {c.text.strip()[:400]}" for c in rag_chunks[:3])
        body = cites or OUT_OF_SCOPE
        status = "skipped"
    else:
        if not facts and needs_board:
            body = NO_BOARD_DATA
            status = "skipped"
        else:
            body = facts or OUT_OF_SCOPE
            if any(r.ok and r.skip_recommendation for r in results if r.name in BOARD_TOOLS | REPORT_TOOLS):
                status = "skipped"
            else:
                rec_text, rec_status = _compose_recommendation(session, results, allowed, settings, client)
                if rec_status == "ready" and rec_text:
                    body = _with_recommendation(body, rec_text)
                    status = "ready"
                elif rec_status == "failed":
                    body = _with_recommendation(body, FAILED_RECOMMENDATION)
                    status = "failed"
                else:
                    status = "skipped"

    message.body = body
    message.recommendation_status = status
    run.status = "ready" if status in {"ready", "skipped", "failed"} else "failed"
    run.steps_json = steps
    session.flush()

    # Episodes are conclusions — never store out-of-scope / empty board placeholders.
    episode_text = (facts or "").strip()
    if not episode_text and rag_only and body != OUT_OF_SCOPE:
        episode_text = body.strip()[:400]
    if episode_text and body not in {OUT_OF_SCOPE, NO_BOARD_DATA}:
        write_episode(
            session,
            user_id,
            project_key,
            episode_text[:400],
            related_keys=sorted(allowed)[:10],
            now=moment,
        )
        session.flush()


def enqueue_agent_turn(
    *,
    message_id: int,
    user_id: int,
    project_key: str,
    text: str,
    settings: Settings,
    engine,
) -> None:
    def work() -> None:
        try:
            with SessionLocal(bind=engine) as session:
                run_agent_turn(
                    session,
                    message_id=message_id,
                    user_id=user_id,
                    project_key=project_key,
                    text=text,
                    settings=settings,
                )
                session.commit()
        except Exception:
            log.exception("agent turn failed for message %s", message_id)
            try:
                with SessionLocal(bind=engine) as session:
                    message = session.get(ChatMessage, message_id)
                    if message is not None and message.recommendation_status == "pending":
                        message.body = OUT_OF_SCOPE
                        message.recommendation_status = "failed"
                        session.commit()
            except Exception:
                log.exception("failed to mark agent message %s failed", message_id)

    submit_to_llm_executor(work)
