from datetime import UTC, datetime, timedelta

import pytest

from erw.domain.triage import classify_triage

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
RAISED = NOW - timedelta(hours=6)

OPEN = {
    "status_category": "indeterminate",
    "resolved_at": None,
    "level": None,
    "dismissed_at_level": None,
    "blocked": False,
    "level_raised_at": None,
    "last_applied_action_at": None,
}


@pytest.mark.parametrize(
    ("case", "overrides", "expected"),
    [
        ("done yesterday", {"status_category": "done", "resolved_at": NOW - timedelta(days=1)}, "done"),
        ("done exactly 7 days ago", {"status_category": "done", "resolved_at": NOW - timedelta(days=7)}, "done"),
        ("done 8 days ago leaves the board", {"status_category": "done", "resolved_at": NOW - timedelta(days=8)}, None),
        ("done without resolved_at leaves the board", {"status_category": "done"}, None),
        ("done issue ignores its HIGH risk", {"status_category": "done", "resolved_at": NOW, "level": "HIGH"}, "done"),
        ("no risk state", {}, "ok"),
        ("LOW risk", {"level": "LOW"}, "ok"),
        ("new issue with LOW risk", {"status_category": "new", "level": "LOW"}, "ok"),
        ("HIGH risk untouched", {"level": "HIGH", "level_raised_at": RAISED}, "needs_action"),
        ("MED risk untouched", {"level": "MED", "level_raised_at": RAISED}, "needs_action"),
        ("blocked without risk level", {"blocked": True}, "needs_action"),
        ("blocked with LOW risk", {"level": "LOW", "blocked": True}, "needs_action"),
        ("dismissed at the current level", {"level": "HIGH", "dismissed_at_level": "HIGH"}, "in_hand"),
        ("dismissed at MED, now HIGH", {"level": "HIGH", "dismissed_at_level": "MED"}, "needs_action"),
        ("blocked, dismissal needs a level", {"blocked": True, "dismissed_at_level": None}, "needs_action"),
        (
            "action applied after the raise",
            {"level": "HIGH", "level_raised_at": RAISED, "last_applied_action_at": RAISED + timedelta(minutes=1)},
            "in_hand",
        ),
        (
            "action applied at the raise instant",
            {"level": "HIGH", "level_raised_at": RAISED, "last_applied_action_at": RAISED},
            "in_hand",
        ),
        (
            "action applied before the raise",
            {"level": "HIGH", "level_raised_at": RAISED, "last_applied_action_at": RAISED - timedelta(days=1)},
            "needs_action",
        ),
        (
            "action applied, raise time unknown",
            {"level": "MED", "last_applied_action_at": RAISED},
            "in_hand",
        ),
        ("blocked with an applied action", {"blocked": True, "last_applied_action_at": RAISED}, "in_hand"),
    ],
)
def test_classify_triage(case, overrides, expected):
    assert classify_triage(**{**OPEN, **overrides}, now=NOW) == expected, case
