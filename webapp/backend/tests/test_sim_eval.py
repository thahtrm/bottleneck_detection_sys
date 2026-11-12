from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from erw.sim.eval import (
    DayEvalRecord,
    DefaultSimScorers,
    SimulationResult,
    run_simulation,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS issues (
    instance            VARCHAR NOT NULL,
    issue_key           VARCHAR NOT NULL,
    project             VARCHAR NOT NULL,
    summary             VARCHAR,
    issuetype           VARCHAR,
    issuetype_theme     VARCHAR,
    priority_raw        VARCHAR,
    priority_norm       DOUBLE,
    status              VARCHAR,
    resolution          VARCHAR,
    created_ts          DOUBLE,
    updated_ts          DOUBLE,
    resolved_ts         DOUBLE,
    assignee            VARCHAR,
    reporter            VARCHAR,
    num_changelogs      INTEGER DEFAULT 0,
    num_links           INTEGER DEFAULT 0,
    num_comments        INTEGER DEFAULT 0,
    has_block_or_depend BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (instance, issue_key)
);

CREATE TABLE IF NOT EXISTS issue_changelogs (
    instance            VARCHAR NOT NULL,
    issue_key           VARCHAR NOT NULL,
    change_id           VARCHAR,
    author              VARCHAR,
    created_ts          DOUBLE NOT NULL,
    field               VARCHAR NOT NULL,
    from_value          VARCHAR,
    to_value            VARCHAR
);

CREATE TABLE IF NOT EXISTS issue_links (
    instance            VARCHAR NOT NULL,
    source_key          VARCHAR NOT NULL,
    target_key          VARCHAR NOT NULL,
    link_type_raw       VARCHAR,
    link_type_std       VARCHAR NOT NULL,
    direction           INTEGER NOT NULL,
    is_block_or_depend  BOOLEAN NOT NULL,
    approx_ts           DOUBLE NOT NULL
);
"""

DAY = 86400.0
# Base epoch: 2024-01-01 08:00:00 UTC
T0 = datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC).timestamp()


class MockScorers:
    def __init__(self, delay_scores: dict[str, float], crit_scores: dict[str, float] | None = None):
        self.delay_scores = delay_scores
        self.crit_scores = crit_scores or {}

    def score(
        self, duckdb_path: str | Path, issue_keys: list[str], as_of: float
    ) -> tuple[dict[str, float], dict[str, float]]:
        del duckdb_path, as_of
        d = {k: self.delay_scores.get(k, 0.20) for k in issue_keys}
        c = {k: self.crit_scores.get(k, 0.01) for k in issue_keys}
        return d, c


def _init_test_duckdb(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_SQL)

    # 5 issues for INST / PRJ:
    # Issue 1: TP - Actually delayed (20d > 10d), stagnant in progress (> 7d), high ML (0.65)
    # Issue 2: FP of ML eliminated by Hybrid - Actual on-time (3d <= 10d), no rule flags, ML false alarm (0.45)
    # Issue 3: FN of ML rescued by Rules - Actually delayed (20d > 10d), blocked by PRJ-10, ML missed (0.20)
    # Issue 4: TN - Quick on-time (2d <= 10d), no rule flags, low ML (0.15)
    # Issue 10: Blocker issue, open at T0, resolved at T0 + 15 days
    issues = [
        (
            "INST",
            "PRJ-1",
            "PRJ",
            "Search bottleneck",
            "Bug",
            "Maintenance",
            "Major",
            0.6,
            "In Progress",
            "Fixed",
            T0 - 8 * DAY,
            T0 + 12 * DAY,
            T0 + 12 * DAY,
            "alice",
            "bob",
            1,
            0,
            0,
            False,
        ),
        (
            "INST",
            "PRJ-2",
            "PRJ",
            "UI cosmetic tweak",
            "Task",
            "Development",
            "Minor",
            0.4,
            "In Progress",
            "Fixed",
            T0,
            T0 + 3 * DAY,
            T0 + 3 * DAY,
            "charlie",
            "bob",
            1,
            0,
            0,
            False,
        ),
        (
            "INST",
            "PRJ-3",
            "PRJ",
            "Payment gateway",
            "New Feature",
            "Requirements",
            "Major",
            0.6,
            "Open",
            "Fixed",
            T0 - 2 * DAY,
            T0 + 18 * DAY,
            T0 + 18 * DAY,
            "david",
            "bob",
            0,
            1,
            0,
            True,
        ),
        (
            "INST",
            "PRJ-4",
            "PRJ",
            "Docs update",
            "Task",
            "Development",
            "Trivial",
            0.2,
            "In Progress",
            "Fixed",
            T0 - 1 * DAY,
            T0 + 2 * DAY,
            T0 + 2 * DAY,
            "eve",
            "bob",
            1,
            0,
            0,
            False,
        ),
        (
            "INST",
            "PRJ-10",
            "PRJ",
            "Core dependency blocker",
            "Bug",
            "Maintenance",
            "Critical",
            0.8,
            "Open",
            "Fixed",
            T0 - 5 * DAY,
            T0 + 15 * DAY,
            T0 + 15 * DAY,
            "alice",
            "bob",
            0,
            1,
            0,
            True,
        ),
    ]

    for iss in issues:
        con.execute("INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", iss)

    # Changelogs for status
    changelogs = [
        ("INST", "PRJ-1", "c1", "alice", T0 - 8 * DAY, "status", "Open", "In Progress"),
        ("INST", "PRJ-2", "c2", "charlie", T0, "status", "Open", "In Progress"),
        ("INST", "PRJ-4", "c3", "eve", T0 - 1 * DAY, "status", "Open", "In Progress"),
    ]
    for cl in changelogs:
        con.execute("INSERT INTO issue_changelogs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", cl)

    # Links: PRJ-3 is blocked by PRJ-10
    links = [
        ("INST", "PRJ-3", "PRJ-10", "is blocked by", "Block", 0, True, T0 - 2 * DAY),
    ]
    for lk in links:
        con.execute("INSERT INTO issue_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)", lk)

    con.close()


def test_simulation_scenarios_tp_fp_fn_tn(tmp_path: Path):
    db_path = tmp_path / "test_sim.duckdb"
    _init_test_duckdb(db_path)

    scorers = MockScorers(
        delay_scores={
            "PRJ-1": 0.65,  # High ML risk
            "PRJ-2": 0.45,  # ML False positive
            "PRJ-3": 0.20,  # ML False negative
            "PRJ-4": 0.15,  # Low ML
            "PRJ-10": 0.30,
        },
        crit_scores={
            "PRJ-1": 0.08,
            "PRJ-2": 0.01,
            "PRJ-3": 0.02,
            "PRJ-4": 0.01,
            "PRJ-10": 0.02,
        },
    )

    res: SimulationResult = run_simulation(
        duckdb_path=db_path,
        instance="INST",
        project="PRJ",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 1),
        step_days=1,
        scorers=scorers,
        delay_threshold=0.39,
        planned_duration_days=10.0,
    )

    assert res.instance == "INST"
    assert res.project == "PRJ"
    assert res.from_date == date(2024, 1, 1)
    assert res.to_date == date(2024, 1, 1)
    assert res.total_evaluations == 5
    assert res.unique_issues_evaluated == 5

    rec_by_key: dict[str, DayEvalRecord] = {r.issue_key: r for r in res.records}

    # Scenario 1: Issue 1 (TP - True Positive for both Rules and ML)
    r1 = rec_by_key["PRJ-1"]
    assert r1.actual_delayed is True
    assert r1.pred_rules is True
    assert any("stagnant_in_progress" in f or "age_over_70pct" in f for f in r1.rule_factors)
    assert r1.pred_ml is True
    assert r1.pred_hybrid is True
    assert r1.lead_time_days is not None
    assert r1.lead_time_days > 10.0  # Resolved on day 13, as_of is end of day 1

    # Scenario 2: Issue 2 (FP of ML suppressed by Hybrid)
    r2 = rec_by_key["PRJ-2"]
    assert r2.actual_delayed is False
    assert r2.pred_rules is False
    assert r2.pred_ml is True  # ML false alarm
    assert r2.pred_hybrid is False  # Hybrid correctly eliminated the false alarm!
    assert r2.lead_time_days is None

    # Scenario 3: Issue 3 (FN of ML rescued by Rules)
    r3 = rec_by_key["PRJ-3"]
    assert r3.actual_delayed is True
    assert r3.pred_rules is True  # Rules caught the blocker!
    assert any("blocked" in f for f in r3.rule_factors)
    assert r3.pred_ml is False  # ML missed it
    assert r3.pred_hybrid is True  # Hybrid rescued by Rules!
    assert r3.lead_time_days is not None
    assert r3.lead_time_days > 15.0

    # Scenario 4: Issue 4 (TN - True Negative)
    r4 = rec_by_key["PRJ-4"]
    assert r4.actual_delayed is False
    assert r4.pred_rules is False
    assert r4.pred_ml is False
    assert r4.pred_hybrid is False
    assert r4.lead_time_days is None

    # Verify metrics
    metrics = res.compute_metrics()
    assert "rules" in metrics
    assert "ml" in metrics
    assert "hybrid" in metrics

    # ML had FP on PRJ-2 and FN on PRJ-3
    assert metrics["ml"]["fp"] >= 1.0
    assert metrics["ml"]["fn"] >= 1.0

    # Hybrid rescued PRJ-3 (no FN on PRJ-1/2/3/4) and eliminated FP on PRJ-2
    assert metrics["hybrid"]["fp"] == 0.0


def test_simulation_multi_day_stepping(tmp_path: Path):
    db_path = tmp_path / "test_multi_day.duckdb"
    _init_test_duckdb(db_path)

    scorers = MockScorers(
        delay_scores={"PRJ-1": 0.6, "PRJ-2": 0.2, "PRJ-3": 0.2, "PRJ-4": 0.1, "PRJ-10": 0.1}
    )

    # Simulate from Jan 1 to Jan 4 (4 days, step=1)
    # PRJ-4 resolves on T0 + 2*DAY (2024-01-03 08:00:00 UTC)
    # At end of Jan 3 (23:59:59), PRJ-4 resolved_ts (Jan 3 08:00) <= d_ts, so on Jan 4 PRJ-4 is NOT open!
    res = run_simulation(
        duckdb_path=db_path,
        instance="INST",
        project="PRJ",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 4),
        step_days=1,
        scorers=scorers,
        planned_duration_days=10.0,
    )

    assert res.from_date == date(2024, 1, 1)
    assert res.to_date == date(2024, 1, 4)

    eval_dates = {r.as_of_date for r in res.records}
    assert eval_dates == {date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)}

    # On Jan 4, PRJ-4 must not be in the evaluated open issues
    jan_4_keys = {r.issue_key for r in res.records if r.as_of_date == date(2024, 1, 4)}
    assert "PRJ-4" not in jan_4_keys
    assert "PRJ-1" in jan_4_keys


def test_read_only_mode_enforcement(tmp_path: Path):
    db_path = tmp_path / "test_readonly.duckdb"
    _init_test_duckdb(db_path)

    # Run simulation on existing file
    res = run_simulation(
        duckdb_path=db_path,
        instance="INST",
        project="PRJ",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 1),
        scorers=MockScorers(delay_scores={}),
    )
    assert res.total_evaluations > 0

    # Verify that duckdb read_only mode prevents any writes
    con = duckdb.connect(str(db_path), read_only=True)
    with pytest.raises(duckdb.InvalidInputException):
        con.execute("DELETE FROM issues")
    con.close()


def test_default_sim_scorers_fallback(tmp_path: Path):
    db_path = tmp_path / "test_default_scorers.duckdb"
    _init_test_duckdb(db_path)

    default_scorer = DefaultSimScorers(bundles_dir=tmp_path / "non_existent_bundles")
    d, c = default_scorer.score(db_path, ["PRJ-1", "PRJ-2"], T0)
    assert "PRJ-1" in d
    assert "PRJ-2" in d
    assert "PRJ-1" in c
    assert "PRJ-2" in c

    # Calling run_simulation with scorers=None uses DefaultSimScorers gracefully
    res = run_simulation(
        duckdb_path=db_path,
        instance="INST",
        project="PRJ",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 1),
        scorers=None,
    )
    assert res.total_evaluations == 5


def test_edge_cases(tmp_path: Path):
    db_path = tmp_path / "test_edge.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_SQL)

    # Issue with non-standard resolution "Won't Fix" resolved quickly (2 days < 14 days)
    # Should still be marked actual_delayed = True because resolution is not standard done!
    con.execute(
        "INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "INST",
            "EDGE-1",
            "PRJ",
            "Cancelled issue",
            "Bug",
            "Maintenance",
            "Minor",
            0.4,
            "Closed",
            "Won't Fix",
            T0,
            T0 + 2 * DAY,
            T0 + 2 * DAY,
            "alice",
            "bob",
            0,
            0,
            0,
            False,
        ),
    )

    # Issue never resolved (resolved_ts is NULL)
    con.execute(
        "INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "INST",
            "EDGE-2",
            "PRJ",
            "Abandoned issue",
            "Bug",
            "Maintenance",
            "Major",
            0.6,
            "Open",
            None,
            T0,
            T0,
            None,
            "alice",
            "bob",
            0,
            0,
            0,
            False,
        ),
    )
    con.close()

    res = run_simulation(
        duckdb_path=db_path,
        instance="INST",
        project="PRJ",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 1),
        scorers=MockScorers(delay_scores={"EDGE-1": 0.1, "EDGE-2": 0.1}),
        planned_duration_days=14.0,
    )

    by_key = {r.issue_key: r for r in res.records}
    assert by_key["EDGE-1"].actual_delayed is True  # Non-standard resolution
    assert by_key["EDGE-2"].actual_delayed is True  # Never resolved

    # from_date > to_date raises ValueError
    with pytest.raises(ValueError, match="must be <= to_date"):
        run_simulation(
            duckdb_path=db_path,
            instance="INST",
            project="PRJ",
            from_date=date(2024, 1, 5),
            to_date=date(2024, 1, 1),
        )

    # to_dict serialization
    d = res.to_dict()
    assert d["instance"] == "INST"
    assert len(d["records"]) == 2
    assert "pred_hybrid" in d["records"][0]
