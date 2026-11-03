from datetime import datetime, timedelta, timezone

from erw.domain.rules import evaluate_rules
from erw.domain.types import Deadline, IssueTimeline, ProjectStats, SprintInfo, Thresholds

NOW = datetime(2026, 11, 4, 5, tzinfo=timezone.utc)  # Wed 12:00 local
TH = Thresholds()
ST = ProjectStats(dwell_p75_days={"In Progress": 4.0})
FAR = Deadline("duedate", NOW + timedelta(days=30), "x")


def tl(**kw) -> IssueTimeline:
    base = dict(
        key="D-1", project="D", summary="", issuetype="Bug", priority_norm=0.5, status="In Progress",
        status_category="indeterminate", assignee_id="u1", assignee_name="A", created_at=NOW,
        resolved_at=None, deleted_at=None, duedate=None, status_since=NOW,
    )
    base.update(kw)
    return IssueTimeline(**base)


def ids(t, dl=FAR, stats=ST):
    return {f.id: f for f in evaluate_rules(t, dl, NOW, stats, TH)}


def test_clean_issue_no_factors():
    assert ids(tl()) == {}


def test_overdue_pos_neg():
    f = ids(tl(), Deadline("duedate", NOW - timedelta(days=2), "x"))
    assert f["overdue"].value == "2 ngày" and f["overdue"].source == "deadline"
    assert "overdue" not in ids(tl())


def _sprint_dl(start, end):
    s = SprintInfo(1, "S", "active", start, end)
    return Deadline("sprint", end, "x"), s


def test_sprint_not_started_pos():
    dl, s = _sprint_dl(NOW - timedelta(days=8), NOW + timedelta(days=2))
    assert "sprint_not_started" in ids(tl(status_category="new", status="Open", sprints=[s]), dl)


def test_sprint_not_started_neg():
    dl, s = _sprint_dl(NOW - timedelta(days=8), NOW + timedelta(days=2))
    assert "sprint_not_started" not in ids(tl(sprints=[s]), dl)  # already started
    dl, s = _sprint_dl(NOW - timedelta(days=1), NOW + timedelta(days=9))
    assert "sprint_not_started" not in ids(tl(status_category="new", sprints=[s]), dl)  # early
    assert "sprint_not_started" not in ids(tl(status_category="new"), FAR)  # not sprint deadline


def test_stagnant_pos_neg():
    f = ids(tl(status_since=NOW - timedelta(days=6)))
    assert f["stagnant"].label == "Đứng ở In Progress" and f["stagnant"].value == "6 ngày"
    assert f["stagnant"].source == "changelog"
    assert "stagnant" not in ids(tl(status_since=NOW - timedelta(days=3)))


def test_stagnant_default_p75():
    assert "stagnant" not in ids(tl(status_since=NOW - timedelta(days=4)), stats=ProjectStats())
    assert "stagnant" in ids(tl(status_since=NOW - timedelta(days=6)), stats=ProjectStats())


def test_blocked_pos_neg():
    f = ids(tl(open_blockers=["DEMO-7", "DEMO-2"]))
    assert f["blocked"].value == "DEMO-2,DEMO-7" and f["blocked"].source == "links"
    assert "blocked" not in ids(tl())


def test_blocked_long_pos_neg():
    f = ids(tl(open_blockers=["D-2"], blocked_since=NOW - timedelta(days=4)))
    assert f["blocked_long"].value == "4 ngày"
    f = ids(tl(open_blockers=["D-2"], blocked_since=NOW - timedelta(days=2)))
    assert "blocked_long" not in f and "blocked" in f


def test_reopened_pos_neg():
    assert "reopened" in ids(tl(reopen_count=1))
    assert "reopened" not in ids(tl(reopen_count=0))


def test_deadline_moved_pos_neg():
    assert "deadline_moved" in ids(tl(duedate_changes=1, sprint_changes=1))
    assert "deadline_moved" not in ids(tl(duedate_changes=1))


def test_reassigned_pos_neg():
    assert "reassigned" in ids(tl(assignee_changes=2))
    assert "reassigned" not in ids(tl(assignee_changes=1))


def test_unassigned_near_deadline_pos_neg():
    near = Deadline("duedate", NOW + timedelta(days=2), "x")  # Fri
    assert "unassigned_near_deadline" in ids(tl(assignee_id=None), near)
    assert "unassigned_near_deadline" not in ids(tl(assignee_id="u1"), near)
    assert "unassigned_near_deadline" not in ids(tl(assignee_id=None), FAR)
    past = Deadline("duedate", NOW - timedelta(days=1), "x")
    assert "unassigned_near_deadline" not in ids(tl(assignee_id=None), past)


def test_unassigned_counts_working_days():
    # Wed -> next Mon is 3 busy days (Wed, Thu, Fri); Tue is 4
    assert "unassigned_near_deadline" in ids(tl(assignee_id=None), Deadline("duedate", NOW + timedelta(days=5), "x"))
    assert "unassigned_near_deadline" not in ids(tl(assignee_id=None), Deadline("duedate", NOW + timedelta(days=6), "x"))


def test_carried_over_pos_neg():
    assert "carried_over" in ids(tl(closed_sprints_count=1))
    assert "carried_over" not in ids(tl(closed_sprints_count=0))


def test_done_issue_has_no_factors():
    past = Deadline("duedate", NOW - timedelta(days=2), "x")
    assert evaluate_rules(tl(status_category="done", reopen_count=3), past, NOW, ST, TH) == []


def test_deleted_issue_has_no_factors():
    assert evaluate_rules(tl(deleted_at=NOW, reopen_count=3), FAR, NOW, ST, TH) == []
