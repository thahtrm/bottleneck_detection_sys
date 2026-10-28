"""Stage 1 — Full-Jira (2,685,911 issues) Task-Criticality dataset with strictly T0-safe features.

Outputs (data/tgn_full/):
  svd16.npz                TruncatedSVD(16) components (fitted on train) -> model bundle
  issues_t0.parquet        one row per issue (row_id aligned with data/emb_row_to_unique_all.npy)
                           split, ground truth, T0 features, SVD16 text embedding
  links_timed.parquet      Block/Depend/... links with a leak-safe timestamp
  criticality_{train,val,test}.parquet   harness-compatible ground-truth files

Leakage controls (differences from the Spring pilot):
  * priority / issuetype / assignee are reconstructed AS OF CREATION from the first changelog
    entry of each field (the issues table stores the final values).
  * link counts are counted only for links whose timestamp <= T0. Link timestamps come from the
    `Link` changelog; links without a changelog entry get max(updated_ts) of both endpoints
    (late, never early). issue_links.approx_ts is NOT used: it equals the source creation time
    even when the target did not exist yet.
  * the final num_links / has_block_or_depend / blocks_count columns are never used as features.
  * TruncatedSVD and the propensity back-off means are fitted on train issues only.
The T0 feature code lives in early_risk_detection.features.t0 (shared with serving).
Ground truth = Spring-pilot formula (CPM marginal delay, cascading delay, slack, blast radius,
inverted PageRank, priority, slippage) on the Block+Depend DAG of all 16 instances.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import duckdb
import networkx as nx
import numpy as np
import pandas as pd
from numpy.lib.format import open_memmap
from sklearn.decomposition import TruncatedSVD

from early_risk_detection._logging import setup_logging
from early_risk_detection.features.t0 import (
    add_t0_features,
    chronological_split,
    issue_durations,
    load_issues_t0,
    load_timed_links,
    planned_and_sp,
)

log = logging.getLogger(__name__).info


def dependency_dag(df: pd.DataFrame, links: pd.DataFrame) -> nx.DiGraph:
    """Edge prerequisite -> dependent. 'A Depends B': B -> A. 'A Blocks B': A -> B."""
    key_to_row = pd.Series(df["row_id"].values, index=df["instance"] + "|" + df["issue_key"])
    dep = links[links["link_type_std"].isin(["Block", "Depend"])]
    s = key_to_row.reindex(dep["instance"] + "|" + dep["source_key"]).values
    t = key_to_row.reindex(dep["instance"] + "|" + dep["target_key"]).values
    ok = ~(np.isnan(s) | np.isnan(t))
    s, t, lt = s[ok].astype(np.int64), t[ok].astype(np.int64), dep["link_type_std"].values[ok]
    pre = np.where(lt == "Depend", t, s)
    post = np.where(lt == "Depend", s, t)
    G = nx.DiGraph()
    G.add_edges_from((int(a), int(b)) for a, b in zip(pre, post) if a != b)
    removed = 0
    while True:  # break the few dependency cycles (68 SCCs in the full dataset)
        try:
            cyc = nx.find_cycle(G)
        except nx.NetworkXNoCycle:
            break
        G.remove_edge(*cyc[-1][:2])
        removed += 1
    log(f"  DAG: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges, {removed} cycle edges removed")
    return G


def cpm_metrics(G: nx.DiGraph, dur: np.ndarray, plan: np.ndarray, slip: np.ndarray, n: int) -> dict[str, np.ndarray]:
    blast = np.zeros(n, np.float32)
    casc = np.zeros(n, np.float32)
    slack = np.full(n, 999.0, np.float32)
    marg = np.zeros(n, np.float32)
    ipr = np.zeros(n, np.float32)
    pr = nx.pagerank(G.reverse(copy=False), alpha=0.85, max_iter=200)
    for k, v in pr.items():
        ipr[k] = v
    for comp in nx.weakly_connected_components(G):
        sub = G.subgraph(comp)
        for u in comp:
            dist = nx.single_source_shortest_path_length(sub, u)
            dist.pop(u, None)
            blast[u] = len(dist)
            if dist:
                d = np.fromiter(dist.values(), np.float32)
                vs = slip[np.fromiter(dist.keys(), np.int64)]
                casc[u] = float(np.sum(slip[u] / d + vs / (d + 1.0)))
        topo = list(nx.topological_sort(sub))
        es, ef = {}, {}
        for u in topo:
            es[u] = max((ef[p] for p in sub.predecessors(u)), default=0.0)
            ef[u] = es[u] + float(dur[u])
        finish = max(ef.values())
        ls = {}
        for u in reversed(topo):
            lf = min((ls[s] for s in sub.successors(u)), default=finish)
            ls[u] = lf - float(dur[u])
            slack[u] = max(0.0, ls[u] - es[u])
        # Only critical-path tasks (slack == 0) can shorten the component finish.
        for u in comp:
            if dur[u] <= plan[u] or slack[u] > 1e-6:
                continue
            cf = {}
            for k in topo:
                cf[k] = max((cf[p] for p in sub.predecessors(k)), default=0.0) + float(plan[u] if k == u else dur[k])
            marg[u] = max(0.0, finish - max(cf.values()))
    return {"blast_radius": blast, "downstream_delay": casc, "slack_time": slack,
            "marginal_delay": marg, "inverted_pagerank": ipr}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default="data/jira.duckdb")
    ap.add_argument("--out_dir", default="data/tgn_full")
    ap.add_argument("--emb_dir", default="data", help="emb_row_to_unique_all.npy / emb_unique_all_fp16.npy")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    setup_logging()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    con = duckdb.connect(args.duckdb, read_only=True)
    log("[1/6] Loading issues and reconstructing T0 attributes...")
    df = load_issues_t0(con)
    log(f"  {len(df):,} issues | priority changed after T0: {df.prio_changed.mean():.2%} | "
        f"type changed: {df.type_changed.mean():.2%} | assignee changed: {df.assignee_changed.mean():.2%}")
    log("[2/6] Loading links with leak-safe timestamps...")
    links = load_timed_links(con)
    con.close()
    log(f"  {len(links):,} links, {links.ts_from_changelog.mean():.2%} timestamped from Link changelog")
    links.to_parquet(out / "links_timed.parquet", index=False)

    n = len(df)
    # Ground-truth quantities use FINAL attributes (they are labels, not features).
    prio = df["priority_norm"].fillna(0.4).values.astype(np.float32)
    planned, sp, _ = planned_and_sp(prio, df["issuetype"], df["issuetype_theme"], df["summary"])
    dur = issue_durations(df)
    slip = np.maximum(0.0, dur - planned).astype(np.float32)

    log("[3/6] Graph CPM on the Block+Depend DAG of all 16 instances...")
    G = dependency_dag(df, links)
    m = cpm_metrics(G, dur, planned, slip, n)
    out_deg = np.zeros(n, np.int32)
    for u, d in G.out_degree():
        out_deg[u] = d
    for k, v in m.items():
        df[k] = v
    df["blocks_count_final"] = out_deg

    log("[4/6] Ground-truth criticality score...")
    graph_crit = (0.35 * m["marginal_delay"] / (m["marginal_delay"].max() + 1e-4)
                  + 0.30 * m["downstream_delay"] / (m["downstream_delay"].max() + 1e-4)
                  + 0.15 * np.exp(-m["slack_time"] / 14.0)
                  + 0.10 * np.clip(m["blast_radius"] / 5.0, 0, 1)
                  + 0.10 * m["inverted_pagerank"] / (m["inverted_pagerank"].max() + 1e-4)).astype(np.float32)
    slip_ratio = np.clip(slip / (planned + 1e-4), 0.0, 3.0) / 3.0
    is_blocker = (m["blast_radius"] > 0) | (out_deg > 0)
    df["is_blocker_final"] = is_blocker.astype(np.int8)
    df["raw_criticality"] = np.where(
        is_blocker,
        0.70 + 0.30 * graph_crit + 0.20 * prio + 0.10 * slip_ratio,
        0.50 * prio + 0.35 * slip_ratio + 0.15 * np.clip(sp / 15.0, 0, 1)).astype(np.float32)
    df["duration_days"], df["slippage_days"], df["planned_duration_days"] = dur, slip, planned

    df["split"] = chronological_split(df)
    df["ground_truth_criticality"] = np.nan
    for s in ["train", "val", "test"]:
        mask = df["split"].values == s
        df.loc[mask, "ground_truth_criticality"] = np.round(
            df.loc[mask, "raw_criticality"].rank(pct=True).values, 5)
    df["is_critical_p0"] = (df["ground_truth_criticality"] >= 0.95).astype(np.int8)
    cdt = pd.to_datetime(df["created_ts"], unit="s", utc=True)
    df["query_group"] = df["instance"] + "_" + df["project"].fillna("APP") + "_" + \
        cdt.dt.year.astype(str) + "_Q" + cdt.dt.quarter.astype(str)
    for s in ["train", "val", "test"]:
        sub = df[df.split == s]
        log(f"  {s:5s}: {len(sub):,} rows ({pd.to_datetime(sub.created_ts.min(), unit='s').date()} -> "
            f"{pd.to_datetime(sub.created_ts.max(), unit='s').date()}) | P0 {sub.is_critical_p0.mean():.2%} | "
            f"blockers {sub.is_blocker_final.mean():.2%}")

    log("[5/6] T0 static, dynamic, link and propensity features...")
    backoff = add_t0_features(df, links, dur, fit_mask=df["split"].values == "train")
    (out / "propensity_backoff.json").write_text(json.dumps(backoff, indent=2))
    log(f"  issues with >=1 link known at T0: {(df.links_t0_any > 0).mean():.3%} "
        f"(vs {(df.blocks_count_final > 0).mean():.3%} final Block/Depend out-degree)")

    log("[6/6] TruncatedSVD(16) on Ollama embeddings, fitted on train only...")
    row_to_unique = np.load(Path(args.emb_dir) / "emb_row_to_unique_all.npy")
    emb = open_memmap(Path(args.emb_dir) / "emb_unique_all_fp16.npy", mode="r")
    assert len(row_to_unique) == n, (len(row_to_unique), n)
    rng = np.random.default_rng(args.seed)
    train_rows = np.flatnonzero(df["split"].values == "train")
    fit_rows = np.sort(rng.choice(train_rows, size=200_000, replace=False))
    svd = TruncatedSVD(n_components=16, random_state=args.seed).fit(emb[row_to_unique[fit_rows]].astype(np.float32))
    log(f"  explained variance: {svd.explained_variance_ratio_.sum():.4f}")
    np.savez(out / "svd16.npz", components=svd.components_.astype(np.float32))
    Z = np.zeros((n, 16), np.float32)
    for c in range(0, n, 200_000):
        Z[c:c + 200_000] = svd.transform(emb[row_to_unique[c:c + 200_000]].astype(np.float32))
    for k in range(16):
        df[f"svd_{k}"] = Z[:, k]

    df = df.drop(columns=["summary"])
    df.to_parquet(out / "issues_t0.parquet", index=False)
    keep = ["issue_key", "instance", "project", "query_group", "created_ts", "raw_criticality",
            "ground_truth_criticality", "is_critical_p0", "is_blocker_final"]
    for s in ["train", "val", "test"]:
        sub = df.loc[df.split == s, keep + ["row_id"]].reset_index(drop=True)
        # issue_key is not globally unique across instances -> harness joins on uid
        sub["issue_key"] = sub["instance"] + "|" + sub["issue_key"]
        sub.to_parquet(out / f"criticality_{s}.parquet", index=False)
    log(f"Done in {time.time() - t_start:.0f}s -> {out}")


if __name__ == "__main__":
    main()
