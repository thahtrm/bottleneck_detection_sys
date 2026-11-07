from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, get_args

from erw.domain.deadline import end_of_day_utc
from erw.domain.types import Deadline

StatusCategory = Literal["new", "indeterminate", "done"]
BANDS: tuple[StatusCategory, ...] = get_args(StatusCategory)
NO_STATUS_NAME = "(Không có trạng thái)"


@dataclass(frozen=True)
class Column:
    id: str
    name: str
    category: StatusCategory
    statuses: tuple[str, ...]
    unmapped: bool


@dataclass(frozen=True)
class ColumnLayout:
    """Ordered board columns plus the status -> column id registry; covers every status it was built from."""

    columns: tuple[Column, ...]
    index: Mapping[str, str]

    def column_for(self, status: str | None) -> str:
        return self.index[_status_key(status)]


def _status_key(status: str | None) -> str:
    return (status or NO_STATUS_NAME).strip().casefold()


def _slug(name: str) -> str:
    return re.sub(r"[^\w]+", "-", name.casefold()).strip("-_") or "column"


def _parse_status_map(status_map: Any) -> list[tuple[str, StatusCategory, tuple[str, ...]]]:
    entries = status_map.get("columns") if isinstance(status_map, dict) else None
    if not isinstance(entries, list):
        return []
    parsed = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name, category, statuses = entry.get("name"), entry.get("category"), entry.get("statuses")
        if not isinstance(name, str) or not name.strip() or category not in BANDS or not isinstance(statuses, list):
            continue
        parsed.append((name.strip(), category, tuple(s.strip() for s in statuses if isinstance(s, str) and s.strip())))
    return parsed


def build_layout(status_map: Any, observed: Iterable[tuple[str | None, str]]) -> ColumnLayout:
    """Columns from the project's status_map, plus one column per observed status the map does not cover.

    `observed` is (status, status_category) pairs from the issues on the board.
    """
    mapped = _parse_status_map(status_map)
    has_map = bool(mapped)
    by_band: dict[str, list[tuple[str, tuple[str, ...], bool]]] = {band: [] for band in BANDS}
    covered: set[str] = set()
    for name, category, statuses in mapped:
        own = tuple(s for s in statuses if _status_key(s) not in covered)
        covered.update(_status_key(s) for s in own)
        by_band[category].append((name, own, False))

    leftovers: dict[str, tuple[str, str]] = {}
    for status, category in observed:
        key = _status_key(status)
        if key not in covered and key not in leftovers:
            band = category if category in BANDS else "new"
            leftovers[key] = (status.strip() if status and status.strip() else NO_STATUS_NAME, band)
    for name, band in sorted(leftovers.values(), key=lambda nb: nb[0].casefold()):
        by_band[band].append((name, (name,), has_map))

    columns: list[Column] = []
    index: dict[str, str] = {}
    used_ids: set[str] = set()
    for band in BANDS:
        for name, statuses, unmapped in by_band[band]:
            base = f"status:{_slug(name)}"
            col_id, n = base, 2
            while col_id in used_ids:
                col_id, n = f"{base}-{n}", n + 1
            used_ids.add(col_id)
            columns.append(Column(col_id, name, band, statuses, unmapped))
            index.update((_status_key(s), col_id) for s in statuses)
    return ColumnLayout(tuple(columns), index)


@dataclass(frozen=True)
class SprintProgress:
    unit: Literal["points", "issues"]
    done: float
    total: float
    done_pct: float
    expected_pct: float | None


def sprint_progress(
    issues: Iterable[tuple[str, float | None]],
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    now: datetime,
) -> SprintProgress:
    """`issues` is (status_category, story_points) for every issue in the sprint, done ones included."""
    scope = list(issues)
    by_points = any(points is not None for _, points in scope)
    weights = [((points or 0.0) if by_points else 1.0, category == "done") for category, points in scope]
    total = float(sum(w for w, _ in weights))
    done = float(sum(w for w, is_done in weights if is_done))
    expected = None
    if start_at is not None and end_at is not None and end_at > start_at:
        expected = round(min(1.0, max(0.0, (now - start_at) / (end_at - start_at))), 2)
    return SprintProgress(
        unit="points" if by_points else "issues",
        done=done,
        total=total,
        done_pct=round(done / total, 2) if total else 0.0,
        expected_pct=expected,
    )


def card_deadline(
    *,
    deadline_type: str | None,
    deadline_label: str | None,
    deadline_at: datetime | None,
    duedate: date | None,
) -> Deadline | None:
    if deadline_at is not None:
        return Deadline(deadline_type or "duedate", deadline_at, deadline_label or "")
    if duedate is not None:
        return Deadline("duedate", end_of_day_utc(duedate), "Due date")
    return None


def card_reason(factors: Any) -> str | None:
    """First risk factor as "{label}: {value}"; also reads the older {rule, detail} factor shape."""
    if not isinstance(factors, list) or not factors:
        return None
    first = factors[0]
    if isinstance(first, str):
        return first or None
    if not isinstance(first, dict):
        return None
    label = first.get("label")
    if not label:
        return first.get("detail") or first.get("rule") or None
    value = first.get("value")
    return f"{label}: {value}" if value not in (None, "") else str(label)
