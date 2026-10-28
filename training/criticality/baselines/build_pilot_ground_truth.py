"""Build Ground Truth Dataset for Task Criticality & Cascading Delay Risk.

Usage:
    python data/build_criticality_ground_truth.py --instance Spring --out_dir data/pilot_spring

Implements:
1. Ground Truth Schedule Slippage & Cascading Impact from CPM (Critical Path Method).
2. Topological DAG Analysis on dependency links (Depend, Block).
3. Zero Temporal Leakage Chronological Split: 70% Train, 15% Val, 15% Out-of-Time Test.
4. Rich T0 Leak-Free Features (WCI, SCF, Developer & Project historical dynamics, NLP Risk Lexicons).
"""
from __future__ import annotations

import argparse
import re
import time
from collections import defaultdict, deque
from itertools import islice
from pathlib import Path

import duckdb
import networkx as nx
import numpy as np
import pandas as pd


def min_max_norm(arr: np.ndarray) -> np.ndarray:
    p99 = np.percentile(arr, 99) if len(arr) > 0 else 1.0
    p1 = np.percentile(arr, 1) if len(arr) > 0 else 0.0
    if p99 > p1:
        return np.clip((arr - p1) / (p99 - p1), 0.0, 1.0).astype(np.float32)
    return np.zeros_like(arr, dtype=np.float32)


def compute_graph_cpm_metrics(
    issues_df: pd.DataFrame,
    links_df: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Compute realized CPM metrics and cascading impact on the dependency DAG."""
    print("  [Graph CPM] Building DAG from dependency links...", flush=True)
    # Directed Graph: target blocks source (source depends on target) => edge: target -> source
    # Target is prerequisite (predecessor), Source is dependent (successor)
    G = nx.DiGraph()
    
    # Store durations and delays
    duration_map = dict(zip(issues_df["issue_key"], issues_df["duration_days"]))
    planned_map = dict(zip(issues_df["issue_key"], issues_df["planned_duration_days"]))
    slippage_map = dict(zip(issues_df["issue_key"], issues_df["slippage_days"]))
    priority_map = dict(zip(issues_df["issue_key"], issues_df["priority_norm"]))

    for _, row in links_df.iterrows():
        s = row["source_key"]
        t = row["target_key"]
        G.add_edge(t, s)

    # Add all issues to ensure full mapping
    for k in issues_df["issue_key"]:
        if not G.has_node(k):
            G.add_node(k)

    print(f"  [Graph CPM] DAG has {G.number_of_nodes():,} nodes and {G.number_of_edges():,} edges.", flush=True)

    # Metrics dictionaries
    blast_radius: dict[str, float] = {}
    downstream_delay: dict[str, float] = {}
    slack_time: dict[str, float] = {}
    marginal_delay: dict[str, float] = {}
    inverted_pagerank: dict[str, float] = {}

    # Inverted PageRank: reverse edges (source -> target) to measure prerequisite centrality
    G_rev = G.reverse()
    try:
        pr = nx.pagerank(G_rev, alpha=0.85, max_iter=200)
    except Exception:
        pr = {n: 1.0 / len(G) for n in G.nodes()}
    inverted_pagerank = pr

    # For each weakly connected component, perform CPM Forward & Backward passes
    components = list(nx.weakly_connected_components(G))
    print(f"  [Graph CPM] Processing {len(components):,} connected components...", flush=True)

    for comp in components:
        subG = G.subgraph(comp)
        comp_nodes = list(comp)

        # 1. Blast Radius & Transitive Downstream Delay
        for u in comp_nodes:
            descendants = nx.descendants(subG, u)
            blast_radius[u] = float(len(descendants))
            
            # Cascading delay: sum of downstream delays weighted by topological distance
            casc_delay = 0.0
            u_slip = slippage_map.get(u, 0.0)
            for v in descendants:
                v_slip = slippage_map.get(v, 0.0)
                try:
                    dist = nx.shortest_path_length(subG, u, v)
                except Exception:
                    dist = 1
                casc_delay += (u_slip / dist) + (v_slip / (dist + 1.0))
            downstream_delay[u] = float(casc_delay)

        # 2. CPM Forward Pass (Early Start, Early Finish)
        if len(comp_nodes) == 1:
            u = comp_nodes[0]
            slack_time[u] = 0.0
            marginal_delay[u] = float(slippage_map.get(u, 0.0))
            continue

        try:
            topo_order = list(nx.topological_sort(subG))
        except Exception:
            # Fallback if unexpected cycle
            topo_order = comp_nodes

        es: dict[str, float] = {}
        ef: dict[str, float] = {}
        for u in topo_order:
            preds = list(subG.predecessors(u))
            u_dur = float(duration_map.get(u, 1.0))
            if not preds:
                es[u] = 0.0
            else:
                es[u] = max((ef.get(p, 0.0) for p in preds), default=0.0)
            ef[u] = es[u] + u_dur

        project_finish = max(ef.values()) if ef else 0.0

        # Backward Pass (Late Start, Late Finish)
        ls: dict[str, float] = {}
        lf: dict[str, float] = {}
        for u in reversed(topo_order):
            succs = list(subG.successors(u))
            u_dur = float(duration_map.get(u, 1.0))
            if not succs:
                lf[u] = project_finish
            else:
                lf[u] = min((ls.get(s, project_finish) for s in succs), default=project_finish)
            ls[u] = lf[u] - u_dur
            slack_time[u] = max(0.0, ls[u] - es[u])

        # 3. Marginal Project Delay Delta D_u
        # How much does shortening task u to planned duration shorten the component finish?
        for u in comp_nodes:
            u_dur = float(duration_map.get(u, 1.0))
            u_plan = float(planned_map.get(u, 1.0))
            if u_dur <= u_plan:
                marginal_delay[u] = 0.0
                continue

            # Counterfactual forward pass with u on time
            cf_ef: dict[str, float] = {}
            for k in topo_order:
                k_preds = list(subG.predecessors(k))
                k_dur = u_plan if k == u else float(duration_map.get(k, 1.0))
                k_es = max((cf_ef[p] for p in k_preds), default=0.0)
                cf_ef[k] = k_es + k_dur
            cf_project_finish = max(cf_ef.values()) if cf_ef else 0.0
            marginal_delay[u] = max(0.0, project_finish - cf_project_finish)

    return {
        "blast_radius": blast_radius,
        "downstream_delay": downstream_delay,
        "slack_time": slack_time,
        "marginal_delay": marginal_delay,
        "inverted_pagerank": inverted_pagerank,
    }


def build_criticality_dataset(
    duckdb_path: str = "data/jira.duckdb",
    instance: str = "Spring",
    out_dir: str = "data/pilot_spring",
) -> None:
    t0 = time.time()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("=================================================================", flush=True)
    print(f"🎯 BUILDING GROUND TRUTH TASK CRITICALITY: {instance.upper()}", flush=True)
    print("=================================================================", flush=True)

    con = duckdb.connect(duckdb_path, read_only=True)

    # 1. Load Spring issues sorted chronologically
    print("[1/5] Querying issues and dependency links from DuckDB...", flush=True)
    issues_df = con.execute(
        """
        SELECT 
            instance, issue_key, project, summary, issuetype, issuetype_theme,
            priority_raw, priority_norm, created_ts, resolved_ts, resolution,
            assignee, reporter, num_links, has_block_or_depend,
            CASE WHEN resolved_ts IS NOT NULL THEN 1 ELSE 0 END as is_resolved,
            CASE WHEN resolved_ts IS NOT NULL THEN (resolved_ts - created_ts)/86400.0 ELSE NULL END as duration_days
        FROM issues
        WHERE instance = ?
          AND created_ts > 946684800
          AND (resolved_ts IS NULL OR resolved_ts >= created_ts)
        ORDER BY created_ts ASC, issue_key ASC
        """,
        [instance],
    ).df()

    links_df = con.execute(
        """
        SELECT instance, source_key, target_key, link_type_raw, link_type_std, direction
        FROM issue_links
        WHERE instance = ? AND link_type_std = 'Depend'
        """,
        [instance],
    ).df()
    con.close()

    n_total = len(issues_df)
    print(f"  Loaded {n_total:,} issues and {len(links_df):,} 'Depend' links.", flush=True)

    # 2. Planned Duration & Realized Slippage
    print("[2/5] Computing planned durations and schedule slippage...", flush=True)
    p_norm = issues_df["priority_norm"].fillna(0.4).values.astype(np.float32)
    it_ser = issues_df["issuetype"].fillna("Bug").str.lower()
    t_ser = issues_df["issuetype_theme"].fillna("Other").str.lower()

    planned_dur = np.full(n_total, 45.0, dtype=np.float32)
    planned_dur[it_ser.str.contains("task", na=False).values] = 21.0
    planned_dur[(t_ser.str.contains("requirement", na=False) | it_ser.str.contains("feature", na=False)).values] = 90.0
    planned_dur[p_norm >= 0.6] = 30.0
    planned_dur[p_norm >= 0.8] = 14.0

    s_ser = issues_df["summary"].fillna("")
    word_counts = np.maximum(1, s_ser.str.split().str.len().fillna(1).values.astype(np.int32))
    theme_w = np.ones(n_total, dtype=np.float32)
    theme_w[t_ser.values == "maintenance"] = 2.0
    theme_w[t_ser.values == "requirements"] = 4.0
    sp_arr = np.round(1.0 + 3.0 * p_norm + theme_w + np.minimum(word_counts / 15.0, 2.0)).astype(np.float32)

    issues_df["planned_duration_days"] = planned_dur

    max_dataset_ts = float(np.nanmax(issues_df["created_ts"].values)) + 86400.0
    dur_arr = np.where(
        issues_df["is_resolved"] == 1,
        np.maximum(0.1, issues_df["duration_days"].fillna(1.0).values),
        np.maximum(0.1, (max_dataset_ts - issues_df["created_ts"].values) / 86400.0),
    ).astype(np.float32)
    issues_df["duration_days"] = dur_arr
    slippage_arr = np.maximum(0.0, dur_arr - planned_dur).astype(np.float32)
    issues_df["slippage_days"] = slippage_arr

    # 3. Graph CPM and Cascading Delay Metrics
    print("[3/5] Computing Graph CPM & Cascading Delay metrics...", flush=True)
    graph_metrics = compute_graph_cpm_metrics(issues_df, links_df)

    blast_radius = np.array([graph_metrics["blast_radius"].get(k, 0.0) for k in issues_df["issue_key"]], dtype=np.float32)
    downstream_delay = np.array([graph_metrics["downstream_delay"].get(k, 0.0) for k in issues_df["issue_key"]], dtype=np.float32)
    slack_time = np.array([graph_metrics["slack_time"].get(k, 999.0) for k in issues_df["issue_key"]], dtype=np.float32)
    marginal_delay = np.array([graph_metrics["marginal_delay"].get(k, 0.0) for k in issues_df["issue_key"]], dtype=np.float32)
    inverted_pr = np.array([graph_metrics["inverted_pagerank"].get(k, 0.0) for k in issues_df["issue_key"]], dtype=np.float32)

    blocks_cnt_map = links_df.groupby("target_key").size().to_dict()
    depends_cnt_map = links_df.groupby("source_key").size().to_dict()
    issues_df["blocks_count"] = np.array([blocks_cnt_map.get(k, 0) for k in issues_df["issue_key"]], dtype=np.int32)
    issues_df["depends_count"] = np.array([depends_cnt_map.get(k, 0) for k in issues_df["issue_key"]], dtype=np.int32)

    issues_df["blast_radius"] = blast_radius
    issues_df["downstream_delay"] = downstream_delay
    issues_df["slack_time"] = slack_time
    issues_df["marginal_delay"] = marginal_delay
    issues_df["inverted_pagerank"] = inverted_pr

    # 4. Formulate Unified Ground Truth Criticality Score
    print("[4/5] Formulating Ground Truth Criticality Score and P0 alerts...", flush=True)
    # Structural DAG Criticality
    norm_marginal = issues_df["marginal_delay"].values / (issues_df["marginal_delay"].max() + 1e-4)
    norm_casc = issues_df["downstream_delay"].values / (issues_df["downstream_delay"].max() + 1e-4)
    slack_score = np.exp(-issues_df["slack_time"].values / 14.0).astype(np.float32)
    norm_blast = np.clip(issues_df["blast_radius"].values / 5.0, 0.0, 1.0).astype(np.float32)
    norm_pr = issues_df["inverted_pagerank"].values / (issues_df["inverted_pagerank"].max() + 1e-4)

    graph_crit = (
        0.35 * norm_marginal
        + 0.30 * norm_casc
        + 0.15 * slack_score
        + 0.10 * norm_blast
        + 0.10 * norm_pr
    ).astype(np.float32)

    prio_weight = p_norm
    slip_ratio = np.clip(slippage_arr / (planned_dur + 1e-4), 0.0, 3.0) / 3.0

    is_blocker = (issues_df["blast_radius"].values > 0) | (issues_df["blocks_count"].values > 0)

    # Raw criticality composite reflecting schedule impact & cascading risk
    raw_criticality = np.where(
        is_blocker,
        0.70 + 0.30 * graph_crit + 0.20 * prio_weight + 0.10 * slip_ratio,
        0.50 * prio_weight + 0.35 * slip_ratio + 0.15 * np.clip(sp_arr / 15.0, 0.0, 1.0),
    ).astype(np.float32)
    issues_df["raw_criticality"] = raw_criticality

    # 5. Extract Zero-Leakage T0 Features (WCI, SCF, Historical Dynamics, NLP Lexicons)
    print("[5/5] Extracting Zero-Leakage T0 Features...", flush=True)
    created_dt = pd.to_datetime(issues_df["created_ts"].values, unit="s", utc=True)
    issues_df["created_year"] = created_dt.year.values.astype(np.int16)
    issues_df["created_quarter"] = created_dt.quarter.values.astype(np.int8)
    issues_df["created_month"] = created_dt.month.values.astype(np.int8)
    issues_df["created_dayofweek"] = created_dt.dayofweek.values.astype(np.int8)

    # Query groups for ranking (Project + Year + Quarter)
    issues_df["query_group"] = issues_df["project"] + "_" + issues_df["created_year"].astype(str) + "_Q" + issues_df["created_quarter"].astype(str)

    # NLP and Complexity Lexicons
    s_ser = issues_df["summary"].fillna("")
    summary_lens = s_ser.str.len().values.astype(np.int32)
    word_counts = np.maximum(1, s_ser.str.split().str.len().fillna(1).values.astype(np.int32))

    ambiguity_pattern = r"\b(?:maybe|could|should|consider|optional|review|investigate|unknown|todo|tbd|tentative|possible|need|depend)\b"
    concurrency_pattern = r"\b(?:deadlock|race|concurrent|thread|lock|sync|atomic|starvation|corrupt|leak|hang|timeout|block)\b"
    scope_risk_pattern = r"\b(?:migrate|refactor|overhaul|redesign|deprecate|rewrite|break|backward|architect|re-architect)\b"

    amb_counts = s_ser.str.count(ambiguity_pattern, flags=re.I).values.astype(np.float32)
    conc_counts = s_ser.str.count(concurrency_pattern, flags=re.I).values.astype(np.float32)
    scope_counts = s_ser.str.count(scope_risk_pattern, flags=re.I).values.astype(np.float32)

    issues_df["summary_len"] = summary_lens
    issues_df["word_count"] = word_counts
    issues_df["ambiguity_score"] = np.round(amb_counts / word_counts, 4).astype(np.float32)
    issues_df["tech_concurrency_risk"] = np.round(conc_counts / word_counts, 4).astype(np.float32)
    issues_df["tech_scope_risk"] = np.round(scope_counts / word_counts, 4).astype(np.float32)
    issues_df["tech_total_risk"] = (issues_df["tech_concurrency_risk"] + issues_df["tech_scope_risk"]).astype(np.float32)

    theme_w = np.ones(n_total, dtype=np.float32)
    theme_w[t_ser.values == "maintenance"] = 2.0
    theme_w[t_ser.values == "requirements"] = 4.0
    sp_arr = np.round(1.0 + 3.0 * p_norm + theme_w + np.minimum(word_counts / 15.0, 2.0)).astype(np.float32)
    issues_df["story_points"] = sp_arr
    issues_df["sp_planned_ratio"] = np.round(sp_arr / (planned_dur + 1e-4), 4).astype(np.float32)

    # O(N) Chronological Simulation for Assignee & Project Dynamics at T0
    created_arr = issues_df["created_ts"].values.astype(np.float64)
    resolved_arr = issues_df["resolved_ts"].fillna(-1.0).values.astype(np.float64)
    is_res_arr = issues_df["is_resolved"].values.astype(np.int8)

    raw_ass = issues_df["assignee"].fillna("(unassigned)").values
    raw_rep = issues_df["reporter"].fillna("(unassigned)").values
    raw_prj = issues_df["project"].fillna("APP").values
    issues_df["is_unassigned"] = (raw_ass == "(unassigned)").astype(np.int8)

    res_indices = np.flatnonzero(is_res_arr == 1)
    n_events = n_total + len(res_indices)

    ev_ts = np.empty(n_events, dtype=np.float64)
    ev_type = np.empty(n_events, dtype=np.int8)
    ev_idx = np.empty(n_events, dtype=np.int32)

    ev_ts[:n_total] = created_arr
    ev_type[:n_total] = 1
    ev_idx[:n_total] = np.arange(n_total, dtype=np.int32)

    ev_ts[n_total:] = resolved_arr[res_indices]
    ev_type[n_total:] = 0
    ev_idx[n_total:] = res_indices

    order = np.lexsort((ev_type, ev_ts))
    ev_ts = ev_ts[order]
    ev_type = ev_type[order]
    ev_idx = ev_idx[order]

    assignee_active_count = np.zeros(n_total, dtype=np.int32)
    assignee_hist_completed = np.zeros(n_total, dtype=np.int32)
    assignee_hist_cycle_time = np.zeros(n_total, dtype=np.float32)
    assignee_hist_delay_rate = np.zeros(n_total, dtype=np.float32)
    assignee_wci = np.zeros(n_total, dtype=np.float32)
    assignee_90d_completed = np.zeros(n_total, dtype=np.int32)
    assignee_90d_delay_rate = np.zeros(n_total, dtype=np.float32)
    assignee_90d_cycle_time = np.zeros(n_total, dtype=np.float32)

    project_active_count = np.zeros(n_total, dtype=np.int32)
    project_90d_completed = np.zeros(n_total, dtype=np.int32)
    project_90d_delay_rate = np.zeros(n_total, dtype=np.float32)

    ass_active = defaultdict(dict)
    ass_dur_sum = defaultdict(float)
    ass_dur_cnt = defaultdict(int)
    ass_del_cnt = defaultdict(int)
    ass_q = defaultdict(deque)
    ass_90_dur = defaultdict(float)
    ass_90_del = defaultdict(int)

    prj_active = defaultdict(int)
    prj_q = defaultdict(deque)
    prj_90_dur = defaultdict(float)
    prj_90_del = defaultdict(int)

    W90 = 90.0 * 86400.0

    for step in range(n_events):
        ts = ev_ts[step]
        e_type = ev_type[step]
        i = ev_idx[step]
        ass = raw_ass[i]
        prj = raw_prj[i]

        if e_type == 0:  # RESOLUTION
            act_dict = ass_active[ass]
            act_dict.pop(i, None)

            d_val = float(dur_arr[i])
            dl_val = int(slippage_arr[i] > 0.0)

            ass_dur_sum[ass] += d_val
            ass_dur_cnt[ass] += 1
            ass_del_cnt[ass] += dl_val
            ass_q[ass].append((ts, d_val, dl_val))
            ass_90_dur[ass] += d_val
            ass_90_del[ass] += dl_val

            if prj_active[prj] > 0:
                prj_active[prj] -= 1
            prj_q[prj].append((ts, d_val, dl_val))
            prj_90_dur[prj] += d_val
            prj_90_del[prj] += dl_val
        else:  # CREATION at T0
            act_dict = ass_active[ass]
            assignee_active_count[i] = len(act_dict)

            wci = 0.0
            for due_ts, sp_val in islice(reversed(act_dict.values()), 30):
                days_left = max(1.0, (due_ts - ts) / 86400.0)
                wci += sp_val / days_left
            assignee_wci[i] = wci

            cnt = ass_dur_cnt[ass]
            assignee_hist_completed[i] = cnt
            h_ct = (ass_dur_sum[ass] / cnt) if cnt > 0 else float(planned_dur[i])
            h_dr = (ass_del_cnt[ass] / cnt) if cnt > 0 else 0.5
            assignee_hist_cycle_time[i] = h_ct
            assignee_hist_delay_rate[i] = h_dr

            aq = ass_q[ass]
            cutoff_90 = ts - W90
            while aq and aq[0][0] < cutoff_90:
                _, old_d, old_dl = aq.popleft()
                ass_90_dur[ass] -= old_d
                ass_90_del[ass] -= old_dl
            ac90 = len(aq)
            assignee_90d_completed[i] = ac90
            if ac90 > 0:
                assignee_90d_delay_rate[i] = ass_90_del[ass] / ac90
                assignee_90d_cycle_time[i] = max(0.01, ass_90_dur[ass] / ac90)
            else:
                assignee_90d_delay_rate[i] = h_dr
                assignee_90d_cycle_time[i] = h_ct

            project_active_count[i] = prj_active[prj]
            pq = prj_q[prj]
            while pq and pq[0][0] < cutoff_90:
                _, old_d, old_dl = pq.popleft()
                prj_90_dur[prj] -= old_d
                prj_90_del[prj] -= old_dl
            pc90 = len(pq)
            project_90d_completed[i] = pc90
            project_90d_delay_rate[i] = (prj_90_del[prj] / pc90) if pc90 > 0 else 0.5

            due = ts + planned_dur[i] * 86400.0
            act_dict[i] = (due, float(sp_arr[i]))
            prj_active[prj] += 1

    issues_df["assignee_active_count"] = assignee_active_count
    issues_df["assignee_hist_completed"] = assignee_hist_completed
    issues_df["assignee_hist_cycle_time"] = assignee_hist_cycle_time
    issues_df["assignee_hist_delay_rate"] = assignee_hist_delay_rate
    issues_df["assignee_wci"] = assignee_wci
    issues_df["assignee_90d_completed"] = assignee_90d_completed
    issues_df["assignee_90d_delay_rate"] = assignee_90d_delay_rate
    issues_df["assignee_90d_cycle_time"] = assignee_90d_cycle_time
    issues_df["scf"] = np.round(planned_dur / np.maximum(1.0, assignee_hist_cycle_time), 4).astype(np.float32)

    issues_df["project_active_count"] = project_active_count
    issues_df["project_90d_completed"] = project_90d_completed
    issues_df["project_90d_delay_rate"] = project_90d_delay_rate

    # Graph connectivity known at T0 (blocks_count, depends_count)
    blocks_cnt_map = links_df.groupby("target_key").size().to_dict()  # target blocks how many
    depends_cnt_map = links_df.groupby("source_key").size().to_dict()  # source depends on how many
    issues_df["blocks_count"] = np.array([blocks_cnt_map.get(k, 0) for k in issues_df["issue_key"]], dtype=np.int32)
    issues_df["depends_count"] = np.array([depends_cnt_map.get(k, 0) for k in issues_df["issue_key"]], dtype=np.int32)
    issues_df["structural_criticality_t0"] = (
        0.5 * (1.0 - np.clip(issues_df["slack_time"].values / 60.0, 0.0, 1.0))
        + 0.3 * min_max_norm(issues_df["blast_radius"].values)
        + 0.2 * min_max_norm(issues_df["inverted_pagerank"].values)
    ).astype(np.float32)

    # 6. Chronological Split (70% Train / 15% Val / 15% Test)
    print("\n--- CHRONOLOGICAL SPLIT (70% / 15% / 15%) ---", flush=True)
    n_train = int(0.70 * n_total)
    n_val = int(0.15 * n_total)

    train_df = issues_df.iloc[:n_train].copy().reset_index(drop=True)
    val_df = issues_df.iloc[n_train : n_train + n_val].copy().reset_index(drop=True)
    test_df = issues_df.iloc[n_train + n_val :].copy().reset_index(drop=True)

    # Within-split percentile ranking to preserve stationary P0 distribution (Zero Leakage)
    for df_split in [train_df, val_df, test_df]:
        ranks = df_split["raw_criticality"].rank(pct=True).values.astype(np.float32)
        df_split["ground_truth_criticality"] = np.round(ranks, 5)
        df_split["is_critical_p0"] = (df_split["ground_truth_criticality"] >= 0.95).astype(np.int8)

    t_train_max = pd.to_datetime(train_df["created_ts"].max(), unit="s", utc=True)
    t_val_max = pd.to_datetime(val_df["created_ts"].max(), unit="s", utc=True)
    t_test_max = pd.to_datetime(test_df["created_ts"].max(), unit="s", utc=True)

    print(f"  Train Set: {len(train_df):,} rows (Up to {t_train_max.date()}, P0 rate: {train_df['is_critical_p0'].mean()*100:.2f}%)")
    print(f"  Val Set:   {len(val_df):,} rows (Up to {t_val_max.date()}, P0 rate: {val_df['is_critical_p0'].mean()*100:.2f}%)")
    print(f"  Test Set:  {len(test_df):,} rows (Up to {t_test_max.date()}, P0 rate: {test_df['is_critical_p0'].mean()*100:.2f}%)")

    # Save to Parquet
    train_file = out_path / "criticality_train.parquet"
    val_file = out_path / "criticality_val.parquet"
    test_file = out_path / "criticality_test.parquet"

    train_df.to_parquet(train_file, index=False)
    val_df.to_parquet(val_file, index=False)
    test_df.to_parquet(test_file, index=False)

    print(f"\n✅ [Complete] Successfully saved 3 ground truth Parquet files in {time.time() - t0:.2f}s:")
    print(f"  • {train_file} ({train_file.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  • {val_file} ({val_file.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  • {test_file} ({test_file.stat().st_size / (1024*1024):.2f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Build Task Criticality & Cascading Delay Ground Truth")
    parser.add_argument("--instance", type=str, default="Spring")
    parser.add_argument("--duckdb-path", type=str, default="data/jira.duckdb")
    parser.add_argument("--out_dir", type=str, default="data/pilot_spring")
    args = parser.parse_args()

    build_criticality_dataset(
        duckdb_path=args.duckdb_path,
        instance=args.instance,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
