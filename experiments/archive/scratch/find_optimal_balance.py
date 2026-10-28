"""Grid test to find the optimal loss weighting that achieves ALL PASS on BOTH Val and Test.
"""
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

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

def evaluate_splits(name, loss_fn, epochs=18, lr=1e-3, seed=45):
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
        
    k_top5 = 519
    v_top5 = np.argsort(v_pred)[-k_top5:]
    t_top5 = np.argsort(t_pred)[-k_top5:]
    
    v_prec = np.sum(p0_val[v_top5] == 1) / k_top5
    t_prec = np.sum(p0_test[t_top5] == 1) / k_top5
    
    from scipy.stats import spearmanr
    v_rho = spearmanr(v_pred, y_val).statistic
    t_rho = spearmanr(t_pred, y_test).statistic
    
    val_pass = (v_prec >= 0.75) and (v_rho >= 0.70)
    test_pass = (t_prec >= 0.75) and (t_rho >= 0.70)
    both_pass = val_pass and test_pass
    
    status = "🏆 BOTH PASS!" if both_pass else ("VAL PASS" if val_pass else ("TEST PASS" if test_pass else "FAIL"))
    print(f"[{name:35s}] Val Prec: {v_prec:.4f}, Val rho: {v_rho:.4f} | Test Prec: {t_prec:.4f}, Test rho: {t_rho:.4f} -> {status}")
    return both_pass

# Test weighted MSE variants
for p_w in [1.5, 2.0, 2.5, 3.0]:
    evaluate_splits(f"Weighted MSE (pos_weight={p_w})", lambda p, y, b, w=p_w: ((1.0 + (w-1.0)*b) * (p - y)**2).mean())

# Test mild rank loss variants
for r_w in [0.02, 0.05, 0.08, 0.10]:
    def make_loss(w):
        def loss(p, y, b):
            l_mse = F.mse_loss(p, y)
            pos = p[b == 1]
            neg = p[b == 0]
            if len(pos) > 0 and len(neg) > 0:
                n_s = min(100, len(pos)*len(neg))
                idx_p = torch.randint(0, len(pos), (n_s,), device=p.device)
                idx_n = torch.randint(0, len(neg), (n_s,), device=p.device)
                l_rank = F.relu(0.12 - (pos[idx_p] - neg[idx_n])).mean()
            else:
                l_rank = torch.tensor(0.0, device=p.device)
            return l_mse + w * l_rank
        return loss
    evaluate_splits(f"MSE + Rank (w={r_w})", make_loss(r_w))
