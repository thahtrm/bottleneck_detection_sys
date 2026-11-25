from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.ml.duckdb_sync import to_dump_shape
from erw.models import Change, Issue, Link, RiskState, Score

from .capabilities import has_column

VALID_LINK_TYPES = frozenset({"Block", "Depend", "Relate", "Duplicate", "Clone"})
VALID_LINK_DIRECTIONS = frozenset({"0", "1"})


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def assert_jira_v3_issue_raw(raw: dict[str, Any], *, check_etl: bool = True) -> None:
    """Assert that Issue.raw conforms to Jira REST API v3 JSON and optionally DuckDB ETL transform."""
    assert isinstance(raw, dict), f"Issue.raw must be a dict, got {type(raw).__name__}"
    assert isinstance(raw.get("key"), str) and raw["key"], "Issue.raw missing non-empty 'key'"

    fields = raw.get("fields")
    assert isinstance(fields, dict), "Issue.raw missing 'fields' dict"
    assert isinstance(fields.get("summary"), str), "Issue.raw.fields.summary must be str"

    issuetype = fields.get("issuetype")
    assert isinstance(issuetype, dict) and isinstance(issuetype.get("name"), str), (
        "Issue.raw.fields.issuetype.name missing"
    )

    status = fields.get("status")
    assert isinstance(status, dict) and isinstance(status.get("name"), str), (
        "Issue.raw.fields.status.name missing"
    )
    status_cat = status.get("statusCategory")
    assert isinstance(status_cat, dict) and status_cat.get("key") in {
        "new",
        "indeterminate",
        "done",
    }, f"Invalid statusCategory.key: {status_cat}"

    priority = fields.get("priority")
    assert isinstance(priority, dict) and isinstance(priority.get("name"), str), (
        "Issue.raw.fields.priority.name missing"
    )

    assert isinstance(fields.get("created"), str) and fields["created"], "Issue.raw.fields.created missing"
    assert isinstance(fields.get("updated"), str) and fields["updated"], "Issue.raw.fields.updated missing"

    desc = fields.get("description")
    if desc is not None:
        assert isinstance(desc, dict), f"Issue.raw.fields.description must be None or ADF dict, got {type(desc).__name__}"
        assert desc.get("type") == "doc", f"ADF description type must be 'doc', got {desc.get('type')}"
        assert desc.get("version") == 1, f"ADF description version must be 1, got {desc.get('version')}"
        assert isinstance(desc.get("content"), list), "ADF description content must be list"

    for user_field in ("assignee", "reporter", "creator"):
        user_obj = fields.get(user_field)
        if user_obj is not None:
            assert isinstance(user_obj, dict), f"fields.{user_field} must be dict or None"
            for required_key in ("accountId", "displayName", "name"):
                assert required_key in user_obj and user_obj[required_key] is not None, (
                    f"fields.{user_field} missing '{required_key}' for JiraTransformer compatibility"
                )

    changelog = raw.get("changelog")
    assert isinstance(changelog, dict) and isinstance(changelog.get("histories"), list), (
        "Issue.raw.changelog.histories must be a list"
    )

    comment = fields.get("comment")
    assert isinstance(comment, dict) and isinstance(comment.get("comments"), list), (
        "Issue.raw.fields.comment must be a dict with 'comments' list"
    )
    assert isinstance(fields.get("issuelinks"), list), "Issue.raw.fields.issuelinks must be a list"
    assert isinstance(fields.get("timetracking"), dict), "Issue.raw.fields.timetracking must be a dict"
    assert "customfield_10016" in fields, "Issue.raw.fields missing 'customfield_10016'"
    assert "customfield_10020" in fields, "Issue.raw.fields missing 'customfield_10020'"

    if check_etl:
        from early_risk_detection.data.etl.transformer import JiraTransformer

        dump_doc = to_dump_shape(raw)
        batch = JiraTransformer().transform_batch([dump_doc], "ERW")
        assert len(batch["issues"]) == 1, f"JiraTransformer failed to produce issue row for {raw.get('key')}"


def assert_change_recorded(
    session: Session,
    issue_key: str,
    field: str,
    *,
    from_str: str | None = None,
    to_str: str | None = None,
    author_id: int | str | None = None,
) -> Change:
    """Assert that a lowercased Jira-format Change row exists for issue_key and field."""
    expected_field = field.lower()
    rows = session.scalars(
        select(Change)
        .where(Change.issue_key == issue_key, Change.field == expected_field)
        .order_by(Change.at.desc(), Change.id.desc())
    ).all()
    assert rows, f"No Change row found for issue={issue_key}, field={expected_field}"

    matched = rows[0]
    if from_str is not None or to_str is not None:
        candidate = next(
            (
                r
                for r in rows
                if (from_str is None or r.from_str == from_str)
                and (to_str is None or r.to_str == to_str)
            ),
            None,
        )
        assert candidate is not None, (
            f"No Change row for {issue_key}.{expected_field} matched "
            f"from_str={from_str!r}, to_str={to_str!r}; got {[(r.from_str, r.to_str) for r in rows]}"
        )
        matched = candidate

    assert matched.at is not None and matched.at.tzinfo is not None, "Change.at must be tz-aware"
    if author_id is not None and has_column(Change, "author_id"):
        assert getattr(matched, "author_id") == author_id, (
            f"Expected Change.author_id={author_id!r}, got {getattr(matched, 'author_id')!r}"
        )
    return matched


def assert_risk_state_fresh(
    session: Session,
    issue_key: str,
    *,
    level: str | None = None,
    blocked: bool | None = None,
    min_updated_at: datetime | None = None,
) -> RiskState:
    """Assert that RiskState and latest rules_dynamic Score exist, are fresh, and match expected level/blocked."""
    issue = session.get(Issue, issue_key)
    assert issue is not None, f"Issue missing for {issue_key}"

    state = session.get(RiskState, issue_key)
    assert state is not None, f"RiskState missing for {issue_key}"
    assert state.updated_at is not None, f"RiskState.updated_at is None for {issue_key}"

    latest_score = session.scalars(
        select(Score)
        .where(Score.issue_key == issue_key, Score.scorer == "rules_dynamic")
        .order_by(Score.as_of.desc(), Score.id.desc())
    ).first()
    assert latest_score is not None, f"Missing rules_dynamic Score for {issue_key}"
    assert latest_score.as_of is not None, f"Score.as_of is None for {issue_key}"

    if issue.updated_at is not None:
        issue_ts = _as_utc(issue.updated_at)
        assert _as_utc(state.updated_at) >= issue_ts, (
            f"Stale RiskState for {issue_key}: state.updated_at={state.updated_at!r} < issue.updated_at={issue.updated_at!r}"
        )
        assert _as_utc(latest_score.as_of) >= issue_ts, (
            f"Stale rules_dynamic Score for {issue_key}: score.as_of={latest_score.as_of!r} < issue.updated_at={issue.updated_at!r}"
        )

    if min_updated_at is not None:
        min_ts = _as_utc(min_updated_at)
        assert _as_utc(state.updated_at) >= min_ts, (
            f"RiskState.updated_at={state.updated_at!r} < min_updated_at={min_updated_at!r} for {issue_key}"
        )
        assert _as_utc(latest_score.as_of) >= min_ts, (
            f"Score.as_of={latest_score.as_of!r} < min_updated_at={min_updated_at!r} for {issue_key}"
        )

    if level is not None:
        assert state.level == level, f"Expected RiskState.level={level!r}, got {state.level!r}"
    if blocked is not None:
        assert state.blocked is blocked, f"Expected RiskState.blocked={blocked!r}, got {state.blocked!r}"
    return state


def assert_canonical_link(
    session: Session,
    source_key: str,
    target_key: str,
    type_std: str,
    direction: str,
) -> Link:
    """Assert that a canonical Link row exists with normalized type_std and direction."""
    assert type_std in VALID_LINK_TYPES, f"Unexpected link type_std={type_std!r}"
    assert direction in VALID_LINK_DIRECTIONS, f"Unexpected link direction={direction!r}"

    link = session.get(Link, (source_key, target_key, type_std))
    assert link is not None, f"Link ({source_key}, {target_key}, {type_std}) not found"
    assert link.direction == direction, f"Expected direction={direction!r}, got {link.direction!r}"
    return link
