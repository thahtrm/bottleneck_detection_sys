from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from early_risk_detection.data.normalize import normalize_link_type, normalize_priority
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erw.db import utcnow
from erw.integrations.jira import JiraClient, JiraError
from erw.kv import kv_get, kv_get_json, kv_set, kv_set_json
from erw.models import Change, Issue, IssueSprint, IssueVersion, Link, Sprint, Version
from erw.settings import Settings


@dataclass
class SyncResult:
    kind: Literal["created", "updated", "unchanged", "deleted", "ignored"]
    key: str
    changed_fields: frozenset[str] = frozenset()


_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_dt(s: str | None) -> datetime | None:
    """Jira timestamps ('...368+0700', '...199Z') -> tz-aware UTC."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = _TZ_NO_COLON.sub(r"\1:\2", s)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _set_sprint(session: Session, raw: dict) -> Sprint | None:
    sid = _to_int(raw.get("id"))
    if sid is None:
        return None
    sp = session.get(Sprint, sid) or Sprint(id=sid)
    sp.name = raw.get("name", sp.name)
    sp.state = raw.get("state", sp.state)
    sp.board_id = _to_int(raw.get("boardId", raw.get("originBoardId"))) or sp.board_id
    sp.start_at = parse_dt(raw.get("startDate")) or sp.start_at
    sp.end_at = parse_dt(raw.get("endDate")) or sp.end_at
    sp.complete_at = parse_dt(raw.get("completeDate")) or sp.complete_at
    session.add(sp)
    return sp


def _set_version(session: Session, raw: dict, project_key: str | None = None) -> Version | None:
    vid = _to_int(raw.get("id"))
    if vid is None:
        return None
    v = session.get(Version, vid) or Version(id=vid, released=False)
    v.name = raw.get("name", v.name)
    if "releaseDate" in raw:
        v.release_date = _parse_date(raw["releaseDate"])
    if "released" in raw:
        v.released = bool(raw["released"])
    v.project_key = project_key or v.project_key
    session.add(v)
    return v


def upsert_issue_json(session: Session, raw: dict, settings: Settings) -> SyncResult:
    key = raw["key"]
    fields = raw.get("fields") or {}
    project_key = (fields.get("project") or {}).get("key") or key.rsplit("-", 1)[0]
    if project_key not in settings.jira_projects:
        return SyncResult("ignored", key)

    issue = session.get(Issue, key)
    created = issue is None
    if created:
        issue = Issue(key=key)
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    category = (status.get("statusCategory") or {}).get("key") or "new"
    category = settings.status_category_overrides.get(status.get("name"), category)

    issue.project_key = project_key
    issue.summary = fields.get("summary") or ""
    issue.issuetype = (fields.get("issuetype") or {}).get("name")
    issue.priority = (fields.get("priority") or {}).get("name")
    issue.priority_norm = normalize_priority(fields.get("priority"))
    issue.status = status.get("name")
    issue.status_category = category
    issue.assignee_id = assignee.get("accountId")
    issue.assignee_name = assignee.get("displayName")
    issue.duedate = _parse_date(fields.get("duedate"))
    sp = fields.get(settings.jira_story_points_field)
    issue.story_points = float(sp) if sp is not None else None
    issue.created_at = parse_dt(fields.get("created"))
    issue.updated_at = parse_dt(fields.get("updated"))
    issue.resolved_at = parse_dt(fields.get("resolutiondate"))
    issue.deleted_at = None
    issue.raw = raw
    session.add(issue)
    session.flush()

    # changelog: only histories not yet stored
    known = set(session.scalars(select(Change.change_id).where(Change.issue_key == key)))
    changed: set[str] = set()
    for h in (raw.get("changelog") or {}).get("histories", []):
        cid = str(h["id"])
        if cid in known:
            continue
        at = parse_dt(h.get("created"))
        for idx, it in enumerate(h.get("items", [])):
            field = (it.get("field") or "").lower()
            changed.add(field)
            session.add(
                Change(
                    issue_key=key, change_id=cid, idx=idx, at=at, field=field,
                    from_val=it.get("from"), to_val=it.get("to"),
                    from_str=it.get("fromString"), to_str=it.get("toString"),
                )
            )

    # sprints
    session.execute(delete(IssueSprint).where(IssueSprint.issue_key == key))
    seen: set[int] = set()
    for rs in fields.get(settings.jira_sprint_field) or []:
        s = _set_sprint(session, rs)
        if s is not None and s.id not in seen:
            seen.add(s.id)
    session.flush()
    session.add_all(IssueSprint(issue_key=key, sprint_id=i) for i in seen)

    # fix versions
    session.execute(delete(IssueVersion).where(IssueVersion.issue_key == key))
    vids: set[int] = set()
    for rv in fields.get("fixVersions") or []:
        v = _set_version(session, rv, project_key)
        if v is not None:
            vids.add(v.id)
    session.flush()
    session.add_all(IssueVersion(issue_key=key, version_id=i) for i in vids)

    # links (this issue is always the source; direction 1 = outward, 0 = inward)
    session.execute(delete(Link).where(Link.source_key == key))
    links: dict[tuple[str, str], str] = {}
    for lk in fields.get("issuelinks") or []:
        type_std = normalize_link_type((lk.get("type") or {}).get("name"))
        if lk.get("outwardIssue"):
            links[(lk["outwardIssue"]["key"], type_std)] = "1"
        elif lk.get("inwardIssue"):
            links[(lk["inwardIssue"]["key"], type_std)] = "0"
    session.add_all(Link(source_key=key, target_key=t, type_std=ty, direction=d) for (t, ty), d in links.items())
    session.flush()

    if created:
        return SyncResult("created", key, frozenset(changed))
    if changed:
        return SyncResult("updated", key, frozenset(changed))
    return SyncResult("unchanged", key)


def mark_deleted(session: Session, key: str) -> SyncResult:
    issue = session.get(Issue, key)
    if issue is not None:
        issue.deleted_at = utcnow()
        session.flush()
    return SyncResult("deleted", key)


def sync_issue(session: Session, client: JiraClient, key: str, settings: Settings) -> SyncResult:
    raw = client.get_issue(key)
    if raw is None:
        return mark_deleted(session, key)
    return upsert_issue_json(session, raw, settings)


def sync_sprint(session: Session, raw_sprint: dict) -> list[str]:
    sp = _set_sprint(session, raw_sprint)
    session.flush()
    if sp is None:
        return []
    return list(session.scalars(select(IssueSprint.issue_key).where(IssueSprint.sprint_id == sp.id).order_by(IssueSprint.issue_key)))


def sync_version(session: Session, raw_version: dict, project_key: str | None = None) -> list[str]:
    v = _set_version(session, raw_version, project_key)
    session.flush()
    if v is None:
        return []
    return list(session.scalars(select(IssueVersion.issue_key).where(IssueVersion.version_id == v.id).order_by(IssueVersion.issue_key)))


def catch_up(session: Session, client: JiraClient, settings: Settings, now: datetime) -> int:
    """Re-sync issues updated since the last webhook (minus 5 min) plus any pending_sync keys."""
    from erw.pipeline.evaluate import on_synced

    last = kv_get(session, "last_webhook_at")
    since = (datetime.fromisoformat(last) if last else now - timedelta(days=1)) - timedelta(minutes=5)
    tz = ZoneInfo(client.myself().get("timeZone") or "UTC")
    stamp = since.astimezone(tz).strftime("%Y/%m/%d %H:%M")
    projects = ", ".join(f'"{p}"' for p in settings.jira_projects)
    keys = client.search_keys(f'project in ({projects}) AND updated >= "{stamp}"')
    for k in kv_get_json(session, "pending_sync", []):
        if k not in keys:
            keys.append(k)

    results: list[SyncResult] = []
    still_pending: list[str] = []
    for k in keys:
        try:
            results.append(sync_issue(session, client, k, settings))
        except JiraError:
            still_pending.append(k)
    kv_set_json(session, "pending_sync", still_pending)
    kv_set(session, "last_catch_up_at", now.isoformat())
    session.commit()
    on_synced(session, results, now, settings)
    session.commit()
    return len(results)
