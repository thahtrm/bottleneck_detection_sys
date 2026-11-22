"""Option B: constrained chat narrate + allowlist; Option A templates as fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from erw.models import Issue, Project, RiskState
from erw.pipeline.chat_narrate import (
    narrate_chat_facts,
    narrate_payloads,
    payload_allowlists,
    validate_chat_narration,
)
from erw.pipeline.chat_tools import run_tool
from erw.settings import Settings

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def _seed_lan_load(session) -> None:
    if session.get(Project, "DEMO") is None:
        session.add(Project(key="DEMO", name="Demo"))
        session.flush()
    for n, crit in enumerate((0.9, 0.8, 0.7), start=1):
        session.add(
            Issue(
                key=f"DEMO-{n}",
                project_key="DEMO",
                summary=f"Task {n}",
                status_category="indeterminate",
                assignee_name="Lan",
                created_at=NOW,
            )
        )
        session.add(
            RiskState(
                issue_key=f"DEMO-{n}",
                level="HIGH" if n == 1 else "MED",
                crit_score=crit,
                deadline_label="hạn mai" if n == 1 else None,
                updated_at=NOW,
            )
        )
    session.flush()


def test_payload_allowlists_collect_keys_and_counts(session, settings: Settings):
    _seed_lan_load(session)
    result = run_tool(session, "lookup_assignee_load", {}, "DEMO", NOW, settings)
    keys, nums = payload_allowlists([result.payload])
    assert "DEMO-1" in keys and "DEMO-2" in keys and "DEMO-3" in keys
    assert 3 in nums  # count
    slim = narrate_payloads([result])
    assert slim and all("line" not in issue for issue in slim[0].get("issues") or [])


def test_validate_rejects_invented_key_and_count():
    allowed_keys = frozenset({"DEMO-1"})
    allowed_numbers = frozenset({1, 3})
    assert validate_chat_narration("Lan có 3 việc: DEMO-1.", allowed_keys, allowed_numbers)
    assert validate_chat_narration("Lan có 3 việc: DEMO-99.", allowed_keys, allowed_numbers) is None
    assert validate_chat_narration("Lan có 9 việc: DEMO-1.", allowed_keys, allowed_numbers) is None


def test_narrate_accepts_grounded_prose(session, settings: Settings):
    _seed_lan_load(session)
    result = run_tool(session, "lookup_assignee_load", {}, "DEMO", NOW, settings)
    settings = settings.model_copy(update={"ollama_url": "http://ollama.test"})
    prose = "Lan đang phụ trách nhiều nhất với 3 việc chưa xong. Ưu tiên DEMO-1 mức Cao hạn mai, rồi DEMO-2 và DEMO-3."

    with patch("erw.pipeline.chat_narrate.call_ollama_chat_text", return_value=prose):
        out = narrate_chat_facts([result], settings)
    assert out == prose


def test_narrate_falls_back_on_invented_count(session, settings: Settings):
    _seed_lan_load(session)
    result = run_tool(session, "lookup_assignee_load", {}, "DEMO", NOW, settings)
    settings = settings.model_copy(update={"ollama_url": "http://ollama.test"})
    bad = "Lan đang ôm 99 việc, gồm DEMO-1."

    with patch("erw.pipeline.chat_narrate.call_ollama_chat_text", return_value=bad):
        assert narrate_chat_facts([result], settings) is None


def test_narrate_skips_without_ollama(session, settings: Settings):
    _seed_lan_load(session)
    result = run_tool(session, "lookup_assignee_load", {}, "DEMO", NOW, settings)
    settings = settings.model_copy(update={"ollama_url": ""})

    def boom(*_a, **_k):
        raise AssertionError("Ollama must not be called")

    with patch("erw.pipeline.chat_narrate.call_ollama_chat_text", side_effect=boom):
        assert narrate_chat_facts([result], settings) is None


def test_assignee_template_fallback_omits_repeated_name(session, settings: Settings):
    _seed_lan_load(session)
    result = run_tool(session, "lookup_assignee_load", {}, "DEMO", NOW, settings)
    assert result.ok
    lines = result.facts.splitlines()
    assert lines[0].startswith("Lan đang được giao")
    bullets = [ln for ln in lines[1:] if ln.startswith("DEMO-")]
    assert bullets
    assert all("Lan" not in ln for ln in bullets)
    assert "assignee" not in result.facts.casefold()
