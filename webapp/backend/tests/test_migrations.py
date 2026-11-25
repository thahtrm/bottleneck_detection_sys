from __future__ import annotations

import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, text

from erw.db import init_db, make_engine
from erw.models import Issue, IssueVersion, Project, RiskState, User, Version
from erw.pipeline.evaluate import evaluate_issue

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_ERW_DB = REPO_ROOT / "var" / "erw.db"


def test_fresh_init_db_is_idempotent(tmp_path):
    db_file = tmp_path / "fresh.db"
    engine = make_engine(f"sqlite:///{db_file}")
    init_db(engine)
    init_db(engine)

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    expected = {
        "users",
        "projects",
        "project_members",
        "issues",
        "changes",
        "links",
        "sprints",
        "issue_sprints",
        "versions",
        "issue_versions",
        "scores",
        "risk_state",
        "notifications",
        "suggestions",
        "actions",
        "kv",
        "chat_messages",
        "report_slots",
        "report_files",
        "chat_memories",
        "chat_rag_chunks",
        "chat_agent_runs",
        "comments",
        "attachments",
        "worklogs",
        "watchers",
        "votes",
        "components",
        "issue_components",
    }
    assert expected.issubset(tables)
    assert set(insp.get_pk_constraint("issue_versions")["constrained_columns"]) == {
        "issue_key",
        "version_id",
        "relation_type",
    }
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_var_erw_db_copy_migrates_idempotently(tmp_path):
    if not REAL_ERW_DB.exists():
        return
    src_stat = REAL_ERW_DB.stat()
    copy_path = tmp_path / "erw_copy.db"
    shutil.copyfile(REAL_ERW_DB, copy_path)

    engine = make_engine(f"sqlite:///{copy_path}")
    init_db(engine)
    init_db(engine)

    insp = inspect(engine)
    assert set(insp.get_pk_constraint("issue_versions")["constrained_columns"]) == {
        "issue_key",
        "version_id",
        "relation_type",
    }
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        users = conn.execute(text("SELECT id, account_id, is_active FROM users ORDER BY id")).all()
        assert len(users) == 3
        assert [u[1] for u in users] == ["local-1", "local-2", "local-3"]
        assert all(u[2] == 1 for u in users)

        proj = conn.execute(text("SELECT issue_seq FROM projects WHERE key = 'DEMO'")).one()
        assert proj[0] == 116

        ranks = [r[0] for r in conn.execute(text("SELECT rank FROM issues")).all()]
        assert all(r > 0 for r in ranks)

    assert REAL_ERW_DB.stat().st_mtime == src_stat.st_mtime
    assert REAL_ERW_DB.stat().st_size == src_stat.st_size
    engine.dispose()


def test_issue_version_relation_type_fix_vs_affects(session, settings):
    now = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
    session.add(Project(key="DEMO", name="Demo", tracked=True))
    session.add(
        Issue(
            key="DEMO-1",
            project_key="DEMO",
            summary="Test",
            status="In Progress",
            status_category="indeterminate",
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=1),
        )
    )
    session.add(Version(id=1, project_key="DEMO", name="v1.0", release_date=date(2026, 11, 5), released=False))
    session.add(Version(id=2, project_key="DEMO", name="v0.9-old", release_date=date(2026, 10, 1), released=False))
    session.flush()

    # Default relation_type is "fix"
    iv_fix = IssueVersion(issue_key="DEMO-1", version_id=1)
    assert iv_fix.relation_type == "fix"
    # Same (issue_key, version_id) with relation_type="affects" can coexist on PK
    iv_aff_same = IssueVersion(issue_key="DEMO-1", version_id=1, relation_type="affects")
    iv_aff_old = IssueVersion(issue_key="DEMO-1", version_id=2, relation_type="affects")
    session.add_all([iv_fix, iv_aff_same, iv_aff_old])
    session.commit()

    evaluate_issue(session, "DEMO-1", now, settings)
    rs = session.get(RiskState, "DEMO-1")
    assert rs is not None
    # Deadline must come from fixVersion v1.0 (2026-11-05), NOT affectsVersion v0.9-old (2026-10-01)
    assert "v1.0" in (rs.deadline_label or "")
    assert "v0.9-old" not in (rs.deadline_label or "")
    assert rs.deadline_at is not None and rs.deadline_at.date() == date(2026, 11, 5)


def test_user_model_defaults_without_persistence():
    u1 = User(email="a@example.com", name="Alice", password_hash="h", created_at=datetime.now(UTC))
    u2 = User(email="b@example.com", name="Bob", password_hash="h", created_at=datetime.now(UTC))
    assert u1.is_active is True
    assert u1.is_admin is False
    assert u1.timezone == "Asia/Ho_Chi_Minh"
    assert u1.avatar_color.startswith("#")
    assert u1.account_id and u2.account_id and u1.account_id != u2.account_id
