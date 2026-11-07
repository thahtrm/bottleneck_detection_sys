from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from erw.ingest.sync import sync_issue
from erw.integrations.jira import match_transition
from erw.integrations.slack import SlackSender
from erw.models import Action, User

if TYPE_CHECKING:
    from erw.integrations.jira import JiraClient
    from erw.settings import Settings

log = logging.getLogger(__name__)


def execute_action(
    session: Session,
    jira_client: JiraClient,
    action_id: int,
    expected_updated: datetime,
    confirmed_by_user: User,
    settings: Settings,
    sender: SlackSender | None = None,
) -> dict[str, Any]:
    action = session.get(Action, action_id)
    if action is None:
        raise ValueError(f"Action {action_id} not found")
    if action.status != "pending":
        return stored_outcome(action)

    issue_key = action.issue_key

    # Optimistic locking check against Jira's current updated timestamp
    current_updated = jira_client.get_issue_updated(issue_key)
    if current_updated.tzinfo is None:
        current_updated = current_updated.replace(tzinfo=UTC)
    else:
        current_updated = current_updated.astimezone(UTC)

    if expected_updated.tzinfo is None:
        exp_utc = expected_updated.replace(tzinfo=UTC)
    else:
        exp_utc = expected_updated.astimezone(UTC)

    if abs((current_updated - exp_utc).total_seconds()) > 2.0:
        action.status = "conflict"
        action.result = {
            "error": "conflict",
            "current_updated": current_updated.isoformat(),
            "expected_updated": expected_updated.isoformat(),
        }
        session.commit()
        return stored_outcome(action)

    raw_items = action.items
    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except Exception:
            raw_items = []
    elif not isinstance(raw_items, list):
        raw_items = []

    pm_attribution = f"\n\n*(xác nhận bởi PM {confirmed_by_user.name} qua Early Risk)*"

    items = [d for d in (_as_dict(i) for i in raw_items) if d is not None]

    try:
        transition_ids, missing = _resolve_transitions(jira_client, issue_key, items)
        if missing is not None:
            action.status = "failed"
            action.result = missing
            session.commit()
            return stored_outcome(action)

        for item in items:
            item_type = item.get("action_type")
            val = item.get("value")
            target = item.get("target")
            reason = item.get("reason")

            if item_type == "adjust_deadline":
                duedate = val
                if (
                    (not duedate or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(duedate)))
                    and target
                    and re.match(r"^\d{4}-\d{2}-\d{2}$", str(target))
                ):
                    duedate = target
                elif not duedate and target:
                    duedate = target
                if duedate:
                    jira_client.update_issue(issue_key, {"duedate": str(duedate)})

            elif item_type == "change_assignee":
                assignee_val = val if val is not None else target
                if assignee_val is None or str(assignee_val).strip().lower() in ("unassigned", "none", "null", ""):
                    jira_client.update_issue(issue_key, {"assignee": None})
                elif isinstance(assignee_val, dict):
                    jira_client.update_issue(issue_key, {"assignee": assignee_val})
                else:
                    jira_client.update_issue(issue_key, {"assignee": {"accountId": str(assignee_val)}})

            elif item_type == "change_status":
                status_val = _status_target(item)
                if status_val:
                    jira_client.transition_issue(issue_key, transition_ids[status_val])

            elif item_type == "add_comment":
                body = val or reason or target or ""
                full_text = f"{body}{pm_attribution}"
                jira_client.add_comment(issue_key, full_text)

            elif item_type == "escalate_blocker":
                if val:
                    desc = str(val)
                elif target and reason:
                    desc = f"[Escalation] Đề xuất gỡ blocker liên quan đến {target}: {reason}"
                elif target:
                    desc = f"[Escalation] Đề xuất gỡ blocker liên quan đến {target}"
                elif reason:
                    desc = f"[Escalation] {reason}"
                else:
                    desc = "[Escalation] Báo cáo blocker cần xử lý khẩn cấp"
                full_text = f"{desc}{pm_attribution}"
                jira_client.add_comment(issue_key, full_text)

    except Exception as e:
        action.status = "failed"
        action.result = {"error": str(e)}
        session.commit()
        raise

    action.status = "applied"
    action.confirmed_by = confirmed_by_user.id
    action.result = {
        "applied_items": len(raw_items),
        "applied_at": datetime.now(UTC).isoformat(),
    }

    # Slack notification
    proj = issue_key.split("-")[0]
    web_base = settings.web_base_url.rstrip("/")
    text = f"[Đã xử lý] [{proj}] <{web_base}/issues/{issue_key}|{issue_key}> đã được cập nhật bởi PM {confirmed_by_user.name}."
    slack = sender
    if slack is None and settings.slack_webhook_url:
        slack = SlackSender(settings.slack_webhook_url)
    if slack is not None:
        try:
            slack.post(text)
        except Exception as e:
            log.warning("Failed to send Slack notification for action %s: %s", action_id, e)

    # Re-sync issue from Jira to update local state
    sync_issue(session, jira_client, issue_key, settings)

    session.commit()
    return {"status": "applied", "action_id": action.id, "applied_items": len(raw_items)}


def stored_outcome(action: Action) -> dict[str, Any]:
    """What confirming `action` produced; a repeat confirm returns this without touching Jira."""
    result = action.result if isinstance(action.result, dict) else {}
    if action.status == "applied":
        return {"status": "applied", "action_id": action.id, "applied_items": result.get("applied_items", 0)}
    if action.status == "conflict":
        return {
            "status": "conflict",
            "current_updated": result.get("current_updated"),
            "expected_updated": result.get("expected_updated"),
        }
    return {**result, "status": action.status}


def _as_dict(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    return None


def _status_target(item: dict[str, Any]) -> str | None:
    target = item.get("value") or item.get("target")
    return str(target) if target else None


def _resolve_transitions(
    jira_client: JiraClient, issue_key: str, items: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Transition id per change_status target, or the failure to store when Jira offers no matching transition.

    Runs before any Jira write so an impossible status move never leaves the other items half applied.
    """
    targets = [t for i in items if i.get("action_type") == "change_status" and (t := _status_target(i))]
    if not targets:
        return {}, None
    transitions = jira_client.get_transitions(issue_key)
    ids: dict[str, str] = {}
    for target in targets:
        found = match_transition(transitions, target)
        if found is None:
            log.warning("Transition not found for issue %s to status %s", issue_key, target)
            available = list(dict.fromkeys(t.to_status for t in transitions if t.to_status))
            return {}, {"error": "transition_not_allowed", "target": target, "available": available}
        ids[target] = found.id
    return ids, None
