"""Generate publication-ready comparison visualizations for the 4 ML tracks:
- figures/pr_roc_curves.png
- figures/confusion_matrices.png
- figures/shap_top10.png
Also copies them to the artifact directory.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_curve, roc_curve

# Configure visual style
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams.update({
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "figure.titlesize": 14,
})

FIG_DIR = Path("figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = Path("/home/jiooum/.gemini/antigravity/brain/188ad42d-9e89-44cd-8b5a-4699ac7f3d2c")

# Load Leaderboard
with open("experiments/leaderboard.json", "r") as f:
    leaderboard = json.load(f)

# Load test predictions
tracks = {
    "Stacking Meta-Learner": {
        "pred_path": "experiments/stacking/predictions_test.csv",
        "color": "#1f77b4",
        "ls": "-",
        "lw": 2.5,
        "key": "stacking",
    },
    "XGBoost (Track 1)": {
        "pred_path": "experiments/xgboost/predictions_test.csv",
        "color": "#ff7f0e",
        "ls": "--",
        "lw": 2.0,
        "key": "xgboost",
    },
    "Random Forest (Track 2)": {
        "pred_path": "experiments/randomforest/predictions_test.csv",
        "color": "#2ca02c",
        "ls": "-.",
        "lw": 2.0,
        "key": "randomforest",
    },
    "Logistic Reg (Track 3)": {
        "pred_path": "experiments/logreg/predictions_test.csv",
        "color": "#d62728",
        "ls": ":",
        "lw": 2.0,
        "key": "logreg",
    },
}

data = {}
for name, meta in tracks.items():
    df = pd.read_csv(meta["pred_path"])
    data[name] = {
        "y_true": df["y_true"].values.astype(int),
        "y_prob": df["y_prob"].values.astype(float),
        "opt_thr": leaderboard[meta["key"]]["optimal_threshold"],
        "metrics": leaderboard[meta["key"]]["test_metrics"],
        "color": meta["color"],
        "ls": meta["ls"],
        "lw": meta["lw"],
    }

# ==============================================================================
# 1. PR-AUC and ROC-AUC Curves
# ==============================================================================
fig, (ax_pr, ax_roc) = plt.subplots(1, 2, figsize=(15, 6.5), dpi=300)

# ISO-F1 Curves on PR plot
f_scores = [0.5, 0.6, 0.7, 0.8]
for f_score in f_scores:
    x_iso = np.linspace(0.01, 1, 100)
    y_iso = f_score * x_iso / (2 * x_iso - f_score)
    ax_pr.plot(x_iso[y_iso >= 0], y_iso[y_iso >= 0], color="gray", alpha=0.3, linestyle=":")
    ax_pr.annotate(f"F1={f_score}", xy=(0.88, f_score * 0.88 / (2 * 0.88 - f_score) + 0.01),
                   fontsize=8, color="gray", alpha=0.7)

# No-skill baseline on PR
y_true_test = data["Stacking Meta-Learner"]["y_true"]
no_skill = y_true_test.mean()
ax_pr.axhline(no_skill, color="gray", linestyle="--", alpha=0.6, label=f"No Skill ({no_skill:.3f})")

# ROC diagonal
ax_roc.plot([0, 1], [0, 1], color="gray", linestyle="--", alpha=0.6, label="Random Guess (0.50)")

for name, d in data.items():
    # PR Curve
    p, r, thrs = precision_recall_curve(d["y_true"], d["y_prob"])
    pr_auc = d["metrics"]["pr_auc"]
    ax_pr.plot(r, p, label=f"{name} (PR-AUC = {pr_auc:.4f})", color=d["color"], ls=d["ls"], lw=d["lw"])

    # Mark operating point
    y_pred = (d["y_prob"] >= d["opt_thr"]).astype(int)
    op_p = d["metrics"]["precision"]
    op_r = d["metrics"]["recall"]
    ax_pr.plot(op_r, op_p, marker="*", markersize=11, color=d["color"], markeredgecolor="black")

    # ROC Curve
    fpr, tpr, _ = roc_curve(d["y_true"], d["y_prob"])
    roc_auc = d["metrics"]["roc_auc"]
    ax_roc.plot(fpr, tpr, label=f"{name} (ROC-AUC = {roc_auc:.4f})", color=d["color"], ls=d["ls"], lw=d["lw"])

ax_pr.set_title("Precision-Recall Curves (Out-of-Time Test Set)", fontweight="bold")
ax_pr.set_xlabel("Recall (True Positive Rate)")
ax_pr.set_ylabel("Precision (Positive Predictive Value)")
ax_pr.set_xlim([0.0, 1.02])
ax_pr.set_ylim([0.35, 1.02])
ax_pr.legend(loc="upper right", frameon=True)
ax_pr.grid(True, alpha=0.3)

ax_roc.set_title("Receiver Operating Characteristic (ROC) Curves", fontweight="bold")
ax_roc.set_xlabel("False Positive Rate (1 - Specificity)")
ax_roc.set_ylabel("True Positive Rate (Recall)")
ax_roc.set_xlim([-0.02, 1.02])
ax_roc.set_ylim([-0.02, 1.02])
ax_roc.legend(loc="lower right", frameon=True)
ax_roc.grid(True, alpha=0.3)

plt.tight_layout()
pr_roc_path = FIG_DIR / "pr_roc_curves.png"
plt.savefig(pr_roc_path, dpi=300, bbox_inches="tight")
plt.close()
print(f"Saved {pr_roc_path}")

# ==============================================================================
# 2. Confusion Matrices (2x2 Grid)
# ==============================================================================
fig, axes = plt.subplots(2, 2, figsize=(12, 10), dpi=300)
axes = axes.flatten()

order = ["Random Forest (Track 2)", "XGBoost (Track 1)", "Logistic Reg (Track 3)", "Stacking Meta-Learner"]

for i, name in enumerate(order):
    ax = axes[i]
    d = data[name]
    cm_dict = d["metrics"]["confusion_matrix"]
    cm = np.array([
        [cm_dict["tn"], cm_dict["fp"]],
        [cm_dict["fn"], cm_dict["tp"]]
    ])
    
    # Plot matrix
    im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
    ax.set_title(
        f"{name}\nF1={d['metrics']['f1_score']:.4f} | Prec={d['metrics']['precision']:.4f} | Rec={d['metrics']['recall']:.4f}",
        fontsize=12, fontweight="bold"
    )
    
    # Tick marks
    tick_marks = np.arange(2)
    ax.set_xticks(tick_marks)
    ax.set_yticks(tick_marks)
    ax.set_xticklabels(["Pred: No Delay (0)", "Pred: Delay (1)"])
    ax.set_yticklabels(["Actual: No Delay (0)", "Actual: Delay (1)"])
    
    # Text annotations inside cells
    thresh = cm.max() / 2.0
    for r in range(2):
        for c in range(2):
            val = cm[r, c]
            pct = val / cm.sum() * 100
            label_text = f"{val}\n({pct:.1f}%)"
            ax.text(c, r, label_text, horizontalalignment="center", verticalalignment="center",
                    color="white" if val > thresh else "black", fontsize=12, fontweight="bold")
                    
    ax.set_ylabel("True Label")
    ax.set_xlabel("Predicted Label")
    ax.grid(False)

plt.tight_layout()
cm_path = FIG_DIR / "confusion_matrices.png"
plt.savefig(cm_path, dpi=300, bbox_inches="tight")
plt.close()
print(f"Saved {cm_path}")

# ==============================================================================
# 3. Top 10 Feature Importances Across Tracks
# ==============================================================================
fig, (ax_xgb, ax_rf, ax_lr) = plt.subplots(1, 3, figsize=(18, 7.5), dpi=300)

# XGBoost SHAP
with open("experiments/xgboost/shap_summary.json") as f:
    shap_data = json.load(f)[:10]
shap_feats = [x["feature"] for x in reversed(shap_data)]
shap_vals = [x["mean_abs_shap"] for x in reversed(shap_data)]
ax_xgb.barh(shap_feats, shap_vals, color="#ff7f0e", alpha=0.85, edgecolor="black")
ax_xgb.set_title("Track 1: XGBoost Top SHAP Features\n(Mean |SHAP Value| on Val)", fontweight="bold")
ax_xgb.set_xlabel("Mean |SHAP Value|")
ax_xgb.grid(True, alpha=0.3)

# Random Forest Importance
with open("experiments/randomforest/rf_importance.json") as f:
    rf_data = json.load(f)["top_features"]
rf_top10 = list(rf_data.items())[:10]
rf_feats = [x[0] for x in reversed(rf_top10)]
rf_vals = [x[1] for x in reversed(rf_top10)]
ax_rf.barh(rf_feats, rf_vals, color="#2ca02c", alpha=0.85, edgecolor="black")
ax_rf.set_title("Track 2: Random Forest Top Features\n(Gini Importance)", fontweight="bold")
ax_rf.set_xlabel("Relative Importance")
ax_rf.grid(True, alpha=0.3)

# Logistic Regression Top Coefficients
with open("experiments/logreg/coefficients.json") as f:
    lr_data = json.load(f)
pos_factors = lr_data["top_positive_risk_factors"][:5]
neg_factors = lr_data["top_negative_protective_factors"][:5]

comb_feats = [x["feature"] for x in reversed(pos_factors)] + [x["feature"] for x in reversed(neg_factors)]
comb_vals = [x["coefficient"] for x in reversed(pos_factors)] + [x["coefficient"] for x in reversed(neg_factors)]
colors = ["#d62728" if v > 0 else "#1f77b4" for v in comb_vals]

ax_lr.barh(comb_feats, comb_vals, color=colors, alpha=0.85, edgecolor="black")
ax_lr.set_title("Track 3: ElasticNet Key Coefficients\n(Red: Risk (+), Blue: Protective (-))", fontweight="bold")
ax_lr.set_xlabel("Standardized Coefficient")
ax_lr.axvline(0, color="black", lw=1)
ax_lr.grid(True, alpha=0.3)

plt.tight_layout()
shap_path = FIG_DIR / "shap_top10.png"
plt.savefig(shap_path, dpi=300, bbox_inches="tight")
plt.close()
print(f"Saved {shap_path}")

# ==============================================================================
# Copy figures to artifact directory
# ==============================================================================
if ARTIFACT_DIR.exists():
    for f in [pr_roc_path, cm_path, shap_path]:
        dest = ARTIFACT_DIR / f.name
        shutil.copy2(f, dest)
        print(f"Copied {f} to artifact directory {dest}")

print("✅ All visualizations successfully generated and copied to artifacts!")
