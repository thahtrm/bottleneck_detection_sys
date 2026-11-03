from datetime import UTC, date, datetime, timedelta

from erw.domain.timeline import build_timeline
from erw.models import Change, Issue, Sprint, Version

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def d(n):
    return T0 + timedelta(days=n)


def issue(**kw):
    base = dict(key="A-1", project_key="A", summary="s", issuetype="Task", priority_norm=0.5,
                status="Done", status_category="done", created_at=T0, duedate=date(2026, 11, 1))
    base.update(kw)
    return Issue(**base)


def ch(n, field, frm=None, to=None, idx=0):
    return Change(issue_key="A-1", change_id=str(n), idx=idx, at=d(n), field=field,
                  from_str=frm, to_str=to, from_val=frm, to_val=to)


def test_timeline_ignores_changes_after_as_of():
    cs = [ch(1, "status", "To Do", "In Progress"), ch(5, "status", "In Progress", "Done"),
          ch(6, "duedate", "2026-11-01", "2026-11-09")]
    tl = build_timeline(issue(), cs, [], [], [], as_of=d(2))
    assert tl.status_since == d(1) and tl.duedate_changes == 0


def test_reopen_counted_from_done_to_not_done():
    cs = [ch(1, "status", "In Progress", "Done"), ch(2, "status", "Done", "Reopened"),
          ch(3, "status", "Reopened", "Closed"), ch(4, "status", "Closed", "In Progress")]
    tl = build_timeline(issue(status_category="indeterminate"), cs, [], [], [], as_of=d(10))
    assert tl.reopen_count == 2


def test_reopen_counted_since_current_sprint_start():
    cs = [ch(1, "status", "Done", "Open"), ch(6, "status", "Open", "Done"), ch(7, "status", "Done", "Open")]
    sp = Sprint(id=1, name="S", state="active", start_at=d(5), end_at=d(15))
    tl = build_timeline(issue(status_category="new"), cs, [sp], [], [], as_of=d(10))
    assert tl.reopen_count == 1


def test_custom_status_categories_and_current_uses_issue_category():
    cs = [ch(1, "status", "Shipped", "Working"), ch(2, "status", "Working", "Weird")]
    tl = build_timeline(issue(status="Weird", status_category="done"), cs, [], [], [], as_of=d(5),
                        status_categories={"shipped": "done"})
    assert tl.reopen_count == 1  # Shipped->Working only; Weird is current and 'done'


def test_status_since_is_last_status_change():
    cs = [ch(1, "status", "To Do", "In Progress"), ch(3, "status", "In Progress", "Done"), ch(4, "assignee", "a", "b")]
    assert build_timeline(issue(), cs, [], [], [], as_of=d(9)).status_since == d(3)
    assert build_timeline(issue(), [], [], [], [], as_of=d(9)).status_since == T0


def test_change_counts_skip_initial_set():
    cs = [ch(0, "assignee", None, "u1"), ch(1, "assignee", "u1", "u2"), ch(1, "sprint", None, "1", idx=1),
          ch(2, "sprint", "1", "1, 2"), ch(3, "duedate", None, "2026-11-01"), ch(4, "duedate", "2026-11-01", "2026-11-09")]
    tl = build_timeline(issue(), cs, [], [], [], as_of=d(9))
    assert (tl.assignee_changes, tl.sprint_changes, tl.duedate_changes) == (1, 1, 1)


def test_sprints_versions_and_blockers():
    sps = [Sprint(id=1, name="a", state="closed"), Sprint(id=2, name="b", state="active")]
    vs = [Version(id=1, name="1.0", release_date=date(2026, 12, 1), released=False)]
    bl = [("B-1", False, d(3)), ("B-2", False, d(2)), ("B-3", True, d(1))]
    tl = build_timeline(issue(), [], sps, vs, bl, as_of=d(9))
    assert tl.closed_sprints_count == 1 and len(tl.sprints) == 2 and tl.versions[0].name == "1.0"
    assert tl.open_blockers == ["B-1", "B-2"] and tl.blocked_since == d(2)
    none = build_timeline(issue(), [], [], [], [("B-3", True, d(1))], as_of=d(9))
    assert none.open_blockers == [] and none.blocked_since is None
