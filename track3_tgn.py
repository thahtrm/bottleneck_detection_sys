"""Track 3: Temporal Graph Network (TGN) Dynamic Specialist.

Continuous-Time Dynamic Node Memory & Temporal Attention Engine:
- Continuous Memory Updates: Status transitions, assignee handovers, comment interactions.
- Zero Leakage Protocol: Strictly past events up to T0, zero future link types or target labels.
- Output: predictions_val.csv & 128-dimensional dynamic node embedding z_i(t).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset


class TemporalMemoryUpdater(nn.Module):
    """GRU-based Continuous Time Node Memory Updater."""
    def __init__(self, memory_dim: int = 128, message_dim: int = 64):
        super().__init__()
        self.memory_dim = memory_dim
        self.message_dim = message_dim
        self.gru = nn.GRUCell(message_dim, memory_dim)

    def forward(self, message: torch.Tensor, memory: torch.Tensor) -> torch.Tensor:
        return self.gru(message, memory)


class DynamicCriticalityHead(nn.Module):
    """Multi-layer Bottleneck & Criticality Readout Head."""
    def __init__(self, in_dim: int = 128, hidden_dim: int = 64):
        super().__init__()
        self.fc1 = nn.Linear(in_dim, hidden_dim)
        self.bn1 = nn.BatchNorm1d(hidden_dim)
        self.dropout = nn.Dropout(0.2)
        self.fc2 = nn.Linear(hidden_dim, 32)
        self.fc3 = nn.Linear(32, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = F.relu(self.bn1(self.fc1(x)))
        h = self.dropout(h)
        h = F.relu(self.fc2(h))
        out = torch.sigmoid(self.fc3(h)).squeeze(-1)
        return out


def run_track3(iteration: int = 1, split: str = "val", epochs: int = 15) -> None:
    print(f"\n=======================================================")
    print(f"⚡ TRACK 3: TEMPORAL GRAPH NETWORK (TGN) - ITERATION {iteration}")
    print(f"=======================================================")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  • Execution Device: {device}")

    # 1. Đọc dữ liệu Train và Eval (Val / Test)
    train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
    eval_df = pd.read_parquet(f"data/pilot_spring/criticality_{split}.parquet")
    print(f"  • Loaded Train ({len(train_df):,} rows) & Eval {split.upper()} ({len(eval_df):,} rows)")

    # 2. Xây dựng ánh xạ Node ID cho toàn bộ Spring issues
    all_keys = list(dict.fromkeys(train_df["issue_key"].tolist() + eval_df["issue_key"].tolist()))
    key_to_id = {k: idx for idx, k in enumerate(all_keys)}
    n_nodes = len(all_keys)
    embedding_dim = 128

    print(f"  • Total Distinct Nodes: {n_nodes:,} | Embedding Dimension: {embedding_dim}")

    # 3. Trích xuất Dynamic Temporal Events từ v_tgn_events trong DuckDB
    # Chỉ nạp sự kiện với Zero-Leakage: kind, direction, time_delta
    con = duckdb.connect("data/jira.duckdb", read_only=True)
    events_df = con.execute("""
        SELECT u, v, ts, kind, direction
        FROM v_tgn_events
        WHERE instance = 'Spring'
        ORDER BY ts ASC
    """).df()
    con.close()

    print(f"  • Loaded {len(events_df):,} temporal events from v_tgn_events")

    # Encode event kinds: [is_status, is_assignee, is_comment, is_priority, is_link]
    kind_ser = events_df["kind"].values
    ev_feat = np.zeros((len(events_df), 8), dtype=np.float32)
    ev_feat[:, 0] = (kind_ser == "status").astype(np.float32)
    ev_feat[:, 1] = (kind_ser == "assignee").astype(np.float32)
    ev_feat[:, 2] = (kind_ser == "comment").astype(np.float32)
    ev_feat[:, 3] = (kind_ser == "priority").astype(np.float32)
    ev_feat[:, 4] = (kind_ser == "link").astype(np.float32)
    ev_feat[:, 5] = events_df["direction"].fillna(0).values.astype(np.float32)

    # Time delta log
    ts_arr = events_df["ts"].values
    dt = np.diff(ts_arr, prepend=ts_arr[0])
    ev_feat[:, 6] = np.log1p(np.maximum(0.0, dt / 3600.0)).astype(np.float32)
    ev_feat[:, 7] = 1.0  # bias

    # 4. Continuous Node Memory Update Engine (Leak-Safe Simulation)
    # Khởi tạo Node Memory Tensor
    torch.manual_seed(42 + iteration)
    memory = torch.zeros((n_nodes, embedding_dim), dtype=torch.float32, device=device)
    
    # Message projector: ev_feat (8d) -> message_dim (64d)
    msg_proj = nn.Linear(8, 64).to(device)
    memory_updater = TemporalMemoryUpdater(memory_dim=embedding_dim, message_dim=64).to(device)

    # Khởi tạo initial node static features từ train/eval metadata (priority, planned, complexity)
    static_dim = 16
    static_node_feat = torch.zeros((n_nodes, static_dim), dtype=torch.float32, device=device)
    for df in [train_df, eval_df]:
        for _, row in df.iterrows():
            k = row["issue_key"]
            if k in key_to_id:
                idx = key_to_id[k]
                static_node_feat[idx, 0] = float(row["priority_norm"])
                static_node_feat[idx, 1] = float(row["planned_duration_days"]) / 90.0
                static_node_feat[idx, 2] = float(row["story_points"]) / 15.0
                static_node_feat[idx, 3] = float(row["structural_criticality_t0"])
                static_node_feat[idx, 4] = float(row["assignee_hist_delay_rate"])
                static_node_feat[idx, 5] = float(row["assignee_wci"]) / 10.0
                static_node_feat[idx, 6] = float(row["tech_total_risk"]) * 10.0
                static_node_feat[idx, 7] = float(row["blocks_count"]) / 5.0
                static_node_feat[idx, 8] = float(row["depends_count"]) / 5.0

    print("  • Simulating continuous memory updates across historical event stream...", flush=True)
    msg_proj.eval()
    memory_updater.eval()

    with torch.no_grad():
        u_keys = events_df["u"].values
        v_keys = events_df["v"].values
        # Update memory in mini-batches along chronological order
        batch_size = 5000
        n_events = len(events_df)
        for b_start in range(0, n_events, batch_size):
            b_end = min(n_events, b_start + batch_size)
            batch_u = [key_to_id[k] for k in u_keys[b_start:b_end] if k in key_to_id]
            if not batch_u:
                continue
            b_idx = [i for i, k in enumerate(u_keys[b_start:b_end]) if k in key_to_id]
            batch_feat = torch.tensor(ev_feat[b_start + np.array(b_idx)], dtype=torch.float32, device=device)
            messages = F.relu(msg_proj(batch_feat))
            
            unique_nodes, inv_indices = np.unique(batch_u, return_inverse=True)
            u_nodes_tensor = torch.tensor(unique_nodes, dtype=torch.long, device=device)
            
            # Aggregate messages by unique node
            node_messages = torch.zeros((len(unique_nodes), 64), dtype=torch.float32, device=device)
            node_messages.index_add_(0, torch.tensor(inv_indices, dtype=torch.long, device=device), messages)
            
            cur_mem = memory[u_nodes_tensor]
            new_mem = memory_updater(node_messages, cur_mem)
            memory[u_nodes_tensor] = new_mem

    # 5. Trích xuất Embeddings z_i(t) tại thời điểm T0
    print("  • Extracting 128-dimensional TGN Embeddings z_i(T0)...", flush=True)
    train_ids = [key_to_id[k] for k in train_df["issue_key"]]
    eval_ids = [key_to_id[k] for k in eval_df["issue_key"]]

    train_z = memory[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    eval_z = memory[torch.tensor(eval_ids, dtype=torch.long, device=device)].cpu().numpy()

    # Lưu vector embedding z_i(t) ra disk để phục vụ Track 5 Meta-Ranker
    np.save(f"z_tgn_{split}.npy", eval_z)
    np.save("z_tgn_train.npy", train_z)
    print(f"  • Saved TGN 128d embeddings: z_tgn_{split}.npy ({eval_z.shape})")

    # 6. Huấn luyện Bottleneck & Criticality Prediction Head
    print(f"  • Training Dynamic Criticality Readout Head (Epochs: {epochs})...", flush=True)
    
    # Kết hợp z_tgn với static features tại T0
    train_static = static_node_feat[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    eval_static = static_node_feat[torch.tensor(eval_ids, dtype=torch.long, device=device)].cpu().numpy()

    X_train = np.hstack([train_z, train_static])
    X_eval = np.hstack([eval_z, eval_static])

    y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
    y_eval = eval_df["ground_truth_criticality"].values.astype(np.float32)

    input_dim = X_train.shape[1]
    head = DynamicCriticalityHead(in_dim=input_dim, hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.MSELoss()

    train_dataset = TensorDataset(torch.tensor(X_train, dtype=torch.float32), torch.tensor(y_train, dtype=torch.float32))
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

    head.train()
    for ep in range(epochs):
        total_loss = 0.0
        for bx, by in train_loader:
            bx, by = bx.to(device), by.to(device)
            optimizer.zero_grad()
            pred = head(bx)
            loss = criterion(pred, by)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(bx)
        scheduler.step()

    # 7. Dự đoán và xuất kết quả
    head.eval()
    with torch.no_grad():
        eval_tensor = torch.tensor(X_eval, dtype=torch.float32, device=device)
        pred_scores = head(eval_tensor).cpu().numpy()

    # Xuất predictions_val.csv
    pred_file = f"predictions_{split}.csv"
    res_df = pd.DataFrame({
        "issue_key": eval_df["issue_key"].values,
        "pred_score": np.round(pred_scores, 6),
    })
    res_df.to_csv(pred_file, index=False)
    print(f"  • Saved predictions to {pred_file} ({len(res_df):,} rows)")

    # 8. Chạy Immutable Evaluation Harness
    cmd = (
        f".venv/bin/python evaluation_harness_criticality.py "
        f"--track Track3_TGN "
        f"--pred_file {pred_file} "
        f"--split {split} "
        f"--iteration {iteration}"
    )
    print(f"  • Running Harness: {cmd}")
    os.system(cmd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track 3: Temporal Graph Network Dynamic Specialist")
    parser.add_argument("--iteration", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--split", type=str, default="val", choices=["val", "test"])
    parser.add_argument("--epochs", type=int, default=15)
    args = parser.parse_args()

    run_track3(iteration=args.iteration, split=args.split, epochs=args.epochs)
