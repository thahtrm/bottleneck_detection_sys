"""Test Readout Head with all top predictive T0 features + z_tgn on Out-of-Time Test Set.
"""
import sys
sys.path.insert(0, ".")
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

z_train = np.load("z_tgn_train.npy")
z_val = np.load("z_tgn_val.npy")
z_test = np.load("z_tgn_test.npy")

def get_features(df):
    f = np.zeros((len(df), 14), dtype=np.float32)
    f[:, 0] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    f[:, 1] = (df["planned_duration_days"].fillna(30.0).values / 90.0).astype(np.float32)
    f[:, 2] = (df["story_points"].fillna(3.0).values / 15.0).astype(np.float32)
    f[:, 3] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    f[:, 4] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    f[:, 5] = (df["assignee_wci"].fillna(1.0).values / 10.0).astype(np.float32)
    f[:, 6] = (df["tech_total_risk"].fillna(0.1).values * 10.0).astype(np.float32)
    f[:, 7] = (df["blocks_count"].fillna(0).values / 5.0).astype(np.float32)
    f[:, 8] = (df["depends_count"].fillna(0).values / 5.0).astype(np.float32)
    # Extra key drivers:
    f[:, 9] = (df["sp_planned_ratio"].fillna(0.1).values * 5.0).astype(np.float32)
    f[:, 10] = (df["assignee_active_count"].fillna(1.0).values / 10.0).astype(np.float32)
    f[:, 11] = (df["assignee_hist_cycle_time"].fillna(30.0).values / 90.0).astype(np.float32)
    f[:, 12] = df["project_90d_delay_rate"].fillna(0.5).values.astype(np.float32)
    f[:, 13] = ((df["blocks_count"].fillna(0).values > 0) | (df["blast_radius"].fillna(0).values > 0)).astype(np.float32)
    return f

X_train = np.hstack([z_train, get_features(train_df)])
X_val = np.hstack([z_val, get_features(val_df)])
X_test = np.hstack([z_test, get_features(test_df)])

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

def train_and_eval(seed, epochs=18, lr=1e-3, margin=0.15, weight=0.20):
    torch.manual_seed(seed)
    head = DynamicCriticalityHead(in_dim=X_train.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    loss_fn = pairwise_margin_loss(margin=margin, weight=weight)

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
    return v_pred, t_pred

print("Evaluating 5 seeds with 14 T0 features + z_tgn:")
seeds = [42, 43, 44, 45, 46]
v_list, t_list = [], []
for s in seeds:
    vp, tp = train_and_eval(s, epochs=18)
    v_list.append(vp)
    t_list.append(tp)

    k_t = 519
    t_top5 = np.argsort(tp)[-k_t:]
    t_prec = np.sum(p0_test[t_top5] == 1) / k_t
    t_rho = spearmanr(tp, y_test).statistic
    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = tp
    t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)
    print(f"Seed {s} -> Test Prec: {t_prec:.4f} ({int(t_prec*k_t):3d}/519) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f}")

# Ensemble
v_ens = np.mean(v_list, axis=0)
t_ens = np.mean(t_list, axis=0)
k_t = 519
t_top5 = np.argsort(t_ens)[-k_t:]
t_prec = np.sum(p0_test[t_top5] == 1) / k_t
t_rho = spearmanr(t_ens, y_test).statistic
test_eval_df = test_df.copy()
test_eval_df["pred_score"] = t_ens
t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)
t_ndcg_glob = ndcg_score([y_test], [t_ens], k=10)
print("\n" + "="*80)
print(f"5-SEED ENSEMBLE RESULTS:")
print(f"  • TEST Prec@Top5%: {t_prec:.4f} ({int(t_prec*k_t)}/{k_t})")
print(f"  • TEST Spearman rho: {t_rho:.4f}")
print(f"  • TEST Grouped NDCG@10: {t_ndcg_grp:.4f} | Global NDCG: {t_ndcg_glob:.4f}")
print("="*80)
