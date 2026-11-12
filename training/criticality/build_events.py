"""Stage 2 — Continuous-time event stream for all 16 instances (DuckDB view -> on-disk memmaps).

Thin CLI over ``early_risk_detection.criticality.stream.build_event_stream`` (the same code
the CriticalityScorer runs at serving time). Writes data/tgn_full/events/*.npy + meta.json.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from early_risk_detection._logging import setup_logging
from early_risk_detection.criticality.stream import build_event_stream


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default="data/jira.duckdb")
    ap.add_argument("--out_dir", default="data/tgn_full")
    args = ap.parse_args()
    setup_logging()
    iss_t0 = pq.read_table(Path(args.out_dir) / "issues_t0.parquet",
                           columns=["row_id", "instance", "assignee_t0", "reporter", "project"]).to_pandas()
    con = duckdb.connect(args.duckdb, read_only=True)
    try:
        build_event_stream(con, iss_t0, Path(args.out_dir) / "events")
    finally:
        con.close()


if __name__ == "__main__":
    main()
