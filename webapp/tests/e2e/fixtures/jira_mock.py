from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from erw import jobs
from erw.integrations import jira as jira_mod
from erw.integrations.jira import JiraError, Transition

from .capabilities import has_local_jira_client, has_setting, require_capability


def _iso_jira(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def make_minimal_v3_issue(
    key: str = "DEMO-1",
    *,
    summary: str = "Sample Jira Cloud issue",
    status_name: str = "To Do",
    status_category: str = "new",
    priority_name: str = "Medium",
    issuetype_name: str = "Story",
    duedate: str | None = "2026-12-01",
    updated: datetime | None = None,
) -> dict[str, Any]:
    now = updated or datetime(2026, 11, 20, 9, 0, 0, tzinfo=UTC)
    created = now - timedelta(days=3)
    return {
        "id": str(abs(hash(key)) % 90000 + 10000),
        "key": key,
        "fields": {
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": f"Description for {key}"}]}
                ],
            },
            "issuetype": {"name": issuetype_name, "subtask": issuetype_name == "Sub-task"},
            "priority": {"name": priority_name},
            "status": {
                "name": status_name,
                "id": "10001",
                "statusCategory": {"id": 2, "key": status_category, "name": status_name},
            },
            "resolution": None,
            "assignee": {
                "accountId": "cloud-pm",
                "displayName": "Cloud PM",
                "name": "Cloud PM",
            },
            "reporter": {
                "accountId": "cloud-admin",
                "displayName": "Cloud Admin",
                "name": "Cloud Admin",
            },
            "creator": {
                "accountId": "cloud-admin",
                "displayName": "Cloud Admin",
                "name": "Cloud Admin",
            },
            "duedate": duedate,
            "created": _iso_jira(created),
            "updated": _iso_jira(now),
            "resolutiondate": None,
            "labels": [],
            "components": [],
            "fixVersions": [],
            "versions": [],
            "issuelinks": [],
            "comment": {"comments": [], "total": 0},
            "timetracking": {},
            "customfield_10016": 3.0,
            "customfield_10020": [],
        },
        "changelog": {"histories": [], "total": 0},
    }


class MockJiraCloudServer:
    """Stateful in-memory Jira Cloud REST v3 + Agile 1.0 server backed by respx."""

    def __init__(self, base_url: str = "https://example.atlassian.net") -> None:
        self.base_url = base_url.rstrip("/")
        self.issues: dict[str, dict[str, Any]] = {}
        self.transitions: dict[str, list[dict[str, Any]]] = {}
        self.sprints: dict[int, dict[str, Any]] = {
            101: {"id": 101, "name": "Sprint 101", "state": "active", "originBoardId": 3}
        }
        self.versions: dict[int, dict[str, Any]] = {
            201: {"id": "201", "name": "v1.0", "released": False, "projectId": 10002}
        }
        self.boards: dict[str, list[dict[str, Any]]] = {
            "DEMO": [{"id": 3, "name": "DEMO board", "type": "scrum"}]
        }
        self.projects: dict[str, dict[str, Any]] = {
            "DEMO": {"id": "10002", "key": "DEMO", "name": "Demo Project"}
        }
        self.myself_payload: dict[str, Any] = {
            "accountId": "cloud-bot",
            "displayName": "Cloud Bot",
            "name": "Cloud Bot",
            "timeZone": "Asia/Ho_Chi_Minh",
        }
        self.webhooks: list[dict[str, Any]] = []
        self.request_log: list[tuple[str, str]] = []
        self._seq = 1000
        self._now = datetime(2026, 11, 25, 10, 0, 0, tzinfo=UTC)
        self._router: respx.MockRouter | None = None

    def _next_time(self) -> datetime:
        self._now += timedelta(seconds=5)
        return self._now

    def _next_id(self) -> str:
        self._seq += 1
        return str(self._seq)

    def seed_issue(
        self,
        key: str = "DEMO-1",
        *,
        transitions: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        issue = make_minimal_v3_issue(key=key, **kwargs)
        self.issues[key] = issue
        self.transitions[key] = transitions or [
            {
                "id": "11",
                "name": "To Do",
                "to": {"name": "To Do", "statusCategory": {"key": "new", "name": "To Do"}},
            },
            {
                "id": "21",
                "name": "In Progress",
                "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate", "name": "In Progress"}},
            },
            {
                "id": "31",
                "name": "Done",
                "to": {"name": "Done", "statusCategory": {"key": "done", "name": "Done"}},
            },
        ]
        return issue

    def mount(self) -> respx.MockRouter:
        router = respx.mock(base_url=self.base_url, assert_all_called=False)

        router.get(path="/rest/api/3/myself").mock(side_effect=self._handle_myself)
        router.get(path__regex=r"^/rest/api/3/project/[^/]+$").mock(side_effect=self._handle_project)
        router.get(path="/rest/agile/1.0/board").mock(side_effect=self._handle_boards)
        router.get(path__regex=r"^/rest/agile/1.0/sprint/\d+$").mock(side_effect=self._handle_sprint)
        router.get(path__regex=r"^/rest/api/3/version/\d+$").mock(side_effect=self._handle_version)
        router.post(path="/rest/api/3/search/jql").mock(side_effect=self._handle_search_jql)
        router.post(path="/rest/webhooks/1.0/webhook").mock(side_effect=self._handle_webhook)

        router.get(path__regex=r"^/rest/api/3/issue/[^/]+$").mock(side_effect=self._handle_get_issue)
        router.get(path__regex=r"^/rest/api/3/issue/[^/]+/changelog$").mock(side_effect=self._handle_changelog)
        router.put(path__regex=r"^/rest/api/3/issue/[^/]+$").mock(side_effect=self._handle_update_issue)
        router.post(path__regex=r"^/rest/api/3/issue/[^/]+/comment$").mock(side_effect=self._handle_add_comment)
        router.get(path__regex=r"^/rest/api/3/issue/[^/]+/transitions$").mock(side_effect=self._handle_get_transitions)
        router.post(path__regex=r"^/rest/api/3/issue/[^/]+/transitions$").mock(side_effect=self._handle_post_transition)

        self._router = router
        return router

    def start(self) -> respx.MockRouter:
        if self._router is None:
            self.mount()
        assert self._router is not None
        self._router.start()
        return self._router

    def stop(self) -> None:
        if self._router is not None:
            self._router.stop()

    def _record(self, request: httpx.Request) -> None:
        self.request_log.append((request.method, request.url.path))

    def _handle_myself(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        return httpx.Response(200, json=self.myself_payload)

    def _handle_project(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        key = request.url.path.rsplit("/", 1)[-1]
        proj = self.projects.get(key)
        if not proj:
            return httpx.Response(404, json={"errorMessages": [f"Project {key} not found"]})
        return httpx.Response(200, json=proj)

    def _handle_boards(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        proj_key = request.url.params.get("projectKeyOrId", "")
        boards = self.boards.get(proj_key, [])
        return httpx.Response(200, json={"values": boards, "isLast": True})

    def _handle_sprint(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        sprint_id = int(request.url.path.rsplit("/", 1)[-1])
        sprint = self.sprints.get(sprint_id)
        if not sprint:
            return httpx.Response(404, json={"errorMessages": ["Sprint not found"]})
        return httpx.Response(200, json=sprint)

    def _handle_version(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        version_id = int(request.url.path.rsplit("/", 1)[-1])
        version = self.versions.get(version_id)
        if not version:
            return httpx.Response(404, json={"errorMessages": ["Version not found"]})
        return httpx.Response(200, json=version)

    def _handle_search_jql(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        keys = [{"key": k} for k in sorted(self.issues.keys())]
        return httpx.Response(200, json={"issues": keys, "isLast": True})

    def _handle_webhook(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        wh = {"id": self._next_id(), **body}
        self.webhooks.append(wh)
        return httpx.Response(201, json=wh)

    def _handle_get_issue(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        key = request.url.path.rsplit("/", 1)[-1]
        issue = self.issues.get(key)
        if not issue:
            return httpx.Response(404, json={"errorMessages": [f"Issue {key} does not exist"]})
        return httpx.Response(200, json=copy.deepcopy(issue))

    def _handle_changelog(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        parts = request.url.path.split("/")
        key = parts[-2]
        issue = self.issues.get(key)
        if not issue:
            return httpx.Response(404, json={"errorMessages": [f"Issue {key} does not exist"]})
        histories = issue.get("changelog", {}).get("histories", [])
        return httpx.Response(200, json={"values": copy.deepcopy(histories), "isLast": True})

    def _handle_update_issue(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        key = request.url.path.rsplit("/", 1)[-1]
        issue = self.issues.get(key)
        if not issue:
            return httpx.Response(404, json={"errorMessages": [f"Issue {key} does not exist"]})
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        fields_patch = payload.get("fields", {})
        fields = issue.setdefault("fields", {})
        now_iso = _iso_jira(self._next_time())
        items = []
        for field_name, new_val in fields_patch.items():
            old_val = fields.get(field_name)
            fields[field_name] = new_val
            old_str = old_val.get("name") if isinstance(old_val, dict) else (None if old_val is None else str(old_val))
            new_str = new_val.get("name") if isinstance(new_val, dict) else (None if new_val is None else str(new_val))
            items.append(
                {
                    "field": field_name,
                    "fieldtype": "jira",
                    "from": old_str,
                    "fromString": old_str,
                    "to": new_str,
                    "toString": new_str,
                }
            )
        fields["updated"] = now_iso
        if items:
            histories = issue.setdefault("changelog", {}).setdefault("histories", [])
            histories.append(
                {
                    "id": self._next_id(),
                    "created": now_iso,
                    "author": self.myself_payload,
                    "items": items,
                }
            )
            issue["changelog"]["total"] = len(histories)
        return httpx.Response(204)

    def _handle_add_comment(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        key = request.url.path.split("/")[-2]
        issue = self.issues.get(key)
        if not issue:
            return httpx.Response(404, json={"errorMessages": [f"Issue {key} does not exist"]})
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        now_iso = _iso_jira(self._next_time())
        comment = {
            "id": self._next_id(),
            "author": self.myself_payload,
            "body": payload.get("body"),
            "created": now_iso,
            "updated": now_iso,
        }
        c_wrap = issue["fields"].setdefault("comment", {"comments": [], "total": 0})
        c_wrap["comments"].append(comment)
        c_wrap["total"] = len(c_wrap["comments"])
        issue["fields"]["updated"] = now_iso
        return httpx.Response(201, json=comment)

    def _handle_get_transitions(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        key = request.url.path.split("/")[-2]
        if key not in self.issues:
            return httpx.Response(404, json={"errorMessages": [f"Issue {key} does not exist"]})
        return httpx.Response(200, json={"transitions": copy.deepcopy(self.transitions.get(key, []))})

    def _handle_post_transition(self, request: httpx.Request) -> httpx.Response:
        self._record(request)
        key = request.url.path.split("/")[-2]
        issue = self.issues.get(key)
        if not issue:
            return httpx.Response(404, json={"errorMessages": [f"Issue {key} does not exist"]})
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        tid = str((payload.get("transition") or {}).get("id") or "")
        match = next((t for t in self.transitions.get(key, []) if str(t["id"]) == tid), None)
        if not match:
            return httpx.Response(400, json={"errorMessages": [f"Transition {tid} not valid for {key}"]})

        now_iso = _iso_jira(self._next_time())
        old_status = issue["fields"]["status"]["name"]
        new_status = match["to"]["name"]
        cat_key = (match["to"].get("statusCategory") or {}).get("key", "indeterminate")
        issue["fields"]["status"] = {
            "name": new_status,
            "id": tid,
            "statusCategory": {"key": cat_key, "name": new_status},
        }
        if cat_key == "done":
            issue["fields"]["resolution"] = {"name": "Done"}
            issue["fields"]["resolutiondate"] = now_iso
        else:
            issue["fields"]["resolution"] = None
            issue["fields"]["resolutiondate"] = None
        issue["fields"]["updated"] = now_iso

        histories = issue.setdefault("changelog", {}).setdefault("histories", [])
        histories.append(
            {
                "id": self._next_id(),
                "created": now_iso,
                "author": self.myself_payload,
                "items": [
                    {
                        "field": "status",
                        "fieldtype": "jira",
                        "from": old_status,
                        "fromString": old_status,
                        "to": new_status,
                        "toString": new_status,
                    }
                ],
            }
        )
        issue["changelog"]["total"] = len(histories)
        return httpx.Response(204)


class FakeJira:
    """In-memory 13-method test double implementing the full JiraClient contract."""

    def __init__(self) -> None:
        self.issues: dict[str, dict[str, Any]] = {}
        self.sprints: dict[int, dict[str, Any]] = {}
        self.versions: dict[int, dict[str, Any]] = {}
        self.transitions: dict[str, list[Transition]] = {}
        self.errors: dict[str, Exception] = {}
        self.get_issue_calls: list[str] = []
        self.search_jqls: list[str] = []
        self.search_result: list[str] = []
        self.boards: dict[str, list[int]] = {"DEMO": [3]}
        self.project_ids: dict[str, int] = {"DEMO": 10002}
        self.tz = "Asia/Saigon"
        self.comments: dict[str, list[str | dict]] = {}
        self.webhooks: list[dict[str, Any]] = []

    def get_issue(self, key: str) -> dict | None:
        self.get_issue_calls.append(key)
        if key in self.errors:
            raise self.errors[key]
        return copy.deepcopy(self.issues.get(key))

    def search_keys(self, jql: str) -> list[str]:
        self.search_jqls.append(jql)
        return list(self.search_result)

    def get_sprint(self, sprint_id: int) -> dict | None:
        return copy.deepcopy(self.sprints.get(sprint_id))

    def get_version(self, version_id: int) -> dict | None:
        return copy.deepcopy(self.versions.get(version_id))

    def board_ids(self, project_key: str) -> list[int]:
        return list(self.boards.get(project_key, []))

    def project_id(self, key: str) -> int:
        if key not in self.project_ids:
            raise JiraError(404, f"Project {key} not found")
        return self.project_ids[key]

    def myself(self) -> dict:
        return {"accountId": "fake-bot", "displayName": "Fake Bot", "name": "Fake Bot", "timeZone": self.tz}

    def register_webhook(self, url: str, events: list[str], jql: str) -> dict:
        wh = {"id": str(len(self.webhooks) + 1), "url": url, "events": list(events), "jql": jql}
        self.webhooks.append(wh)
        return wh

    def get_issue_updated(self, key: str) -> datetime:
        issue = self.issues.get(key)
        if not issue:
            raise JiraError(404, f"Issue {key} not found")
        updated = (issue.get("fields") or {}).get("updated")
        if not updated:
            raise JiraError(404, f"Updated timestamp missing for {key}")
        return jira_mod._parse_jira_datetime(updated)

    def update_issue(self, key: str, fields: dict) -> None:
        issue = self.issues.get(key)
        if not issue:
            raise JiraError(404, f"Issue {key} not found")
        issue.setdefault("fields", {}).update(copy.deepcopy(fields))
        issue["fields"]["updated"] = _iso_jira(datetime.now(UTC))

    def add_comment(self, key: str, body: str | dict) -> None:
        if key not in self.issues:
            raise JiraError(404, f"Issue {key} not found")
        self.comments.setdefault(key, []).append(body)

    def get_transitions(self, key: str) -> list[Transition]:
        if key not in self.issues:
            raise JiraError(404, f"Issue {key} not found")
        return list(self.transitions.get(key, []))

    def transition_issue(self, key: str, transition_id: str) -> None:
        if key not in self.issues:
            raise JiraError(404, f"Issue {key} not found")
        choices = self.transitions.get(key, [])
        match = next((t for t in choices if t.id == str(transition_id)), None)
        if match is None:
            raise JiraError(400, f"Invalid transition {transition_id}")
        self.issues[key]["fields"]["status"] = {
            "name": match.to_status,
            "statusCategory": {"key": match.to_category or "indeterminate"},
        }
        self.issues[key]["fields"]["updated"] = _iso_jira(datetime.now(UTC))


@pytest.fixture
def mock_jira_cloud(monkeypatch):
    """Mount stateful respx MockJiraCloudServer and zero JiraClient retry backoff."""
    monkeypatch.setattr(jira_mod, "BACKOFF_SECONDS", (0, 0, 0))
    server = MockJiraCloudServer()
    server.seed_issue("DEMO-1")
    with server.mount():
        yield server


@pytest.fixture
def fake_jira():
    fake = FakeJira()
    jobs.set_client(fake)
    yield fake
    jobs.set_client(None)


@pytest.fixture(params=["local", "jira_cloud"])
def dual_mode_env(request):
    mode = request.param
    if mode == "local":
        require_capability(
            has_local_jira_client() and has_setting("jira_mode"),
            "LocalJiraClient / Settings.jira_mode not implemented yet",
        )
    return mode
