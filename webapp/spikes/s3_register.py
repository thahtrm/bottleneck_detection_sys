"""Spike S3: register / list / delete the admin webhook on a Jira Cloud site, and print custom field ids.

Env: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, S3_SECRET, S3_PUBLIC_URL (e.g. https://<static>.ngrok-free.app)
Run: .venv/bin/python webapp/spikes/s3_register.py register --jql "project = DEMO"
     .venv/bin/python webapp/spikes/s3_register.py list | delete <id> | fields
"""
from __future__ import annotations

import argparse
import json
import os

import httpx

EVENTS = [
    "jira:issue_created", "jira:issue_updated", "jira:issue_deleted",
    "issuelink_created", "issuelink_deleted",
    "sprint_created", "sprint_updated", "sprint_started", "sprint_closed",
    "jira:version_created", "jira:version_updated", "jira:version_released",
]


def client() -> httpx.Client:
    return httpx.Client(base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
                        auth=(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]),
                        headers={"Accept": "application/json"}, timeout=30)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--jql", required=True)
    sub.add_parser("list")
    d = sub.add_parser("delete")
    d.add_argument("id")
    sub.add_parser("fields")
    a = ap.parse_args()
    with client() as c:
        if a.cmd == "register":
            url = f"{os.environ['S3_PUBLIC_URL'].rstrip('/')}/webhooks/jira/{os.environ['S3_SECRET']}"
            body = {"name": "early-risk-s3", "url": url, "events": EVENTS,
                    "filters": {"issue-related-events-section": a.jql}, "excludeBody": False}
            resp = c.post("/rest/webhooks/1.0/webhook", json=body)
        elif a.cmd == "list":
            resp = c.get("/rest/webhooks/1.0/webhook")
        elif a.cmd == "delete":
            resp = c.delete(f"/rest/webhooks/1.0/webhook/{a.id}")
        else:
            resp = c.get("/rest/api/3/field")
            resp.raise_for_status()
            for f in resp.json():
                if any(k in f["name"].lower() for k in ("sprint", "story point", "flagged", "epic")):
                    print(f["id"], "|", f["name"])
            return
        print(resp.status_code)
        if resp.content:
            out = resp.json()
            if isinstance(out, dict):
                out.pop("url", None)  # contains the secret
            elif isinstance(out, list):
                for w in out:
                    w.pop("url", None)
            print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
