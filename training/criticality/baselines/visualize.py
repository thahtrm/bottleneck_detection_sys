"""
Generate publication-quality charts for Task Criticality & Schedule Impact Experiments.
Outputs:
  docs/figures/task_criticality_benchmark.png
"""

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import auc, precision_recall_curve, roc_curve

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.size"] = 10
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["axes.labelsize"] = 10
plt.rcParams["figure.dpi"] = 300

fig, axes = plt.subplots(2, 2, figsize=(15, 12))
fig.suptitle("Task Criticality & Schedule Impact Modeling (Spring Pilot — 69,154 Issues)", fontsize=16, fontweight="bold", y=0.98)

# -------------------------------------------------------------
# Panel A: Hard Constraints Benchmark on Out-of-Time Test Set
# -------------------------------------------------------------
ax1 = axes[0, 0]
tracks = ["Track 1\nGraph CPM", "Track 2\nCascade Sim", "Track 3\nTGN Memory", "Track 4\nLGBMRanker", "Track 5\nHybrid Meta"]
ndcg = [0.9964, 0.9577, 0.9929, 0.9885, 0.9966]
prec = [0.4200, 0.5222, 0.7303, 0.5915, 0.7726]
spearman = [0.3933, 0.5294, 0.7604, 0.5499, 0.7606]

x = np.arange(len(tracks))
width = 0.25

rects1 = ax1.bar(x - width, ndcg, width, label="NDCG@10", color="#2b5c8f", alpha=0.9)
rects2 = ax1.bar(x, prec, width, label="Precision@Top-5%", color="#e74c3c", alpha=0.9)
rects3 = ax1.bar(x + width, spearman, width, label="Spearman rho", color="#27ae60", alpha=0.9)

# Targets
ax1.axhline(0.82, color="#2b5c8f", linestyle="--", linewidth=1.2, alpha=0.7, label="Target NDCG (>=0.82)")
ax1.axhline(0.75, color="#e74c3c", linestyle="--", linewidth=1.2, alpha=0.7, label="Target Precision (>=0.75)")
ax1.axhline(0.70, color="#27ae60", linestyle="--", linewidth=1.2, alpha=0.7, label="Target Spearman (>=0.70)")

ax1.set_ylabel("Metric Score")
ax1.set_title("A. Model Benchmark vs. Hard Constraints (Out-of-Time Test Set)", fontweight="bold")
ax1.set_xticks(x)
ax1.set_xticklabels(tracks, fontsize=9)
ax1.set_ylim(0, 1.15)
ax1.legend(loc="lower right", fontsize=8, ncol=2)
ax1.grid(axis="y", linestyle=":", alpha=0.6)

# -------------------------------------------------------------
# Panel B: PR & ROC Curve for Track 5 Hybrid Meta
# -------------------------------------------------------------
ax2 = axes[0, 1]
pred_df = pd.read_csv("experiments/predictions_test_hybrid.csv")
gt_df = pd.read_parquet("data/pilot_spring/criticality_test.parquet")
merged = pred_df.merge(gt_df[["issue_key", "is_critical_p0"]], on="issue_key")

precisions, recalls, thresholds = precision_recall_curve(merged["is_critical_p0"], merged["pred_score"])
pr_auc = auc(recalls, precisions)
fpr, tpr, _ = roc_curve(merged["is_critical_p0"], merged["pred_score"])
roc_auc = auc(fpr, tpr)

ax2.plot(recalls, precisions, color="#8e44ad", lw=2.5, label=f"PR Curve (AUC = {pr_auc:.4f})")
ax2.plot(fpr, tpr, color="#2980b9", lw=2, linestyle="-.", label=f"ROC Curve (AUC = {roc_auc:.4f})")

# Operating point at top 5%
k_top5 = int(np.ceil(0.05 * len(merged)))
top_5_cutoff = merged["pred_score"].nlargest(k_top5).iloc[-1]
p0_top5 = merged[merged["pred_score"] >= top_5_cutoff]["is_critical_p0"]
prec_top5 = p0_top5.mean()
rec_top5 = p0_top5.sum() / merged["is_critical_p0"].sum()

ax2.scatter([rec_top5], [prec_top5], color="#c0392b", s=100, zorder=5, label=f"Top-5% Operating Point\n(Prec={prec_top5:.1%}, Rec={rec_top5:.1%})")
ax2.axhline(0.75, color="red", linestyle=":", label="Precision Target (0.75)")

ax2.set_xlabel("Recall / False Positive Rate")
ax2.set_ylabel("Precision / True Positive Rate")
ax2.set_title("B. Track 5 Hybrid Meta: PR & ROC Curves (Test Set)", fontweight="bold")
ax2.set_xlim([0.0, 1.02])
ax2.set_ylim([0.0, 1.05])
ax2.legend(loc="lower left", fontsize=8)
ax2.grid(True, linestyle=":", alpha=0.6)

# -------------------------------------------------------------
# Panel C: Meta-Learner Stacking Weight Allocation
# -------------------------------------------------------------
ax3 = axes[1, 0]
with open("experiments/track5_meta_learner_summary.json") as f:
    meta_info = json.load(f)

weights = meta_info["ensemble_weights"]
labels = [f"{k}\n({v*100:.1f}%)" for k, v in weights.items()]
vals = list(weights.values())
colors = ["#3498db", "#f39c12", "#9b59b6", "#1abc9c"]

wedges, texts, autotexts = ax3.pie(
    vals, 
    labels=labels, 
    autopct="%1.1f%%", 
    startangle=140, 
    colors=colors,
    textprops=dict(color="black", fontsize=9),
    wedgeprops=dict(width=0.45, edgecolor="white", linewidth=2)
)
for at in autotexts:
    at.set_fontsize(8)
    at.set_weight("bold")
ax3.set_title("C. Meta-Learner Multi-View Stacking Weights (NNLS)", fontweight="bold")

# -------------------------------------------------------------
# Panel D: Top 10 Drivers of Criticality (TreeExplainer SHAP)
# -------------------------------------------------------------
ax4 = axes[1, 1]
with open("experiments/track4_shap_top10.json") as f:
    shap_data = json.load(f)

features = [d["feature"] for d in shap_data][::-1]
shap_vals = [d["mean_abs_shap"] for d in shap_data][::-1]

y_pos = np.arange(len(features))
bars = ax4.barh(y_pos, shap_vals, color="#e67e22", alpha=0.85, height=0.6)
ax4.set_yticks(y_pos)
ax4.set_yticklabels(features, fontsize=9)
ax4.set_xlabel("Mean |SHAP Value| (Impact on Criticality Score)")
ax4.set_title("D. Top 10 Criticality Drivers (SHAP Explanation)", fontweight="bold")
ax4.grid(axis="x", linestyle=":", alpha=0.6)

for bar in bars:
    w = bar.get_width()
    ax4.text(w + 0.002, bar.get_y() + bar.get_height()/2, f"{w:.4f}", va="center", ha="left", fontsize=8)

plt.tight_layout(rect=[0, 0.03, 1, 0.95])
plt.savefig("docs/figures/task_criticality_benchmark.png", dpi=300)
plt.savefig("figures/task_criticality_benchmark.png", dpi=300)
print("Saved figures to docs/figures/task_criticality_benchmark.png and figures/task_criticality_benchmark.png")
