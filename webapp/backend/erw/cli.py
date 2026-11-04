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
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")
    subparsers.add_parser("catch-up")
    subparsers.add_parser("register-webhook")
    subparsers.add_parser("run-batch")

    digest_parser = subparsers.add_parser("digest")
    digest_parser.add_argument("--dry-run", action="store_true", help="digest: print instead of sending")

    admin_parser = subparsers.add_parser("create-admin")
    admin_parser.add_argument("--email", required=True, help="admin email")
    admin_parser.add_argument("--name", required=True, help="admin name")
    admin_parser.add_argument("--password", required=True, help="admin password")

    seed_parser = subparsers.add_parser("seed-demo", help="seed demo data and scenarios")
    seed_parser.add_argument("--reset", action="store_true", help="wipe existing demo data before seeding")

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "create-admin":
        import sys

        from sqlalchemy import func, select

        from erw.auth import hash_password
        from erw.models import User

        email = args.email.strip()
        name = args.name.strip()
        password = args.password

        engine = make_engine(settings.db_url)
        init_db(engine)
        with SessionLocal(bind=engine) as session:
            existing = session.execute(
                select(User).where(func.lower(User.email) == email.lower())
            ).scalar_one_or_none()
            if existing is not None:
                print(f"Error: user with email '{email}' already exists", file=sys.stderr)
                return 1
            user = User(
                email=email,
                name=name,
                password_hash=hash_password(password),
                is_admin=True,
                created_at=utcnow(),
            )
            session.add(user)
            session.commit()
            print(f"admin user created: {email}")
            return 0

    if args.command == "seed-demo":
        from erw.demo.seed import seed_demo_data

        engine = make_engine(settings.db_url)
        init_db(engine)
        with SessionLocal(bind=engine) as session:
            summary = seed_demo_data(session, reset=args.reset)
            print(f"Seed demo data completed successfully: {summary}")
        return 0

    if args.command == "init-db":
        init_db(make_engine(settings.db_url))
        print("database initialised")
        return 0

    if args.command == "run-batch":
        from erw.ml.batch import LibraryScorers, make_unload_llm, run_model_batch

        engine = make_engine(settings.db_url)
        init_db(engine)
        with SessionLocal(bind=engine) as session:
            print(run_model_batch(session, settings, utcnow(), LibraryScorers(settings),
                                  unload_llm=make_unload_llm(settings)))
        return 0

    if args.command == "digest":
        from erw.pipeline.digest import build_digest

        if not args.dry_run:
            parser.error("digest currently supports --dry-run only; the scheduler sends the real digest")
        engine = make_engine(settings.db_url)
        init_db(engine)
        with SessionLocal(bind=engine) as session:
            for project in settings.jira_projects:
                print(build_digest(session, project, utcnow(), settings), end="\n\n")
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
    from erw.pipeline import alerts, evaluate

    evaluate._dispatch = alerts.dispatch
    with SessionLocal(bind=engine) as session:
        print(f"synced {catch_up(session, client, settings, utcnow())} issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
