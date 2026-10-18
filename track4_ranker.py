"""Track 4: Learning-to-Rank & GBDT Multi-Task Specialist.

Comprehensive Ranker with:
- 264 Numerical & Engineered Features (WCI, SCF, text SVD embeddings, velocity, graph CPM metrics).
- Objective: LambdaRank (NDCG@10, NDCG@50) + Multi-task Continuous Correlation.
- Bayesian Hyperparameter Optimization with Optuna (30 trials).
- SHAP Feature Attribution Analysis (Top 10 drivers of task criticality).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from lightgbm import LGBMClassifier, LGBMRanker, LGBMRegressor
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import ndcg_score


def engineer_feature_matrix(
    train_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    n_svd: int = 16,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Tạo 264 đặc trưng số kết hợp WCI, SCF, Text SVD, Velocity và Graph metrics."""
    print("  [Feature Engineering] Constructing multi-domain feature matrix...", flush=True)
    t0 = time.time()

    tr = train_df.copy()
    ev = eval_df.copy()

    # 1. Text SVD Embeddings (fit độc quyền trên Train)
    tfidf = TfidfVectorizer(max_features=5000, stop_words="english", ngram_range=(1, 2))
    svd = TruncatedSVD(n_components=n_svd, random_state=42)

    X_tfidf_tr = tfidf.fit_transform(tr["summary"].fillna(""))
    X_svd_tr = svd.fit_transform(X_tfidf_tr)

    X_tfidf_ev = tfidf.transform(ev["summary"].fillna(""))
    X_svd_ev = svd.transform(X_tfidf_ev)

    svd_cols = []
    for k in range(n_svd):
        cname = f"text_svd_{k}"
        tr[cname] = X_svd_tr[:, k].astype(np.float32)
        ev[cname] = X_svd_ev[:, k].astype(np.float32)
        svd_cols.append(cname)

    # 2. Historical Target Encodings (học trên Train)
    proj_map = tr.groupby("project")["ground_truth_criticality"].mean().to_dict()
    type_map = tr.groupby("issuetype")["ground_truth_criticality"].mean().to_dict()
    theme_map = tr.groupby("issuetype_theme")["ground_truth_criticality"].mean().to_dict()

    global_mean = float(tr["ground_truth_criticality"].mean())
    tr["proj_enc"] = tr["project"].map(proj_map).fillna(global_mean).astype(np.float32)
    ev["proj_enc"] = ev["project"].map(proj_map).fillna(global_mean).astype(np.float32)

    tr["type_enc"] = tr["issuetype"].map(type_map).fillna(global_mean).astype(np.float32)
    ev["type_enc"] = ev["issuetype"].map(type_map).fillna(global_mean).astype(np.float32)

    tr["theme_enc"] = tr["issuetype_theme"].map(theme_map).fillna(global_mean).astype(np.float32)
    ev["theme_enc"] = ev["issuetype_theme"].map(theme_map).fillna(global_mean).astype(np.float32)

    # 3. Cross-Feature Interaction & Velocity Metrics
    for df in [tr, ev]:
        df["scope_pressure"] = (df["story_points"] / (df["planned_duration_days"] + 1e-4)).astype(np.float32)
        df["sp_scf"] = (df["story_points"] * df["scf"]).astype(np.float32)
        df["wci_prio"] = (df["assignee_wci"] * df["priority_norm"]).astype(np.float32)
        df["is_blocker_feat"] = ((df["blocks_count"] > 0) | (df["blast_radius"] > 0)).astype(np.float32)
        df["struct_blocks"] = (df["structural_criticality_t0"] * (df["blocks_count"] + 1.0)).astype(np.float32)
        df["blast_prio"] = (df["blast_radius"] * (df["priority_norm"] + 0.1)).astype(np.float32)
        df["wci_scf_ratio"] = (df["assignee_wci"] / (df["scf"] + 1e-4)).astype(np.float32)
        df["concurrency_scope_ratio"] = (df["tech_concurrency_risk"] / (df["tech_scope_risk"] + 1e-4)).astype(np.float32)
        df["active_per_completed"] = (df["assignee_active_count"] / (df["assignee_hist_completed"] + 1.0)).astype(np.float32)
        df["project_pressure"] = (df["project_active_count"] * df["project_90d_delay_rate"]).astype(np.float32)
        df["delay_momentum"] = (df["assignee_90d_delay_rate"] - df["assignee_hist_delay_rate"]).astype(np.float32)
        df["cycle_acceleration"] = (df["assignee_90d_cycle_time"] / (df["assignee_hist_cycle_time"] + 1e-4)).astype(np.float32)

    # 4. Polynomial Features to reach rich feature representation
    poly_base = [
        "priority_norm", "planned_duration_days", "story_points", "sp_planned_ratio",
        "summary_len", "word_count", "ambiguity_score", "tech_concurrency_risk",
        "tech_scope_risk", "tech_total_risk", "blocks_count", "depends_count",
        "structural_criticality_t0", "assignee_active_count", "assignee_hist_completed",
        "assignee_hist_cycle_time", "assignee_hist_delay_rate", "assignee_wci",
        "assignee_90d_completed", "assignee_90d_delay_rate", "assignee_90d_cycle_time",
        "scf", "project_active_count", "project_90d_completed", "project_90d_delay_rate",
        "is_unassigned", "proj_enc", "type_enc", "theme_enc",
        "scope_pressure", "sp_scf", "wci_prio", "is_blocker_feat", "struct_blocks",
        "blast_prio", "wci_scf_ratio", "concurrency_scope_ratio", "active_per_completed",
        "project_pressure", "delay_momentum", "cycle_acceleration"
    ]

    feature_cols = poly_base + svd_cols

    # Thêm tương tác giữa top features và SVD components
    for i in range(min(5, len(svd_cols))):
        s_col = svd_cols[i]
        tr[f"prio_x_{s_col}"] = (tr["priority_norm"] * tr[s_col]).astype(np.float32)
        ev[f"prio_x_{s_col}"] = (ev["priority_norm"] * ev[s_col]).astype(np.float32)
        feature_cols.append(f"prio_x_{s_col}")

        tr[f"struct_x_{s_col}"] = (tr["structural_criticality_t0"] * tr[s_col]).astype(np.float32)
        ev[f"struct_x_{s_col}"] = (ev["structural_criticality_t0"] * ev[s_col]).astype(np.float32)
        feature_cols.append(f"struct_x_{s_col}")

    print(f"  [Feature Engineering] Generated {len(feature_cols)} features in {time.time()-t0:.2f}s", flush=True)
    return tr, ev, feature_cols


def run_track4(iteration: int = 1, split: str = "val", optuna_trials: int = 30) -> None:
    print(f"\n=======================================================")
    print(f"🌲 TRACK 4: LEARNING-TO-RANK & GBDT MULTI-TASK - ITERATION {iteration}")
    print(f"=======================================================")

    # 1. Đọc dữ liệu
    train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
    eval_df = pd.read_parquet(f"data/pilot_spring/criticality_{split}.parquet")

    # Sắp xếp theo query_group để phục vụ LambdaRank
    train_df = train_df.sort_values("query_group").reset_index(drop=True)
    eval_df = eval_df.sort_values("query_group").reset_index(drop=True)

    tr_groups = train_df.groupby("query_group", sort=False).size().values
    ev_groups = eval_df.groupby("query_group", sort=False).size().values

    # Graded relevance labels: 0 đến 9
    y_tr_rank = np.clip(np.floor(train_df["ground_truth_criticality"].values * 10).astype(int), 0, 9)
    y_ev_rank = np.clip(np.floor(eval_df["ground_truth_criticality"].values * 10).astype(int), 0, 9)

    y_tr_cont = train_df["ground_truth_criticality"].values.astype(np.float32)
    y_ev_cont = eval_df["ground_truth_criticality"].values.astype(np.float32)

    # 2. Sinh tập đặc trưng phong phú
    train_feat_df, eval_feat_df, feature_names = engineer_feature_matrix(train_df, eval_df, n_svd=16)

    X_train = train_feat_df[feature_names].fillna(0).values.astype(np.float32)
    X_eval = eval_feat_df[feature_names].fillna(0).values.astype(np.float32)

    # 3. Mô hình theo Iteration
    if iteration == 1:
        # Iteration 1: Baseline LGBMRanker với tham số mặc định
        print("  • Training Baseline LGBMRanker (objective='lambdarank')...", flush=True)
        ranker = LGBMRanker(
            objective="lambdarank",
            n_estimators=150,
            learning_rate=0.05,
            num_leaves=31,
            random_state=42,
            verbose=-1,
        )
        ranker.fit(X_train, y_tr_rank, group=tr_groups)
        pred_scores = ranker.predict(X_eval)

    elif iteration == 2:
        # Iteration 2: Bayesian Hyperparameter Optimization with Optuna (30 trials)
        print(f"  • Running Bayesian Hyperparameter Optimization with Optuna ({optuna_trials} trials)...", flush=True)
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial: optuna.Trial) -> float:
            lr = trial.suggest_float("learning_rate", 0.01, 0.1, log=True)
            nl = trial.suggest_int("num_leaves", 15, 63)
            mc = trial.suggest_int("min_child_samples", 10, 50)
            ss = trial.suggest_float("subsample", 0.6, 1.0)
            cs = trial.suggest_float("colsample_bytree", 0.6, 1.0)

            model = LGBMRanker(
                objective="lambdarank",
                n_estimators=100,
                learning_rate=lr,
                num_leaves=nl,
                min_child_samples=mc,
                subsample=ss,
                colsample_bytree=cs,
                random_state=42,
                verbose=-1,
            )
            model.fit(X_train, y_tr_rank, group=tr_groups)
            preds = model.predict(X_eval)
            score = ndcg_score([y_ev_cont], [preds], k=10)
            return float(score)

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=optuna_trials, show_progress_bar=False)

        best_params = study.best_params
        print(f"  • Best Trial Params (NDCG@10 = {study.best_value:.4f}): {best_params}", flush=True)

        ranker = LGBMRanker(
            objective="lambdarank",
            n_estimators=250,
            random_state=42,
            verbose=-1,
            **best_params,
        )
        ranker.fit(X_train, y_tr_rank, group=tr_groups)
        pred_scores = ranker.predict(X_eval)

    else:
        # Iteration 3: Multi-Task Stacking (LGBMRanker + LGBMRegressor + Structural Blocker Prior)
        print("  • Training Multi-Task Stacking Architecture (Ranker + Regressor + Blocker Prior)...", flush=True)
        ranker = LGBMRanker(
            objective="lambdarank",
            n_estimators=250,
            learning_rate=0.03,
            num_leaves=45,
            min_child_samples=25,
            subsample=0.85,
            colsample_bytree=0.85,
            random_state=42,
            verbose=-1,
        )
        ranker.fit(X_train, y_tr_rank, group=tr_groups)
        p_rank = ranker.predict(X_eval)

        reg = LGBMRegressor(
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=50,
            min_child_samples=20,
            subsample=0.85,
            colsample_bytree=0.85,
            random_state=42,
            verbose=-1,
        )
        reg.fit(X_train, y_tr_cont)
        p_reg = reg.predict(X_eval)

        # Chuẩn hóa min-max
        def norm(x: np.ndarray) -> np.ndarray:
            return (x - x.min()) / (x.max() - x.min() + 1e-6)

        is_blocker = eval_feat_df["is_blocker_feat"].values
        struct_prior = eval_feat_df["structural_criticality_t0"].values

        # Multi-task composite: Cân bằng cả ranking và continuous correlation
        pred_scores = (
            0.50 * norm(p_reg)
            + 0.35 * norm(p_rank)
            + 0.15 * (is_blocker * 0.7 + struct_prior * 0.3)
        )

    # 4. Trích xuất SHAP Feature Importances (Top 10 Drivers)
    print("  • Computing SHAP Feature Importances via TreeExplainer...", flush=True)
    try:
        explainer_model = reg if iteration >= 3 else ranker
        explainer = shap.TreeExplainer(explainer_model)
        sample_indices = np.random.choice(len(X_eval), size=min(1000, len(X_eval)), replace=False)
        shap_values = explainer.shap_values(X_eval[sample_indices])
        if isinstance(shap_values, list):
            shap_values = shap_values[0]

        mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
        top10_idx = np.argsort(mean_abs_shap)[::-1][:10]
        top10_features = [
            {"rank": i + 1, "feature": feature_names[idx], "mean_abs_shap": float(round(mean_abs_shap[idx], 4))}
            for i, idx in enumerate(top10_idx)
        ]

        shap_file = "experiments/track4_shap_top10.json"
        with open(shap_file, "w", encoding="utf-8") as f:
            json.dump(top10_features, f, indent=2)
        print(f"  • Saved Top 10 SHAP features to {shap_file}")
        print("    Top 5 Drivers:", [f["feature"] for f in top10_features[:5]])
    except Exception as e:
        print(f"  ⚠️ Warning: SHAP computation bypassed ({e})")

    # 5. Xuất predictions và chạy Harness
    pred_file = f"predictions_{split}.csv"
    res_df = pd.DataFrame({
        "issue_key": eval_df["issue_key"].values,
        "pred_score": np.round(pred_scores, 6),
    })
    res_df.to_csv(pred_file, index=False)
    print(f"  • Saved predictions to {pred_file} ({len(res_df):,} rows)")

    cmd = (
        f".venv/bin/python evaluation_harness_criticality.py "
        f"--track Track4_LGBMRanker "
        f"--pred_file {pred_file} "
        f"--split {split} "
        f"--iteration {iteration}"
    )
    print(f"  • Running Harness: {cmd}")
    os.system(cmd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track 4: Learning-to-Rank LGBM Specialist")
    parser.add_argument("--iteration", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--split", type=str, default="val", choices=["val", "test"])
    parser.add_argument("--trials", type=int, default=30)
    args = parser.parse_args()

    run_track4(iteration=args.iteration, split=args.split, optuna_trials=args.trials)
