"""Experiment Vector 3: Multi-Task Ranking Loss & Differentiable Approx-NDCG.
Benchmarks:
1. Baseline: MSE + Random Pairwise Margin (margin=0.15, w=0.20)
2. Multi-Task Joint Loss: MSE + Pairwise Margin + BCE(P0) with tunable weights
3. Top-Heavy ApproxNDCG + Pairwise Margin Loss
4. Focal Margin Loss + BCE Loss
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
print("Device:", device)

train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

z_train = np.load("z_tgn_train.npy")
z_val = np.load("z_tgn_val.npy")
z_test = np.load("z_tgn_test.npy")

def get_static(df):
    feats = np.zeros((len(df), 16), dtype=np.float32)
    feats[:, 0] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    feats[:, 1] = (df["planned_duration_days"].fillna(30.0).values / 90.0).astype(np.float32)
    feats[:, 2] = (df["story_points"].fillna(3.0).values / 15.0).astype(np.float32)
    feats[:, 3] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    feats[:, 4] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    feats[:, 5] = (df["assignee_wci"].fillna(1.0).values / 10.0).astype(np.float32)
    feats[:, 6] = (df["tech_total_risk"].fillna(0.1).values * 10.0).astype(np.float32)
    feats[:, 7] = (df["blocks_count"].fillna(0).values / 5.0).astype(np.float32)
    feats[:, 8] = (df["depends_count"].fillna(0).values / 5.0).astype(np.float32)
    feats[:, 9] = (df["blast_radius"].fillna(0).values / 5.0).astype(np.float32)
    feats[:, 10] = (df["sp_planned_ratio"].fillna(0.1).values * 5.0).astype(np.float32)
    feats[:, 11] = df["scf"].fillna(0.0).values.astype(np.float32)
    feats[:, 12] = (df["inverted_pagerank"].fillna(0.0).values * 1000.0).astype(np.float32)
    feats[:, 13] = np.exp(-df["slack_time"].fillna(14.0).values / 14.0).astype(np.float32)
    feats[:, 14] = (df["assignee_active_count"].fillna(1.0).values / 10.0).astype(np.float32)
    feats[:, 15] = df["ambiguity_score"].fillna(0.0).values.astype(np.float32)
    return feats

X_train = np.hstack([z_train, get_static(train_df)])
X_val = np.hstack([z_val, get_static(val_df)])
X_test = np.hstack([z_test, get_static(test_df)])

y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
y_val = val_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_train = train_df["is_critical_p0"].values.astype(np.float32)
p0_val = val_df["is_critical_p0"].values.astype(np.float32)
p0_test = test_df["is_critical_p0"].values.astype(np.float32)

class CriticalityHead(nn.Module):
    def __init__(self, in_dim: int = 144, hidden_dim: int = 64):
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

def evaluate_model(name, loss_fn, epochs=18, lr=1e-3, seed=45):
    torch.manual_seed(seed)
    head = CriticalityHead(in_dim=X_train.shape[1], hidden_dim=64).to(device)
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

    print(f"[{name:35s}] TEST Prec: {t_prec:.4f} ({int(t_prec*519)}/519) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f} | VAL Prec: {v_prec:.4f}")
    return t_prec, t_rho, t_ndcg_grp

print("="*90)
print("BENCHMARKING LOSS FUNCTIONS ON TGN ARCHITECTURE")
print("="*90)

# 1. Baseline Pairwise Margin Loss
def baseline_loss(margin=0.15, weight=0.20):
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

evaluate_model("1. Baseline Margin (0.15, w=0.20)", baseline_loss(0.15, 0.20))

# 2. Multi-Task Joint Loss: MSE + Rank + BCE
def multitask_joint_loss(margin=0.15, w_rank=0.25, w_bce=0.10):
    def loss(pred, by, bp):
        l_mse = F.mse_loss(pred, by)
        pos = pred[bp == 1]
        neg = pred[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            n_pos, n_neg = len(pos), len(neg)
            n_s = min(300, n_pos * n_neg)
            idx_p = torch.randint(0, n_pos, (n_s,), device=pred.device)
            idx_n = torch.randint(0, n_neg, (n_s,), device=pred.device)
            l_rank = F.relu(margin - (pos[idx_p] - neg[idx_n])).mean()
        else:
            l_rank = torch.tensor(0.0, device=pred.device)
        # Binary Cross Entropy on P0 classification
        l_bce = F.binary_cross_entropy(pred.clamp(1e-6, 1.0 - 1e-6), bp)
        return l_mse + w_rank * l_rank + w_bce * l_bce
    return loss

evaluate_model("2. Multi-Task (w_rk=0.25, w_bce=0.05)", multitask_joint_loss(0.15, 0.25, 0.05))
evaluate_model("2. Multi-Task (w_rk=0.30, w_bce=0.10)", multitask_joint_loss(0.15, 0.30, 0.10))
evaluate_model("2. Multi-Task (w_rk=0.20, w_bce=0.15)", multitask_joint_loss(0.15, 0.20, 0.15))

# 3. Differentiable ApproxNDCG Loss
def approx_ndcg_loss(alpha=10.0, w_ndcg=0.30):
    def loss(pred, by, bp):
        l_mse = F.mse_loss(pred, by)
        # Compute ApproxNDCG on the batch
        # pred: [B], by: [B]
        # Pairwise sigmoid diff
        diff = pred.unsqueeze(1) - pred.unsqueeze(0) # [B, B]
        # approx rank_i = 1 + sum_{j != i} sigmoid(alpha * (s_j - s_i))
        # Note: s_j > s_i means j is ranked higher than i
        # diff[j, i] = s_j - s_i
        soft_ranks = 1.0 + torch.sigmoid(-alpha * diff).sum(dim=1) - torch.sigmoid(torch.tensor(0.0, device=pred.device))
        
        # Gain: 2^y - 1
        gains = (torch.pow(2.0, by) - 1.0)
        discounts = 1.0 / torch.log2(soft_ranks + 1.0)
        dcg = (gains * discounts).sum()
        
        # Ideal DCG
        ideal_ranks = 1.0 + torch.arange(len(by), device=pred.device, dtype=torch.float32)
        ideal_discounts = 1.0 / torch.log2(ideal_ranks + 1.0)
        sorted_gains, _ = torch.sort(gains, descending=True)
        idcg = (sorted_gains * ideal_discounts).sum().clamp(min=1e-6)
        
        l_ndcg = 1.0 - (dcg / idcg)
        return l_mse + w_ndcg * l_ndcg
    return loss

evaluate_model("3. ApproxNDCG (alpha=10, w=0.20)", approx_ndcg_loss(alpha=10.0, w_ndcg=0.20))
evaluate_model("3. ApproxNDCG (alpha=20, w=0.30)", approx_ndcg_loss(alpha=20.0, w_ndcg=0.30))

# 4. Hybrid: ApproxNDCG + Pairwise Margin + MSE
def hybrid_rank_ndcg_loss(margin=0.15, w_rank=0.20, alpha=10.0, w_ndcg=0.20):
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

        diff = pred.unsqueeze(1) - pred.unsqueeze(0)
        soft_ranks = 1.0 + torch.sigmoid(-alpha * diff).sum(dim=1) - torch.sigmoid(torch.tensor(0.0, device=pred.device))
        gains = (torch.pow(2.0, by) - 1.0)
        discounts = 1.0 / torch.log2(soft_ranks + 1.0)
        dcg = (gains * discounts).sum()
        sorted_gains, _ = torch.sort(gains, descending=True)
        ideal_ranks = 1.0 + torch.arange(len(by), device=pred.device, dtype=torch.float32)
        idcg = (sorted_gains / torch.log2(ideal_ranks + 1.0)).sum().clamp(min=1e-6)
        l_ndcg = 1.0 - (dcg / idcg)

        return l_mse + w_rank * l_rank + w_ndcg * l_ndcg
    return loss

evaluate_model("4. Hybrid Margin + ApproxNDCG", hybrid_rank_ndcg_loss(0.15, 0.20, 10.0, 0.20))
