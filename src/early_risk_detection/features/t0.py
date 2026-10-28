"""T0-safe issue features shared by the delay-risk and criticality models.

Every feature here is computable at an issue's creation time T0 from the Jira DuckDB
(schema of ``early_risk_detection.data.etl``):

* priority / issuetype / assignee are reconstructed AS OF CREATION from the first changelog
  entry of each field (the ``issues`` table stores the final values);
* link counts only include links whose leak-safe timestamp is <= T0
  (see :func:`load_timed_links`);
* history features only use events strictly before T0.

Row order (``row_id``) is ``ORDER BY created_ts, instance, issue_key`` over ``VALID_FILTER``;
the event stream, embedding index and training splits all share it.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from itertools import islice

import duckdb
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

USER_RE = r"\|author_(?:accountId|name|key)\|([0-9a-f\-]+)\|"
VALID_FILTER = "created_ts > 946684800 AND (resolved_ts IS NULL OR resolved_ts >= created_ts)"


def load_issues_t0(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Issues in embedding row order, with priority/issuetype/assignee reconstructed at T0.

    Every arg_max / arg_min carries its own value as tie-breaker: DuckDB picks an arbitrary row
    among ties, which made T0 attributes differ between two runs on the same database.
    """
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
                SELECT instance, issue_key, arg_max(to_value, (created_ts, to_value)) tv
                FROM issue_changelogs WHERE field = '{field}' GROUP BY ALL),
            j AS (
                SELECT l.instance, tv, i.{col} v, count(*) n
                FROM last l JOIN issues i USING (instance, issue_key)
                WHERE tv IS NOT NULL AND i.{col} IS NOT NULL GROUP BY ALL)
            SELECT instance, tv, arg_max(v, (n, v)) v FROM j GROUP BY ALL
        """)
        con.execute(f"""
            CREATE TEMP TABLE first_{field} AS
            SELECT instance, issue_key, arg_min(from_value, (created_ts, from_value)) fv
            FROM issue_changelogs WHERE field = '{field}' GROUP BY ALL
        """)
    con.execute("""
        CREATE TEMP TABLE prio_norm AS
        SELECT priority_raw, arg_max(priority_norm, (n, priority_norm)) pn FROM
          (SELECT priority_raw, priority_norm, count(*) n FROM issues GROUP BY ALL) GROUP BY ALL
    """)
    con.execute("""
        CREATE TEMP TABLE type_theme AS
        SELECT issuetype, arg_max(issuetype_theme, (n, issuetype_theme)) th FROM
          (SELECT issuetype, issuetype_theme, count(*) n FROM issues GROUP BY ALL) GROUP BY ALL
    """)
    df = con.execute("""
        SELECT i.row_id, i.instance, i.issue_key, i.project, i.summary,
               i.issuetype, i.issuetype_theme, i.priority_norm,
               i.created_ts, i.resolved_ts, i.updated_ts, i.assignee, i.reporter,
               i.priority_raw, i.resolution,
               (i.resolved_ts IS NOT NULL)::TINYINT AS is_resolved,
               -- T0 reconstruction
               CASE WHEN fp.issue_key IS NULL THEN i.priority_norm
                    ELSE COALESCE(pn.pn, 0.4) END AS priority_norm_t0,
               CASE WHEN fp.issue_key IS NULL THEN i.priority_raw
                    ELSE COALESCE(mp.v, i.priority_raw) END AS priority_raw_t0,
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
    return con.execute("""
        WITH cl AS (
            SELECT instance, issue_key, to_value, min(created_ts) ts
            FROM issue_changelogs WHERE field = 'Link' AND to_value IS NOT NULL GROUP BY ALL),
        ends AS (SELECT instance, issue_key, created_ts, updated_ts FROM issues)
        SELECT l.instance, l.source_key, l.target_key, l.link_type_std, l.direction,
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
            logger.info(f"    simulation step {step:,}/{len(order):,}")
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


def propensity_features(df: pd.DataFrame, links: pd.DataFrame, planned_t0: np.ndarray, dur: np.ndarray,
                        fit_mask: np.ndarray | None = None,
                        backoff: dict[str, float] | None = None) -> tuple[pd.DataFrame, dict[str, float]]:
    """T0-safe 'link culture' and per-segment duration history (only events strictly before T0).

    Empty segments back off to the instance x priority history, then to a global mean. That mean
    is computed on ``fit_mask`` rows (training) or taken from ``backoff`` (serving); returns
    ``(features, backoff)``.
    """
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
    if backoff is None:
        fit = o if fit_mask is None else o[fit_mask]
        backoff = {}
    for st in ["slip_ratio", "long_rate", "log_dur"]:
        for g in ["proj_prio", "proj_type"]:
            o[f"{g}_hist_{st}"] = o[f"{g}_hist_{st}"].fillna(o[f"inst_prio_hist_{st}"])
        cols = [c for c in o.columns if c.endswith(st)]
        for c in cols:
            if c not in backoff:
                backoff[c] = float(fit[c].fillna(fit[f"inst_prio_hist_{st}"]).mean()) \
                    if not c.startswith("inst_prio") else float(fit[c].mean())
        o = o.fillna({c: backoff[c] for c in cols})
    return o, backoff


LEXICON = {
    "ambiguity_score": r"\b(?:maybe|could|should|consider|optional|review|investigate|unknown|todo|tbd|tentative|possible|need|depend)\b",
    "tech_concurrency_risk": r"\b(?:deadlock|race|concurrent|thread|lock|sync|atomic|starvation|corrupt|leak|hang|timeout|block)\b",
    "tech_scope_risk": r"\b(?:migrate|refactor|overhaul|redesign|deprecate|rewrite|break|backward|architect|re-architect)\b",
    "umbrella_score": r"\b(?:umbrella|epic|tracking|meta|parent|roadmap|plan|support for|implement|upgrade|release)\b",
}


def issue_durations(df: pd.DataFrame) -> np.ndarray:
    """Duration in days; open issues are censored at their instance's last creation + 1 day.

    Only resolved issues' durations enter the T0 features (as history credited at resolution time).
    """
    max_ts = df.groupby("instance")["created_ts"].transform("max").values + 86400.0
    dur = np.where(df["is_resolved"].values == 1,
                   np.maximum(0.1, (df["resolved_ts"].values - df["created_ts"].values) / 86400.0),
                   np.maximum(0.1, (max_ts - df["created_ts"].values) / 86400.0)).astype(np.float32)
    return np.nan_to_num(dur, nan=0.1)


def links_known_at_t0(df: pd.DataFrame, links: pd.DataFrame) -> np.ndarray:
    """Number of links (any type, either end) whose leak-safe timestamp is <= the issue's T0."""
    key_to_row = pd.Series(df["row_id"].values, index=df["instance"] + "|" + df["issue_key"])
    created = df["created_ts"].values
    cnt = np.zeros(len(df), np.float32)
    for e in ["source_key", "target_key"]:
        r = key_to_row.reindex(links["instance"] + "|" + links[e]).values
        ok = ~np.isnan(r)
        r = r[ok].astype(np.int64)
        known = links["link_ts"].values[ok] <= created[r]
        np.add.at(cnt, r[known], 1)
    return cnt


def add_t0_features(df: pd.DataFrame, links: pd.DataFrame, dur: np.ndarray,
                    fit_mask: np.ndarray | None = None,
                    backoff: dict[str, float] | None = None) -> dict[str, float]:
    """Add every T0 static / dynamic / link / propensity column to ``df`` (in place).

    ``df`` comes from :func:`load_issues_t0` (needs ``summary``). Pass ``fit_mask`` when
    training and the returned ``backoff`` when serving.
    """
    prio_t0 = df["priority_norm_t0"].fillna(0.4).values.astype(np.float32)
    planned_t0, sp_t0, wc = planned_and_sp(prio_t0, df["issuetype_t0"], df["issuetype_theme_t0"], df["summary"])
    df["priority_t0"], df["planned_t0"], df["story_points_t0"] = prio_t0, planned_t0, sp_t0
    s_ser = df["summary"].fillna("")
    df["summary_len"] = s_ser.str.len().astype(np.float32)
    df["word_count"] = wc.astype(np.float32)
    for name, pat in LEXICON.items():
        df[name] = (s_ser.str.count(pat, flags=re.I).values / wc).astype(np.float32)
    cdt = pd.to_datetime(df["created_ts"], unit="s", utc=True)
    df["is_unassigned_t0"] = (df["assignee_t0"] == "(unassigned)").astype(np.int8)
    df["created_month"] = cdt.dt.month.astype(np.int8)
    df["created_dow"] = cdt.dt.dayofweek.astype(np.int8)
    df["created_hour"] = cdt.dt.hour.astype(np.int8)
    dyn = t0_dynamics(df, planned_t0, sp_t0, dur)
    for c in dyn.columns:
        df[c] = dyn[c].values
    df["links_t0_any"] = links_known_at_t0(df, links)
    prop, backoff = propensity_features(df, links, planned_t0, dur, fit_mask=fit_mask, backoff=backoff)
    for c in prop.columns:
        df[c] = prop[c].values
    return backoff


def select_issues(df: pd.DataFrame, issue_keys=None, as_of=None, open_only: bool = True) -> np.ndarray:
    """Row positions to score: explicit ``instance|issue_key`` uids, or every issue created before
    ``as_of`` (epoch seconds or ``pd.Timestamp``; default now) and, if ``open_only``, not resolved by then."""
    if issue_keys is not None:
        uid = pd.Index(df["instance"] + "|" + df["issue_key"])
        keys = list(issue_keys)
        pos = uid.get_indexer(keys)
        missing = [k for k, p in zip(keys, pos) if p < 0]
        if missing:
            raise KeyError(f"{len(missing)} issue keys not found, e.g. {missing[:3]}")
        return np.sort(pos)
    t = pd.Timestamp.now(tz="UTC").timestamp() if as_of is None else \
        (as_of.timestamp() if isinstance(as_of, pd.Timestamp) else float(as_of))
    mask = df["created_ts"].values <= t
    if open_only:
        res = df["resolved_ts"].values
        mask &= np.isnan(res) | (res > t)
    return np.flatnonzero(mask)
