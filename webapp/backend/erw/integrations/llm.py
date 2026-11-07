from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from erw.db import SessionLocal, make_engine, utcnow
from erw.models import Change, Issue, IssueSprint, Link, RiskState, Sprint, Suggestion
from erw.settings import Settings

log = logging.getLogger(__name__)

ALLOWED_ACTION_TYPES = {
    "adjust_deadline",
    "change_assignee",
    "change_status",
    "add_comment",
    "escalate_blocker",
}

_llm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="erw-llm")
_in_progress_keys: set[str] = set()
_lock = threading.Lock()
_engine: Any = None
_http_client: httpx.Client | None = None


def set_engine(engine: Any) -> None:
    """Configure a shared SQLAlchemy Engine for background worker tasks."""
    global _engine
    _engine = engine


def set_http_client(client: httpx.Client | None) -> None:
    """Configure a default HTTP client for Ollama calls (useful in testing)."""
    global _http_client
    _http_client = client


class ActionItem(BaseModel):
    action_type: str
    target: str | None = None
    value: str | None = None
    reason: str


class SuggestionOutput(BaseModel):
    summary: str
    explanation: str
    factors_cited: list[str] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)


def build_system_prompt() -> str:
    allowed_str = ", ".join(sorted(ALLOWED_ACTION_TYPES))
    return (
        "Bạn là chuyên gia quản trị dự án phần mềm Jira (Agile/Scrum PM). "
        "Nhiệm vụ của bạn là phân tích các rủi ro trễ hạn của công việc (issue) dựa trên thông tin "
        "về Issue, RiskState, và các yếu tố rủi ro (factors) đã được hệ thống ghi nhận.\n"
        "Hãy đưa ra giải thích nguyên nhân rủi ro và các đề xuất hành động cụ thể để giảm thiểu rủi ro.\n"
        "Tin nhắn người dùng có mô tả task, người phụ trách hiện tại, lịch sử tiến độ, sprint và các task liên quan.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. Giải thích bằng tiếng Việt tự nhiên, chuyên nghiệp; giữ nguyên các thuật ngữ Agile/kỹ thuật thông dụng "
        "(Sprint, Backlog, Blocker, Story Points, Due Date, Assignee, v.v.).\n"
        "2. Trong trường 'factors_cited', CHỈ ĐƯỢC trích dẫn các yếu tố rủi ro thực tế có trong danh sách factors "
        "được cung cấp. TUYỆT ĐỐI KHÔNG bịa đặt yếu tố rủi ro không có trong danh sách.\n"
        f"3. Trong mảng 'actions', mỗi hành động phải có 'action_type' thuộc danh sách cho phép sau: [{allowed_str}].\n"
        "4. Phản hồi CHỈ bao gồm một JSON object duy nhất, không kèm markdown fences hay văn bản thừa ngoài JSON, "
        "tuân thủ đúng JSON schema sau:\n"
        "{\n"
        '  "summary": "Tóm tắt ngắn gọn tình trạng rủi ro",\n'
        '  "explanation": "Giải thích chi tiết nguyên nhân rủi ro",\n'
        '  "factors_cited": ["tên_factor_1", "tên_factor_2"],\n'
        '  "actions": [\n'
        '    {\n'
        '      "action_type": "adjust_deadline | change_assignee | change_status | add_comment | escalate_blocker",\n'
        '      "target": "đối tượng tác động hoặc null",\n'
        '      "value": "giá trị mới hoặc null",\n'
        '      "reason": "lý do đề xuất"\n'
        '    }\n'
        '  ]\n'
        "}"
    )


def _collect_text(node: Any, parts: list[str]) -> None:
    if isinstance(node, dict):
        text = node.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
        for child in node.get("content") or []:
            _collect_text(child, parts)
    elif isinstance(node, list):
        for child in node:
            _collect_text(child, parts)


def _plain_text(value: Any, limit: int = 4000) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (dict, list)):
        parts: list[str] = []
        _collect_text(value, parts)
        text = "\n".join(parts).strip()
    else:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _issue_description(issue: Issue) -> str:
    raw = issue.raw if isinstance(issue.raw, dict) else {}
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    text = _plain_text(fields.get("description"))
    if text:
        return text
    return _plain_text(raw.get("description")) or "Không có mô tả"


def _assignee_line(name: str | None, account_id: str | None) -> str:
    if name and account_id:
        return f"{name} (accountId: {account_id})"
    if name:
        return name
    if account_id:
        return f"accountId: {account_id}"
    return "Chưa phân công"


def _factor_lines(risk_state: RiskState | None) -> list[str]:
    if risk_state is None or not isinstance(risk_state.factors, list):
        return []
    lines: list[str] = []
    for factor in risk_state.factors:
        if isinstance(factor, str):
            lines.append(factor)
            continue
        if not isinstance(factor, dict):
            continue
        factor_id = factor.get("id") or factor.get("name") or factor.get("label") or ""
        label = factor.get("label") or ""
        value = factor.get("value") or factor.get("detail") or ""
        bits = [str(part) for part in (factor_id, label, value) if part]
        if bits:
            lines.append(" | ".join(bits))
    return lines


def _when(value: datetime | None) -> str:
    if value is None:
        return "không rõ thời điểm"
    return value.isoformat()


def _related_line(issue_key: str, link: Link, other: Issue | None) -> str:
    other_key = link.target_key if link.source_key == issue_key else link.source_key
    if other is None:
        summary, status, owner = "không có trong hệ thống", "N/A", "Chưa phân công"
    else:
        summary = other.summary
        status = other.status or "N/A"
        owner = _assignee_line(other.assignee_name, other.assignee_id)
    direction = "inward" if link.direction in ("0", "inward") else "outward"
    return f"  - {other_key} | {summary} | {status} | phụ trách: {owner} | {link.type_std} | {direction}"


def build_user_prompt(
    session: Session,
    issue: Issue,
    risk_state: RiskState | None,
    actual_factors: list[str],
) -> str:
    factors_str = json.dumps(actual_factors, ensure_ascii=False) if actual_factors else "[]"
    deadline_info = "Không có"
    if risk_state and risk_state.deadline_at:
        deadline_info = f"{risk_state.deadline_at.isoformat()} ({risk_state.deadline_type or 'deadline'})"
    elif issue.duedate:
        deadline_info = str(issue.duedate)

    risk_level = risk_state.level if risk_state and risk_state.level else "LOW"
    is_blocked = "Có" if (risk_state and risk_state.blocked) else "Không"
    is_critical = "Có" if (risk_state and risk_state.is_critical) else "Không"

    changes = list(
        session.scalars(
            select(Change)
            .where(Change.issue_key == issue.key)
            .order_by(Change.at.desc(), Change.id.desc())
            .limit(20)
        ).all()
    )
    changes.reverse()
    if changes:
        progress = "\n".join(
            f"  - {_when(change.at)} | {change.field}: {change.from_str or change.from_val or 'trống'} → {change.to_str or change.to_val or 'trống'}"
            for change in changes
        )
    else:
        progress = "  Không có lịch sử thay đổi"

    links = list(
        session.scalars(select(Link).where(or_(Link.source_key == issue.key, Link.target_key == issue.key))).all()
    )
    other_keys = [link.target_key if link.source_key == issue.key else link.source_key for link in links]
    others = (
        {row.key: row for row in session.scalars(select(Issue).where(Issue.key.in_(other_keys))).all()}
        if other_keys
        else {}
    )
    if links:
        related = "\n".join(
            _related_line(
                issue.key,
                link,
                others.get(link.target_key if link.source_key == issue.key else link.source_key),
            )
            for link in links
        )
    else:
        related = "  Không có task liên kết"

    sprint_ids = list(session.scalars(select(IssueSprint.sprint_id).where(IssueSprint.issue_key == issue.key)).all())
    sprints = list(session.scalars(select(Sprint).where(Sprint.id.in_(sprint_ids))).all()) if sprint_ids else []
    mate_keys = (
        list(
            session.scalars(
                select(IssueSprint.issue_key)
                .where(IssueSprint.sprint_id.in_(sprint_ids), IssueSprint.issue_key != issue.key)
                .limit(40)
            ).all()
        )
        if sprint_ids
        else []
    )
    mates = list(session.scalars(select(Issue).where(Issue.key.in_(mate_keys))).all()) if mate_keys else []
    if sprints:
        sprint_head = "\n".join(
            f"  - {sprint.name or sprint.id} | trạng thái sprint: {sprint.state or 'N/A'} | {_when(sprint.start_at)} → {_when(sprint.end_at)}"
            for sprint in sprints
        )
    else:
        sprint_head = "  Không thuộc sprint nào"
    if mates:
        roster = "\n".join(
            f"  - {mate.key} | {mate.summary} | {mate.status or 'N/A'} | phụ trách: {_assignee_line(mate.assignee_name, mate.assignee_id)}"
            for mate in mates
        )
    else:
        roster = "  Không có task khác trong cùng sprint"

    factor_detail = _factor_lines(risk_state)
    factor_block = "\n".join(f"  - {line}" for line in factor_detail) if factor_detail else "  Không có"
    delay_value = risk_state.delay_value if risk_state and risk_state.delay_value is not None else "N/A"
    deadline_label = risk_state.deadline_label if risk_state and risk_state.deadline_label else "Không có"

    return (
        "Hãy phân tích và đề xuất hành động cho issue sau:\n"
        f"- Mã issue: {issue.key}\n"
        f"- Tóm tắt: {issue.summary}\n"
        f"- Phân loại: {issue.issuetype or 'N/A'}\n"
        f"- Mức ưu tiên: {issue.priority or 'N/A'}\n"
        f"- Trạng thái hiện tại: {issue.status or 'N/A'} (nhóm: {issue.status_category or 'N/A'})\n"
        f"- Người phụ trách hiện tại: {_assignee_line(issue.assignee_name, issue.assignee_id)}\n"
        f"- Hạn chót (Deadline/DueDate): {deadline_info}\n"
        f"- Nhãn hạn: {deadline_label}\n"
        f"- Story Points: {issue.story_points if issue.story_points is not None else 'N/A'}\n"
        f"- Tạo lúc: {_when(issue.created_at)}\n"
        f"- Cập nhật lúc: {_when(issue.updated_at)}\n"
        f"- Mức độ rủi ro (Risk Level): {risk_level}\n"
        f"- Xác suất trễ (delay_value): {delay_value}\n"
        f"- Bị chặn (Blocked): {is_blocked}\n"
        f"- Trọng yếu (Critical): {is_critical}\n"
        f"- Mô tả:\n{_issue_description(issue)}\n"
        f"- Tiến độ (changelog, cũ đến mới):\n{progress}\n"
        f"- Sprint:\n{sprint_head}\n"
        f"- Task khác trong cùng sprint:\n{roster}\n"
        f"- Task liên kết:\n{related}\n"
        f"- Yếu tố rủi ro (id | nhãn | giá trị):\n{factor_block}\n"
        f"- Danh sách factor được phép trích dẫn: {factors_str}\n\n"
        "Yêu cầu: Trả về JSON theo đúng schema đã hướng dẫn. Chỉ trích dẫn factor từ danh sách được phép ở trên."
    )


def validate_suggestion(output: SuggestionOutput, actual_factors: list[str]) -> bool:
    actual_set = set(actual_factors)
    for f in output.factors_cited:
        if f not in actual_set:
            return False
    for a in output.actions:
        if a.action_type not in ALLOWED_ACTION_TYPES:
            return False
    return True


def call_ollama_chat(
    prompt: str,
    system_prompt: str,
    model: str,
    base_url: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "format": "json",
        "stream": False,
    }

    c = client or _http_client
    if c is not None:
        resp = c.post(url, json=payload, timeout=120.0)
    else:
        with httpx.Client(timeout=120.0) as http_client:
            resp = http_client.post(url, json=payload)

    resp.raise_for_status()
    data = resp.json()
    message = data.get("message", {})
    content = message.get("content", "")
    if isinstance(content, dict):
        return content
    return json.loads(content)


def get_cached_suggestion(
    session: Session,
    issue_key: str,
    issue_updated_at: datetime | None,
) -> Suggestion | None:
    stmt = select(Suggestion).where(
        Suggestion.issue_key == issue_key,
        Suggestion.valid.is_(True),
    )
    if issue_updated_at is not None:
        stmt = stmt.where(Suggestion.issue_updated_at == issue_updated_at)
    stmt = stmt.order_by(Suggestion.id.desc())
    return session.scalars(stmt).first()


def _extract_factors(risk_state: RiskState | None) -> tuple[list[str], list[str]]:
    """Return (display_factors, valid_factors).

    display_factors: unique primary names/labels to present in user prompt.
    valid_factors: set of all recognized ids, names, and labels for validation.
    """
    display: list[str] = []
    valid: set[str] = set()
    if not risk_state or not risk_state.factors:
        return display, list(valid)

    for f in risk_state.factors:
        if isinstance(f, dict):
            primary = f.get("name") or f.get("id") or f.get("label")
            if primary and str(primary) not in display:
                display.append(str(primary))
            for k in ("name", "id", "label"):
                val = f.get(k)
                if val:
                    valid.add(str(val))
        elif isinstance(f, str):
            if f not in display:
                display.append(f)
            valid.add(f)

    return display, list(valid)


def generate_suggestion(
    session: Session,
    issue_key: str,
    settings: Settings,
    client: httpx.Client | None = None,
) -> Suggestion:
    issue = session.get(Issue, issue_key)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_key}")

    cached = get_cached_suggestion(session, issue_key, issue.updated_at)
    if cached is not None:
        return cached

    risk_state = session.get(RiskState, issue_key)
    display_factors, valid_factors = _extract_factors(risk_state)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(session, issue, risk_state, display_factors)

    last_raw_or_parsed: Any = {}
    valid_output: SuggestionOutput | None = None

    for attempt in range(2):
        prompt_to_send = user_prompt
        if attempt > 0:
            prompt_to_send = (
                f"{user_prompt}\n\n"
                f"[LƯU Ý SỬA LỖI]: Lần thử trước không hợp lệ. "
                f"Vui lòng đảm bảo trả về đúng JSON khớp schema, "
                f"chỉ sử dụng action_type trong {sorted(ALLOWED_ACTION_TYPES)}, "
                f"và chỉ trích dẫn factors trong {display_factors}."
            )

        try:
            raw_dict = call_ollama_chat(
                prompt=prompt_to_send,
                system_prompt=system_prompt,
                model=settings.llm_model,
                base_url=settings.ollama_url,
                client=client,
            )
            last_raw_or_parsed = raw_dict
            parsed = SuggestionOutput.model_validate(raw_dict)
            if validate_suggestion(parsed, valid_factors):
                valid_output = parsed
                break
            log.warning("Attempt %d validation failed for %s", attempt + 1, issue_key)
        except json.JSONDecodeError as e:
            log.warning("Attempt %d JSON decode error for %s: %s", attempt + 1, issue_key, e)
            last_raw_or_parsed = {"raw": e.doc, "error": str(e)}
        except ValidationError as e:
            log.warning("Attempt %d Pydantic validation error for %s: %s", attempt + 1, issue_key, e)
            last_raw_or_parsed = raw_dict if "raw_dict" in locals() else {"error": str(e)}
        except Exception as e:
            log.warning("Attempt %d unexpected error for %s: %s", attempt + 1, issue_key, e)
            last_raw_or_parsed = {"error": str(e)}

    now = utcnow()
    if valid_output is not None:
        suggestion = Suggestion(
            issue_key=issue_key,
            issue_updated_at=issue.updated_at,
            model=settings.llm_model,
            output=valid_output.model_dump(),
            valid=True,
            created_at=now,
        )
    else:
        suggestion = Suggestion(
            issue_key=issue_key,
            issue_updated_at=issue.updated_at,
            model=settings.llm_model,
            output=last_raw_or_parsed if isinstance(last_raw_or_parsed, dict) else {"raw": str(last_raw_or_parsed)},
            valid=False,
            created_at=now,
        )

    session.add(suggestion)
    session.commit()
    return suggestion


def is_suggestion_in_progress(issue_key: str) -> bool:
    with _lock:
        return issue_key in _in_progress_keys


def enqueue_suggestion(
    issue_key: str,
    settings: Settings,
    engine: Any | None = None,
    client: httpx.Client | None = None,
) -> bool:
    with _lock:
        if issue_key in _in_progress_keys:
            return False
        _in_progress_keys.add(issue_key)

    def _worker() -> None:
        try:
            eng = engine or _engine
            if eng is None:
                eng = make_engine(settings.db_url)
            with SessionLocal(bind=eng) as session:
                generate_suggestion(session, issue_key, settings, client=client)
        except Exception as e:
            log.exception("Background suggestion generation failed for %s: %s", issue_key, e)
        finally:
            with _lock:
                _in_progress_keys.discard(issue_key)

    _llm_executor.submit(_worker)
    return True
