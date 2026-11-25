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


def _add_missing_columns(conn, existing_cols: set[str], table: str, specs: list[tuple[str, str]]) -> set[str]:
    from sqlalchemy import text

    added: set[str] = set()
    for col_name, col_ddl in specs:
        if col_name not in existing_cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl}"))
            added.add(col_name)
    return added


def init_db(engine: Engine) -> None:
    import re

    from sqlalchemy import inspect, text

    from erw.models import Base

    Base.metadata.create_all(engine)
    # Lightweight SQLite migrations for existing demos (no Alembic in this app).
    if engine.dialect.name == "sqlite":
        insp = inspect(engine)
        users_cols = {c["name"] for c in insp.get_columns("users")}
        projects_cols = {c["name"] for c in insp.get_columns("projects")}
        issues_cols = {c["name"] for c in insp.get_columns("issues")}
        changes_cols = {c["name"] for c in insp.get_columns("changes")}
        sprints_cols = {c["name"] for c in insp.get_columns("sprints")}
        versions_cols = {c["name"] for c in insp.get_columns("versions")}
        iv_cols = {c["name"] for c in insp.get_columns("issue_versions")}
        iv_pk = list((insp.get_pk_constraint("issue_versions") or {}).get("constrained_columns") or [])

        with engine.begin() as conn:
            _add_missing_columns(
                conn,
                users_cols,
                "users",
                [
                    ("is_active", "BOOLEAN NOT NULL DEFAULT 1"),
                    ("account_id", "VARCHAR"),
                    ("avatar_url", "VARCHAR"),
                    ("avatar_color", "VARCHAR"),
                    ("job_title", "VARCHAR"),
                    ("department", "VARCHAR"),
                    ("timezone", "VARCHAR NOT NULL DEFAULT 'Asia/Ho_Chi_Minh'"),
                ],
            )
            conn.execute(text("UPDATE users SET account_id = 'local-' || id WHERE account_id IS NULL OR account_id = ''"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_account_id ON users (account_id)"))

            _add_missing_columns(
                conn,
                projects_cols,
                "projects",
                [
                    ("description", "TEXT NOT NULL DEFAULT ''"),
                    ("lead_user_id", "INTEGER REFERENCES users(id)"),
                    ("issue_seq", "INTEGER NOT NULL DEFAULT 0"),
                    ("workflow", "JSON NOT NULL DEFAULT '{}'"),
                ],
            )
            max_by_proj: dict[str, int] = {}
            for proj_key, issue_key in conn.execute(text("SELECT project_key, key FROM issues")).all():
                if not proj_key or not issue_key:
                    continue
                m = re.search(r"-(\d+)$", str(issue_key))
                if m:
                    num = int(m.group(1))
                    if num > max_by_proj.get(proj_key, 0):
                        max_by_proj[proj_key] = num
            for proj_key, max_seq in max_by_proj.items():
                conn.execute(
                    text("UPDATE projects SET issue_seq = :max_seq WHERE key = :pk AND issue_seq < :max_seq"),
                    {"max_seq": max_seq, "pk": proj_key},
                )

            added_issue_cols = _add_missing_columns(
                conn,
                issues_cols,
                "issues",
                [
                    ("parent_key", "VARCHAR"),
                    ("description", "TEXT NOT NULL DEFAULT ''"),
                    ("environment", "TEXT NOT NULL DEFAULT ''"),
                    ("resolution", "VARCHAR"),
                    ("reporter_id", "VARCHAR"),
                    ("reporter_name", "VARCHAR"),
                    ("creator_id", "VARCHAR"),
                    ("creator_name", "VARCHAR"),
                    ("start_date", "DATE"),
                    ("rank", "FLOAT NOT NULL DEFAULT 0.0"),
                    ("original_estimate_seconds", "INTEGER"),
                    ("remaining_estimate_seconds", "INTEGER"),
                    ("time_spent_seconds", "INTEGER NOT NULL DEFAULT 0"),
                    ("labels", "JSON NOT NULL DEFAULT '[]'"),
                    ("version", "INTEGER NOT NULL DEFAULT 1"),
                ],
            )
            if "rank" in added_issue_cols:
                conn.execute(text("UPDATE issues SET rank = rowid * 1000.0"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_issues_parent_key ON issues (parent_key)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_issues_rank ON issues (rank)"))

            _add_missing_columns(
                conn,
                changes_cols,
                "changes",
                [
                    ("author_id", "VARCHAR"),
                    ("author_name", "VARCHAR"),
                ],
            )

            _add_missing_columns(
                conn,
                sprints_cols,
                "sprints",
                [
                    ("project_key", "VARCHAR"),
                    ("goal", "TEXT NOT NULL DEFAULT ''"),
                ],
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sprints_project_key ON sprints (project_key)"))

            _add_missing_columns(
                conn,
                versions_cols,
                "versions",
                [
                    ("description", "TEXT NOT NULL DEFAULT ''"),
                    ("start_date", "DATE"),
                ],
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_versions_project_key ON versions (project_key)"))

        if "relation_type" not in iv_pk:
            rel_expr = "COALESCE(relation_type, 'fix')" if "relation_type" in iv_cols else "'fix'"
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                try:
                    conn.execute(text("BEGIN"))
                    conn.execute(
                        text(
                            "CREATE TABLE issue_versions_new ("
                            "issue_key VARCHAR NOT NULL, "
                            "version_id INTEGER NOT NULL, "
                            "relation_type VARCHAR NOT NULL DEFAULT 'fix', "
                            "PRIMARY KEY (issue_key, version_id, relation_type), "
                            'FOREIGN KEY(issue_key) REFERENCES issues ("key"), '
                            "FOREIGN KEY(version_id) REFERENCES versions (id)"
                            ")"
                        )
                    )
                    conn.execute(
                        text(
                            f"INSERT INTO issue_versions_new (issue_key, version_id, relation_type) "
                            f"SELECT issue_key, version_id, {rel_expr} FROM issue_versions"
                        )
                    )
                    conn.execute(text("DROP TABLE issue_versions"))
                    conn.execute(text("ALTER TABLE issue_versions_new RENAME TO issue_versions"))
                    conn.execute(text("COMMIT"))
                except Exception:
                    conn.execute(text("ROLLBACK"))
                    raise
                finally:
                    conn.execute(text("PRAGMA foreign_keys=ON"))


def utcnow() -> datetime:
    return datetime.now(UTC)
