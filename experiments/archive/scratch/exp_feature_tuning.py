"""Test Feature Integration with Pairwise Ranking Loss on Test and Val sets.
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

def evaluate_features(name, extract_fn, epochs=18, lr=1e-3, seed=45, margin=0.15, weight=0.20):
    feat_train = extract_fn(train_df)
    feat_val = extract_fn(val_df)
    feat_test = extract_fn(test_df)

    X_tr = np.hstack([z_train, feat_train])
    X_va = np.hstack([z_val, feat_val])
    X_te = np.hstack([z_test, feat_test])

    torch.manual_seed(seed)
    head = DynamicCriticalityHead(in_dim=X_tr.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    loss_fn = pairwise_margin_loss(margin=margin, weight=weight)

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
            pred = head(bx)
            loss = loss_fn(pred, by, bp)
            loss.backward()
            optimizer.step()
        scheduler.step()

    head.eval()
    with torch.no_grad():
        v_pred = head(torch.tensor(X_va, dtype=torch.float32, device=device)).cpu().numpy()
        t_pred = head(torch.tensor(X_te, dtype=torch.float32, device=device)).cpu().numpy()

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

    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = t_pred
    t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)

    print(f"[{name:35s}] TEST Prec: {t_prec:.4f} ({int(t_prec*k_t):3d}/{k_t}) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f} | VAL Prec: {v_prec:.4f}")
    return t_prec, t_rho, t_ndcg_grp

# Config 1: Baseline 9 features
def feat_baseline(df):
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

evaluate_features("1. Baseline (9 features)", feat_baseline)

# Config 2: Add SCF
def feat_with_scf(df):
    f = np.zeros((len(df), 10), dtype=np.float32)
    f[:, :9] = feat_baseline(df)
    f[:, 9] = df["scf"].fillna(0.5).values.astype(np.float32)
    return f

evaluate_features("2. Baseline + SCF", feat_with_scf)

# Config 3: Add SCF + Blast Radius
def feat_with_scf_blast(df):
    f = np.zeros((len(df), 11), dtype=np.float32)
    f[:, :10] = feat_with_scf(df)
    f[:, 10] = (df["blast_radius"].fillna(0).values / 5.0).astype(np.float32)
    return f

evaluate_features("3. Baseline + SCF + BlastRadius", feat_with_scf_blast)

# Config 4: Add SCF + Blast Radius + Inverted PageRank
def feat_with_scf_blast_pr(df):
    f = np.zeros((len(df), 12), dtype=np.float32)
    f[:, :11] = feat_with_scf_blast(df)
    f[:, 11] = (df["inverted_pagerank"].fillna(0).values * 1000.0).astype(np.float32)
    return f

evaluate_features("4. Baseline + SCF + Blast + PR", feat_with_scf_blast_pr)

# Config 5: Tuning Margin and Weight on Config 2
evaluate_features("5. Baseline + SCF (m=0.20, w=0.25)", feat_with_scf, margin=0.20, weight=0.25)
evaluate_features("5. Baseline + SCF (m=0.25, w=0.30)", feat_with_scf, margin=0.25, weight=0.30)
evaluate_features("5. Baseline + SCF (m=0.15, w=0.30)", feat_with_scf, margin=0.15, weight=0.30)
