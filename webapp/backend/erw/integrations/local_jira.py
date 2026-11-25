from __future__ import annotations

import copy
import re
import uuid
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from early_risk_detection.data.normalize import normalize_link_type, normalize_priority
from sqlalchemy import Engine, delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from erw.auth import get_user_project_role
from erw.db import SessionLocal, make_engine, utcnow
from erw.domain.timeline import _DEFAULT_CATEGORIES
from erw.integrations.jira import JiraClient, JiraError, Transition
from erw.models import (
    Action,
    Attachment,
    Change,
    Comment,
    Component,
    Issue,
    IssueComponent,
    IssueSprint,
    IssueVersion,
    IssueVote,
    IssueWatcher,
    Link,
    Notification,
    Project,
    ProjectMember,
    RiskState,
    Score,
    Sprint,
    Suggestion,
    User,
    Version,
    Worklog,
)
from erw.settings import Settings
from erw.sql_like import like_contains

DEFAULT_WORKFLOW: dict[str, Any] = {
    "statuses": [
        {"id": "10008", "name": "To Do", "category": "new"},
        {"id": "1", "name": "Open", "category": "new"},
        {"id": "3", "name": "In Progress", "category": "indeterminate"},
        {"id": "10009", "name": "In Review", "category": "indeterminate"},
        {"id": "10010", "name": "Blocked", "category": "indeterminate"},
        {"id": "10001", "name": "Done", "category": "done"},
        {"id": "4", "name": "Reopened", "category": "indeterminate"},
    ],
    "transitions": [
        {"id": "11", "name": "Open", "from": ["To Do", "Reopened"], "to": "Open"},
        {"id": "21", "name": "To Do", "from": ["Open", "In Progress", "In Review", "Blocked", "Reopened"], "to": "To Do"},
        {"id": "31", "name": "Start Progress", "from": ["To Do", "Open", "In Review", "Blocked", "Reopened"], "to": "In Progress"},
        {"id": "41", "name": "In Review", "from": ["To Do", "Open", "In Progress", "Blocked", "Reopened"], "to": "In Review"},
        {"id": "51", "name": "Block", "from": ["To Do", "Open", "In Progress", "In Review", "Blocked", "Reopened"], "to": "Blocked"},
        {
            "id": "61",
            "name": "Done",
            "from": ["To Do", "Open", "In Progress", "In Review", "Blocked", "Reopened"],
            "to": "Done",
            "auto_resolution": "Done",
        },
        {"id": "71", "name": "Reopen Issue", "from": ["Done"], "to": "Reopened"},
    ],
}

LINK_INPUT_MAP: dict[str, tuple[str, str]] = {
    "blocks": ("Block", "1"),
    "is blocked by": ("Block", "0"),
    "depends on": ("Depend", "1"),
    "is depended on by": ("Depend", "0"),
    "relates to": ("Relate", "1"),
    "relates": ("Relate", "1"),
    "duplicates": ("Duplicate", "1"),
    "is duplicated by": ("Duplicate", "0"),
    "clones": ("Clone", "1"),
    "is cloned by": ("Clone", "0"),
}

_LINK_RAW_META: dict[str, dict[str, str]] = {
    "Block": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
    "Depend": {"name": "Depend", "inward": "is depended on by", "outward": "depends on"},
    "Relate": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
    "Duplicate": {"name": "Duplicate", "inward": "is duplicated by", "outward": "duplicates"},
    "Clone": {"name": "Clone", "inward": "is cloned by", "outward": "clones"},
}

_DURATION_MULTIPLIERS = {
    "w": 5 * 8 * 3600,
    "d": 8 * 3600,
    "h": 3600,
    "m": 60,
    "s": 1,
}
_DURATION_TOKEN_RE = re.compile(r"(\d+)\s*([wdhms])", re.IGNORECASE)
_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")
_MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9._:-]*)")
_REKEY_ISSUE_COLUMNS = (
    Change.issue_key,
    Comment.issue_key,
    Attachment.issue_key,
    Worklog.issue_key,
    IssueSprint.issue_key,
    IssueVersion.issue_key,
    IssueWatcher.issue_key,
    IssueVote.issue_key,
    IssueComponent.issue_key,
    Score.issue_key,
    RiskState.issue_key,
    Notification.issue_key,
    Suggestion.issue_key,
    Action.issue_key,
)


class LocalJiraConflictError(JiraError):
    def __init__(
        self,
        *,
        current_version: int | None = None,
        expected_version: int | None = None,
        current_updated: datetime | None = None,
        expected_updated: datetime | str | None = None,
    ) -> None:
        cur_u = _iso_utc(current_updated) if current_updated else None
        exp_u = (
            _iso_utc(expected_updated)
            if isinstance(expected_updated, datetime)
            else (str(expected_updated) if expected_updated is not None else None)
        )
        self.detail: dict[str, Any] = {
            "status": "conflict",
            "error": "conflict",
            "current_version": current_version,
            "expected_version": expected_version,
            "current_updated": cur_u,
            "expected_updated": exp_u,
        }
        super().__init__(409, "Optimistic locking conflict")


class TransitionNotAllowedError(JiraError):
    def __init__(self, target: str, available: list[str]) -> None:
        self.target = target
        self.available = available
        self.detail: dict[str, Any] = {
            "error": "transition_not_allowed",
            "target": target,
            "available": available,
        }
        super().__init__(422, f"Transition '{target}' not allowed; available: {available}")


def parse_jira_duration(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        secs = int(value)
        if secs < 0:
            raise ValueError("Duration cannot be negative")
        return secs
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text) * 60
    tokens = _DURATION_TOKEN_RE.findall(text)
    if not tokens:
        raise ValueError(f"Invalid Jira duration: {value!r}")
    reconstructed = _DURATION_TOKEN_RE.sub("", text).strip()
    if reconstructed:
        raise ValueError(f"Invalid Jira duration: {value!r}")
    total = 0
    for num_str, unit in tokens:
        total += int(num_str) * _DURATION_MULTIPLIERS[unit.lower()]
    return total


def format_jira_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    rem = max(0, int(seconds))
    if rem == 0:
        return "0m"
    parts: list[str] = []
    for unit in ("w", "d", "h", "m", "s"):
        mult = _DURATION_MULTIPLIERS[unit]
        if rem >= mult:
            qty, rem = divmod(rem, mult)
            parts.append(f"{qty}{unit}")
    return " ".join(parts)


def canonical_link(source_key: str, target_key: str, link_type: str) -> tuple[str, str, str, str]:
    lt = (link_type or "").strip().lower()
    if lt in LINK_INPUT_MAP:
        type_std, direction = LINK_INPUT_MAP[lt]
    else:
        if "clon" in lt:
            type_std = "Clone"
        else:
            type_std = normalize_link_type(link_type)
        direction = "0" if ("is " in lt and " by" in lt) else "1"
    return source_key, target_key, type_std, direction


def _flipped_direction(type_std: str, direction: str) -> str:
    if type_std == "Relate":
        return direction
    return "0" if direction == "1" else "1"


def _link_verb(type_std: str, direction: str) -> str:
    meta = _LINK_RAW_META.get(type_std)
    if meta:
        return meta["outward"] if direction == "1" else meta["inward"]
    return type_std.lower()


def _adf_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    inner = _adf_text(node.get("content") or [])
    return inner + "\n" if node.get("type") in ("paragraph", "heading", "codeBlock", "listItem") else inner


def _text_to_adf(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    lines = text.splitlines() or [text]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in lines
        ],
    }


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0000"


def _parse_dt(val: datetime | str | None, *, default_tz: str = "UTC") -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=ZoneInfo(default_tz)).astimezone(UTC)
        return val.astimezone(UTC)
    s = str(val).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = _TZ_NO_COLON.sub(r"\1:\2", s)
    # Handle Jira JQL format "YYYY/MM/DD HH:MM"
    s_norm = s.replace("/", "-")
    dt = datetime.fromisoformat(s_norm)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(default_tz))
    return dt.astimezone(UTC)


def _parse_date(val: date | datetime | str | None) -> date | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val).strip()[:10])


def _next_updated_at(issue: Issue, now: datetime | None = None) -> datetime:
    base = now or utcnow()
    if issue.updated_at is not None:
        cur = issue.updated_at if issue.updated_at.tzinfo else issue.updated_at.replace(tzinfo=UTC)
        if base <= cur:
            return cur + timedelta(milliseconds=1)
    return base


def _get_workflow(project: Project | None) -> dict[str, Any]:
    if project is not None:
        if isinstance(project.workflow, dict) and project.workflow.get("statuses") and project.workflow.get("transitions"):
            return project.workflow
        sm = project.status_map
        if isinstance(sm, dict) and isinstance(sm.get("workflow"), dict):
            wf = sm["workflow"]
            if wf.get("statuses") and wf.get("transitions"):
                return wf
    return DEFAULT_WORKFLOW


def _resolve_status_category(status_name: str | None, workflow: dict[str, Any], settings: Settings | None) -> str:
    if settings and status_name and status_name in settings.status_category_overrides:
        return settings.status_category_overrides[status_name]
    needle = (status_name or "").strip().casefold()
    for st in workflow.get("statuses") or []:
        if str(st.get("name") or "").strip().casefold() == needle:
            return str(st.get("category") or "indeterminate")
    return _DEFAULT_CATEGORIES.get(needle, "indeterminate")


def _status_id(status_name: str | None, workflow: dict[str, Any]) -> str | None:
    if not status_name:
        return None
    needle = status_name.strip().casefold()
    for st in workflow.get("statuses") or []:
        if str(st.get("name") or "").strip().casefold() == needle:
            return str(st.get("id") or status_name)
    return status_name


def _user_dict(
    session: Session,
    user_id: str | None,
    display_name: str | None,
    *,
    tz: str = "Asia/Ho_Chi_Minh",
) -> dict[str, Any] | None:
    if not user_id and not display_name:
        return None
    user_obj: User | None = None
    if user_id:
        user_obj = session.execute(select(User).where(User.account_id == user_id)).scalar_one_or_none()
        if user_obj is None and user_id.isdigit():
            user_obj = session.get(User, int(user_id))
    acc_id = (user_obj.account_id if user_obj and user_obj.account_id else user_id) or ""
    name = (user_obj.name if user_obj else None) or display_name or acc_id
    active = bool(getattr(user_obj, "is_active", True)) if user_obj is not None else True
    user_tz = (user_obj.timezone if user_obj and user_obj.timezone else None) or tz
    out: dict[str, Any] = {
        "accountId": acc_id,
        "name": name,
        "displayName": name,
        "active": active,
        "timeZone": user_tz,
    }
    if user_obj is not None and user_obj.avatar_url:
        out["avatarUrls"] = {"48x48": user_obj.avatar_url}
    return out


def _user_dict_from_user(user: User, default_tz: str = "Asia/Ho_Chi_Minh") -> dict[str, Any]:
    acc_id = user.account_id or f"local-{user.id}"
    out: dict[str, Any] = {
        "accountId": acc_id,
        "name": user.name,
        "displayName": user.name,
        "emailAddress": user.email,
        "active": bool(getattr(user, "is_active", True)),
        "timeZone": getattr(user, "timezone", None) or default_tz,
    }
    if getattr(user, "avatar_url", None):
        out["avatarUrls"] = {"48x48": user.avatar_url}
    return out


def _resolve_user_ref(session: Session, ref: Any) -> tuple[str | None, str | None]:
    if ref is None or ref == "" or (isinstance(ref, str) and ref.strip().lower() in ("unassigned", "none", "null")):
        return None, None
    if isinstance(ref, User):
        return ref.account_id or f"local-{ref.id}", ref.name
    if isinstance(ref, dict):
        acc = ref.get("accountId") or ref.get("account_id") or ref.get("id") or ref.get("name")
        disp = ref.get("displayName") or ref.get("name")
        if acc is not None:
            u = session.execute(select(User).where(User.account_id == str(acc))).scalar_one_or_none()
            if u is None and str(acc).isdigit():
                u = session.get(User, int(acc))
            if u is not None:
                return u.account_id or f"local-{u.id}", u.name
            return str(acc), str(disp or acc)
        return None, None
    ref_str = str(ref).strip()
    u = session.execute(select(User).where(User.account_id == ref_str)).scalar_one_or_none()
    if u is None and ref_str.isdigit():
        u = session.get(User, int(ref_str))
    if u is not None:
        return u.account_id or f"local-{u.id}", u.name
    return ref_str, ref_str


def _actor_identity(actor: User | None) -> tuple[str | None, str]:
    if actor is None:
        return None, "System"
    return (actor.account_id or f"local-{actor.id}"), actor.name


def _sprint_dict(sp: Sprint) -> dict[str, Any]:
    return {
        "id": sp.id,
        "name": sp.name,
        "state": sp.state,
        "boardId": sp.board_id,
        "originBoardId": sp.board_id,
        "startDate": _iso_utc(sp.start_at),
        "endDate": _iso_utc(sp.end_at),
        "completeDate": _iso_utc(sp.complete_at),
        "goal": sp.goal or "",
    }


def _version_dict(v: Version) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "name": v.name,
        "description": v.description or "",
        "released": bool(v.released),
        "startDate": v.start_date.isoformat() if v.start_date else None,
        "releaseDate": v.release_date.isoformat() if v.release_date else None,
        "projectId": (zlib.crc32(v.project_key.encode("utf-8")) & 0x7FFFFFFF) or 1 if v.project_key else None,
    }


def _check_optimistic_lock(
    issue: Issue,
    *,
    expected_version: int | None = None,
    expected_updated: datetime | str | None = None,
) -> None:
    if expected_version is not None and (issue.version or 1) != int(expected_version):
        raise LocalJiraConflictError(
            current_version=issue.version,
            expected_version=expected_version,
            current_updated=issue.updated_at,
            expected_updated=expected_updated,
        )
    if expected_updated is not None:
        exp_utc = _parse_dt(expected_updated)
        if issue.updated_at is None or exp_utc is None:
            raise LocalJiraConflictError(
                current_version=issue.version,
                expected_version=expected_version,
                current_updated=issue.updated_at,
                expected_updated=expected_updated,
            )
        cur_utc = issue.updated_at if issue.updated_at.tzinfo else issue.updated_at.replace(tzinfo=UTC)
        if _iso_utc(cur_utc) != _iso_utc(exp_utc):
            raise LocalJiraConflictError(
                current_version=issue.version,
                expected_version=expected_version,
                current_updated=cur_utc,
                expected_updated=exp_utc,
            )


def _load_project(session: Session, key: str) -> Project:
    project = session.get(Project, key)
    if project is None:
        raise JiraError(404, f"Project {key} not found")
    return project


def _load_live_issue(session: Session, key: str) -> Issue:
    issue = session.get(Issue, key)
    if issue is None or issue.deleted_at is not None:
        raise JiraError(404, f"Issue {key} not found")
    return issue


def _touch_issue(session: Session, issue: Issue, settings: Settings | None, now: datetime | None = None) -> datetime:
    stamped = _next_updated_at(issue, now)
    issue.updated_at = stamped
    issue.version = (issue.version or 1) + 1
    session.flush()
    issue.raw = LocalJiraService.build_issue_raw(session, issue, settings)
    session.flush()
    return stamped


def _optional_dt(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return _parse_dt(value)
    except ValueError as exc:
        raise JiraError(400, f"Invalid datetime: {value}") from exc


def _count_for(session: Session, model: type[IssueWatcher] | type[IssueVote], issue_key: str) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(model.issue_key == issue_key)) or 0)


def _can_modify_comment(session: Session, comment: Comment, actor: User | None) -> bool:
    if actor is None:
        return False
    author_id, _name = _actor_identity(actor)
    if comment.author_id and author_id and comment.author_id == author_id:
        return True
    issue = session.get(Issue, comment.issue_key)
    if issue is None:
        return False
    role = get_user_project_role(session, actor, issue.project_key)
    return role in {"pm", "admin"}


def _move_attachment_dir(settings: Settings | None, old_key: str, new_key: str) -> None:
    if settings is None:
        return
    root = Path(settings.attachments_dir)
    src = root / old_key
    dst = root / new_key
    if not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        for child in src.iterdir():
            child.replace(dst / child.name)
        src.rmdir()
        return
    src.rename(dst)


class LocalJiraService:
    """Transactional SQLite-backed Jira engine sharing caller Session when provided."""

    @staticmethod
    def next_issue_key(session: Session, project_key: str) -> str:
        project = session.get(Project, project_key)
        if project is None:
            raise JiraError(404, f"Project {project_key} not found")
        max_existing = 0
        prefix = f"{project_key}-"
        for k in session.scalars(select(Issue.key).where(Issue.project_key == project_key)).all():
            if k.startswith(prefix):
                tail = k[len(prefix) :]
                if tail.isdigit():
                    max_existing = max(max_existing, int(tail))
        next_num = max(int(project.issue_seq or 0), max_existing) + 1
        project.issue_seq = next_num
        session.flush()
        return f"{project_key}-{next_num}"

    @staticmethod
    def build_issue_raw(session: Session, issue: Issue, settings: Settings | None = None) -> dict[str, Any]:
        tz = settings.tz if settings else "Asia/Ho_Chi_Minh"
        project = session.get(Project, issue.project_key)
        wf = _get_workflow(project)

        sprints = list(
            session.scalars(
                select(Sprint)
                .join(IssueSprint, IssueSprint.sprint_id == Sprint.id)
                .where(IssueSprint.issue_key == issue.key)
                .order_by(Sprint.id.asc())
            ).all()
        )
        fix_versions = list(
            session.scalars(
                select(Version)
                .join(IssueVersion, IssueVersion.version_id == Version.id)
                .where(IssueVersion.issue_key == issue.key, IssueVersion.relation_type == "fix")
                .order_by(Version.id.asc())
            ).all()
        )
        affects_versions = list(
            session.scalars(
                select(Version)
                .join(IssueVersion, IssueVersion.version_id == Version.id)
                .where(IssueVersion.issue_key == issue.key, IssueVersion.relation_type == "affects")
                .order_by(Version.id.asc())
            ).all()
        )
        components = list(
            session.scalars(
                select(Component)
                .join(IssueComponent, IssueComponent.component_id == Component.id)
                .where(IssueComponent.issue_key == issue.key)
                .order_by(Component.id.asc())
            ).all()
        )
        comments = list(
            session.scalars(
                select(Comment)
                .where(Comment.issue_key == issue.key, Comment.deleted_at.is_(None))
                .order_by(Comment.created_at.asc(), Comment.id.asc())
            ).all()
        )
        links = list(
            session.scalars(
                select(Link).where((Link.source_key == issue.key) | (Link.target_key == issue.key))
            ).all()
        )
        changes = list(
            session.scalars(
                select(Change)
                .where(Change.issue_key == issue.key)
                .order_by(Change.at.asc(), Change.idx.asc(), Change.id.asc())
            ).all()
        )
        subtasks = list(
            session.scalars(
                select(Issue)
                .where(
                    Issue.parent_key == issue.key,
                    Issue.issuetype == "Sub-task",
                    Issue.deleted_at.is_(None),
                )
                .order_by(Issue.rank.asc(), Issue.key.asc())
            ).all()
        )
        watch_count = int(
            session.scalar(select(func.count()).select_from(IssueWatcher).where(IssueWatcher.issue_key == issue.key)) or 0
        )
        vote_count = int(
            session.scalar(select(func.count()).select_from(IssueVote).where(IssueVote.issue_key == issue.key)) or 0
        )

        comment_dicts = [
            {
                "id": str(c.id),
                "author": _user_dict(session, c.author_id, c.author_name, tz=tz),
                "updateAuthor": _user_dict(session, c.author_id, c.author_name, tz=tz),
                "body": c.body,
                "created": _iso_utc(c.created_at),
                "updated": _iso_utc(c.updated_at),
            }
            for c in comments
        ]

        issuelinks: list[dict[str, Any]] = []
        for idx, lk in enumerate(links):
            if lk.source_key == issue.key:
                other_key = lk.target_key
                is_outward = lk.direction == "1"
            else:
                other_key = lk.source_key
                is_outward = lk.direction == "0"
            other = session.get(Issue, other_key)
            if other is not None and other.deleted_at is not None:
                continue
            type_meta = _LINK_RAW_META.get(
                lk.type_std,
                {"name": lk.type_std, "inward": lk.type_std.lower(), "outward": lk.type_std.lower()},
            )
            other_obj: dict[str, Any] = {"key": other_key}
            if other is not None:
                other_obj["fields"] = {
                    "summary": other.summary,
                    "status": {
                        "name": other.status,
                        "statusCategory": {"key": other.status_category},
                    },
                    "issuetype": {"name": other.issuetype} if other.issuetype else None,
                    "priority": {"name": other.priority} if other.priority else None,
                }
            entry: dict[str, Any] = {
                "id": f"{issue.key}-{other_key}-{lk.type_std}-{idx}",
                "type": dict(type_meta),
            }
            if is_outward:
                entry["outwardIssue"] = other_obj
            else:
                entry["inwardIssue"] = other_obj
            issuelinks.append(entry)

        timetracking: dict[str, Any] = {}
        if issue.original_estimate_seconds is not None:
            timetracking["originalEstimate"] = format_jira_duration(issue.original_estimate_seconds)
            timetracking["originalEstimateSeconds"] = issue.original_estimate_seconds
        if issue.remaining_estimate_seconds is not None:
            timetracking["remainingEstimate"] = format_jira_duration(issue.remaining_estimate_seconds)
            timetracking["remainingEstimateSeconds"] = issue.remaining_estimate_seconds
        if issue.time_spent_seconds:
            timetracking["timeSpent"] = format_jira_duration(issue.time_spent_seconds)
            timetracking["timeSpentSeconds"] = issue.time_spent_seconds

        parent_obj: dict[str, Any] | None = None
        if issue.parent_key:
            p_issue = session.get(Issue, issue.parent_key)
            parent_obj = {
                "key": issue.parent_key,
                "fields": {
                    "summary": p_issue.summary if p_issue else "",
                    "issuetype": {"name": p_issue.issuetype} if p_issue and p_issue.issuetype else None,
                    "status": {"name": p_issue.status} if p_issue and p_issue.status else None,
                },
            }

        subtask_objs = [
            {
                "key": st.key,
                "fields": {
                    "summary": st.summary,
                    "status": {"name": st.status, "statusCategory": {"key": st.status_category}},
                    "issuetype": {"name": st.issuetype or "Sub-task"},
                },
            }
            for st in subtasks
        ]

        sprint_list = [_sprint_dict(sp) for sp in sprints]
        sprint_field = settings.jira_sprint_field if settings else "customfield_10020"
        sp_field = settings.jira_story_points_field if settings else "customfield_10016"

        fields: dict[str, Any] = {
            "project": {"key": issue.project_key, "name": project.name if project else issue.project_key},
            "summary": issue.summary or "",
            "description": _text_to_adf(issue.description),
            "environment": _text_to_adf(issue.environment),
            "issuetype": {"name": issue.issuetype} if issue.issuetype else None,
            "priority": {"name": issue.priority} if issue.priority else None,
            "status": {
                "id": _status_id(issue.status, wf),
                "name": issue.status,
                "statusCategory": {"key": issue.status_category},
            }
            if issue.status
            else None,
            "resolution": {"name": issue.resolution} if issue.resolution else None,
            "assignee": _user_dict(session, issue.assignee_id, issue.assignee_name, tz=tz),
            "reporter": _user_dict(session, issue.reporter_id, issue.reporter_name, tz=tz),
            "creator": _user_dict(session, issue.creator_id, issue.creator_name, tz=tz),
            "created": _iso_utc(issue.created_at),
            "updated": _iso_utc(issue.updated_at),
            "resolutiondate": _iso_utc(issue.resolved_at),
            "duedate": issue.duedate.isoformat() if issue.duedate else None,
            "labels": list(issue.labels or []),
            "components": [{"id": str(c.id), "name": c.name} for c in components],
            "fixVersions": [_version_dict(v) for v in fix_versions],
            "versions": [_version_dict(v) for v in affects_versions],
            "issuelinks": issuelinks,
            "timetracking": timetracking,
            "timeoriginalestimate": issue.original_estimate_seconds,
            "timeestimate": issue.remaining_estimate_seconds,
            "timespent": issue.time_spent_seconds or None,
            "parent": parent_obj,
            "subtasks": subtask_objs,
            "watches": {"watchCount": watch_count, "isWatching": False},
            "votes": {"votes": vote_count, "hasVoted": False},
            "comment": {
                "comments": comment_dicts,
                "startAt": 0,
                "maxResults": len(comment_dicts),
                "total": len(comment_dicts),
            },
            "customfield_10016": issue.story_points,
            "customfield_10020": sprint_list,
        }
        fields[sp_field] = issue.story_points
        fields[sprint_field] = sprint_list

        histories: list[dict[str, Any]] = []
        grouped: dict[str, list[Change]] = {}
        order: list[str] = []
        for ch in changes:
            if ch.change_id not in grouped:
                grouped[ch.change_id] = []
                order.append(ch.change_id)
            grouped[ch.change_id].append(ch)
        for cid in order:
            grp = grouped[cid]
            first = grp[0]
            author = _user_dict(session, first.author_id, first.author_name, tz=tz) or {
                "accountId": "local-system",
                "name": "System",
                "displayName": "System",
                "active": True,
                "timeZone": tz,
            }
            histories.append(
                {
                    "id": cid,
                    "author": author,
                    "created": _iso_utc(first.at),
                    "items": [
                        {
                            "field": c.field,
                            "fieldtype": "custom" if c.field == "sprint" else "jira",
                            "from": c.from_val,
                            "fromString": c.from_str,
                            "to": c.to_val,
                            "toString": c.to_str,
                        }
                        for c in grp
                    ],
                }
            )

        numeric_id = (zlib.crc32(issue.key.encode("utf-8")) & 0x7FFFFFFF) or 1
        return {
            "id": str(numeric_id),
            "key": issue.key,
            "self": f"local://rest/api/3/issue/{issue.key}",
            "fields": fields,
            "changelog": {
                "startAt": 0,
                "maxResults": len(histories),
                "total": len(histories),
                "histories": histories,
            },
        }

    @staticmethod
    def evaluate_with_neighbors(
        session: Session,
        keys: list[str] | set[str],
        now: datetime,
        settings: Settings | None,
        *,
        is_new: bool = False,
        status_changed: bool = False,
    ) -> list[Any]:
        from erw.pipeline import evaluate as ev

        s = settings or Settings(_env_file=None)
        if status_changed:
            ev.clear_stats_cache()

        target_keys = sorted(set(keys))
        changes = []
        for k in target_keys:
            issue = session.get(Issue, k)
            if issue is None or issue.deleted_at is not None:
                rs = session.get(RiskState, k)
                if rs is not None:
                    session.delete(rs)
                continue
            ch = ev.evaluate_issue(session, k, now, s, is_new=is_new)
            if ch is not None:
                changes.append(ch)

        if target_keys:
            linked_rows = session.execute(
                select(Link.source_key, Link.target_key).where(
                    Link.type_std.in_(["Block", "Depend"]),
                    or_(Link.source_key.in_(target_keys), Link.target_key.in_(target_keys)),
                )
            ).all()
            dep_keys: set[str] = set()
            key_set = set(target_keys)
            for src, tgt in linked_rows:
                if src not in key_set:
                    dep_keys.add(src)
                if tgt not in key_set:
                    dep_keys.add(tgt)
            for dk in sorted(dep_keys):
                dep_issue = session.get(Issue, dk)
                if dep_issue is not None and dep_issue.deleted_at is None:
                    ch = ev.evaluate_issue(session, dk, now, s, is_new=False)
                    if ch is not None:
                        changes.append(ch)

        if ev._dispatch is not None and changes:
            ev._dispatch(session, changes, now, s)
        session.flush()
        return changes

    @staticmethod
    def get_transitions(session: Session, key: str, *, settings: Settings | None = None) -> list[Transition]:
        issue = session.get(Issue, key)
        if issue is None or issue.deleted_at is not None:
            raise JiraError(404, f"Issue {key} not found")
        project = session.get(Project, issue.project_key)
        wf = _get_workflow(project)
        cur = (issue.status or "").strip().casefold()
        known_statuses = {str(s.get("name") or "").strip().casefold() for s in wf.get("statuses") or []}

        transitions_spec = wf.get("transitions") or []
        if cur in known_statuses:
            matched = [
                t
                for t in transitions_spec
                if "*" in (t.get("from") or [])
                or cur in {str(f).strip().casefold() for f in (t.get("from") or [])}
            ]
        elif issue.status_category == "done":
            matched = [
                t
                for t in transitions_spec
                if "done" in {str(f).strip().casefold() for f in (t.get("from") or [])}
            ]
        else:
            matched = [
                t
                for t in transitions_spec
                if str(t.get("to") or "").strip().casefold() != "reopened"
            ]

        return [
            Transition(
                id=str(t["id"]),
                name=str(t.get("name") or ""),
                to_status=str(t.get("to") or ""),
                to_category=_resolve_status_category(t.get("to"), wf, settings),
            )
            for t in matched
        ]

    @staticmethod
    def create_issue(
        session: Session,
        *,
        project_key: str,
        summary: str,
        issuetype: str = "Task",
        priority: str = "Medium",
        description: str = "",
        environment: str = "",
        parent_key: str | None = None,
        assignee: Any = None,
        reporter: Any = None,
        creator: Any = None,
        duedate: date | str | None = None,
        start_date: date | str | None = None,
        story_points: float | None = None,
        original_estimate_seconds: int | None = None,
        remaining_estimate_seconds: int | None = None,
        labels: list[str] | None = None,
        sprint_ids: list[int] | None = None,
        fix_version_ids: list[int] | None = None,
        affects_version_ids: list[int] | None = None,
        component_ids: list[int] | None = None,
        status: str | None = None,
        rank: float | None = None,
        created_at: datetime | None = None,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Issue:
        project = session.get(Project, project_key)
        if project is None:
            raise JiraError(404, f"Project {project_key} not found")
        clean_summary = (summary or "").strip()
        if not clean_summary:
            raise JiraError(400, "Summary is required")

        due_d = _parse_date(duedate)
        start_d = _parse_date(start_date)
        if start_d and due_d and start_d > due_d:
            raise JiraError(422, "start_date cannot be after duedate")

        if parent_key:
            parent = session.get(Issue, parent_key)
            if parent is None or parent.deleted_at is not None:
                raise JiraError(404, f"Parent issue {parent_key} not found")
            if issuetype == "Sub-task":
                if parent.project_key != project_key:
                    raise JiraError(422, "Sub-task parent must belong to the same project")
                if parent.issuetype == "Sub-task":
                    raise JiraError(422, "Sub-task cannot be parented to another Sub-task")
            else:
                if parent.issuetype != "Epic":
                    raise JiraError(422, "Non-subtask parent_key must reference an Epic")

        wf = _get_workflow(project)
        init_status = status
        if not init_status:
            new_statuses = [s["name"] for s in wf.get("statuses") or [] if s.get("category") == "new"]
            init_status = new_statuses[0] if new_statuses else "To Do"
        init_cat = _resolve_status_category(init_status, wf, settings)

        key = LocalJiraService.next_issue_key(session, project_key)
        now = created_at or utcnow()
        if rank is None:
            max_rank = session.scalar(
                select(func.coalesce(func.max(Issue.rank), 0.0)).where(Issue.project_key == project_key)
            )
            rank = float(max_rank or 0.0) + 1000.0

        assignee_id, assignee_name = _resolve_user_ref(session, assignee)
        if reporter is not None:
            reporter_id, reporter_name = _resolve_user_ref(session, reporter)
        elif actor is not None:
            reporter_id, reporter_name = _resolve_user_ref(session, actor)
        else:
            reporter_id, reporter_name = None, None

        if creator is not None:
            creator_id, creator_name = _resolve_user_ref(session, creator)
        elif actor is not None:
            creator_id, creator_name = _resolve_user_ref(session, actor)
        else:
            creator_id, creator_name = reporter_id, reporter_name

        rem_est = remaining_estimate_seconds
        if original_estimate_seconds is not None and rem_est is None:
            rem_est = original_estimate_seconds

        issue = Issue(
            key=key,
            project_key=project_key,
            parent_key=parent_key,
            summary=clean_summary,
            description=description or "",
            environment=environment or "",
            issuetype=issuetype,
            priority=priority,
            priority_norm=normalize_priority(priority),
            status=init_status,
            status_category=init_cat,
            resolution="Done" if init_cat == "done" else None,
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            reporter_id=reporter_id,
            reporter_name=reporter_name,
            creator_id=creator_id,
            creator_name=creator_name,
            start_date=start_d,
            duedate=due_d,
            story_points=float(story_points) if story_points is not None else None,
            rank=float(rank),
            original_estimate_seconds=original_estimate_seconds,
            remaining_estimate_seconds=rem_est,
            time_spent_seconds=0,
            labels=list(labels or []),
            version=1,
            created_at=now,
            updated_at=now,
            resolved_at=now if init_cat == "done" else None,
        )
        session.add(issue)
        session.flush()

        for sid in dict.fromkeys(sprint_ids or []):
            if session.get(Sprint, int(sid)) is not None:
                session.add(IssueSprint(issue_key=key, sprint_id=int(sid)))
        for vid in dict.fromkeys(fix_version_ids or []):
            if session.get(Version, int(vid)) is not None:
                session.add(IssueVersion(issue_key=key, version_id=int(vid), relation_type="fix"))
        for vid in dict.fromkeys(affects_version_ids or []):
            if session.get(Version, int(vid)) is not None:
                session.add(IssueVersion(issue_key=key, version_id=int(vid), relation_type="affects"))
        for cid in dict.fromkeys(component_ids or []):
            if session.get(Component, int(cid)) is not None:
                session.add(IssueComponent(issue_key=key, component_id=int(cid)))
        session.flush()

        issue.raw = LocalJiraService.build_issue_raw(session, issue, settings)
        session.flush()
        LocalJiraService.evaluate_with_neighbors(session, [key], now, settings, is_new=True)
        return issue

    @staticmethod
    def update_issue(
        session: Session,
        key: str,
        fields: dict[str, Any],
        *,
        actor: User | None = None,
        settings: Settings | None = None,
        expected_version: int | None = None,
        expected_updated: datetime | str | None = None,
    ) -> Issue:
        issue = session.get(Issue, key)
        if issue is None or issue.deleted_at is not None:
            raise JiraError(404, f"Issue {key} not found")
        _check_optimistic_lock(
            issue,
            expected_version=expected_version,
            expected_updated=expected_updated,
        )

        now = _next_updated_at(issue)
        author_id, author_name = _actor_identity(actor)
        change_id = f"loc-{uuid.uuid4().hex[:12]}"
        pending_changes: list[tuple[str, str | None, str | None, str | None, str | None]] = []
        mutated = False

        sp_field = settings.jira_story_points_field if settings else "customfield_10016"
        sprint_field = settings.jira_sprint_field if settings else "customfield_10020"

        if "summary" in fields:
            new_sum = (fields["summary"] or "").strip()
            if not new_sum:
                raise JiraError(400, "Summary cannot be empty")
            if new_sum != issue.summary:
                pending_changes.append(("summary", issue.summary, new_sum, issue.summary, new_sum))
                issue.summary = new_sum
                mutated = True

        if "description" in fields:
            raw_desc = fields["description"]
            new_desc = _adf_text(raw_desc).strip() if isinstance(raw_desc, (dict, list)) else str(raw_desc or "")
            if new_desc != (issue.description or ""):
                pending_changes.append(
                    ("description", issue.description or None, new_desc or None, issue.description or None, new_desc or None)
                )
                issue.description = new_desc
                mutated = True

        if "environment" in fields:
            raw_env = fields["environment"]
            new_env = _adf_text(raw_env).strip() if isinstance(raw_env, (dict, list)) else str(raw_env or "")
            if new_env != (issue.environment or ""):
                pending_changes.append(
                    ("environment", issue.environment or None, new_env or None, issue.environment or None, new_env or None)
                )
                issue.environment = new_env
                mutated = True

        if "issuetype" in fields:
            raw_it = fields["issuetype"]
            new_it = raw_it.get("name") if isinstance(raw_it, dict) else raw_it
            if new_it != issue.issuetype:
                pending_changes.append(("issuetype", issue.issuetype, new_it, issue.issuetype, new_it))
                issue.issuetype = new_it
                mutated = True

        if "priority" in fields:
            raw_pri = fields["priority"]
            new_pri = raw_pri.get("name") if isinstance(raw_pri, dict) else raw_pri
            if new_pri != issue.priority:
                pending_changes.append(("priority", issue.priority, new_pri, issue.priority, new_pri))
                issue.priority = new_pri
                issue.priority_norm = normalize_priority(new_pri)
                mutated = True

        if "resolution" in fields:
            raw_res = fields["resolution"]
            new_res = raw_res.get("name") if isinstance(raw_res, dict) else raw_res
            if new_res != issue.resolution:
                pending_changes.append(("resolution", issue.resolution, new_res, issue.resolution, new_res))
                issue.resolution = new_res
                mutated = True

        if "assignee" in fields or "assignee_id" in fields:
            ref = fields["assignee"] if "assignee" in fields else fields["assignee_id"]
            new_id, new_name = _resolve_user_ref(session, ref)
            if new_id != issue.assignee_id or new_name != issue.assignee_name:
                pending_changes.append(
                    ("assignee", issue.assignee_id, new_id, issue.assignee_name, new_name)
                )
                issue.assignee_id = new_id
                issue.assignee_name = new_name
                mutated = True

        if "reporter" in fields or "reporter_id" in fields:
            ref = fields["reporter"] if "reporter" in fields else fields["reporter_id"]
            new_id, new_name = _resolve_user_ref(session, ref)
            if new_id != issue.reporter_id or new_name != issue.reporter_name:
                pending_changes.append(
                    ("reporter", issue.reporter_id, new_id, issue.reporter_name, new_name)
                )
                issue.reporter_id = new_id
                issue.reporter_name = new_name
                mutated = True

        if "parent_key" in fields or "parent" in fields:
            raw_p = fields["parent_key"] if "parent_key" in fields else fields["parent"]
            new_parent = raw_p.get("key") if isinstance(raw_p, dict) else raw_p
            if new_parent != issue.parent_key:
                if new_parent == key:
                    raise JiraError(422, "Issue cannot be its own parent")
                if new_parent:
                    p_obj = session.get(Issue, new_parent)
                    if p_obj is None or p_obj.deleted_at is not None:
                        raise JiraError(404, f"Parent issue {new_parent} not found")
                pending_changes.append(("parent", issue.parent_key, new_parent, issue.parent_key, new_parent))
                issue.parent_key = new_parent
                mutated = True

        new_start = issue.start_date
        new_due = issue.duedate
        start_changed = False
        due_changed = False
        if "start_date" in fields:
            try:
                new_start = _parse_date(fields["start_date"])
            except ValueError as e:
                raise JiraError(400, f"Invalid start_date: {e}") from e
            start_changed = new_start != issue.start_date
        if "duedate" in fields:
            try:
                new_due = _parse_date(fields["duedate"])
            except ValueError as e:
                raise JiraError(400, f"Invalid duedate: {e}") from e
            due_changed = new_due != issue.duedate
        if new_start and new_due and new_start > new_due:
            raise JiraError(422, "start_date cannot be after duedate")
        if start_changed:
            old_s = issue.start_date.isoformat() if issue.start_date else None
            new_s = new_start.isoformat() if new_start else None
            pending_changes.append(("start_date", old_s, new_s, old_s, new_s))
            issue.start_date = new_start
            mutated = True
        if due_changed:
            old_d = issue.duedate.isoformat() if issue.duedate else None
            new_d = new_due.isoformat() if new_due else None
            pending_changes.append(("duedate", old_d, new_d, old_d, new_d))
            issue.duedate = new_due
            mutated = True

        sp_key = "story_points" if "story_points" in fields else (sp_field if sp_field in fields else ("customfield_10016" if "customfield_10016" in fields else None))
        if sp_key is not None:
            raw_sp = fields[sp_key]
            new_sp = float(raw_sp) if raw_sp is not None else None
            if new_sp != issue.story_points:
                old_s = str(issue.story_points) if issue.story_points is not None else None
                new_s = str(new_sp) if new_sp is not None else None
                pending_changes.append(("story_points", old_s, new_s, old_s, new_s))
                issue.story_points = new_sp
                mutated = True

        if "rank" in fields and fields["rank"] is not None:
            new_rank = float(fields["rank"])
            if new_rank != issue.rank:
                issue.rank = new_rank
                mutated = True

        if "original_estimate_seconds" in fields or "original_estimate" in fields:
            raw_oe = fields["original_estimate_seconds"] if "original_estimate_seconds" in fields else fields["original_estimate"]
            try:
                new_oe = parse_jira_duration(raw_oe)
            except ValueError as e:
                raise JiraError(400, str(e)) from e
            if new_oe != issue.original_estimate_seconds:
                pending_changes.append(
                    (
                        "original_estimate",
                        str(issue.original_estimate_seconds) if issue.original_estimate_seconds is not None else None,
                        str(new_oe) if new_oe is not None else None,
                        format_jira_duration(issue.original_estimate_seconds),
                        format_jira_duration(new_oe),
                    )
                )
                issue.original_estimate_seconds = new_oe
                mutated = True

        if "remaining_estimate_seconds" in fields or "remaining_estimate" in fields:
            raw_re = fields["remaining_estimate_seconds"] if "remaining_estimate_seconds" in fields else fields["remaining_estimate"]
            try:
                new_re = parse_jira_duration(raw_re)
            except ValueError as e:
                raise JiraError(400, str(e)) from e
            if new_re != issue.remaining_estimate_seconds:
                pending_changes.append(
                    (
                        "remaining_estimate",
                        str(issue.remaining_estimate_seconds) if issue.remaining_estimate_seconds is not None else None,
                        str(new_re) if new_re is not None else None,
                        format_jira_duration(issue.remaining_estimate_seconds),
                        format_jira_duration(new_re),
                    )
                )
                issue.remaining_estimate_seconds = new_re
                mutated = True

        if "labels" in fields:
            new_labels = [str(x).strip() for x in (fields["labels"] or []) if str(x).strip()]
            old_labels = list(issue.labels or [])
            if new_labels != old_labels:
                old_str = " ".join(sorted(old_labels)) or None
                new_str = " ".join(sorted(new_labels)) or None
                pending_changes.append(("labels", old_str, new_str, old_str, new_str))
                issue.labels = new_labels
                mutated = True

        sprint_input_key = (
            "sprint_ids"
            if "sprint_ids" in fields
            else (sprint_field if sprint_field in fields else ("customfield_10020" if "customfield_10020" in fields else None))
        )
        if sprint_input_key is not None:
            raw_sprints = fields[sprint_input_key] or []
            new_sids: list[int] = []
            for item in raw_sprints:
                sid = int(item["id"]) if isinstance(item, dict) else int(item)
                if sid not in new_sids:
                    new_sids.append(sid)
            old_sprints = list(
                session.scalars(
                    select(Sprint).join(IssueSprint, IssueSprint.sprint_id == Sprint.id).where(IssueSprint.issue_key == key).order_by(Sprint.id.asc())
                ).all()
            )
            old_sids = [s.id for s in old_sprints]
            if sorted(new_sids) != sorted(old_sids):
                new_sprints = [session.get(Sprint, sid) for sid in new_sids]
                new_sprints = [s for s in new_sprints if s is not None]
                old_id_s = ", ".join(str(s.id) for s in old_sprints)
                new_id_s = ", ".join(str(s.id) for s in new_sprints)
                old_nm_s = ", ".join(s.name or str(s.id) for s in old_sprints)
                new_nm_s = ", ".join(s.name or str(s.id) for s in new_sprints)
                pending_changes.append(("sprint", old_id_s, new_id_s, old_nm_s, new_nm_s))
                session.execute(delete(IssueSprint).where(IssueSprint.issue_key == key))
                session.add_all(IssueSprint(issue_key=key, sprint_id=s.id) for s in new_sprints)
                mutated = True

        if "fix_version_ids" in fields:
            new_vids = list(dict.fromkeys(int(x) for x in (fields["fix_version_ids"] or [])))
            old_vers = list(
                session.scalars(
                    select(Version)
                    .join(IssueVersion, IssueVersion.version_id == Version.id)
                    .where(IssueVersion.issue_key == key, IssueVersion.relation_type == "fix")
                    .order_by(Version.id.asc())
                ).all()
            )
            if sorted(new_vids) != sorted(v.id for v in old_vers):
                new_vers = [v for vid in new_vids if (v := session.get(Version, vid)) is not None]
                pending_changes.append(
                    (
                        "fix_versions",
                        ", ".join(str(v.id) for v in old_vers) or None,
                        ", ".join(str(v.id) for v in new_vers) or None,
                        ", ".join(v.name or str(v.id) for v in old_vers) or None,
                        ", ".join(v.name or str(v.id) for v in new_vers) or None,
                    )
                )
                session.execute(
                    delete(IssueVersion).where(IssueVersion.issue_key == key, IssueVersion.relation_type == "fix")
                )
                session.add_all(IssueVersion(issue_key=key, version_id=v.id, relation_type="fix") for v in new_vers)
                mutated = True

        if "affects_version_ids" in fields:
            new_vids = list(dict.fromkeys(int(x) for x in (fields["affects_version_ids"] or [])))
            old_vers = list(
                session.scalars(
                    select(Version)
                    .join(IssueVersion, IssueVersion.version_id == Version.id)
                    .where(IssueVersion.issue_key == key, IssueVersion.relation_type == "affects")
                    .order_by(Version.id.asc())
                ).all()
            )
            if sorted(new_vids) != sorted(v.id for v in old_vers):
                new_vers = [v for vid in new_vids if (v := session.get(Version, vid)) is not None]
                pending_changes.append(
                    (
                        "affects_versions",
                        ", ".join(str(v.id) for v in old_vers) or None,
                        ", ".join(str(v.id) for v in new_vers) or None,
                        ", ".join(v.name or str(v.id) for v in old_vers) or None,
                        ", ".join(v.name or str(v.id) for v in new_vers) or None,
                    )
                )
                session.execute(
                    delete(IssueVersion).where(IssueVersion.issue_key == key, IssueVersion.relation_type == "affects")
                )
                session.add_all(IssueVersion(issue_key=key, version_id=v.id, relation_type="affects") for v in new_vers)
                mutated = True

        if "component_ids" in fields:
            new_cids = list(dict.fromkeys(int(x) for x in (fields["component_ids"] or [])))
            old_comps = list(
                session.scalars(
                    select(Component)
                    .join(IssueComponent, IssueComponent.component_id == Component.id)
                    .where(IssueComponent.issue_key == key)
                    .order_by(Component.id.asc())
                ).all()
            )
            if sorted(new_cids) != sorted(c.id for c in old_comps):
                new_comps = [c for cid in new_cids if (c := session.get(Component, cid)) is not None]
                pending_changes.append(
                    (
                        "components",
                        ", ".join(str(c.id) for c in old_comps) or None,
                        ", ".join(str(c.id) for c in new_comps) or None,
                        ", ".join(c.name for c in old_comps) or None,
                        ", ".join(c.name for c in new_comps) or None,
                    )
                )
                session.execute(delete(IssueComponent).where(IssueComponent.issue_key == key))
                session.add_all(IssueComponent(issue_key=key, component_id=c.id) for c in new_comps)
                mutated = True

        if mutated:
            for idx, (fld, fv, tv, fs, ts) in enumerate(pending_changes):
                session.add(
                    Change(
                        issue_key=key,
                        change_id=change_id,
                        idx=idx,
                        at=now,
                        author_id=author_id,
                        author_name=author_name,
                        field=fld,
                        from_val=fv,
                        to_val=tv,
                        from_str=fs,
                        to_str=ts,
                    )
                )
            issue.updated_at = now
            issue.version = (issue.version or 1) + 1
            session.flush()
            issue.raw = LocalJiraService.build_issue_raw(session, issue, settings)
            session.flush()
            LocalJiraService.evaluate_with_neighbors(session, [key], now, settings)
        return issue

    @staticmethod
    def transition_issue(
        session: Session,
        key: str,
        transition_id: str,
        *,
        resolution: str | None = None,
        actor: User | None = None,
        settings: Settings | None = None,
        expected_version: int | None = None,
        expected_updated: datetime | str | None = None,
    ) -> Issue:
        issue = session.get(Issue, key)
        if issue is None or issue.deleted_at is not None:
            raise JiraError(404, f"Issue {key} not found")
        _check_optimistic_lock(
            issue,
            expected_version=expected_version,
            expected_updated=expected_updated,
        )

        allowed = LocalJiraService.get_transitions(session, key, settings=settings)
        chosen = next((t for t in allowed if t.id == str(transition_id)), None)
        if chosen is None:
            raise TransitionNotAllowedError(
                target=str(transition_id),
                available=[t.to_status for t in allowed],
            )

        project = session.get(Project, issue.project_key)
        wf = _get_workflow(project)
        trans_spec = next(
            (t for t in (wf.get("transitions") or []) if str(t.get("id")) == chosen.id),
            {},
        )

        now = _next_updated_at(issue)
        old_status = issue.status
        old_cat = issue.status_category
        old_res = issue.resolution
        old_sid = _status_id(old_status, wf)

        new_status = chosen.to_status
        new_cat = chosen.to_category or _resolve_status_category(new_status, wf, settings)
        new_sid = _status_id(new_status, wf)

        if new_cat == "done":
            if old_cat != "done":
                issue.resolution = resolution or trans_spec.get("auto_resolution") or issue.resolution or "Done"
                issue.resolved_at = now
            else:
                if resolution:
                    issue.resolution = resolution
                if issue.resolved_at is None:
                    issue.resolved_at = now
        elif old_cat == "done" and new_cat != "done":
            issue.resolution = None
            issue.resolved_at = None

        issue.status = new_status
        issue.status_category = new_cat
        issue.updated_at = now
        issue.version = (issue.version or 1) + 1

        author_id, author_name = _actor_identity(actor)
        change_id = f"loc-{uuid.uuid4().hex[:12]}"
        session.add(
            Change(
                issue_key=key,
                change_id=change_id,
                idx=0,
                at=now,
                author_id=author_id,
                author_name=author_name,
                field="status",
                from_val=old_sid,
                to_val=new_sid,
                from_str=old_status,
                to_str=new_status,
            )
        )
        if issue.resolution != old_res:
            session.add(
                Change(
                    issue_key=key,
                    change_id=change_id,
                    idx=1,
                    at=now,
                    author_id=author_id,
                    author_name=author_name,
                    field="resolution",
                    from_val=old_res,
                    to_val=issue.resolution,
                    from_str=old_res,
                    to_str=issue.resolution,
                )
            )
        session.flush()
        issue.raw = LocalJiraService.build_issue_raw(session, issue, settings)
        session.flush()
        LocalJiraService.evaluate_with_neighbors(session, [key], now, settings, status_changed=True)
        return issue

    @staticmethod
    def add_comment(
        session: Session,
        key: str,
        body: str | dict[str, Any],
        *,
        actor: User | None = None,
        settings: Settings | None = None,
        mentions: list[Any] | None = None,
    ) -> Comment:
        issue = session.get(Issue, key)
        if issue is None or issue.deleted_at is not None:
            raise JiraError(404, f"Issue {key} not found")
        text_body = _adf_text(body).strip() if isinstance(body, (dict, list)) else str(body)
        if mentions is None:
            mentions = LocalJiraService.parse_mentions(session, issue.project_key, text_body, actor)
        now = _next_updated_at(issue)
        author_id, author_name = _actor_identity(actor)
        comment = Comment(
            issue_key=key,
            author_id=author_id,
            author_name=author_name if actor else None,
            body=text_body,
            mentions=list(mentions or []),
            created_at=now,
            updated_at=now,
            edited=False,
        )
        session.add(comment)
        issue.updated_at = now
        issue.version = (issue.version or 1) + 1
        session.flush()
        issue.raw = LocalJiraService.build_issue_raw(session, issue, settings)
        session.flush()
        LocalJiraService.evaluate_with_neighbors(session, [key], now, settings)
        return comment

    @staticmethod
    def add_link(
        session: Session,
        source_key: str,
        target_key: str,
        link_type: str,
        *,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Link:
        if source_key == target_key:
            raise JiraError(400, "Cannot link an issue to itself")
        src_issue = session.get(Issue, source_key)
        tgt_issue = session.get(Issue, target_key)
        if src_issue is None or src_issue.deleted_at is not None:
            raise JiraError(404, f"Issue {source_key} not found")
        if tgt_issue is None or tgt_issue.deleted_at is not None:
            raise JiraError(404, f"Issue {target_key} not found")

        src, tgt, type_std, direction = canonical_link(source_key, target_key, link_type)
        flipped = _flipped_direction(type_std, direction)

        existing = session.get(Link, (src, tgt, type_std))
        if existing is not None:
            return existing
        inv = session.get(Link, (tgt, src, type_std))
        if inv is not None and inv.direction == flipped:
            return inv

        link = Link(source_key=src, target_key=tgt, type_std=type_std, direction=direction)
        session.add(link)

        now_src = _next_updated_at(src_issue)
        now_tgt = _next_updated_at(tgt_issue, now_src)
        author_id, author_name = _actor_identity(actor)
        cid_src = f"loc-{uuid.uuid4().hex[:12]}"
        cid_tgt = f"loc-{uuid.uuid4().hex[:12]}"

        verb_src = _link_verb(type_std, direction)
        verb_tgt = _link_verb(type_std, flipped)
        session.add(
            Change(
                issue_key=src,
                change_id=cid_src,
                idx=0,
                at=now_src,
                author_id=author_id,
                author_name=author_name,
                field="link",
                from_val=None,
                to_val=tgt,
                from_str=None,
                to_str=f"This work item {verb_src} {tgt}",
            )
        )
        session.add(
            Change(
                issue_key=tgt,
                change_id=cid_tgt,
                idx=0,
                at=now_tgt,
                author_id=author_id,
                author_name=author_name,
                field="link",
                from_val=None,
                to_val=src,
                from_str=None,
                to_str=f"This work item {verb_tgt} {src}",
            )
        )
        src_issue.updated_at = now_src
        src_issue.version = (src_issue.version or 1) + 1
        tgt_issue.updated_at = now_tgt
        tgt_issue.version = (tgt_issue.version or 1) + 1
        session.flush()

        src_issue.raw = LocalJiraService.build_issue_raw(session, src_issue, settings)
        tgt_issue.raw = LocalJiraService.build_issue_raw(session, tgt_issue, settings)
        session.flush()
        LocalJiraService.evaluate_with_neighbors(session, [src, tgt], max(now_src, now_tgt), settings)
        return link

    @staticmethod
    def delete_link(
        session: Session,
        source_key: str,
        target_key: str,
        link_type: str,
        *,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> bool:
        _, _, type_std, _ = canonical_link(source_key, target_key, link_type)
        candidates = [type_std, link_type]
        link: Link | None = None
        for t in candidates:
            link = session.get(Link, (source_key, target_key, t)) or session.get(Link, (target_key, source_key, t))
            if link is not None:
                break
        if link is None:
            return False

        src = link.source_key
        tgt = link.target_key
        direction = link.direction or "1"
        flipped = _flipped_direction(link.type_std, direction)
        session.delete(link)
        session.flush()

        src_issue = session.get(Issue, src)
        tgt_issue = session.get(Issue, tgt)
        author_id, author_name = _actor_identity(actor)
        now = utcnow()
        affected: list[str] = []

        if src_issue is not None and src_issue.deleted_at is None:
            now_s = _next_updated_at(src_issue, now)
            session.add(
                Change(
                    issue_key=src,
                    change_id=f"loc-{uuid.uuid4().hex[:12]}",
                    idx=0,
                    at=now_s,
                    author_id=author_id,
                    author_name=author_name,
                    field="link",
                    from_val=tgt,
                    to_val=None,
                    from_str=f"This work item {_link_verb(link.type_std, direction)} {tgt}",
                    to_str=None,
                )
            )
            src_issue.updated_at = now_s
            src_issue.version = (src_issue.version or 1) + 1
            session.flush()
            src_issue.raw = LocalJiraService.build_issue_raw(session, src_issue, settings)
            affected.append(src)

        if tgt_issue is not None and tgt_issue.deleted_at is None:
            now_t = _next_updated_at(tgt_issue, now)
            session.add(
                Change(
                    issue_key=tgt,
                    change_id=f"loc-{uuid.uuid4().hex[:12]}",
                    idx=0,
                    at=now_t,
                    author_id=author_id,
                    author_name=author_name,
                    field="link",
                    from_val=src,
                    to_val=None,
                    from_str=f"This work item {_link_verb(link.type_std, flipped)} {src}",
                    to_str=None,
                )
            )
            tgt_issue.updated_at = now_t
            tgt_issue.version = (tgt_issue.version or 1) + 1
            session.flush()
            tgt_issue.raw = LocalJiraService.build_issue_raw(session, tgt_issue, settings)
            affected.append(tgt)

        session.flush()
        if affected:
            LocalJiraService.evaluate_with_neighbors(session, affected, now, settings)
        return True

    @staticmethod
    def soft_delete_issue(
        session: Session,
        key: str,
        *,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> None:
        issue = session.get(Issue, key)
        if issue is None or issue.deleted_at is not None:
            raise JiraError(404, f"Issue {key} not found")
        now = _next_updated_at(issue)
        issue.deleted_at = now
        issue.updated_at = now
        issue.version = (issue.version or 1) + 1
        session.flush()
        LocalJiraService.evaluate_with_neighbors(session, [key], now, settings)

    @staticmethod
    def parse_mentions(
        session: Session,
        project_key: str,
        body: str,
        actor: User | None = None,
    ) -> list[str]:
        tokens = _MENTION_RE.findall(body or "")
        if not tokens:
            return []
        members = session.scalars(
            select(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_key == project_key, User.is_active.is_(True))
        ).all()
        allowed = {member.account_id for member in members if member.account_id}
        if actor is not None and actor.account_id:
            allowed.add(actor.account_id)
        found: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token in allowed and token not in seen:
                seen.add(token)
                found.append(token)
        return found

    @staticmethod
    def update_comment(
        session: Session,
        key: str,
        comment_id: int,
        body: str,
        *,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Comment:
        issue = _load_live_issue(session, key)
        comment = session.get(Comment, int(comment_id))
        if comment is None or comment.issue_key != key or comment.deleted_at is not None:
            raise JiraError(404, "Comment not found")
        if not _can_modify_comment(session, comment, actor):
            raise JiraError(403, "Only the author or a PM can edit this comment")
        text = body if isinstance(body, str) else str(body or "")
        comment.body = text
        comment.mentions = LocalJiraService.parse_mentions(session, issue.project_key, text, actor)
        comment.edited = True
        comment.updated_at = utcnow()
        _touch_issue(session, issue, settings)
        return comment

    @staticmethod
    def delete_comment(
        session: Session,
        key: str,
        comment_id: int,
        *,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> None:
        issue = _load_live_issue(session, key)
        comment = session.get(Comment, int(comment_id))
        if comment is None or comment.issue_key != key or comment.deleted_at is not None:
            raise JiraError(404, "Comment not found")
        if not _can_modify_comment(session, comment, actor):
            raise JiraError(403, "Only the author or a PM can delete this comment")
        comment.deleted_at = utcnow()
        _touch_issue(session, issue, settings)

    @staticmethod
    def list_activity(
        session: Session,
        key: str,
        *,
        kind: str = "all",
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        _load_live_issue(session, key)
        if kind not in {"all", "comments", "history", "worklog"}:
            raise JiraError(400, "Invalid activity kind")
        if order not in {"asc", "desc"}:
            raise JiraError(400, "Invalid activity order")
        rows: list[tuple[datetime, int, dict[str, Any]]] = []
        if kind in {"all", "comments"}:
            comments = session.scalars(
                select(Comment).where(Comment.issue_key == key, Comment.deleted_at.is_(None))
            ).all()
            for comment in comments:
                rows.append(
                    (
                        comment.created_at,
                        comment.id,
                        {
                            "kind": "comment",
                            "id": comment.id,
                            "at": comment.created_at.isoformat(),
                            "author_id": comment.author_id,
                            "author_name": comment.author_name,
                            "body": comment.body,
                            "mentions": list(comment.mentions or []),
                            "edited": bool(comment.edited),
                        },
                    )
                )
        if kind in {"all", "history"}:
            changes = session.scalars(select(Change).where(Change.issue_key == key)).all()
            for change in changes:
                rows.append(
                    (
                        change.at,
                        change.id,
                        {
                            "kind": "history",
                            "id": change.id,
                            "at": change.at.isoformat(),
                            "author_id": change.author_id,
                            "author_name": change.author_name,
                            "field": change.field,
                            "from_str": change.from_str,
                            "to_str": change.to_str,
                        },
                    )
                )
        if kind in {"all", "worklog"}:
            worklogs = session.scalars(select(Worklog).where(Worklog.issue_key == key)).all()
            for worklog in worklogs:
                at = worklog.started_at or worklog.created_at
                rows.append(
                    (
                        at,
                        worklog.id,
                        {
                            "kind": "worklog",
                            "id": worklog.id,
                            "at": at.isoformat(),
                            "author_id": worklog.author_id,
                            "author_name": worklog.author_name,
                            "time_spent_seconds": worklog.time_spent_seconds,
                            "comment": worklog.comment or "",
                        },
                    )
                )
        rows.sort(key=lambda row: (row[0], row[1]), reverse=order == "desc")
        return [item for _at, _id, item in rows]

    @staticmethod
    def add_worklog(
        session: Session,
        key: str,
        time_spent: str | int | float | None,
        *,
        started_at: datetime | str | None = None,
        comment: str | None = None,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Worklog:
        issue = _load_live_issue(session, key)
        try:
            seconds = parse_jira_duration(time_spent)
        except ValueError as exc:
            raise JiraError(400, str(exc)) from exc
        if seconds is None:
            raise JiraError(400, "time_spent is required")
        started = _optional_dt(started_at) or utcnow()
        author_id, author_name = _actor_identity(actor)
        now = utcnow()
        worklog = Worklog(
            issue_key=key,
            author_id=author_id,
            author_name=author_name if actor else None,
            time_spent_seconds=seconds,
            started_at=started,
            comment=comment or "",
            created_at=now,
            updated_at=now,
        )
        session.add(worklog)
        issue.time_spent_seconds = int(issue.time_spent_seconds or 0) + seconds
        if issue.remaining_estimate_seconds is not None:
            issue.remaining_estimate_seconds = max(0, int(issue.remaining_estimate_seconds) - seconds)
        session.flush()
        _touch_issue(session, issue, settings)
        LocalJiraService.evaluate_with_neighbors(session, [key], issue.updated_at or now, settings)
        return worklog

    @staticmethod
    def add_attachment(
        session: Session,
        key: str,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Attachment:
        _load_live_issue(session, key)
        if settings is None:
            raise JiraError(500, "Attachment storage is not configured")
        raw_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
        if not raw_name or raw_name in {".", ".."}:
            raise JiraError(400, "Filename is required")
        directory = Path(settings.attachments_dir) / key
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / raw_name
        if dest.exists():
            stem = Path(raw_name).stem
            suffix = Path(raw_name).suffix
            number = 2
            while dest.exists():
                dest = directory / f"{stem}-{number}{suffix}"
                number += 1
        dest.write_bytes(content or b"")
        author_id, author_name = _actor_identity(actor)
        attachment = Attachment(
            issue_key=key,
            author_id=author_id,
            author_name=author_name if actor else None,
            filename=dest.name,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=len(content or b""),
            storage_path=str(dest.resolve()),
            created_at=utcnow(),
        )
        session.add(attachment)
        session.flush()
        return attachment

    @staticmethod
    def get_attachment(session: Session, key: str, attachment_id: int) -> Attachment:
        _load_live_issue(session, key)
        attachment = session.get(Attachment, int(attachment_id))
        if attachment is None or attachment.issue_key != key:
            raise JiraError(404, "Attachment not found")
        return attachment

    @staticmethod
    def watch_issue(session: Session, key: str, *, actor: User | None) -> int:
        issue = _load_live_issue(session, key)
        if actor is None:
            raise JiraError(400, "Actor is required")
        if session.get(IssueWatcher, (issue.key, actor.id)) is None:
            session.add(IssueWatcher(issue_key=issue.key, user_id=actor.id, created_at=utcnow()))
            session.flush()
        return _count_for(session, IssueWatcher, issue.key)

    @staticmethod
    def unwatch_issue(session: Session, key: str, *, actor: User | None) -> int:
        issue = _load_live_issue(session, key)
        if actor is None:
            raise JiraError(400, "Actor is required")
        row = session.get(IssueWatcher, (issue.key, actor.id))
        if row is not None:
            session.delete(row)
            session.flush()
        return _count_for(session, IssueWatcher, issue.key)

    @staticmethod
    def vote_issue(session: Session, key: str, *, actor: User | None) -> int:
        issue = _load_live_issue(session, key)
        if actor is None:
            raise JiraError(400, "Actor is required")
        if session.get(IssueVote, (issue.key, actor.id)) is None:
            session.add(IssueVote(issue_key=issue.key, user_id=actor.id, created_at=utcnow()))
            session.flush()
        return _count_for(session, IssueVote, issue.key)

    @staticmethod
    def unvote_issue(session: Session, key: str, *, actor: User | None) -> int:
        issue = _load_live_issue(session, key)
        if actor is None:
            raise JiraError(400, "Actor is required")
        row = session.get(IssueVote, (issue.key, actor.id))
        if row is not None:
            session.delete(row)
            session.flush()
        return _count_for(session, IssueVote, issue.key)

    @staticmethod
    def clone_issue(
        session: Session,
        key: str,
        *,
        summary: str | None = None,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Issue:
        source = _load_live_issue(session, key)
        copied = source.summary if summary is None else summary
        return LocalJiraService.create_issue(
            session,
            project_key=source.project_key,
            summary=copied,
            issuetype=source.issuetype or "Task",
            priority=source.priority or "Medium",
            description=source.description or "",
            labels=list(source.labels or []),
            actor=actor,
            settings=settings,
        )

    @staticmethod
    def move_issue(
        session: Session,
        key: str,
        *,
        project_key: str | None = None,
        issuetype: str | None = None,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Issue:
        issue = _load_live_issue(session, key)
        dest = (project_key or issue.project_key).strip()
        if not dest:
            raise JiraError(400, "project_key or issuetype is required")
        if dest == issue.project_key:
            if issuetype is None or issuetype == issue.issuetype:
                if project_key is None and issuetype is None:
                    raise JiraError(400, "project_key or issuetype is required")
                return issue
            return LocalJiraService.update_issue(
                session,
                issue.key,
                {"issuetype": issuetype},
                actor=actor,
                settings=settings,
            )
        target_type = issuetype if issuetype is not None else issue.issuetype
        if issue.issuetype == "Sub-task" or target_type == "Sub-task":
            raise JiraError(422, "Sub-task cannot move to another project")
        child_count = session.scalar(
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.parent_key == issue.key,
                Issue.issuetype == "Sub-task",
                Issue.deleted_at.is_(None),
            )
        )
        if child_count:
            raise JiraError(422, "Issue with sub-tasks cannot move to another project")
        if session.get(Project, dest) is None:
            raise JiraError(404, f"Project {dest} not found")

        new_key = LocalJiraService.next_issue_key(session, dest)
        now = _next_updated_at(issue)
        author_id, author_name = _actor_identity(actor)
        old_key = issue.key
        old_project = issue.project_key
        old_type = issue.issuetype
        payload = {column.name: getattr(issue, column.name) for column in Issue.__table__.columns}
        payload["key"] = new_key
        payload["project_key"] = dest
        payload["issuetype"] = target_type
        payload["updated_at"] = now
        payload["version"] = int(payload.get("version") or 1) + 1
        session.expunge(issue)
        session.execute(insert(Issue).values(**payload))
        for column in _REKEY_ISSUE_COLUMNS:
            session.execute(update(column.class_).where(column == old_key).values({column.key: new_key}))
        session.execute(update(Link).where(Link.source_key == old_key).values(source_key=new_key))
        session.execute(update(Link).where(Link.target_key == old_key).values(target_key=new_key))
        session.execute(update(Issue).where(Issue.parent_key == old_key).values(parent_key=new_key))
        session.execute(delete(Issue).where(Issue.key == old_key))
        session.expire_all()
        moved = session.get(Issue, new_key)
        if moved is None:
            raise JiraError(500, "Moved issue was not saved")
        _move_attachment_dir(settings, old_key, new_key)
        if settings is not None:
            root = Path(settings.attachments_dir).resolve()
            for attachment in session.scalars(select(Attachment).where(Attachment.issue_key == new_key)):
                attachment.storage_path = str(root / new_key / attachment.filename)
        change_id = f"loc-{uuid.uuid4().hex[:12]}"
        history = [("project", old_project, dest), ("key", old_key, new_key)]
        if target_type != old_type:
            history.append(("issuetype", old_type, target_type))
        for idx, (field, frm, to) in enumerate(history):
            session.add(
                Change(
                    issue_key=new_key,
                    change_id=change_id,
                    idx=idx,
                    at=now,
                    author_id=author_id,
                    author_name=author_name,
                    field=field,
                    from_val=frm,
                    to_val=to,
                    from_str=frm,
                    to_str=to,
                )
            )
        session.flush()
        moved.raw = LocalJiraService.build_issue_raw(session, moved, settings)
        session.flush()
        LocalJiraService.evaluate_with_neighbors(session, [new_key], now, settings)
        return moved

    @staticmethod
    def search_issues(
        session: Session,
        *,
        project_key: str,
        q: str | None = None,
        status: str | None = None,
        issuetype: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        sprint_id: int | None = None,
    ) -> list[Issue]:
        _load_project(session, project_key)
        stmt = select(Issue).where(Issue.project_key == project_key, Issue.deleted_at.is_(None))
        if q:
            stmt = stmt.where(func.lower(Issue.summary).like(like_contains(q).lower(), escape="\\"))
        if status:
            stmt = stmt.where(Issue.status == status)
        if issuetype:
            stmt = stmt.where(Issue.issuetype == issuetype)
        if priority:
            stmt = stmt.where(Issue.priority == priority)
        if assignee:
            stmt = stmt.where(or_(Issue.assignee_id == assignee, Issue.assignee_name == assignee))
        if sprint_id is not None:
            stmt = stmt.join(IssueSprint, IssueSprint.issue_key == Issue.key).where(IssueSprint.sprint_id == int(sprint_id))
        stmt = stmt.order_by(Issue.rank.asc(), Issue.key.asc())
        return list(session.scalars(stmt).all())

    @staticmethod
    def create_project(
        session: Session,
        *,
        key: str,
        name: str,
        description: str | None = None,
        actor: User | None = None,
    ) -> Project:
        if actor is None:
            raise JiraError(400, "Actor is required")
        clean_key = (key or "").strip()
        clean_name = (name or "").strip()
        if not clean_key or not clean_name:
            raise JiraError(400, "Project key and name are required")
        if session.get(Project, clean_key) is not None:
            raise JiraError(409, f"Project {clean_key} already exists")
        project = Project(
            key=clean_key,
            name=clean_name,
            description=description or "",
            tracked=True,
            lead_user_id=actor.id,
            issue_seq=0,
            workflow={},
            status_map={},
            thresholds={},
        )
        session.add(project)
        session.add(ProjectMember(project_key=clean_key, user_id=actor.id, role="pm"))
        session.flush()
        return project

    @staticmethod
    def update_project(session: Session, key: str, fields: dict[str, Any]) -> Project:
        project = _load_project(session, key)
        if "name" in fields:
            clean_name = (fields["name"] or "").strip()
            if not clean_name:
                raise JiraError(400, "Project name cannot be empty")
            project.name = clean_name
        if "description" in fields:
            project.description = fields["description"] or ""
        if "lead_user_id" in fields:
            lead_id = fields["lead_user_id"]
            if lead_id is None:
                project.lead_user_id = None
            else:
                if session.get(User, int(lead_id)) is None:
                    raise JiraError(404, "User not found")
                project.lead_user_id = int(lead_id)
        session.flush()
        return project

    @staticmethod
    def list_components(session: Session, project_key: str) -> list[Component]:
        _load_project(session, project_key)
        return list(
            session.scalars(
                select(Component).where(Component.project_key == project_key).order_by(Component.id.asc())
            ).all()
        )

    @staticmethod
    def create_component(
        session: Session,
        project_key: str,
        *,
        name: str,
        description: str | None = None,
        lead_user_id: int | None = None,
    ) -> Component:
        _load_project(session, project_key)
        clean_name = (name or "").strip()
        if not clean_name:
            raise JiraError(400, "Component name is required")
        clash = session.scalar(
            select(Component.id).where(Component.project_key == project_key, Component.name == clean_name)
        )
        if clash is not None:
            raise JiraError(409, "Component name already exists")
        if lead_user_id is not None and session.get(User, int(lead_user_id)) is None:
            raise JiraError(404, "User not found")
        component = Component(
            project_key=project_key,
            name=clean_name,
            description=description or "",
            lead_user_id=int(lead_user_id) if lead_user_id is not None else None,
        )
        session.add(component)
        session.flush()
        return component

    @staticmethod
    def update_component(session: Session, project_key: str, component_id: int, fields: dict[str, Any]) -> Component:
        _load_project(session, project_key)
        component = session.get(Component, int(component_id))
        if component is None or component.project_key != project_key:
            raise JiraError(404, "Component not found")
        if "name" in fields:
            clean_name = (fields["name"] or "").strip()
            if not clean_name:
                raise JiraError(400, "Component name cannot be empty")
            clash = session.scalar(
                select(Component.id).where(
                    Component.project_key == project_key,
                    Component.name == clean_name,
                    Component.id != component.id,
                )
            )
            if clash is not None:
                raise JiraError(409, "Component name already exists")
            component.name = clean_name
        if "description" in fields:
            component.description = fields["description"] or ""
        if "lead_user_id" in fields:
            lead_id = fields["lead_user_id"]
            if lead_id is None:
                component.lead_user_id = None
            else:
                if session.get(User, int(lead_id)) is None:
                    raise JiraError(404, "User not found")
                component.lead_user_id = int(lead_id)
        session.flush()
        return component

    @staticmethod
    def delete_component(session: Session, project_key: str, component_id: int) -> None:
        _load_project(session, project_key)
        component = session.get(Component, int(component_id))
        if component is None or component.project_key != project_key:
            raise JiraError(404, "Component not found")
        session.execute(delete(IssueComponent).where(IssueComponent.component_id == component.id))
        session.delete(component)
        session.flush()

    @staticmethod
    def list_versions(session: Session, project_key: str) -> list[Version]:
        _load_project(session, project_key)
        return list(
            session.scalars(select(Version).where(Version.project_key == project_key).order_by(Version.id.asc())).all()
        )

    @staticmethod
    def create_version(
        session: Session,
        project_key: str,
        *,
        name: str,
        description: str | None = None,
        start_date: date | str | None = None,
        release_date: date | str | None = None,
        released: bool = False,
    ) -> Version:
        _load_project(session, project_key)
        clean_name = (name or "").strip()
        if not clean_name:
            raise JiraError(400, "Version name is required")
        version = Version(
            project_key=project_key,
            name=clean_name,
            description=description or "",
            start_date=_parse_date(start_date),
            release_date=_parse_date(release_date),
            released=bool(released),
        )
        session.add(version)
        session.flush()
        return version

    @staticmethod
    def update_version(session: Session, project_key: str, version_id: int, fields: dict[str, Any]) -> Version:
        _load_project(session, project_key)
        version = session.get(Version, int(version_id))
        if version is None or version.project_key != project_key:
            raise JiraError(404, "Version not found")
        if "name" in fields:
            clean_name = (fields["name"] or "").strip()
            if not clean_name:
                raise JiraError(400, "Version name cannot be empty")
            version.name = clean_name
        if "description" in fields:
            version.description = fields["description"] or ""
        if "start_date" in fields:
            version.start_date = _parse_date(fields["start_date"])
        if "release_date" in fields:
            version.release_date = _parse_date(fields["release_date"])
        if "released" in fields:
            version.released = bool(fields["released"])
        session.flush()
        return version

    @staticmethod
    def get_project_workflow(session: Session, project_key: str) -> dict[str, Any]:
        project = _load_project(session, project_key)
        return copy.deepcopy(_get_workflow(project))

    @staticmethod
    def replace_workflow(session: Session, project_key: str, workflow: dict[str, Any]) -> dict[str, Any]:
        project = _load_project(session, project_key)
        if not isinstance(workflow, dict):
            raise JiraError(400, "Workflow must be an object")
        statuses = workflow.get("statuses")
        transitions = workflow.get("transitions")
        if not isinstance(statuses, list) or not isinstance(transitions, list):
            raise JiraError(400, "Workflow needs statuses and transitions")
        names: set[str] = set()
        for status_row in statuses:
            if not isinstance(status_row, dict) or not str(status_row.get("name") or "").strip():
                raise JiraError(400, "Workflow status needs a name")
            names.add(str(status_row["name"]).strip())
        for transition in transitions:
            if not isinstance(transition, dict):
                raise JiraError(400, "Invalid transition")
            target = str(transition.get("to") or "").strip()
            if target not in names:
                raise JiraError(400, f"Transition references unknown status {target}")
            for source in transition.get("from") or []:
                source_name = str(source).strip()
                if source_name == "*":
                    continue
                if source_name not in names:
                    raise JiraError(400, f"Transition references unknown status {source_name}")
        stored = copy.deepcopy(workflow)
        project.workflow = stored
        session.flush()
        return copy.deepcopy(stored)

    @staticmethod
    def list_sprints(session: Session, project_key: str) -> list[Sprint]:
        _load_project(session, project_key)
        return list(
            session.scalars(select(Sprint).where(Sprint.project_key == project_key).order_by(Sprint.id.asc())).all()
        )

    @staticmethod
    def create_sprint(
        session: Session,
        project_key: str,
        *,
        name: str,
        goal: str | None = None,
        start_at: datetime | str | None = None,
        end_at: datetime | str | None = None,
    ) -> Sprint:
        _load_project(session, project_key)
        clean_name = (name or "").strip()
        if not clean_name:
            raise JiraError(400, "Sprint name is required")
        sprint = Sprint(
            project_key=project_key,
            name=clean_name,
            goal=goal or "",
            state="future",
            board_id=1,
            start_at=_optional_dt(start_at),
            end_at=_optional_dt(end_at),
        )
        session.add(sprint)
        session.flush()
        return sprint

    @staticmethod
    def update_sprint(session: Session, project_key: str, sprint_id: int, fields: dict[str, Any]) -> Sprint:
        _load_project(session, project_key)
        sprint = session.get(Sprint, int(sprint_id))
        if sprint is None or sprint.project_key != project_key:
            raise JiraError(404, "Sprint not found")
        if "name" in fields:
            clean_name = (fields["name"] or "").strip()
            if not clean_name:
                raise JiraError(400, "Sprint name cannot be empty")
            sprint.name = clean_name
        if "goal" in fields:
            sprint.goal = fields["goal"] or ""
        if "start_at" in fields:
            sprint.start_at = _optional_dt(fields["start_at"])
        if "end_at" in fields:
            sprint.end_at = _optional_dt(fields["end_at"])
        session.flush()
        return sprint

    @staticmethod
    def start_sprint(session: Session, project_key: str, sprint_id: int) -> Sprint:
        _load_project(session, project_key)
        sprint = session.get(Sprint, int(sprint_id))
        if sprint is None or sprint.project_key != project_key:
            raise JiraError(404, "Sprint not found")
        if sprint.state == "active":
            return sprint
        other = session.scalar(
            select(Sprint.id).where(
                Sprint.project_key == project_key,
                Sprint.state == "active",
                Sprint.id != sprint.id,
            )
        )
        if other is not None:
            raise JiraError(409, "Project already has an active sprint")
        sprint.state = "active"
        if sprint.start_at is None:
            sprint.start_at = utcnow()
        session.flush()
        return sprint

    @staticmethod
    def complete_sprint(
        session: Session,
        project_key: str,
        sprint_id: int,
        *,
        settings: Settings | None = None,
    ) -> tuple[Sprint, list[str]]:
        _load_project(session, project_key)
        sprint = session.get(Sprint, int(sprint_id))
        if sprint is None or sprint.project_key != project_key:
            raise JiraError(404, "Sprint not found")
        rows = session.execute(
            select(Issue, IssueSprint)
            .join(IssueSprint, IssueSprint.issue_key == Issue.key)
            .where(IssueSprint.sprint_id == sprint.id)
        ).all()
        moved: list[str] = []
        affected: list[Issue] = []
        for issue, membership in rows:
            if issue.deleted_at is not None:
                continue
            affected.append(issue)
            if issue.status_category != "done":
                session.delete(membership)
                moved.append(issue.key)
        sprint.state = "closed"
        if sprint.complete_at is None:
            sprint.complete_at = utcnow()
        session.flush()
        for issue in affected:
            issue.raw = LocalJiraService.build_issue_raw(session, issue, settings)
        session.flush()
        return sprint, moved

    @staticmethod
    def rank_backlog(
        session: Session,
        project_key: str,
        issue_key: str,
        *,
        sprint_id: int | None,
        before_key: str | None,
        actor: User | None = None,
        settings: Settings | None = None,
    ) -> Issue:
        _load_project(session, project_key)
        issue = _load_live_issue(session, issue_key)
        if issue.project_key != project_key:
            raise JiraError(404, f"Issue {issue_key} not found")
        if before_key == issue.key:
            raise JiraError(400, "before_key cannot be the same issue")
        if sprint_id is not None:
            sprint = session.get(Sprint, int(sprint_id))
            if sprint is None or sprint.project_key != project_key:
                raise JiraError(404, "Sprint not found")
        memberships = list(session.scalars(select(IssueSprint).where(IssueSprint.issue_key == issue.key)).all())
        if sprint_id is None:
            for row in memberships:
                session.delete(row)
        else:
            found = False
            for row in memberships:
                if row.sprint_id == int(sprint_id):
                    found = True
                else:
                    session.delete(row)
            if not found:
                session.add(IssueSprint(issue_key=issue.key, sprint_id=int(sprint_id)))
        session.flush()
        if sprint_id is None:
            peers = list(
                session.scalars(
                    select(Issue).where(
                        Issue.project_key == project_key,
                        Issue.deleted_at.is_(None),
                        ~Issue.key.in_(select(IssueSprint.issue_key)),
                    )
                ).all()
            )
        else:
            peers = list(
                session.scalars(
                    select(Issue)
                    .join(IssueSprint, IssueSprint.issue_key == Issue.key)
                    .where(IssueSprint.sprint_id == int(sprint_id), Issue.deleted_at.is_(None))
                ).all()
            )
        peer_keys = {peer.key for peer in peers}
        if before_key:
            if before_key not in peer_keys:
                raise JiraError(400, "before_key is not in the destination")
            before = next(peer for peer in peers if peer.key == before_key)
            lower = [peer.rank for peer in peers if peer.key != issue.key and peer.rank < before.rank]
            issue.rank = (max(lower) + before.rank) / 2.0 if lower else float(before.rank) - 1000.0
        else:
            others = [peer.rank for peer in peers if peer.key != issue.key]
            issue.rank = (max(others) if others else 0.0) + 1000.0
        _touch_issue(session, issue, settings)
        return issue

    @staticmethod
    def get_board(session: Session, project_key: str) -> dict[str, Any]:
        project = _load_project(session, project_key)
        workflow = _get_workflow(project)
        issues = session.scalars(
            select(Issue)
            .where(Issue.project_key == project_key, Issue.deleted_at.is_(None))
            .order_by(Issue.rank.asc(), Issue.key.asc())
        ).all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for issue in issues:
            grouped.setdefault(issue.status or "", []).append(
                {
                    "key": issue.key,
                    "summary": issue.summary,
                    "status": issue.status,
                    "issuetype": issue.issuetype,
                    "priority": issue.priority,
                    "assignee_id": issue.assignee_id,
                    "assignee_name": issue.assignee_name,
                    "rank": issue.rank,
                }
            )
        columns = []
        for status_row in workflow.get("statuses") or []:
            name = str(status_row.get("name") or "")
            columns.append(
                {
                    "name": name,
                    "status": name,
                    "category": status_row.get("category"),
                    "issues": grouped.get(name, []),
                }
            )
        return {"project_key": project_key, "columns": columns}


class LocalJiraClient:
    """SQLite-backed JiraClient drop-in implementing all 13 JiraClient methods."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session: Session | None = None,
        engine: Engine | None = None,
        actor: User | None = None,
    ) -> None:
        self.settings = settings or Settings(_env_file=None)
        self._session = session
        self._engine = engine
        self._actor = actor

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = make_engine(self.settings.db_url)
        return self._engine

    @contextmanager
    def _ro_session(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
            return
        with SessionLocal(bind=self._get_engine()) as s:
            yield s

    @contextmanager
    def _rw_session(self) -> Iterator[Session]:
        if self._session is not None:
            with self._session.begin_nested():
                yield self._session
                self._session.flush()
            return
        with SessionLocal(bind=self._get_engine()) as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    def get_issue(self, key: str) -> dict | None:
        with self._ro_session() as s:
            issue = s.get(Issue, key)
            if issue is None or issue.deleted_at is not None:
                return None
            return LocalJiraService.build_issue_raw(s, issue, self.settings)

    def search_keys(self, jql: str) -> list[str]:
        with self._ro_session() as s:
            stmt = select(Issue.key).where(Issue.deleted_at.is_(None))
            jql_str = jql or ""

            m_in = re.search(r"project\s+in\s*\(([^)]+)\)", jql_str, re.IGNORECASE)
            m_eq = re.search(r"project\s*=\s*\"?([A-Za-z0-9_]+)\"?", jql_str, re.IGNORECASE)
            if m_in:
                projects = [p.strip().strip('"').strip("'") for p in m_in.group(1).split(",") if p.strip()]
                if projects:
                    stmt = stmt.where(Issue.project_key.in_(projects))
            elif m_eq:
                stmt = stmt.where(Issue.project_key == m_eq.group(1))

            m_upd = re.search(r'updated\s*>=\s*"([^"]+)"', jql_str, re.IGNORECASE)
            if m_upd:
                since = _parse_dt(m_upd.group(1), default_tz=self.settings.tz)
                if since is not None:
                    stmt = stmt.where(Issue.updated_at >= since)

            return list(s.scalars(stmt.order_by(Issue.key.asc())).all())

    def get_sprint(self, sprint_id: int) -> dict | None:
        with self._ro_session() as s:
            sp = s.get(Sprint, sprint_id)
            if sp is None:
                return None
            return _sprint_dict(sp)

    def get_version(self, version_id: int) -> dict | None:
        with self._ro_session() as s:
            v = s.get(Version, version_id)
            if v is None:
                return None
            return _version_dict(v)

    def board_ids(self, project_key: str) -> list[int]:
        with self._ro_session() as s:
            proj = s.get(Project, project_key)
            if proj is None:
                return []
            ids = set(
                s.scalars(
                    select(Sprint.board_id).where(
                        Sprint.project_key == project_key,
                        Sprint.board_id.is_not(None),
                    )
                ).all()
            )
            ids.update(
                s.scalars(
                    select(Sprint.board_id)
                    .join(IssueSprint, IssueSprint.sprint_id == Sprint.id)
                    .join(Issue, Issue.key == IssueSprint.issue_key)
                    .where(Issue.project_key == project_key, Sprint.board_id.is_not(None))
                ).all()
            )
            cleaned = sorted(int(b) for b in ids if b is not None)
            return cleaned or [1]

    def project_id(self, key: str) -> int:
        with self._ro_session() as s:
            proj = s.get(Project, key)
            if proj is None:
                raise JiraError(404, f"Project {key} not found")
            return (zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF) or 1

    def myself(self) -> dict:
        if self._actor is not None:
            return _user_dict_from_user(self._actor, self.settings.tz)
        return {
            "accountId": "local-system",
            "name": "Local Jira",
            "displayName": "Local Jira",
            "active": True,
            "timeZone": self.settings.tz,
        }

    def register_webhook(self, url: str, events: list[str], jql: str) -> dict:
        return {
            "self": "local://webhook",
            "name": "early-risk",
            "url": url,
            "events": list(events),
            "filters": {"issue-related-events-section": jql},
            "enabled": True,
        }

    def get_issue_updated(self, key: str) -> datetime:
        with self._ro_session() as s:
            issue = s.get(Issue, key)
            if issue is None or issue.deleted_at is not None or issue.updated_at is None:
                raise JiraError(404, f"Updated timestamp not found for issue {key}")
            dt = issue.updated_at
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)

    def update_issue(self, key: str, fields: dict) -> None:
        with self._rw_session() as s:
            LocalJiraService.update_issue(s, key, fields, actor=self._actor, settings=self.settings)

    def add_comment(self, key: str, body: str | dict) -> None:
        with self._rw_session() as s:
            LocalJiraService.add_comment(s, key, body, actor=self._actor, settings=self.settings)

    def get_transitions(self, key: str) -> list[Transition]:
        with self._ro_session() as s:
            return LocalJiraService.get_transitions(s, key, settings=self.settings)

    def transition_issue(self, key: str, transition_id: str) -> None:
        with self._rw_session() as s:
            LocalJiraService.transition_issue(s, key, transition_id, actor=self._actor, settings=self.settings)


def make_jira_client(
    settings: Settings,
    *,
    session: Session | None = None,
    engine: Engine | None = None,
    actor: User | None = None,
) -> JiraClient | LocalJiraClient:
    if getattr(settings, "jira_mode", "local") == "local":
        return LocalJiraClient(settings, session=session, engine=engine, actor=actor)
    return JiraClient(settings)
