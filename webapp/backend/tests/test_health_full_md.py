"""Mode B: LLM full health markdown — validate + Facts-only fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from erw.models import Issue, Project, RiskState
from erw.pipeline.health_report import (
    LLM_FULL_MD_FLAG,
    build_health_markdown,
    collect_health_snapshot,
    health_md_skeleton,
    narrate_health,
    render_facts_markdown,
    validate_health_markdown,
)
from erw.settings import Settings

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def _seed_demo(session) -> None:
    if session.get(Project, "DEMO") is None:
        session.add(Project(key="DEMO", name="Demo"))
        session.flush()
    session.add(
        Issue(
            key="DEMO-1",
            project_key="DEMO",
            summary="Việc quan trọng",
            status_category="indeterminate",
            assignee_name="Lan",
            created_at=NOW,
        )
    )
    session.add(RiskState(issue_key="DEMO-1", level="HIGH", blocked=False, updated_at=NOW))
    session.flush()


def test_skeleton_has_seven_sections(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    skeleton = health_md_skeleton(snap)
    assert "## 1. Overview" in skeleton
    assert "## 7. Action recommendations" in skeleton
    assert "### AI Insight" in skeleton


def test_validate_accepts_facts_only_template(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    md = render_facts_markdown(snap)
    assert validate_health_markdown(md, snap) is not None


def test_validate_strips_invented_keys(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    md = render_facts_markdown(snap)
    poisoned = md.replace("DEMO-1", "DEMO-99", 1)
    cleaned = validate_health_markdown(poisoned, snap)
    assert cleaned is not None
    assert "DEMO-99" not in cleaned


def test_validate_strips_invented_counts(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    md = render_facts_markdown(snap)
    # Inject a count that cannot appear in the snapshot allowlist — strip, keep sections.
    poisoned = md.replace(f"Open: {snap.facts['overview']['open_count']}", "Open: 424242", 1)
    cleaned = validate_health_markdown(poisoned, snap)
    assert cleaned is not None
    assert "424242" not in cleaned
    assert "## 1. Overview" in cleaned


def test_validate_rejects_missing_section(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    md = render_facts_markdown(snap).replace("## 7. Action recommendations", "## 7. Other")
    assert validate_health_markdown(md, snap) is None


def test_narrate_health_returns_validated_full_md(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    facts = render_facts_markdown(snap)
    settings.ollama_url = "http://ollama.test"

    def fake_llm(prompt, system, model, base_url, client=None, timeout=300.0):
        return facts

    with patch("erw.pipeline.health_report.call_ollama_chat_text", side_effect=fake_llm):
        out = narrate_health(snap, settings)
    assert out is not None
    assert "## 1. Overview" in out
    assert "DEMO-1" in out


def test_narrate_health_none_on_llm_failure(session, settings: Settings):
    _seed_demo(session)
    snap = collect_health_snapshot(session, "DEMO", NOW, settings)
    settings.ollama_url = "http://ollama.test"

    def boom(*_a, **_k):
        raise RuntimeError("ollama down")

    with patch("erw.pipeline.health_report.call_ollama_chat_text", side_effect=boom):
        assert narrate_health(snap, settings) is None


def test_build_health_markdown_falls_back_to_facts(session, settings: Settings):
    _seed_demo(session)
    settings.ollama_url = ""  # no LLM → Facts-only
    body, snap, narratives = build_health_markdown(session, "DEMO", NOW, settings)
    assert LLM_FULL_MD_FLAG not in narratives
    assert body == render_facts_markdown(snap)
    assert "### Facts" in body


def test_build_health_markdown_uses_llm_full_md(session, settings: Settings):
    _seed_demo(session)
    settings.ollama_url = "http://ollama.test"
    snap_preview = collect_health_snapshot(session, "DEMO", NOW, settings)
    llm_body = render_facts_markdown(snap_preview)
    # Mark it so we can tell LLM path was used (same as facts content is fine).
    llm_body = llm_body.replace(
        "### Facts\n",
        "### Facts\n- LLM_FULL_MARK\n",
        1,
    )

    def fake_llm(prompt, system, model, base_url, client=None, timeout=300.0):
        return llm_body

    with patch("erw.pipeline.health_report.call_ollama_chat_text", side_effect=fake_llm):
        body, _snap, narratives = build_health_markdown(session, "DEMO", NOW, settings)
    assert narratives.get(LLM_FULL_MD_FLAG) == "1"
    assert "LLM_FULL_MARK" in body
