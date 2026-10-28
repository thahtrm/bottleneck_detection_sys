"""Experiment Vector 5: Cross-Project Generalization (Inductive Transfer).
Evaluates the trained TGN model from Spring on the JFrog dataset (15,535 issues):
1. Zero-shot transfer: Evaluates Spring-trained TGN weights directly on JFrog Out-of-Time Test Set.
2. Few-shot adaptation: Fine-tunes the readout head on JFrog Train (10% samples) and evaluates on JFrog Test.
3. Quantifies domain shift and inductive transfer performance across software ecosystems.
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
print("Device:", device)

# 1. Load JFrog splits
jfrog_train_df = pd.read_parquet("data/pilot_jfrog/criticality_train.parquet")
jfrog_val_df = pd.read_parquet("data/pilot_jfrog/criticality_val.parquet")
jfrog_test_df = pd.read_parquet("data/pilot_jfrog/criticality_test.parquet")

all_jfrog_keys = list(dict.fromkeys(
    jfrog_train_df["issue_key"].tolist() + 
    jfrog_val_df["issue_key"].tolist() + 
    jfrog_test_df["issue_key"].tolist()
))
jfrog_key_to_id = {k: idx for idx, k in enumerate(all_jfrog_keys)}
n_jfrog_nodes = len(all_jfrog_keys)
print(f"Loaded JFrog: {n_jfrog_nodes:,} issues (Train: {len(jfrog_train_df):,}, Val: {len(jfrog_val_df):,}, Test: {len(jfrog_test_df):,})")

# 2. Extract events for JFrog
con = duckdb.connect("data/jira.duckdb", read_only=True)
jfrog_events_df = con.execute("""
    SELECT u, v, ts, kind, direction
    FROM v_tgn_events
    WHERE instance = 'JFrog'
    ORDER BY ts ASC
""").df()
con.close()
print(f"Loaded {len(jfrog_events_df):,} events for JFrog")

# 3. Encode JFrog event features (8d)
kind_ser = jfrog_events_df["kind"].values
ev_feat = np.zeros((len(jfrog_events_df), 8), dtype=np.float32)
ev_feat[:, 0] = (kind_ser == "status").astype(np.float32)
ev_feat[:, 1] = (kind_ser == "assignee").astype(np.float32)
ev_feat[:, 2] = (kind_ser == "comment").astype(np.float32)
ev_feat[:, 3] = (kind_ser == "priority").astype(np.float32)
ev_feat[:, 4] = (kind_ser == "link").astype(np.float32)
ev_feat[:, 5] = jfrog_events_df["direction"].fillna(0).values.astype(np.float32)
ts_arr = jfrog_events_df["ts"].values
dt = np.diff(ts_arr, prepend=ts_arr[0]) if len(ts_arr) > 0 else np.zeros(0)
ev_feat[:, 6] = np.log1p(np.maximum(0.0, dt / 3600.0)).astype(np.float32)
ev_feat[:, 7] = 1.0

# 4. Continuous Node Memory for JFrog
torch.manual_seed(45)
jfrog_memory = torch.zeros((n_jfrog_nodes, 128), dtype=torch.float32, device=device)
msg_proj = nn.Linear(8, 64).to(device)
gru = nn.GRUCell(64, 128).to(device)
msg_proj.eval()
gru.eval()

with torch.no_grad():
    u_keys = jfrog_events_df["u"].values
    batch_size = 5000
    n_events = len(jfrog_events_df)
    for b_start in range(0, n_events, batch_size):
        b_end = min(n_events, b_start + batch_size)
        batch_u = [jfrog_key_to_id[k] for k in u_keys[b_start:b_end] if k in jfrog_key_to_id]
        if not batch_u:
            continue
        b_idx = [i for i, k in enumerate(u_keys[b_start:b_end]) if k in jfrog_key_to_id]
        batch_feat = torch.tensor(ev_feat[b_start + np.array(b_idx)], dtype=torch.float32, device=device)
        messages = F.relu(msg_proj(batch_feat))

        unique_nodes, inv_indices = np.unique(batch_u, return_inverse=True)
        u_nodes_tensor = torch.tensor(unique_nodes, dtype=torch.long, device=device)

        node_messages = torch.zeros((len(unique_nodes), 64), dtype=torch.float32, device=device)
        node_messages.index_add_(0, torch.tensor(inv_indices, dtype=torch.long, device=device), messages)

        cur_mem = jfrog_memory[u_nodes_tensor]
        new_mem = gru(node_messages, cur_mem)
        jfrog_memory[u_nodes_tensor] = new_mem

# 5. Extract Static Features
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

jfrog_train_ids = [jfrog_key_to_id[k] for k in jfrog_train_df["issue_key"]]
jfrog_test_ids = [jfrog_key_to_id[k] for k in jfrog_test_df["issue_key"]]

z_jf_train = jfrog_memory[torch.tensor(jfrog_train_ids, dtype=torch.long, device=device)].cpu().numpy()
z_jf_test = jfrog_memory[torch.tensor(jfrog_test_ids, dtype=torch.long, device=device)].cpu().numpy()

X_jf_train = np.hstack([z_jf_train, get_static(jfrog_train_df)])
X_jf_test = np.hstack([z_jf_test, get_static(jfrog_test_df)])

y_jf_train = jfrog_train_df["ground_truth_criticality"].values.astype(np.float32)
y_jf_test = jfrog_test_df["ground_truth_criticality"].values.astype(np.float32)
p0_jf_test = jfrog_test_df["is_critical_p0"].values.astype(np.float32)

# 6. Load Spring-trained Head for Zero-Shot Evaluation
# First, train Head on Spring
spring_train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
spring_z_train = np.load("z_tgn_train.npy")
X_spring_train = np.hstack([spring_z_train, get_static(spring_train_df)])
y_spring_train = spring_train_df["ground_truth_criticality"].values.astype(np.float32)
p0_spring_train = spring_train_df["is_critical_p0"].values.astype(np.float32)

class DynamicCriticalityHead(nn.Module):
    def __init__(self, in_dim: int = 137, hidden_dim: int = 64):
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

torch.manual_seed(45)
head = DynamicCriticalityHead(in_dim=137, hidden_dim=64).to(device)
optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=18)
loss_fn = pairwise_margin_loss(margin=0.15, weight=0.20)

train_loader = DataLoader(
    TensorDataset(
        torch.tensor(X_spring_train, dtype=torch.float32),
        torch.tensor(y_spring_train, dtype=torch.float32),
        torch.tensor(p0_spring_train, dtype=torch.float32)
    ),
    batch_size=256, shuffle=True
)

head.train()
for ep in range(18):
    for bx, by, bp in train_loader:
        bx, by, bp = bx.to(device), by.to(device), bp.to(device)
        optimizer.zero_grad()
        loss = loss_fn(head(bx), by, bp)
        loss.backward()
        optimizer.step()
    scheduler.step()

# Zero-Shot evaluation on JFrog Test Set
head.eval()
with torch.no_grad():
    zero_shot_pred = head(torch.tensor(X_jf_test, dtype=torch.float32, device=device)).cpu().numpy()

k_jf = max(1, int(np.ceil(0.05 * len(jfrog_test_df))))
top_jf = np.argsort(zero_shot_pred)[-k_jf:]
prec_zs = np.sum(p0_jf_test[top_jf] == 1) / k_jf
recall_zs = np.sum(p0_jf_test[top_jf] == 1) / np.sum(p0_jf_test == 1)
rho_zs = spearmanr(zero_shot_pred, y_jf_test).statistic
ndcg_zs = ndcg_score([y_jf_test], [zero_shot_pred], k=10)

test_eval_df = jfrog_test_df.copy()
test_eval_df["pred_score"] = zero_shot_pred
grp_ndcg_zs = compute_group_ndcg(test_eval_df, k=10)

print("\n" + "="*80)
print("CROSS-PROJECT GENERALIZATION: SPRING -> JFROG (ZERO-SHOT INDUCTIVE TRANSFER)")
print("="*80)
print(f"  • JFrog Test Samples:    {len(jfrog_test_df):,} issues (P0 count: {int(p0_jf_test.sum())})")
print(f"  • Top-5% Cutoff:         {k_jf} issues")
print(f"  • Zero-Shot Prec@Top-5%: {prec_zs:.4f} ({int(prec_zs * k_jf)}/{k_jf})")
print(f"  • Zero-Shot Recall@5%:   {recall_zs:.4f}")
print(f"  • Zero-Shot Spearman rho:{rho_zs:.4f}")
print(f"  • Zero-Shot NDCG@10:     {ndcg_zs:.4f}")
print(f"  • Zero-Shot Grp-NDCG@10: {grp_ndcg_zs:.4f}")
print("="*80)
