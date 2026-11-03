from dataclasses import dataclass, field
from datetime import date, datetime
from enum import IntEnum
from typing import Literal


class Level(IntEnum):
    LOW = 0
    MED = 1
    HIGH = 2

    @property
    def label_vi(self) -> str:
        return {0: "Thấp", 1: "TB", 2: "Cao"}[int(self)]


@dataclass(frozen=True)
class Deadline:
    type: Literal["duedate", "sprint", "release", "sla"]
    at: datetime
    label: str


@dataclass(frozen=True)
class SprintInfo:
    id: int
    name: str | None
    state: str | None
    start_at: datetime | None
    end_at: datetime | None


@dataclass(frozen=True)
class VersionInfo:
    id: int
    name: str | None
    release_date: date | None
    released: bool


@dataclass(frozen=True)
class IssueTimeline:
    key: str
    project: str
    summary: str
    issuetype: str | None
    priority_norm: float
    status: str | None
    status_category: str
    assignee_id: str | None
    assignee_name: str | None
    created_at: datetime | None
    resolved_at: datetime | None
    deleted_at: datetime | None
    duedate: date | None
    status_since: datetime
    sprints: list[SprintInfo] = field(default_factory=list)
    versions: list[VersionInfo] = field(default_factory=list)
    reopen_count: int = 0
    duedate_changes: int = 0
    sprint_changes: int = 0
    assignee_changes: int = 0
    closed_sprints_count: int = 0
    open_blockers: list[str] = field(default_factory=list)
    blocked_since: datetime | None = None
