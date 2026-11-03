import httpx
import pytest
import respx

from erw.integrations.jira import JiraClient, JiraError

BASE = "https://example.atlassian.net"


@pytest.fixture
def jira(monkeypatch):
    monkeypatch.setattr("erw.integrations.jira.BACKOFF_SECONDS", (0, 0, 0))
    with httpx.Client() as http:
        yield JiraClient(BASE, "bot@example.com", "tok", http=http)


def _hist(n, start=0):
    return [{"id": str(start + i), "created": "2026-01-01T00:00:00.000+0000", "items": []} for i in range(n)]


@respx.mock
def test_get_issue_fetches_remaining_changelog_pages(jira):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-1").mock(
        return_value=httpx.Response(
            200, json={"key": "DEMO-1", "fields": {}, "changelog": {"total": 150, "histories": _hist(100)}}
        )
    )
    route = respx.get(f"{BASE}/rest/api/3/issue/DEMO-1/changelog").mock(
        return_value=httpx.Response(200, json={"values": _hist(50, 100), "isLast": True, "total": 150})
    )
    issue = jira.get_issue("DEMO-1")
    assert len(issue["changelog"]["histories"]) == 150
    assert route.calls.last.request.url.params["startAt"] == "100"


@respx.mock
def test_retry_on_429_then_success(jira):
    route = respx.get(f"{BASE}/rest/api/3/myself").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={"accountId": "a"})]
    )
    assert jira.myself() == {"accountId": "a"}
    assert route.call_count == 2


@respx.mock
def test_retry_gives_up_after_four_attempts(jira):
    route = respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(JiraError) as e:
        jira.myself()
    assert e.value.status == 503 and route.call_count == 4


@respx.mock
def test_non_retryable_error_raises_immediately(jira):
    route = respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, text="no"))
    with pytest.raises(JiraError) as e:
        jira.myself()
    assert e.value.status == 401 and e.value.body == "no" and route.call_count == 1


@respx.mock
def test_get_issue_404_returns_none(jira):
    respx.get(f"{BASE}/rest/api/3/issue/DEMO-9").mock(return_value=httpx.Response(404, json={}))
    assert jira.get_issue("DEMO-9") is None


@respx.mock
def test_search_keys_pages_with_next_page_token(jira):
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        side_effect=[
            httpx.Response(200, json={"issues": [{"key": "DEMO-1"}], "nextPageToken": "t2", "isLast": False}),
            httpx.Response(200, json={"issues": [{"key": "DEMO-2"}], "isLast": True}),
        ]
    )
    assert jira.search_keys("project = DEMO") == ["DEMO-1", "DEMO-2"]
    assert b"t2" in route.calls.last.request.content


@respx.mock
def test_get_sprint_version_and_404(jira):
    respx.get(f"{BASE}/rest/agile/1.0/sprint/2").mock(return_value=httpx.Response(200, json={"id": 2}))
    respx.get(f"{BASE}/rest/api/3/version/7").mock(return_value=httpx.Response(404))
    assert jira.get_sprint(2) == {"id": 2}
    assert jira.get_version(7) is None


@respx.mock
def test_register_webhook(jira):
    route = respx.post(f"{BASE}/rest/webhooks/1.0/webhook").mock(return_value=httpx.Response(201, json={"self": "x"}))
    assert jira.register_webhook("https://h/x", ["jira:issue_created"], "project = DEMO") == {"self": "x"}
    body = route.calls.last.request.content
    assert b"issue-related-events-section" in body and b"project = DEMO" in body
