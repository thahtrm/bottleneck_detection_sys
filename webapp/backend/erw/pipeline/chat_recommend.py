from __future__ import annotations

import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from erw.db import SessionLocal
from erw.integrations.llm import (
    ALLOWED_ACTION_TYPES,
    ActionItem,
    call_ollama_chat,
    submit_to_llm_executor,
)
from erw.models import ChatMessage
from erw.pipeline.chat_lookup import keys_in_text
from erw.settings import Settings

log = logging.getLogger(__name__)

FAILED_RECOMMENDATION = "Chưa tạo được đề xuất bám dữ liệu."
RecommendationStatus = Literal["ready", "failed"]


class ChatRecommendation(BaseModel):
    text: str
    actions: list[ActionItem] = Field(default_factory=list)


def _system_prompt() -> str:
    allowed = ", ".join(sorted(ALLOWED_ACTION_TYPES))
    return (
        "Bạn viết đoạn đề xuất ngắn cho PM, bằng tiếng Việt. "
        "Chỉ dùng issue có trong dữ liệu người dùng đưa. Không bịa issue, factor, hoặc hành động khác.\n"
        "Trả về một JSON object duy nhất, không markdown:\n"
        '{"text": "1 đến 3 câu", "actions": [{"action_type": "...", "target": "ISSUE hoặc null", '
        '"value": "giá trị hoặc null", "reason": "lý do"}]}\n'
        f"action_type chỉ được thuộc: {allowed}. Tối đa 3 action."
    )


def validate_recommendation(text: str, actions: list[ActionItem], allowed_keys: set[str]) -> bool:
    if len(actions) > 3:
        return False
    allowed = {key.upper() for key in allowed_keys}
    mentioned = set(keys_in_text(text))
    for action in actions:
        if action.action_type not in ALLOWED_ACTION_TYPES:
            return False
        for part in (action.target, action.value, action.reason):
            if part:
                mentioned |= keys_in_text(part)
    return mentioned <= allowed


def write_recommendation(
    user_prompt: str,
    allowed_keys: set[str],
    settings: Settings,
    client: httpx.Client | None = None,
) -> tuple[str, RecommendationStatus]:
    if not settings.ollama_url:
        return FAILED_RECOMMENDATION, "failed"
    allow_line = ", ".join(sorted(key.upper() for key in allowed_keys)) or "(không có mã issue)"
    prompt = f"{user_prompt}\nChỉ được nhắc các mã: {allow_line}"
    try:
        raw = call_ollama_chat(
            prompt,
            _system_prompt(),
            settings.llm_model,
            settings.ollama_url,
            client,
        )
        parsed = ChatRecommendation.model_validate(raw)
    except Exception:
        log.warning("chat recommendation failed", exc_info=True)
        return FAILED_RECOMMENDATION, "failed"
    if not parsed.text.strip() or not validate_recommendation(parsed.text, parsed.actions, allowed_keys):
        return FAILED_RECOMMENDATION, "failed"
    return parsed.text.strip(), "ready"


def recommendation_from_stored(output: dict, allowed_keys: set[str]) -> tuple[str, RecommendationStatus]:
    summary = str(output.get("summary") or "").strip()
    raw_actions = output.get("actions") or []
    if not isinstance(raw_actions, list):
        return FAILED_RECOMMENDATION, "failed"
    actions: list[ActionItem] = []
    for item in raw_actions[:3]:
        try:
            actions.append(ActionItem.model_validate(item))
        except ValidationError:
            return FAILED_RECOMMENDATION, "failed"
    lines = [summary] if summary else []
    for action in actions:
        target = f"{action.target}: " if action.target else ""
        lines.append(f"{target}{action.action_type} — {action.reason}")
    text = "\n".join(line for line in lines if line).strip()
    if not text or not validate_recommendation(text, actions, allowed_keys):
        return FAILED_RECOMMENDATION, "failed"
    return text, "ready"


def apply_recommendation(session: Session, message_id: int, text: str, status: str) -> None:
    message = session.get(ChatMessage, message_id)
    if message is None or message.recommendation_status != "pending":
        return
    message.body = f"{message.body.rstrip()}\n\n{text.strip()}"
    message.recommendation_status = status
    session.flush()


def enqueue_message_recommendation(
    message_id: int,
    user_prompt: str,
    allowed_keys: set[str],
    settings: Settings,
    engine,
) -> None:
    def work() -> None:
        text, status = write_recommendation(user_prompt, set(allowed_keys), settings)
        try:
            with SessionLocal(bind=engine) as session:
                apply_recommendation(session, message_id, text, status)
                session.commit()
        except Exception:
            log.exception("failed to store chat recommendation for %s", message_id)

    submit_to_llm_executor(work)
