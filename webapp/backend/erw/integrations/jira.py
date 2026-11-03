from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

RETRY_STATUSES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_SECONDS: tuple[float, ...] = (2, 4, 8)  # waits between attempts when no Retry-After

_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def _parse_jira_datetime(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = _TZ_NO_COLON.sub(r"\1:\2", s)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class JiraError(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"Jira HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body
        self.retry_after: float | None = None


class _Retryable(JiraError):
    pass


def _wait(retry_state) -> float:
    exc = retry_state.outcome.exception()
    if isinstance(exc, _Retryable) and exc.retry_after is not None:
        return exc.retry_after
    i = min(retry_state.attempt_number - 1, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[i]


class JiraClient:
    def __init__(self, base_url: str, email: str, token: str, *, http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._auth = (email, token)
        self._http = http or httpx.Client(timeout=30)

    def _send(self, method: str, path: str, **kw) -> httpx.Response:
        def once() -> httpx.Response:
            resp = self._http.request(
                method, f"{self.base_url}{path}", auth=self._auth, headers={"Accept": "application/json"}, **kw
            )
            if resp.status_code in RETRY_STATUSES:
                err = _Retryable(resp.status_code, resp.text)
                try:
                    err.retry_after = float(resp.headers["Retry-After"])
                except (KeyError, ValueError):
                    pass
                raise err
            return resp

        try:
            for attempt in Retrying(
                retry=retry_if_exception_type(_Retryable),
                stop=stop_after_attempt(MAX_ATTEMPTS),
                wait=_wait,
                reraise=True,
            ):
                with attempt:
                    return once()
        except _Retryable as e:
            raise JiraError(e.status, e.body) from None
        raise AssertionError("unreachable")  # pragma: no cover

    def _json(self, method: str, path: str, *, none_on_404: bool = False, **kw):
        resp = self._send(method, path, **kw)
        if resp.status_code == 404 and none_on_404:
            return None
        if resp.status_code >= 400:
            raise JiraError(resp.status_code, resp.text)
        return resp.json() if resp.content else {}

    def get_issue(self, key: str) -> dict | None:
        issue = self._json("GET", f"/rest/api/3/issue/{key}", none_on_404=True, params={"expand": "changelog"})
        if issue is None:
            return None
        cl = issue.setdefault("changelog", {"histories": []})
        hist = cl.setdefault("histories", [])
        total = cl.get("total", len(hist))
        while total > len(hist):
            page = self._json("GET", f"/rest/api/3/issue/{key}/changelog", params={"startAt": len(hist)})
            values = page.get("values", [])
            if not values:
                break
            hist.extend(values)
        return issue

    def search_keys(self, jql: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            body: dict = {"jql": jql, "fields": ["key"], "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            data = self._json("POST", "/rest/api/3/search/jql", json=body)
            keys.extend(i["key"] for i in data.get("issues", []))
            token = data.get("nextPageToken")
            if data.get("isLast", True) or not token:
                return keys

    def get_sprint(self, sprint_id: int) -> dict | None:
        return self._json("GET", f"/rest/agile/1.0/sprint/{sprint_id}", none_on_404=True)

    def get_version(self, version_id: int) -> dict | None:
        return self._json("GET", f"/rest/api/3/version/{version_id}", none_on_404=True)

    def board_ids(self, project_key: str) -> list[int]:
        ids: list[int] = []
        while True:
            data = self._json(
                "GET", "/rest/agile/1.0/board", params={"projectKeyOrId": project_key, "startAt": len(ids), "maxResults": 50}
            )
            values = data.get("values", [])
            ids.extend(int(b["id"]) for b in values)
            if data.get("isLast", True) or not values:
                return ids

    def project_id(self, key: str) -> int:
        return int(self._json("GET", f"/rest/api/3/project/{key}")["id"])

    def myself(self) -> dict:
        return self._json("GET", "/rest/api/3/myself")

    def register_webhook(self, url: str, events: list[str], jql: str) -> dict:
        body = {
            "name": "early-risk",
            "url": url,
            "events": events,
            "filters": {"issue-related-events-section": jql},
            "excludeBody": False,
        }
        return self._json("POST", "/rest/webhooks/1.0/webhook", json=body)

    def get_issue_updated(self, key: str) -> datetime:
        data = self._json("GET", f"/rest/api/3/issue/{key}", params={"fields": "updated"})
        fields = data.get("fields", {}) if isinstance(data, dict) else {}
        updated_raw = fields.get("updated")
        if not updated_raw:
            raise JiraError(404, f"Updated timestamp not found for issue {key}")
        return _parse_jira_datetime(updated_raw)

    def update_issue(self, key: str, fields: dict) -> None:
        self._json("PUT", f"/rest/api/3/issue/{key}", json={"fields": fields})

    def add_comment(self, key: str, body: str) -> None:
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            }
        }
        self._json("POST", f"/rest/api/3/issue/{key}/comment", json=payload)

    def find_transition_id(self, key: str, target_status_name: str) -> str | None:
        data = self._json("GET", f"/rest/api/3/issue/{key}/transitions")
        transitions = data.get("transitions", []) if isinstance(data, dict) else []
        target = target_status_name.strip().lower()
        for t in transitions:
            to_name = t.get("to", {}).get("name", "").strip().lower()
            if to_name == target:
                return str(t["id"])
        for t in transitions:
            trans_name = t.get("name", "").strip().lower()
            if trans_name == target:
                return str(t["id"])
        return None

    def transition_issue(self, key: str, transition_id: str) -> None:
        self._json("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": transition_id}})
