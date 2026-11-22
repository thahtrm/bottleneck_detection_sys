"""Option B: constrained LLM narrate of chat digests from structured tool JSON.

Facts stay grounded: numbers/keys must ⊆ payload allowlists. On LLM/validate
failure, callers keep Option A polished template strings from the tools.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from erw.integrations.llm import call_ollama_chat_text
from erw.pipeline.chat_lookup import keys_in_text
from erw.pipeline.chat_tools import BOARD_TOOLS, ToolResult
from erw.settings import Settings

log = logging.getLogger(__name__)

# List / digest payloads that benefit from a short VI narrate pass.
NARRATE_KINDS = frozenset(
    {
        "assignee",
        "blocked",
        "risky",
        "due",
        "overdue",
        "important",
        "open",
        "digest",
    }
)

_NUMBER_RE = re.compile(r"\d+")
_KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]+-\d+)\b")


def narrate_payloads(results: list[ToolResult]) -> list[dict[str, Any]]:
    """Board tool payloads eligible for constrained narration."""
    out: list[dict[str, Any]] = []
    for result in results:
        if not result.ok or result.name not in BOARD_TOOLS:
            continue
        payload = result.payload
        if not isinstance(payload, dict):
            continue
        kind = payload.get("kind")
        if kind in NARRATE_KINDS:
            # Drop pre-rendered template lines from the LLM view (structured fields only).
            out.append(_payload_for_llm(payload))
    return out


def _payload_for_llm(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    issues = cleaned.get("issues")
    if isinstance(issues, list):
        slim: list[dict[str, Any]] = []
        for item in issues:
            if not isinstance(item, dict):
                continue
            row = {k: v for k, v in item.items() if k != "line"}
            slim.append(row)
        cleaned["issues"] = slim
    return cleaned


def payload_allowlists(payloads: list[dict[str, Any]]) -> tuple[frozenset[str], frozenset[int]]:
    """Issue keys + integers that appear in structured tool JSON (no invented counts)."""
    blob = json.dumps(payloads, ensure_ascii=False)
    keys = frozenset(m.group(1).upper() for m in _KEY_RE.finditer(blob))
    for payload in payloads:
        for result_key in ("key",):
            val = payload.get(result_key)
            if isinstance(val, str) and val.strip():
                keys = keys | frozenset({val.strip().upper()})
        for issue in payload.get("issues") or []:
            if isinstance(issue, dict) and isinstance(issue.get("key"), str):
                keys = keys | frozenset({issue["key"].upper()})
        for item in payload.get("top_risky") or []:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                keys = keys | frozenset({item["key"].upper()})
    nums = frozenset(int(m.group(0)) for m in _NUMBER_RE.finditer(blob))
    return keys, nums


def validate_chat_narration(
    text: str,
    allowed_keys: frozenset[str],
    allowed_numbers: frozenset[int],
) -> str | None:
    """
    Accept only when every issue key and every integer token ⊆ allowlists
    (same spirit as validate_recommendation — reject drift, do not soft-rewrite).
    """
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    # Unwrap accidental fences / JSON {"text": "..."} wrappers.
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            raw = json.loads(cleaned)
            if isinstance(raw, dict) and isinstance(raw.get("text"), str):
                cleaned = raw["text"].strip()
        except json.JSONDecodeError:
            pass
    if not cleaned:
        return None
    mentioned_keys = keys_in_text(cleaned)
    if not mentioned_keys <= {k.upper() for k in allowed_keys}:
        return None
    mentioned_nums = {int(m.group(0)) for m in _NUMBER_RE.finditer(cleaned)}
    if not mentioned_nums <= set(allowed_numbers):
        return None
    return cleaned


def _system_prompt() -> str:
    return (
        "Bạn viết câu trả lời ngắn cho PM bằng tiếng Việt tự nhiên (2–5 câu hoặc vài dòng). "
        "Chỉ dùng dữ liệu trong JSON người dùng đưa. "
        "CẤM bịa mã issue, số lượng, hạn, hoặc tên người không có trong JSON. "
        "Copy đúng các số count trong JSON. "
        "Không nhắc lại tên người phụ trách trên từng dòng nếu header đã nêu. "
        "Không dùng từ tiếng Anh assignee / Digest / block — dùng phụ trách / bị chặn. "
        "Trả về plain text tiếng Việt thôi — không JSON, không markdown fence."
    )


def narrate_chat_facts(
    results: list[ToolResult],
    settings: Settings,
    client: httpx.Client | None = None,
) -> str | None:
    """
    Optional Ollama narrate from structured tool payloads.
    Returns validated prose, or None → caller keeps Option A templates.
    """
    payloads = narrate_payloads(results)
    if not payloads:
        return None
    if not settings.ollama_url:
        return None
    allowed_keys, allowed_numbers = payload_allowlists(payloads)
    prompt = (
        "Viết câu trả lời tiếng Việt từ JSON sau. Không thêm key/số ngoài allowlist.\n\n"
        f"## PAYLOAD_JSON\n{json.dumps(payloads, ensure_ascii=False)}\n\n"
        f"## ALLOWED_KEYS\n{json.dumps(sorted(allowed_keys), ensure_ascii=False)}\n\n"
        f"## ALLOWED_COUNTS\n{json.dumps(sorted(allowed_numbers), ensure_ascii=False)}\n"
    )
    try:
        raw = call_ollama_chat_text(
            prompt,
            _system_prompt(),
            settings.llm_model,
            settings.ollama_url,
            client,
            timeout=60.0,
        )
    except Exception:
        log.warning("chat narrate LLM failed", exc_info=True)
        return None
    validated = validate_chat_narration(raw if isinstance(raw, str) else "", allowed_keys, allowed_numbers)
    if validated is None:
        log.warning("chat narrate failed allowlist validate; using template fallback")
    return validated
