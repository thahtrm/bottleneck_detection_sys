"""Spike S3: drive a scripted scenario on the DEMO project so every webhook type fires.

Env: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.  Board id and project key via args.
Run: .venv/bin/python webapp/spikes/s3_drive.py --project DEMO --board 3
Prints one line per action with its wall-clock time so latency can be matched with var/s3/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import time

import httpx

SPRINT_FIELD = "customfield_10020"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="DEMO")
    ap.add_argument("--board", type=int, required=True)
    ap.add_argument("--pause", type=float, default=4.0)
    a = ap.parse_args()
    c = httpx.Client(base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
                     auth=(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]),
                     headers={"Accept": "application/json"}, timeout=60)

    def step(name: str, resp: httpx.Response) -> httpx.Response:
        print(f"{time.time():.3f} {name}: {resp.status_code}", flush=True)
        if resp.status_code >= 400:
            print("   ", resp.text[:300])
        time.sleep(a.pause)
        return resp

    def issue(summary: str) -> str:
        r = step(f"create '{summary}'", c.post("/rest/api/3/issue", json={"fields": {
            "project": {"key": a.project}, "issuetype": {"name": "Task"}, "summary": summary}}))
        return r.json()["key"]

    k1 = issue("Tích hợp cổng thanh toán VNPay")
    k2 = issue("Payment gateway sandbox credentials")
    k3 = issue("Viết test đối soát <refund> & 🚀")

    now = dt.datetime.now(dt.UTC)
    sp = step("sprint_created", c.post("/rest/agile/1.0/sprint", json={
        "name": "Sprint S3", "originBoardId": a.board,
        "startDate": now.isoformat(), "endDate": (now + dt.timedelta(days=10)).isoformat()})).json()
    step("issues -> sprint", c.post(f"/rest/agile/1.0/sprint/{sp['id']}/issue", json={"issues": [k1, k2, k3]}))
    step("sprint_started", c.post(f"/rest/agile/1.0/sprint/{sp['id']}", json={"state": "active"}))
    step("sprint_updated (end date)", c.post(f"/rest/agile/1.0/sprint/{sp['id']}", json={
        "endDate": (now + dt.timedelta(days=7)).isoformat()}))

    step("duedate", c.put(f"/rest/api/3/issue/{k1}", json={"fields": {"duedate": (now.date() - dt.timedelta(days=1)).isoformat()}}))
    step("story points", c.put(f"/rest/api/3/issue/{k2}", json={"fields": {"customfield_10016": 5}}))
    step("assignee", c.put(f"/rest/api/3/issue/{k1}/assignee", json={"accountId": c.get("/rest/api/3/myself").json()["accountId"]}))

    trans = c.get(f"/rest/api/3/issue/{k1}/transitions").json()["transitions"]
    print("    transitions:", [(t["id"], t["name"]) for t in trans])
    prog = next((t for t in trans if t["to"]["statusCategory"]["key"] == "indeterminate"), None)
    if prog:
        step("status -> In Progress", c.post(f"/rest/api/3/issue/{k1}/transitions", json={"transition": {"id": prog["id"]}}))

    step("issuelink_created (k1 is blocked by k2)", c.post("/rest/api/3/issueLink", json={
        "type": {"name": "Blocks"}, "inwardIssue": {"key": k1}, "outwardIssue": {"key": k2}}))

    pid = c.get(f"/rest/api/3/project/{a.project}").json()["id"]
    v = step("version_created", c.post("/rest/api/3/version", json={
        "name": "v0.1-s3", "projectId": int(pid), "releaseDate": (now.date() + dt.timedelta(days=14)).isoformat()})).json()
    step("fixVersion on k3", c.put(f"/rest/api/3/issue/{k3}", json={"update": {"fixVersions": [{"add": {"id": v["id"]}}]}}))
    step("version_updated (release date)", c.put(f"/rest/api/3/version/{v['id']}", json={
        "releaseDate": (now.date() + dt.timedelta(days=10)).isoformat()}))

    links = c.get(f"/rest/api/3/issue/{k1}", params={"fields": "issuelinks"}).json()["fields"]["issuelinks"]
    if links:
        step("issuelink_deleted", c.delete(f"/rest/api/3/issueLink/{links[0]['id']}"))
    step("issue_deleted (k3)", c.delete(f"/rest/api/3/issue/{k3}"))
    print("keys:", k1, k2, k3, "sprint:", sp["id"], "version:", v["id"])


if __name__ == "__main__":
    main()
