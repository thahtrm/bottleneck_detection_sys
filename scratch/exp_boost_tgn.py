"""Experiment: Benchmark Enhanced Ranking Head on TGN Dynamic Embeddings z_i(T0).
Tests:
1. Neural Deep Ranker with LayerNorm + Dropout + Cosine Annealing
2. CatBoost / LightGBM Ranker with query_groups on [z_tgn || static_features]
3. Multi-Head Temporal GAT representation
"""
import sys
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score
from evaluation_harness_criticality import compute_group_ndcg

train_df = pd.read_parquet("data/pilot_spring/criticality_train.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")
test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")

z_train = np.load("z_tgn_train.npy")
z_val = np.load("z_tgn_val.npy")
z_test = np.load("z_tgn_test.npy")

# Candidate features known at T0
def extract_rich_t0_features(df):
    f_dict = {}
    f_dict["priority_norm"] = df["priority_norm"].fillna(0.5).values.astype(np.float32)
    f_dict["planned_duration_days"] = (df["planned_duration_days"].fillna(30.0).values / 90.0).astype(np.float32)
    f_dict["story_points"] = (df["story_points"].fillna(3.0).values / 15.0).astype(np.float32)
    f_dict["structural_criticality_t0"] = df["structural_criticality_t0"].fillna(0.0).values.astype(np.float32)
    f_dict["assignee_hist_delay_rate"] = df["assignee_hist_delay_rate"].fillna(0.5).values.astype(np.float32)
    f_dict["assignee_wci"] = (df["assignee_wci"].fillna(1.0).values / 10.0).astype(np.float32)
    f_dict["tech_total_risk"] = (df["tech_total_risk"].fillna(0.1).values * 10.0).astype(np.float32)
    f_dict["blocks_count"] = (df["blocks_count"].fillna(0).values / 5.0).astype(np.float32)
    f_dict["depends_count"] = (df["depends_count"].fillna(0).values / 5.0).astype(np.float32)
    f_dict["scf"] = df["scf"].fillna(0.5).values.astype(np.float32)
    f_dict["blast_radius"] = (df["blast_radius"].fillna(0).values / 5.0).astype(np.float32)
    f_dict["sp_planned_ratio"] = (df["sp_planned_ratio"].fillna(0.1).values * 5.0).astype(np.float32)
    f_dict["slack_score"] = np.exp(-df["slack_time"].fillna(14.0).values / 14.0).astype(np.float32)
    f_dict["assignee_active_count"] = (df["assignee_active_count"].fillna(1.0).values / 10.0).astype(np.float32)
    f_dict["is_unassigned"] = df["is_unassigned"].fillna(0).values.astype(np.float32)
    f_dict["is_blocker"] = ((df["blocks_count"].fillna(0).values > 0) | (df["blast_radius"].fillna(0).values > 0)).astype(np.float32)
    f_dict["struct_x_blocks"] = (df["structural_criticality_t0"].fillna(0).values * (df["blocks_count"].fillna(0).values + 1.0)).astype(np.float32)
    f_dict["prio_x_scf"] = (df["priority_norm"].fillna(0.5).values * df["scf"].fillna(0.5).values).astype(np.float32)
    return pd.DataFrame(f_dict).values

feat_tr = extract_rich_t0_features(train_df)
feat_va = extract_rich_t0_features(val_df)
feat_te = extract_rich_t0_features(test_df)

X_tr = np.hstack([z_train, feat_tr])
X_va = np.hstack([z_val, feat_va])
X_te = np.hstack([z_test, feat_te])

y_tr = train_df["ground_truth_criticality"].values.astype(np.float32)
y_va = val_df["ground_truth_criticality"].values.astype(np.float32)
y_te = test_df["ground_truth_criticality"].values.astype(np.float32)

p0_tr = train_df["is_critical_p0"].values.astype(np.float32)
p0_va = val_df["is_critical_p0"].values.astype(np.float32)
p0_te = test_df["is_critical_p0"].values.astype(np.float32)

def eval_preds(name, v_pred, t_pred):
    k_v = 519
    v_top5 = np.argsort(v_pred)[-k_v:]
    v_prec = np.sum(p0_va[v_top5] == 1) / k_v
    v_rho = spearmanr(v_pred, y_va).statistic

    k_t = 519
    t_top5 = np.argsort(t_pred)[-k_t:]
    t_prec = np.sum(p0_te[t_top5] == 1) / k_t
    t_recall = np.sum(p0_te[t_top5] == 1) / np.sum(p0_te == 1)
    t_rho = spearmanr(t_pred, y_te).statistic
    t_ndcg_global = ndcg_score([y_te], [t_pred], k=10)

    test_eval_df = test_df.copy()
    test_eval_df["pred_score"] = t_pred
    t_ndcg_grp = compute_group_ndcg(test_eval_df, k=10)

    print(f"[{name:35s}] TEST Prec: {t_prec:.4f} ({int(t_prec*k_t):3d}/{k_t}) | rho: {t_rho:.4f} | Grp-NDCG: {t_ndcg_grp:.4f} | VAL Prec: {v_prec:.4f} | VAL rho: {v_rho:.4f}")
    return t_prec, t_rho, t_ndcg_grp

print(f"X_train shape: {X_tr.shape}")

# Test LightGBM Regressor on [z_tgn || static]
print("\n--- Testing LightGBM Regressor on TGN Features ---")
model = lgb.LGBMRegressor(
    n_estimators=300,
    learning_rate=0.03,
    num_leaves=31,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=4,
)
model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], callbacks=[lgb.early_stopping(30, verbose=False)])
v_p = model.predict(X_va)
t_p = model.predict(X_te)
eval_preds("LGBM Regressor [z_tgn + static]", v_p, t_p)

# Test LightGBM LambdaRank on query_groups
print("\n--- Testing LightGBM LambdaRank on TGN Features ---")
q_tr = train_df.groupby("query_group", sort=False).size().values
q_va = val_df.groupby("query_group", sort=False).size().values
# Convert continuous y to integer relevance grades (0..31) for lambdarank
y_tr_rank = np.clip((y_tr * 31.0).astype(int), 0, 31)
y_va_rank = np.clip((y_va * 31.0).astype(int), 0, 31)

ranker = lgb.LGBMRanker(
    n_estimators=300,
    learning_rate=0.03,
    num_leaves=31,
    random_state=42,
    n_jobs=4,
)
ranker.fit(
    X_tr, y_tr_rank,
    group=q_tr,
    eval_set=[(X_va, y_va_rank)],
    eval_group=[q_va],
    callbacks=[lgb.early_stopping(30, verbose=False)],
)
v_p_rk = ranker.predict(X_va)
t_p_rk = ranker.predict(X_te)
eval_preds("LGBM LambdaRank [z_tgn + static]", v_p_rk, t_p_rk)
