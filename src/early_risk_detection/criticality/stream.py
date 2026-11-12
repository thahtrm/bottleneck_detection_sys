"""Continuous-time event stream of a Jira DuckDB -> flat on-disk memmaps for the TGN memory.

Event kinds: status, assignee, priority (issue_changelogs), comment (issue_comments),
link (issue_links, leak-safe timestamp, see ``features.t0.load_timed_links``), create (issue
creation by its reporter). Every event touches three memory nodes: the issue u, the counterpart
v (status/priority value node, user, or linked issue) and the issue's project p.

Node id space: [0, N_issue) = ``row_id`` of ``features.t0.load_issues_t0``; other nodes follow.
Node ids are only indices into the memory matrix (all weights are shared across nodes), so they
need not be persisted: a stream rebuilt from a newer database is valid for a trained model.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..features.t0 import USER_RE, VALID_FILTER

logger = logging.getLogger(__name__)

KINDS = ["status", "assignee", "priority", "comment", "link", "create"]
LTYPES = {"Block": 0, "Depend": 0, "Relate": 1, "Duplicate": 2}  # everything else -> 3
DONE_STATUS = "('5', '6', '10001', '10002')"  # Resolved, Closed, Done (std Jira ids)
PROGRESS_STATUS = "('3', '10000', '10011')"
REOPEN_STATUS = "('4')"

VIEW_SQL = f"""
CREATE OR REPLACE TEMP VIEW v_tgn_events_all AS
WITH map_assignee AS (
    WITH last AS (SELECT instance, issue_key, arg_max(to_value, (created_ts, to_value)) tv
                  FROM issue_changelogs WHERE field = 'assignee' GROUP BY ALL),
         j AS (SELECT l.instance, tv, i.assignee v, count(*) n
               FROM last l JOIN issues i USING (instance, issue_key)
               WHERE tv IS NOT NULL AND i.assignee IS NOT NULL GROUP BY ALL)
    SELECT instance, tv, arg_max(v, (n, v)) v FROM j GROUP BY ALL),
link_cl AS (
    SELECT instance, issue_key, to_value, min(created_ts) ts
    FROM issue_changelogs WHERE field = 'Link' AND to_value IS NOT NULL GROUP BY ALL),
ends AS (SELECT instance, issue_key, created_ts, updated_ts FROM issues)
SELECT instance, u, v, ts, kind, detail_to, link_type, direction, body_len FROM (
    SELECT c.instance, c.issue_key AS u,
           'status:' || COALESCE(c.to_value, 'none') AS v, c.created_ts AS ts, 'status' AS kind,
           c.to_value AS detail_to, NULL AS link_type, 1 AS direction, 0 AS body_len
    FROM issue_changelogs c WHERE c.field = 'status'
    UNION ALL
    SELECT c.instance, c.issue_key,
           'user:' || COALESCE(nullif(regexp_extract(COALESCE(m.v, c.to_value), '{USER_RE}', 1), ''),
                               COALESCE(m.v, c.to_value), '(unassigned)'),
           c.created_ts, 'assignee', c.to_value, NULL, 1, 0
    FROM issue_changelogs c LEFT JOIN map_assignee m ON m.instance = c.instance AND m.tv = c.to_value
    WHERE c.field = 'assignee'
    UNION ALL
    SELECT instance, issue_key, 'priority:' || COALESCE(to_value, 'none'), created_ts, 'priority',
           to_value, NULL, 1, 0
    FROM issue_changelogs WHERE field = 'priority'
    UNION ALL
    SELECT instance, issue_key,
           'user:' || COALESCE(nullif(regexp_extract(author, '{USER_RE}', 1), ''), author, '(unknown)'),
           created_ts, 'comment', NULL, NULL, 1, COALESCE(body_len, 0)
    FROM issue_comments
    UNION ALL
    SELECT l.instance, l.source_key, 'issue:' || l.target_key,
           greatest(COALESCE(least(c1.ts, c2.ts), c1.ts, c2.ts, greatest(a.updated_ts, b.updated_ts)),
                    a.created_ts, b.created_ts),
           'link', NULL, l.link_type_std, 1, 0
    FROM issue_links l
    JOIN ends a ON a.instance = l.instance AND a.issue_key = l.source_key
    JOIN ends b ON b.instance = l.instance AND b.issue_key = l.target_key
    LEFT JOIN link_cl c1 ON c1.instance = l.instance AND c1.issue_key = l.source_key AND c1.to_value = l.target_key
    LEFT JOIN link_cl c2 ON c2.instance = l.instance AND c2.issue_key = l.target_key AND c2.to_value = l.source_key
    UNION ALL
    SELECT instance, issue_key,
           'user:' || COALESCE(nullif(regexp_extract(reporter, '{USER_RE}', 1), ''), reporter, '(unknown)'),
           created_ts, 'create', NULL, NULL, 1, 0
    FROM issues
)
"""

COLUMNS = {"ts": "f8", "u_id": "i4", "v_id": "i4", "p_id": "i4", "kind": "i1", "ltype": "i1", "scat": "i1", "blen": "f4"}


def build_event_stream(con: duckdb.DuckDBPyConnection, issues_t0: pd.DataFrame, out_dir: str | Path,
                       memory_limit: str = "10GB") -> dict:
    """Write the sorted event stream and the T0 neighbour ids of every issue under ``out_dir``.

    ``issues_t0`` needs ``row_id, instance, assignee_t0, reporter, project`` in ``row_id`` order
    (output of ``load_issues_t0``). Returns the stream metadata (also written to ``meta.json``).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(VIEW_SQL)
    con.execute("SET preserve_insertion_order = true")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ev_iss AS
        SELECT (row_number() OVER (ORDER BY created_ts, instance, issue_key) - 1)::INTEGER AS row_id,
               instance, issue_key, 'issue:' || issue_key AS ikey, created_ts,
               instance || '|project:' || COALESCE(project, 'APP') AS pkey
        FROM issues WHERE {VALID_FILTER}
    """)
    n_issue = con.execute("SELECT count(*) FROM ev_iss").fetchone()[0]
    assert n_issue == len(issues_t0), (n_issue, len(issues_t0))
    # Materialise the view once, then plain hash joins (a conditional join here was pathologically slow).
    con.execute("CREATE OR REPLACE TEMP TABLE e AS SELECT * FROM v_tgn_events_all")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE ev AS
        SELECT e.*, e.instance || '|' || e.v AS vkey, i.row_id AS u_id, i.pkey, t.row_id AS v_issue
        FROM e
        JOIN ev_iss i ON i.instance = e.instance AND i.issue_key = e.u
        LEFT JOIN ev_iss t ON t.instance = e.instance AND t.ikey = e.v
        WHERE e.ts IS NOT NULL AND (e.kind <> 'link' OR t.row_id IS NOT NULL)
    """)
    con.execute("DROP TABLE e")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE nodes AS
        SELECT key, ({n_issue} + row_number() OVER (ORDER BY key) - 1)::INTEGER AS nid FROM (
            SELECT DISTINCT vkey AS key FROM ev WHERE kind <> 'link'
            UNION SELECT DISTINCT pkey FROM ev
            UNION SELECT DISTINCT instance || '|user:' ||
                COALESCE(nullif(regexp_extract(assignee, '{USER_RE}', 1), ''), assignee, '(unassigned)')
                FROM issues)
    """)
    n_nodes = n_issue + con.execute("SELECT count(*) FROM nodes").fetchone()[0]
    logger.info(f"Nodes: {n_issue:,} issues + {n_nodes - n_issue:,} users/projects/value nodes = {n_nodes:,}")

    tmp_parquet = out / "events_sorted.parquet"
    con.execute(f"""
        COPY (
            SELECT e.ts, e.u_id,
                   COALESCE(e.v_issue, nv.nid) AS v_id, np.nid AS p_id,
                   CASE e.kind {' '.join(f"WHEN '{k}' THEN {i}" for i, k in enumerate(KINDS))} END::TINYINT AS kind,
                   CASE WHEN e.link_type IN ('Block','Depend') THEN 0 WHEN e.link_type = 'Relate' THEN 1
                        WHEN e.link_type = 'Duplicate' THEN 2 WHEN e.link_type IS NULL THEN -1 ELSE 3 END::TINYINT AS ltype,
                   CASE WHEN e.kind <> 'status' THEN -1
                        WHEN e.detail_to IN {DONE_STATUS} THEN 0 WHEN e.detail_to IN {PROGRESS_STATUS} THEN 1
                        WHEN e.detail_to IN {REOPEN_STATUS} THEN 2 ELSE 3 END::TINYINT AS scat,
                   ln(1 + e.body_len)::FLOAT AS blen
            FROM ev e
            LEFT JOIN nodes nv ON nv.key = e.vkey
            JOIN nodes np ON np.key = e.pkey
            ORDER BY e.ts, e.u_id, kind, v_id, p_id
        ) TO '{tmp_parquet}' (FORMAT PARQUET, ROW_GROUP_SIZE 500000)
    """)
    # Assignee-at-T0 node id for every issue (used to read the assignee memory at T0).
    con.register("iss_t0", issues_t0[["row_id", "instance", "assignee_t0", "reporter", "project"]])
    side = con.execute(f"""
        SELECT r.row_id, na.nid AS a_id, nr.nid AS r_id, np.nid AS p_id
        FROM iss_t0 r
        LEFT JOIN nodes na ON na.key = r.instance || '|user:' ||
             COALESCE(nullif(regexp_extract(r.assignee_t0, '{USER_RE}', 1), ''), r.assignee_t0)
        LEFT JOIN nodes nr ON nr.key = r.instance || '|user:' ||
             COALESCE(nullif(regexp_extract(r.reporter, '{USER_RE}', 1), ''), r.reporter, '(unknown)')
        LEFT JOIN nodes np ON np.key = r.instance || '|project:' || COALESCE(r.project, 'APP')
        ORDER BY r.row_id
    """).df()
    con.unregister("iss_t0")
    con.execute("DROP TABLE ev")
    for c in ["a_id", "r_id", "p_id"]:
        miss = side[c].isna().mean()
        logger.info(f"  T0 neighbour {c}: {miss:.3%} unresolved -> mapped to -1")
        np.save(out / f"issue_{c}.npy", side[c].fillna(-1).values.astype(np.int32))

    pf = pq.ParquetFile(tmp_parquet)
    n_ev = pf.metadata.num_rows
    mm = {c: np.lib.format.open_memmap(out / f"{c}.npy", mode="w+", dtype=d, shape=(n_ev,)) for c, d in COLUMNS.items()}
    pos = 0
    for batch in pf.iter_batches(batch_size=1_000_000):
        k = batch.num_rows
        for c in COLUMNS:
            mm[c][pos:pos + k] = batch.column(c).to_numpy(zero_copy_only=False)
        pos += k
    for a in mm.values():
        a.flush()
    assert pos == n_ev
    ts = mm["ts"]
    assert np.all(np.diff(ts) >= 0), "event stream not sorted"
    counts = {k: int((mm["kind"] == i).sum()) for i, k in enumerate(KINDS)}
    meta = {"n_events": int(n_ev), "n_issue": int(n_issue), "n_nodes": int(n_nodes), "kinds": KINDS,
            "kind_counts": counts, "ts_min": float(ts[0]), "ts_max": float(ts[-1])}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    tmp_parquet.unlink()
    logger.info(f"Wrote {n_ev:,} events {counts} in {time.time() - t0:.0f}s")
    return meta


def load_neighbours(stream_dir: str | Path) -> np.ndarray:
    """(N_issue, 3) node ids of reporter, assignee at T0 and project; -1 if unknown."""
    root = Path(stream_dir)
    return np.stack([np.load(root / f"issue_{c}.npy") for c in ["r_id", "a_id", "p_id"]], 1)
