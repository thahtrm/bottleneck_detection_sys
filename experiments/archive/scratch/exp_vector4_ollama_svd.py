"""Experiment Vector 4: Dense Semantic Embeddings from Ollama via TruncatedSVD.
Evaluates the impact of 16d and 32d semantic representations extracted from Ollama (nomic-embed-text)
combined with TGN continuous memory representations z_i(T0).
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
from sklearn.decomposition import TruncatedSVD
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score
from evaluation_harness_criticality import evaluate_criticality

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", device)

# 1. Load Parquet splits
train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

# 2. Load TGN embeddings
z_train = np.load("z_tgn_train.npy")
z_val = np.load("z_tgn_val.npy")
z_test = np.load("z_tgn_test.npy")

# 3. Load Static Features
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

static_train = get_static(train_df)
static_val = get_static(val_df)
static_test = get_static(test_df)

# 4. Load Ollama 768d embeddings
con = duckdb.connect("data/jira.duckdb", read_only=True)
df_keys = con.execute("""
    SELECT issue_key, ROW_NUMBER() OVER (ORDER BY created_ts ASC, instance ASC, issue_key ASC) - 1 as row_idx
    FROM issues
    WHERE created_ts > 946684800
      AND (resolved_ts IS NULL OR resolved_ts >= created_ts)
      AND instance = 'Spring'
""").df()
con.close()

row_to_uniq = np.load("data/emb_row_to_unique_all.npy", mmap_mode="r")
unique_emb = np.load("data/emb_unique_all_fp16.npy", mmap_mode="r")

key_to_row = dict(zip(df_keys["issue_key"], df_keys["row_idx"]))

train_rows = [key_to_row[k] for k in train_df["issue_key"]]
val_rows = [key_to_row[k] for k in val_df["issue_key"]]
test_rows = [key_to_row[k] for k in test_df["issue_key"]]

train_emb = np.array(unique_emb[row_to_uniq[train_rows]], dtype=np.float32)
val_emb = np.array(unique_emb[row_to_uniq[val_rows]], dtype=np.float32)
test_emb = np.array(unique_emb[row_to_uniq[test_rows]], dtype=np.float32)

print(f"Ollama Embeddings: train {train_emb.shape}, val {val_emb.shape}, test {test_emb.shape}")

y_train = train_df["ground_truth_criticality"].values.astype(np.float32)
y_val = val_df["ground_truth_criticality"].values.astype(np.float32)
y_test = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_train = train_df["is_critical_p0"].values.astype(np.float32)
p0_val = val_df["is_critical_p0"].values.astype(np.float32)
p0_test = test_df["is_critical_p0"].values.astype(np.float32)

class CriticalityHead(nn.Module):
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

def train_and_eval(X_tr, X_va, X_te, name, epochs=18, seed=45):
    torch.manual_seed(seed)
    head = CriticalityHead(in_dim=X_tr.shape[1], hidden_dim=64).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    loss_fn = pairwise_margin_loss(margin=0.15, weight=0.20)

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
    k_top5_val = max(1, int(np.ceil(0.05 * len(val_df))))
    v_top5 = np.argsort(v_pred)[-k_top5_val:]
    v_prec = np.sum(p0_val[v_top5] == 1) / k_top5_val
    v_rho = spearmanr(v_pred, y_val).statistic

    # Test metrics
    k_top5_te = max(1, int(np.ceil(0.05 * len(test_df))))
    t_top5 = np.argsort(t_pred)[-k_top5_te:]
    t_prec = np.sum(p0_test[t_top5] == 1) / k_top5_te
    t_rho = spearmanr(t_pred, y_test).statistic
    t_ndcg = ndcg_score([y_test], [t_pred], k=10)

    print(f"\n=======================================================")
    print(f"RESULTS FOR: {name}")
    print(f"  • VAL  - Prec@Top5%: {v_prec:.4f} ({int(v_prec*k_top5_val)}/{k_top5_val}) | rho: {v_rho:.4f}")
    print(f"  • TEST - Prec@Top5%: {t_prec:.4f} ({int(t_prec*k_top5_te)}/{k_top5_te}) | rho: {t_rho:.4f} | NDCG@10: {t_ndcg:.4f}")
    print(f"=======================================================")
    return t_pred, v_pred

# Test 1: SVD 16 components
print("\n--- Fitting TruncatedSVD (16 components) ---")
svd_16 = TruncatedSVD(n_components=16, random_state=42)
svd_train_16 = svd_16.fit_transform(train_emb)
svd_val_16 = svd_16.transform(val_emb)
svd_test_16 = svd_16.transform(test_emb)
print(f"Explained variance ratio (16 components): {svd_16.explained_variance_ratio_.sum():.4f}")

X_tr_16 = np.hstack([z_train, static_train, svd_train_16])
X_va_16 = np.hstack([z_val, static_val, svd_val_16])
X_te_16 = np.hstack([z_test, static_test, svd_test_16])

t_pred_16, v_pred_16 = train_and_eval(X_tr_16, X_va_16, X_te_16, "TGN + 16 Static + SVD-16 Ollama")

# Test 2: SVD 32 components
print("\n--- Fitting TruncatedSVD (32 components) ---")
svd_32 = TruncatedSVD(n_components=32, random_state=42)
svd_train_32 = svd_32.fit_transform(train_emb)
svd_val_32 = svd_32.transform(val_emb)
svd_test_32 = svd_32.transform(test_emb)
print(f"Explained variance ratio (32 components): {svd_32.explained_variance_ratio_.sum():.4f}")

X_tr_32 = np.hstack([z_train, static_train, svd_train_32])
X_va_32 = np.hstack([z_val, static_val, svd_val_32])
X_te_32 = np.hstack([z_test, static_test, svd_test_32])

t_pred_32, v_pred_32 = train_and_eval(X_tr_32, X_va_32, X_te_32, "TGN + 16 Static + SVD-32 Ollama")
