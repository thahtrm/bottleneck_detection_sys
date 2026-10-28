"""Test Combined Optimization:
- Rich discriminative T0 signals (scf, sp_planned_ratio, is_unassigned)
- Higher P0 Margin (m=0.18) + Continuous Pairwise Ranking Loss
- Multi-seed training (e.g. 3-head ensemble)
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

def get_static(df):
    f = np.zeros((len(df), 12), dtype=np.float32)
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
    f[:, 10] = (df["sp_planned_ratio"].fillna(0.1).values * 5.0).astype(np.float32)
    f[:, 11] = df["is_unassigned"].fillna(0).values.astype(np.float32)
    return f

X_train = np.hstack([z_train, get_static(train_df)])
X_val = np.hstack([z_val, get_static(val_df)])
X_test = np.hstack([z_test, get_static(test_df)])

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

def compound_loss(w_mse=1.0, w_p0=0.25, p0_margin=0.18, w_cont=0.20, cont_scale=0.5):
    def loss_fn(pred, by, bp):
        l_mse = F.mse_loss(pred, by)

        pos = pred[bp == 1]
        neg = pred[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            n_s = min(200, len(pos) * len(neg))
            idx_p = torch.randint(0, len(pos), (n_s,), device=pred.device)
            idx_n = torch.randint(0, len(neg), (n_s,), device=pred.device)
            l_p0 = F.relu(p0_margin - (pos[idx_p] - neg[idx_n])).mean()
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
            y_diff = (by[i_sub] - by[j_sub])
            pred_diff = pred[i_sub] - pred[j_sub]
            l_cont = F.relu(cont_scale * y_diff - pred_diff).mean()
        else:
            l_cont = torch.tensor(0.0, device=pred.device)

        return w_mse * l_mse + w_p0 * l_p0 + w_cont * l_cont
    return loss_fn

def train_and_eval(seed, epochs=18, lr=1e-3, loss_fn=None):
    torch.manual_seed(seed)
    head = DynamicCriticalityHead(in_dim=X_train.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

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

loss_fn = compound_loss(w_mse=1.0, w_p0=0.25, p0_margin=0.18, w_cont=0.20, cont_scale=0.5)

seeds = [42, 44, 45, 47, 48]
v_preds, t_preds = [], []

for s in seeds:
    vp, tp = train_and_eval(s, epochs=18, loss_fn=loss_fn)
    v_preds.append(vp)
    t_preds.append(tp)

    k_t = 519
    t_top5 = np.argsort(tp)[-k_t:]
    t_prec = np.sum(p0_test[t_top5] == 1) / k_t
    t_rho = spearmanr(tp, y_test).statistic
    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = tp
    t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)
    print(f"Seed {s:2d} -> Test Prec: {t_prec:.4f} ({int(t_prec*k_t):3d}/519) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f}")

# Ensemble
v_ens = np.mean(v_preds, axis=0)
t_ens = np.mean(t_preds, axis=0)

k_t = 519
t_top5 = np.argsort(t_ens)[-k_t:]
t_prec = np.sum(p0_test[t_top5] == 1) / k_t
t_rho = spearmanr(t_ens, y_test).statistic
test_eval_df = test_df.copy()
test_eval_df["pred_score"] = t_ens
t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)
t_ndcg_glob = ndcg_score([y_test], [t_ens], k=10)

k_v = 519
v_top5 = np.argsort(v_ens)[-k_v:]
v_prec = np.sum(p0_val[v_top5] == 1) / k_v
v_rho = spearmanr(v_ens, y_val).statistic

print("\n" + "="*80)
print(f"ENSEMBLE RESULTS ({len(seeds)} Heads):")
print(f"  • TEST Prec@Top5%: {t_prec:.4f} ({int(t_prec*k_t)}/{k_t})")
print(f"  • TEST Spearman rho: {t_rho:.4f}")
print(f"  • TEST Grouped NDCG@10: {t_ndcg_grp:.4f} | Global NDCG: {t_ndcg_glob:.4f}")
print(f"  • VAL Prec@Top5%: {v_prec:.4f} ({int(v_prec*k_v)}/{k_v}) | VAL rho: {v_rho:.4f}")
print("="*80)
