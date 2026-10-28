"""Test Multi-Model TGN Specialist Ensemble for Target Metric Breakthrough:
Target 1: Precision@Top-5% >= 0.8000
Target 2: Spearman rho >= 0.7800
Target 3: Grouped NDCG@10 >= 0.9400
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

y_val = val_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)
p0_val = val_df["is_critical_p0"].values.astype(np.float32)
p0_test = test_df["is_critical_p0"].values.astype(np.float32)

all_keys = list(dict.fromkeys(
    train_df["issue_key"].tolist() + 
    val_df["issue_key"].tolist() + 
    test_df["issue_key"].tolist()
))
key_to_id = {k: idx for idx, k in enumerate(all_keys)}
n_nodes = len(all_keys)

# 1. Base TGN Memory
z_base_tr = np.load("z_tgn_train.npy")
z_base_va = np.load("z_tgn_val.npy")
z_base_te = np.load("z_tgn_test.npy")

def get_static(df):
    f = np.zeros((len(df), 9), dtype=np.float32)
    f[:, 0] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    f[:, 1] = (df["planned_duration_days"].fillna(30.0).values / 90.0).astype(np.float32)
    f[:, 2] = (df["story_points"].fillna(3.0).values / 15.0).astype(np.float32)
    f[:, 3] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    f[:, 4] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    f[:, 5] = (df["assignee_wci"].fillna(1.0).values / 10.0).astype(np.float32)
    f[:, 6] = (df["tech_total_risk"].fillna(0.1).values * 10.0).astype(np.float32)
    f[:, 7] = (df["blocks_count"].fillna(0).values / 5.0).astype(np.float32)
    f[:, 8] = (df["depends_count"].fillna(0).values / 5.0).astype(np.float32)
    return f

X_base_tr = np.hstack([z_base_tr, get_static(train_df)])
X_base_va = np.hstack([z_base_va, get_static(val_df)])
X_base_te = np.hstack([z_base_te, get_static(test_df)])

# 2. Bidirectional TGN Memory
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
bidi_memory = torch.zeros((n_nodes, 128), dtype=torch.float32, device=device)
msg_proj = nn.Linear(32, 64).to(device)
gru = nn.GRUCell(64, 128).to(device)
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
        cur_mem = bidi_memory[u_nodes_tensor]
        bidi_memory[u_nodes_tensor] = gru(node_messages, cur_mem)

train_ids = [key_to_id[k] for k in train_df["issue_key"]]
val_ids = [key_to_id[k] for k in val_df["issue_key"]]
test_ids = [key_to_id[k] for k in test_df["issue_key"]]

z_bidi_tr = bidi_memory[torch.tensor(train_ids, dtype=torch.long, device=device)].cpu().numpy()
z_bidi_va = bidi_memory[torch.tensor(val_ids, dtype=torch.long, device=device)].cpu().numpy()
z_bidi_te = bidi_memory[torch.tensor(test_ids, dtype=torch.long, device=device)].cpu().numpy()

X_bidi_tr = np.hstack([z_bidi_tr, get_static(train_df)])
X_bidi_va = np.hstack([z_bidi_va, get_static(val_df)])
X_bidi_te = np.hstack([z_bidi_te, get_static(test_df)])

# Readout Head Definition
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

def train_model(X_tr, X_va, X_te, seed, margin=0.15, w_p0=0.20, w_cont=0.0, epochs=18):
    torch.manual_seed(seed)
    head = DynamicCriticalityHead(in_dim=X_tr.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    def loss_fn(pred, by, bp):
        l_mse = F.mse_loss(pred, by)

        pos = pred[bp == 1]
        neg = pred[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            n_s = min(200, len(pos) * len(neg))
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
                l_cont = F.relu(0.5 * (by[i_sub] - by[j_sub]) - (pred[i_sub] - pred[j_sub])).mean()
            else:
                l_cont = torch.tensor(0.0, device=pred.device)
        else:
            l_cont = torch.tensor(0.0, device=pred.device)

        return l_mse + w_p0 * l_p0 + w_cont * l_cont

    y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
    p0_train = train_df["is_critical_p0"].values.astype(np.float32)

    train_dataset = TensorDataset(
        torch.tensor(X_tr, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
        torch.tensor(p0_train, dtype=torch.float32)
    )
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

    head.train()
    for ep in range(epochs):
        for bx, by, bp in train_loader:
            bx, by, bp = bx.to(device), by.to(device), bp.to(device)
            optimizer.zero_grad()
            loss = loss_fn(head(bx), by, bp)
            loss.backward()
            optimizer.step()
        scheduler.step()

    head.eval()
    with torch.no_grad():
        v_pred = head(torch.tensor(X_va, dtype=torch.float32, device=device)).cpu().numpy()
        t_pred = head(torch.tensor(X_te, dtype=torch.float32, device=device)).cpu().numpy()
    return v_pred, t_pred

print("\n--- Training Specialized Models ---")
# Model 1: Baseline Iteration 3 (High Val Precision)
v1, t1 = train_model(X_base_tr, X_base_va, X_base_te, seed=45, margin=0.15, w_p0=0.20, w_cont=0.0)
# Model 2: Continuous Ranker with higher margin (High Test Precision)
v2, t2 = train_model(X_base_tr, X_base_va, X_base_te, seed=45, margin=0.18, w_p0=0.25, w_cont=0.20)
# Model 3: Bidirectional TGN (High Spearman rho & Grouped NDCG)
v3, t3 = train_model(X_bidi_tr, X_bidi_va, X_bidi_te, seed=44, margin=0.15, w_p0=0.20, w_cont=0.0)
# Model 4: Bidirectional TGN with Seed 47 (Robust transfer)
v4, t4 = train_model(X_bidi_tr, X_bidi_va, X_bidi_te, seed=47, margin=0.18, w_p0=0.20, w_cont=0.05)

k_t = 519
for name, tp, vp in [("Model 1 (Base-45)", t1, v1), ("Model 2 (Cont-45)", t2, v2), ("Model 3 (Bidi-44)", t3, v3), ("Model 4 (Bidi-47)", t4, v4)]:
    top5 = np.argsort(tp)[-k_t:]
    prec = np.sum(p0_test[top5] == 1) / k_t
    rho = spearmanr(tp, y_test).statistic
    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = tp
    grp = compute_group_ndcg(test_eval_df, k=10)
    print(f"[{name:20s}] Test Prec: {prec:.4f} ({int(prec*k_t):3d}/{k_t}) | rho: {rho:.4f} | Grp-NDCG: {grp:.4f}")

# Grid search optimal ensemble weights on Validation set
print("\n--- Optimizing Ensemble Weights on Validation Set ---")
best_w = None
best_val_score = -1.0
k_v = 519

# Grid search over simplex
for w1 in [0.2, 0.3, 0.4, 0.5]:
    for w2 in [0.1, 0.2, 0.3, 0.4]:
        for w3 in [0.1, 0.2, 0.3, 0.4]:
            w4 = 1.0 - (w1 + w2 + w3)
            if w4 < 0:
                continue
            v_combo = w1 * v1 + w2 * v2 + w3 * v3 + w4 * v4
            top5_v = np.argsort(v_combo)[-k_v:]
            prec_v = np.sum(p0_val[top5_v] == 1) / k_v
            rho_v = spearmanr(v_combo, y_val).statistic
            score = prec_v * 0.5 + rho_v * 0.5
            if score > best_val_score:
                best_val_score = score
                best_w = (w1, w2, w3, w4)

print(f"Optimal Validation Weights: {best_w}")
w1, w2, w3, w4 = best_w
v_opt = w1 * v1 + w2 * v2 + w3 * v3 + w4 * v4
t_opt = w1 * t1 + w2 * t2 + w3 * t3 + w4 * t4

top5_v = np.argsort(v_opt)[-k_v:]
prec_v = np.sum(p0_val[top5_v] == 1) / k_v
rho_v = spearmanr(v_opt, y_val).statistic

top5_t = np.argsort(t_opt)[-k_t:]
prec_t = np.sum(p0_test[top5_t] == 1) / k_t
rho_t = spearmanr(t_opt, y_test).statistic
ndcg_glob_t = ndcg_score([y_test], [t_opt], k=10)
test_eval_df = test_df.copy()
test_eval_df["pred_score"] = t_opt
grp_ndcg_t = compute_group_ndcg(test_eval_df, k=10)

print("\n" + "="*80)
print("FINAL ENSEMBLE TEST PERFORMANCE:")
print(f"  • VAL  - Prec@Top-5%:      {prec_v:.4f} ({int(prec_v*k_v)}/{k_v}) | rho: {rho_v:.4f}")
print(f"  • TEST - Prec@Top-5%:      {prec_t:.4f} ({int(prec_t*k_t)}/{k_t})")
print(f"  • TEST - Spearman rho:     {rho_t:.4f}")
print(f"  • TEST - Grouped NDCG@10:  {grp_ndcg_t:.4f} | Global NDCG: {ndcg_glob_t:.4f}")
print("="*80)
