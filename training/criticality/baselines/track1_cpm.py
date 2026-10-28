"""Track 1: Topological DAG & CPM Specialist.

Auto-Iteration Engine for Structural Baseline:
- Iteration 1: Canonical CPM Slack + Blast Radius + Inverted PageRank.
- Iteration 2: Prior Structural Pressure Calibration for Isolated Nodes (Priority + SLA + Link density).
- Iteration 3: Multi-Scale Topological Centrality with Harmonic Downstream Decay & Betweenness.
"""
from __future__ import annotations

import argparse

import networkx as nx
from pathlib import Path

import numpy as np
import pandas as pd

from early_risk_detection.evaluation import evaluate_criticality

OUT_DIR = Path("outputs/criticality/Track1_GraphCPM")


def min_max_norm(arr: np.ndarray) -> np.ndarray:
    p99 = np.percentile(arr, 99) if len(arr) > 0 else 1.0
    p1 = np.percentile(arr, 1) if len(arr) > 0 else 0.0
    if p99 > p1:
        return np.clip((arr - p1) / (p99 - p1), 0.0, 1.0).astype(np.float32)
    return np.zeros_like(arr, dtype=np.float32)


def run_track1(iteration: int = 1, split: str = "val") -> None:
    print("\n=======================================================")
    print(f"🚀 TRACK 1: GRAPH CPM & TOPOLOGY - ITERATION {iteration}")
    print("=======================================================")

    # 1. Đọc dữ liệu tập train để học prior cycle time và dữ liệu eval (val hoặc test)
    train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
    eval_df = pd.read_parquet(f"data/pilot_spring/criticality_{split}.parquet")
    
    print(f"  • Loaded Train ({len(train_df):,} rows) & Eval {split.upper()} ({len(eval_df):,} rows)")

    # 2. Xây dựng DAG từ issue_links (Target -> Source)
    # Target là task tiên quyết (predecessor), Source là task phụ thuộc (successor)
    G = nx.DiGraph()
    for _, row in train_df[train_df["blast_radius"] > 0].iterrows():
        G.add_node(row["issue_key"])

    # Đọc lại link từ DuckDB hoặc từ cột graph features
    import duckdb
    con = duckdb.connect("data/jira.duckdb", read_only=True)
    links = con.execute("""
        SELECT source_key, target_key 
        FROM issue_links 
        WHERE instance = 'Spring' AND link_type_std = 'Depend'
    """).fetchall()
    con.close()

    for s, t in links:
        G.add_edge(t, s)

    print(f"  • Dependency Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    # Inverted PageRank (ngược chiều: task nào bị nhiều task trỏ tới làm tiên quyết sẽ có authority cao)
    G_rev = G.reverse()
    try:
        pr_map = nx.pagerank(G_rev, alpha=0.85, max_iter=200)
    except Exception:
        pr_map = {n: 1.0 / max(1, len(G)) for n in G.nodes()}

    # Harmonic blast radius & depth-weighted downstream count
    blast_map = {}
    harmonic_map = {}
    for n in eval_df["issue_key"]:
        if G.has_node(n):
            desc = nx.descendants(G, n)
            blast_map[n] = float(len(desc))
            h_score = 0.0
            for d in desc:
                try:
                    dist = nx.shortest_path_length(G, n, d)
                    h_score += 1.0 / dist
                except Exception:
                    h_score += 1.0
            harmonic_map[n] = float(h_score)
        else:
            blast_map[n] = 0.0
            harmonic_map[n] = 0.0

    # 3. Tính toán CPM Slack
    slack_raw = eval_df["slack_time"].values.astype(np.float32)
    blast_raw = np.array([blast_map.get(k, 0.0) for k in eval_df["issue_key"]], dtype=np.float32)
    harmonic_raw = np.array([harmonic_map.get(k, 0.0) for k in eval_df["issue_key"]], dtype=np.float32)
    pr_raw = np.array([pr_map.get(k, 0.0) for k in eval_df["issue_key"]], dtype=np.float32)

    norm_slack_tightness = np.exp(-slack_raw / 14.0)  # Càng gần 0 (đường găng) -> càng tiến tới 1
    norm_blast = min_max_norm(blast_raw)
    norm_harmonic = min_max_norm(harmonic_raw)
    norm_pr = min_max_norm(pr_raw)

    is_graph = (blast_raw > 0) | (slack_raw < 900)

    if iteration == 1:
        # Canonical CPM Baseline:
        # Y_graph = 0.5 * (1 - norm(S_i)) + 0.3 * norm(BlastRadius_i) + 0.2 * norm(PageRank_i)
        pred_scores = 0.50 * norm_slack_tightness + 0.30 * norm_blast + 0.20 * norm_pr

    elif iteration == 2:
        # Iteration 2: Giải quyết điểm yếu của node độc lập (Isolated Nodes).
        # Tích hợp áp lực cấu trúc tiên nghiệm tại T0 (priority_norm, sp_planned_ratio, scf).
        prior_structural_pressure = (
            0.45 * eval_df["priority_norm"].values
            + 0.30 * min_max_norm(eval_df["sp_planned_ratio"].values)
            + 0.25 * min_max_norm(eval_df["scf"].values)
        ).astype(np.float32)

        pred_scores = np.where(
            is_graph,
            0.45 * norm_slack_tightness + 0.35 * norm_blast + 0.20 * norm_pr + 0.15 * prior_structural_pressure,
            0.85 * prior_structural_pressure + 0.15 * min_max_norm(eval_df["summary_len"].values),
        )

    else:  # iteration >= 3
        # Iteration 3: Tối ưu sâu với Harmonic Downstream Decay và Tỷ trọng Đường găng động
        prior_structural_pressure = (
            0.50 * eval_df["priority_norm"].values
            + 0.30 * min_max_norm(eval_df["sp_planned_ratio"].values)
            + 0.20 * min_max_norm(eval_df["scf"].values)
        ).astype(np.float32)

        graph_score = (
            0.40 * norm_slack_tightness
            + 0.35 * norm_harmonic
            + 0.15 * norm_pr
            + 0.10 * prior_structural_pressure
        )

        isolated_score = (
            0.70 * prior_structural_pressure
            + 0.20 * min_max_norm(eval_df["word_count"].values)
            + 0.10 * min_max_norm(eval_df["tech_total_risk"].values)
        )

        pred_scores = np.where(is_graph, graph_score * 1.35, isolated_score)

    # 4. Xuất predictions_val.csv / predictions_test.csv
    pred_file = OUT_DIR / f"predictions_{split}.csv"
    res_df = pd.DataFrame({
        "issue_key": eval_df["issue_key"].values,
        "pred_score": np.round(pred_scores, 6),
    })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res_df.to_csv(pred_file, index=False)
    print(f"  • Saved predictions to {pred_file} ({len(res_df):,} rows)")

    # 5. Chạy Immutable Evaluation Harness
    evaluate_criticality(pred_file=str(pred_file), track="Track1_GraphCPM", split=split, iteration=iteration)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track 1: Topological DAG & CPM Specialist")
    parser.add_argument("--iteration", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--split", type=str, default="val", choices=["val", "test"])
    args = parser.parse_args()

    run_track1(iteration=args.iteration, split=args.split)
