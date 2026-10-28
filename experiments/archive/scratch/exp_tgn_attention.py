"""Experiment: TGN with Temporal Dependency Graph Attention and Rich T0 Features.
"""
import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from evaluation_harness_criticality import evaluate_criticality

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", device)

def run_experiment(split="test", epochs=18, lr=1e-3, weight_decay=1e-4, seed=42):
    train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
    eval_df = pd.read_parquet(f"data/pilot_spring/criticality_{split}.parquet")
    
    all_keys = list(dict.fromkeys(train_df["issue_key"].tolist() + eval_df["issue_key"].tolist()))
    key_to_id = {k: idx for idx, k in enumerate(all_keys)}
    n_nodes = len(all_keys)
    embedding_dim = 128
    
    # 1. Load events
    con = duckdb.connect("data/jira.duckdb", read_only=True)
    events_df = con.execute("""
        SELECT u, v, ts, kind, direction
        FROM v_tgn_events
        WHERE instance = 'Spring'
        ORDER BY ts ASC
    """).df()
    
    # Also load links for graph attention
    links_df = con.execute("""
        SELECT source_key, target_key, link_type_std
        FROM issue_links
        WHERE instance = 'Spring'
    """).df()
    con.close()
    
    kind_ser = events_df["kind"].values
    ev_feat = np.zeros((len(events_df), 8), dtype=np.float32)
    ev_feat[:, 0] = (kind_ser == "status").astype(np.float32)
    ev_feat[:, 1] = (kind_ser == "assignee").astype(np.float32)
    ev_feat[:, 2] = (kind_ser == "comment").astype(np.float32)
    ev_feat[:, 3] = (kind_ser == "priority").astype(np.float32)
    ev_feat[:, 4] = (kind_ser == "link").astype(np.float32)
    ev_feat[:, 5] = events_df["direction"].fillna(0).values.astype(np.float32)
    ts_arr = events_df["ts"].values
    dt = np.diff(ts_arr, prepend=ts_arr[0])
    ev_feat[:, 6] = np.log1p(np.maximum(0.0, dt / 3600.0)).astype(np.float32)
    ev_feat[:, 7] = 1.0

    torch.manual_seed(seed)
    memory = torch.zeros((n_nodes, embedding_dim), dtype=torch.float32, device=device)
    msg_proj = nn.Linear(8, 64).to(device)
    gru = nn.GRUCell(64, embedding_dim).to(device)

    msg_proj.eval()
    gru.eval()
    with torch.no_grad():
        u_keys = events_df["u"].values
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
            
            node_messages = torch.zeros((len(unique_nodes), 64), dtype=torch.float32, device=device)
            node_messages.index_add_(0, torch.tensor(inv_indices, dtype=torch.long, device=device), messages)
            
            cur_mem = memory[u_nodes_tensor]
            new_mem = gru(node_messages, cur_mem)
            memory[u_nodes_tensor] = new_mem

    # 2. Build Dependency Adjacency for Graph Attention
    # Map link types to ids
    link_type_map = {"Depend": 0, "Relate": 1, "Duplicate": 2, "Supercede": 3}
    adj_list = {i: [] for i in range(n_nodes)}
    for _, r in links_df.iterrows():
        s, t, lt = r["source_key"], r["target_key"], r["link_type_std"]
        if s in key_to_id and t in key_to_id:
            s_id = key_to_id[s]
            t_id = key_to_id[t]
            l_code = link_type_map.get(lt, 1)
            adj_list[s_id].append((t_id, l_code))
            adj_list[t_id].append((s_id, l_code))

    # Graph Attention aggregation layer
    class TemporalGraphAttention(nn.Module):
        def __init__(self, embed_dim=128, edge_dim=16, n_heads=4):
            super().__init__()
            self.embed_dim = embed_dim
            self.edge_emb = nn.Embedding(4, edge_dim)
            self.mha = nn.MultiheadAttention(embed_dim=embed_dim, kdim=embed_dim + edge_dim,
                                             vdim=embed_dim + edge_dim, num_heads=n_heads, batch_first=True)
            self.ln = nn.LayerNorm(embed_dim)

        def forward(self, node_ids: torch.Tensor, all_memory: torch.Tensor, max_neighbors=8):
            batch_size = len(node_ids)
            queries = all_memory[node_ids].unsqueeze(1) # [B, 1, D]
            
            # Construct neighbor keys and values
            keys_list = []
            masks = []
            for nid in node_ids.cpu().numpy():
                nbrs = adj_list[nid][:max_neighbors]
                if nbrs:
                    n_ids = [nb[0] for nb in nbrs]
                    l_codes = [nb[1] for nb in nbrs]
                    n_mem = all_memory[torch.tensor(n_ids, device=all_memory.device)]
                    e_emb = self.edge_emb(torch.tensor(l_codes, device=all_memory.device))
                    kv = torch.cat([n_mem, e_emb], dim=-1)
                    # Pad to max_neighbors
                    if len(nbrs) < max_neighbors:
                        pad = torch.zeros((max_neighbors - len(nbrs), kv.shape[1]), device=all_memory.device)
                        kv = torch.cat([kv, pad], dim=0)
                        mask = [False] * len(nbrs) + [True] * (max_neighbors - len(nbrs))
                    else:
                        mask = [False] * max_neighbors
                else:
                    kv = torch.zeros((max_neighbors, self.embed_dim + 16), device=all_memory.device)
                    mask = [True] * max_neighbors
                keys_list.append(kv)
                masks.append(mask)

            keys_tensor = torch.stack(keys_list, dim=0) # [B, K, D+E]
            mask_tensor = torch.tensor(masks, dtype=torch.bool, device=all_memory.device) # [B, K]
            
            # If all are masked in a row, unmask first to prevent NaN in softmax
            all_masked = mask_tensor.all(dim=1)
            mask_tensor[all_masked, 0] = False
            
            attn_out, _ = self.mha(queries, keys_tensor, keys_tensor, key_padding_mask=mask_tensor)
            # If was originally all masked, zero out the attention output
            attn_out[all_masked] = 0.0
            
            out = self.ln(queries.squeeze(1) + attn_out.squeeze(1))
            return out

    # Compute attention-enhanced embeddings
    print("Computing Temporal Graph Attention embeddings...")
    gat = TemporalGraphAttention(embed_dim=128, edge_dim=16, n_heads=4).to(device)
    gat.eval()
    
    train_ids = [key_to_id[k] for k in train_df["issue_key"]]
    eval_ids = [key_to_id[k] for k in eval_df["issue_key"]]

    with torch.no_grad():
        def batch_gat(ids_list, bsize=2048):
            res = []
            for i in range(0, len(ids_list), bsize):
                b_ids = torch.tensor(ids_list[i:i+bsize], dtype=torch.long, device=device)
                b_z = gat(b_ids, memory)
                res.append(b_z.cpu())
            return torch.cat(res, dim=0).numpy()

        train_z = batch_gat(train_ids)
        eval_z = batch_gat(eval_ids)

    print(f"Extracted GAT Embeddings: train_z={train_z.shape}, eval_z={eval_z.shape}")

    # 3. Rich 16 Static Features
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
                static_node_feat[idx, 9] = float(row["blast_radius"]) / 5.0
                static_node_feat[idx, 10] = float(row["sp_planned_ratio"]) * 5.0
                static_node_feat[idx, 11] = float(row["scf"])
                static_node_feat[idx, 12] = float(row["inverted_pagerank"]) * 1000.0
                static_node_feat[idx, 13] = float(np.exp(-float(row["slack_time"]) / 14.0))
                static_node_feat[idx, 14] = float(row["assignee_active_count"]) / 10.0
                static_node_feat[idx, 15] = float(row["ambiguity_score"])

    train_static = static_node_feat[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    eval_static = static_node_feat[torch.tensor(eval_ids, dtype=torch.long, device=device)].cpu().numpy()

    X_train = np.hstack([train_z, train_static])
    X_eval = np.hstack([eval_z, eval_static])

    y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
    y_eval = eval_df["ground_truth_criticality"].values.astype(np.float32)

    # 4. Readout Head
    class CriticalityHead(nn.Module):
        def __init__(self, in_dim: int, hidden_dim: int = 64):
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

    head = CriticalityHead(in_dim=X_train.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.MSELoss()

    train_dataset = TensorDataset(torch.tensor(X_train, dtype=torch.float32), torch.tensor(y_train, dtype=torch.float32))
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

    head.train()
    for ep in range(epochs):
        for bx, by in train_loader:
            bx, by = bx.to(device), by.to(device)
            optimizer.zero_grad()
            pred = head(bx)
            loss = criterion(pred, by)
            loss.backward()
            optimizer.step()
        scheduler.step()

    head.eval()
    with torch.no_grad():
        eval_tensor = torch.tensor(X_eval, dtype=torch.float32, device=device)
        pred_scores = head(eval_tensor).cpu().numpy()

    pred_file = f"scratch/pred_{split}_gat.csv"
    res_df = pd.DataFrame({
        "issue_key": eval_df["issue_key"].values,
        "pred_score": np.round(pred_scores, 6),
    })
    res_df.to_csv(pred_file, index=False)

    print(f"\n--- EVALUATION ON {split.upper()} SET ---")
    evaluate_criticality(
        pred_file=pred_file,
        track="Track3_TGN_GAT",
        split=split,
        iteration=2
    )

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", type=str, default="test")
    parser.add_argument("--epochs", type=int, default=18)
    args = parser.parse_args()
    run_experiment(split=args.split, epochs=args.epochs)
