"""Benchmark advanced ranking objective functions on TGN embeddings:
1. Baseline MSE + Random Pairwise Margin
2. Hard Negative Mining Pairwise Margin Loss (focus on margin errors near P0 threshold)
3. RankNet with Delta-NDCG weights (LambdaRank)
4. Differentiable ApproxNDCG Loss
"""
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

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
    return feats

X_train = np.hstack([z_train, get_static(train_df)])
X_test = np.hstack([z_test, get_static(test_df)])

y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_train = train_df["is_critical_p0"].values.astype(np.float32)
p0_test = test_df["is_critical_p0"].values.astype(np.float32)

class DynamicCriticalityHead(nn.Module):
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

def run_experiment(name, loss_fn, epochs=18, lr=1e-3, seed=45):
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
        t_pred = head(torch.tensor(X_test, dtype=torch.float32, device=device)).cpu().numpy()
        
    k_top5 = 519
    t_top5 = np.argsort(t_pred)[-k_top5:]
    t_prec = np.sum(p0_test[t_top5] == 1) / k_top5
    t_recall = np.sum(p0_test[t_top5] == 1) / np.sum(p0_test == 1)
    t_rho = spearmanr(t_pred, y_test).statistic
    ndcg10 = ndcg_score([y_test], [t_pred], k=10)
    
    print(f"[{name:38s}] Prec@Top5%: {t_prec:.4f} ({int(t_prec*519)}/{k_top5}) | Recall: {t_recall:.4f} | NDCG@10: {ndcg10:.4f} | rho: {t_rho:.4f}")
    return t_prec, t_rho, ndcg10

print("=========================================================================================")
print("BENCHMARKING RANKING-AWARE OBJECTIVE FUNCTIONS ON OUT-OF-TIME TEST SET")
print("=========================================================================================")

# 1. Baseline Random Pairwise Margin (Current Iter 3)
def random_pairwise(margin=0.15, weight=0.20):
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

run_experiment("1. Random Pairwise Margin (Current)", random_pairwise(0.15, 0.20))

# 2. Hard Negative Mining Pairwise Loss:
# Instead of random negatives, pick the negatives with highest predicted score or highest y (near P0 threshold)
def hard_negative_margin(margin=0.15, weight=0.20, top_k_neg=50):
    def loss(pred, by, bp):
        l_mse = F.mse_loss(pred, by)
        pos = pred[bp == 1]
        neg = pred[bp == 0]
        neg_y = by[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            # Pick hardest negatives: those with highest ground truth y (borderline P0) or highest pred
            k = min(len(neg), top_k_neg)
            # Semi-hard: top-k by ground-truth y (the borderline near-P0 issues)
            hard_neg_idx = torch.topk(neg_y, k=k).indices
            hard_neg = neg[hard_neg_idx]
            
            # Pair all pos with hard negatives
            # pos: [P, 1], hard_neg: [1, K]
            diff = pos.unsqueeze(1) - hard_neg.unsqueeze(0) # [P, K]
            l_rank = F.relu(margin - diff).mean()
        else:
            l_rank = torch.tensor(0.0, device=pred.device)
        return l_mse + weight * l_rank
    return loss

run_experiment("2. Hard Negative Mining (Borderline)", hard_negative_margin(0.15, 0.20, top_k_neg=30))
run_experiment("2. Hard Negative Mining (Top-50 Hard)", hard_negative_margin(0.15, 0.15, top_k_neg=50))

# 3. Softplus RankNet Loss: smooth surrogate to 0-1 ranking error
def ranknet_loss(weight=0.15):
    def loss(pred, by, bp):
        l_mse = F.mse_loss(pred, by)
        pos = pred[bp == 1]
        neg = pred[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            # Pairwise diff
            diff = neg.unsqueeze(0) - pos.unsqueeze(1) # should be negative (pos > neg)
            l_ranknet = F.softplus(diff * 5.0).mean() # log(1 + exp(5*(s_neg - s_pos)))
        else:
            l_ranknet = torch.tensor(0.0, device=pred.device)
        return l_mse + weight * l_ranknet
    return loss

run_experiment("3. RankNet Softplus Loss", ranknet_loss(weight=0.10))

# 4. LambdaRank-style Delta-Y weighted Pairwise Loss
def delta_y_weighted_pairwise(margin=0.15, weight=0.25):
    def loss(pred, by, bp):
        l_mse = F.mse_loss(pred, by)
        pos = pred[bp == 1]
        neg = pred[bp == 0]
        pos_y = by[bp == 1]
        neg_y = by[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            # delta_y indicates urgency of ranking gap
            delta_y = (pos_y.unsqueeze(1) - neg_y.unsqueeze(0)).clamp(min=0.01) # [P, N]
            diff = pos.unsqueeze(1) - neg.unsqueeze(0)
            l_rank = (delta_y * F.relu(margin - diff)).mean()
        else:
            l_rank = torch.tensor(0.0, device=pred.device)
        return l_mse + weight * l_rank
    return loss

run_experiment("4. Delta-Y Weighted Pairwise Loss", delta_y_weighted_pairwise(0.15, 0.25))
