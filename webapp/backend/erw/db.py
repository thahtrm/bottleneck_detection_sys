from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetime stored as naive UTC (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use timezone-aware values")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Generator[Session, None, None]:
    engine = getattr(request.app.state, "engine", None)
    if engine is not None:
        with Session(engine) as session:
            yield session
    else:
        with SessionLocal() as session:
            yield session


def make_engine(url: str) -> Engine:
    u = make_url(url)
    kwargs: dict = {}
    if u.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if u.database in (None, "", ":memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            Path(u.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if u.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def init_db(engine: Engine) -> None:
    from erw.models import Base

    Base.metadata.create_all(engine)


def utcnow() -> datetime:
    return datetime.now(UTC)
