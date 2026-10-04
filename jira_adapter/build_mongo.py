"""Driver: đọc issue document từ MongoDB (đã restore từ mongodump) -> pipeline
`jira_adapter` -> file `ml_{instance}.*` đúng format repo TGN, kèm EDA.

Yêu cầu: mongod đang chạy (mặc định 127.0.0.1:27017), DB `JiraReposAnon`,
collection = tên instance (Spring, JFrog, Mojang, ...).

Chạy:
    python -m jira_adapter.build_mongo --list
    python -m jira_adapter.build_mongo --instance JFrog --out data            # EDA + build
    python -m jira_adapter.build_mongo --all --out data                        # mọi instance
    python -m jira_adapter.build_mongo --instance Mojang --limit 20000        # pilot nhanh

Lưu ý bộ nhớ: Mojang (~421k issue, ~20GB) có thể vượt 30GB RAM nếu nạp toàn
bộ vào list — dùng --limit hoặc (P2) streaming theo batch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .events import extract_events
from .labels import assign_labels
from .to_tgn import write_instance
from .eda import eda_instance, render_markdown


def _bson_to_plain(obj: Any) -> Any:
    """ObjectId/datetime -> giá trị JSON-safe (đệ quy)."""
    if isinstance(obj, dict):
        return {k: _bson_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_bson_to_plain(v) for v in obj]
    try:
        from bson import ObjectId, _datetime  # noqa: F401
        if isinstance(obj, ObjectId):
            return str(obj)
    except ImportError:
        pass
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    return obj


def connect(host: str = "127.0.0.1:27017", db: str = "JiraReposAnon"):
    import pymongo
    return pymongo.MongoClient(host, serverSelectionTimeoutMS=5000)[db]


def list_instances(host: str, db: str = "JiraReposAnon") -> list[dict[str, Any]]:
    d = connect(host, db)
    out = []
    for name in d.list_collection_names():
        if name.startswith("system."):
            continue
        out.append({"instance": name, "n_issues": d[name].count_documents({})})
    return sorted(out, key=lambda r: r["instance"])


def fetch_instance(host: str, name: str,
                   db: str = "JiraReposAnon",
                   limit: int | None = None) -> list[dict]:
    d = connect(host, db)
    cur = d[name].find({})
    if limit:
        cur = cur.limit(limit)
    return [_bson_to_plain(doc) for doc in cur]


def build_instance_mongo(name: str, host: str, out_dir: str = "data",
                         q: float = 0.05, w=None,
                         db: str = "JiraReposAnon",
                         limit: int | None = None,
                         eda_out: str | None = None,
                         mode: str = "dependency",
                         use_dwell: bool = False,
                         as_name: str | None = None) -> dict:
    docs = fetch_instance(host, name, db=db, limit=limit)
    if not docs:
        raise SystemExit(f"[build_mongo] instance {name}: 0 issue — kiểm tra host/db/collection")

    result: dict[str, Any] = {"instance": name, "n_docs": len(docs),
                              "limit": limit, "host": host, "db": db}

    # --- EDA -----------------------------------------------------------------
    try:
        stats = eda_instance(name, docs)
        result["eda"] = stats
        if eda_out:
            md = render_markdown([stats])
            Path(eda_out).mkdir(parents=True, exist_ok=True)
            (Path(eda_out) / f"eda_{name}.md").write_text(md, encoding="utf-8")
    except Exception as ex:  # noqa: BLE001 - EDA lỗi không chặn build
        result["eda_error"] = f"{type(ex).__name__}: {ex}"

    # --- events -> labels -> files -------------------------------------------
    eps = {d.get("key"): extract_events(d) for d in docs if d.get("key")}
    rows, lab_stats = assign_labels(docs, eps, w=w, q=q, mode=mode, use_dwell=use_dwell)
    label_map = {(r["key"], round(r["ts"], 3)): r for r in rows}
    result["label_stats"] = lab_stats
    out_name = as_name or name
    result["out"] = write_instance(out_name, docs, eps, label_map, out_dir=out_dir)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:27017")
    ap.add_argument("--db", default="JiraReposAnon")
    ap.add_argument("--list", action="store_true", help="liệt kê instance + số issue")
    ap.add_argument("--instance", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default="data")
    ap.add_argument("--eda-out", default="docs/eda", help="thư mục lưu EDA markdown")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--q", type=float, default=0.05)
    ap.add_argument("--label-mode", default="dependency", choices=["dependency", "composite"],
                    help="dependency (v3, mặc định) | composite (ablation top-q%%)")
    ap.add_argument("--use-dwell", action="store_true",
                    help="chỉ cho composite: thêm tín hiệu dwell (v1 — leakage temporal)")
    ap.add_argument("--as-name", default=None,
                    help="tên output (ml_{as_name}.*) khác tên instance, vd JFrog_comp")
    args = ap.parse_args()

    if args.list:
        for row in list_instances(args.host, args.db):
            print(f"{row['instance']:<15} {row['n_issues']:>10,} issues")
        return

    if not args.instance and not args.all:
        ap.error("chọn --list | --instance <tên> | --all")

    dbobj = connect(args.host, args.db)
    dbobj.client.admin.command("ping")  # fail-fast nếu mongod không chạy

    if args.all:
        names = [r["instance"] for r in list_instances(args.host, args.db)]
    else:
        names = [args.instance]

    results = []
    for name in names:
        print(f"[build_mongo] == {name} ==", file=sys.stderr)
        try:
            results.append(build_instance_mongo(name, args.host, out_dir=args.out, q=args.q,
                                                db=args.db, limit=args.limit,
                                                eda_out=args.eda_out,
                                                mode=args.label_mode, use_dwell=args.use_dwell,
                                                as_name=args.as_name))
        except Exception as ex:  # noqa: BLE001
            results.append({"instance": name, "error": f"{type(ex).__name__}: {ex}"})

    (Path(args.out) / "build_mongo_summary.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
