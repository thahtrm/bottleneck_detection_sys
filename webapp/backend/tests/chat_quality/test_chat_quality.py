"""CI entry: PM chat answer-quality suite (non-zero exit on regression)."""

from __future__ import annotations

import pytest

from tests.chat_quality.board_seed import PROJECT, seed_quality_board
from tests.chat_quality.scorer import load_fixtures, run_eval


@pytest.fixture
def quality_now(session):
    return seed_quality_board(session)


def test_fixture_set_is_non_empty():
    fixtures = load_fixtures()
    assert len(fixtures) >= 12
    ids = [c["id"] for c in fixtures]
    assert len(ids) == len(set(ids))


def test_answer_quality_suite(session, settings, quality_now):
    report = run_eval(session, settings, project=PROJECT, now=quality_now)
    failures = [
        f"{c.case_id}: " + "; ".join(f"{x.name} ({x.detail})" for x in c.failures) for c in report.cases if not c.ok
    ]
    assert report.ok, (
        f"chat quality regressions: {report.failed}/{report.fixture_count} failed "
        f"(source={report.source_mode})\n" + "\n".join(failures)
    )
