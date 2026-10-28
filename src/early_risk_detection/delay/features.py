"""Delay-risk features: O(N) chronological workload simulation + a fitted tabular featurizer.

Features are computed AS OF CREATION (T0): priority / issuetype / assignee come from
``features.t0.load_issues_t0`` (first changelog value), link counts only include links known at
T0. Labels keep the business definition on FINAL attributes (``is_delayed`` = duration >
planned duration of the final priority / type), like the criticality ground truth: labels are
targets, never inputs. History features credit a resolved issue's outcome at its resolution
time, which is always before the T0 of every issue that uses it.

``DelayFeaturizer`` holds every fitted state of the tabular feature engine (top-K one-hot
vocabularies, smoothed target / frequency encodings, TF-IDF + SVD) so serving reproduces the
training matrix exactly.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from itertools import islice

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import StratifiedKFold

from ..bundle import ModelBundle
from ..features.t0 import LEXICON, links_known_at_t0

logger = logging.getLogger(__name__)

W90 = 90.0 * 86400.0


def planned_duration(prio: np.ndarray, issuetype: pd.Series, theme: pd.Series) -> np.ndarray:
    """Operational SLA in days (priority / type / theme heuristic of the delay study)."""
    it = issuetype.fillna("Bug").str.lower()
    th = theme.fillna("Other").str.lower()
    planned = np.full(len(prio), 45.0, dtype=np.float32)
    planned[it.str.contains("task", na=False).values] = 21.0
    planned[(th.str.contains("requirement", na=False) | it.str.contains("feature", na=False)).values] = 90.0
    planned[prio >= 0.6] = 30.0
    planned[prio >= 0.8] = 14.0
    return planned


def story_points(prio: np.ndarray, theme: pd.Series, word_counts: np.ndarray) -> np.ndarray:
    th = theme.fillna("Other").str.lower().values
    theme_w = np.ones(len(prio), dtype=np.float32)
    theme_w[th == "maintenance"] = 2.0
    theme_w[th == "requirements"] = 4.0
    return np.round(1.0 + 3.0 * prio + theme_w + np.minimum(word_counts / 15.0, 2.0)).astype(np.float32)


def _link_counts_t0(df: pd.DataFrame, links: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Outward / inward link counts (source side) and Block-or-Depend flag, links known at T0 only."""
    key_to_row = pd.Series(df["row_id"].values, index=df["instance"] + "|" + df["issue_key"])
    created = df["created_ts"].values
    n = len(df)
    out_cnt, in_cnt, bd = np.zeros(n, np.int32), np.zeros(n, np.int32), np.zeros(n, np.int8)
    r = key_to_row.reindex(links["instance"] + "|" + links["source_key"]).values
    ok = ~np.isnan(r)
    r = r[ok].astype(np.int64)
    known = links["link_ts"].values[ok] <= created[r]
    d = links["direction"].values[ok]
    np.add.at(out_cnt, r[known & (d == 1)], 1)
    np.add.at(in_cnt, r[known & (d == 0)], 1)
    is_bd = links["link_type_std"].isin(["Block", "Depend"]).values
    for e in ["source_key", "target_key"]:
        rr = key_to_row.reindex(links["instance"] + "|" + links[e]).values
        m = ~np.isnan(rr) & is_bd
        rr_i = rr[m].astype(np.int64)
        kn = links["link_ts"].values[m] <= created[rr_i]
        bd[rr_i[kn]] = 1
    return out_cnt, in_cnt, bd


def chronological_features(df: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    """Base delay dataset (one row per issue, ``row_id`` order) from ``load_issues_t0`` + ``load_timed_links``.

    Returns T0 features (same column names as the original study) and the label columns
    ``is_resolved, duration_days, lower_bound, upper_bound, is_delayed, resolution``.
    """
    n_total = len(df)
    inst_arr = df["instance"].values
    # --- T0 attributes (features) and FINAL attributes (labels) ---
    p_t0 = df["priority_norm_t0"].fillna(0.4).values.astype(np.float32)
    p_fin = df["priority_norm"].fillna(0.4).values.astype(np.float32)
    type_t0, theme_t0 = df["issuetype_t0"].fillna("Bug"), df["issuetype_theme_t0"].fillna("Other")
    planned_arr = planned_duration(p_t0, type_t0, theme_t0)
    planned_label = planned_duration(p_fin, df["issuetype"], df["issuetype_theme"])

    s_ser = df["summary"].fillna("")
    summary_lens = s_ser.str.len().values.astype(np.int32)
    word_counts = np.maximum(1, s_ser.str.split().str.len().fillna(1).values.astype(np.int32))
    lex = {k: np.round(s_ser.str.count(LEXICON[k], flags=re.I).values.astype(np.float32) / word_counts, 4).astype(np.float32)
           for k in ["ambiguity_score", "tech_concurrency_risk", "tech_scope_risk"]}
    sp_arr = story_points(p_t0, theme_t0, word_counts)
    blocks_cnt, depends_cnt, has_bd = _link_counts_t0(df, links)
    num_links = links_known_at_t0(df, links).astype(np.int32)

    created_arr = df["created_ts"].values.astype(np.float64)
    resolved_arr = df["resolved_ts"].fillna(-1.0).values.astype(np.float64)
    is_res_arr = df["is_resolved"].values.astype(np.int8)
    dur_arr = np.where(is_res_arr == 1, (resolved_arr - created_arr) / 86400.0, -1.0).astype(np.float32)

    raw_ass = df["assignee_t0"].fillna("(unassigned)").values
    raw_rep = df["reporter"].fillna("(unassigned)").values
    raw_prj = df["project"].fillna("APP").values
    is_unass_arr = raw_ass == "(unassigned)"
    ass_keys = [f"{inst_arr[i]}:{raw_ass[i]}" for i in range(n_total)]
    ass_fin = df["assignee"].fillna("(unassigned)").values
    ass_fin_keys = [f"{inst_arr[i]}:{ass_fin[i]}" for i in range(n_total)]
    rep_keys = [f"{inst_arr[i]}:{raw_rep[i]}" for i in range(n_total)]
    prj_keys = [f"{inst_arr[i]}:{raw_prj[i]}" for i in range(n_total)]

    res_indices = np.flatnonzero(is_res_arr == 1)
    ev_ts = np.concatenate([created_arr, resolved_arr[res_indices]])
    ev_type = np.concatenate([np.zeros(n_total, np.int8), np.ones(len(res_indices), np.int8)])
    ev_idx = np.concatenate([np.arange(n_total, dtype=np.int32), res_indices.astype(np.int32)])
    # creations before resolutions at equal ts: an issue closed at its creation instant must not
    # see its own outcome as history (the original study ordered the other way round)
    order = np.lexsort((ev_type, ev_ts))
    ev_ts, ev_type, ev_idx = ev_ts[order], ev_type[order], ev_idx[order]

    cols = {c: np.zeros(n_total, np.float32) for c in [
        "assignee_active_count", "assignee_hist_completed", "assignee_hist_cycle_time", "assignee_hist_delay_rate",
        "assignee_wci", "assignee_90d_completed", "assignee_90d_delay_rate", "assignee_90d_cycle_time",
        "reporter_hist_delay_rate", "reporter_hist_completed", "reporter_90d_completed", "reporter_90d_delay_rate",
        "project_active_count", "project_90d_completed", "project_90d_delay_rate", "project_90d_cycle_time",
        "unassigned_active_count", "unassigned_90d_delay_rate"]}
    ass_active = defaultdict(dict)
    owner_t0: dict[int, str] = {}
    ass_dur_sum, ass_dur_cnt, ass_del_cnt = defaultdict(float), defaultdict(int), defaultdict(int)
    ass_q, ass_90_dur, ass_90_del = defaultdict(deque), defaultdict(float), defaultdict(int)
    rep_cnt, rep_del_cnt, rep_q, rep_90_del = defaultdict(int), defaultdict(int), defaultdict(deque), defaultdict(int)
    prj_active, prj_q, prj_90_dur, prj_90_del = defaultdict(int), defaultdict(deque), defaultdict(float), defaultdict(int)
    unass_active, unass_q, unass_90_del = defaultdict(int), defaultdict(deque), defaultdict(int)

    for step in range(len(ev_ts)):
        ts, i = ev_ts[step], ev_idx[step]
        rep, prj, inst, is_un = rep_keys[i], prj_keys[i], inst_arr[i], is_unass_arr[i]
        if ev_type[step] == 1:  # RESOLUTION: outcome credited to the final assignee, load released by the T0 owner
            ass_active[owner_t0.pop(i)].pop(i, None)
            ass = ass_fin_keys[i]
            d_val = float(dur_arr[i])
            dl_val = 1 if d_val > planned_label[i] else 0
            ass_dur_sum[ass] += d_val; ass_dur_cnt[ass] += 1; ass_del_cnt[ass] += dl_val
            ass_q[ass].append((ts, d_val, dl_val)); ass_90_dur[ass] += d_val; ass_90_del[ass] += dl_val
            rep_cnt[rep] += 1; rep_del_cnt[rep] += dl_val
            rep_q[rep].append((ts, dl_val)); rep_90_del[rep] += dl_val
            if prj_active[prj] > 0:
                prj_active[prj] -= 1
            prj_q[prj].append((ts, d_val, dl_val)); prj_90_dur[prj] += d_val; prj_90_del[prj] += dl_val
            if is_un:
                if unass_active[inst] > 0:
                    unass_active[inst] -= 1
                unass_q[inst].append((ts, dl_val)); unass_90_del[inst] += dl_val
            continue
        ass = ass_keys[i]  # CREATION
        act_dict = ass_active[ass]
        cols["assignee_active_count"][i] = len(act_dict)
        wci = 0.0
        for due_ts, sp_val in islice(reversed(act_dict.values()), 30):
            wci += sp_val / max(1.0, (due_ts - ts) / 86400.0)
        cols["assignee_wci"][i] = wci
        cnt = ass_dur_cnt[ass]
        cols["assignee_hist_completed"][i] = cnt
        h_ct = (ass_dur_sum[ass] / cnt) if cnt > 0 else float(planned_arr[i])
        h_dr = (ass_del_cnt[ass] / cnt) if cnt > 0 else 0.5
        cols["assignee_hist_cycle_time"][i] = h_ct
        cols["assignee_hist_delay_rate"][i] = h_dr
        cutoff_90 = ts - W90
        aq = ass_q[ass]
        while aq and aq[0][0] < cutoff_90:
            _, old_d, old_dl = aq.popleft(); ass_90_dur[ass] -= old_d; ass_90_del[ass] -= old_dl
        ac90 = len(aq)
        cols["assignee_90d_completed"][i] = ac90
        cols["assignee_90d_delay_rate"][i] = ass_90_del[ass] / ac90 if ac90 else h_dr
        cols["assignee_90d_cycle_time"][i] = max(0.01, ass_90_dur[ass] / ac90) if ac90 else h_ct
        rcnt = rep_cnt[rep]
        cols["reporter_hist_completed"][i] = rcnt
        rh_dr = (rep_del_cnt[rep] / rcnt) if rcnt > 0 else 0.5
        cols["reporter_hist_delay_rate"][i] = rh_dr
        rq = rep_q[rep]
        while rq and rq[0][0] < cutoff_90:
            _, old_dl = rq.popleft(); rep_90_del[rep] -= old_dl
        rc90 = len(rq)
        cols["reporter_90d_completed"][i] = rc90
        cols["reporter_90d_delay_rate"][i] = rep_90_del[rep] / rc90 if rc90 else rh_dr
        cols["project_active_count"][i] = prj_active[prj]
        pq = prj_q[prj]
        while pq and pq[0][0] < cutoff_90:
            _, old_d, old_dl = pq.popleft(); prj_90_dur[prj] -= old_d; prj_90_del[prj] -= old_dl
        pc90 = len(pq)
        cols["project_90d_completed"][i] = pc90
        cols["project_90d_delay_rate"][i] = prj_90_del[prj] / pc90 if pc90 else 0.5
        cols["project_90d_cycle_time"][i] = max(0.01, prj_90_dur[prj] / pc90) if pc90 else float(planned_arr[i])
        cols["unassigned_active_count"][i] = unass_active[inst]
        uq = unass_q[inst]
        while uq and uq[0][0] < cutoff_90:
            _, old_dl = uq.popleft(); unass_90_del[inst] -= old_dl
        uc90 = len(uq)
        cols["unassigned_90d_delay_rate"][i] = unass_90_del[inst] / uc90 if uc90 else 0.5
        act_dict[i] = (ts + planned_arr[i] * 86400.0, float(sp_arr[i]))
        owner_t0[i] = ass
        prj_active[prj] += 1
        if is_un:
            unass_active[inst] += 1
        if (step + 1) % 1_000_000 == 0:
            logger.info(f"  [simulation] {step + 1:,}/{len(ev_ts):,} events")

    scf = np.round(planned_arr / np.maximum(1.0, cols["assignee_hist_cycle_time"]), 4).astype(np.float32)
    created_dt = pd.to_datetime(created_arr, unit="s", utc=True)
    max_dataset_ts = float(np.nanmax(created_arr)) + 86400.0
    lower_bound = np.where(is_res_arr == 1, np.maximum(0.01, dur_arr),
                           np.maximum(0.1, (max_dataset_ts - created_arr) / 86400.0)).astype(np.float32)
    upper_bound = np.where(is_res_arr == 1, lower_bound, np.inf).astype(np.float32)
    tech_total = (lex["tech_concurrency_risk"] + lex["tech_scope_risk"]).astype(np.float32)
    out = pd.DataFrame({
        "row_id": df["row_id"].values.astype(np.int32),
        "instance": inst_arr,
        "issue_key": df["issue_key"].values,
        "project": prj_keys,
        "summary": s_ser.str.slice(0, 200).values,
        "issuetype": type_t0.values,
        "issuetype_theme": theme_t0.values,
        "priority_raw": df["priority_raw_t0"].fillna("Major").values,
        "priority_norm": p_t0,
        "created_ts": created_arr,
        "created_year": created_dt.year.values.astype(np.int16),
        "created_month": created_dt.month.values.astype(np.int8),
        "created_dayofweek": created_dt.dayofweek.values.astype(np.int8),
        "planned_duration_days": planned_arr,
        "story_points": sp_arr,
        "sp_planned_ratio": np.round(sp_arr / (planned_arr + 1e-4), 4).astype(np.float32),
        "sp_planned_product": np.round(sp_arr * planned_arr, 2).astype(np.float32),
        "summary_len": summary_lens,
        "word_count": word_counts,
        **lex,
        "tech_total_risk": tech_total,
        "num_links": num_links,
        "has_block_or_depend": has_bd,
        "blocks_count": blocks_cnt,
        "depends_count": depends_cnt,
        "assignee": raw_ass,
        "is_unassigned": is_unass_arr.astype(np.int8),
        **{c: cols[c] for c in ["assignee_active_count", "assignee_hist_completed", "assignee_hist_cycle_time",
                                "assignee_hist_delay_rate", "assignee_90d_completed", "assignee_90d_delay_rate",
                                "assignee_90d_cycle_time", "assignee_wci"]},
        "scf": scf,
        "reporter": raw_rep,
        **{c: cols[c] for c in ["reporter_hist_completed", "reporter_hist_delay_rate", "reporter_90d_completed",
                                "reporter_90d_delay_rate", "project_active_count", "project_90d_completed",
                                "project_90d_delay_rate", "project_90d_cycle_time", "unassigned_active_count",
                                "unassigned_90d_delay_rate"]},
        # ---- labels (FINAL attributes / outcomes) ----
        "planned_duration_label": planned_label,
        "resolution": df["resolution"].fillna("Open").values,
        "is_resolved": is_res_arr,
        "duration_days": dur_arr,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "is_delayed": (lower_bound > planned_label).astype(np.int8),
    })
    return out


# --------------------------------------------------------------------------- text embedding features
class TextRiskFeatures:
    """TruncatedSVD(16) of the 768-d embedding + linear 'semantic delay risk' (both fitted on train)."""

    def __init__(self, components: np.ndarray | None = None, coef: np.ndarray | None = None,
                 intercept: float | None = None):
        self.components, self.coef, self.intercept = components, coef, intercept

    def fit(self, emb: np.ndarray, y: np.ndarray, seed: int = 42) -> TextRiskFeatures:
        from sklearn.linear_model import SGDClassifier

        x = emb.astype(np.float32)
        svd = TruncatedSVD(n_components=16, random_state=seed).fit(x)
        logger.info(f"[text] SVD16 explained variance {svd.explained_variance_ratio_.sum():.4f}")
        clf = SGDClassifier(loss="log_loss", penalty="l2", alpha=1e-3, max_iter=200, random_state=seed).fit(x, y)
        self.components = svd.components_.astype(np.float32)
        self.coef, self.intercept = clf.coef_.ravel().astype(np.float64), float(clf.intercept_[0])
        return self

    def transform(self, emb: np.ndarray, base: pd.DataFrame) -> pd.DataFrame:
        """``base`` supplies ``is_unassigned`` and ``sp_planned_ratio`` for the interaction terms."""
        x = emb.astype(np.float32)
        svd = x @ self.components.T
        risk = (1.0 / (1.0 + np.exp(-(x.astype(np.float64) @ self.coef + self.intercept)))).astype(np.float32)
        out = {f"text_svd_{k}": svd[:, k] for k in range(svd.shape[1])}
        out["semantic_delay_risk"] = risk
        out["semantic_unassigned_risk"] = np.round(risk * base["is_unassigned"].values, 4).astype(np.float32)
        out["semantic_sp_ratio"] = np.round(risk * base["sp_planned_ratio"].values, 4).astype(np.float32)
        return pd.DataFrame(out, index=base.index)

    def save(self, bundle: ModelBundle, name: str = "text_features.npz") -> None:
        bundle.save_arrays(name, components=self.components, coef=self.coef, intercept=np.array([self.intercept]))

    @classmethod
    def load(cls, bundle: ModelBundle, name: str = "text_features.npz") -> TextRiskFeatures:
        a = bundle.load_arrays(name)
        return cls(a["components"], a["coef"], float(a["intercept"][0]))


# --------------------------------------------------------------------------- tabular feature engine
RAW_NUM_COLS = [
    "priority_norm", "planned_duration_days", "story_points", "sp_planned_ratio", "sp_planned_product",
    "assignee_active_count", "assignee_hist_completed", "assignee_hist_cycle_time", "assignee_hist_delay_rate",
    "assignee_90d_completed", "assignee_90d_delay_rate", "assignee_90d_cycle_time", "assignee_wci", "scf",
    "reporter_hist_completed", "reporter_hist_delay_rate", "reporter_90d_completed", "reporter_90d_delay_rate",
    "project_active_count", "project_90d_completed", "project_90d_delay_rate", "project_90d_cycle_time",
    "unassigned_active_count", "unassigned_90d_delay_rate",
    "semantic_delay_risk", "semantic_unassigned_risk", "semantic_sp_ratio",
    "tech_concurrency_risk", "tech_scope_risk", "tech_total_risk",
] + [f"text_svd_{k}" for k in range(16)]
OHE_COLS = ["instance", "project", "issuetype", "issuetype_theme"]
TE_COLS = ["instance", "project", "issuetype", "issuetype_theme", "priority_raw", "assignee", "reporter"]


def row_features(d: pd.DataFrame) -> pd.DataFrame:
    """Stateless per-row features (workload ratios, queue estimates, logs, interactions, graph, text, calendar)."""
    feats: dict[str, np.ndarray] = {}
    f32 = lambda c: d[c].values.astype(np.float32)  # noqa: E731
    ass_act, prj_act, unass_act = f32("assignee_active_count"), f32("project_active_count"), f32("unassigned_active_count")
    ass_h_comp, ass_90_comp = f32("assignee_hist_completed"), f32("assignee_90d_completed")
    prj_90_comp, rep_h_comp, rep_90_comp = f32("project_90d_completed"), f32("reporter_hist_completed"), f32("reporter_90d_completed")
    ass_h_ct, ass_90_ct, prj_90_ct = f32("assignee_hist_cycle_time"), f32("assignee_90d_cycle_time"), f32("project_90d_cycle_time")
    ass_h_dr, ass_90_dr = f32("assignee_hist_delay_rate"), f32("assignee_90d_delay_rate")
    rep_h_dr, rep_90_dr, prj_90_dr = f32("reporter_hist_delay_rate"), f32("reporter_90d_delay_rate"), f32("project_90d_delay_rate")
    planned, sp, wci, scf, p_norm = f32("planned_duration_days"), f32("story_points"), f32("assignee_wci"), f32("scf"), f32("priority_norm")

    # 1. Assignment & workload ratios
    feats["is_unassigned"] = (d["assignee"] == "(unassigned)").values.astype(np.float32)
    feats["is_unassigned_reporter"] = (d["reporter"] == "(unassigned)").values.astype(np.float32)
    feats["assignee_load_ratio"] = ass_act / (prj_act + 1.0)
    feats["active_per_completed"] = ass_act / (ass_h_comp + 1.0)
    feats["active_per_completed_90d"] = ass_act / (ass_90_comp + 1.0)
    feats["project_active_per_completed"] = prj_act / (prj_90_comp + 1.0)
    feats["unassigned_pressure"] = unass_act / (prj_act + 1.0)
    feats["is_assignee_overloaded"] = (ass_act > 10).astype(np.float32)
    feats["is_assignee_fresh"] = (ass_h_comp == 0).astype(np.float32)
    feats["is_assignee_experienced"] = (ass_h_comp >= 30).astype(np.float32)
    # 2. Queue clearing estimates
    feats["queue_clearing_estimate"] = ass_act * ass_90_ct
    feats["queue_clearing_ratio"] = feats["queue_clearing_estimate"] / (planned + 1e-4)
    feats["hist_queue_clearing_estimate"] = ass_act * ass_h_ct
    feats["hist_queue_clearing_ratio"] = feats["hist_queue_clearing_estimate"] / (planned + 1e-4)
    feats["project_queue_clearing_estimate"] = prj_act * prj_90_ct
    feats["project_queue_clearing_ratio"] = feats["project_queue_clearing_estimate"] / (planned + 1e-4)
    # 3. Log transforms
    for name, v in [("log_assignee_active", ass_act), ("log_project_active", prj_act), ("log_unassigned_active", unass_act),
                    ("log_assignee_completed", ass_h_comp), ("log_assignee_90d_completed", ass_90_comp),
                    ("log_reporter_completed", rep_h_comp), ("log_reporter_90d_completed", rep_90_comp),
                    ("log_project_90d_completed", prj_90_comp), ("log_story_points", sp), ("log_planned_duration", planned),
                    ("log_wci", wci), ("log_scf", scf), ("log_cycle_time_90d", ass_90_ct),
                    ("log_project_cycle_time_90d", prj_90_ct)]:
        feats[name] = np.log1p(np.maximum(0.0, v))
    # 4. Non-linear interactions
    feats["wci_x_scf"] = wci * scf
    feats["wci_div_scf"] = wci / (scf + 1e-4)
    feats["sp_x_scf"] = sp * scf
    feats["sp_div_scf"] = sp / (scf + 1e-4)
    feats["sp_x_planned"] = sp * planned
    feats["sp_div_planned"] = sp / (planned + 1e-4)
    feats["wci_x_planned"] = wci * planned
    feats["wci_div_planned"] = wci / (planned + 1e-4)
    feats["wci_x_sp"] = wci * sp
    feats["wci_div_sp"] = wci / (sp + 1e-4)
    feats["pressure_index"] = (sp * wci) / (scf * planned + 1e-4)
    feats["scf_sq"] = scf ** 2
    feats["is_compressed"] = (scf < 1.0).astype(np.float32)
    feats["is_extreme_compressed"] = (scf < 0.5).astype(np.float32)
    feats["is_high_wci"] = (wci > 50.0).astype(np.float32)
    feats["is_low_wci"] = (wci < 10.0).astype(np.float32)
    # 5. Rolling 90-day velocity & momentum
    scf_90d = planned / (ass_90_ct + 1e-4)
    feats["scf_90d"] = scf_90d
    feats["wci_x_scf_90d"] = wci * scf_90d
    feats["pressure_index_90d"] = (sp * wci) / (scf_90d * planned + 1e-4)
    feats["assignee_delay_velocity"] = ass_90_dr - ass_h_dr
    feats["assignee_cycle_velocity"] = ass_90_ct - ass_h_ct
    feats["reporter_delay_velocity"] = rep_90_dr - rep_h_dr
    feats["project_delay_velocity"] = prj_90_dr - ass_h_dr
    feats["project_cycle_vs_assignee"] = prj_90_ct - ass_90_ct
    feats["assignee_vs_project_delay"] = ass_90_dr - prj_90_dr
    feats["rolling_mean_delay"] = (ass_90_dr + rep_90_dr + prj_90_dr) / 3.0
    feats["rolling_max_delay"] = np.maximum(ass_90_dr, np.maximum(rep_90_dr, prj_90_dr))
    feats["rolling_min_delay"] = np.minimum(ass_90_dr, np.minimum(rep_90_dr, prj_90_dr))
    feats["cycle_vs_planned_90d"] = ass_90_ct / (planned + 1e-4)
    feats["cycle_minus_planned_90d"] = ass_90_ct - planned
    feats["proj_cycle_vs_planned_90d"] = prj_90_ct / (planned + 1e-4)
    feats["proj_cycle_minus_planned_90d"] = prj_90_ct - planned
    feats["cycle_vs_planned_hist"] = ass_h_ct / (planned + 1e-4)
    feats["cycle_minus_planned_hist"] = ass_h_ct - planned
    feats["is_cycle_exceed_90d"] = (ass_90_ct > planned).astype(np.float32)
    feats["is_cycle_exceed_hist"] = (ass_h_ct > planned).astype(np.float32)
    feats["mean_hist_delay"] = (ass_h_dr + rep_h_dr) / 2.0
    feats["diff_hist_delay"] = ass_h_dr - rep_h_dr
    feats["prod_hist_delay"] = ass_h_dr * rep_h_dr
    feats["assignee_delay_risk"] = ass_h_dr * feats["log_assignee_completed"]
    feats["reporter_delay_risk"] = rep_h_dr * feats["log_reporter_completed"]
    for col in RAW_NUM_COLS:
        feats[col] = f32(col)
    # 6. Dependency graph (links known at T0)
    blk, dep, nlinks = f32("blocks_count"), f32("depends_count"), f32("num_links")
    feats["total_deps"] = blk + dep
    feats["has_links"] = (nlinks > 0).astype(np.float32)
    feats["has_blocks"] = (blk > 0).astype(np.float32)
    feats["has_depends"] = (dep > 0).astype(np.float32)
    feats["dep_density"] = (blk + 1.0) * (dep + 1.0)
    feats["links_per_sp"] = nlinks / (sp + 1e-4)
    feats["is_isolated"] = (nlinks == 0).astype(np.float32)
    feats["blocks_count"], feats["depends_count"], feats["num_links"] = blk, dep, nlinks
    # 7. Text complexity & ambiguity
    slen, wcnt, amb = f32("summary_len"), np.maximum(1.0, f32("word_count")), f32("ambiguity_score")
    feats["summary_len"], feats["word_count"], feats["ambiguity_score"] = slen, wcnt, amb
    feats["chars_per_word"] = slen / wcnt
    feats["has_ambiguity"] = (amb > 0).astype(np.float32)
    feats["high_ambiguity"] = (amb > 0.1).astype(np.float32)
    feats["ambiguity_words"] = amb * wcnt
    feats["sp_per_word"] = sp / wcnt
    feats["is_long_summary"] = (slen > 80).astype(np.float32)
    feats["is_short_summary"] = (slen < 30).astype(np.float32)
    # 8. Calendar & deadline flags
    c_month, c_dow = f32("created_month"), f32("created_dayofweek")
    feats["is_high_priority"] = (p_norm >= 0.8).astype(np.float32)
    feats["is_low_priority"] = (p_norm <= 0.4).astype(np.float32)
    feats["is_tight_deadline"] = (planned <= 14.0).astype(np.float32)
    feats["is_medium_deadline"] = (planned == 30.0).astype(np.float32)
    feats["is_loose_deadline"] = (planned >= 45.0).astype(np.float32)
    feats["priority_planned_ratio"] = p_norm / (planned + 1e-4)
    feats["priority_sp_ratio"] = p_norm / (sp + 1e-4)
    feats["sin_month"] = np.sin(2.0 * np.pi * c_month / 12.0).astype(np.float32)
    feats["cos_month"] = np.cos(2.0 * np.pi * c_month / 12.0).astype(np.float32)
    feats["sin_dow"] = np.sin(2.0 * np.pi * c_dow / 7.0).astype(np.float32)
    feats["cos_dow"] = np.cos(2.0 * np.pi * c_dow / 7.0).astype(np.float32)
    feats["is_weekend"] = (c_dow >= 5).astype(np.float32)
    return pd.DataFrame(feats, index=d.index)


class DelayFeaturizer:
    """Fitted tabular feature engine (one-hot top-16, smoothed target + log-frequency encodings, TF-IDF + SVD8)."""

    def __init__(self, seed: int = 42, smoothing: float = 20.0, n_splits: int = 5):
        self.seed, self.smoothing, self.n_splits = seed, smoothing, n_splits
        self.ohe: dict[str, list] = {}
        self.global_mean = 0.5
        self.te: dict[str, pd.DataFrame] = {}  # col -> DataFrame(index=value, columns=[smoothed, count])
        self.tfidf: TfidfVectorizer | None = None
        self.tfidf_svd: np.ndarray | None = None
        self.columns: list[str] = []

    # ------------------------------------------------------------------ fit
    def fit_transform(self, train_df: pd.DataFrame, target_col: str = "is_delayed") -> pd.DataFrame:
        """Fit on ``train_df`` and return its matrix (target encodings out-of-fold, as at training time)."""
        base = row_features(train_df)
        self.ohe = {col: train_df[col].value_counts().head(16).index.tolist() for col in OHE_COLS}
        y = train_df[target_col].values.astype(np.int32)
        self.global_mean = float(train_df[target_col].mean())
        skf = StratifiedKFold(n_splits=self.n_splits, shuffle=True, random_state=self.seed)
        folds = list(skf.split(np.zeros(len(train_df)), y))
        te_tr = {}
        for col in TE_COLS:
            tr_s = train_df[col].fillna("UNK").astype(str)
            oof = np.full(len(train_df), self.global_mean, dtype=np.float32)
            for tr_idx, va_idx in folds:
                stats = train_df[target_col].iloc[tr_idx].groupby(tr_s.iloc[tr_idx]).agg(["count", "mean"])
                sm = (stats["count"] * stats["mean"] + self.smoothing * self.global_mean) / (stats["count"] + self.smoothing)
                oof[va_idx] = tr_s.iloc[va_idx].map(sm).fillna(self.global_mean).values.astype(np.float32)
            full = train_df[target_col].groupby(tr_s).agg(["count", "mean"])
            sm_full = (full["count"] * full["mean"] + self.smoothing * self.global_mean) / (full["count"] + self.smoothing)
            self.te[col] = pd.DataFrame({"smoothed": sm_full.astype(np.float64), "count": full["count"].astype(np.int64)})
            te_tr[f"{col}_te"] = oof
            te_tr[f"{col}_log_freq"] = np.log1p(tr_s.map(full["count"]).fillna(0).values.astype(np.float32))
        logger.info("[featurizer] TF-IDF (1,2)-grams x40 + SVD8 ...")
        self.tfidf = TfidfVectorizer(ngram_range=(1, 2), max_features=40, stop_words="english",
                                     sublinear_tf=True, dtype=np.float32)
        summaries = train_df["summary"].fillna("")
        if len(summaries) > 300_000:
            rng = np.random.default_rng(self.seed)
            self.tfidf.fit(summaries.iloc[rng.choice(len(summaries), size=300_000, replace=False)])
        else:
            self.tfidf.fit(summaries)
        mat = self.tfidf.transform(summaries)
        svd = TruncatedSVD(n_components=8, random_state=self.seed)
        svd.fit(mat[:300_000] if mat.shape[0] > 300_000 else mat)
        self.tfidf_svd = svd.components_.astype(np.float32)
        X = pd.concat([base, self._ohe(train_df), pd.DataFrame(te_tr, index=train_df.index),
                       self._tfidf(mat, train_df.index)], axis=1)
        self.columns = list(X.columns)
        return X

    # ------------------------------------------------------------------ transform
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        te = {}
        for col in TE_COLS:
            s = df[col].fillna("UNK").astype(str)
            t = self.te[col]
            te[f"{col}_te"] = s.map(t["smoothed"]).fillna(self.global_mean).values.astype(np.float32)
            te[f"{col}_log_freq"] = np.log1p(s.map(t["count"]).fillna(0).values.astype(np.float32))
        mat = self.tfidf.transform(df["summary"].fillna(""))
        X = pd.concat([row_features(df), self._ohe(df), pd.DataFrame(te, index=df.index), self._tfidf(mat, df.index)], axis=1)
        return X[self.columns]

    def _ohe(self, df: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for col, vals in self.ohe.items():
            for v in vals:
                out[f"ohe_{col}_{str(v).replace(' ', '_').replace(':', '_')[:25]}"] = (df[col] == v).values.astype(np.float32)
        return pd.DataFrame(out, index=df.index)

    def _tfidf(self, mat, index) -> pd.DataFrame:
        names = [f"tfidf_{f.replace(' ', '_')}" for f in self.tfidf.get_feature_names_out()]
        dense = mat.toarray().astype(np.float32)
        out = pd.DataFrame(dense, columns=names, index=index)
        # TruncatedSVD.transform on a sparse matrix == X @ components.T
        svd = np.asarray(mat @ self.tfidf_svd.T, dtype=np.float32)
        for i in range(svd.shape[1]):
            out[f"svd_summary_{i}"] = svd[:, i]
        return out

    # ------------------------------------------------------------------ persistence
    def save(self, bundle: ModelBundle, prefix: str) -> None:
        bundle.save_json(f"{prefix}_featurizer.json", {
            "seed": self.seed, "smoothing": self.smoothing, "global_mean": self.global_mean,
            "ohe": {k: [str(v) for v in vals] for k, vals in self.ohe.items()}, "columns": self.columns})
        te = pd.concat([t.rename_axis("value").reset_index().assign(column=c) for c, t in self.te.items()])
        te.to_parquet(bundle.file(f"{prefix}_target_encoding.parquet"), index=False)
        bundle.save_json(f"{prefix}_tfidf.json", {
            "vocabulary": {k: int(v) for k, v in self.tfidf.vocabulary_.items()},
            "idf": self.tfidf.idf_.tolist()})
        bundle.save_arrays(f"{prefix}_tfidf_svd.npz", components=self.tfidf_svd)

    @classmethod
    def load(cls, bundle: ModelBundle, prefix: str) -> DelayFeaturizer:
        meta = bundle.load_json(f"{prefix}_featurizer.json")
        f = cls(seed=meta["seed"], smoothing=meta["smoothing"])
        f.global_mean, f.ohe, f.columns = meta["global_mean"], meta["ohe"], meta["columns"]
        te = pd.read_parquet(bundle.file(f"{prefix}_target_encoding.parquet"))
        f.te = {c: g.set_index("value")[["smoothed", "count"]] for c, g in te.groupby("column")}
        tf = bundle.load_json(f"{prefix}_tfidf.json")
        f.tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True, dtype=np.float32,
                                  vocabulary=tf["vocabulary"])
        f.tfidf.idf_ = np.asarray(tf["idf"], dtype=np.float32)
        f.tfidf_svd = bundle.load_arrays(f"{prefix}_tfidf_svd.npz")["components"]
        return f


def extract_all_features(train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame,
                         seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Original study API (used by baselines): fit on train, transform val / test."""
    f = DelayFeaturizer(seed=seed)
    return f.fit_transform(train_df), f.transform(val_df), f.transform(test_df)
