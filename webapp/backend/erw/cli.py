from __future__ import annotations

import argparse

from erw import jobs
from erw.db import SessionLocal, init_db, make_engine, utcnow
from erw.ingest.sync import catch_up
from erw.integrations.jira import JiraClient
from erw.settings import get_settings

WEBHOOK_EVENTS = [
    "jira:issue_created", "jira:issue_updated", "jira:issue_deleted",
    "issuelink_created", "issuelink_deleted",
    "sprint_created", "sprint_updated", "sprint_started", "sprint_closed",
    "jira:version_created", "jira:version_updated", "jira:version_released",
]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="erw")
    parser.add_argument("command", choices=["init-db", "catch-up", "register-webhook"])
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "init-db":
        init_db(make_engine(settings.db_url))
        print("database initialised")
        return 0

    client = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
    if args.command == "register-webhook":
        url = f"{settings.public_base_url}/webhooks/jira/{settings.jira_webhook_secret}"
        jql = "project in (" + ", ".join(settings.jira_projects) + ")"
        client.register_webhook(url, WEBHOOK_EVENTS, jql)
        print(f"webhook registered: {settings.public_base_url}/webhooks/jira/<secret>")
        return 0

    engine = make_engine(settings.db_url)
    init_db(engine)
    jobs.configure(settings, engine)
    with SessionLocal(bind=engine) as session:
        print(f"synced {catch_up(session, client, settings, utcnow())} issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
