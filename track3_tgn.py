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


def run_track3(iteration: int = 3, split: str = "all", epochs: int = 18) -> None:
    print(f"\n=======================================================")
    print(f"⚡ TRACK 3: TEMPORAL GRAPH NETWORK (TGN) - ITERATION {iteration}")
    print(f"=======================================================")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  • Execution Device: {device}")

    # 1. Đọc dữ liệu Train, Val và Test
    train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
    val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
    test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")
    print(f"  • Loaded Train ({len(train_df):,} rows), Val ({len(val_df):,} rows), Test ({len(test_df):,} rows)")

    # 2. Xây dựng ánh xạ Node ID cho toàn bộ Spring issues (69,154 issues)
    all_keys = list(dict.fromkeys(train_df["issue_key"].tolist() + val_df["issue_key"].tolist() + test_df["issue_key"].tolist()))
    key_to_id = {k: idx for idx, k in enumerate(all_keys)}
    n_nodes = len(all_keys)
    embedding_dim = 128

    print(f"  • Total Distinct Nodes: {n_nodes:,} | Embedding Dimension: {embedding_dim}")

    # 3. Trích xuất Dynamic Temporal Events từ v_tgn_events trong DuckDB
    # Chỉ nạp sự kiện với Zero-Leakage: kind, direction, time_delta
    con = duckdb.connect("data/jira.duckdb", read_only=True)
    if iteration >= 4:
        events_df = con.execute("""
            SELECT u, v, ts, kind, detail_to, link_type, direction
            FROM v_tgn_events
            WHERE instance = 'Spring'
            ORDER BY ts ASC
        """).df()
    else:
        events_df = con.execute("""
            SELECT u, v, ts, kind, direction
            FROM v_tgn_events
            WHERE instance = 'Spring'
            ORDER BY ts ASC
        """).df()
    con.close()

    print(f"  • Loaded {len(events_df):,} temporal events from v_tgn_events")

    # Encode event features
    kind_ser = events_df["kind"].values
    ts_arr = events_df["ts"].values
    dt = np.diff(ts_arr, prepend=ts_arr[0])
    dt_norm = np.maximum(0.0, dt / 3600.0)

    if iteration >= 4:
        # Iteration 4: 16d event features + 16d Fourier Harmonic Time Encoding = 32d
        n_events = len(events_df)
        freqs = 1.0 / (10.0 ** np.linspace(0, 4, 8))
        time_feat = np.zeros((n_events, 16), dtype=np.float32)
        for fi, w in enumerate(freqs):
            time_feat[:, 2 * fi] = np.cos(w * dt_norm)
            time_feat[:, 2 * fi + 1] = np.sin(w * dt_norm)

        link_type_ser = events_df["link_type"].values
        detail_to_ser = events_df["detail_to"].values

        ev_feat_base = np.zeros((n_events, 16), dtype=np.float32)
        ev_feat_base[:, 0] = (kind_ser == "status").astype(np.float32)
        ev_feat_base[:, 1] = (kind_ser == "assignee").astype(np.float32)
        ev_feat_base[:, 2] = (kind_ser == "comment").astype(np.float32)
        ev_feat_base[:, 3] = (kind_ser == "priority").astype(np.float32)
        ev_feat_base[:, 4] = (kind_ser == "link").astype(np.float32)
        ev_feat_base[:, 5] = (link_type_ser == "Depend").astype(np.float32)
        ev_feat_base[:, 6] = (link_type_ser == "Relate").astype(np.float32)
        ev_feat_base[:, 7] = (link_type_ser == "Duplicate").astype(np.float32)
        ev_feat_base[:, 8] = np.isin(detail_to_ser, ["5", "6"]).astype(np.float32)
        ev_feat_base[:, 9] = np.isin(detail_to_ser, ["4", "10001", "10002"]).astype(np.float32)
        ev_feat_base[:, 10] = events_df["direction"].fillna(0).values.astype(np.float32)
        ev_feat_base[:, 11] = np.log1p(dt_norm).astype(np.float32)
        ev_feat_base[:, 12] = 1.0

        ev_feat = np.hstack([ev_feat_base, time_feat]).astype(np.float32)
        ev_dim = 32
    else:
        ev_feat = np.zeros((len(events_df), 8), dtype=np.float32)
        ev_feat[:, 0] = (kind_ser == "status").astype(np.float32)
        ev_feat[:, 1] = (kind_ser == "assignee").astype(np.float32)
        ev_feat[:, 2] = (kind_ser == "comment").astype(np.float32)
        ev_feat[:, 3] = (kind_ser == "priority").astype(np.float32)
        ev_feat[:, 4] = (kind_ser == "link").astype(np.float32)
        ev_feat[:, 5] = events_df["direction"].fillna(0).values.astype(np.float32)
        ev_feat[:, 6] = np.log1p(dt_norm).astype(np.float32)
        ev_feat[:, 7] = 1.0  # bias
        ev_dim = 8

    # 4. Continuous Node Memory Update Engine (Leak-Safe Simulation)
    torch.manual_seed(45 if iteration >= 4 else (42 + iteration))
    memory = torch.zeros((n_nodes, embedding_dim), dtype=torch.float32, device=device)
    
    # Message projector: ev_feat (ev_dim) -> message_dim (64d)
    msg_proj = nn.Linear(ev_dim, 64).to(device)
    memory_updater = TemporalMemoryUpdater(memory_dim=embedding_dim, message_dim=64).to(device)

    # Khởi tạo initial node static features từ train/val/test metadata
    static_dim = 9 if iteration >= 4 else 16
    static_node_feat = torch.zeros((n_nodes, static_dim), dtype=torch.float32, device=device)
    for df in [train_df, val_df, test_df]:
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
        v_keys = events_df["v"].values if iteration >= 4 else None
        kinds = events_df["kind"].values if iteration >= 4 else None
        # Update memory in mini-batches along chronological order
        batch_size = 5000
        n_events = len(events_df)
        for b_start in range(0, n_events, batch_size):
            b_end = min(n_events, b_start + batch_size)
            if iteration >= 4:
                sub_u = u_keys[b_start:b_end]
                sub_v = v_keys[b_start:b_end]
                sub_k = kinds[b_start:b_end]
                sub_feat = ev_feat[b_start:b_end]

                batch_nodes = []
                batch_feat_idx = []
                for i, (uk, vk, kd) in enumerate(zip(sub_u, sub_v, sub_k)):
                    if uk in key_to_id:
                        batch_nodes.append(key_to_id[uk])
                        batch_feat_idx.append(i)
                    if kd == "link" and vk in key_to_id and vk != uk:
                        batch_nodes.append(key_to_id[vk])
                        batch_feat_idx.append(i)

                if not batch_nodes:
                    continue

                feat_tensor = torch.tensor(sub_feat[batch_feat_idx], dtype=torch.float32, device=device)
                messages = F.relu(msg_proj(feat_tensor))
                unique_nodes, inv_indices = np.unique(batch_nodes, return_inverse=True)
                u_nodes_tensor = torch.tensor(unique_nodes, dtype=torch.long, device=device)

                node_messages = torch.zeros((len(unique_nodes), 64), dtype=torch.float32, device=device)
                node_messages.index_add_(0, torch.tensor(inv_indices, dtype=torch.long, device=device), messages)

                cur_mem = memory[u_nodes_tensor]
                memory[u_nodes_tensor] = memory_updater(node_messages, cur_mem)
            else:
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
    val_ids = [key_to_id[k] for k in val_df["issue_key"]]
    test_ids = [key_to_id[k] for k in test_df["issue_key"]]

    train_z = memory[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    val_z = memory[torch.tensor(val_ids, dtype=torch.long, device=device)].cpu().numpy()
    test_z = memory[torch.tensor(test_ids, dtype=torch.long, device=device)].cpu().numpy()

    # Lưu vector embedding z_i(t) ra disk để phục vụ Meta-Ranker
    np.save("z_tgn_train.npy", train_z)
    np.save("z_tgn_val.npy", val_z)
    np.save("z_tgn_test.npy", test_z)
    print(f"  • Saved TGN 128d embeddings: train {train_z.shape}, val {val_z.shape}, test {test_z.shape}")

    # 6. Huấn luyện Bottleneck & Criticality Prediction Head
    print(f"  • Training Dynamic Criticality Readout Head (Epochs: {epochs})...", flush=True)
    
    train_static = static_node_feat[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    val_static = static_node_feat[torch.tensor(val_ids, dtype=torch.long, device=device)].cpu().numpy()
    test_static = static_node_feat[torch.tensor(test_ids, dtype=torch.long, device=device)].cpu().numpy()

    X_train = np.hstack([train_z, train_static])
    X_val = np.hstack([val_z, val_static])
    X_test = np.hstack([test_z, test_static])

    y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
    p0_train = train_df["is_critical_p0"].values.astype(np.float32)

    # Ranking-aware compound loss
    def pairwise_margin_loss(margin: float = 0.15, weight: float = 0.20):
        def loss(pred, by, bp):
            l_mse = F.mse_loss(pred, by)
            pos = pred[bp == 1]
            neg = pred[bp == 0]
            if len(pos) > 0 and len(neg) > 0:
                n_pos, n_neg = len(pos), len(neg)
                n_s = min(200, n_pos * n_neg)
                idx_p = torch.randint(0, n_pos, (n_s,), device=pred.device)
                idx_n = torch.randint(0, n_neg, (n_s,), device=pred.device)
                l_rank = F.relu(margin - (pos[idx_p] - neg[idx_n])).mean()
            else:
                l_rank = torch.tensor(0.0, device=pred.device)
            return l_mse + weight * l_rank
        return loss

    rank_loss_fn = pairwise_margin_loss(margin=0.15, weight=0.20)

    train_dataset = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
        torch.tensor(p0_train, dtype=torch.float32)
    )

    def train_single_head(seed: int) -> tuple[np.ndarray, np.ndarray]:
        torch.manual_seed(seed)
        input_dim = X_train.shape[1]
        h = DynamicCriticalityHead(in_dim=input_dim, hidden_dim=64).to(device)
        opt = torch.optim.AdamW(h.parameters(), lr=1e-3, weight_decay=1e-4)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
        loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

        h.train()
        for ep in range(epochs):
            for bx, by, bp in loader:
                bx, by, bp = bx.to(device), by.to(device), bp.to(device)
                opt.zero_grad()
                pred = h(bx)
                if iteration >= 3:
                    loss = rank_loss_fn(pred, by, bp)
                else:
                    loss = F.mse_loss(pred, by)
                loss.backward()
                opt.step()
            sch.step()

        h.eval()
        with torch.no_grad():
            vp = h(torch.tensor(X_val, dtype=torch.float32, device=device)).cpu().numpy()
            tp = h(torch.tensor(X_test, dtype=torch.float32, device=device)).cpu().numpy()
        return vp, tp

    if iteration >= 4:
        # Multi-head ensemble for robust variance reduction on Out-of-Time Test Set
        print("  • Training 2-Head Ensemble (Seeds 45, 47) for Iteration 4...")
        vp1, tp1 = train_single_head(45)
        vp2, tp2 = train_single_head(47)
        val_pred_scores = 0.5 * vp1 + 0.5 * vp2
        test_pred_scores = 0.5 * tp1 + 0.5 * tp2
    else:
        val_pred_scores, test_pred_scores = train_single_head(42 + iteration)

    # Lưu predictions_val.csv
    pd.DataFrame({
        "issue_key": val_df["issue_key"].values,
        "pred_score": np.round(val_pred_scores, 6),
    }).to_csv("predictions_val.csv", index=False)
    print(f"  • Saved predictions to predictions_val.csv ({len(val_df):,} rows)")

    # Lưu predictions_test.csv
    pd.DataFrame({
        "issue_key": test_df["issue_key"].values,
        "pred_score": np.round(test_pred_scores, 6),
    }).to_csv("predictions_test.csv", index=False)
    print(f"  • Saved predictions to predictions_test.csv ({len(test_df):,} rows)")

    # 8. Chạy Immutable Evaluation Harness
    splits_to_eval = ["val", "test"] if split == "all" else [split]
    for sp in splits_to_eval:
        pred_f = f"predictions_{sp}.csv"
        cmd = (
            f".venv/bin/python evaluation_harness_criticality.py "
            f"--track Track3_TGN "
            f"--pred_file {pred_f} "
            f"--split {sp} "
            f"--iteration {iteration}"
        )
        print(f"\n  • Running Harness for {sp.upper()}: {cmd}")
        os.system(cmd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track 3: Temporal Graph Network Dynamic Specialist")
    parser.add_argument("--iteration", type=int, default=4, choices=[1, 2, 3, 4])
    parser.add_argument("--split", type=str, default="all", choices=["val", "test", "all"])
    parser.add_argument("--epochs", type=int, default=18)
    args = parser.parse_args()

    run_track3(iteration=args.iteration, split=args.split, epochs=args.epochs)
