import json
import threading
import time
from datetime import UTC, datetime

import pytest
import respx
from httpx import Response
from sqlalchemy import select

from erw.db import utcnow
from erw.integrations.llm import (
    ALLOWED_ACTION_TYPES,
    ActionItem,
    SuggestionOutput,
    call_ollama_chat,
    enqueue_suggestion,
    generate_suggestion,
    get_cached_suggestion,
    is_suggestion_in_progress,
    validate_suggestion,
)
from erw.models import Issue, RiskState, Suggestion


def test_validate_suggestion_valid():
    output = SuggestionOutput(
        summary="Nguy cơ trễ hạn sprint",
        explanation="Task bị nghẽn do blocker liên quan đến dependency",
        factors_cited=["overdue", "blocked"],
        actions=[
            ActionItem(action_type="adjust_deadline", target="2026-11-20", value="Dời 3 ngày", reason="Thiếu tài nguyên"),
            ActionItem(action_type="escalate_blocker", target="DEMO-99", value=None, reason="Cần gỡ blocker khẩn"),
            ActionItem(action_type="add_comment", target=None, value="Họp sync gấp", reason="Cập nhật tiến độ"),
        ],
    )
    actual_factors = ["overdue", "blocked", "assignee_swapped"]
    assert validate_suggestion(output, actual_factors) is True


def test_validate_suggestion_invalid_action_type():
    output = SuggestionOutput(
        summary="Tóm tắt",
        explanation="Giải thích",
        factors_cited=["overdue"],
        actions=[
            ActionItem(action_type="delete_jira_issue", target="DEMO-1", reason="Sai quy trình"),
        ],
    )
    assert validate_suggestion(output, ["overdue"]) is False


def test_validate_suggestion_fabricated_factor():
    output = SuggestionOutput(
        summary="Tóm tắt",
        explanation="Giải thích",
        factors_cited=["hallucinated_factor"],
        actions=[
            ActionItem(action_type="add_comment", reason="Trao đổi"),
        ],
    )
    assert validate_suggestion(output, ["overdue", "blocked"]) is False


def test_validate_suggestion_empty_factors():
    output = SuggestionOutput(
        summary="Không có rủi ro",
        explanation="Tiến độ bình thường",
        factors_cited=[],
        actions=[],
    )
    assert validate_suggestion(output, []) is True


def test_validate_all_allowed_action_types():
    actions = [ActionItem(action_type=act, reason="reason") for act in ALLOWED_ACTION_TYPES]
    output = SuggestionOutput(
        summary="Đầy đủ hành động",
        explanation="Chi tiết",
        factors_cited=["factor1"],
        actions=actions,
    )
    assert validate_suggestion(output, ["factor1"]) is True


@respx.mock
def test_call_ollama_chat_success():
    expected_content = {
        "summary": "Task có rủi ro cao",
        "explanation": "Sprint sắp kết thúc mà chưa xong",
        "factors_cited": ["sprint_elapsed"],
        "actions": [{"action_type": "adjust_deadline", "reason": "Gia hạn thêm 2 ngày"}],
    }
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(
            200,
            json={
                "model": "qwen3:1.7b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(expected_content),
                },
                "done": True,
            },
        )
    )

    data = call_ollama_chat(
        prompt="User prompt",
        system_prompt="System prompt",
        model="qwen3:1.7b",
        base_url="http://localhost:11434",
    )
    assert data["summary"] == "Task có rủi ro cao"
    assert data["factors_cited"] == ["sprint_elapsed"]
    assert len(data["actions"]) == 1
    assert data["actions"][0]["action_type"] == "adjust_deadline"


@respx.mock
def test_call_ollama_chat_syntax_error():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(
            200,
            json={
                "model": "qwen3:1.7b",
                "message": {
                    "role": "assistant",
                    "content": "Not a valid JSON payload: {summary: broken",
                },
                "done": True,
            },
        )
    )

    with pytest.raises(json.JSONDecodeError):
        call_ollama_chat(
            prompt="User prompt",
            system_prompt="System prompt",
            model="qwen3:1.7b",
            base_url="http://localhost:11434",
        )


def test_generate_suggestion_issue_not_found(session, settings):
    with pytest.raises(ValueError, match="Issue not found: NONEXISTENT-999"):
        generate_suggestion(session, "NONEXISTENT-999", settings)


def test_generate_suggestion_cache_hit(session, settings):
    updated = datetime(2026, 11, 4, 1, 0, 0, tzinfo=UTC)
    issue = Issue(key="DEMO-CACHE-1", project_key="DEMO", summary="Cached task", updated_at=updated)
    session.add(issue)
    cached = Suggestion(
        issue_key="DEMO-CACHE-1",
        issue_updated_at=updated,
        model=settings.llm_model,
        output={"summary": "Pre-calculated suggestion", "explanation": "Cache hit", "factors_cited": [], "actions": []},
        valid=True,
        created_at=utcnow(),
    )
    session.add(cached)
    session.commit()

    # respx is NOT mocked; if an HTTP call were attempted it would raise or fail
    res = generate_suggestion(session, "DEMO-CACHE-1", settings)
    assert res.id == cached.id
    assert res.output["summary"] == "Pre-calculated suggestion"


@respx.mock
def test_generate_suggestion_cache_miss_success(session, settings):
    updated = datetime(2026, 11, 4, 2, 0, 0, tzinfo=UTC)
    issue = Issue(
        key="DEMO-MISS-1",
        project_key="DEMO",
        summary="Important feature",
        priority="High",
        status="In Progress",
        assignee_name="Alice",
        updated_at=updated,
    )
    risk_state = RiskState(
        issue_key="DEMO-MISS-1",
        level="HIGH",
        blocked=True,
        factors=[{"name": "blocked", "id": "blocked", "label": "Bị chặn bởi issue khác"}],
    )
    session.add_all([issue, risk_state])
    session.commit()

    expected_output = {
        "summary": "Công việc bị chặn bởi phụ thuộc kỹ thuật",
        "explanation": "Cần ưu tiên gỡ blocker trước",
        "factors_cited": ["blocked"],
        "actions": [
            {
                "action_type": "escalate_blocker",
                "target": "DEMO-BLOCKED",
                "value": None,
                "reason": "Gỡ blocker ngay",
            }
        ],
    }

    mock_route = respx.post(f"{settings.ollama_url}/api/chat").mock(
        return_value=Response(
            200,
            json={
                "model": settings.llm_model,
                "message": {"role": "assistant", "content": json.dumps(expected_output)},
            },
        )
    )

    res = generate_suggestion(session, "DEMO-MISS-1", settings)
    assert mock_route.called
    assert res.valid is True
    assert res.issue_key == "DEMO-MISS-1"
    assert res.issue_updated_at == updated
    assert res.output["summary"] == expected_output["summary"]
    assert res.output["factors_cited"] == ["blocked"]

    # Verify stored in DB
    db_record = session.scalar(select(Suggestion).where(Suggestion.issue_key == "DEMO-MISS-1"))
    assert db_record is not None
    assert db_record.valid is True
    assert db_record.output["summary"] == expected_output["summary"]


@respx.mock
def test_generate_suggestion_retry_success(session, settings):
    updated = datetime(2026, 11, 4, 3, 0, 0, tzinfo=UTC)
    issue = Issue(key="DEMO-RETRY-1", project_key="DEMO", summary="Feature with retry", updated_at=updated)
    risk_state = RiskState(
        issue_key="DEMO-RETRY-1",
        level="MED",
        factors=[{"name": "overdue", "id": "overdue"}],
    )
    session.add_all([issue, risk_state])
    session.commit()

    valid_payload = {
        "summary": "Đã sửa lỗi sau retry",
        "explanation": "Giải thích chi tiết",
        "factors_cited": ["overdue"],
        "actions": [{"action_type": "adjust_deadline", "reason": "Hạn quá gần"}],
    }

    mock_route = respx.post(f"{settings.ollama_url}/api/chat").mock(
        side_effect=[
            # First attempt: invalid JSON syntax
            Response(200, json={"message": {"content": "broken json{"}}),
            # Second attempt: valid schema
            Response(200, json={"message": {"content": json.dumps(valid_payload)}}),
        ]
    )

    res = generate_suggestion(session, "DEMO-RETRY-1", settings)
    assert mock_route.call_count == 2
    assert res.valid is True
    assert res.output["summary"] == "Đã sửa lỗi sau retry"


@respx.mock
def test_generate_suggestion_retry_failure_marks_invalid(session, settings):
    updated = datetime(2026, 11, 4, 4, 0, 0, tzinfo=UTC)
    issue = Issue(key="DEMO-INVALID-1", project_key="DEMO", summary="Persistently invalid", updated_at=updated)
    risk_state = RiskState(
        issue_key="DEMO-INVALID-1",
        level="HIGH",
        factors=[{"name": "overdue", "id": "overdue"}],
    )
    session.add_all([issue, risk_state])
    session.commit()

    hallucinated_payload = {
        "summary": "Bịa đặt factor",
        "explanation": "Chi tiết",
        "factors_cited": ["fake_nonexistent_factor"],
        "actions": [{"action_type": "adjust_deadline", "reason": "Test"}],
    }

    mock_route = respx.post(f"{settings.ollama_url}/api/chat").mock(
        return_value=Response(200, json={"message": {"content": json.dumps(hallucinated_payload)}})
    )

    res = generate_suggestion(session, "DEMO-INVALID-1", settings)
    assert mock_route.call_count == 2
    assert res.valid is False
    assert res.issue_key == "DEMO-INVALID-1"

    # Verify DB has valid=False
    db_rec = session.scalar(select(Suggestion).where(Suggestion.issue_key == "DEMO-INVALID-1"))
    assert db_rec is not None
    assert db_rec.valid is False


def test_get_cached_suggestion_stale_updated_at(session):
    t1 = datetime(2026, 11, 4, 1, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 4, 2, 0, 0, tzinfo=UTC)

    session.add(
        Suggestion(
            issue_key="DEMO-STALE",
            issue_updated_at=t1,
            model="qwen3:1.7b",
            output={"summary": "old"},
            valid=True,
            created_at=utcnow(),
        )
    )
    session.commit()

    # Querying with t2 should return None because issue was updated after suggestion
    assert get_cached_suggestion(session, "DEMO-STALE", t2) is None
    # Querying with t1 should hit cache
    assert get_cached_suggestion(session, "DEMO-STALE", t1) is not None


@respx.mock
def test_enqueue_suggestion_and_is_in_progress(session, settings, engine):
    updated = datetime(2026, 11, 4, 5, 0, 0, tzinfo=UTC)
    issue = Issue(key="DEMO-ASYNC-1", project_key="DEMO", summary="Async task", updated_at=updated)
    session.add(issue)
    session.commit()

    started_event = threading.Event()
    release_event = threading.Event()

    def slow_response(request):
        started_event.set()
        release_event.wait(timeout=5.0)
        return Response(
            200,
            json={
                "model": settings.llm_model,
                "message": {
                    "content": json.dumps(
                        {
                            "summary": "Async ok",
                            "explanation": "Exp",
                            "factors_cited": [],
                            "actions": [],
                        }
                    )
                },
            },
        )

    respx.post(f"{settings.ollama_url}/api/chat").mock(side_effect=slow_response)

    # Initial state: not in progress
    assert is_suggestion_in_progress("DEMO-ASYNC-1") is False

    # Enqueue first time
    queued = enqueue_suggestion("DEMO-ASYNC-1", settings, engine=engine)
    assert queued is True

    # Wait until thread starts executing the Ollama call
    assert started_event.wait(timeout=5.0)
    assert is_suggestion_in_progress("DEMO-ASYNC-1") is True

    # Duplicate enqueue while in progress should be skipped
    queued_dup = enqueue_suggestion("DEMO-ASYNC-1", settings, engine=engine)
    assert queued_dup is False

    # Release worker to finish
    release_event.set()

    # Wait for completion
    for _ in range(50):
        if not is_suggestion_in_progress("DEMO-ASYNC-1"):
            break
        time.sleep(0.05)

    assert is_suggestion_in_progress("DEMO-ASYNC-1") is False

    # Verify suggestion was saved in DB
    rec = session.scalar(select(Suggestion).where(Suggestion.issue_key == "DEMO-ASYNC-1"))
    assert rec is not None
    assert rec.valid is True
    assert rec.output["summary"] == "Async ok"
