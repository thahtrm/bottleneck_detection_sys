"""Test Pairwise Blends of Bidi-44 and Bidi-47.
"""
import sys
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score
from evaluation_harness_criticality import compute_group_ndcg

test_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")
val_df = pd.read_parquet("data/pilot_spring/criticality_val.parquet")

y_test = test_df["ground_truth_criticality"].values
p0_test = test_df["is_critical_p0"].values

y_val = val_df["ground_truth_criticality"].values
p0_val = val_df["is_critical_p0"].values
k = 519

# Import from test_multi_model_ensemble
from test_multi_model_ensemble import v1, t1, v2, t2, v3, t3, v4, t4

for alpha in [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]:
    t_b = alpha * t3 + (1 - alpha) * t4
    v_b = alpha * v3 + (1 - alpha) * v4

    top_t = np.argsort(t_b)[-k:]
    prec_t = np.sum(p0_test[top_t] == 1) / k
    rho_t = spearmanr(t_b, y_test).statistic
    test_eval = test_df.copy()
    test_eval["pred_score"] = t_b
    grp_t = compute_group_ndcg(test_eval, k=10)

    top_v = np.argsort(v_b)[-k:]
    prec_v = np.sum(p0_val[top_v] == 1) / k
    rho_v = spearmanr(v_b, y_val).statistic

    print(f"Alpha {alpha:.1f} (t3 * {alpha:.1f} + t4 * {1-alpha:.1f}): TEST Prec: {prec_t:.4f} ({int(prec_t*k)}/{k}) | rho: {rho_t:.4f} | Grp-NDCG: {grp_t:.4f} | VAL Prec: {prec_v:.4f} | VAL rho: {rho_v:.4f}")
