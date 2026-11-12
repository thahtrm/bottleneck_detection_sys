"""Chuẩn bị dữ liệu và phân chia thời gian (Chronological Split) cho bài toán dự đoán nguy cơ trễ hạn Issue.

Đảm bảo:
1. Zero Temporal Data Leakage: Mọi đặc trưng được tính tại mốc created_ts, chỉ dựa trên quá khứ.
2. Phân chia thời gian bất biến: 70% Train, 15% Val, 15% Test.
3. Xuất ra: data/train.parquet, data/val.parquet, data/test.parquet.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


def prepare_datasets(duckdb_path: str = "data/jira.duckdb", instance: str = "JFrog", out_dir: str = "data"):
    print(f"[Dataset Preparation] Connecting to {duckdb_path}...")
    con = duckdb.connect(duckdb_path, read_only=True)

    t0 = time.time()
    df = con.execute(
        """
        SELECT 
            issue_key, project, summary, issuetype, issuetype_theme,
            priority_raw, priority_norm, created_ts, resolved_ts,
            (resolved_ts - created_ts)/86400.0 as duration_days,
            assignee, reporter, num_links, has_block_or_depend
        FROM issues
        WHERE instance = ? AND resolved_ts IS NOT NULL AND resolved_ts >= created_ts
        ORDER BY created_ts ASC
        """,
        [instance],
    ).df()
    print(f"[Dataset Preparation] Loaded {len(df)} resolved issues for {instance} in {time.time()-t0:.2f}s")

    # Links
    links_df = con.execute(
        """
        SELECT source_key, target_key, link_type_std, direction, is_block_or_depend
        FROM issue_links
        WHERE instance = ?
        """,
        [instance],
    ).df()
    con.close()

    blocks_map = links_df[links_df["direction"] == 1].groupby("source_key").size().to_dict()
    depends_map = links_df[links_df["direction"] == 0].groupby("source_key").size().to_dict()

    # Planned Duration allocation at creation
    def get_planned_duration(p: float, t: str, it: str) -> float:
        if p >= 0.8:
            return 14.0
        elif p >= 0.6:
            return 30.0
        elif "requirement" in t or "feature" in it:
            return 90.0
        elif "task" in it:
            return 21.0
        else:
            return 45.0

    p_arr = df["priority_norm"].fillna(0.4).values
    t_arr = df["issuetype_theme"].fillna("Other").str.lower().values
    it_arr = df["issuetype"].fillna("Bug").str.lower().values
    created_arr = df["created_ts"].values
    resolved_arr = df["resolved_ts"].values
    assignee_arr = df["assignee"].fillna("(unassigned)").values
    reporter_arr = df["reporter"].fillna("(unassigned)").values
    proj_arr = df["project"].values
    dur_arr = df["duration_days"].values

    planned_arr = np.array([get_planned_duration(p_arr[i], t_arr[i], it_arr[i]) for i in range(len(df))])
    is_delayed_arr = (dur_arr > planned_arr).astype(int)

    # NLP text complexity & ambiguity
    ambiguity_pattern = re.compile(
        r"\b(maybe|could|should|consider|optional|review|investigate|unknown|todo|tbd|tentative|possible|need|depend)\b",
        re.I,
    )
    summaries = df["summary"].fillna("").tolist()
    summary_lens = np.array([len(s) for s in summaries], dtype=int)
    word_counts = np.array([max(1, len(s.split())) for s in summaries], dtype=int)
    amb_counts = np.array([len(ambiguity_pattern.findall(s)) for s in summaries], dtype=int)
    amb_score = np.round(amb_counts / word_counts, 4)

    # Proxy Story Points
    theme_weights = {"requirements": 4.0, "maintenance": 2.0, "development": 1.0, "other": 1.0}
    theme_w = np.array([theme_weights.get(t, 1.0) for t in t_arr])
    sp_arr = np.round(1.0 + 3.0 * p_arr + theme_w + np.minimum(word_counts / 15.0, 2.0)).astype(float)

    # Chronological simulation for Assignee Workload & History
    events = []
    for i in range(len(df)):
        events.append((created_arr[i], 1, i))
        events.append((resolved_arr[i], 0, i))
    events.sort(key=lambda x: (x[0], x[1]))

    assignee_active = defaultdict(dict)
    assignee_dur_sum = defaultdict(float)
    assignee_dur_cnt = defaultdict(int)
    assignee_del_cnt = defaultdict(int)
    reporter_del_cnt = defaultdict(int)
    reporter_cnt = defaultdict(int)
    project_active = defaultdict(int)

    assignee_active_count = np.zeros(len(df), dtype=int)
    assignee_hist_completed = np.zeros(len(df), dtype=int)
    assignee_hist_cycle_time = np.zeros(len(df), dtype=float)
    assignee_hist_delay_rate = np.zeros(len(df), dtype=float)
    assignee_wci = np.zeros(len(df), dtype=float)
    reporter_hist_delay_rate = np.zeros(len(df), dtype=float)
    reporter_hist_completed = np.zeros(len(df), dtype=int)
    project_active_count = np.zeros(len(df), dtype=int)

    for ts, ev_type, i in events:
        ass = assignee_arr[i]
        rep = reporter_arr[i]
        prj = proj_arr[i]

        if ev_type == 0:  # RESOLUTION
            assignee_active[ass].pop(i, None)
            assignee_dur_sum[ass] += dur_arr[i]
            assignee_dur_cnt[ass] += 1
            assignee_del_cnt[ass] += is_delayed_arr[i]
            reporter_del_cnt[rep] += is_delayed_arr[i]
            reporter_cnt[rep] += 1
            project_active[prj] = max(0, project_active[prj] - 1)
        else:  # CREATION
            act_dict = assignee_active[ass]
            assignee_active_count[i] = len(act_dict)

            # Assignee Workload Congestion Index (WCI)
            wci = 0.0
            items = list(act_dict.values())
            if len(items) > 30:
                items = items[-30:]
            for due_ts, sp in items:
                days_left = max(1.0, (due_ts - ts) / 86400.0)
                wci += sp / days_left
            assignee_wci[i] = round(wci, 4)

            # Historical stats prior to ts
            cnt = assignee_dur_cnt[ass]
            assignee_hist_completed[i] = cnt
            assignee_hist_cycle_time[i] = round((assignee_dur_sum[ass] / cnt) if cnt > 0 else planned_arr[i], 2)
            assignee_hist_delay_rate[i] = round((assignee_del_cnt[ass] / cnt) if cnt > 0 else 0.5, 4)

            r_cnt = reporter_cnt[rep]
            reporter_hist_completed[i] = r_cnt
            reporter_hist_delay_rate[i] = round((reporter_del_cnt[rep] / r_cnt) if r_cnt > 0 else 0.5, 4)

            project_active_count[i] = project_active[prj]

            due = ts + planned_arr[i] * 86400.0
            act_dict[i] = (due, sp_arr[i])
            project_active[prj] += 1

    # Schedule Compression Factor
    scf = np.round(planned_arr / np.maximum(1.0, assignee_hist_cycle_time), 4)

    # Graph dependency counts
    k_list = df["issue_key"].tolist()
    blocks_cnt = np.array([blocks_map.get(k, 0) for k in k_list], dtype=int)
    depends_cnt = np.array([depends_map.get(k, 0) for k in k_list], dtype=int)

    # Date calendar features
    created_dt = pd.to_datetime(df["created_ts"], unit="s", utc=True)

    feat_df = pd.DataFrame({
        "issue_key": df["issue_key"].values,
        "project": df["project"].values,
        "issuetype": df["issuetype"].values,
        "issuetype_theme": df["issuetype_theme"].values,
        "priority_raw": df["priority_raw"].values,
        "priority_norm": p_arr,
        "created_ts": created_arr,
        "created_year": created_dt.dt.year.values,
        "created_month": created_dt.dt.month.values,
        "created_dayofweek": created_dt.dt.dayofweek.values,
        "planned_duration_days": planned_arr,
        "story_points": sp_arr,
        "sp_planned_ratio": np.round(sp_arr / (planned_arr + 1e-4), 4),
        "sp_planned_product": np.round(sp_arr * planned_arr, 2),
        "summary_len": summary_lens,
        "word_count": word_counts,
        "ambiguity_score": amb_score,
        "num_links": df["num_links"].fillna(0).astype(int).values,
        "has_block_or_depend": df["has_block_or_depend"].astype(int).values,
        "blocks_count": blocks_cnt,
        "depends_count": depends_cnt,
        "assignee": assignee_arr,
        "assignee_active_count": assignee_active_count,
        "assignee_hist_completed": assignee_hist_completed,
        "assignee_hist_cycle_time": assignee_hist_cycle_time,
        "assignee_hist_delay_rate": assignee_hist_delay_rate,
        "assignee_wci": assignee_wci,
        "scf": scf,
        "reporter": reporter_arr,
        "reporter_hist_completed": reporter_hist_completed,
        "reporter_hist_delay_rate": reporter_hist_delay_rate,
        "project_active_count": project_active_count,
        "is_delayed": is_delayed_arr,
    })

    # Chronological Split: 70% Train, 15% Val, 15% Test
    n = len(feat_df)
    n_train = int(0.70 * n)
    n_val = int(0.15 * n)

    train_df = feat_df.iloc[:n_train].copy().reset_index(drop=True)
    val_df = feat_df.iloc[n_train : n_train + n_val].copy().reset_index(drop=True)
    test_df = feat_df.iloc[n_train + n_val :].copy().reset_index(drop=True)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_file = out_path / "train.parquet"
    val_file = out_path / "val.parquet"
    test_file = out_path / "test.parquet"

    train_df.to_parquet(train_file, index=False)
    val_df.to_parquet(val_file, index=False)
    test_df.to_parquet(test_file, index=False)

    print(f"[Dataset Preparation] Saved {train_file} ({len(train_df)} rows, delay_rate={train_df['is_delayed'].mean():.4f})")
    print(f"[Dataset Preparation] Saved {val_file} ({len(val_df)} rows, delay_rate={val_df['is_delayed'].mean():.4f})")
    print(f"[Dataset Preparation] Saved {test_file} ({len(test_df)} rows, delay_rate={test_df['is_delayed'].mean():.4f})")
    print("[Dataset Preparation] Completed successfully!")


if __name__ == "__main__":
    prepare_datasets()
