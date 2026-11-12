"""Spike S3: turn captured webhook payloads (var/s3/) and one REST issue into anonymised test fixtures.

Run: .venv/bin/python webapp/spikes/s3_fixtures.py --out webapp/backend/tests/fixtures/jira
Env (for the REST capture): JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from pathlib import Path

import httpx

FAKE_HOST = "example.atlassian.net"
FAKE_NAME = "Nguyễn Văn An"
DROP_KEYS = {"avatarUrls", "emailAddress", "iconUrl", "avatarId"}


def anonymise(obj, host: str, accounts: dict[str, str]):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in DROP_KEYS:
                continue
            if k == "accountId" and isinstance(v, str):
                out[k] = accounts.setdefault(v, f"acc-{len(accounts) + 1}")
            elif k == "displayName" and isinstance(v, str) and "accountId" in obj:
                out[k] = FAKE_NAME
            else:
                out[k] = anonymise(v, host, accounts)
        return out
    if isinstance(obj, list):
        return [anonymise(v, host, accounts) for v in obj]
    if isinstance(obj, str):
        s = obj.replace(host, FAKE_HOST)
        for real, fake in accounts.items():
            s = s.replace(real, fake)
        return s
    return obj


def collect_names(obj, names: set[str]) -> None:
    """Display names of every user object, so free-text copies (changelog toString) can be replaced too."""
    if isinstance(obj, dict):
        if "accountId" in obj and isinstance(obj.get("displayName"), str):
            names.add(obj["displayName"])
        for v in obj.values():
            collect_names(v, names)
    elif isinstance(obj, list):
        for v in obj:
            collect_names(v, names)


def scrub_names(obj, names: set[str]):
    if isinstance(obj, dict):
        return {k: scrub_names(v, names) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_names(v, names) for v in obj]
    if isinstance(obj, str):
        for n in names:
            obj = obj.replace(n, FAKE_NAME)
    return obj


def first(pattern: str) -> dict:
    return json.load(open(sorted(glob.glob(pattern))[0]))["payload"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="var/s3")
    ap.add_argument("--out", required=True)
    ap.add_argument("--issue", default="DEMO-1")
    a = ap.parse_args()
    host = re.sub(r"^https?://", "", os.environ["JIRA_BASE_URL"]).rstrip("/")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    accounts: dict[str, str] = {}

    status_upd = next(json.load(open(f))["payload"] for f in sorted(glob.glob(f"{a.src}/*jira_issue_updated.json"))
                      if any(i.get("fieldId") == "status"
                             for i in (json.load(open(f))["payload"].get("changelog") or {}).get("items", [])))
    picks = {
        "wh_issue_created": first(f"{a.src}/*jira_issue_created.json"),
        "wh_issue_updated_status": status_upd,
        "wh_issuelink_created": first(f"{a.src}/*issuelink_created.json"),
        "wh_sprint_updated": first(f"{a.src}/*sprint_updated.json"),
        "wh_version_updated": first(f"{a.src}/*jira_version_updated.json"),
    }
    with httpx.Client(base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
                      auth=(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]), timeout=60) as c:
        r = c.get(f"/rest/api/3/issue/{a.issue}", params={"expand": "changelog"})
        r.raise_for_status()
        picks["rest_issue_demo1"] = r.json()
    names: set[str] = set()
    collect_names(picks, names)
    for name, payload in picks.items():
        clean = scrub_names(anonymise(payload, host, accounts), names)
        (out / f"{name}.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2))
        print("wrote", out / f"{name}.json")


if __name__ == "__main__":
    main()
