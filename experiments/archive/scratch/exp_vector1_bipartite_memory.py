"""Experiment Vector 1: Heterogeneous Dynamic Memory (Bipartite CTDG).
Separates dynamic memory for Issues (128d) and Developers (64d).
Simulates continuous-time interactions:
- Status / Priority: Updates Issue memory s_issue(t)
- Link: Updates source and target Issue memories
- Assignee: Updates Issue memory and Developer workload memory s_dev(t)
- Comment: Updates Issue progress memory and Developer activity memory s_dev(t)
At T0: z_u(T0) = [s_issue_u(T0) || s_dev_assignee(T0)] in R^192.
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

# 1. Read splits
train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

# 2. Build issue and developer mappings
con = duckdb.connect("data/jira.duckdb", read_only=True)
events_df = con.execute("""
    SELECT u, v, ts, kind, direction
    FROM v_tgn_events
    WHERE instance = 'Spring'
    ORDER BY ts ASC
""").df()
con.close()

all_issue_keys = list(dict.fromkeys(
    train_df["issue_key"].tolist() + 
    val_df["issue_key"].tolist() + 
    test_df["issue_key"].tolist()
))
issue_to_id = {k: idx for idx, k in enumerate(all_issue_keys)}
n_issues = len(all_issue_keys)

# Collect all developer identifiers from assignee and comment events, plus train/val/test assignee column
dev_candidates = set()
for dev in train_df["assignee"].dropna().tolist() + val_df["assignee"].dropna().tolist() + test_df["assignee"].dropna().tolist():
    dev_candidates.add(dev)

comment_devs = events_df[events_df["kind"] == "comment"]["v"].dropna().unique().tolist()
for d in comment_devs:
    dev_candidates.add(d)

assignee_devs = events_df[events_df["kind"] == "assignee"]["v"].dropna().unique().tolist()
for d in assignee_devs:
    dev_candidates.add(d)

all_dev_keys = list(dev_candidates)
dev_to_id = {k: idx for idx, k in enumerate(all_dev_keys)}
n_devs = len(all_dev_keys)

print(f"Total Issues: {n_issues:,} | Total Developers: {n_devs:,}")

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

# 4. Continuous Bipartite Memory Update Engine
issue_mem_dim = 128
dev_mem_dim = 64

torch.manual_seed(45)
issue_memory = torch.zeros((n_issues, issue_mem_dim), dtype=torch.float32, device=device)
dev_memory = torch.zeros((n_devs, dev_mem_dim), dtype=torch.float32, device=device)

# Message projectors & GRUs
msg_proj_issue = nn.Linear(8, 64).to(device)
msg_proj_dev = nn.Linear(8, 32).to(device)
gru_issue = nn.GRUCell(64, issue_mem_dim).to(device)
gru_dev = nn.GRUCell(32, dev_mem_dim).to(device)

msg_proj_issue.eval()
msg_proj_dev.eval()
gru_issue.eval()
gru_dev.eval()

print("Simulating Heterogeneous Bipartite Continuous Memory updates...", flush=True)

with torch.no_grad():
    u_vals = events_df["u"].values
    v_vals = events_df["v"].values
    kinds = events_df["kind"].values
    n_events = len(events_df)
    batch_size = 5000

    for b_start in range(0, n_events, batch_size):
        b_end = min(n_events, b_start + batch_size)
        sub_u = u_vals[b_start:b_end]
        sub_v = v_vals[b_start:b_end]
        sub_k = kinds[b_start:b_end]
        sub_feat = ev_feat[b_start:b_end]

        # 1. Collect issue updates:
        # u is always an issue (if in issue_to_id)
        # v is an issue if kind == 'link' and v in issue_to_id
        issue_update_ids = []
        issue_feat_indices = []

        dev_update_ids = []
        dev_feat_indices = []

        for i, (uk, vk, kd) in enumerate(zip(sub_u, sub_v, sub_k)):
            if uk in issue_to_id:
                issue_update_ids.append(issue_to_id[uk])
                issue_feat_indices.append(i)

            if kd == "link" and vk in issue_to_id:
                issue_update_ids.append(issue_to_id[vk])
                issue_feat_indices.append(i)

            if kd in ("comment", "assignee") and vk in dev_to_id:
                dev_update_ids.append(dev_to_id[vk])
                dev_feat_indices.append(i)

        # Update issue memory
        if issue_update_ids:
            feat_tensor = torch.tensor(sub_feat[issue_feat_indices], dtype=torch.float32, device=device)
            messages = F.relu(msg_proj_issue(feat_tensor))
            uniq_u, inv_u = np.unique(issue_update_ids, return_inverse=True)
            u_tensor = torch.tensor(uniq_u, dtype=torch.long, device=device)
            node_msgs = torch.zeros((len(uniq_u), 64), dtype=torch.float32, device=device)
            node_msgs.index_add_(0, torch.tensor(inv_u, dtype=torch.long, device=device), messages)
            cur_mem = issue_memory[u_tensor]
            issue_memory[u_tensor] = gru_issue(node_msgs, cur_mem)

        # Update developer memory
        if dev_update_ids:
            feat_tensor_d = torch.tensor(sub_feat[dev_feat_indices], dtype=torch.float32, device=device)
            messages_d = F.relu(msg_proj_dev(feat_tensor_d))
            uniq_d, inv_d = np.unique(dev_update_ids, return_inverse=True)
            d_tensor = torch.tensor(uniq_d, dtype=torch.long, device=device)
            dev_msgs = torch.zeros((len(uniq_d), 32), dtype=torch.float32, device=device)
            dev_msgs.index_add_(0, torch.tensor(inv_d, dtype=torch.long, device=device), messages_d)
            cur_mem_d = dev_memory[d_tensor]
            dev_memory[d_tensor] = gru_dev(dev_msgs, cur_mem_d)

print("Memory simulation complete!", flush=True)

# 5. Extract combined representation z_u(T0) = [s_issue_u || s_dev_assignee]
def extract_split_features(df):
    u_ids = [issue_to_id[k] for k in df["issue_key"]]
    u_mem = issue_memory[torch.tensor(u_ids, dtype=torch.long, device=device)]

    # Assignee dev memory
    d_mems = []
    for a in df["assignee"]:
        if a in dev_to_id:
            d_id = dev_to_id[a]
            d_mems.append(dev_memory[d_id])
        else:
            d_mems.append(torch.zeros(dev_mem_dim, device=device))
    d_mem = torch.stack(d_mems, dim=0)

    # Static 9 features (same as Track 3 baseline)
    static_feats = np.zeros((len(df), 16), dtype=np.float32)
    static_feats[:, 0] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    static_feats[:, 1] = (df["planned_duration_days"].fillna(30.0).values / 90.0).astype(np.float32)
    static_feats[:, 2] = (df["story_points"].fillna(3.0).values / 15.0).astype(np.float32)
    static_feats[:, 3] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    static_feats[:, 4] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    static_feats[:, 5] = (df["assignee_wci"].fillna(1.0).values / 10.0).astype(np.float32)
    static_feats[:, 6] = (df["tech_total_risk"].fillna(0.1).values * 10.0).astype(np.float32)
    static_feats[:, 7] = (df["blocks_count"].fillna(0).values / 5.0).astype(np.float32)
    static_feats[:, 8] = (df["depends_count"].fillna(0).values / 5.0).astype(np.float32)

    z_dyn = torch.cat([u_mem, d_mem], dim=-1).cpu().numpy() # [N, 192]
    return np.hstack([z_dyn, static_feats]) # [N, 208]

X_train = extract_split_features(train_df)
X_val = extract_split_features(val_df)
X_test = extract_split_features(test_df)

print(f"Combined Feature Shapes: train {X_train.shape}, val {X_val.shape}, test {X_test.shape}")

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

def train_and_evaluate(name, epochs=18, lr=1e-3, seed=45):
    torch.manual_seed(seed)
    head = DynamicCriticalityHead(in_dim=X_train.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    loss_fn = pairwise_margin_loss(margin=0.15, weight=0.20)

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

    # Val metrics
    k_v = 519
    v_top5 = np.argsort(v_pred)[-k_v:]
    v_prec = np.sum(p0_val[v_top5] == 1) / k_v
    v_rho = spearmanr(v_pred, y_val).statistic

    # Test metrics
    k_t = 519
    t_top5 = np.argsort(t_pred)[-k_t:]
    t_prec = np.sum(p0_test[t_top5] == 1) / k_t
    t_recall = np.sum(p0_test[t_top5] == 1) / np.sum(p0_test == 1)
    t_rho = spearmanr(t_pred, y_test).statistic
    t_ndcg_global = ndcg_score([y_test], [t_pred], k=10)

    # Grouped NDCG@10 on test
    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = t_pred
    t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)

    print(f"\n=======================================================")
    print(f"RESULTS FOR: {name}")
    print(f"  • VAL  - Prec@Top5%: {v_prec:.4f} ({int(v_prec*k_v)}/{k_v}) | rho: {v_rho:.4f}")
    print(f"  • TEST - Prec@Top5%: {t_prec:.4f} ({int(t_prec*k_t)}/{k_t}) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f} | Global-NDCG: {t_ndcg_global:.4f}")
    print(f"=======================================================")
    return t_pred, v_pred

train_and_evaluate("Vector 1: Heterogeneous Bipartite Dynamic Memory (Issue 128d + Dev 64d)")
