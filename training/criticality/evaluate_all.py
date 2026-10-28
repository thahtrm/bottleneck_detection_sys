"""Stage 5 — run the immutable harness on every model, collect scale statistics and draw figures.

Writes: experiments/leaderboard_jira_full.json (via the harness), data/tgn_full/eval_summary.json,
docs/figures/tgn_full_*.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from early_risk_detection.evaluation import evaluate_criticality

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Paths are relative to the repo root (set by main from --repo).
REPO = Path(".")
DATA = REPO / "data/tgn_full"
FIG = REPO / "docs/figures"
LEADERBOARD = REPO / "experiments/leaderboard_jira_full.json"
MODELS = ["gbdt_static", "gbdt_tgn", "mlp_static", "tgn_mse", "tgn_hybrid", "LEAKY_gbdt_pilot_features"]
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"


def scale_stats() -> pd.DataFrame:
    con = duckdb.connect(str(REPO / "data/jira.duckdb"), read_only=True)
    df = con.execute("""
        WITH i AS (SELECT instance, count(*) AS n_issues FROM issues
                   WHERE created_ts > 946684800 AND (resolved_ts IS NULL OR resolved_ts >= created_ts) GROUP BY 1),
             c AS (SELECT instance, count(*) changelogs,
                          count(*) FILTER (WHERE field IN ('status','assignee','priority')) tgn_changelogs
                   FROM issue_changelogs GROUP BY 1),
             m AS (SELECT instance, count(*) AS n_comments FROM issue_comments GROUP BY 1),
             l AS (SELECT instance, count(*) links,
                          count(*) FILTER (WHERE link_type_std IN ('Block','Depend')) dep_links
                   FROM issue_links GROUP BY 1)
        SELECT * FROM i LEFT JOIN c USING (instance) LEFT JOIN m USING (instance) LEFT JOIN l USING (instance)
        ORDER BY n_issues DESC""").df()
    con.close()
    iss = pd.read_parquet(DATA / "issues_t0.parquet", columns=["instance", "split"])
    split = iss.groupby(["instance", "split"]).size().unstack(fill_value=0)
    df = df.merge(split, left_on="instance", right_index=True, how="left").fillna(0)
    meta = json.loads((DATA / "events/meta.json").read_text())
    return df, meta


def style(ax) -> None:
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    for sp in ["left", "bottom"]:
        ax.spines[sp].set_color(MUTED)
        ax.spines[sp].set_linewidth(0.8)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig_score_distribution(gt: pd.DataFrame) -> dict:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True, facecolor="#fcfcfb")
    stats = {}
    for ax, name, title in zip(axes, ["tgn_mse", "tgn_hybrid"],
                               ["Before: pointwise MSE only (λ = 0)", "After: MSE + pairwise margin loss (λ*, γ*)"]):
        p = pd.read_csv(DATA / f"predictions/{name}/predictions_test.csv")
        m = gt.merge(p, on="issue_key")
        s = m["pred_score"].values
        bins = np.linspace(s.min(), s.max(), 60)
        neg, pos = s[m.is_critical_p0 == 0], s[m.is_critical_p0 == 1]
        ax.hist(neg, bins=bins, density=True, color=BLUE, alpha=0.55, label="Normal (non-P0)", edgecolor="#fcfcfb", linewidth=0.5)
        ax.hist(pos, bins=bins, density=True, color=ORANGE, alpha=0.55, label="P0 (top 5% true criticality)", edgecolor="#fcfcfb", linewidth=0.5)
        auc = roc_auc_score(m.is_critical_p0, s)
        gap = (np.median(pos) - np.median(neg)) / (np.std(s) + 1e-9)
        stats[name] = {"roc_auc": float(auc), "median_gap_in_std": float(gap),
                       "median_pos": float(np.median(pos)), "median_neg": float(np.median(neg))}
        ax.set_title(title, fontsize=10.5, color=INK, loc="left")
        ax.text(0.98, 0.95, f"ROC-AUC {auc:.3f}\nmedian gap {gap:.2f} σ", transform=ax.transAxes,
                ha="right", va="top", fontsize=9, color=MUTED)
        ax.set_xlabel("Predicted criticality score", fontsize=9.5, color=MUTED)
        style(ax)
    axes[0].set_ylabel("Density", fontsize=9.5, color=MUTED)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left", labelcolor=INK)
    fig.suptitle("Out-of-time test set (346,174 issues): score distribution by true class", fontsize=12, color=INK,
                 x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / "tgn_full_score_distribution.png", dpi=160)
    plt.close(fig)
    return stats


def fig_per_instance(per: dict[str, list[dict]]) -> None:
    a = pd.DataFrame(per["gbdt_static"]).set_index("instance")
    b = pd.DataFrame(per["tgn_hybrid"]).set_index("instance")
    order = a.index[a["n"] >= 500]
    y = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(order) + 1.2), facecolor="#fcfcfb")
    ax.barh(y - 0.2, a.loc[order, "precision_top5pct"], height=0.38, color=BLUE, label="Static GBDT", edgecolor="#fcfcfb")
    ax.barh(y + 0.2, b.loc[order, "precision_top5pct"], height=0.38, color=ORANGE, label="TGN hybrid", edgecolor="#fcfcfb")
    ax.set_yticks(y, [f"{i}  (n={a.loc[i, 'n']:,})" for i in order], fontsize=9, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("Precision@Top-5% (test)", fontsize=9.5, color=MUTED)
    style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, fontsize=9, loc="lower left", bbox_to_anchor=(0.0, 1.01), ncol=2)
    ax.set_title("Per-ecosystem Precision@Top-5% on the out-of-time test set", fontsize=11, color=INK, loc="left", pad=26)
    fig.tight_layout()
    fig.savefig(FIG / "tgn_full_per_instance_precision.png", dpi=160)
    plt.close(fig)


def main() -> None:
    global REPO, DATA, FIG, LEADERBOARD
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="repo root holding data/, docs/figures/, experiments/")
    ap.add_argument("--data_dir", default=None, help="default: <repo>/data/tgn_full")
    ap.add_argument("--leaderboard", default=None, help="default: <repo>/experiments/leaderboard_jira_full.json")
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--track_suffix", default="", help="appended to JiraFull_<model> track names")
    ap.add_argument("--no_figures", action="store_true")
    args = ap.parse_args()
    REPO = Path(args.repo)
    DATA = Path(args.data_dir) if args.data_dir else REPO / "data/tgn_full"
    FIG = REPO / "docs/figures"
    LEADERBOARD = Path(args.leaderboard) if args.leaderboard else REPO / "experiments/leaderboard_jira_full.json"
    FIG.mkdir(parents=True, exist_ok=True)
    if LEADERBOARD.exists():
        LEADERBOARD.unlink()  # one consolidated run per execution of this script
    results, per = {}, {}
    for name in args.models:
        if not (DATA / f"predictions/{name}").exists():
            continue
        for split in ["val", "test"]:
            e = evaluate_criticality(
                pred_file=str(DATA / f"predictions/{name}/predictions_{split}.csv"),
                track=f"JiraFull_{name}{args.track_suffix}", split=split,
                ground_truth_file=str(DATA / f"criticality_{split}.parquet"),
                leaderboard_file=str(LEADERBOARD), iteration=1,
                target_overrides={"ndcg": 0.85, "prec": 0.75, "rho": 0.70},
                experiment_name="Task_Criticality_Jira_Full_2.68M")
            results[f"{name}/{split}"] = {"metrics": e["metrics"], "target_status": e["target_status"]}
            if split == "test":
                per[name] = e["per_instance"]
    if args.no_figures:
        (DATA / "eval_summary.json").write_text(json.dumps({"results": results, "per_instance_test": per}, indent=2, default=float))
        print(json.dumps({k: v["metrics"] for k, v in results.items()}, indent=1))
        return
    gt = pd.read_parquet(DATA / "criticality_test.parquet")
    dist = fig_score_distribution(gt)
    fig_per_instance(per)
    stats, meta = scale_stats()
    out = {"results": results, "per_instance_test": per, "score_distribution": dist,
           "scale": stats.to_dict(orient="records"), "event_meta": meta}
    (DATA / "eval_summary.json").write_text(json.dumps(out, indent=2, default=float))
    print(json.dumps({k: v["metrics"] for k, v in results.items()}, indent=1))


if __name__ == "__main__":
    main()
