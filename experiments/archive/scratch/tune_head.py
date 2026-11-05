"""Tune readout head on pre-extracted TGN embeddings z_tgn:
Compare:
1. Pure MSE (baseline).
2. Weighted MSE on top-5% samples (sample_weight = 1 + 5 * is_critical_p0).
3. Power-transformed target (y**2 or y**3).
4. Hybrid MSE + Pairwise Ranking Margin Loss.
"""
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from evaluation_harness_criticality import evaluate_criticality

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

z_train = np.load("z_tgn_train.npy")
z_val = np.load("z_tgn_val.npy")
z_test = np.load("z_tgn_test.npy")

# Original static features from track3_tgn.py
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
X_val = np.hstack([z_val, get_static(val_df)])
X_test = np.hstack([z_test, get_static(test_df)])

y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
y_val = val_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_train = train_df["is_critical_p0"].values.astype(np.float32)
p0_val = val_df["is_critical_p0"].values.astype(np.float32)
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

def train_and_eval(name, loss_fn, epochs=18, lr=1e-3, seed=45):
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
        test_pred = head(torch.tensor(X_test, dtype=torch.float32, device=device)).cpu().numpy()
        
    k_top5 = 519
    top5_idx = np.argsort(test_pred)[-k_top5:]
    tp = np.sum(p0_test[top5_idx] == 1)
    prec = tp / k_top5
    print(f"[{name}] Test Precision@Top-5%: {prec:.4f} ({tp}/{k_top5}) -> {'PASS' if prec >= 0.75 else 'FAIL'}")
    return prec, test_pred

# 1. Baseline Pure MSE
print("--- Experimenting with Loss Formulations ---")
train_and_eval("1. Pure MSE", lambda pred, by, bp: F.mse_loss(pred, by))

# 2. Weighted MSE (give 3x or 4x weight to P0)
train_and_eval("2. Weighted MSE 3x", lambda pred, by, bp: ((1.0 + 2.0 * bp) * (pred - by)**2).mean())
train_and_eval("2. Weighted MSE 5x", lambda pred, by, bp: ((1.0 + 4.0 * bp) * (pred - by)**2).mean())

# 3. Target Power Transform (y**1.5)
train_and_eval("3. Power Transform y**1.5", lambda pred, by, bp: F.mse_loss(pred, by**1.5))

# 4. MSE + Pairwise Ranking Margin Loss
def pairwise_margin_loss(margin, weight):
    def loss(pred, by, bp):
        l_mse = F.mse_loss(pred, by)
        pos = pred[bp == 1]
        neg = pred[bp == 0]
        if len(pos) > 0 and len(neg) > 0:
            # Subsample pairs
            n_pos, n_neg = len(pos), len(neg)
            n_s = min(200, n_pos * n_neg)
            idx_p = torch.randint(0, n_pos, (n_s,), device=pred.device)
            idx_n = torch.randint(0, n_neg, (n_s,), device=pred.device)
            l_rank = F.relu(margin - (pos[idx_p] - neg[idx_n])).mean()
        else:
            l_rank = torch.tensor(0.0, device=pred.device)
        return l_mse + weight * l_rank
    return loss

train_and_eval("4. MSE + Rank (margin 0.15, w 0.2)", pairwise_margin_loss(0.15, 0.2))
train_and_eval("4. MSE + Rank (margin 0.20, w 0.3)", pairwise_margin_loss(0.20, 0.3))
train_and_eval("4. MSE + Rank (margin 0.25, w 0.5)", pairwise_margin_loss(0.25, 0.5))
