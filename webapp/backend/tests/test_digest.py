from datetime import UTC, datetime, timedelta

from erw.models import Issue, IssueSprint, Notification, RiskState, Sprint
from erw.pipeline.alerts import AlertSpec, notify
from erw.pipeline.digest import build_digest

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)  # 08:00 ICT


def add(session, n, level="HIGH", crit=None, sp=None, cat="indeterminate", created=None, blocked=False,
        prev=None, updated=None, raised_at=None, summary="Task <x>"):
    key = f"DEMO-{n}"
    if raised_at is None and prev and prev != level:
        from erw.domain.types import Level
        if Level[level] > Level[prev]:
            raised_at = updated or NOW
    session.add(Issue(key=key, project_key="DEMO", summary=summary, status_category=cat, story_points=sp,
                      assignee_name="An", created_at=created or NOW - timedelta(days=10)))
    session.add(RiskState(issue_key=key, level=level, prev_level=prev, level_raised_at=raised_at,
                          crit_score=crit, blocked=blocked,
                          deadline_label="Trễ due date", updated_at=updated or NOW, is_critical=crit is not None))
    session.flush()


def test_digest_header_and_max_five_items(session, settings):
    for n in range(1, 8):
        add(session, n, crit=n / 10)
    text = build_digest(session, "DEMO", NOW, settings)
    lines = text.split("\n")
    assert lines[0] == "[Tổng hợp ngày][DEMO] 04/11"
    assert lines[1].startswith("Nguy cơ trễ: 7 (0 tăng bậc 24h) · Bị block: 0 · Mới 24h: 0 (0 critical)")
    items = [ln for ln in lines if ln.startswith("•")]
    assert len(items) == 5 and "DEMO-7" in items[0]
    assert "Task &lt;x&gt;" in items[0] and "@An" in items[0] and "Cao" in items[0]
    assert lines[-1] == "<http://localhost:8000|Xem tất cả trên Early Risk>"


def test_digest_counts(session, settings):
    add(session, 1, level="MED", prev="LOW", updated=NOW - timedelta(hours=2), blocked=True)
    add(session, 2, level="LOW", created=NOW - timedelta(hours=3), crit=0.9)
    add(session, 3, level="HIGH", cat="done")
    text = build_digest(session, "DEMO", NOW, settings)
    assert "Nguy cơ trễ: 1 (1 tăng bậc 24h) · Bị block: 1 · Mới 24h: 1 (1 critical)" in text


def _sprint(session, start_days=-5, end_days=5):
    session.add(Sprint(id=1, name="Sprint 24", state="active", start_at=NOW + timedelta(days=start_days),
                       end_at=NOW + timedelta(days=end_days)))
    session.flush()


def test_digest_sprint_progress_story_points_vs_count(session, settings):
    _sprint(session)
    add(session, 1, sp=8, cat="done")
    add(session, 2, sp=2)
    for n in (1, 2):
        session.add(IssueSprint(issue_key=f"DEMO-{n}", sprint_id=1))
    session.flush()
    assert "Tiến độ Sprint 24: 80% (kỳ vọng 50%)" in build_digest(session, "DEMO", NOW, settings)
    # no story points on the done issue -> coverage 50% < 80% -> count by task
    session.get(Issue, "DEMO-1").story_points = None
    session.flush()
    assert "Tiến độ Sprint 24: 50% (kỳ vọng 50%)" in build_digest(session, "DEMO", NOW, settings)


def test_digest_expected_clamped(session, settings):
    _sprint(session, start_days=-20, end_days=-10)
    add(session, 1)
    session.add(IssueSprint(issue_key="DEMO-1", sprint_id=1))
    session.flush()
    assert "(kỳ vọng 100%)" in build_digest(session, "DEMO", NOW, settings)


def test_digest_without_active_sprint_omits_progress(session, settings):
    add(session, 1)
    assert "Tiến độ" not in build_digest(session, "DEMO", NOW, settings)


def test_digest_sent_once_per_day(session, settings):
    spec = AlertSpec("digest", None, "DEMO", None, "digest:DEMO:2026-11-04")
    assert notify(session, spec, "x", None, NOW, 20) == "disabled"
    class S:
        def post(self, t): pass
    assert notify(session, spec, "x", S(), NOW, 20) == "sent"
    assert notify(session, spec, "x", S(), NOW, 20) == "duplicate"
    assert session.query(Notification).count() == 1


def test_digest_level_raised_preserved_across_morning_reevaluation(session, settings):
    from erw.pipeline.evaluate import evaluate_issue

    t0 = NOW - timedelta(hours=17)
    # Issue initially exists at LOW
    session.add(Issue(
        key="DEMO-1", project_key="DEMO", summary="Overdue task", status_category="indeterminate",
        created_at=t0 - timedelta(days=5), duedate=t0 - timedelta(days=1),  # overdue at t0
    ))
    session.add(RiskState(issue_key="DEMO-1", level="LOW"))
    session.flush()

    # Raise at T: LOW -> HIGH
    evaluate_issue(session, "DEMO-1", t0, settings)
    rs = session.get(RiskState, "DEMO-1")
    assert rs.level == "HIGH"
    assert rs.level_raised_at == t0

    # Morning re-evaluation at T+15h (level remains HIGH)
    t_morning = t0 + timedelta(hours=15)
    evaluate_issue(session, "DEMO-1", t_morning, settings)
    rs = session.get(RiskState, "DEMO-1")
    assert rs.level == "HIGH"
    assert rs.prev_level == "HIGH"
    assert rs.level_raised_at == t0  # preserved!

    # Digest at T+17h (2h after morning re-evaluation): still within 24h of T
    t_digest = t0 + timedelta(hours=17)
    text = build_digest(session, "DEMO", t_digest, settings)
    assert "(1 tăng bậc 24h)" in text
