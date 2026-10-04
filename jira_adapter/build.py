"""Driver: instance Jira -> events -> labels bottleneck -> file `ml_{instance}.*`.

Sau khi tải + giải nén dataset, chạy:
    python -m jira_adapter.build --root data/raw --instance Spring --out data
    python -m jira_adapter.build --root data/raw --all --out data

Kết quả: data/ml_{instance}.csv / .npy / _node.npy — đúng format repo TGN.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .events import extract_events
from .labels import assign_labels
from .to_tgn import write_instance
from .eda import discover, _iter_issues_from_file


def build_instance(name: str, paths: list[Path], out_dir: str = "data",
                   q: float = 0.05, w=None) -> dict:
    docs: list[dict] = []
    for p in paths:
        docs.extend(_iter_issues_from_file(p))
    if not docs:
        raise SystemExit(f"[build] instance {name}: không đọc được issue nào từ {paths}")

    eps = {d.get("key"): extract_events(d) for d in docs if d.get("key")}
    rows, stats = assign_labels(docs, eps, w=w, q=q)
    label_map = {(r["key"], round(r["ts"], 3)): r for r in rows}

    out_stats = write_instance(name, docs, eps, label_map, out_dir=out_dir)
    return {"instance": name, "n_docs": len(docs), "label_stats": stats, "out": out_stats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw")
    ap.add_argument("--instance", default=None, help="tên instance (vd Spring, JFrog, Mojang)")
    ap.add_argument("--all", action="store_true", help="xây tất cả instance tìm được")
    ap.add_argument("--out", default="data")
    ap.add_argument("--q", type=float, default=0.05, help="top-q%% làm nhãn bottleneck (mặc định 5%%)")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Không thấy {root} — tải + giải nén dataset trước.")

    mapping = discover(root)
    if not args.all:
        if not args.instance:
            print("Chọn --instance <tên> hoặc --all. Có:", list(mapping), file=sys.stderr)
            raise SystemExit(2)
        keep = {k.lower(): (k, v) for k, v in mapping.items()}
        if args.instance.lower() not in keep:
            raise SystemExit(f"Không thấy instance '{args.instance}'. Có: {list(mapping)}")
        name, paths = keep[args.instance.lower()]
        result = build_instance(name, paths, out_dir=args.out, q=args.q)
        print(json.dumps(result, indent=2, default=str))
    else:
        results = []
        for inst in sorted(mapping):
            print(f"[build] == {inst} ==", file=sys.stderr)
            try:
                results.append(build_instance(inst, mapping[inst], out_dir=args.out, q=args.q))
            except Exception as ex:  # noqa: BLE001 - tiếp tục các instance khác
                results.append({"instance": inst, "error": f"{type(ex).__name__}: {ex}"})
        (Path(args.out) / "build_summary.json").write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
