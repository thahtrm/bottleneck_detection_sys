#!/usr/bin/env python3
"""Run PM chat answer-quality eval; exit 1 on any fixture failure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "webapp" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from erw.db import SessionLocal, init_db, make_engine  # noqa: E402
from erw.settings import Settings  # noqa: E402
from tests.chat_quality.board_seed import PROJECT, seed_quality_board  # noqa: E402
from tests.chat_quality.scorer import load_fixtures, run_eval  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable report")
    parser.add_argument("--fixtures", type=Path, default=None, help="Override questions.json path")
    args = parser.parse_args(argv)

    settings = Settings(
        _env_file=None,
        db_url="sqlite://",
        jira_base_url="https://example.atlassian.net",
        jira_email="bot@example.com",
        jira_api_token="token",
        jira_projects=[PROJECT],
    )
    engine = make_engine(settings.db_url)
    init_db(engine)
    fixtures = load_fixtures(args.fixtures) if args.fixtures else load_fixtures()
    with SessionLocal(bind=engine) as session:
        now = seed_quality_board(session)
        report = run_eval(session, settings, project=PROJECT, now=now, fixtures=fixtures)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            f"chat_quality: {report.passed}/{report.fixture_count} passed "
            f"(failed={report.failed}, source={report.source_mode})"
        )
        for case in report.cases:
            if case.ok:
                continue
            bits = "; ".join(f"{c.name}: {c.detail}" for c in case.failures)
            print(f"  FAIL {case.case_id}: {bits}")
    engine.dispose()
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
