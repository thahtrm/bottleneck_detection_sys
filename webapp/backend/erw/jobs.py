from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from erw.db import SessionLocal, utcnow
from erw.ingest.sync import SyncResult, catch_up, mark_deleted, sync_issue, sync_sprint, sync_version
from erw.integrations.jira import JiraClient, JiraError
from erw.kv import kv_get_json, kv_set, kv_set_json
from erw.pipeline.evaluate import on_synced
from erw.settings import Settings

log = logging.getLogger(__name__)

# max_workers=1 serialises all SQLite writes
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="erw-jobs")

_settings: Settings | None = None
_engine: Engine | None = None
_client = None


def configure(settings: Settings, engine: Engine) -> None:
    global _settings, _engine
    _settings, _engine = settings, engine


def set_client(client) -> None:
    """Install a JiraClient (or a test double); None resets to the default built from settings."""
    global _client
    _client = client


def get_client():
    global _client
    if _client is None:
        s = _settings
        _client = JiraClient(s.jira_base_url, s.jira_email, s.jira_api_token)
    return _client


def _add_pending(session: Session, key: str) -> None:
    pending = kv_get_json(session, "pending_sync", [])
    if key not in pending:
        pending.append(key)
    kv_set_json(session, "pending_sync", pending)


def _tracked_boards(session: Session, client, settings: Settings, board_id: int) -> bool:
    boards = kv_get_json(session, "tracked_boards", None)
    if boards is None or board_id not in boards:  # missing or possibly stale: refresh once
        boards = sorted({b for p in settings.jira_projects for b in client.board_ids(p)})
        kv_set_json(session, "tracked_boards", boards)
    return board_id in boards


def _tracked_project(session: Session, client, settings: Settings, project_id: int) -> str | None:
    ids = kv_get_json(session, "tracked_project_ids", None)
    if ids is None or str(project_id) not in ids:
        ids = {str(client.project_id(p)): p for p in settings.jira_projects}
        kv_set_json(session, "tracked_project_ids", ids)
    return ids.get(str(project_id))


def _sync_keys(session: Session, client, settings: Settings, keys: list[str]) -> list[SyncResult]:
    results = []
    for k in keys:
        try:
            results.append(sync_issue(session, client, k, settings))
        except JiraError as e:
            log.warning("Jira error syncing %s: %s", k, e)
            session.rollback()
            _add_pending(session, k)
            session.commit()
    return results


def _member_results(keys: list[str], field: str) -> list[SyncResult]:
    return [SyncResult("updated", k, frozenset({field})) for k in keys]


def _dispatch(session: Session, payload: dict, client, settings: Settings) -> list[SyncResult]:
    event = payload.get("webhookEvent", "")
    if event in ("jira:issue_created", "jira:issue_updated"):
        return _sync_keys(session, client, settings, [payload["issue"]["key"]])
    if event in ("issuelink_created", "issuelink_deleted"):
        link = payload["issueLink"]
        return _sync_keys(session, client, settings, [str(link["sourceIssueId"]), str(link["destinationIssueId"])])
    if event == "jira:issue_deleted":
        return [mark_deleted(session, payload["issue"]["key"])]
    if event.startswith("sprint_"):
        sprint = payload["sprint"]
        board = sprint.get("originBoardId")
        if board is None or not _tracked_boards(session, client, settings, int(board)):
            return []
        return _member_results(sync_sprint(session, sprint), "sprint")
    if event.startswith("jira:version_"):
        version = payload["version"]
        project_key = _tracked_project(session, client, settings, int(version["projectId"]))
        if project_key is None:
            return []
        return _member_results(sync_version(session, version, project_key), "fix version")
    log.info("ignoring webhook event %r", event)
    return []


def handle_webhook(payload: dict) -> None:
    settings, client = _settings, get_client()
    try:
        with SessionLocal(bind=_engine) as session:
            try:
                results = _dispatch(session, payload, client, settings)
                now = utcnow()
                session.commit()
                on_synced(session, results, now, settings)
                kv_set(session, "last_webhook_at", now.isoformat())
                session.commit()
            except Exception:
                session.rollback()
                raise
    except Exception:
        log.exception("webhook handling failed: %s", payload.get("webhookEvent"))


def run_catch_up() -> None:
    try:
        with SessionLocal(bind=_engine) as session:
            n = catch_up(session, get_client(), _settings, utcnow())
            log.info("catch-up synced %d issues", n)
    except Exception:
        log.exception("catch-up failed")
