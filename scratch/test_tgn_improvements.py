import os
import sys
import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from evaluation_harness_criticality import evaluate_criticality

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Execution device:", device)

# 1. Read datasets
train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

# 2. Build complete entity map (issues + devs)
con = duckdb.connect("data/jira.duckdb", read_only=True)
events_df = con.execute("""
    SELECT u, v, ts, kind, direction
    FROM v_tgn_events
    WHERE instance = 'Spring'
    ORDER BY ts ASC
""").df()
con.close()

all_u = events_df["u"].dropna().tolist()
all_v = events_df["v"].dropna().tolist()
all_keys = list(dict.fromkeys(
    train_df["issue_key"].tolist() + 
    val_df["issue_key"].tolist() + 
    test_df["issue_key"].tolist() + 
    all_u + all_v
))
key_to_id = {k: idx for idx, k in enumerate(all_keys)}
n_nodes = len(all_keys)
embedding_dim = 128
print(f"Total distinct nodes (issues + devs): {n_nodes:,}")

# 3. Encode event features (8d)
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

# 4. Bidirectional Memory Updater
class TemporalMemoryUpdater(nn.Module):
    def __init__(self, memory_dim: int = 128, message_dim: int = 64):
        super().__init__()
        self.gru = nn.GRUCell(message_dim, memory_dim)

    def forward(self, message: torch.Tensor, memory: torch.Tensor) -> torch.Tensor:
        return self.gru(message, memory)

torch.manual_seed(42)
memory = torch.zeros((n_nodes, embedding_dim), dtype=torch.float32, device=device)
msg_proj = nn.Linear(8, 64).to(device)
memory_updater = TemporalMemoryUpdater(memory_dim=embedding_dim, message_dim=64).to(device)

msg_proj.eval()
memory_updater.eval()

print("Simulating bidirectional continuous memory updates...")
with torch.no_grad():
    u_keys = events_df["u"].values
    v_keys = events_df["v"].values
    batch_size = 5000
    n_events = len(events_df)
    for b_start in range(0, n_events, batch_size):
        b_end = min(n_events, b_start + batch_size)
        
        # Collect updates for both u and v
        batch_nodes = []
        batch_feat_idx = []
        for i, (uk, vk) in enumerate(zip(u_keys[b_start:b_end], v_keys[b_start:b_end])):
            if uk in key_to_id:
                batch_nodes.append(key_to_id[uk])
                batch_feat_idx.append(b_start + i)
            if vk in key_to_id and vk != uk:
                batch_nodes.append(key_to_id[vk])
                batch_feat_idx.append(b_start + i)
                
        if not batch_nodes:
            continue
            
        feat_tensor = torch.tensor(ev_feat[batch_feat_idx], dtype=torch.float32, device=device)
        messages = F.relu(msg_proj(feat_tensor))
        
        unique_nodes, inv_indices = np.unique(batch_nodes, return_inverse=True)
        u_nodes_tensor = torch.tensor(unique_nodes, dtype=torch.long, device=device)
        
        node_messages = torch.zeros((len(unique_nodes), 64), dtype=torch.float32, device=device)
        node_messages.index_add_(0, torch.tensor(inv_indices, dtype=torch.long, device=device), messages)
        
        cur_mem = memory[u_nodes_tensor]
        new_mem = memory_updater(node_messages, cur_mem)
        memory[u_nodes_tensor] = new_mem

print("Memory simulation completed.")

# 5. Extract 16 Rich Static Features at T0
def extract_static_features(df):
    feats = np.zeros((len(df), 16), dtype=np.float32)
    feats[:, 0] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    feats[:, 1] = np.clip(df["planned_duration_days"].fillna(30.0).values / 90.0, 0, 5.0).astype(np.float32)
    feats[:, 2] = np.clip(df["story_points"].fillna(3.0).values / 15.0, 0, 5.0).astype(np.float32)
    feats[:, 3] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    feats[:, 4] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    feats[:, 5] = np.clip(df["assignee_wci"].fillna(1.0).values / 10.0, 0, 5.0).astype(np.float32)
    feats[:, 6] = np.clip(df["tech_total_risk"].fillna(0.1).values * 10.0, 0, 5.0).astype(np.float32)
    feats[:, 7] = np.clip(df["blocks_count"].fillna(0).values / 5.0, 0, 10.0).astype(np.float32)
    feats[:, 8] = np.clip(df["depends_count"].fillna(0).values / 5.0, 0, 10.0).astype(np.float32)
    feats[:, 9] = np.clip(df["scf"].fillna(1.0).values / 3.0, 0, 5.0).astype(np.float32)
    feats[:, 10] = np.clip(df["sp_planned_ratio"].fillna(0.1).values * 5.0, 0, 5.0).astype(np.float32)
    feats[:, 11] = np.clip(df["assignee_active_count"].fillna(1).values / 10.0, 0, 5.0).astype(np.float32)
    feats[:, 12] = np.clip(df["project_active_count"].fillna(10).values / 100.0, 0, 5.0).astype(np.float32)
    feats[:, 13] = df["is_unassigned"].fillna(0).values.astype(np.float32)
    feats[:, 14] = df["ambiguity_score"].fillna(0.0).values.astype(np.float32)
    feats[:, 15] = df["tech_concurrency_risk"].fillna(0.0).values.astype(np.float32)
    return feats

# 6. Build combined input representation (z_u + z_assignee + static_16)
def get_features(df):
    u_ids = [key_to_id[k] for k in df["issue_key"]]
    z_u = memory[torch.tensor(u_ids, dtype=torch.long, device=device)].cpu().numpy()
    
    # Also fetch assignee dynamic memory if available
    assignee_ids = [key_to_id.get(str(a), u_ids[i]) for i, a in enumerate(df["assignee"])]
    z_ass = memory[torch.tensor(assignee_ids, dtype=torch.long, device=device)].cpu().numpy()
    
    static_feats = extract_static_features(df)
    return np.hstack([z_u, z_ass, static_feats])

print("Building feature tensors...")
X_train = get_features(train_df)
X_val = get_features(val_df)
X_test = get_features(test_df)

y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
y_val = val_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_train = train_df["is_critical_p0"].values.astype(np.float32)
p0_val = val_df["is_critical_p0"].values.astype(np.float32)
p0_test = test_df["is_critical_p0"].values.astype(np.float32)

print(f"X_train: {X_train.shape}, X_val: {X_val.shape}, X_test: {X_test.shape}")

# 7. Deep Multi-Task & Ranking-Aware Head
class AdvancedCriticalityHead(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int = 128):
        super().__init__()
        self.fc1 = nn.Linear(in_dim, hidden_dim)
        self.bn1 = nn.BatchNorm1d(hidden_dim)
        self.act1 = nn.GELU()
        self.drop1 = nn.Dropout(0.2)
        
        self.fc2 = nn.Linear(hidden_dim, 64)
        self.bn2 = nn.BatchNorm1d(64)
        self.act2 = nn.GELU()
        self.drop2 = nn.Dropout(0.15)
        
        self.fc_crit = nn.Linear(64, 1)   # continuous score [0, 1]
        self.fc_p0 = nn.Linear(64, 1)     # binary logit for P0

    def forward(self, x: torch.Tensor):
        h = self.drop1(self.act1(self.bn1(self.fc1(x))))
        h = self.drop2(self.act2(self.bn2(self.fc2(h))))
        crit = torch.sigmoid(self.fc_crit(h)).squeeze(-1)
        p0_logit = self.fc_p0(h).squeeze(-1)
        return crit, p0_logit

# Compound Ranking Loss
class CompoundRankingLoss(nn.Module):
    def __init__(self, margin: float = 0.25, pos_weight: float = 4.0):
        super().__init__()
        self.mse = nn.MSELoss()
        self.bce = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight]))
        self.margin = margin

    def forward(self, pred_crit, p0_logit, target_crit, target_p0):
        # 1. MSE Loss
        l_mse = self.mse(pred_crit, target_crit)
        
        # 2. Weighted BCE for P0 alerts
        self.bce.pos_weight = self.bce.pos_weight.to(pred_crit.device)
        l_bce = self.bce(p0_logit, target_p0)
        
        # 3. Pairwise Margin Ranking between P0 positive and negative tasks
        pos_mask = (target_p0 == 1)
        neg_mask = (target_p0 == 0)
        if pos_mask.sum() > 0 and neg_mask.sum() > 0:
            pos_preds = pred_crit[pos_mask]
            neg_preds = pred_crit[neg_mask]
            
            n_pos = len(pos_preds)
            n_neg = len(neg_preds)
            n_sample = min(400, n_pos * n_neg)
            idx_pos = torch.randint(0, n_pos, (n_sample,), device=pred_crit.device)
            idx_neg = torch.randint(0, n_neg, (n_sample,), device=pred_crit.device)
            
            l_rank = torch.clamp(self.margin - (pos_preds[idx_pos] - neg_preds[idx_neg]), min=0.0).mean()
        else:
            l_rank = torch.tensor(0.0, device=pred_crit.device)
            
        return l_mse + 0.3 * l_bce + 0.4 * l_rank

# Train
epochs = 18
input_dim = X_train.shape[1]
head = AdvancedCriticalityHead(in_dim=input_dim, hidden_dim=128).to(device)
criterion = CompoundRankingLoss(margin=0.25, pos_weight=4.0)
optimizer = torch.optim.AdamW(head.parameters(), lr=1.5e-3, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

train_dataset = TensorDataset(
    torch.tensor(X_train, dtype=torch.float32),
    torch.tensor(y_train, dtype=torch.float32),
    torch.tensor(p0_train, dtype=torch.float32)
)
train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

print(f"Training Advanced Criticality Head ({epochs} epochs)...")
head.train()
for ep in range(epochs):
    total_loss = 0.0
    for bx, by_crit, by_p0 in train_loader:
        bx, by_crit, by_p0 = bx.to(device), by_crit.to(device), by_p0.to(device)
        optimizer.zero_grad()
        p_crit, p_logit = head(bx)
        loss = criterion(p_crit, p_logit, by_crit, by_p0)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * len(bx)
    scheduler.step()
    if (ep + 1) % 6 == 0 or ep == epochs - 1:
        print(f"  Epoch {ep+1:02d}/{epochs}: Loss = {total_loss/len(train_dataset):.4f}")

# Evaluation
head.eval()
with torch.no_grad():
    val_crit, val_p0_logit = head(torch.tensor(X_val, dtype=torch.float32, device=device))
    test_crit, test_p0_logit = head(torch.tensor(X_test, dtype=torch.float32, device=device))
    
    # Combined score: continuous criticality + sigmoid(p0_logit)
    val_pred = (val_crit * 0.7 + torch.sigmoid(val_p0_logit) * 0.3).cpu().numpy()
    test_pred = (test_crit * 0.7 + torch.sigmoid(test_p0_logit) * 0.3).cpu().numpy()

# Save temp files and test harness
val_res = pd.DataFrame({"issue_key": val_df["issue_key"].values, "pred_score": np.round(val_pred, 6)})
val_res.to_csv("scratch/pred_val_test.csv", index=False)

test_res = pd.DataFrame({"issue_key": test_df["issue_key"].values, "pred_score": np.round(test_pred, 6)})
test_res.to_csv("scratch/pred_test_test.csv", index=False)

print("\n--- EVALUATION ON VALIDATION SET ---")
evaluate_criticality(
    pred_file="scratch/pred_val_test.csv",
    track="Track3_TGN_Iter2_Draft",
    split="val",
    iteration=2
)

print("\n--- EVALUATION ON OUT-OF-TIME TEST SET ---")
evaluate_criticality(
    pred_file="scratch/pred_test_test.csv",
    track="Track3_TGN_Iter2_Draft",
    split="test",
    iteration=2
)
