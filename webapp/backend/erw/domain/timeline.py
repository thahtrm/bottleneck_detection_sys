from collections.abc import Mapping
from datetime import datetime

from erw.domain.types import IssueTimeline, SprintInfo, VersionInfo
from erw.models import Change, Issue, Sprint, Version

_DEFAULT_CATEGORIES = {
    "done": "done", "closed": "done", "resolved": "done",
    "to do": "new", "open": "new", "backlog": "new",
}


def _category(name: str | None, table: dict[str, str]) -> str:
    return table.get((name or "").strip().lower(), "indeterminate")


def _is_initial(c: Change) -> bool:
    return not (c.from_val or c.from_str)


def build_timeline(
    issue: Issue,
    changes: list[Change],
    sprints: list[Sprint],
    versions: list[Version],
    blockers: list[tuple[str, bool, datetime]],
    as_of: datetime,
    status_categories: Mapping[str, str] | None = None,
) -> IssueTimeline:
    table = dict(_DEFAULT_CATEGORIES)
    table.update({k.strip().lower(): v for k, v in (status_categories or {}).items()})

    chs = sorted((c for c in changes if c.at <= as_of), key=lambda c: (c.at, c.idx))
    status_changes = [c for c in chs if c.field == "status"]
    status_since = status_changes[-1].at if status_changes else issue.created_at

    sprint_infos = [SprintInfo(s.id, s.name, s.state, s.start_at, s.end_at) for s in sprints]
    version_infos = [VersionInfo(v.id, v.name, v.release_date, v.released) for v in versions]

    current = [s for s in sprints if s.state == "active" and s.start_at is not None]
    since = max((s.start_at for s in current), default=None)
    reopen = 0
    last_status_change = max((c for c in changes if c.field == "status"), key=lambda c: (c.at, c.idx), default=None)
    for c in status_changes:
        if since is not None and c.at < since:
            continue
        to_cat = issue.status_category if c is last_status_change else _category(c.to_str, table)
        if _category(c.from_str, table) == "done" and to_cat != "done":
            reopen += 1

    def count(name: str) -> int:
        return sum(1 for c in chs if c.field == name and not _is_initial(c))

    open_b = [b for b in blockers if not b[1]]
    return IssueTimeline(
        key=issue.key,
        project=issue.project_key,
        summary=issue.summary,
        issuetype=issue.issuetype,
        priority_norm=issue.priority_norm,
        status=issue.status,
        status_category=issue.status_category,
        assignee_id=issue.assignee_id,
        assignee_name=issue.assignee_name,
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
        deleted_at=issue.deleted_at,
        duedate=issue.duedate,
        status_since=status_since,
        sprints=sprint_infos,
        versions=version_infos,
        reopen_count=reopen,
        duedate_changes=count("duedate"),
        sprint_changes=count("sprint"),
        assignee_changes=count("assignee"),
        closed_sprints_count=sum(1 for s in sprints if s.state == "closed"),
        open_blockers=[b[0] for b in open_b],
        blocked_since=min((b[2] for b in open_b), default=None),
    )
