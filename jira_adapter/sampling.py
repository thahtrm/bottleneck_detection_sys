"""Chọn mẫu pilot cho gắn nhãn bottleneck bằng LLM — §4.2 của
`docs/phuong-an-gan-nhan-bottleneck-bang-llm.md`.

Ba tầng, không chồng lấn, lấy theo thứ tự:
  v3        : issue dương theo nhãn v3 (≥1 link Block/Depend, đúng `labels.py`)
  candidate : thỏa ≥1 tiêu chí F (heuristic) — không thuộc v3
  random    : phần còn lại — để ước lượng recall bị bỏ sót
Trong mỗi tầng: phân bổ tỉ lệ theo (mở/đóng, theme), seed cố định.

Chạy (mongod @127.0.0.1:27017, db JiraReposAnon):
    PYTHONPATH=.pylibs python -m jira_adapter.sampling --instance JFrog --out data/llm_pilot

Ra `data/llm_pilot/{instance}/`:
    dossiers/{key}.json   hồ sơ đầy đủ (máy đọc)
    text/{key}.md         hồ sơ dạng văn bản (prompt LLM / người chấm)
    manifest.csv          key, tầng, lý do ứng viên, chấm đôi — KHÔNG đưa cho người chấm
    gold_rater_A.csv      300 key (thứ tự xáo trộn) + cột để chấm
    gold_rater_B.csv      100 key chấm độc lập (đo κ người–người)
    summary.json          kích thước quần thể/tầng, ước lượng token
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from .dossier import build_dossier, build_project_context, render_text
from .labels import build_states

TIERS = {"v3": 60, "candidate": 120, "random": 120}
DOUBLE = {"v3": 20, "candidate": 40, "random": 40}

GOLD_COLUMNS = ["key", "rater", "B1", "B2", "B3", "overall_K_CK_C", "is_bottleneck",
                "role", "type", "episode_start", "episode_end", "exclusion", "reason"]


def candidate_reasons(d: dict) -> list[str]:
    """Tiêu chí F (§2.1) dạng heuristic để lọc ứng viên — rộng tay, LLM/người lọc lại."""
    s, r = d["signals"], []
    if (s["F1_max_active_dwell_pct"] or 0) >= 0.9:
        r.append("F1_active")
    if (s["F1_max_new_dwell_pct"] or 0) >= 0.9 and d["assignee_now"] and d["priority_norm"] >= 0.6:
        r.append("F1_committed_waiting")
    if s["F2_wait_comment_idx"]:
        r.append("F2_wait_comment")
    if s["F3_reopen"] >= 1 or s["F3_status_pingpong"] >= 2 or s["F3_assignee_handoffs"] >= 3:
        r.append("F3_churn")
    if s["F4_high_prio_unassigned"]:
        r.append("F4_unassigned_high_prio")
    return r


def _stratified(keys: list[str], strata: dict[str, tuple], n: int, rng: random.Random) -> list[str]:
    """Phân bổ tỉ lệ theo tầng con (largest remainder), rồi rút ngẫu nhiên."""
    if len(keys) <= n:
        return list(keys)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for k in keys:
        groups[strata[k]].append(k)
    quota = {g: n * len(v) / len(keys) for g, v in groups.items()}
    alloc = {g: int(q) for g, q in quota.items()}
    for g in sorted(quota, key=lambda g: quota[g] - alloc[g], reverse=True)[: n - sum(alloc.values())]:
        alloc[g] += 1
    out = []
    for g in sorted(groups):
        out += rng.sample(sorted(groups[g]), alloc[g])
    return out


def sample_instance(docs: list[dict], seed: int = 0,
                    tiers: dict[str, int] = TIERS, double: dict[str, int] = DOUBLE):
    ctx = build_project_context(docs)
    dossiers = {}
    for doc in docs:
        if doc.get("key"):
            d = build_dossier(doc, ctx)
            dossiers[d["key"]] = d
    v3 = {s.key for s in build_states(docs) if s.links_total >= 1}
    reasons = {k: candidate_reasons(d) for k, d in dossiers.items()}
    strata = {k: (d["status_category_now"] == "done", d["theme"]) for k, d in dossiers.items()}

    pools = {
        "v3": [k for k in dossiers if k in v3],
        "candidate": [k for k in dossiers if k not in v3 and reasons[k]],
        "random": [k for k in dossiers if k not in v3 and not reasons[k]],
    }
    rng = random.Random(seed)
    chosen: dict[str, list[str]] = {t: _stratified(pools[t], strata, n, rng) for t, n in tiers.items()}
    doubles = {t: set(rng.sample(sorted(chosen[t]), min(double[t], len(chosen[t])))) for t in tiers}
    stats = {"seed": seed, "n_issues": len(dossiers), "data_end": ctx.end_ts,
             "pool_sizes": {t: len(p) for t, p in pools.items()},
             "sample_sizes": {t: len(c) for t, c in chosen.items()},
             "candidate_reason_counts": _count([r for k in pools["candidate"] for r in reasons[k]]),
             "bulk_close_batches": len(ctx.bulk_close)}
    return dossiers, chosen, doubles, reasons, stats


def _count(xs):
    out = defaultdict(int)
    for x in xs:
        out[x] += 1
    return dict(sorted(out.items()))


def write_pilot(out_dir: Path, dossiers, chosen, doubles, reasons, stats, seed: int = 0) -> dict:
    (out_dir / "dossiers").mkdir(parents=True, exist_ok=True)
    (out_dir / "text").mkdir(parents=True, exist_ok=True)
    rows, chars = [], []
    for tier, keys in chosen.items():
        for k in keys:
            d = dossiers[k]
            (out_dir / "dossiers" / f"{k}.json").write_text(
                json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            txt = render_text(d)
            (out_dir / "text" / f"{k}.md").write_text(txt, encoding="utf-8")
            chars.append(len(txt))
            rows.append({"key": k, "tier": tier, "double_rated": int(k in doubles[tier]),
                         "status_category_now": d["status_category_now"], "theme": d["theme"],
                         "candidate_reasons": ";".join(reasons[k]),
                         "flags": ";".join(d["flags"]), "approx_tokens": len(txt) // 4})
    with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # bảng chấm: thứ tự xáo trộn, không lộ tầng
    rng = random.Random(seed + 1)
    all_keys = [r["key"] for r in rows]
    for rater, keys in (("A", all_keys), ("B", [r["key"] for r in rows if r["double_rated"]])):
        keys = list(keys)
        rng.shuffle(keys)
        with (out_dir / f"gold_rater_{rater}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(GOLD_COLUMNS)
            for k in keys:
                w.writerow([k, rater] + [""] * (len(GOLD_COLUMNS) - 2))

    chars.sort()
    stats = dict(stats, n_written=len(rows),
                 approx_tokens={"median": chars[len(chars) // 2] // 4, "p90": chars[int(0.9 * len(chars))] // 4,
                                "max": chars[-1] // 4, "total": sum(chars) // 4})
    (out_dir / "summary.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    from .build_mongo import connect, fetch_instance
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:27017")
    ap.add_argument("--db", default="JiraReposAnon")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--out", default="data/llm_pilot")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    connect(args.host, args.db).client.admin.command("ping")
    docs = fetch_instance(args.host, args.instance, db=args.db)
    res = sample_instance(docs, seed=args.seed)
    stats = write_pilot(Path(args.out) / args.instance, *res, seed=args.seed)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
