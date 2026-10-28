"""Experiment Vector 2: End-to-End Causal Temporal Graph Attention (GAT) on CTDG.
Implements:
1. Causal Graph Attention:
   - Queries: Q = [s_u(T0) || phi(0)] (144d)
   - Keys/Values: K, V = [s_v(T0) || e_uv || phi(T0 - t_uv)] (149d)
   - Only causal neighbors with t_uv <= T0 (Zero Temporal Leakage)
   - 4-head Multihead Attention trained END-TO-END with gradients
2. Residual & LayerNorm skip connection:
   z_gat = LayerNorm(s_u(T0) + MHA(Q, K, V))
3. Readout Head with Compound Ranking Loss.
"""
import sys
sys.path.insert(0, ".")
import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score
from evaluation_harness_criticality import compute_group_ndcg

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", device)

# 1. Load Parquets
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
print(f"Total nodes: {n_nodes:,}")

# 2. Load TGN Dynamic Embeddings
z_train = np.load("z_tgn_train.npy")
z_val = np.load("z_tgn_val.npy")
z_test = np.load("z_tgn_test.npy")

# Store full node memory in tensor
full_memory = np.zeros((n_nodes, 128), dtype=np.float32)
for idx, k in enumerate(train_df["issue_key"]):
    full_memory[key_to_id[k]] = z_train[idx]
for idx, k in enumerate(val_df["issue_key"]):
    full_memory[key_to_id[k]] = z_val[idx]
for idx, k in enumerate(test_df["issue_key"]):
    full_memory[key_to_id[k]] = z_test[idx]

full_memory_tensor = torch.tensor(full_memory, dtype=torch.float32, device=device)

# 3. Load Issue Links and build Causal Neighbor Index
con = duckdb.connect("data/jira.duckdb", read_only=True)
links_df = con.execute("""
    SELECT source_key, target_key, approx_ts, link_type_std, direction 
    FROM issue_links 
    WHERE instance = 'Spring'
""").df()
con.close()

# Create created_ts lookup
all_created = {}
for df in [train_df, val_df, test_df]:
    for k, ts in zip(df["issue_key"], df["created_ts"]):
        all_created[k] = ts

link_type_map = {"Depend": 0, "Relate": 1, "Duplicate": 2, "Supercede": 3}

# Build adjacency lists strictly satisfying causality t_link <= T0_u
causal_adj = {i: [] for i in range(n_nodes)}
for _, row in links_df.iterrows():
    s = row["source_key"]
    t = row["target_key"]
    lt = row["link_type_std"]
    l_code = link_type_map.get(lt, 1)
    l_ts = float(row["approx_ts"]) if pd.notna(row["approx_ts"]) else 0.0

    if s in key_to_id and t in key_to_id:
        s_id = key_to_id[s]
        t_id = key_to_id[t]
        s_t0 = all_created.get(s, float("inf"))
        t_t0 = all_created.get(t, float("inf"))

        # From s looking at t (s depends on t or relates to t)
        if l_ts <= s_t0:
            dt_s = max(0.0, (s_t0 - l_ts) / 3600.0) # hours
            causal_adj[s_id].append((t_id, l_code, 1.0, dt_s))

        # From t looking at s (t is blocked by / blocks s)
        if l_ts <= t_t0:
            dt_t = max(0.0, (t_t0 - l_ts) / 3600.0)
            causal_adj[t_id].append((s_id, l_code, -1.0, dt_t))

# 4. Construct Fixed-Sized Neighbor Tensors for Fast Batching
MAX_NEIGHBORS = 6
freqs = 1.0 / (10.0 ** np.linspace(0, 4, 8)) # 16d Fourier time encoding

def build_neighbor_arrays(df):
    N = len(df)
    n_ids = np.zeros((N, MAX_NEIGHBORS), dtype=np.int64)
    edge_feats = np.zeros((N, MAX_NEIGHBORS, 5), dtype=np.float32)
    time_encs = np.zeros((N, MAX_NEIGHBORS, 16), dtype=np.float32)
    masks = np.ones((N, MAX_NEIGHBORS), dtype=bool) # True = padded/masked

    for i, k in enumerate(df["issue_key"]):
        u_id = key_to_id[k]
        nbrs = causal_adj[u_id][:MAX_NEIGHBORS]
        for j, (v_id, l_code, direction, dt_h) in enumerate(nbrs):
            n_ids[i, j] = v_id
            masks[i, j] = False
            # Edge features: 4 one-hot link types + 1 direction
            edge_feats[i, j, l_code] = 1.0
            edge_feats[i, j, 4] = direction
            # Time encoding
            for fi, w in enumerate(freqs):
                time_encs[i, j, 2 * fi] = np.cos(w * dt_h)
                time_encs[i, j, 2 * fi + 1] = np.sin(w * dt_h)

    return n_ids, edge_feats, time_encs, masks

tr_n_ids, tr_e_feats, tr_t_encs, tr_masks = build_neighbor_arrays(train_df)
va_n_ids, va_e_feats, va_t_encs, va_masks = build_neighbor_arrays(val_df)
te_n_ids, te_e_feats, te_t_encs, te_masks = build_neighbor_arrays(test_df)

print(f"Constructed Causal Neighbor Arrays: {tr_n_ids.shape}")

# 5. Static Features
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

static_tr = get_static(train_df)
static_va = get_static(val_df)
static_te = get_static(test_df)

y_tr = train_df["ground_truth_criticality"].values.astype(np.float32)
y_va = val_df["ground_truth_criticality"].values.astype(np.float32)
y_te = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_tr = train_df["is_critical_p0"].values.astype(np.float32)
p0_va = val_df["is_critical_p0"].values.astype(np.float32)
p0_te = test_df["is_critical_p0"].values.astype(np.float32)

# 6. End-to-End Causal Temporal Graph Attention Architecture
class CausalTemporalGAT(nn.Module):
    def __init__(self, node_dim=128, edge_dim=5, time_dim=16, n_heads=4, static_dim=9):
        super().__init__()
        self.node_dim = node_dim
        self.query_dim = node_dim
        self.kv_dim = node_dim + edge_dim + time_dim # 128 + 5 + 16 = 149
        
        # Multi-head Attention
        self.mha = nn.MultiheadAttention(
            embed_dim=node_dim,
            kdim=self.kv_dim,
            vdim=self.kv_dim,
            num_heads=n_heads,
            dropout=0.1,
            batch_first=True
        )
        self.ln = nn.LayerNorm(node_dim)
        
        # Readout MLP Head
        head_in = node_dim + static_dim # 128 + 9 = 137
        self.fc1 = nn.Linear(head_in, 64)
        self.bn1 = nn.BatchNorm1d(64)
        self.dropout = nn.Dropout(0.2)
        self.fc2 = nn.Linear(64, 32)
        self.fc3 = nn.Linear(32, 1)

    def forward(self, s_u, n_ids, e_feats, t_encs, masks, static_feat):
        # s_u: [B, 128]
        # n_ids: [B, K]
        # e_feats: [B, K, 5]
        # t_encs: [B, K, 16]
        # masks: [B, K] bool
        # static_feat: [B, 9]

        queries = s_u.unsqueeze(1) # [B, 1, 128]
        nbr_mems = full_memory_tensor[n_ids] # [B, K, 128]
        kv = torch.cat([nbr_mems, e_feats, t_encs], dim=-1) # [B, K, 149]

        # Prevent all-masked NaNs
        all_masked = masks.all(dim=1)
        safe_mask = masks.clone()
        safe_mask[all_masked, 0] = False

        attn_out, _ = self.mha(queries, kv, kv, key_padding_mask=safe_mask) # [B, 1, 128]
        attn_out = attn_out.squeeze(1) # [B, 128]
        attn_out[all_masked] = 0.0

        # Residual skip connection & LayerNorm
        z_gat = self.ln(s_u + attn_out) # [B, 128]

        # Readout
        h = torch.cat([z_gat, static_feat], dim=-1)
        h = F.relu(self.bn1(self.fc1(h)))
        h = self.dropout(h)
        h = F.relu(self.fc2(h))
        out = torch.sigmoid(self.fc3(h)).squeeze(-1)
        return out

# PyTorch Dataset for batching
class GATDataset(Dataset):
    def __init__(self, s_u, n_ids, e_feats, t_encs, masks, static, y, p0):
        self.s_u = torch.tensor(s_u, dtype=torch.float32)
        self.n_ids = torch.tensor(n_ids, dtype=torch.long)
        self.e_feats = torch.tensor(e_feats, dtype=torch.float32)
        self.t_encs = torch.tensor(t_encs, dtype=torch.float32)
        self.masks = torch.tensor(masks, dtype=torch.bool)
        self.static = torch.tensor(static, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.p0 = torch.tensor(p0, dtype=torch.float32)

    def __len__(self):
        return len(self.s_u)

    def __getitem__(self, idx):
        return (
            self.s_u[idx], self.n_ids[idx], self.e_feats[idx],
            self.t_encs[idx], self.masks[idx], self.static[idx],
            self.y[idx], self.p0[idx]
        )

train_dataset = GATDataset(z_train, tr_n_ids, tr_e_feats, tr_t_encs, tr_masks, static_tr, y_tr, p0_tr)
train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

# 7. Train End-to-End with Compound Loss
torch.manual_seed(45)
gat_model = CausalTemporalGAT(node_dim=128, edge_dim=5, time_dim=16, n_heads=4, static_dim=9).to(device)
optimizer = torch.optim.AdamW(gat_model.parameters(), lr=1e-3, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=18)

def compound_loss(margin=0.18, weight_p0=0.25, weight_cont=0.20):
    def loss(pred, by, bp):
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

        B = len(pred)
        n_pairs = min(400, B * (B - 1) // 2)
        idx_i = torch.randint(0, B, (n_pairs,), device=pred.device)
        idx_j = torch.randint(0, B, (n_pairs,), device=pred.device)
        mask = by[idx_i] > by[idx_j]
        if mask.sum() > 0:
            i_sub = idx_i[mask]
            j_sub = idx_j[mask]
            l_cont = F.relu(0.5 * (by[i_sub] - by[j_sub]) - (pred[i_sub] - pred[j_sub])).mean()
        else:
            l_cont = torch.tensor(0.0, device=pred.device)

        return l_mse + weight_p0 * l_p0 + weight_cont * l_cont
    return loss

loss_fn = compound_loss(margin=0.18, weight_p0=0.25, weight_cont=0.20)

print("\n--- Training End-to-End Causal Temporal GAT (18 Epochs) ---")
gat_model.train()
for ep in range(18):
    for b_su, b_nid, b_ef, b_te, b_mask, b_stat, by, bp in train_loader:
        b_su = b_su.to(device)
        b_nid = b_nid.to(device)
        b_ef = b_ef.to(device)
        b_te = b_te.to(device)
        b_mask = b_mask.to(device)
        b_stat = b_stat.to(device)
        by = by.to(device)
        bp = bp.to(device)

        optimizer.zero_grad()
        pred = gat_model(b_su, b_nid, b_ef, b_te, b_mask, b_stat)
        loss = loss_fn(pred, by, bp)
        loss.backward()
        optimizer.step()
    scheduler.step()

# 8. Evaluation
gat_model.eval()
with torch.no_grad():
    def predict_split(s_u, n_ids, e_feats, t_encs, masks, static):
        preds = []
        bsize = 512
        for i in range(0, len(s_u), bsize):
            p = gat_model(
                torch.tensor(s_u[i:i+bsize], dtype=torch.float32, device=device),
                torch.tensor(n_ids[i:i+bsize], dtype=torch.long, device=device),
                torch.tensor(e_feats[i:i+bsize], dtype=torch.float32, device=device),
                torch.tensor(t_encs[i:i+bsize], dtype=torch.float32, device=device),
                torch.tensor(masks[i:i+bsize], dtype=torch.bool, device=device),
                torch.tensor(static[i:i+bsize], dtype=torch.float32, device=device),
            )
            preds.append(p.cpu())
        return torch.cat(preds, dim=0).numpy()

    v_pred = predict_split(z_val, va_n_ids, va_e_feats, va_t_encs, va_masks, static_va)
    t_pred = predict_split(z_test, te_n_ids, te_e_feats, te_t_encs, te_masks, static_te)

k_t = 519
t_top5 = np.argsort(t_pred)[-k_t:]
t_prec = np.sum(p0_te[t_top5] == 1) / k_t
t_rho = spearmanr(t_pred, y_te).statistic
test_eval_df = test_df.copy()
test_eval_df["pred_score"] = t_pred
t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)
t_ndcg_glob = ndcg_score([y_te], [t_pred], k=10)

k_v = 519
v_top5 = np.argsort(v_pred)[-k_v:]
v_prec = np.sum(p0_va[v_top5] == 1) / k_v
v_rho = spearmanr(v_pred, y_va).statistic

print("\n" + "="*80)
print("END-TO-END CAUSAL TEMPORAL GAT RESULTS:")
print(f"  • TEST Prec@Top5%:      {t_prec:.4f} ({int(t_prec*k_t)}/{k_t})")
print(f"  • TEST Spearman rho:    {t_rho:.4f}")
print(f"  • TEST Grouped NDCG@10: {t_ndcg_grp:.4f} | Global NDCG: {t_ndcg_glob:.4f}")
print(f"  • VAL Prec@Top5%:       {v_prec:.4f} ({int(v_prec*k_v)}/{k_v}) | VAL rho: {v_rho:.4f}")
print("="*80)
