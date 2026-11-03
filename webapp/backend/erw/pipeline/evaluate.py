from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from erw.ingest.sync import SyncResult
from erw.settings import Settings


def on_synced(session: Session, results: list[SyncResult], now: datetime, settings: Settings) -> list:
    """Re-evaluate risk for synced issues. Stub until Task 9."""
    return []
