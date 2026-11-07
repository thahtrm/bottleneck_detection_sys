from datetime import UTC, date, datetime, timedelta

import pytest

from erw.domain.board import Column, build_layout, card_deadline, card_reason, sprint_progress
from erw.domain.deadline import end_of_day_utc

OBSERVED = [
    ("In Progress", "indeterminate"),
    ("To Do", "new"),
    ("Done", "done"),
    ("Open", "new"),
    ("Blocked", "indeterminate"),
    ("To Do", "new"),
]


def _ids(layout):
    return [c.id for c in layout.columns]


def test_empty_map_derives_one_column_per_status_in_band_order():
    layout = build_layout({}, OBSERVED)

    assert layout.columns == (
        Column("status:open", "Open", "new", ("Open",), False),
        Column("status:to-do", "To Do", "new", ("To Do",), False),
        Column("status:blocked", "Blocked", "indeterminate", ("Blocked",), False),
        Column("status:in-progress", "In Progress", "indeterminate", ("In Progress",), False),
        Column("status:done", "Done", "done", ("Done",), False),
    )


def test_map_merges_statuses_into_one_column_and_keeps_map_order():
    status_map = {"columns": [
        {"name": "Đang làm", "statuses": ["In Progress"], "category": "indeterminate"},
        {"name": "Cần làm", "statuses": ["Open", "To Do"], "category": "new"},
        {"name": "Xong", "statuses": ["Done", "Closed"], "category": "done"},
    ]}

    layout = build_layout(status_map, OBSERVED)

    assert [(c.name, c.statuses, c.unmapped) for c in layout.columns] == [
        ("Cần làm", ("Open", "To Do"), False),
        ("Đang làm", ("In Progress",), False),
        ("Blocked", ("Blocked",), True),
        ("Xong", ("Done", "Closed"), False),
    ]
    assert layout.column_for("Open") == layout.column_for("To Do") == "status:cần-làm"
    assert layout.column_for("closed") == "status:xong"


def test_unmapped_status_is_appended_to_the_end_of_its_band():
    status_map = {"columns": [
        {"name": "Backlog", "statuses": ["To Do"], "category": "new"},
        {"name": "Doing", "statuses": ["In Progress"], "category": "indeterminate"},
        {"name": "Done", "statuses": ["Done"], "category": "done"},
    ]}

    layout = build_layout(status_map, [*OBSERVED, ("Waiting", "indeterminate")])

    assert _ids(layout) == [
        "status:backlog", "status:open",
        "status:doing", "status:blocked", "status:waiting",
        "status:done",
    ]
    assert [c.unmapped for c in layout.columns] == [False, True, False, True, True, False]


@pytest.mark.parametrize(
    "status_map",
    [
        None,
        "columns",
        {"columns": "nope"},
        {"columns": [
            "not a dict",
            {"name": "", "statuses": ["To Do"], "category": "new"},
            {"name": "No category", "statuses": ["To Do"]},
            {"name": "Bad category", "statuses": ["To Do"], "category": "todo"},
            {"name": "Bad statuses", "statuses": "To Do", "category": "new"},
        ]},
    ],
)
def test_malformed_map_entries_are_skipped(status_map):
    assert build_layout(status_map, OBSERVED) == build_layout({}, OBSERVED)


def test_valid_entries_survive_next_to_malformed_ones():
    status_map = {"columns": [
        {"name": 42, "statuses": ["Open"], "category": "new"},
        {"name": "Todo", "statuses": ["To Do", 7, "Open"], "category": "new"},
    ]}

    layout = build_layout(status_map, OBSERVED)

    assert layout.columns[0] == Column("status:todo", "Todo", "new", ("To Do", "Open"), False)


def test_every_observed_status_has_a_column_including_a_missing_status():
    observed = [*OBSERVED, (None, "new"), ("in progress", "indeterminate")]
    status_map = {"columns": [{"name": "Doing", "statuses": ["In Progress"], "category": "indeterminate"}]}

    layout = build_layout(status_map, observed)

    ids = set(_ids(layout))
    assert all(layout.column_for(status) in ids for status, _ in observed)
    assert len(ids) == len(layout.columns)


def test_column_ids_stay_unique_when_names_slug_alike():
    status_map = {"columns": [
        {"name": "To Do", "statuses": ["To Do"], "category": "new"},
        {"name": "to-do", "statuses": ["Open"], "category": "new"},
    ]}

    assert _ids(build_layout(status_map, OBSERVED))[:2] == ["status:to-do", "status:to-do-2"]


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def test_sprint_progress_counts_points_when_any_issue_has_points():
    progress = sprint_progress(
        [("done", 5.0), ("indeterminate", 8.0), ("new", None), ("done", None)],
        start_at=NOW - timedelta(days=5),
        end_at=NOW + timedelta(days=5),
        now=NOW,
    )

    assert (progress.unit, progress.done, progress.total) == ("points", 5.0, 13.0)
    assert progress.done_pct == 0.38
    assert progress.expected_pct == 0.5


def test_sprint_progress_falls_back_to_issue_count():
    progress = sprint_progress(
        [("done", None), ("new", None), ("new", None), ("indeterminate", None)],
        start_at=NOW - timedelta(days=20),
        end_at=NOW - timedelta(days=6),
        now=NOW,
    )

    assert (progress.unit, progress.done, progress.total, progress.done_pct) == ("issues", 1.0, 4.0, 0.25)
    assert progress.expected_pct == 1.0


def test_sprint_progress_empty_sprint_and_unknown_dates():
    progress = sprint_progress([], start_at=None, end_at=None, now=NOW)

    assert (progress.done, progress.total, progress.done_pct, progress.expected_pct) == (0.0, 0.0, 0.0, None)


def test_sprint_not_started_expects_nothing_yet():
    progress = sprint_progress([], start_at=NOW + timedelta(days=1), end_at=NOW + timedelta(days=10), now=NOW)

    assert progress.expected_pct == 0.0


def test_card_deadline_prefers_risk_deadline_then_duedate():
    at = NOW + timedelta(days=3)
    risk = card_deadline(deadline_type="sprint", deadline_label="Sprint 1", deadline_at=at, duedate=date(2026, 12, 1))
    due = card_deadline(deadline_type=None, deadline_label=None, deadline_at=None, duedate=date(2026, 12, 1))

    assert (risk.type, risk.label, risk.at) == ("sprint", "Sprint 1", at)
    assert (due.type, due.label, due.at) == ("duedate", "Due date", end_of_day_utc(date(2026, 12, 1)))
    assert card_deadline(deadline_type=None, deadline_label=None, deadline_at=None, duedate=None) is None


@pytest.mark.parametrize(
    ("factors", "expected"),
    [
        ([{"id": "blocked", "label": "Bị chặn", "value": "4 ngày", "source": "links"}, {"label": "x"}], "Bị chặn: 4 ngày"),
        ([{"id": "unassigned", "label": "Chưa phân công", "value": "", "source": "assignee"}], "Chưa phân công"),
        ([{"rule": "blocked_stale", "detail": "Bị chặn bởi DEMO-105"}], "Bị chặn bởi DEMO-105"),
        ([], None),
        (None, None),
    ],
)
def test_card_reason_is_the_first_factor(factors, expected):
    assert card_reason(factors) == expected
