"""Driver: đọc dữ liệu từ DuckDB (đã nạp qua ETL) -> pipeline `jira_adapter`
-> sinh file `data/ml_{instance}.{csv,npy,_node.npy}` đúng chuẩn TGN.

Ưu điểm so với build_mongo:
- Không cần daemon mongod chạy ngầm.
- Đọc theo cột cực nhanh, tiêu thụ ít RAM.
- Tương thích 100% với định dạng của repo TGN.

Chạy:
    PYTHONPATH=.pylibs python -m jira_adapter.build_duckdb --instance JFrog --duckdb data/jira.duckdb
    PYTHONPATH=.pylibs python -m jira_adapter.build_duckdb --instance JFrog --leak-safe --as-name JFrog_ls
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from .events import Event
from .labels import assign_labels
from .normalize import link_type_index
from .to_tgn import write_instance


def fetch_instance_from_duckdb(duckdb_path: str, instance: str) -> tuple[list[dict], dict[str, list[Event]]]:
    """Đọc instance từ DuckDB và tái tạo docs, events_per_issue."""
    con = duckdb.connect(duckdb_path, read_only=True)

    # 1. Đọc metadata issues
    issue_rows = con.execute(
        """
        SELECT 
            issue_key, project, summary, issuetype, issuetype_theme,
            priority_raw, priority_norm, status, resolution,
            created_ts, updated_ts, resolved_ts, assignee, reporter,
            num_links, has_block_or_depend
        FROM issues
        WHERE instance = ?
        ORDER BY created_ts ASC
        """,
        [instance],
    ).fetchall()

    if not issue_rows:
        con.close()
        raise SystemExit(f"[build_duckdb] instance '{instance}': 0 issue trong DuckDB ({duckdb_path})")

    # 2. Đọc links
    link_rows = con.execute(
        """
        SELECT source_key, target_key, link_type_raw, link_type_std, direction, is_block_or_depend, approx_ts
        FROM issue_links
        WHERE instance = ?
        """,
        [instance],
    ).fetchall()

    links_by_key: dict[str, list[dict]] = defaultdict(list)
    for src, tgt, raw_t, std_t, direction, is_bod, approx_ts in link_rows:
        link_dict = {
            "type": {"name": raw_t},
            "outwardIssue": {"key": src if direction == 1 else tgt},
            "inwardIssue": {"key": tgt if direction == 1 else src},
        }
        links_by_key[src].append(link_dict)

    # 3. Tạo list docs tương thích
    docs: list[dict] = []
    for r in issue_rows:
        key = r[0]
        doc = {
            "key": key,
            "fields": {
                "project": {"key": r[1]},
                "summary": r[2],
                "issuetype": {"name": r[3]},
                "priority": {"name": r[5]},
                "status": {"name": r[7]},
                "resolution": {"name": r[8]} if r[8] else None,
                "created": r[9],
                "updated": r[10],
                "resolutiondate": r[11],
                "assignee": {"name": r[12]} if r[12] else None,
            },
            "issueLinks": links_by_key.get(key, []),
            "changelog": [],  # Sẽ đọc event trực tiếp từ v_tgn_events
        }
        docs.append(doc)

    # 4. Đọc events từ v_tgn_events
    event_rows = con.execute(
        """
        SELECT u, v, ts, kind, detail_from, detail_to, link_type, direction
        FROM v_tgn_events
        WHERE instance = ?
        ORDER BY ts ASC, kind ASC
        """,
        [instance],
    ).fetchall()

    events_per_issue: dict[str, list[Event]] = defaultdict(list)
    for u, v, ts, kind, d_from, d_to, l_type, direction in event_rows:
        detail: dict[str, Any] = {}
        if kind in ("status", "assignee", "priority"):
            detail = {"from": d_from, "to": d_to}
        elif kind == "link":
            detail = {
                "link_type": l_type,
                "link_type_idx": link_type_index(l_type),
                "direction": direction,
            }
        e = Event(u=u, v=v, ts=ts, kind=kind, detail=detail)
        events_per_issue[u].append(e)

    con.close()
    return docs, dict(events_per_issue)


def build_instance_duckdb(
    name: str,
    duckdb_path: str = "data/jira.duckdb",
    out_dir: str = "data",
    q: float = 0.05,
    w=None,
    mode: str = "dependency",
    use_dwell: bool = False,
    as_name: str | None = None,
    leak_safe: bool = False,
) -> dict:
    docs, eps = fetch_instance_from_duckdb(duckdb_path, name)

    result: dict[str, Any] = {
        "instance": name,
        "n_docs": len(docs),
        "source": "duckdb",
        "duckdb_path": duckdb_path,
    }

    # Gán nhãn và xuất file
    rows, lab_stats = assign_labels(docs, eps, w=w, q=q, mode=mode, use_dwell=use_dwell)
    label_map = {(r["key"], round(r["ts"], 3)): r for r in rows}
    result["label_stats"] = lab_stats
    out_name = as_name or name
    result["out"] = write_instance(out_name, docs, eps, label_map, out_dir=out_dir, leak_safe=leak_safe)
    result["leak_safe"] = leak_safe
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Build TGN dataset trực tiếp từ DuckDB")
    ap.add_argument("--duckdb", default="data/jira.duckdb", help="Đường dẫn file DuckDB")
    ap.add_argument("--instance", required=True, help="Tên instance cần build (JFrog, Spring, ...)")
    ap.add_argument("--out", default="data", help="Thư mục xuất file data/ml_*")
    ap.add_argument("--q", type=float, default=0.05)
    ap.add_argument("--label-mode", default="dependency", choices=["dependency", "composite"])
    ap.add_argument("--use-dwell", action="store_true")
    ap.add_argument("--as-name", default=None)
    ap.add_argument("--leak-safe", action="store_true")

    args = ap.parse_args()

    print(f"[build_duckdb] == Xử lý {args.instance} từ {args.duckdb} ==", file=sys.stderr)
    res = build_instance_duckdb(
        name=args.instance,
        duckdb_path=args.duckdb,
        out_dir=args.out,
        q=args.q,
        mode=args.label_mode,
        use_dwell=args.use_dwell,
        as_name=args.as_name,
        leak_safe=args.leak_safe,
    )
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
