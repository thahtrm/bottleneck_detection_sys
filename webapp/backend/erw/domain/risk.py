from typing import Literal

from erw.domain.types import Deadline, Factor, IssueTimeline, Level, ModelSignals, Thresholds


def aggregate(
    factors: list[Factor],
    model: ModelSignals | None,
    deadline: Deadline,
    th: Thresholds,
    model_mode: Literal["shadow", "active"] | str,
    tl: IssueTimeline | None = None,
) -> Level:
    """Combine rule factors and (in active mode) model signals into a risk level.

    Pass `tl` to force LOW for done or deleted issues.
    """
    if tl is not None and (tl.status_category == "done" or tl.deleted_at is not None):
        return Level.LOW
    if model_mode == "shadow":
        model = None
    n = sum(1 for f in factors if f.id != "blocked_long")
    overrun = bool(model and model.predicted_finish and model.predicted_finish > deadline.at)
    p = model.p_delay if model and model.p_delay is not None else None
    if any(f.id == "overdue" for f in factors) or n >= 2:
        return Level.HIGH
    if n == 1 and (overrun or (p is not None and p >= th.p_high)):
        return Level.HIGH
    if n == 1 or overrun or (p is not None and p >= th.p_med):
        return Level.MED
    return Level.LOW
