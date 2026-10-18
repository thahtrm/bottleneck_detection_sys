"""TRACK 1: Pipeline Gradient Boosting (XGBoost Binary) Chuyên Sâu cho Toàn bộ Kho dữ liệu Jira (2.68M Issues).

Chức năng:
1. Feature Engineering Tập trung (Centralized Feature Engine - float32 tối ưu bộ nhớ):
   - Động lực học tải làm việc Kỹ sư & Dự án: WCI, SCF, Rolling 90d Velocity, Queue Clearing, Unassigned Pressure.
   - Đặc trưng Ngữ nghĩa Sâu: 16 thành phần SVD từ 768d Ollama Dense Embeddings (`nomic-embed-text`), Out-of-fold Semantic Risk, 40 từ khóa TF-IDF n-grams (1, 2), và Lexicon Rủi ro Kỹ thuật (`tech_concurrency_risk`, `tech_scope_risk`, `ambiguity_score`).
   - Cấu trúc Đồ thị Phụ thuộc: `blocks_count`, `depends_count`, `num_links`, `dep_density`.
   - Mốc lịch & Hạn mức cam kết: `planned_duration_days`, `story_points`, `sp_planned_ratio`, `is_unassigned`.
   - Mã hóa Top-K One-Hot kết hợp Out-of-Fold Smoothed Target Encoding & Frequency Encoding chống bùng nổ chiều trên >1,200 projects.
2. Tối ưu hóa siêu tham số Bayesian bằng Optuna (35 trials) với TimeSeriesSplit.
3. Huấn luyện 5-Fold Stratified Ensemble trên toàn bộ tập Train (`data/train.parquet`).
4. Xuất `predictions_val.csv`, `predictions_test.csv`, `shap_summary.json` và cập nhật `experiments/leaderboard.json`.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import time
from pathlib import Path
from typing import Tuple

import numpy as np
import optuna
import pandas as pd
import shap
import xgboost as xgb
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit

from evaluation_harness import evaluate_predictions

optuna.logging.set_verbosity(optuna.logging.WARNING)


def compute_target_and_freq_encoding(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    cat_cols: list[str],
    target_col: str = "is_delayed",
    n_splits: int = 5,
    smoothing: float = 20.0,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Tính toán Target Encoding mượt hóa Out-of-fold (Laplace smoothing) và Log-Frequency Encoding."""
    global_mean = float(train_df[target_col].mean())
    te_train_dict: dict[str, np.ndarray] = {}
    te_val_dict: dict[str, np.ndarray] = {}
    te_test_dict: dict[str, np.ndarray] = {}

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    y_tr_vals = train_df[target_col].values.astype(np.int32)

    for col in cat_cols:
        if col not in train_df.columns:
            continue

        tr_s = train_df[col].fillna("UNK").astype(str)
        va_s = val_df[col].fillna("UNK").astype(str)
        te_s = test_df[col].fillna("UNK").astype(str)

        # 1. Out-of-fold Target Encoding cho Train
        oof_arr = np.full(len(train_df), global_mean, dtype=np.float32)
        for tr_idx, val_idx in skf.split(np.zeros(len(train_df)), y_tr_vals):
            fold_col = tr_s.iloc[tr_idx]
            fold_y = train_df[target_col].iloc[tr_idx]
            stats = fold_y.groupby(fold_col).agg(["count", "mean"])
            smoothed = (stats["count"] * stats["mean"] + smoothing * global_mean) / (stats["count"] + smoothing)
            oof_arr[val_idx] = tr_s.iloc[val_idx].map(smoothed).fillna(global_mean).values.astype(np.float32)
        te_train_dict[f"{col}_te"] = oof_arr

        # 2. Full Train mapping sang Val và Test
        stats_full = train_df[target_col].groupby(tr_s).agg(["count", "mean"])
        smoothed_full = (stats_full["count"] * stats_full["mean"] + smoothing * global_mean) / (stats_full["count"] + smoothing)
        te_val_dict[f"{col}_te"] = va_s.map(smoothed_full).fillna(global_mean).values.astype(np.float32)
        te_test_dict[f"{col}_te"] = te_s.map(smoothed_full).fillna(global_mean).values.astype(np.float32)

        # 3. Log-Frequency Encoding
        counts = stats_full["count"]
        te_train_dict[f"{col}_log_freq"] = np.log1p(tr_s.map(counts).fillna(0).values.astype(np.float32))
        te_val_dict[f"{col}_log_freq"] = np.log1p(va_s.map(counts).fillna(0).values.astype(np.float32))
        te_test_dict[f"{col}_log_freq"] = np.log1p(te_s.map(counts).fillna(0).values.astype(np.float32))

    return (
        pd.DataFrame(te_train_dict, index=train_df.index),
        pd.DataFrame(te_val_dict, index=val_df.index),
        pd.DataFrame(te_test_dict, index=test_df.index),
    )


def extract_all_features(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Khai phá và kỹ thuật hóa toàn diện các đặc trưng tabular, NLP (Ollama 16-SVD + TF-IDF), rolling velocity và tương tác phi tuyến dưới dạng float32."""
    t0 = time.time()
    cache_dir = Path(f"data/cache_features_{len(train_df)}_{len(val_df)}_{len(test_df)}")
    if (cache_dir / "X_train.parquet").exists() and (cache_dir / "X_val.parquet").exists() and (cache_dir / "X_test.parquet").exists():
        print(f"[Feature Engineering] Loading cached float32 feature matrices from {cache_dir}...", flush=True)
        p_train = pd.read_parquet(cache_dir / "X_train.parquet")
        p_val = pd.read_parquet(cache_dir / "X_val.parquet")
        p_test = pd.read_parquet(cache_dir / "X_test.parquet")
        print(f"[Feature Engineering] Loaded {p_train.shape[1]} cached features in {time.time() - t0:.2f}s.", flush=True)
        return p_train, p_val, p_test
    print(f"[Feature Engineering] Extracting features for Train ({len(train_df):,}), Val ({len(val_df):,}), Test ({len(test_df):,})...", flush=True)
    dfs = [train_df, val_df, test_df]
    processed_dfs = []

    for d in dfs:
        feats: dict[str, np.ndarray] = {}

        ass_act = d["assignee_active_count"].values.astype(np.float32)
        prj_act = d["project_active_count"].values.astype(np.float32)
        unass_act = d["unassigned_active_count"].values.astype(np.float32) if "unassigned_active_count" in d.columns else np.zeros(len(d), dtype=np.float32)
        ass_h_comp = d["assignee_hist_completed"].values.astype(np.float32)
        ass_90_comp = d["assignee_90d_completed"].values.astype(np.float32) if "assignee_90d_completed" in d.columns else ass_h_comp
        prj_90_comp = d["project_90d_completed"].values.astype(np.float32) if "project_90d_completed" in d.columns else prj_act
        rep_h_comp = d["reporter_hist_completed"].values.astype(np.float32)
        rep_90_comp = d["reporter_90d_completed"].values.astype(np.float32) if "reporter_90d_completed" in d.columns else rep_h_comp

        ass_h_ct = d["assignee_hist_cycle_time"].values.astype(np.float32)
        ass_90_ct = d["assignee_90d_cycle_time"].values.astype(np.float32) if "assignee_90d_cycle_time" in d.columns else ass_h_ct
        prj_90_ct = d["project_90d_cycle_time"].values.astype(np.float32) if "project_90d_cycle_time" in d.columns else ass_h_ct

        ass_h_dr = d["assignee_hist_delay_rate"].values.astype(np.float32)
        ass_90_dr = d["assignee_90d_delay_rate"].values.astype(np.float32) if "assignee_90d_delay_rate" in d.columns else ass_h_dr
        rep_h_dr = d["reporter_hist_delay_rate"].values.astype(np.float32)
        rep_90_dr = d["reporter_90d_delay_rate"].values.astype(np.float32) if "reporter_90d_delay_rate" in d.columns else rep_h_dr
        prj_90_dr = d["project_90d_delay_rate"].values.astype(np.float32) if "project_90d_delay_rate" in d.columns else ass_h_dr

        planned = d["planned_duration_days"].values.astype(np.float32)
        sp = d["story_points"].values.astype(np.float32)
        wci = d["assignee_wci"].values.astype(np.float32)
        scf = d["scf"].values.astype(np.float32)
        p_norm = d["priority_norm"].values.astype(np.float32)

        # 1. Assignment & Workload Ratios
        is_unass = (d["assignee"] == "(unassigned)").values.astype(np.float32)
        feats["is_unassigned"] = is_unass
        feats["is_unassigned_reporter"] = (d["reporter"] == "(unassigned)").values.astype(np.float32)
        feats["assignee_load_ratio"] = ass_act / (prj_act + 1.0)
        feats["active_per_completed"] = ass_act / (ass_h_comp + 1.0)
        feats["active_per_completed_90d"] = ass_act / (ass_90_comp + 1.0)
        feats["project_active_per_completed"] = prj_act / (prj_90_comp + 1.0)
        feats["unassigned_pressure"] = unass_act / (prj_act + 1.0)
        feats["is_assignee_overloaded"] = (ass_act > 10).astype(np.float32)
        feats["is_assignee_fresh"] = (ass_h_comp == 0).astype(np.float32)
        feats["is_assignee_experienced"] = (ass_h_comp >= 30).astype(np.float32)

        # 2. Queue Clearing Estimates
        feats["queue_clearing_estimate"] = ass_act * ass_90_ct
        feats["queue_clearing_ratio"] = feats["queue_clearing_estimate"] / (planned + 1e-4)
        feats["hist_queue_clearing_estimate"] = ass_act * ass_h_ct
        feats["hist_queue_clearing_ratio"] = feats["hist_queue_clearing_estimate"] / (planned + 1e-4)
        feats["project_queue_clearing_estimate"] = prj_act * prj_90_ct
        feats["project_queue_clearing_ratio"] = feats["project_queue_clearing_estimate"] / (planned + 1e-4)

        # 3. Chuyển đổi Log (Log1p)
        feats["log_assignee_active"] = np.log1p(np.maximum(0.0, ass_act))
        feats["log_project_active"] = np.log1p(np.maximum(0.0, prj_act))
        feats["log_unassigned_active"] = np.log1p(np.maximum(0.0, unass_act))
        feats["log_assignee_completed"] = np.log1p(np.maximum(0.0, ass_h_comp))
        feats["log_assignee_90d_completed"] = np.log1p(np.maximum(0.0, ass_90_comp))
        feats["log_reporter_completed"] = np.log1p(np.maximum(0.0, rep_h_comp))
        feats["log_reporter_90d_completed"] = np.log1p(np.maximum(0.0, rep_90_comp))
        feats["log_project_90d_completed"] = np.log1p(np.maximum(0.0, prj_90_comp))
        feats["log_story_points"] = np.log1p(np.maximum(0.0, sp))
        feats["log_planned_duration"] = np.log1p(np.maximum(0.0, planned))
        feats["log_wci"] = np.log1p(np.maximum(0.0, wci))
        feats["log_scf"] = np.log1p(np.maximum(0.0, scf))
        feats["log_cycle_time_90d"] = np.log1p(np.maximum(0.0, ass_90_ct))
        feats["log_project_cycle_time_90d"] = np.log1p(np.maximum(0.0, prj_90_ct))

        # 4. Tương tác Phi Tuyến: WCI x SCF, Pressure Index
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

        # 5. Động lực học 90 ngày (Rolling 90-day Velocity & Momentum)
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

        # Các trường số gốc + Tier 1 Dense Embedding SVD (16 chiều) & Rủi ro kỹ thuật
        raw_num_cols = [
            "priority_norm", "planned_duration_days", "story_points", "sp_planned_ratio", "sp_planned_product",
            "assignee_active_count", "assignee_hist_completed", "assignee_hist_cycle_time", "assignee_hist_delay_rate",
            "assignee_90d_completed", "assignee_90d_delay_rate", "assignee_90d_cycle_time", "assignee_wci", "scf",
            "reporter_hist_completed", "reporter_hist_delay_rate", "reporter_90d_completed", "reporter_90d_delay_rate",
            "project_active_count", "project_90d_completed", "project_90d_delay_rate", "project_90d_cycle_time",
            "unassigned_active_count", "unassigned_90d_delay_rate",
            "semantic_delay_risk", "semantic_unassigned_risk", "semantic_sp_ratio",
            "tech_concurrency_risk", "tech_scope_risk", "tech_total_risk",
        ] + [f"text_svd_{k}" for k in range(16)]

        for col in raw_num_cols:
            if col in d.columns:
                feats[col] = d[col].values.astype(np.float32)

        # 6. Graph Dependency Network
        blk = d["blocks_count"].values.astype(np.float32)
        dep = d["depends_count"].values.astype(np.float32)
        nlinks = d["num_links"].values.astype(np.float32)
        feats["total_deps"] = blk + dep
        feats["has_links"] = (nlinks > 0).astype(np.float32)
        feats["has_blocks"] = (blk > 0).astype(np.float32)
        feats["has_depends"] = (dep > 0).astype(np.float32)
        feats["dep_density"] = (blk + 1.0) * (dep + 1.0)
        feats["links_per_sp"] = nlinks / (sp + 1e-4)
        feats["is_isolated"] = (nlinks == 0).astype(np.float32)
        feats["blocks_count"] = blk
        feats["depends_count"] = dep
        feats["num_links"] = nlinks

        # 7. Text Complexity & Ambiguity
        slen = d["summary_len"].values.astype(np.float32)
        wcnt = np.maximum(1.0, d["word_count"].values.astype(np.float32))
        amb = d["ambiguity_score"].values.astype(np.float32)
        feats["summary_len"] = slen
        feats["word_count"] = wcnt
        feats["ambiguity_score"] = amb
        feats["chars_per_word"] = slen / wcnt
        feats["has_ambiguity"] = (amb > 0).astype(np.float32)
        feats["high_ambiguity"] = (amb > 0.1).astype(np.float32)
        feats["ambiguity_words"] = amb * wcnt
        feats["sp_per_word"] = sp / wcnt
        feats["is_long_summary"] = (slen > 80).astype(np.float32)
        feats["is_short_summary"] = (slen < 30).astype(np.float32)

        # 8. Calendar & Deadline Flags
        c_month = d["created_month"].values.astype(np.float32)
        c_dow = d["created_dayofweek"].values.astype(np.float32)
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

        processed_dfs.append(pd.DataFrame(feats, index=d.index))

    p_train, p_val, p_test = processed_dfs

    # 9. Bounded Top-K One-Hot Encoding (chống bùng nổ RAM khi có >1,200 projects)
    cat_cols = [c for c in ["instance", "project", "issuetype", "issuetype_theme"] if c in train_df.columns]
    ohe_tr_dict, ohe_va_dict, ohe_te_dict = {}, {}, {}
    for col in cat_cols:
        top_vals = train_df[col].value_counts().head(16).index.tolist()
        for v in top_vals:
            clean_v = str(v).replace(" ", "_").replace(":", "_")[:25]
            col_name = f"ohe_{col}_{clean_v}"
            ohe_tr_dict[col_name] = (train_df[col] == v).values.astype(np.float32)
            ohe_va_dict[col_name] = (val_df[col] == v).values.astype(np.float32)
            ohe_te_dict[col_name] = (test_df[col] == v).values.astype(np.float32)

    p_train = pd.concat([p_train, pd.DataFrame(ohe_tr_dict, index=train_df.index)], axis=1)
    p_val = pd.concat([p_val, pd.DataFrame(ohe_va_dict, index=val_df.index)], axis=1)
    p_test = pd.concat([p_test, pd.DataFrame(ohe_te_dict, index=test_df.index)], axis=1)

    # 10. Out-of-fold Smoothed Target Encoding & Log-Frequency Encoding
    te_cols = [c for c in ["instance", "project", "issuetype", "issuetype_theme", "priority_raw", "assignee", "reporter"] if c in train_df.columns]
    te_train, te_val, te_test = compute_target_and_freq_encoding(
        train_df, val_df, test_df,
        cat_cols=te_cols,
        target_col="is_delayed",
        seed=seed,
    )
    p_train = pd.concat([p_train, te_train], axis=1)
    p_val = pd.concat([p_val, te_val], axis=1)
    p_test = pd.concat([p_test, te_test], axis=1)

    # 11. Trích xuất TF-IDF n-grams (1, 2) 40 từ khóa kỹ thuật từ summary (chỉ fit trên Train)
    print("[NLP] Extracting 40 TF-IDF n-gram (1, 2) technical keywords and 8 TF-IDF SVD components...", flush=True)
    tfidf = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=40,
        stop_words="english",
        sublinear_tf=True,
        dtype=np.float32,
    )
    tr_summaries = train_df["summary"].fillna("")
    if len(tr_summaries) > 300000:
        rng = np.random.default_rng(seed)
        fit_idx = rng.choice(len(tr_summaries), size=300000, replace=False)
        tfidf.fit(tr_summaries.iloc[fit_idx])
        tr_tfidf_mat = tfidf.transform(tr_summaries)
    else:
        tr_tfidf_mat = tfidf.fit_transform(tr_summaries)

    va_tfidf_mat = tfidf.transform(val_df["summary"].fillna(""))
    te_tfidf_mat = tfidf.transform(test_df["summary"].fillna(""))

    tfidf_feat_names = [f"tfidf_{feat.replace(' ', '_')}" for feat in tfidf.get_feature_names_out()]
    tr_tfidf_df = pd.DataFrame(tr_tfidf_mat.toarray().astype(np.float32), columns=tfidf_feat_names, index=train_df.index)
    va_tfidf_df = pd.DataFrame(va_tfidf_mat.toarray().astype(np.float32), columns=tfidf_feat_names, index=val_df.index)
    te_tfidf_df = pd.DataFrame(te_tfidf_mat.toarray().astype(np.float32), columns=tfidf_feat_names, index=test_df.index)

    svd = TruncatedSVD(n_components=8, random_state=seed)
    if tr_tfidf_mat.shape[0] > 300000:
        svd.fit(tr_tfidf_mat[:300000])
        tr_svd_mat = svd.transform(tr_tfidf_mat).astype(np.float32)
    else:
        tr_svd_mat = svd.fit_transform(tr_tfidf_mat).astype(np.float32)
    va_svd_mat = svd.transform(va_tfidf_mat).astype(np.float32)
    te_svd_mat = svd.transform(te_tfidf_mat).astype(np.float32)

    svd_feat_names = [f"svd_summary_{i}" for i in range(8)]
    tr_svd_df = pd.DataFrame(tr_svd_mat, columns=svd_feat_names, index=train_df.index)
    va_svd_df = pd.DataFrame(va_svd_mat, columns=svd_feat_names, index=val_df.index)
    te_svd_df = pd.DataFrame(te_svd_mat, columns=svd_feat_names, index=test_df.index)

    p_train = pd.concat([p_train, tr_tfidf_df, tr_svd_df], axis=1)
    p_val = pd.concat([p_val, va_tfidf_df, va_svd_df], axis=1)
    p_test = pd.concat([p_test, te_tfidf_df, te_svd_df], axis=1)

    cache_dir.mkdir(parents=True, exist_ok=True)
    p_train.to_parquet(cache_dir / "X_train.parquet", index=False)
    p_val.to_parquet(cache_dir / "X_val.parquet", index=False)
    p_test.to_parquet(cache_dir / "X_test.parquet", index=False)
    print(f"[Feature Engineering] Extracted and cached {p_train.shape[1]} float32 features in {time.time() - t0:.2f}s.", flush=True)
    return p_train, p_val, p_test


def optimize_hyperparameters(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    created_ts: np.ndarray,
    n_trials: int = 35,
    seed: int = 42,
) -> Tuple[dict, float]:
    """Tối ưu hóa siêu tham số Bayesian bằng Optuna (TimeSeriesSplit)."""
    print(f"\n[Optuna] Starting Bayesian Hyperparameter Optimization ({n_trials} trials)...", flush=True)

    # Nếu tập Train quá lớn (>250K dòng), lấy mẫu phân tầng theo trật tự thời gian để tuning nhanh & chuẩn xác
    if len(X_train) > 250000:
        step = len(X_train) / 250000.0
        sub_idx = np.unique((np.arange(250000) * step).astype(np.int64))
        X_opt = X_train.iloc[sub_idx].reset_index(drop=True)
        y_opt = y_train[sub_idx]
        ts_opt = created_ts[sub_idx]
        n_splits = 3
    else:
        X_opt = X_train
        y_opt = y_train
        ts_opt = created_ts
        n_splits = 5

    tscv = TimeSeriesSplit(n_splits=n_splits)
    default_scale_pos = float((len(y_opt) - y_opt.sum()) / max(1, y_opt.sum()))
    ts_norm = (ts_opt - ts_opt.min()) / (ts_opt.max() - ts_opt.min() + 1e-4)

    def objective(trial: optuna.Trial) -> float:
        recency_alpha = trial.suggest_float("recency_alpha", 0.0, 1.5)
        sw = np.exp(recency_alpha * ts_norm).astype(np.float32)
        sw = sw / sw.mean()

        params = {
            "n_estimators": trial.suggest_int("n_estimators", 120, 260, step=20),
            "max_depth": trial.suggest_int("max_depth", 4, 7),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10, log=True),
            "subsample": trial.suggest_float("subsample", 0.70, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.55, 0.85),
            "colsample_bylevel": trial.suggest_float("colsample_bylevel", 0.65, 0.95),
            "min_child_weight": trial.suggest_int("min_child_weight", 4, 20),
            "gamma": trial.suggest_float("gamma", 0.0, 2.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-2, 5.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 15.0, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.80 * default_scale_pos, 1.25 * default_scale_pos),
            "tree_method": "hist",
            "random_state": seed,
            "n_jobs": 8,
            "eval_metric": "logloss",
        }

        pr_auc_scores = []
        for tr_idx, va_idx in tscv.split(X_opt):
            X_tr, y_tr = X_opt.iloc[tr_idx], y_opt[tr_idx]
            X_va, y_va = X_opt.iloc[va_idx], y_opt[va_idx]
            sw_tr = sw[tr_idx]

            clf = xgb.XGBClassifier(**params)
            clf.fit(X_tr, y_tr, sample_weight=sw_tr)
            preds_prob = clf.predict_proba(X_va)[:, 1]
            score = average_precision_score(y_va, preds_prob)
            pr_auc_scores.append(score)

        return float(np.mean(pr_auc_scores))

    def print_callback(study: optuna.Study, trial: optuna.Trial):
        if (trial.number + 1) % 5 == 0 or trial.number == 0:
            print(
                f"  [Optuna Trial {trial.number + 1:2d}/{n_trials}] PR-AUC: {trial.value:.4f} "
                f"(Best so far: {study.best_value:.4f})",
                flush=True,
            )

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, callbacks=[print_callback])

    best_trial = study.best_trial
    best_recency_alpha = best_trial.params.pop("recency_alpha", 0.0)
    best_params = best_trial.params

    print(f"\n[Optuna] Optimization finished! Best Mean PR-AUC: {study.best_value:.4f}", flush=True)
    return best_params, best_recency_alpha


def compute_shap_analysis(
    models: list[xgb.XGBClassifier],
    X_val: pd.DataFrame,
    out_path: str = "experiments/xgboost/shap_summary.json",
    top_k: int = 10,
) -> list[dict]:
    """Tính toán SHAP values trên mẫu đại diện của validation set và lưu Top 10 đặc trưng quan trọng nhất."""
    if len(X_val) > 10000:
        X_shap = X_val.sample(n=10000, random_state=42)
    else:
        X_shap = X_val

    print(f"\n[SHAP] Computing SHAP values across ensemble ({len(X_shap):,} samples)...", flush=True)
    all_shap = []
    for model in models:
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_shap)
        all_shap.append(np.abs(shap_vals))

    mean_abs_shap = np.mean(np.mean(all_shap, axis=0), axis=0)
    feat_names = list(X_val.columns)

    shap_df = pd.DataFrame({
        "feature": feat_names,
        "mean_abs_shap": [float(v) for v in mean_abs_shap],
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    top_features = shap_df.head(top_k).to_dict(orient="records")

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(top_features, f, indent=2, ensure_ascii=False)

    print(f"[SHAP] Top {top_k} features saved to {out_file.resolve()}:", flush=True)
    for rank, item in enumerate(top_features, 1):
        print(f"  {rank:2d}. {item['feature']:35s} : {item['mean_abs_shap']:.5f}", flush=True)

    return top_features


def main():
    parser = argparse.ArgumentParser(description="Train and Optimize XGBoost Binary Pipeline (Track 1)")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--output-dir", type=str, default="experiments/xgboost")
    parser.add_argument("--n-trials", type=int, default=35)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-tuning", action="store_true")

    args = parser.parse_args()
    data_path = Path(args.data_dir)
    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("=================================================================", flush=True)
    print("🚀 TRACK 1: TRAINING GRADIENT BOOSTING (XGBOOST BINARY) PIPELINE", flush=True)
    print("=================================================================", flush=True)

    t0 = time.time()
    train_df = pd.read_parquet(data_path / "train.parquet")
    val_df = pd.read_parquet(data_path / "val.parquet")
    test_df = pd.read_parquet(data_path / "test.parquet")
    print(f"[Data] Loaded Train: {len(train_df):,}, Val: {len(val_df):,}, Test: {len(test_df):,} in {time.time()-t0:.2f}s", flush=True)

    y_train = train_df["is_delayed"].values.astype(np.int32)
    y_val = val_df["is_delayed"].values.astype(np.int32)
    y_test = test_df["is_delayed"].values.astype(np.int32)
    created_ts_tr = train_df["created_ts"].values

    X_train, X_val, X_test = extract_all_features(train_df, val_df, test_df, seed=args.seed)
    del train_df, val_df, test_df
    gc.collect()

    if args.skip_tuning:
        best_params = {
            "n_estimators": 200,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.85,
            "colsample_bytree": 0.70,
            "colsample_bylevel": 0.80,
            "min_child_weight": 10,
            "gamma": 0.5,
            "reg_alpha": 0.5,
            "reg_lambda": 5.0,
            "scale_pos_weight": 1.0,
        }
        best_recency_alpha = 0.8
    else:
        best_params, best_recency_alpha = optimize_hyperparameters(
            X_train, y_train, created_ts_tr, n_trials=args.n_trials, seed=args.seed
        )

    best_params["tree_method"] = "hist"
    best_params["random_state"] = args.seed
    best_params["n_jobs"] = -1
    best_params["eval_metric"] = "logloss"

    ts_norm = (created_ts_tr - created_ts_tr.min()) / (created_ts_tr.max() - created_ts_tr.min() + 1e-4)
    sample_weights = np.exp(best_recency_alpha * ts_norm).astype(np.float32)
    sample_weights = sample_weights / sample_weights.mean()

    print(f"\n[Training] Fitting 5-Fold Stratified XGBoost Ensemble on full Train ({len(X_train):,} rows)...", flush=True)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    models = []
    y_val_prob = np.zeros(len(X_val), dtype=np.float64)
    y_test_prob = np.zeros(len(X_test), dtype=np.float64)

    for fold, (tr_idx, _) in enumerate(skf.split(np.zeros(len(y_train)), y_train)):
        fold_params = best_params.copy()
        fold_params["random_state"] = args.seed + fold

        clf = xgb.XGBClassifier(**fold_params)
        clf.fit(X_train.iloc[tr_idx], y_train[tr_idx], sample_weight=sample_weights[tr_idx])
        models.append(clf)

        y_val_prob += clf.predict_proba(X_val)[:, 1] / 5.0
        y_test_prob += clf.predict_proba(X_test)[:, 1] / 5.0

    val_pred_file = out_path / "predictions_val.csv"
    test_pred_file = out_path / "predictions_test.csv"

    pd.DataFrame({"y_true": y_val, "y_prob": y_val_prob}).to_csv(val_pred_file, index=False)
    pd.DataFrame({"y_true": y_test, "y_prob": y_test_prob}).to_csv(test_pred_file, index=False)

    shap_file = out_path / "shap_summary.json"
    compute_shap_analysis(models, X_val, out_path=str(shap_file), top_k=10)

    evaluate_predictions(
        test_pred_path=str(test_pred_file),
        val_pred_path=str(val_pred_file),
        track="xgboost",
    )


if __name__ == "__main__":
    main()
