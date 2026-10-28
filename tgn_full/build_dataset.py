"""Stage 1 — Full-Jira (2,685,911 issues) Task-Criticality dataset with strictly T0-safe features.

Outputs (data/tgn_full/):
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
  * TruncatedSVD is fitted on train issues only.
Ground truth = Spring-pilot formula (CPM marginal delay, cascading delay, slack, blast radius,
inverted PageRank, priority, slippage) on the Block+Depend DAG of all 16 instances.
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
from numpy.lib.format import open_memmap
from sklearn.decomposition import TruncatedSVD

USER_RE = r"\|author_(?:accountId|name|key)\|([0-9a-f\-]+)\|"
VALID_FILTER = "created_ts > 946684800 AND (resolved_ts IS NULL OR resolved_ts >= created_ts)"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_issues_t0(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Issues in embedding row order, with priority/issuetype/assignee reconstructed at T0."""
    con.execute(f"""
        CREATE TEMP TABLE iss AS
        SELECT (row_number() OVER (ORDER BY created_ts, instance, issue_key) - 1)::INTEGER AS row_id, *
        FROM issues WHERE {VALID_FILTER}
    """)
    # Changelog value IDs -> issue-table values (per instance, majority vote over the last change).
    for field, col in [("priority", "priority_raw"), ("issuetype", "issuetype"), ("assignee", "assignee")]:
        con.execute(f"""
            CREATE TEMP TABLE map_{field} AS
            WITH last AS (
                SELECT instance, issue_key, arg_max(to_value, created_ts) tv
                FROM issue_changelogs WHERE field = '{field}' GROUP BY ALL),
            j AS (
                SELECT l.instance, tv, i.{col} v, count(*) n
                FROM last l JOIN issues i USING (instance, issue_key)
                WHERE tv IS NOT NULL AND i.{col} IS NOT NULL GROUP BY ALL)
            SELECT instance, tv, arg_max(v, n) v FROM j GROUP BY ALL
        """)
        con.execute(f"""
            CREATE TEMP TABLE first_{field} AS
            SELECT instance, issue_key, arg_min(from_value, created_ts) fv
            FROM issue_changelogs WHERE field = '{field}' GROUP BY ALL
        """)
    con.execute("""
        CREATE TEMP TABLE prio_norm AS
        SELECT priority_raw, arg_max(priority_norm, n) pn FROM
          (SELECT priority_raw, priority_norm, count(*) n FROM issues GROUP BY ALL) GROUP BY ALL
    """)
    con.execute("""
        CREATE TEMP TABLE type_theme AS
        SELECT issuetype, arg_max(issuetype_theme, n) th FROM
          (SELECT issuetype, issuetype_theme, count(*) n FROM issues GROUP BY ALL) GROUP BY ALL
    """)
    df = con.execute(f"""
        SELECT i.row_id, i.instance, i.issue_key, i.project, i.summary,
               i.issuetype, i.issuetype_theme, i.priority_norm,
               i.created_ts, i.resolved_ts, i.updated_ts, i.assignee, i.reporter,
               (i.resolved_ts IS NOT NULL)::TINYINT AS is_resolved,
               -- T0 reconstruction
               CASE WHEN fp.issue_key IS NULL THEN i.priority_norm
                    ELSE COALESCE(pn.pn, 0.4) END AS priority_norm_t0,
               CASE WHEN ft.issue_key IS NULL THEN i.issuetype
                    ELSE COALESCE(mt.v, i.issuetype) END AS issuetype_t0,
               CASE WHEN fa.issue_key IS NULL THEN COALESCE(i.assignee, '(unassigned)')
                    WHEN fa.fv IS NULL OR fa.fv = '' THEN '(unassigned)'
                    ELSE COALESCE(ma.v, fa.fv) END AS assignee_t0,
               (fp.issue_key IS NOT NULL)::TINYINT AS prio_changed,
               (ft.issue_key IS NOT NULL)::TINYINT AS type_changed,
               (fa.issue_key IS NOT NULL)::TINYINT AS assignee_changed
        FROM iss i
        LEFT JOIN first_priority fp USING (instance, issue_key)
        LEFT JOIN map_priority mp ON mp.instance = i.instance AND mp.tv = fp.fv
        LEFT JOIN prio_norm pn ON pn.priority_raw = mp.v
        LEFT JOIN first_issuetype ft USING (instance, issue_key)
        LEFT JOIN map_issuetype mt ON mt.instance = i.instance AND mt.tv = ft.fv
        LEFT JOIN first_assignee fa USING (instance, issue_key)
        LEFT JOIN map_assignee ma ON ma.instance = i.instance AND ma.tv = fa.fv
        ORDER BY i.row_id
    """).df()
    theme = dict(con.execute("SELECT issuetype, th FROM type_theme").fetchall())
    df["issuetype_theme_t0"] = df["issuetype_t0"].map(theme).fillna(df["issuetype_theme"]).fillna("Other")
    return df


def load_timed_links(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """All links with a leak-safe (never earlier than reality) timestamp."""
    return con.execute(f"""
        WITH cl AS (
            SELECT instance, issue_key, to_value, min(created_ts) ts
            FROM issue_changelogs WHERE field = 'Link' AND to_value IS NOT NULL GROUP BY ALL),
        ends AS (SELECT instance, issue_key, created_ts, updated_ts FROM issues)
        SELECT l.instance, l.source_key, l.target_key, l.link_type_std,
               greatest(
                   COALESCE(least(c1.ts, c2.ts), c1.ts, c2.ts,
                            greatest(a.updated_ts, b.updated_ts)),
                   a.created_ts, b.created_ts) AS link_ts,
               (c1.ts IS NOT NULL OR c2.ts IS NOT NULL)::TINYINT AS ts_from_changelog
        FROM issue_links l
        JOIN ends a ON a.instance = l.instance AND a.issue_key = l.source_key
        JOIN ends b ON b.instance = l.instance AND b.issue_key = l.target_key
        LEFT JOIN cl c1 ON c1.instance = l.instance AND c1.issue_key = l.source_key AND c1.to_value = l.target_key
        LEFT JOIN cl c2 ON c2.instance = l.instance AND c2.issue_key = l.target_key AND c2.to_value = l.source_key
        ORDER BY l.instance, l.source_key, l.target_key, l.link_type_std, l.link_type_raw
    """).df()


def planned_and_sp(prio: np.ndarray, itype: pd.Series, theme: pd.Series, summary: pd.Series):
    """Pilot heuristics for planned duration and story points."""
    it = itype.fillna("Bug").str.lower()
    th = theme.fillna("Other").str.lower()
    planned = np.full(len(prio), 45.0, dtype=np.float32)
    planned[it.str.contains("task", na=False).values] = 21.0
    planned[(th.str.contains("requirement", na=False) | it.str.contains("feature", na=False)).values] = 90.0
    planned[prio >= 0.6] = 30.0
    planned[prio >= 0.8] = 14.0
    wc = np.maximum(1, summary.fillna("").str.split().str.len().fillna(1).values.astype(np.int32))
    theme_w = np.ones(len(prio), dtype=np.float32)
    theme_w[th.values == "maintenance"] = 2.0
    theme_w[th.values == "requirements"] = 4.0
    sp = np.round(1.0 + 3.0 * prio + theme_w + np.minimum(wc / 15.0, 2.0)).astype(np.float32)
    return planned, sp, wc


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


def chronological_split(df: pd.DataFrame) -> np.ndarray:
    """Identical to prepare_censored_dataset.attach_embeddings_and_split (val 346,172 / test 346,174)."""
    res_pos = np.flatnonzero(df["is_resolved"].values == 1)
    n_tr, n_va = int(0.70 * len(res_pos)), int(0.15 * len(res_pos))
    split = np.full(len(df), "none", dtype=object)
    split[res_pos[:n_tr]] = "train"
    split[res_pos[n_tr:n_tr + n_va]] = "val"
    split[res_pos[n_tr + n_va:]] = "test"
    cutoff = float(df["created_ts"].values[res_pos[n_tr - 1]])
    open_train = (df["is_resolved"].values == 0) & (df["created_ts"].values <= cutoff)
    split[open_train] = "train"
    return split


def t0_dynamics(df: pd.DataFrame, planned_t0: np.ndarray, sp_t0: np.ndarray, dur: np.ndarray) -> pd.DataFrame:
    """O(N) chronological simulation of assignee / reporter / project dynamics strictly before T0.

    Load (active set, WCI) uses the T0 assignee; completed-work history is credited at resolution
    time to the final assignee (known at that moment, which is before every later T0).
    """
    n = len(df)
    inst = df["instance"].values
    ass_t0 = (inst + "|" + df["assignee_t0"].values).astype(object)
    ass_fin = (inst + "|" + df["assignee"].fillna("(unassigned)").values).astype(object)
    rep = (inst + "|" + df["reporter"].fillna("(unknown)").values).astype(object)
    prj = (inst + "|" + df["project"].fillna("APP").values).astype(object)
    created = df["created_ts"].values.astype(np.float64)
    resolved = df["resolved_ts"].fillna(-1).values.astype(np.float64)
    delayed = (dur > planned_t0).astype(np.int8)

    res_idx = np.flatnonzero(df["is_resolved"].values == 1)
    ev_ts = np.concatenate([created, resolved[res_idx]])
    ev_type = np.concatenate([np.zeros(n, np.int8), np.ones(len(res_idx), np.int8)])
    ev_i = np.concatenate([np.arange(n), res_idx])
    # creations before resolutions at equal ts: a resolution at exactly T0 is not "history" yet
    order = np.lexsort((ev_type, ev_ts))

    cols = {c: np.zeros(n, np.float32) for c in [
        "assignee_active_count", "assignee_wci", "assignee_hist_completed", "assignee_hist_cycle_time",
        "assignee_hist_delay_rate", "assignee_90d_completed", "assignee_90d_delay_rate",
        "reporter_hist_created", "reporter_hist_completed", "reporter_hist_delay_rate",
        "project_active_count", "project_90d_completed", "project_90d_delay_rate", "project_90d_cycle_time",
        "project_hist_created"]}
    active = defaultdict(dict)
    a_sum, a_cnt, a_del = defaultdict(float), defaultdict(int), defaultdict(int)
    a_q = defaultdict(deque)
    a_90 = defaultdict(lambda: [0.0, 0])
    r_cre, r_cnt, r_del = defaultdict(int), defaultdict(int), defaultdict(int)
    p_act, p_cre = defaultdict(int), defaultdict(int)
    p_q = defaultdict(deque)
    p_90 = defaultdict(lambda: [0.0, 0])
    W90 = 90 * 86400.0
    owner_t0 = {}

    for step, j in enumerate(order):
        i = ev_i[j]
        ts = ev_ts[j]
        if ev_type[j] == 1:  # resolution of issue i
            active[owner_t0.pop(i)].pop(i, None)
            d, dl = float(dur[i]), int(delayed[i])
            a = ass_fin[i]
            a_sum[a] += d; a_cnt[a] += 1; a_del[a] += dl
            a_q[a].append((ts, d, dl)); s = a_90[a]; s[0] += d; s[1] += dl
            r = rep[i]; r_cnt[r] += 1; r_del[r] += dl
            p = prj[i]
            p_act[p] -= 1
            p_q[p].append((ts, d, dl)); s = p_90[p]; s[0] += d; s[1] += dl
            continue
        a, r, p = ass_t0[i], rep[i], prj[i]
        act = active[a]
        cols["assignee_active_count"][i] = len(act)
        wci = 0.0
        for due, spv in islice(reversed(act.values()), 30):
            wci += spv / max(1.0, (due - ts) / 86400.0)
        cols["assignee_wci"][i] = wci
        c = a_cnt[a]
        cols["assignee_hist_completed"][i] = c
        cols["assignee_hist_cycle_time"][i] = a_sum[a] / c if c else planned_t0[i]
        cols["assignee_hist_delay_rate"][i] = a_del[a] / c if c else 0.5
        q, s = a_q[a], a_90[a]
        while q and q[0][0] < ts - W90:
            _, od, odl = q.popleft(); s[0] -= od; s[1] -= odl
        cols["assignee_90d_completed"][i] = len(q)
        cols["assignee_90d_delay_rate"][i] = s[1] / len(q) if q else cols["assignee_hist_delay_rate"][i]
        cols["reporter_hist_created"][i] = r_cre[r]
        cols["reporter_hist_completed"][i] = r_cnt[r]
        cols["reporter_hist_delay_rate"][i] = r_del[r] / r_cnt[r] if r_cnt[r] else 0.5
        cols["project_active_count"][i] = p_act[p]
        cols["project_hist_created"][i] = p_cre[p]
        q, s = p_q[p], p_90[p]
        while q and q[0][0] < ts - W90:
            _, od, odl = q.popleft(); s[0] -= od; s[1] -= odl
        cols["project_90d_completed"][i] = len(q)
        cols["project_90d_delay_rate"][i] = s[1] / len(q) if q else 0.5
        cols["project_90d_cycle_time"][i] = s[0] / len(q) if q else planned_t0[i]
        act[i] = (ts + planned_t0[i] * 86400.0, float(sp_t0[i]))
        owner_t0[i] = a
        r_cre[r] += 1; p_cre[p] += 1; p_act[p] += 1
        if step % 1_000_000 == 0:
            log(f"    simulation step {step:,}/{len(order):,}")
    out = pd.DataFrame(cols)
    out["scf"] = planned_t0 / np.maximum(1.0, out["assignee_hist_cycle_time"].values)
    return out


def _codes(*cols: np.ndarray) -> np.ndarray:
    return pd.MultiIndex.from_arrays(list(cols)).factorize()[0].astype(np.int64) if len(cols) > 1 \
        else pd.factorize(cols[0])[0].astype(np.int64)


def history_before(ev_code: np.ndarray, ev_ts: np.ndarray, ev_vals: list[np.ndarray],
                   q_code: np.ndarray, q_ts: np.ndarray, window: float | None = None):
    """For each query (group, T0): count and sums of group events with floor(ts) < floor(T0).

    Vectorised with composite int64 keys (group << 32 | second) + searchsorted; strictly-before
    at one-second granularity (events in the same second as T0 are excluded -> conservative).
    """
    ek = (ev_code << 32) | np.floor(ev_ts).astype(np.int64)
    o = np.argsort(ek, kind="stable")
    ek = ek[o]
    csum = [np.concatenate([[0.0], np.cumsum(v[o].astype(np.float64))]) for v in ev_vals]
    hi = np.searchsorted(ek, (q_code << 32) | np.floor(q_ts).astype(np.int64), side="left")
    lo_ts = np.floor(q_ts - window).astype(np.int64) if window else np.zeros(len(q_ts), np.int64)
    lo = np.searchsorted(ek, (q_code << 32) | lo_ts, side="left")
    return hi - lo, [c[hi] - c[lo] for c in csum]


def propensity_features(df: pd.DataFrame, links: pd.DataFrame, planned_t0: np.ndarray, dur: np.ndarray) -> pd.DataFrame:
    """T0-safe 'link culture' and per-segment duration history (only events strictly before T0)."""
    n = len(df)
    created = df["created_ts"].values.astype(np.float64)
    key_to_row = pd.Series(df["row_id"].values, index=df["instance"] + "|" + df["issue_key"])
    dep = links[links["link_type_std"].isin(["Block", "Depend"])]
    s = key_to_row.reindex(dep["instance"] + "|" + dep["source_key"]).values
    t = key_to_row.reindex(dep["instance"] + "|" + dep["target_key"]).values
    ok = ~(np.isnan(s) | np.isnan(t))
    s, t, lt, lts = s[ok].astype(np.int64), t[ok].astype(np.int64), dep["link_type_std"].values[ok], dep["link_ts"].values[ok]
    pre = np.where(lt == "Depend", t, s)
    # time at which an issue first became a prerequisite (= observable blocker event)
    first_pre = pd.Series(lts).groupby(pre).min()
    b_rows, b_ts = first_pre.index.values.astype(np.int64), first_pre.values.astype(np.float64)
    all_l = links.copy()
    ls_ = key_to_row.reindex(all_l["instance"] + "|" + all_l["source_key"]).values
    ok_l = ~np.isnan(ls_)
    l_rows, l_ts = ls_[ok_l].astype(np.int64), all_l["link_ts"].values[ok_l].astype(np.float64)

    inst = df["instance"].values
    groups = {
        "project": _codes(inst, df["project"].fillna("APP").values),
        "reporter": _codes(inst, df["reporter"].fillna("(unknown)").values),
        "assignee": _codes(inst, df["assignee_t0"].values),
        "instance": _codes(inst),
    }
    out = {}
    one = np.ones(n)
    for g, code in groups.items():
        n_cre, _ = history_before(code, created, [], code, created)
        n_blk, _ = history_before(code[b_rows], b_ts, [], code, created)
        out[f"{g}_blockers_before"] = n_blk.astype(np.float32)
        out[f"{g}_blocker_rate_before"] = (n_blk / np.maximum(1, n_cre)).astype(np.float32)
    pc = groups["project"]
    n90, _ = history_before(pc[b_rows], b_ts, [], pc, created, window=90 * 86400.0)
    out["project_blockers_90d"] = n90.astype(np.float32)
    nl90, _ = history_before(pc[l_rows], l_ts, [], pc, created, window=90 * 86400.0)
    out["project_links_90d"] = nl90.astype(np.float32)

    # duration history per (project, priority bucket) and (project, issuetype) from resolutions before T0
    res = np.flatnonzero(df["is_resolved"].values == 1)
    r_ts = df["resolved_ts"].values[res].astype(np.float64)
    sr = np.clip(np.maximum(0, dur - planned_t0) / planned_t0, 0, 3) / 3.0
    longr = (dur > 2.0 * planned_t0).astype(np.float64)
    logd = np.log1p(dur)
    pb = np.digitize(df["priority_t0"].values, [0.35, 0.55, 0.75]).astype(np.int64)
    segs = {"proj_prio": _codes(inst, df["project"].fillna("APP").values, pb),
            "proj_type": _codes(inst, df["project"].fillna("APP").values, df["issuetype_t0"].fillna("?").values),
            "inst_prio": _codes(inst, pb)}
    for g, code in segs.items():
        cnt, (s_sr, s_long, s_logd) = history_before(code[res], r_ts, [sr[res], longr[res], logd[res]], code, created)
        c = np.maximum(1, cnt)
        out[f"{g}_hist_n"] = cnt.astype(np.float32)
        out[f"{g}_hist_slip_ratio"] = np.where(cnt > 0, s_sr / c, np.nan).astype(np.float32)
        out[f"{g}_hist_long_rate"] = np.where(cnt > 0, s_long / c, np.nan).astype(np.float32)
        out[f"{g}_hist_log_dur"] = np.where(cnt > 0, s_logd / c, np.nan).astype(np.float32)
    o = pd.DataFrame(out)
    # back-off: empty segments fall back to the instance x priority history, then global train mean
    for st in ["slip_ratio", "long_rate", "log_dur"]:
        for g in ["proj_prio", "proj_type"]:
            o[f"{g}_hist_{st}"] = o[f"{g}_hist_{st}"].fillna(o[f"inst_prio_hist_{st}"])
        o = o.fillna({c: o[c].mean() for c in o.columns if c.endswith(st)})
    return o


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default="data/jira.duckdb")
    ap.add_argument("--out_dir", default="data/tgn_full")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    con = duckdb.connect(args.duckdb, read_only=True)
    log("[1/7] Loading issues and reconstructing T0 attributes...")
    df = load_issues_t0(con)
    log(f"  {len(df):,} issues | priority changed after T0: {df.prio_changed.mean():.2%} | "
        f"type changed: {df.type_changed.mean():.2%} | assignee changed: {df.assignee_changed.mean():.2%}")
    log("[2/7] Loading links with leak-safe timestamps...")
    links = load_timed_links(con)
    con.close()
    log(f"  {len(links):,} links, {links.ts_from_changelog.mean():.2%} timestamped from Link changelog")
    links.to_parquet(out / "links_timed.parquet", index=False)

    n = len(df)
    # Ground-truth quantities use FINAL attributes (they are labels, not features).
    prio = df["priority_norm"].fillna(0.4).values.astype(np.float32)
    planned, sp, _ = planned_and_sp(prio, df["issuetype"], df["issuetype_theme"], df["summary"])
    max_ts = df.groupby("instance")["created_ts"].transform("max").values + 86400.0
    dur = np.where(df["is_resolved"].values == 1,
                   np.maximum(0.1, (df["resolved_ts"].values - df["created_ts"].values) / 86400.0),
                   np.maximum(0.1, (max_ts - df["created_ts"].values) / 86400.0)).astype(np.float32)
    dur = np.nan_to_num(dur, nan=0.1)
    slip = np.maximum(0.0, dur - planned).astype(np.float32)

    log("[3/7] Graph CPM on the Block+Depend DAG of all 16 instances...")
    G = dependency_dag(df, links)
    m = cpm_metrics(G, dur, planned, slip, n)
    out_deg = np.zeros(n, np.int32)
    for u, d in G.out_degree():
        out_deg[u] = d
    for k, v in m.items():
        df[k] = v
    df["blocks_count_final"] = out_deg

    log("[4/7] Ground-truth criticality score...")
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

    log("[5/7] T0 static features...")
    prio_t0 = df["priority_norm_t0"].fillna(0.4).values.astype(np.float32)
    planned_t0, sp_t0, wc = planned_and_sp(prio_t0, df["issuetype_t0"], df["issuetype_theme_t0"], df["summary"])
    df["priority_t0"], df["planned_t0"], df["story_points_t0"] = prio_t0, planned_t0, sp_t0
    s_ser = df["summary"].fillna("")
    df["summary_len"] = s_ser.str.len().astype(np.float32)
    df["word_count"] = wc.astype(np.float32)
    for name, pat in [
        ("ambiguity_score", r"\b(?:maybe|could|should|consider|optional|review|investigate|unknown|todo|tbd|tentative|possible|need|depend)\b"),
        ("tech_concurrency_risk", r"\b(?:deadlock|race|concurrent|thread|lock|sync|atomic|starvation|corrupt|leak|hang|timeout|block)\b"),
        ("tech_scope_risk", r"\b(?:migrate|refactor|overhaul|redesign|deprecate|rewrite|break|backward|architect|re-architect)\b"),
        ("umbrella_score", r"\b(?:umbrella|epic|tracking|meta|parent|roadmap|plan|support for|implement|upgrade|release)\b"),
    ]:
        df[name] = (s_ser.str.count(pat, flags=re.I).values / wc).astype(np.float32)
    df["is_unassigned_t0"] = (df["assignee_t0"] == "(unassigned)").astype(np.int8)
    df["created_month"] = cdt.dt.month.astype(np.int8)
    df["created_dow"] = cdt.dt.dayofweek.astype(np.int8)
    df["created_hour"] = cdt.dt.hour.astype(np.int8)
    dyn = t0_dynamics(df, planned_t0, sp_t0, dur)
    for c in dyn.columns:
        df[c] = dyn[c].values

    log("[6/7] Link counts known at T0...")
    key_to_row = pd.Series(df["row_id"].values, index=df["instance"] + "|" + df["issue_key"])
    created = df["created_ts"].values
    for col, ends in [("links_t0_any", ["source_key", "target_key"])]:
        cnt = np.zeros(n, np.float32)
        for e in ends:
            r = key_to_row.reindex(links["instance"] + "|" + links[e]).values
            ok = ~np.isnan(r)
            r = r[ok].astype(np.int64)
            known = links["link_ts"].values[ok] <= created[r]
            np.add.at(cnt, r[known], 1)
        df[col] = cnt
    log(f"  issues with >=1 link known at T0: {(df.links_t0_any > 0).mean():.3%} "
        f"(vs {(df.blocks_count_final > 0).mean():.3%} final Block/Depend out-degree)")
    prop = propensity_features(df, links, planned_t0, dur)
    for c in prop.columns:
        df[c] = prop[c].values
    log(f"  added {prop.shape[1]} propensity / segment-history features")

    log("[7/7] TruncatedSVD(16) on Ollama embeddings, fitted on train only...")
    row_to_unique = np.load("data/emb_row_to_unique_all.npy")
    emb = open_memmap("data/emb_unique_all_fp16.npy", mode="r")
    assert len(row_to_unique) == n, (len(row_to_unique), n)
    rng = np.random.default_rng(args.seed)
    train_rows = np.flatnonzero(df["split"].values == "train")
    fit_rows = np.sort(rng.choice(train_rows, size=200_000, replace=False))
    svd = TruncatedSVD(n_components=16, random_state=args.seed).fit(emb[row_to_unique[fit_rows]].astype(np.float32))
    log(f"  explained variance: {svd.explained_variance_ratio_.sum():.4f}")
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
