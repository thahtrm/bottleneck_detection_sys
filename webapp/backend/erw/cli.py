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

    sim_parser = subparsers.add_parser("sim-eval", help="run historical simulation evaluation on DuckDB")
    sim_parser.add_argument("--instance", default="Apache", help="Jira instance name (default: Apache)")
    sim_parser.add_argument("--project", default="ZOOKEEPER", help="Jira project key (default: ZOOKEEPER)")
    sim_parser.add_argument("--from", dest="from_date", required=True, help="start date (YYYY-MM-DD)")
    sim_parser.add_argument("--to", dest="to_date", required=True, help="end date (YYYY-MM-DD)")
    sim_parser.add_argument("--step-days", type=int, default=1, help="step interval in days (default: 1)")
    sim_parser.add_argument("--duckdb-path", default="data/jira.duckdb", help="path to historical DuckDB")
    sim_parser.add_argument("--delay-threshold", type=float, default=0.39, help="p_delay threshold (default: 0.39)")
    sim_parser.add_argument("--crit-top-pct", type=float, default=0.05, help="criticality top percentage (default: 0.05)")
    sim_parser.add_argument("--output", help="output markdown file path (default: reports/sim-<instance>-<project>.md)")

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "sim-eval":
        import sys
        from datetime import date
        from pathlib import Path

        from erw.sim.eval import DefaultSimScorers, run_simulation
        from erw.sim.metrics import analyze_simulation, generate_sim_report

        try:
            from_d = date.fromisoformat(args.from_date)
            to_d = date.fromisoformat(args.to_date)
        except (ValueError, TypeError) as exc:
            print(f"Error: Invalid date format: {exc}. Please use YYYY-MM-DD.", file=sys.stderr)
            return 1

        if from_d > to_d:
            print(f"Error: --from ({from_d}) must be earlier than or equal to --to ({to_d}).", file=sys.stderr)
            return 1

        if args.step_days <= 0:
            print("Error: --step-days must be a positive integer.", file=sys.stderr)
            return 1

        duckdb_path = Path(args.duckdb_path)
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        if not duckdb_path.exists() and str(duckdb_path) != ":memory:":
            if (repo_root / args.duckdb_path).exists():
                duckdb_path = repo_root / args.duckdb_path
            else:
                print(f"Error: DuckDB database not found at {args.duckdb_path}", file=sys.stderr)
                return 1

        output_path = args.output
        if not output_path:
            output_path = f"reports/sim-{args.instance.lower()}-{args.project.lower()}.md"

        out_path = Path(output_path)
        if not out_path.is_absolute() and Path.cwd().resolve().is_relative_to(repo_root) and Path.cwd() != repo_root:
            if str(output_path).startswith("reports"):
                out_path = repo_root / output_path

        print("======================================================================")
        print("EARLY RISK WEB — HISTORICAL SIMULATION EVALUATION ENGINE")
        print(f"Instance: {args.instance} | Project: {args.project}")
        print(f"Time range: {from_d.isoformat()} -> {to_d.isoformat()} (step: {args.step_days} day(s))")
        print(f"DuckDB: {args.duckdb_path}")
        print(f"Thresholds: p_delay >= {args.delay_threshold}, criticality top {args.crit_top_pct}")
        print("======================================================================")

        bundles_dir = repo_root / "bundles" if (repo_root / "bundles").exists() else Path("bundles")
        emb_dir = repo_root / "data" if (repo_root / "data").exists() else Path("data")
        scorers = DefaultSimScorers(bundles_dir=bundles_dir, emb_dir=emb_dir)

        try:
            sim_result = run_simulation(
                duckdb_path=duckdb_path,
                instance=args.instance,
                project=args.project,
                from_date=from_d,
                to_date=to_d,
                step_days=args.step_days,
                scorers=scorers,
                delay_threshold=args.delay_threshold,
                crit_top_pct=args.crit_top_pct,
            )
        except Exception as exc:
            print(f"Error running simulation: {exc}", file=sys.stderr)
            return 1

        analysis = analyze_simulation(sim_result)
        generate_sim_report(sim_result, output_path=out_path)

        print(
            f"\nSimulation completed: {analysis.total_evaluations} evaluations across "
            f"{analysis.unique_issues} unique issues."
        )
        print("\nSummary Results:")
        print(
            f"{'Configuration':<35} | {'Alerts':<6} | {'TP':<4} | {'FP':<4} | "
            f"{'FN':<4} | {'Precision':<9} | {'Recall':<6} | {'F1':<6} | {'Lead Time'}"
        )
        print("-" * 105)
        for cfg_name, label in [("rules", "Rules Only"), ("ml", "ML T0 Only"), ("hybrid", "Hybrid ERW")]:
            m = analysis[cfg_name]
            lead_str = f"{m.avg_lead_time_days:.2f}d" if m.avg_lead_time_days is not None else "N/A"
            print(
                f"{label:<35} | {m.alert_count:<6} | {m.tp:<4} | {m.fp:<4} | "
                f"{m.fn:<4} | {m.precision:<9.4f} | {m.recall:<6.4f} | {m.f1:<6.4f} | {lead_str}"
            )
        print("-" * 105)
        print(f"\nReport generated and saved to: {output_path}")
        return 0

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
