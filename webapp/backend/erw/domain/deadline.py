from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from early_risk_detection.data.normalize import ISSUE_THEME_MAP

from erw.domain.types import Deadline, IssueTimeline

DISPLAY_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def end_of_day_utc(d: date) -> datetime:
    """Deadline instant for a date-only value: 23:59:59 on that day in Asia/Ho_Chi_Minh, as UTC."""
    return datetime.combine(d, time(23, 59, 59), tzinfo=DISPLAY_TZ).astimezone(timezone.utc)


def _ddmm(dt: datetime) -> str:
    return dt.astimezone(DISPLAY_TZ).strftime("%d/%m")


def sla_days(issuetype: str | None, priority_norm: float) -> float:
    """Operational SLA in days; mirrors early_risk_detection.delay.features.planned_duration.

    The library's theme comes from the issue type via ISSUE_THEME_MAP.
    """
    it = (issuetype or "Bug").lower()
    theme = ISSUE_THEME_MAP.get(it.strip(), "Other").lower()
    days = 45.0
    if "task" in it:
        days = 21.0
    if "requirement" in theme or "feature" in it:
        days = 90.0
    if priority_norm >= 0.6:
        days = 30.0
    if priority_norm >= 0.8:
        days = 14.0
    return days


def resolve_deadline(tl: IssueTimeline) -> Deadline:
    """duedate -> earliest active/future sprint end -> earliest unreleased version -> model SLA.

    Date-only values (duedate, release_date) are the END of that day (23:59:59) in
    Asia/Ho_Chi_Minh, converted to UTC.
    """
    if tl.duedate is not None:
        at = end_of_day_utc(tl.duedate)
        return Deadline("duedate", at, f"Trễ due date {_ddmm(at)}")
    sprints = [s for s in tl.sprints if s.state in {"active", "future"} and s.end_at is not None]
    if sprints:
        s = min(sprints, key=lambda x: x.end_at)
        return Deadline("sprint", s.end_at, f"Trễ sprint {s.name} ({_ddmm(s.end_at)})")
    versions = [v for v in tl.versions if not v.released and v.release_date is not None]
    if versions:
        v = min(versions, key=lambda x: x.release_date)
        at = end_of_day_utc(v.release_date)
        return Deadline("release", at, f"Vượt release {v.name} ({_ddmm(at)})")
    days = sla_days(tl.issuetype, tl.priority_norm)
    at = tl.created_at + timedelta(days=days)
    return Deadline("sla", at, f"Hạn: SLA mô hình {days:g} ngày")
