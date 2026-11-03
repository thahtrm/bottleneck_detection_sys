from datetime import UTC, date, datetime, timedelta

import pytest

from erw.domain.deadline import resolve_deadline, sla_days
from erw.domain.types import IssueTimeline, Level, SprintInfo, VersionInfo

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def tl(**kw) -> IssueTimeline:
    base = dict(
        key="D-1", project="D", summary="", issuetype="Bug", priority_norm=0.5, status="Open",
        status_category="new", assignee_id=None, assignee_name=None, created_at=T0,
        resolved_at=None, deleted_at=None, duedate=None, status_since=T0,
    )
    base.update(kw)
    return IssueTimeline(**base)


S23 = SprintInfo(23, "Sprint 23", "closed", T0, datetime(2026, 10, 20, tzinfo=UTC))
S24 = SprintInfo(24, "Sprint 24", "active", T0, datetime(2026, 11, 4, 10, tzinfo=UTC))
S25 = SprintInfo(25, "Sprint 25", "future", None, datetime(2026, 11, 18, tzinfo=UTC))


def test_duedate_wins():
    d = resolve_deadline(tl(duedate=date(2026, 11, 5), sprints=[S24]))
    assert d.type == "duedate"
    assert d.at == datetime(2026, 11, 5, 16, 59, 59, tzinfo=UTC)
    assert d.label == "Trễ due date 05/11"


def test_sprint_when_no_duedate():
    d = resolve_deadline(tl(sprints=[S25, S23, S24]))
    assert d.type == "sprint" and d.at == S24.end_at
    assert d.label == "Trễ sprint Sprint 24 (04/11)"


def test_release_when_no_sprint():
    vs = [
        VersionInfo(1, "2.4", date(2026, 12, 1), False),
        VersionInfo(2, "2.3", date(2026, 11, 15), False),
        VersionInfo(3, "2.2", date(2026, 10, 1), True),
    ]
    d = resolve_deadline(tl(sprints=[S23], versions=vs))
    assert d.type == "release" and d.label == "Vượt release 2.3 (15/11)"


def test_deadline_falls_back_to_sla():
    d = resolve_deadline(tl(issuetype="Task", priority_norm=0.5))
    assert d.type == "sla" and d.at == T0 + timedelta(days=21)
    assert d.label == "Hạn: SLA mô hình 21 ngày"


@pytest.mark.parametrize(
    "it,p,days",
    [("Bug", 0.5, 45), ("Task", 0.5, 21), ("New Feature", 0.5, 90), ("Story", 0.5, 90),
     ("Task", 0.6, 30), ("Bug", 0.8, 14), (None, 0.0, 45)],
)
def test_sla_days(it, p, days):
    assert sla_days(it, p) == days


def test_level_labels():
    assert [lv.label_vi for lv in Level] == ["Thấp", "TB", "Cao"]
