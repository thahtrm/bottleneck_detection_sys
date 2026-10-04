"""EDA The Public Jira Dataset — số liệu quyết định P1.

Chạy:  python -m jira_adapter.eda --root data/raw --out data/eda_report.md

Đo (per instance):
- số issue, số dự án, khoảng thời gian (min/max created)
- sự kiện: tổng, trung vị/số issue, phân bố theo loại (status/assignee/priority/link/comment)
- link: tổng, mật độ theo hạng mục chuẩn (Block/Depend/Epic/...), % issue có ≥1 link Block/Depend
- assignee: số người, coverage (% issue có assignee), top-10 tải
- comment: tổng, trung vị/issue
- output: bảng markdown + JSON metrics (dùng cho quyết định scope P1, trọng số nhãn §6.1)
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Iterable

from .events import Event, extract_events
from .normalize import LINK_TYPE_MAP, normalize_link_type


# --- loader đa định dạng ----------------------------------------------------

def _iter_issues_from_file(path: Path) -> Iterable[dict]:
    """Hỗ trợ: JSON array, JSONL. Trả về iterator của issue dict."""
    text_head = path.read_text(errors="replace")[:256].lstrip()
    if text_head.startswith("["):
        data = json.loads(path.read_text(errors="replace"))
        if isinstance(data, list):
            for d in data:
                yield d
        return
    # JSONL (mỗi dòng 1 issue) hoặc single JSON object
    with path.open(errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict) and ("key" in d or "fields" in d):
                yield d


def discover(root: Path) -> dict[str, list[Path]]:
    """Tìm file issue theo instance. Trả về {instance: [paths]}.

    Heuristic: tên thư mục/tệp chứa tên instance (Apache, Spring, JFrog, ...).
    In ra cây thư mục để đối chiếu khi layout khác dự đoán.
    """
    print(f"[eda] tree của {root}:")
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root)
            print(f"    {rel}  ({p.stat().st_size/1e6:.1f} MB)")

    mapping: dict[str, list[Path]] = {}
    candidates = [p for p in root.rglob("*") if p.is_file()
                  and p.suffix.lower() in {".json", ".jsonl", ".ndjson", ".txt", ".csv"}]
    for p in candidates:
        rel = p.relative_to(root)
        # instance = phần tên đầu tiên khớp chữ cái (không lấy file meta như README)
        for part in list(rel.parts)[:-1]:
            if part.lower() not in {"data", "dump", "jira", "issues"}:
                inst = part
                break
        else:
            inst = p.stem
        if inst.lower() in {"readme", "license", "metadata"}:
            continue
        mapping.setdefault(inst, []).append(p)
    return mapping


# --- metrics ----------------------------------------------------------------

def _median(xs: list[float]) -> float:
    return float(statistics.median(xs)) if xs else 0.0


def eda_instance(instance: str, issues: Iterable[dict]) -> dict[str, Any]:
    n_issue = 0
    created_ts: list[float] = []
    kind_counts: dict[str, int] = {}
    events_per_issue: list[float] = []
    link_type_counts: dict[str, int] = {}
    n_issue_with_block_or_depend = 0
    n_issue_any_link = 0
    assignee_counts: dict[str, int] = {}
    n_issue_assigned = 0
    comment_counts: list[int] = []
    statuses: dict[str, int] = {}
    open_issue = 0

    from .normalize import normalize_doc
    for doc in issues:
        doc = normalize_doc(doc)
        n_issue += 1
        f = doc.get("fields") or {}
        if f.get("created"):
            from .events import _to_epoch
            ts = _to_epoch(f["created"])
            if ts:
                created_ts.append(ts)
        st_raw = f.get("status")
        st = st_raw.get("name") if isinstance(st_raw, dict) else st_raw
        if st:
            st = str(st)
            statuses[st] = statuses.get(st, 0) + 1
            if not st.lower().startswith(("close", "done", "resolved", "complete", "cancelled", "canceled", "wont", "won't")):
                open_issue += 1
        if f.get("assignee"):
            n_issue_assigned += 1
            name = f["assignee"].get("name") if isinstance(f.get("assignee"), dict) else str(f.get("assignee"))
            assignee_counts[name or "(null)"] = assignee_counts.get(name or "(null)", 0) + 1
        else:
            assignee_counts["(unassigned)"] = assignee_counts.get("(unassigned)", 0) + 1

        links = doc.get("issueLinks") or []
        has_bd = False
        if links:
            n_issue_any_link += 1
        for lk in links:
            raw = (lk.get("type") or {}).get("name")
            std = normalize_link_type(raw)
            link_type_counts[std] = link_type_counts.get(std, 0) + 1
            if std in ("Block", "Depend"):
                has_bd = True
        if has_bd:
            n_issue_with_block_or_depend += 1

        comments = doc.get("comments") or []
        comment_counts.append(len(comments))

        evs = extract_events(doc)
        events_per_issue.append(len(evs))
        for e in evs:
            kind_counts[e.kind] = kind_counts.get(e.kind, 0) + 1

    n = max(n_issue, 1)
    return {
        "instance": instance,
        "n_issues": n_issue,
        "n_open_issues": open_issue,
        "time_range": {
            "min_created": min(created_ts) if created_ts else None,
            "max_created": max(created_ts) if created_ts else None,
        },
        "events": {
            "total": sum(kind_counts.values()),
            "median_per_issue": _median(events_per_issue),
            "by_kind": dict(sorted(kind_counts.items(), key=lambda x: -x[1])),
        },
        "links": {
            "total": sum(link_type_counts.values()),
            "by_std_type": dict(sorted(link_type_counts.items(), key=lambda x: -x[1])),
            "pct_issues_with_block_or_depend": round(n_issue_with_block_or_depend / n * 100, 2),
            "pct_issues_with_any_link": round(n_issue_any_link / n * 100, 2),
        },
        "assignees": {
            "unique": len([k for k in assignee_counts if k != "(unassigned)"]),
            "pct_assigned": round(n_issue_assigned / n * 100, 2),
            "top10": sorted(assignee_counts.items(), key=lambda x: -x[1])[:10],
        },
        "comments": {
            "total": sum(comment_counts),
            "median_per_issue": _median(comment_counts),
        },
        "top_statuses": dict(sorted(statuses.items(), key=lambda x: -x[1])[:10]),
    }


# --- report -----------------------------------------------------------------

def render_markdown(rows: list[dict]) -> str:
    L: list[str] = ["# EDA The Public Jira Dataset", ""]
    L.append(f"Number of instances analysed: **{len(rows)}**")
    L.append("")
    for r in rows:
        L.append(f"## {r['instance']}")
        L.append(f"- Issues: **{r['n_issues']:,}** (mở: {r['n_open_issues']:,})")
        tr = r["time_range"]
        if tr["min_created"]:
            import datetime
            fmt = lambda ts: datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()
            L.append(f"- Khoảng thời gian issue: {fmt(tr['min_created'])} → {fmt(tr['max_created'])}")
        e = r["events"]
        L.append(f"- Events: **{e['total']:,}** (trung vị {e['median_per_issue']}/issue) — phân bố: "
                 + ", ".join(f"{k}:{v:,}" for k, v in e["by_kind"].items()))
        lk = r["links"]
        L.append(f"- Links: {lk['total']:,} endpoint-occurrences (≈ {lk['total']//2:,} link độc lập — "
                 f"mỗi link xuất hiện trong document của cả 2 issue); "
                 f"% issue có Block/Depend: **{lk['pct_issues_with_block_or_depend']}%**; "
                 f"% issue có ≥1 link bất kỳ: {lk['pct_issues_with_any_link']}%")
        L.append("  - Theo loại chuẩn: " + ", ".join(f"{k}:{v:,}" for k, v in list(lk["by_std_type"].items())[:10]))
        a = r["assignees"]
        L.append(f"- Assignees: {a['unique']:,} người; % issue có assignee: {a['pct_assigned']}%")
        c = r["comments"]
        L.append(f"- Comments: {c['total']:,} (trung vị {c['median_per_issue']}/issue)")
        L.append(f"- Status top: " + ", ".join(f"{k}:{v:,}" for k, v in list(r["top_statuses"].items())[:5]))
        L.append("")
    # quyết định gợi ý
    L.append("## Gợi ý quyết định P1 (từ số liệu)")
    for r in rows:
        ev = r["events"]["total"]
        if ev < 500_000:
            verdict = "nhẹ — chạy được CPU lẫn GPU, phù hợp sanity"
        elif ev < 5_000_000:
            verdict = "vừa — GPU thoải mái, CPU chấp nhận được (giảm epoch)"
        else:
            verdict = "nặng — ưu tiên GPU (RTX 4060 Ti)"
        L.append(f"- **{r['instance']}**: {ev:,} events → {verdict}")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw", help="thư mục chứa dataset đã giải nén")
    ap.add_argument("--out", default="data/eda_report.md")
    ap.add_argument("--only", default=None, help="chỉ chạy 1 instance (tên, case-insensitive)")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Không thấy thư mục {root} — hãy giải nén dataset trước (xem README data/raw).")

    mapping = discover(root)
    if args.only:
        keep = {k.lower(): v for k, v in mapping.items()}
        mapping = {k: v for k, v in mapping.items() if k.lower() in keep}
        if not mapping:
            raise SystemExit(f"Không tìm thấy instance '{args.only}' trong {list(keep)}")

    rows = []
    for inst, paths in sorted(mapping.items()):
        print(f"[eda] == {inst} ({len(paths)} file(s)) ==")
        def _issues():
            for p in paths:
                yield from _iter_issues_from_file(p)
        try:
            row = eda_instance(inst, _issues())
        except Exception as ex:  # noqa: BLE001 - EDA phải tiếp tục các instance khác
            print(f"[eda] !! lỗi {inst}: {type(ex).__name__}: {ex}")
            row = {"instance": inst, "error": f"{type(ex).__name__}: {ex}"}
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k not in ("assignees",)}, default=str)[:600])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(rows), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"[eda] done -> {out} (+ .json)")


if __name__ == "__main__":
    main()
