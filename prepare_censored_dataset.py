"""Xây dựng tập dữ liệu Toàn cục (Full Jira Database - 2,685,911 issues) tích hợp Right-Censored Data.

Kiến trúc $O(N)$ Sliding-Window Deque & Out-of-Core Memmap:
1. Zero Temporal Data Leakage:
   - Toàn bộ 2,685,911 issues (2,307,818 resolved + 378,093 open) được mô phỏng theo dòng thời gian thực.
   - Sử dụng cấu trúc hàng đợi hai đầu `collections.deque` và `itertools.islice(reversed(...))` giúp giảm độ phức tạp tính toán WCI và Rolling 90-Day Velocity từ O(N^2) xuống O(1) trung bình mỗi sự kiện.
2. Strict Chronological Split (70% Train / 15% Val / 15% Test):
   - Train (Resolved): 1,615,472 issues (70% đầu tiên).
   - Train (Censored): 1,810,895 issues (1,615,472 resolved + 195,423 open issues tạo trước mốc T_cutoff).
   - Validation:       346,173 issues (15% tiếp theo).
   - Out-of-Time Test: 346,173 issues (15% mới nhất).
3. Tích hợp Dense Embeddings 768 chiều từ Ollama (`emb_unique_all_fp16.npy`):
   - Fit `TruncatedSVD(n_components=16)` và `LogisticRegression` (Semantic Delay Risk) độc quyền trên tập Train, biến đổi theo lô (chunked transform) không tốn RAM.
"""
from __future__ import annotations

import argparse
import gc
import os
import re
import time
from collections import defaultdict, deque
from itertools import islice
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from numpy.lib.format import open_memmap
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import SGDClassifier
from sklearn.model_selection import StratifiedKFold


def build_base_chronological_features(
    duckdb_path: str = "data/jira.duckdb",
    instance: str = "ALL",
    out_dir: str = "data",
) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    suffix = "all" if instance.upper() == "ALL" else instance.lower()
    base_cache_file = out_path / f"base_chronological_{suffix}.parquet"

    if base_cache_file.exists():
        print(f"[Phase 1] Found cached chronological features at {base_cache_file}.", flush=True)
        return base_cache_file

    print("=================================================================", flush=True)
    print(f"⚡ PHASE 1: O(N) CHRONOLOGICAL FEATURE ENGINE (INSTANCE={instance})", flush=True)
    print("=================================================================", flush=True)

    t0 = time.time()
    con = duckdb.connect(duckdb_path, read_only=True)

    if instance.upper() == "ALL":
        df = con.execute(
            """
            SELECT 
                instance, issue_key, project, summary, issuetype, issuetype_theme,
                priority_raw, priority_norm, created_ts, resolved_ts, resolution,
                assignee, reporter, num_links, has_block_or_depend,
                CASE WHEN resolved_ts IS NOT NULL THEN 1 ELSE 0 END as is_resolved,
                CASE WHEN resolved_ts IS NOT NULL THEN (resolved_ts - created_ts)/86400.0 ELSE NULL END as duration_days
            FROM issues
            WHERE created_ts > 946684800
              AND (resolved_ts IS NULL OR resolved_ts >= created_ts)
            ORDER BY created_ts ASC, instance ASC, issue_key ASC
            """
        ).df()
        links_df = con.execute(
            """
            SELECT instance, source_key, direction, COUNT(*) as cnt
            FROM issue_links
            GROUP BY instance, source_key, direction
            """
        ).df()
    else:
        df = con.execute(
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
            ORDER BY created_ts ASC, instance ASC, issue_key ASC
            """,
            [instance],
        ).df()
        links_df = con.execute(
            """
            SELECT instance, source_key, direction, COUNT(*) as cnt
            FROM issue_links
            WHERE instance = ?
            GROUP BY instance, source_key, direction
            """,
            [instance],
        ).df()
    con.close()

    n_total = len(df)
    n_res = int(df["is_resolved"].sum())
    n_open = n_total - n_res
    print(f"[DuckDB] Loaded {n_total:,} issues (Resolved: {n_res:,}, Open: {n_open:,}) in {time.time() - t0:.2f}s", flush=True)

    # 1. Ánh xạ Graph Links (blocks_count, depends_count)
    t1 = time.time()
    blocks_df = links_df[links_df["direction"] == 1]
    depends_df = links_df[links_df["direction"] == 0]
    blocks_map = dict(zip(zip(blocks_df["instance"], blocks_df["source_key"]), blocks_df["cnt"]))
    depends_map = dict(zip(zip(depends_df["instance"], depends_df["source_key"]), depends_df["cnt"]))
    del links_df, blocks_df, depends_df

    inst_arr = df["instance"].fillna("UNK").values
    key_arr = df["issue_key"].fillna("UNK").values
    blocks_cnt = np.fromiter((blocks_map.get((inst_arr[i], key_arr[i]), 0) for i in range(n_total)), dtype=np.int32, count=n_total)
    depends_cnt = np.fromiter((depends_map.get((inst_arr[i], key_arr[i]), 0) for i in range(n_total)), dtype=np.int32, count=n_total)
    del blocks_map, depends_map
    print(f"[Graph] Mapped dependency counts in {time.time() - t1:.2f}s", flush=True)

    # 2. Vectorized Planned Duration, Ambiguity & Technical Risk Lexicon
    t2 = time.time()
    p_arr = df["priority_norm"].fillna(0.4).values.astype(np.float32)
    t_ser = df["issuetype_theme"].fillna("Other").str.lower()
    it_ser = df["issuetype"].fillna("Bug").str.lower()

    planned_arr = np.full(n_total, 45.0, dtype=np.float32)
    mask_task = it_ser.str.contains("task", na=False).values
    mask_req = (t_ser.str.contains("requirement", na=False) | it_ser.str.contains("feature", na=False)).values
    planned_arr[mask_task] = 21.0
    planned_arr[mask_req] = 90.0
    planned_arr[p_arr >= 0.6] = 30.0
    planned_arr[p_arr >= 0.8] = 14.0

    s_ser = df["summary"].fillna("")
    summary_lens = s_ser.str.len().values.astype(np.int32)
    word_counts = np.maximum(1, s_ser.str.split().str.len().fillna(1).values.astype(np.int32))

    ambiguity_pattern = r"\b(?:maybe|could|should|consider|optional|review|investigate|unknown|todo|tbd|tentative|possible|need|depend)\b"
    concurrency_pattern = r"\b(?:deadlock|race|concurrent|thread|lock|sync|atomic|starvation|corrupt|leak|hang|timeout|block)\b"
    scope_risk_pattern = r"\b(?:migrate|refactor|overhaul|redesign|deprecate|rewrite|break|backward|architect|re-architect)\b"

    amb_counts = s_ser.str.count(ambiguity_pattern, flags=re.I).values.astype(np.float32)
    conc_counts = s_ser.str.count(concurrency_pattern, flags=re.I).values.astype(np.float32)
    scope_counts = s_ser.str.count(scope_risk_pattern, flags=re.I).values.astype(np.float32)

    amb_score = np.round(amb_counts / word_counts, 4).astype(np.float32)
    tech_conc_risk = np.round(conc_counts / word_counts, 4).astype(np.float32)
    tech_scope_risk = np.round(scope_counts / word_counts, 4).astype(np.float32)
    tech_total_risk = (tech_conc_risk + tech_scope_risk).astype(np.float32)

    theme_w = np.ones(n_total, dtype=np.float32)
    t_vals = t_ser.values
    theme_w[t_vals == "maintenance"] = 2.0
    theme_w[t_vals == "requirements"] = 4.0
    sp_arr = np.round(1.0 + 3.0 * p_arr + theme_w + np.minimum(word_counts / 15.0, 2.0)).astype(np.float32)
    del t_ser, it_ser, s_ser, amb_counts, conc_counts, scope_counts, theme_w
    print(f"[Lexicon & Anchors] Computed vectorized NLP & schedule anchors in {time.time() - t2:.2f}s", flush=True)

    # 3. Chuẩn bị mảng sự kiện thời gian O(N)
    t3 = time.time()
    created_arr = df["created_ts"].values.astype(np.float64)
    resolved_arr = df["resolved_ts"].fillna(-1.0).values.astype(np.float64)
    is_res_arr = df["is_resolved"].values.astype(np.int8)
    dur_arr = df["duration_days"].fillna(-1.0).values.astype(np.float32)

    raw_ass = df["assignee"].fillna("(unassigned)").values
    raw_rep = df["reporter"].fillna("(unassigned)").values
    raw_prj = df["project"].fillna("APP").values
    is_unass_arr = (raw_ass == "(unassigned)")

    # Ghép khóa theo instance để tránh đụng độ tên giữa 16 hệ thống Jira
    ass_keys = [f"{inst_arr[i]}:{raw_ass[i]}" for i in range(n_total)]
    rep_keys = [f"{inst_arr[i]}:{raw_rep[i]}" for i in range(n_total)]
    prj_keys = [f"{inst_arr[i]}:{raw_prj[i]}" for i in range(n_total)]

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
    del order, res_indices
    print(f"[Events] Sorted {n_events:,} chronological events in {time.time() - t3:.2f}s", flush=True)

    # 4. Thực thi mô phỏng dòng thời gian O(N) với Sliding-Window Deque
    t4 = time.time()
    assignee_active_count = np.zeros(n_total, dtype=np.int32)
    assignee_hist_completed = np.zeros(n_total, dtype=np.int32)
    assignee_hist_cycle_time = np.zeros(n_total, dtype=np.float32)
    assignee_hist_delay_rate = np.zeros(n_total, dtype=np.float32)
    assignee_wci = np.zeros(n_total, dtype=np.float32)

    assignee_90d_completed = np.zeros(n_total, dtype=np.int32)
    assignee_90d_delay_rate = np.zeros(n_total, dtype=np.float32)
    assignee_90d_cycle_time = np.zeros(n_total, dtype=np.float32)

    reporter_hist_delay_rate = np.zeros(n_total, dtype=np.float32)
    reporter_hist_completed = np.zeros(n_total, dtype=np.int32)
    reporter_90d_completed = np.zeros(n_total, dtype=np.int32)
    reporter_90d_delay_rate = np.zeros(n_total, dtype=np.float32)

    project_active_count = np.zeros(n_total, dtype=np.int32)
    project_90d_completed = np.zeros(n_total, dtype=np.int32)
    project_90d_delay_rate = np.zeros(n_total, dtype=np.float32)
    project_90d_cycle_time = np.zeros(n_total, dtype=np.float32)

    unassigned_active_count = np.zeros(n_total, dtype=np.int32)
    unassigned_90d_delay_rate = np.zeros(n_total, dtype=np.float32)

    ass_active = defaultdict(dict)
    ass_dur_sum = defaultdict(float)
    ass_dur_cnt = defaultdict(int)
    ass_del_cnt = defaultdict(int)
    ass_q = defaultdict(deque)
    ass_90_dur = defaultdict(float)
    ass_90_del = defaultdict(int)

    rep_cnt = defaultdict(int)
    rep_del_cnt = defaultdict(int)
    rep_q = defaultdict(deque)
    rep_90_del = defaultdict(int)

    prj_active = defaultdict(int)
    prj_q = defaultdict(deque)
    prj_90_dur = defaultdict(float)
    prj_90_del = defaultdict(int)

    unass_active = defaultdict(int)
    unass_q = defaultdict(deque)
    unass_90_del = defaultdict(int)

    W90 = 90.0 * 86400.0

    for step in range(n_events):
        ts = ev_ts[step]
        etype = ev_type[step]
        i = ev_idx[step]

        ass = ass_keys[i]
        rep = rep_keys[i]
        prj = prj_keys[i]
        inst = inst_arr[i]
        is_un = is_unass_arr[i]

        if etype == 0:  # RESOLUTION
            ass_active[ass].pop(i, None)
            d_val = float(dur_arr[i])
            dl_val = 1 if d_val > planned_arr[i] else 0

            ass_dur_sum[ass] += d_val
            ass_dur_cnt[ass] += 1
            ass_del_cnt[ass] += dl_val
            ass_q[ass].append((ts, d_val, dl_val))
            ass_90_dur[ass] += d_val
            ass_90_del[ass] += dl_val

            rep_cnt[rep] += 1
            rep_del_cnt[rep] += dl_val
            rep_q[rep].append((ts, dl_val))
            rep_90_del[rep] += dl_val

            if prj_active[prj] > 0:
                prj_active[prj] -= 1
            prj_q[prj].append((ts, d_val, dl_val))
            prj_90_dur[prj] += d_val
            prj_90_del[prj] += dl_val

            if is_un:
                if unass_active[inst] > 0:
                    unass_active[inst] -= 1
                unass_q[inst].append((ts, dl_val))
                unass_90_del[inst] += dl_val
        else:  # CREATION
            act_dict = ass_active[ass]
            assignee_active_count[i] = len(act_dict)

            # WCI O(1) qua reversed iterator (tối đa 30 task gần nhất)
            wci = 0.0
            for due_ts, sp_val in islice(reversed(act_dict.values()), 30):
                days_left = max(1.0, (due_ts - ts) / 86400.0)
                wci += sp_val / days_left
            assignee_wci[i] = wci

            cnt = ass_dur_cnt[ass]
            assignee_hist_completed[i] = cnt
            h_ct = (ass_dur_sum[ass] / cnt) if cnt > 0 else float(planned_arr[i])
            h_dr = (ass_del_cnt[ass] / cnt) if cnt > 0 else 0.5
            assignee_hist_cycle_time[i] = h_ct
            assignee_hist_delay_rate[i] = h_dr

            # Sliding 90d window cho Assignee
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

            # Sliding 90d window cho Reporter
            rcnt = rep_cnt[rep]
            reporter_hist_completed[i] = rcnt
            rh_dr = (rep_del_cnt[rep] / rcnt) if rcnt > 0 else 0.5
            reporter_hist_delay_rate[i] = rh_dr

            rq = rep_q[rep]
            while rq and rq[0][0] < cutoff_90:
                _, old_dl = rq.popleft()
                rep_90_del[rep] -= old_dl
            rc90 = len(rq)
            reporter_90d_completed[i] = rc90
            reporter_90d_delay_rate[i] = (rep_90_del[rep] / rc90) if rc90 > 0 else rh_dr

            # Sliding 90d window cho Project
            project_active_count[i] = prj_active[prj]
            pq = prj_q[prj]
            while pq and pq[0][0] < cutoff_90:
                _, old_d, old_dl = pq.popleft()
                prj_90_dur[prj] -= old_d
                prj_90_del[prj] -= old_dl
            pc90 = len(pq)
            project_90d_completed[i] = pc90
            if pc90 > 0:
                project_90d_delay_rate[i] = prj_90_del[prj] / pc90
                project_90d_cycle_time[i] = max(0.01, prj_90_dur[prj] / pc90)
            else:
                project_90d_delay_rate[i] = 0.5
                project_90d_cycle_time[i] = float(planned_arr[i])

            # Sliding 90d window cho Unassigned
            unassigned_active_count[i] = unass_active[inst]
            uq = unass_q[inst]
            while uq and uq[0][0] < cutoff_90:
                _, old_dl = uq.popleft()
                unass_90_del[inst] -= old_dl
            uc90 = len(uq)
            unassigned_90d_delay_rate[i] = (unass_90_del[inst] / uc90) if uc90 > 0 else 0.5

            # Đăng ký active issue
            due = ts + planned_arr[i] * 86400.0
            act_dict[i] = (due, float(sp_arr[i]))
            prj_active[prj] += 1
            if is_un:
                unass_active[inst] += 1

        if (step + 1) % 1000000 == 0:
            print(f"  [Sim Progress] Processed {step + 1:,}/{n_events:,} events ({time.time() - t4:.1f}s)...", flush=True)

    print(f"[Simulation] Completed O(N) simulation of {n_events:,} events in {time.time() - t4:.2f}s!", flush=True)
    del ev_ts, ev_type, ev_idx, ass_active, ass_q, rep_q, prj_q, unass_q
    gc.collect()

    scf = np.round(planned_arr / np.maximum(1.0, assignee_hist_cycle_time), 4).astype(np.float32)
    created_dt = pd.to_datetime(created_arr, unit="s", utc=True)

    max_dataset_ts = float(np.nanmax(created_arr)) + 86400.0
    lower_bound = np.where(
        is_res_arr == 1,
        np.maximum(0.01, dur_arr),
        np.maximum(0.1, (max_dataset_ts - created_arr) / 86400.0),
    ).astype(np.float32)
    upper_bound = np.where(is_res_arr == 1, lower_bound, np.inf).astype(np.float32)
    is_delayed = (lower_bound > planned_arr).astype(np.int8)

    base_df = pd.DataFrame({
        "row_id": np.arange(n_total, dtype=np.int32),
        "instance": df["instance"].values,
        "issue_key": df["issue_key"].values,
        "project": prj_keys,
        "summary": df["summary"].fillna("").str.slice(0, 200).values,
        "issuetype": df["issuetype"].fillna("Bug").values,
        "issuetype_theme": df["issuetype_theme"].fillna("Other").values,
        "priority_raw": df["priority_raw"].fillna("Major").values,
        "priority_norm": p_arr,
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
        "ambiguity_score": amb_score,
        "tech_concurrency_risk": tech_conc_risk,
        "tech_scope_risk": tech_scope_risk,
        "tech_total_risk": tech_total_risk,
        "num_links": df["num_links"].fillna(0).values.astype(np.int32),
        "has_block_or_depend": df["has_block_or_depend"].fillna(False).values.astype(np.int8),
        "blocks_count": blocks_cnt,
        "depends_count": depends_cnt,
        "assignee": raw_ass,
        "is_unassigned": is_unass_arr.astype(np.int8),
        "assignee_active_count": assignee_active_count,
        "assignee_hist_completed": assignee_hist_completed,
        "assignee_hist_cycle_time": assignee_hist_cycle_time,
        "assignee_hist_delay_rate": assignee_hist_delay_rate,
        "assignee_90d_completed": assignee_90d_completed,
        "assignee_90d_delay_rate": assignee_90d_delay_rate,
        "assignee_90d_cycle_time": assignee_90d_cycle_time,
        "assignee_wci": assignee_wci,
        "scf": scf,
        "reporter": raw_rep,
        "reporter_hist_completed": reporter_hist_completed,
        "reporter_hist_delay_rate": reporter_hist_delay_rate,
        "reporter_90d_completed": reporter_90d_completed,
        "reporter_90d_delay_rate": reporter_90d_delay_rate,
        "project_active_count": project_active_count,
        "project_90d_completed": project_90d_completed,
        "project_90d_delay_rate": project_90d_delay_rate,
        "project_90d_cycle_time": project_90d_cycle_time,
        "unassigned_active_count": unassigned_active_count,
        "unassigned_90d_delay_rate": unassigned_90d_delay_rate,
        "resolution": df["resolution"].fillna("Open").values,
        "is_resolved": is_res_arr,
        "duration_days": dur_arr,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "is_delayed": is_delayed,
    })

    base_df.to_parquet(base_cache_file, index=False)
    print(f"✅ [Phase 1 Complete] Saved {base_cache_file} ({len(base_df):,} rows) in {time.time() - t0:.2f}s!", flush=True)
    return base_cache_file


def attach_embeddings_and_split(
    base_cache_file: Path,
    instance: str = "ALL",
    out_dir: str = "data",
    seed: int = 42,
) -> None:
    out_path = Path(out_dir)
    suffix = "all" if instance.upper() == "ALL" else instance.lower()
    map_path = out_path / f"emb_row_to_unique_{suffix}.npy"
    memmap_path = out_path / f"emb_unique_{suffix}_fp16.npy"

    if not map_path.exists() or not memmap_path.exists():
        raise FileNotFoundError(
            f"Missing Ollama embeddings files ({memmap_path} or {map_path}). "
            f"Please ensure `python extract_ollama_embeddings.py --instance {instance}` has completed."
        )

    print("=================================================================", flush=True)
    print("🧠 PHASE 2: INTEGRATING OLLAMA EMBEDDINGS, SVD & TEMPORAL SPLIT", flush=True)
    print("=================================================================", flush=True)

    t0 = time.time()
    df = pd.read_parquet(base_cache_file)
    row_to_unique = np.load(map_path)
    emb_mmap = open_memmap(str(memmap_path), mode="r", dtype=np.float16)
    print(f"[Load] Base DF: {len(df):,} rows | Unique Embeddings Memmap: {emb_mmap.shape}", flush=True)

    # 1. Xác định các chỉ số phân tập Strict Chronological Split trên tập Resolved Issues
    res_mask = (df["is_resolved"].values == 1)
    res_positions = np.flatnonzero(res_mask)
    n_res = len(res_positions)
    n_train_res = int(0.70 * n_res)
    n_val_res = int(0.15 * n_res)

    train_res_pos = res_positions[:n_train_res]
    val_res_pos = res_positions[n_train_res : n_train_res + n_val_res]
    test_res_pos = res_positions[n_train_res + n_val_res :]

    train_cutoff_ts = float(df["created_ts"].values[train_res_pos[-1]])
    open_train_pos = np.flatnonzero((df["is_resolved"].values == 0) & (df["created_ts"].values <= train_cutoff_ts))

    print(
        f"[Split] Resolved Train: {len(train_res_pos):,} | Open Censored Train: {len(open_train_pos):,} | "
        f"Val: {len(val_res_pos):,} | Test: {len(test_res_pos):,}",
        flush=True,
    )

    # 2. Fit TruncatedSVD(n_components=16) & Linear Semantic Classifier ĐỘC QUYỀN trên Train Resolved
    rng = np.random.default_rng(seed)
    fit_sample_size = min(200000, len(train_res_pos))
    fit_sample_pos = np.sort(rng.choice(train_res_pos, size=fit_sample_size, replace=False))
    X_emb_fit = emb_mmap[row_to_unique[fit_sample_pos]].astype(np.float32)
    y_fit = df["is_delayed"].values[fit_sample_pos].astype(np.int32)

    print(f"[SVD] Fitting TruncatedSVD(n_components=16) on {fit_sample_size:,} Train embeddings...", flush=True)
    svd = TruncatedSVD(n_components=16, random_state=seed)
    svd.fit(X_emb_fit)
    print(f"[SVD] Explained variance ratio sum: {svd.explained_variance_ratio_.sum():.4f}", flush=True)

    print("[Semantic Risk] Fitting L2-regularized Logistic Classifier on Train embeddings...", flush=True)
    clf = SGDClassifier(loss="log_loss", penalty="l2", alpha=1e-3, max_iter=200, random_state=seed)
    clf.fit(X_emb_fit, y_fit)
    del X_emb_fit, y_fit
    gc.collect()

    # 3. Biến đổi theo lô (Chunked Transform) cho toàn bộ các tập
    active_positions = np.concatenate([train_res_pos, open_train_pos, val_res_pos, test_res_pos])
    active_positions.sort()

    n_active = len(active_positions)
    svd_features = np.empty((n_active, 16), dtype=np.float32)
    sem_risk = np.empty(n_active, dtype=np.float32)

    chunk_size = 100000
    for c_start in range(0, n_active, chunk_size):
        c_end = min(n_active, c_start + chunk_size)
        pos_Batch = active_positions[c_start:c_end]
        u_idx = row_to_unique[pos_Batch]
        batch_emb = emb_mmap[u_idx].astype(np.float32)
        svd_features[c_start:c_end] = svd.transform(batch_emb)
        sem_risk[c_start:c_end] = clf.predict_proba(batch_emb)[:, 1]

    sub_df = df.iloc[active_positions].copy().reset_index(drop=True)
    del df
    gc.collect()

    for k in range(16):
        sub_df[f"text_svd_{k}"] = svd_features[:, k]
    sub_df["semantic_delay_risk"] = sem_risk
    sub_df["semantic_unassigned_risk"] = np.round(sem_risk * sub_df["is_unassigned"].values, 4).astype(np.float32)
    sub_df["semantic_sp_ratio"] = np.round(sem_risk * sub_df["sp_planned_ratio"].values, 4).astype(np.float32)
    del svd_features, sem_risk
    gc.collect()

    # 4. Tách và lưu các tập dữ liệu chuẩn
    is_res_sub = (sub_df["is_resolved"].values == 1)
    res_sub_idx = np.flatnonzero(is_res_sub)

    tr_res_idx = res_sub_idx[:n_train_res]
    va_res_idx = res_sub_idx[n_train_res : n_train_res + n_val_res]
    te_res_idx = res_sub_idx[n_train_res + n_val_res :]
    open_tr_idx = np.flatnonzero(~is_res_sub)

    train_df = sub_df.iloc[tr_res_idx].copy().reset_index(drop=True)
    val_df = sub_df.iloc[va_res_idx].copy().reset_index(drop=True)
    test_df = sub_df.iloc[te_res_idx].copy().reset_index(drop=True)

    # Cập nhật lower_bound cho open_train tại đúng mốc train_cutoff_ts (Zero Temporal Leakage)
    train_cens_idx = np.sort(np.concatenate([tr_res_idx, open_tr_idx]))
    train_cens_df = sub_df.iloc[train_cens_idx].copy().reset_index(drop=True)
    open_mask_tc = (train_cens_df["is_resolved"].values == 0)
    cens_lb = np.maximum(0.1, (train_cutoff_ts - train_cens_df.loc[open_mask_tc, "created_ts"].values) / 86400.0).astype(np.float32)
    train_cens_df.loc[open_mask_tc, "lower_bound"] = cens_lb
    train_cens_df.loc[open_mask_tc, "upper_bound"] = np.inf
    train_cens_df.loc[open_mask_tc, "is_delayed"] = (cens_lb > train_cens_df.loc[open_mask_tc, "planned_duration_days"].values).astype(np.int8)

    train_df.to_parquet(out_path / "train.parquet", index=False)
    val_df.to_parquet(out_path / "val.parquet", index=False)
    test_df.to_parquet(out_path / "test.parquet", index=False)

    train_cens_df.to_parquet(out_path / "train_censored.parquet", index=False)
    val_df.to_parquet(out_path / "val_censored.parquet", index=False)
    test_df.to_parquet(out_path / "test_censored.parquet", index=False)

    print(f"\n✅ [Phase 2 Complete] Saved all Parquet datasets in {time.time() - t0:.2f}s:", flush=True)
    print(f"  • data/train.parquet:          {len(train_df):,} rows (delay_rate={train_df['is_delayed'].mean():.4f})", flush=True)
    print(f"  • data/train_censored.parquet: {len(train_cens_df):,} rows ({len(train_df):,} resolved + {open_mask_tc.sum():,} censored)", flush=True)
    print(f"  • data/val.parquet:            {len(val_df):,} rows (delay_rate={val_df['is_delayed'].mean():.4f})", flush=True)
    print(f"  • data/test.parquet:           {len(test_df):,} rows (delay_rate={test_df['is_delayed'].mean():.4f})", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Build Right-Censored Jira Dataset at Full 2.68M Scale")
    parser.add_argument("--duckdb-path", type=str, default="data/jira.duckdb")
    parser.add_argument("--instance", type=str, default="ALL")
    parser.add_argument("--out-dir", type=str, default="data")
    parser.add_argument("--phase1-only", action="store_true", help="Only run Phase 1 O(N) chronological simulation")
    args = parser.parse_args()

    base_cache_file = build_base_chronological_features(
        duckdb_path=args.duckdb_path,
        instance=args.instance,
        out_dir=args.out_dir,
    )
    if not args.phase1_only:
        attach_embeddings_and_split(
            base_cache_file=base_cache_file,
            instance=args.instance,
            out_dir=args.out_dir,
        )


if __name__ == "__main__":
    main()
