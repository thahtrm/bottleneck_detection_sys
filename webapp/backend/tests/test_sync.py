import httpx
import respx
from sqlalchemy import select

from erw.ingest.sync import mark_deleted, sync_issue, sync_sprint, sync_version, upsert_issue_json
from erw.integrations.jira import JiraClient
from erw.models import Change, Issue, IssueSprint, IssueVersion, Link, Sprint, Version
from tests.conftest import load_fixture


def test_upsert_new_issue_is_created(session, settings, issue_new):
    r = upsert_issue_json(session, issue_new, settings)
    assert r.kind == "created" and r.key == "DEMO-1"
    i = session.get(Issue, "DEMO-1")
    assert i.status_category == "new" and i.assignee_name == "Nguyễn Văn An" and i.assignee_id == "acc-1"
    assert i.project_key == "DEMO" and str(i.duedate) == "2026-11-02" and i.priority_norm > 0
    assert i.created_at.tzinfo is not None and i.created_at.hour == 17  # 00:07+07 -> 17:07Z previous day
    assert {c.field for c in session.scalars(select(Change))} == {"sprint", "duedate", "assignee"}
    assert [s.sprint_id for s in session.scalars(select(IssueSprint))] == [2]
    assert session.get(Sprint, 2).state == "active"


def test_sync_same_issue_twice_is_unchanged(session, settings, issue_new):
    upsert_issue_json(session, issue_new, settings)
    assert upsert_issue_json(session, issue_new, settings).kind == "unchanged"
    assert len(session.scalars(select(Change)).all()) == 3


def test_update_reports_changed_fields(session, settings, issue_new, issue_updated):
    upsert_issue_json(session, issue_new, settings)
    r = upsert_issue_json(session, issue_updated, settings)
    assert r.kind == "updated" and r.changed_fields == frozenset({"status", "sprint"})
    i = session.get(Issue, "DEMO-1")
    assert i.status_category == "indeterminate" and i.status == "In Progress"
    ch = session.scalars(select(Change).where(Change.change_id == "10100", Change.field == "status")).one()
    assert (ch.from_val, ch.to_val, ch.from_str, ch.to_str) == ("10008", "3", "To Do", "In Progress")
    assert sorted(s.sprint_id for s in session.scalars(select(IssueSprint))) == [2, 3]


def test_untracked_project_ignored(session, settings, issue_new):
    issue_new["key"] = "OTHER-1"
    issue_new["fields"]["project"]["key"] = "OTHER"
    r = upsert_issue_json(session, issue_new, settings)
    assert r.kind == "ignored"
    assert session.get(Issue, "OTHER-1") is None


def test_blocked_link_stored(session, settings, issue_blocked):
    upsert_issue_json(session, issue_blocked, settings)
    link = session.scalars(select(Link)).one()
    assert (link.source_key, link.target_key, link.type_std) == ("DEMO-3", "DEMO-2", "Block")
    # re-sync replaces rather than duplicates
    issue_blocked["fields"]["issuelinks"] = []
    upsert_issue_json(session, issue_blocked, settings)
    assert session.scalars(select(Link)).all() == []


def test_deleted_issue_marked(session, settings, issue_new):
    upsert_issue_json(session, issue_new, settings)
    r = mark_deleted(session, "DEMO-1")
    assert r.kind == "deleted" and session.get(Issue, "DEMO-1").deleted_at is not None


def test_fix_versions_replaced(session, settings, issue_new):
    issue_new["fields"]["fixVersions"] = [{"id": "10000", "name": "v0.1-s3", "released": False, "releaseDate": "2026-11-13"}]
    upsert_issue_json(session, issue_new, settings)
    assert [v.version_id for v in session.scalars(select(IssueVersion))] == [10000]
    assert session.get(Version, 10000).name == "v0.1-s3"


@respx.mock
def test_sync_issue_404_marks_deleted_and_200_upserts(session, settings, issue_new):
    base = settings.jira_base_url
    with httpx.Client() as http:
        client = JiraClient(base, "e", "t", http=http)
        respx.get(f"{base}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(200, json=issue_new))
        assert sync_issue(session, client, "DEMO-1", settings).kind == "created"
        respx.get(f"{base}/rest/api/3/issue/DEMO-1").mock(return_value=httpx.Response(404))
        assert sync_issue(session, client, "DEMO-1", settings).kind == "deleted"
    assert session.get(Issue, "DEMO-1").deleted_at is not None


def test_sync_sprint_and_version_return_issue_keys(session, settings, issue_new):
    upsert_issue_json(session, issue_new, settings)
    raw = load_fixture("wh_sprint_updated")["sprint"]
    assert sync_sprint(session, raw) == ["DEMO-1"]
    assert session.get(Sprint, 2).board_id == 3
    issue_new["fields"]["fixVersions"] = [{"id": "10000", "name": "old"}]
    upsert_issue_json(session, issue_new, settings)
    assert sync_version(session, load_fixture("wh_version_updated")["version"]) == ["DEMO-1"]
    v = session.get(Version, 10000)
    assert v.name == "v0.1-s3" and str(v.release_date) == "2026-11-13" and v.released is False
