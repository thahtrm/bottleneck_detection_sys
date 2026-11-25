"""Score simulated projects through the same path a Jira webhook uses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from erw.db import utcnow
from erw.ingest.sync import SyncResult
from erw.models import Issue, Project
from erw.pipeline.evaluate import on_synced
from erw.settings import Settings


def score_simulated_projects(session: Session, settings: Settings) -> int:
    """Re-evaluate issues whose project origin is simulate. Jira projects stay on webhooks."""
    keys = list(
        session.scalars(
            select(Issue.key)
            .join(Project, Project.key == Issue.project_key)
            .where(Project.origin == "simulate", Issue.deleted_at.is_(None))
            .order_by(Issue.key)
        ).all()
    )
    if not keys:
        return 0
    on_synced(
        session,
        [SyncResult("updated", key, frozenset({"status"})) for key in keys],
        utcnow(),
        settings,
    )
    return len(keys)
