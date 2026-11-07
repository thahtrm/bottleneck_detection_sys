from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

Triage = Literal["needs_action", "in_hand", "ok", "done"]

RECENT_DONE_WINDOW = timedelta(days=7)
_FLAGGED_LEVELS = frozenset({"HIGH", "MED"})


def classify_triage(
    *,
    status_category: str,
    resolved_at: datetime | None,
    level: str | None,
    dismissed_at_level: str | None,
    blocked: bool,
    level_raised_at: datetime | None,
    last_applied_action_at: datetime | None,
    now: datetime,
) -> Triage | None:
    """Where an issue sits on the PM's "what still needs me" board; None means off the board."""
    if status_category == "done":
        recent = resolved_at is not None and now - resolved_at <= RECENT_DONE_WINDOW
        return "done" if recent else None
    if level not in _FLAGGED_LEVELS and not blocked:
        return "ok"
    dismissed = level is not None and dismissed_at_level == level
    # An action applied before the risk was raised does not address the current risk.
    acted = last_applied_action_at is not None and (
        level_raised_at is None or last_applied_action_at >= level_raised_at
    )
    return "in_hand" if dismissed or acted else "needs_action"
