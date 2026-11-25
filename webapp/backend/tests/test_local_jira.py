from __future__ import annotations

from datetime import UTC, date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from erw.auth import hash_password
from erw.db import SessionLocal, init_db, make_engine, utcnow
from erw.ingest.sync import sync_issue
from erw.integrations.jira import JiraError, match_transition
from erw.integrations.local_jira import (
    LocalJiraClient,
    LocalJiraConflictError,
    LocalJiraService,
    TransitionNotAllowedError,
    canonical_link,
    format_jira_duration,
    parse_jira_duration,
)
from erw.main import create_app
from erw.ml.duckdb_sync import ensure_work_db, sync_erw_instance, to_dump_shape
from erw.models import (
    Change,
    Comment,
    Component,
    Issue,
    IssueVersion,
    Link,
    Project,
    ProjectMember,
    RiskState,
    Sprint,
    User,
    Version,
)
from erw.settings import Settings


@pytest.fixture
def local_settings():
    return Settings(
        _env_file=None,
        db_url="sqlite://",
        jira_base_url="",
        jira_projects=["DEMO"],
        slack_webhook_url="",
    )


@pytest.fixture
def local_engine(local_settings):
    eng = make_engine(local_settings.db_url)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def local_session(local_engine):
    with SessionLocal(bind=local_engine) as s:
        yield s


@pytest.fixture
def demo_setup(local_session, local_settings):
    now = utcnow()
    pm = User(
        email="pm@local.test",
        name="PM Alice",
        password_hash=hash_password("pass"),
        account_id="acc-pm",
        created_at=now,
    )
    dev = User(
        email="dev@local.test",
        name="Dev Bob",
        password_hash=hash_password("pass"),
        account_id="acc-dev",
        created_at=now,
    )
    proj = Project(key="DEMO", name="Demo Project", tracked=True)
    local_session.add_all([pm, dev, proj])
    local_session.flush()
    sp = Sprint(id=10, project_key="DEMO", board_id=3, name="Sprint 10", state="active", start_at=now - timedelta(days=2), end_at=now + timedelta(days=5))
    ver = Version(id=20, project_key="DEMO", name="v1.0", release_date=(now + timedelta(days=7)).date(), released=False)
    aff = Version(id=21, project_key="DEMO", name="v0.9", release_date=(now - timedelta(days=7)).date(), released=True)
    comp = Component(id=30, project_key="DEMO", name="API")
    local_session.add_all([sp, ver, aff, comp])
    local_session.flush()
    local_session.add(ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"))
    local_session.add(ProjectMember(project_key="DEMO", user_id=dev.id, role="developer"))
    local_session.commit()
    return {"pm": pm, "dev": dev, "project": proj, "sprint": sp, "version": ver, "affects_version": aff, "component": comp}


def test_duration_parser_and_formatter():
    assert parse_jira_duration("1w 2d 3h 4m") == (5 * 8 + 2 * 8 + 3) * 3600 + 4 * 60
    assert parse_jira_duration("90") == 5400
    assert format_jira_duration(parse_jira_duration("1w 2d 3h 4m")) == "1w 2d 3h 4m"
    assert format_jira_duration(0) == "0m"
    with pytest.raises(ValueError):
        parse_jira_duration("not-a-duration")
    assert canonical_link("A", "B", "depends on") == ("A", "B", "Depend", "1")
    assert canonical_link("A", "B", "is blocked by") == ("A", "B", "Block", "0")
    assert canonical_link("A", "B", "clones") == ("A", "B", "Clone", "1")


def test_local_jira_client_13_methods_parity(local_engine, local_session, local_settings, demo_setup):
    pm = demo_setup["pm"]
    dev = demo_setup["dev"]
    issue = LocalJiraService.create_issue(
        local_session,
        project_key="DEMO",
        summary="Build API",
        description="Line 1\nLine 2",
        priority="High",
        assignee=dev,
        reporter=pm,
        duedate="2026-11-20",
        story_points=5.0,
        original_estimate_seconds=7200,
        labels=["backend", "urgent"],
        sprint_ids=[10],
        fix_version_ids=[20],
        affects_version_ids=[21],
        component_ids=[30],
        actor=pm,
        settings=local_settings,
    )
    local_session.commit()

    client = LocalJiraClient(local_settings, engine=local_engine, actor=pm)

    # 1. get_issue
    raw = client.get_issue(issue.key)
    assert raw is not None and raw["key"] == issue.key
    assert raw["fields"]["assignee"]["name"] == "Dev Bob"
    assert raw["fields"]["assignee"]["displayName"] == "Dev Bob"
    assert raw["fields"]["customfield_10016"] == 5.0
    assert len(raw["fields"]["customfield_10020"]) == 1
    assert len(raw["fields"]["fixVersions"]) == 1
    assert len(raw["fields"]["versions"]) == 1
    assert client.get_issue("DEMO-999") is None

    # 2. search_keys
    assert client.search_keys('project in ("DEMO")') == [issue.key]
    assert client.search_keys('project in ("DEMO") AND updated >= "2020/01/01 00:00"') == [issue.key]
    assert client.search_keys('project in ("DEMO") AND updated >= "2099/01/01 00:00"') == []

    # 3. get_sprint
    sp = client.get_sprint(10)
    assert sp is not None and sp["name"] == "Sprint 10"
    assert client.get_sprint(999) is None

    # 4. get_version
    ver = client.get_version(20)
    assert ver is not None and ver["name"] == "v1.0"
    assert client.get_version(999) is None

    # 5. board_ids
    assert client.board_ids("DEMO") == [3]

    # 6. project_id
    assert client.project_id("DEMO") > 0
    with pytest.raises(JiraError) as exc_proj:
        client.project_id("NOPE")
    assert exc_proj.value.status == 404

    # 7. myself
    me = client.myself()
    assert me["accountId"] == "acc-pm" and me["name"] == "PM Alice" and me["displayName"] == "PM Alice"

    # 8. register_webhook
    wh = client.register_webhook("https://example/wh", ["jira:issue_updated"], "project = DEMO")
    assert wh["enabled"] is True

    # 9. get_issue_updated
    upd = client.get_issue_updated(issue.key)
    assert upd.tzinfo == UTC

    # 10. update_issue
    client.update_issue(issue.key, {"duedate": "2026-12-01", "assignee": {"accountId": "acc-pm"}})

    # 11. add_comment (str & ADF dict)
    client.add_comment(issue.key, "Plain comment")
    client.add_comment(
        issue.key,
        {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "ADF comment"}]}]},
    )

    # 12. get_transitions & 13. transition_issue
    transitions = client.get_transitions(issue.key)
    t_prog = match_transition(transitions, "In Progress")
    assert t_prog is not None
    client.transition_issue(issue.key, t_prog.id)

    after = client.get_issue(issue.key)
    assert after["fields"]["status"]["name"] == "In Progress"
    assert after["fields"]["duedate"] == "2026-12-01"
    assert after["fields"]["assignee"]["accountId"] == "acc-pm"
    assert len(after["fields"]["comment"]["comments"]) == 2
    assert len(after["changelog"]["histories"]) >= 2


def test_workflow_auto_resolution_reopen_and_422(local_session, local_settings, demo_setup):
    pm = demo_setup["pm"]
    issue = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Flow", actor=pm, settings=local_settings
    )
    local_session.commit()

    # Cannot jump from To Do directly to Reopened (id "71")
    with pytest.raises(TransitionNotAllowedError) as exc_bad:
        LocalJiraService.transition_issue(local_session, issue.key, "71", actor=pm, settings=local_settings)
    assert exc_bad.value.status == 422

    # Transition to Done ("61") -> auto-sets resolution & resolved_at
    LocalJiraService.transition_issue(local_session, issue.key, "61", actor=pm, settings=local_settings)
    assert issue.status == "Done"
    assert issue.status_category == "done"
    assert issue.resolution == "Done"
    assert issue.resolved_at is not None

    # Reopen ("71") -> clears resolution & resolved_at
    LocalJiraService.transition_issue(local_session, issue.key, "71", actor=pm, settings=local_settings)
    assert issue.status == "Reopened"
    assert issue.status_category == "indeterminate"
    assert issue.resolution is None
    assert issue.resolved_at is None


def test_optimistic_locking_version_and_updated_at(local_session, local_settings, demo_setup):
    pm = demo_setup["pm"]
    issue = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Lock", actor=pm, settings=local_settings
    )
    v1 = issue.version
    u1 = issue.updated_at

    LocalJiraService.update_issue(
        local_session, issue.key, {"summary": "Lock v2"}, expected_version=v1, actor=pm, settings=local_settings
    )
    assert issue.version == v1 + 1
    assert issue.updated_at > u1

    with pytest.raises(LocalJiraConflictError) as exc_v:
        LocalJiraService.update_issue(
            local_session, issue.key, {"summary": "Stale"}, expected_version=v1, actor=pm, settings=local_settings
        )
    assert exc_v.value.status == 409

    with pytest.raises(LocalJiraConflictError) as exc_u:
        LocalJiraService.update_issue(
            local_session, issue.key, {"summary": "Stale2"}, expected_updated=u1, actor=pm, settings=local_settings
        )
    assert exc_u.value.status == 409

    echoed = issue.raw["fields"]["updated"]
    LocalJiraService.update_issue(
        local_session, issue.key, {"summary": "Lock echoed"}, expected_updated=echoed, actor=pm, settings=local_settings
    )
    assert issue.summary == "Lock echoed"

    with pytest.raises(LocalJiraConflictError) as exc_ms:
        LocalJiraService.update_issue(
            local_session,
            issue.key,
            {"summary": "Skewed"},
            expected_updated=issue.updated_at + timedelta(milliseconds=1),
            actor=pm,
            settings=local_settings,
        )
    assert exc_ms.value.status == 409
    assert issue.summary == "Lock echoed"


def test_execute_action_end_to_end_in_local_mode(local_engine, local_session, local_settings, demo_setup):
    pm = demo_setup["pm"]
    dev = demo_setup["dev"]
    issue = LocalJiraService.create_issue(
        local_session,
        project_key="DEMO",
        summary="Action target",
        description="Preserved description",
        parent_key=None,
        assignee=dev,
        actor=pm,
        settings=local_settings,
    )
    local_session.commit()
    exp_updated = issue.updated_at.isoformat()

    with TestClient(
        create_app(local_settings, engine=local_engine, catch_up_on_startup=False, start_scheduler_on_startup=False)
    ) as client:
        assert client.post("/api/auth/login", json={"email": "pm@local.test", "password": "pass"}).status_code == 200
        prop = client.post(
            "/api/actions/propose",
            json={
                "issue_key": issue.key,
                "items": [
                    {"action_type": "adjust_deadline", "value": "2026-11-28"},
                    {"action_type": "change_assignee", "value": "acc-pm"},
                    {"action_type": "change_status", "value": "In Progress"},
                    {"action_type": "add_comment", "value": "Confirmed locally"},
                ],
            },
        )
        assert prop.status_code == 201
        action_id = prop.json()["action_id"]

        conf = client.post(f"/api/actions/{action_id}/confirm", json={"expected_updated": exp_updated})
        assert conf.status_code == 200
        assert conf.json()["status"] == "applied"

    local_session.expire_all()
    updated = local_session.get(Issue, issue.key)
    assert updated.status == "In Progress"
    assert updated.assignee_id == "acc-pm"
    assert updated.duedate == date(2026, 11, 28)
    assert updated.description == "Preserved description"
    assert updated.version > 1
    assert len(local_session.scalars(select(Comment).where(Comment.issue_key == issue.key)).all()) == 1
    fields_changed = {c.field for c in local_session.scalars(select(Change).where(Change.issue_key == issue.key)).all()}
    assert {"duedate", "assignee", "status"}.issubset(fields_changed)
    assert local_session.get(RiskState, issue.key) is not None


def test_canonical_link_and_realtime_neighbor_evaluation(local_session, local_settings, demo_setup):
    pm = demo_setup["pm"]
    blocker = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Blocker", actor=pm, settings=local_settings
    )
    blocked = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Blocked", actor=pm, settings=local_settings
    )
    local_session.commit()

    link = LocalJiraService.add_link(
        local_session, blocker.key, blocked.key, "blocks", actor=pm, settings=local_settings
    )
    assert (link.source_key, link.target_key, link.type_std, link.direction) == (blocker.key, blocked.key, "Block", "1")
    # Adding inverse link does not create a duplicate row
    inv_link = LocalJiraService.add_link(
        local_session, blocked.key, blocker.key, "is blocked by", actor=pm, settings=local_settings
    )
    assert inv_link is link
    assert len(local_session.scalars(select(Link)).all()) == 1

    # Blocked neighbor RiskState updated immediately
    assert local_session.get(RiskState, blocked.key).blocked is True

    # Resolving blocker to Done immediately clears blocked flag on neighbor
    LocalJiraService.transition_issue(local_session, blocker.key, "61", actor=pm, settings=local_settings)
    assert local_session.get(RiskState, blocked.key).blocked is False

    # sync_issue preserves affects version & does not duplicate inverse link
    local_session.add(IssueVersion(issue_key=blocked.key, version_id=21, relation_type="affects"))
    local_session.commit()
    client = LocalJiraClient(local_settings, session=local_session, actor=pm)
    sync_issue(local_session, client, blocked.key, local_settings)
    assert len(local_session.scalars(select(Link)).all()) == 1
    assert len(local_session.scalars(select(IssueVersion).where(IssueVersion.issue_key == blocked.key, IssueVersion.relation_type == "affects")).all()) == 1

    left = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Relate left", actor=pm, settings=local_settings
    )
    right = LocalJiraService.create_issue(
        local_session, project_key="DEMO", summary="Relate right", actor=pm, settings=local_settings
    )
    LocalJiraService.add_link(local_session, left.key, right.key, "relates to", actor=pm, settings=local_settings)
    local_session.commit()
    sync_issue(local_session, client, right.key, local_settings)
    sync_issue(local_session, client, left.key, local_settings)
    relate_rows = local_session.scalars(select(Link).where(Link.type_std == "Relate")).all()
    assert len(relate_rows) == 1
    assert len(local_session.scalars(select(Link).where(Link.type_std == "Block")).all()) == 1


def test_local_issue_raw_passes_jira_transformer_and_duckdb_sync(tmp_path, local_session, local_settings, demo_setup):
    from early_risk_detection.data.etl.loader import DuckDBLoader
    from early_risk_detection.data.etl.transformer import JiraTransformer

    pm = demo_setup["pm"]
    dev = demo_setup["dev"]
    a = LocalJiraService.create_issue(
        local_session,
        project_key="DEMO",
        summary="Issue A",
        description="Detail paragraph",
        assignee=dev,
        reporter=pm,
        actor=pm,
        settings=local_settings,
    )
    b = LocalJiraService.create_issue(
        local_session,
        project_key="DEMO",
        summary="Issue B",
        assignee=pm,
        reporter=pm,
        actor=pm,
        settings=local_settings,
    )
    LocalJiraService.add_link(local_session, a.key, b.key, "blocks", actor=pm, settings=local_settings)
    LocalJiraService.add_comment(local_session, b.key, "Waiting on A", actor=pm, settings=local_settings)
    LocalJiraService.transition_issue(local_session, b.key, "31", actor=dev, settings=local_settings)
    local_session.commit()

    shaped_b = to_dump_shape(b.raw)
    transformed = JiraTransformer().transform_doc(shaped_b, "ERW")
    assert len(transformed["issues"]) == 1
    # Tuple fields: (instance, key, project, summary, it_name, it_theme, p_raw, p_norm, status, resolution, assignee, reporter, ..., has_block_or_depend)
    issue_tup = transformed["issues"][0]
    assert "PM Alice" in issue_tup
    assert issue_tup[-1] is True  # has_block_or_depend
    assert len(transformed["links"]) == 1
    assert len(transformed["comments"]) == 1
    assert len(transformed["changelogs"]) >= 2

    base = tmp_path / "base.duckdb"
    DuckDBLoader(str(base)).init_schema()
    etl_settings = local_settings.model_copy(update={"base_duckdb": str(base), "work_duckdb": str(tmp_path / "work.duckdb")})
    ensure_work_db(etl_settings)
    assert sync_erw_instance(etl_settings, [a.raw, b.raw]) == 2
