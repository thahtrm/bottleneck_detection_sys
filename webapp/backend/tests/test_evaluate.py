from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from erw.domain.types import Level
from erw.ingest.sync import SyncResult, upsert_issue_json
from erw.models import Change, Issue, Link, RiskState, Score
from erw.pipeline import evaluate as ev

NOW = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)
CREATED = NOW - timedelta(days=2)


@pytest.fixture(autouse=True)
def _clear_cache():
    ev.clear_stats_cache()
    yield
    ev.clear_stats_cache()


def mk(session, key="DEMO-1", **kw):
    d = dict(project_key="DEMO", summary="s", issuetype="Task", priority_norm=0.5, status="In Progress",
             status_category="indeterminate", assignee_id="a", assignee_name="A",
             duedate=date(2026, 12, 30), created_at=CREATED)
    d.update(kw)
    i = Issue(key=key, **d)
    session.add(i)
    session.commit()
    return i


def test_new_blocked_issue_creates_risk_state(session, settings, issue_blocked):
    upsert_issue_json(session, issue_blocked, settings)
    session.commit()
    ch = ev.evaluate_issue(session, "DEMO-3", NOW, settings, is_new=True)
    rs = session.get(RiskState, "DEMO-3")
    assert rs.blocked and ch.newly_blocked and ch.is_new and ch.prev_level is None
    assert ch.level >= Level.MED and rs.level == ch.level.name
    assert rs.deadline_label


def test_level_increase_tracked(session, settings):
    i = mk(session, status="Open", status_category="new")
    session.add(Link(source_key="DEMO-1", target_key="DEMO-9", type_std="Block", direction="0"))
    session.commit()
    c1 = ev.evaluate_issue(session, "DEMO-1", NOW, settings)
    assert c1.level == Level.MED
    i.duedate = date(2026, 11, 1)
    session.commit()
    c2 = ev.evaluate_issue(session, "DEMO-1", NOW + timedelta(minutes=5), settings)
    assert c2.prev_level == Level.MED and c2.level == Level.HIGH and not c2.newly_blocked
    assert session.get(RiskState, "DEMO-1").prev_level == "MED"


def test_resolved_issue_is_low_and_not_alerted(session, settings):
    mk(session, status="Done", status_category="done", duedate=date(2026, 11, 1))
    session.add(Score(issue_key="DEMO-1", scorer="delay_t0", as_of=NOW, value=0.95, extra={"predicted_duration_days": 400}))
    session.commit()
    s = settings.model_copy(update={"model_mode": "active"})
    ch = ev.evaluate_issue(session, "DEMO-1", NOW, s)
    assert ch.level == Level.LOW
    assert session.get(RiskState, "DEMO-1").factors == []


def test_model_signals_used_only_in_active_mode(session, settings):
    mk(session)
    session.add(Score(issue_key="DEMO-1", scorer="delay_t0", as_of=NOW, value=0.95, extra={"predicted_duration_days": 5}))
    session.add(Score(issue_key="DEMO-1", scorer="criticality_t0", as_of=NOW, value=0.8, is_critical=True))
    session.commit()
    sh = ev.evaluate_issue(session, "DEMO-1", NOW, settings)
    assert sh.level == Level.LOW and sh.became_critical
    rs = session.get(RiskState, "DEMO-1")
    assert rs.delay_value == 0.95 and rs.is_critical and rs.crit_score == 0.8
    act = ev.evaluate_issue(session, "DEMO-1", NOW, settings.model_copy(update={"model_mode": "active"}))
    assert act.level == Level.MED and not act.became_critical


def test_latest_model_signals(session):
    assert ev.latest_model_signals(session, "X-1") is None
    mk(session)
    session.add(Score(issue_key="DEMO-1", scorer="delay_t0", as_of=NOW - timedelta(days=1), value=0.1, extra={"predicted_duration_days": 1}))
    session.add(Score(issue_key="DEMO-1", scorer="delay_t0", as_of=NOW, value=0.7, extra={"predicted_duration_days": 10}))
    session.commit()
    m = ev.latest_model_signals(session, "DEMO-1")
    assert m.p_delay == 0.7 and m.predicted_finish == CREATED + timedelta(days=10) and not m.is_critical


def test_rules_score_appended_each_evaluation(session, settings):
    mk(session)
    ev.evaluate_issue(session, "DEMO-1", NOW, settings)
    ev.evaluate_issue(session, "DEMO-1", NOW, settings)
    rows = session.scalars(select(Score).where(Score.scorer == "rules_dynamic")).all()
    assert len(rows) == 2 and rows[0].deadline_type == "duedate"


def test_missing_issue_returns_none(session, settings):
    assert ev.evaluate_issue(session, "NOPE-1", NOW, settings) is None


def test_blocker_done_is_not_open(session, settings):
    mk(session, "DEMO-1")
    mk(session, "DEMO-2", status="Done", status_category="done")
    b3 = mk(session, "DEMO-3", status="Done", status_category="done")
    session.add(Link(source_key="DEMO-1", target_key="DEMO-2", type_std="Block", direction="0"))
    session.add(Link(source_key="DEMO-3", target_key="DEMO-1", type_std="Block", direction="1"))
    session.commit()
    ev.evaluate_issue(session, "DEMO-1", NOW, settings)
    assert not session.get(RiskState, "DEMO-1").blocked
    b3.status_category = "indeterminate"
    session.commit()
    ev.evaluate_issue(session, "DEMO-1", NOW, settings)
    assert session.get(RiskState, "DEMO-1").blocked  # DEMO-3 blocks DEMO-1 (outward row on DEMO-3)


def test_project_stats_p75_and_cache(session):
    mk(session)
    t = CREATED
    for n, (d, to) in enumerate([(0, "A"), (4, "B"), (8, "C")]):
        session.add(Change(issue_key="DEMO-1", change_id=str(n), idx=0, at=t + timedelta(days=d), field="status",
                           from_str="x", to_str=to))
    session.commit()
    st = ev.project_stats(session, "DEMO")
    assert st.dwell_p75_days == {"A": 4.0, "B": 4.0}
    session.add(Change(issue_key="DEMO-1", change_id="9", idx=0, at=t + timedelta(days=20), field="status",
                       from_str="C", to_str="D"))
    session.commit()
    assert ev.project_stats(session, "DEMO") == st  # cached
    ev.clear_stats_cache()
    assert "C" in ev.project_stats(session, "DEMO").dwell_p75_days


def test_on_synced_evaluates_and_deletes(session, settings):
    mk(session, "DEMO-1")
    session.add(RiskState(issue_key="DEMO-2", level="LOW"))
    session.commit()
    out = ev.on_synced(session, [SyncResult("created", "DEMO-1"), SyncResult("deleted", "DEMO-2"),
                                 SyncResult("unchanged", "DEMO-1")], NOW, settings)
    assert len(out) == 1 and out[0].is_new
    assert session.get(RiskState, "DEMO-2") is None and session.get(RiskState, "DEMO-1") is not None


def test_evaluate_all_skips_deleted(session, settings):
    mk(session, "DEMO-1")
    mk(session, "DEMO-2", deleted_at=NOW)
    mk(session, "OTHER-1", project_key="OTHER")
    assert [c.key for c in ev.evaluate_all(session, NOW, settings)] == ["DEMO-1"]
