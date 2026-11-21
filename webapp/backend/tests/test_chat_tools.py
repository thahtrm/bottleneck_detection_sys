from datetime import UTC, datetime

from erw.models import Issue, Project, RiskState
from erw.pipeline.chat_lookup import answer_facts
from erw.pipeline.chat_tools import board_tool_succeeded, render_facts_from_tool_results, run_tool, tool_hint, union_allowed_keys
from erw.settings import Settings

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def _seed(session):
    session.add(Project(key="DEMO", name="Demo"))
    session.add(
        Issue(
            key="DEMO-1",
            project_key="DEMO",
            summary="A",
            status_category="indeterminate",
            assignee_name="Lan",
            updated_at=NOW,
        )
    )
    session.add(RiskState(issue_key="DEMO-1", level="HIGH", crit_score=0.9, blocked=True, updated_at=NOW))
    session.commit()


def test_tool_hint_maps_phrases():
    assert tool_hint("tiến độ sprint thế nào", "DEMO") == "lookup_sprint"
    assert tool_hint("ai bị block", "DEMO") == "lookup_blocked"
    assert tool_hint("DEMO-9 sao rồi", "DEMO") == "lookup_issue"
    assert tool_hint("thời tiết", "DEMO") is None


def test_lookup_tools_match_answer_facts(session, settings):
    _seed(session)
    for text, tool in [
        ("tiến độ sprint", "lookup_sprint"),
        ("issue bị block", "lookup_blocked"),
        ("nguy cơ trễ", "lookup_risky"),
        ("DEMO-1 sao rồi", "lookup_issue"),
    ]:
        direct = answer_facts(session, "DEMO", text, NOW, settings)
        via = run_tool(session, tool, {}, "DEMO", NOW, settings, user_text=text)
        assert via.ok
        assert via.facts == direct.facts
        assert via.allowed_keys == direct.allowed_keys


def test_digest_snapshot_tool(session, settings):
    _seed(session)
    result = run_tool(session, "get_digest_snapshot", {}, "DEMO", NOW, settings)
    assert result.ok
    assert result.payload["risky_count"] == 1
    assert result.payload["blocked_count"] == 1
    assert "DEMO-1" in result.allowed_keys


def test_unknown_tool_rejected(session, settings):
    result = run_tool(session, "apply_jira", {}, "DEMO", NOW, settings)
    assert not result.ok
    assert result.error


def test_render_and_union(session, settings):
    _seed(session)
    a = run_tool(session, "lookup_blocked", {}, "DEMO", NOW, settings)
    b = run_tool(session, "lookup_risky", {}, "DEMO", NOW, settings)
    facts = render_facts_from_tool_results([a, b])
    assert "bị block" in facts
    assert board_tool_succeeded([a, b])
    assert "DEMO-1" in union_allowed_keys([a, b])
