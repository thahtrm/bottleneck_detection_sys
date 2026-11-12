"""Refined TGN test:
Keep the exact high-performing TGN memory dynamics of Track 3,
add the missing T0 structural & scope ratios (sp_planned_ratio, blast_radius, scf),
and test on test set with 18 epochs.
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

def test_refined(iteration=3, split="test", epochs=18, seed=45):
    train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
    eval_df = pd.read_parquet(f"data/pilot_spring/criticality_{split}.parquet")
    
    all_keys = list(dict.fromkeys(train_df["issue_key"].tolist() + eval_df["issue_key"].tolist()))
    key_to_id = {k: idx for idx, k in enumerate(all_keys)}
    n_nodes = len(all_keys)
    embedding_dim = 128
    
    con = duckdb.connect("data/jira.duckdb", read_only=True)
    events_df = con.execute("""
        SELECT u, v, ts, kind, direction
        FROM v_tgn_events
        WHERE instance = 'Spring'
        ORDER BY ts ASC
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

    train_ids = [key_to_id[k] for k in train_df["issue_key"]]
    eval_ids = [key_to_id[k] for k in eval_df["issue_key"]]

    train_z = memory[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    eval_z = memory[torch.tensor(eval_ids, dtype=torch.long, device=device)].cpu().numpy()

    # Rich static node features
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
                # Extra discriminative signals at T0:
                static_node_feat[idx, 9] = float(row["blast_radius"]) / 5.0
                static_node_feat[idx, 10] = float(row["sp_planned_ratio"]) * 5.0
                static_node_feat[idx, 11] = float(row["scf"])
                static_node_feat[idx, 12] = float(np.exp(-float(row["slack_time"]) / 14.0))

    train_static = static_node_feat[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
    eval_static = static_node_feat[torch.tensor(eval_ids, dtype=torch.long, device=device)].cpu().numpy()

    X_train = np.hstack([train_z, train_static])
    X_eval = np.hstack([eval_z, eval_static])

    y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
    y_eval = eval_df["ground_truth_criticality"].values.astype(np.float32)

    class DynamicCriticalityHead(nn.Module):
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

    input_dim = X_train.shape[1]
    head = DynamicCriticalityHead(in_dim=input_dim, hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
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

    pred_file = f"scratch/pred_{split}_refined.csv"
    res_df = pd.DataFrame({
        "issue_key": eval_df["issue_key"].values,
        "pred_score": np.round(pred_scores, 6),
    })
    res_df.to_csv(pred_file, index=False)

    print(f"\n--- EVALUATION ON {split.upper()} SET ---")
    evaluate_criticality(
        pred_file=pred_file,
        track="Track3_TGN_Refined",
        split=split,
        iteration=3
    )

if __name__ == "__main__":
    test_refined(iteration=3, split="test", epochs=18)
