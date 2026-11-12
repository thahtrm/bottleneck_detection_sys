from datetime import datetime

import numpy as np

from erw.domain.deadline import DISPLAY_TZ
from erw.domain.types import Deadline, Factor, IssueTimeline, ProjectStats, Thresholds

DEFAULT_DWELL_P75_DAYS = 5.0
_DAY = 86400.0


def _days(seconds: float) -> int:
    return max(1, int(seconds // _DAY))


def _fmt_days(seconds: float) -> str:
    return f"{_days(seconds)} ngày"


def _sprint_elapsed(tl: IssueTimeline, deadline: Deadline, now: datetime) -> float | None:
    for s in tl.sprints:
        if s.end_at == deadline.at and s.start_at is not None and s.end_at > s.start_at:
            return (now - s.start_at).total_seconds() / (s.end_at - s.start_at).total_seconds()
    return None


def evaluate_rules(
    tl: IssueTimeline, deadline: Deadline, now: datetime, stats: ProjectStats, th: Thresholds
) -> list[Factor]:
    """Dynamic rule signals for one open issue; done or deleted issues have none."""
    if tl.status_category == "done" or tl.deleted_at is not None:
        return []
    out: list[Factor] = []
    overdue = now > deadline.at
    if overdue:
        out.append(Factor("overdue", "Quá hạn", _fmt_days((now - deadline.at).total_seconds()), "deadline"))

    if deadline.type == "sprint" and tl.status_category == "new":
        frac = _sprint_elapsed(tl, deadline, now)
        if frac is not None and frac >= th.sprint_elapsed:
            out.append(Factor(
                "sprint_not_started", "Sprint đã qua phần lớn nhưng chưa bắt đầu", f"{round(frac * 100)}%", "sprint"
            ))

    status = tl.status or ""
    dwell_s = (now - tl.status_since).total_seconds()
    if dwell_s / _DAY > stats.dwell_p75_days.get(status, DEFAULT_DWELL_P75_DAYS):
        out.append(Factor("stagnant", f"Đứng ở {status}", _fmt_days(dwell_s), "changelog"))

    if tl.open_blockers:
        out.append(Factor("blocked", "Bị chặn bởi", ",".join(sorted(tl.open_blockers)), "links"))
        if tl.blocked_since is not None:
            bs = (now - tl.blocked_since).total_seconds()
            if bs / _DAY > th.blocked_long_days:
                out.append(Factor("blocked_long", "Bị chặn kéo dài", _fmt_days(bs), "links"))

    if tl.reopen_count >= th.reopen_min:
        out.append(Factor("reopened", "Bị mở lại", f"{tl.reopen_count} lần", "changelog"))

    moves = tl.duedate_changes + tl.sprint_changes
    if moves >= th.deadline_moves_min:
        out.append(Factor("deadline_moved", "Dời hạn nhiều lần", f"{moves} lần", "changelog"))

    if tl.assignee_changes >= th.reassign_min:
        out.append(Factor("reassigned", "Đổi người xử lý nhiều lần", f"{tl.assignee_changes} lần", "assignee"))

    if tl.assignee_id is None and not overdue:
        wd = int(np.busday_count(
            now.astimezone(DISPLAY_TZ).date(), deadline.at.astimezone(DISPLAY_TZ).date()
        ))
        if wd <= th.unassigned_workdays:
            out.append(Factor(
                "unassigned_near_deadline", "Chưa có người nhận, gần hạn", f"{wd} ngày làm việc", "assignee"
            ))

    if tl.closed_sprints_count >= 1:
        out.append(Factor("carried_over", "Chuyển từ sprint trước", f"{tl.closed_sprints_count} sprint", "sprint"))
    return out
