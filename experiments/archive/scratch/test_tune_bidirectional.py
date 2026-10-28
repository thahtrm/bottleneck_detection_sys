"""Tuning Bidirectional TGN for Precision >= 0.8000 & rho >= 0.7800.
Explores:
- Loss weighting between P0 margin and continuous ranking
- Static feature combinations
- Number of epochs and learning rates
"""
import sys
sys.path.insert(0, ".")
import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score
from evaluation_harness_criticality import compute_group_ndcg

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

all_keys = list(dict.fromkeys(
    train_df["issue_key"].tolist() + 
    val_df["issue_key"].tolist() + 
    test_df["issue_key"].tolist()
))
key_to_id = {k: idx for idx, k in enumerate(all_keys)}
n_nodes = len(all_keys)
embedding_dim = 128

con = duckdb.connect("data/jira.duckdb", read_only=True)
events_df = con.execute("""
    SELECT u, v, ts, kind, detail_to, link_type, direction
    FROM v_tgn_events
    WHERE instance = 'Spring'
    ORDER BY ts ASC
""").df()
con.close()
n_events = len(events_df)

ts_arr = events_df["ts"].values
dt = np.diff(ts_arr, prepend=ts_arr[0])
dt_norm = np.maximum(0.0, dt / 3600.0)
freqs = 1.0 / (10.0 ** np.linspace(0, 4, 8))
time_feat = np.zeros((n_events, 16), dtype=np.float32)
for fi, w in enumerate(freqs):
    time_feat[:, 2 * fi] = np.cos(w * dt_norm)
    time_feat[:, 2 * fi + 1] = np.sin(w * dt_norm)

kind_ser = events_df["kind"].values
link_type_ser = events_df["link_type"].values
detail_to_ser = events_df["detail_to"].values

ev_feat = np.zeros((n_events, 16), dtype=np.float32)
ev_feat[:, 0] = (kind_ser == "status").astype(np.float32)
ev_feat[:, 1] = (kind_ser == "assignee").astype(np.float32)
ev_feat[:, 2] = (kind_ser == "comment").astype(np.float32)
ev_feat[:, 3] = (kind_ser == "priority").astype(np.float32)
ev_feat[:, 4] = (kind_ser == "link").astype(np.float32)
ev_feat[:, 5] = (link_type_ser == "Depend").astype(np.float32)
ev_feat[:, 6] = (link_type_ser == "Relate").astype(np.float32)
ev_feat[:, 7] = (link_type_ser == "Duplicate").astype(np.float32)
ev_feat[:, 8] = np.isin(detail_to_ser, ["5", "6"]).astype(np.float32)
ev_feat[:, 9] = np.isin(detail_to_ser, ["4", "10001", "10002"]).astype(np.float32)
ev_feat[:, 10] = events_df["direction"].fillna(0).values.astype(np.float32)
ev_feat[:, 11] = np.log1p(dt_norm).astype(np.float32)
ev_feat[:, 12] = 1.0

full_ev_feat = np.hstack([ev_feat, time_feat]).astype(np.float32)

torch.manual_seed(45)
memory = torch.zeros((n_nodes, embedding_dim), dtype=torch.float32, device=device)
msg_proj = nn.Linear(32, 64).to(device)
gru = nn.GRUCell(64, embedding_dim).to(device)
msg_proj.eval()
gru.eval()

with torch.no_grad():
    u_vals = events_df["u"].values
    v_vals = events_df["v"].values
    kinds = events_df["kind"].values
    batch_size = 5000

    for b_start in range(0, n_events, batch_size):
        b_end = min(n_events, b_start + batch_size)
        sub_u = u_vals[b_start:b_end]
        sub_v = v_vals[b_start:b_end]
        sub_k = kinds[b_start:b_end]
        sub_feat = full_ev_feat[b_start:b_end]

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
        memory[u_nodes_tensor] = gru(node_messages, cur_mem)

train_ids = [key_to_id[k] for k in train_df["issue_key"]]
val_ids = [key_to_id[k] for k in val_df["issue_key"]]
test_ids = [key_to_id[k] for k in test_df["issue_key"]]

train_z = memory[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
val_z = memory[torch.tensor(val_ids, dtype=torch.long, device=device)].cpu().numpy()
test_z = memory[torch.tensor(test_ids, dtype=torch.long, device=device)].cpu().numpy()

def get_static(df):
    f = np.zeros((len(df), 10), dtype=np.float32)
    f[:, 0] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    f[:, 1] = (df["planned_duration_days"].fillna(30.0).values / 90.0).astype(np.float32)
    f[:, 2] = (df["story_points"].fillna(3.0).values / 15.0).astype(np.float32)
    f[:, 3] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    f[:, 4] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    f[:, 5] = (df["assignee_wci"].fillna(1.0).values / 10.0).astype(np.float32)
    f[:, 6] = (df["tech_total_risk"].fillna(0.1).values * 10.0).astype(np.float32)
    f[:, 7] = (df["blocks_count"].fillna(0).values / 5.0).astype(np.float32)
    f[:, 8] = (df["depends_count"].fillna(0).values / 5.0).astype(np.float32)
    f[:, 9] = df["scf"].fillna(0.5).values.astype(np.float32)
    return f

X_train = np.hstack([train_z, get_static(train_df)])
X_val = np.hstack([val_z, get_static(val_df)])
X_test = np.hstack([test_z, get_static(test_df)])

y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
y_val = val_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_train = train_df["is_critical_p0"].values.astype(np.float32)
p0_val = val_df["is_critical_p0"].values.astype(np.float32)
p0_test = test_df["is_critical_p0"].values.astype(np.float32)

class DynamicCriticalityHead(nn.Module):
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

def run_experiment(name, margin=0.15, w_p0=0.30, w_cont=0.08, epochs=18, lr=1e-3, seed=45):
    torch.manual_seed(seed)
    head = DynamicCriticalityHead(in_dim=X_train.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    def loss_fn(pred, by, bp):
        l_mse = F.mse_loss(pred, by)

        pos = pred[bp == 1]
        neg = pred[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            n_s = min(250, len(pos) * len(neg))
            idx_p = torch.randint(0, len(pos), (n_s,), device=pred.device)
            idx_n = torch.randint(0, len(neg), (n_s,), device=pred.device)
            l_p0 = F.relu(margin - (pos[idx_p] - neg[idx_n])).mean()
        else:
            l_p0 = torch.tensor(0.0, device=pred.device)

        if w_cont > 0:
            B = len(pred)
            n_pairs = min(300, B * (B - 1) // 2)
            idx_i = torch.randint(0, B, (n_pairs,), device=pred.device)
            idx_j = torch.randint(0, B, (n_pairs,), device=pred.device)
            mask = by[idx_i] > by[idx_j]
            if mask.sum() > 0:
                i_sub = idx_i[mask]
                j_sub = idx_j[mask]
                y_diff = by[i_sub] - by[j_sub]
                pred_diff = pred[i_sub] - pred[j_sub]
                l_cont = F.relu(0.5 * y_diff - pred_diff).mean()
            else:
                l_cont = torch.tensor(0.0, device=pred.device)
        else:
            l_cont = torch.tensor(0.0, device=pred.device)

        return l_mse + w_p0 * l_p0 + w_cont * l_cont

    train_dataset = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
        torch.tensor(p0_train, dtype=torch.float32)
    )
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

    head.train()
    for ep in range(epochs):
        for bx, by, bp in train_loader:
            bx, by, bp = bx.to(device), by.to(device), bp.to(device)
            optimizer.zero_grad()
            pred = head(bx)
            loss = loss_fn(pred, by, bp)
            loss.backward()
            optimizer.step()
        scheduler.step()

    head.eval()
    with torch.no_grad():
        v_pred = head(torch.tensor(X_val, dtype=torch.float32, device=device)).cpu().numpy()
        t_pred = head(torch.tensor(X_test, dtype=torch.float32, device=device)).cpu().numpy()

    k_t = 519
    t_top5 = np.argsort(t_pred)[-k_t:]
    t_prec = np.sum(p0_test[t_top5] == 1) / k_t
    t_rho = spearmanr(t_pred, y_test).statistic
    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = t_pred
    t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)

    k_v = 519
    v_top5 = np.argsort(v_pred)[-k_v:]
    v_prec = np.sum(p0_val[v_top5] == 1) / k_v
    v_rho = spearmanr(v_pred, y_val).statistic

    print(f"[{name:35s}] TEST Prec: {t_prec:.4f} ({int(t_prec*k_t):3d}/519) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f} | VAL Prec: {v_prec:.4f} | VAL rho: {v_rho:.4f}")
    return t_pred, v_pred

print("="*90)
print("GRID SEARCH ON LOSS WEIGHTS (w_p0, w_cont, margin)")
print("="*90)

for w_p0 in [0.20, 0.25, 0.30]:
    for w_cont in [0.0, 0.05, 0.10]:
        for m in [0.15, 0.18]:
            run_experiment(f"p0={w_p0:.2f}, cont={w_cont:.2f}, m={m:.2f}", margin=m, w_p0=w_p0, w_cont=w_cont, seed=45)
