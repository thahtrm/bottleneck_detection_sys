from __future__ import annotations

import json

from sqlalchemy.orm import Session

from erw.models import KV


def kv_get(session: Session, key: str) -> str | None:
    row = session.get(KV, key)
    return row.value if row else None


def kv_set(session: Session, key: str, value: str) -> None:
    row = session.get(KV, key)
    if row is None:
        session.add(KV(key=key, value=value))
    else:
        row.value = value


def kv_get_json(session: Session, key: str, default=None):
    raw = kv_get(session, key)
    return default if raw is None else json.loads(raw)


def kv_set_json(session: Session, key: str, value) -> None:
    kv_set(session, key, json.dumps(value))
