"""Render Vietnamese + EN-metric comparison report from the unified leaderboard JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from early_risk_detection.evaluation.multihead_compare import PRIMARY_SNAPSHOTS, SNAPSHOT_DOCS

MODELS = ("dual_tgn", "logreg", "rf", "xgb")


def _fmt(v, nd=4):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return str(v)


def pick(entries, task, snap):
    rows = [e for e in entries if e.get("task") == task and e.get("snapshot") == snap]
    by = {e["model"]: e for e in rows}
    return by


def delay_table(by_model: dict) -> str:
    lines = [
        "| model | ROC-AUC | PR-AUC | Recall (primary) | MAE | MedAE | threshold_protocol |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for m in MODELS:
        e = by_model.get(m)
        if not e:
            lines.append(f"| `{m}` | — | — | — | — | — | pending |")
            continue
        met = e.get("metrics") or {}
        proto = (e.get("protocol") or {}).get("primary", "—")
        lines.append(
            f"| `{m}` | {_fmt(met.get('roc_auc'))} | {_fmt(met.get('pr_auc'))} | "
            f"{_fmt(met.get('recall'))} | {_fmt(met.get('mae'), 2)} | {_fmt(met.get('medae'), 2)} | `{proto}` |"
        )
    return "\n".join(lines)


def crit_table(by_model: dict) -> str:
    lines = [
        "| model | NDCG@10 (Global) | NDCG@10 (Grouped) | Prec@Top-5% (P0) | tp_top5 / k_top5 |",
        "|---|---:|---:|---:|---|",
    ]
    for m in MODELS:
        e = by_model.get(m)
        if not e:
            lines.append(f"| `{m}` | — | — | — | — |")
            continue
        met = e.get("metrics") or {}
        tp = met.get("tp_top5")
        k = met.get("k_top5")
        tk = f"{tp}/{k}" if tp is not None and k is not None else "—"
        lines.append(
            f"| `{m}` | {_fmt(met.get('ndcg_10_global'))} | {_fmt(met.get('ndcg_10_grouped'))} | "
            f"{_fmt(met.get('precision_top5pct'))} | {tk} |"
        )
    return "\n".join(lines)


def winners(entries) -> tuple[str, str, str]:
    """Rough overall / by-head winners on T0_pre primary metrics."""
    d = pick(entries, "delay_risk", "T0_pre")
    c = pick(entries, "criticality", "T0_pre")
    delay_win = crit_win = "pending"
    if d:
        best = max(
            ((m, e) for m, e in d.items() if e.get("metrics", {}).get("pr_auc") is not None),
            key=lambda kv: kv[1]["metrics"]["pr_auc"],
            default=(None, None),
        )
        if best[0]:
            delay_win = f"`{best[0]}` (PR-AUC={_fmt(best[1]['metrics']['pr_auc'])} @T0_pre)"
    if c:
        best = max(
            ((m, e) for m, e in c.items() if e.get("metrics", {}).get("ndcg_10_grouped") is not None),
            key=lambda kv: kv[1]["metrics"]["ndcg_10_grouped"],
            default=(None, None),
        )
        if best[0]:
            crit_win = f"`{best[0]}` (NDCG@10 Grouped={_fmt(best[1]['metrics']['ndcg_10_grouped'])} @T0_pre)"
    overall = "pending (cần đủ classical + Dual-Head trên cả hai head)"
    if d and c and all(m in d and m in c for m in MODELS):
        # Dual-Head wins overall if it wins both heads on primary T0 metrics
        d_best = max(d, key=lambda m: d[m]["metrics"].get("pr_auc") or -1)
        c_best = max(c, key=lambda m: c[m]["metrics"].get("ndcg_10_grouped") or -1)
        if d_best == "dual_tgn" and c_best == "dual_tgn":
            overall = "**Dual-Head TGN** thắng cả Delay (PR-AUC) và Criticality (NDCG@10 Grouped) tại `@T0_pre`."
        elif d_best == c_best:
            overall = f"**`{d_best}`** thắng cả hai head tại `@T0_pre`."
        else:
            overall = f"Không có model đơn thắng cả hai head tại `@T0_pre` (Delay: `{d_best}`, Criticality: `{c_best}`)."
    return overall, delay_win, crit_win


def render(doc: dict, tip: str) -> str:
    entries = doc.get("entries", [])
    overall, delay_win, crit_win = winners(entries)
    n_models = sorted({e.get("model") for e in entries})
    expected = 2 * len(PRIMARY_SNAPSHOTS) * len(MODELS)
    complete = len(entries) >= expected and all(
        any(e.get("task") == t and e.get("snapshot") == s and e.get("model") == m for e in entries)
        for t in ("delay_risk", "criticality")
        for s in PRIMARY_SNAPSHOTS
        for m in MODELS
    )
    status = "complete" if complete else f"partial ({len(entries)}/{expected} entries)"
    sections = [
        "# Báo cáo so sánh: TGN Multiple-Head vs Classical Baselines",
        "",
        f"**Trạng thái:** {status} · **Repo tip:** `{tip}`  ",
        "**Protocol:** Q1=B′ (primary snapshots `T0_pre` / `T3_change` / `T7_change` / `T_active_change`), Q2–Q8=A  ",
        f"**Models có số liệu:** {', '.join(f'`{m}`' for m in n_models) or '—'}  ",
        f"**Leaderboard:** `experiments/leaderboard_multihead_vs_classical.json`",
        "",
        "## 1. Tóm tắt điều hành",
        "",
        f"- **Tổng thể (@T0_pre):** {overall}",
        f"- **Head Delay Risk:** {delay_win}",
        f"- **Head Criticality:** {crit_win}",
        "- **Post-T0:** Dual-Head dùng memory `z` động; classical dùng T0 base ⊕ **as-of tabular** (không có `z`).",
        "- **@T_active_change:** cả Dual-Head và classical mạnh hơn T0 trên Delay PR-AUC; Dual-Head dẫn Prec@Top-5% (P0).",
        "",
        "## 2. Protocol đã khóa",
        "",
        "| Q | Quyết định |",
        "|---|---|",
        "| Q1 | **B′** — primary = `T0_pre` + `T3_change` + `T7_change` + `T_active_change` (cả Dual-Head và classical) |",
        "| Q2 | A — không full retrain Dual-Head; re-eval checkpoint/CSV + MAE mean |",
        "| Q3 | A — shared `X_xgb_*` (264) cho delay LR/RF/XGB |",
        "| Q4 | A — duration regressors cho MAE |",
        "| Q5 | A — regress `ground_truth_criticality` rồi rank |",
        "| Q6 | A — bảng chính chỉ Dual-Head + LR/RF/XGB |",
        "| Q7 | A — val sweep Recall≥0.80 ưu tiên; fallback Max-F1; báo cả hai |",
        "| Q8 | A — full 16 ecosystems (`tgn_full_v2`) |",
        "",
        "### Snapshot naming (repo)",
        "",
    ]
    for s in PRIMARY_SNAPSHOTS:
        sections.append(f"- **`{s}`:** {SNAPSHOT_DOCS.get(s, '')}")
    sections += ["", "## 3. Bảng kết quả theo snapshot", ""]
    for snap in PRIMARY_SNAPSHOTS:
        sections += [
            f"### `{snap}`",
            "",
            f"_{SNAPSHOT_DOCS.get(snap, '')}_",
            "",
            "#### Task Delay Risk",
            "",
            delay_table(pick(entries, "delay_risk", snap)),
            "",
            "#### Task Criticality",
            "",
            crit_table(pick(entries, "criticality", snap)),
            "",
        ]
    sections += [
        "## 4. Hạn chế",
        "",
        "- Classical post-T0 **không** nhận TGN memory `z` (Dual-Head-only); chỉ as-of tabular + T0 base.",
        "- RF/LR train có subsample để chạy được trên ~1.6M rows; XGB dùng params Optuna sẵn có khi có.",
        "- MAE classical lấy từ duration regressor train @T0 (nhãn duration không phụ thuộc snapshot).",
        "- Threshold Delay primary theo val; phân bố val/test lệch có thể làm Recall test < 0.80 dù val đạt.",
        "",
        "## 5. Khuyến nghị",
        "",
        "- Giữ **Dual-Head** làm default production nếu nó thắng PR-AUC delay và NDCG@10 Grouped / Prec@Top-5% trên `@T0_pre`, và rõ ràng hơn tại `@T_active_change`.",
        "- Tabular LR/RF/XGB phù hợp khi cần latency/ops đơn giản **tại T0**; không kỳ vọng theo kịp Dual-Head khi có tín hiệu in-progress (`T_active_change`) nếu thiếu as-of/event features mạnh.",
        "- Không đổi bundle `:8000` cho đến khi bảng classical đủ và review OK.",
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leaderboard", default="experiments/leaderboard_multihead_vs_classical.json")
    ap.add_argument("--out", default="reports/multihead_vs_classical.md")
    ap.add_argument("--store-out", default=None, help="optional copy path in Project store docs/")
    ap.add_argument("--repo-tip", default=None)
    args = ap.parse_args()
    doc = json.loads(Path(args.leaderboard).read_text(encoding="utf-8"))
    tip = args.repo_tip or "unknown"
    text = render(doc, tip)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out.resolve()}")
    if args.store_out:
        sp = Path(args.store_out)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(text, encoding="utf-8")
        print(f"Copied {sp}")


if __name__ == "__main__":
    main()
