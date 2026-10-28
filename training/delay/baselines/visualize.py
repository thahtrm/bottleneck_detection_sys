"""Tạo các biểu đồ so sánh trực quan cho các Track Mô hình Cốt lõi trên Out-of-Time Test Set:
- figures/pr_roc_curves.png
- figures/confusion_matrices.png
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
ARTIFACT_DIR = Path("/home/jiooum/.gemini/antigravity/brain/37355967-0fbb-4de6-9070-8598b73639b0")


def main():
    with open("experiments/leaderboard.json", encoding="utf-8") as f:
        leaderboard = json.load(f)

    tracks = {
        "Track 1: XGBoost (Binary)": {
            "file": "experiments/xgboost/predictions_test.csv",
            "color": "#1f77b4",
            "key": "xgboost",
        },
        "Track 2: XGBoost Survival AFT": {
            "file": "experiments/survival_aft/predictions_test.csv",
            "color": "#d62728",
            "key": "survival_aft",
        },
        "Track 3a: CatBoost Survival AFT": {
            "file": "experiments/catboost_survival/predictions_test.csv",
            "color": "#2ca02c",
            "key": "catboost_survival",
        },
        "Track 3b: CatBoost Competing Risks": {
            "file": "experiments/catboost_competing_risks/predictions_test.csv",
            "color": "#9467bd",
            "key": "catboost_competing_risks",
        },
        "Track 4: CatBoost Cox (Breslow)": {
            "file": "experiments/catboost_cox/predictions_test.csv",
            "color": "#ff7f0e",
            "key": "catboost_cox",
        },
    }

    data = {}
    for name, meta in tracks.items():
        if os.path.exists(meta["file"]):
            df = pd.read_csv(meta["file"])
            thr = leaderboard.get(meta["key"], {}).get("optimal_threshold", 0.5)
            f1 = leaderboard.get(meta["key"], {}).get("test_metrics", {}).get("f1_score", 0.0)
            data[name] = {"df": df, "color": meta["color"], "thr": thr, "f1": f1}

    if not data:
        print("No track predictions found yet.")
        return

    # 1. Plot PR & ROC Curves
    fig, (ax_pr, ax_roc) = plt.subplots(1, 2, figsize=(14, 6))
    for name, d in data.items():
        y_true = d["df"]["y_true"].values
        y_prob = d["df"]["y_prob"].values
        color = d["color"]
        f1 = d["f1"]

        p, r, _ = precision_recall_curve(y_true, y_prob)
        if len(p) > 2000:
            idx = np.linspace(0, len(p) - 1, 2000).astype(int)
            p, r = p[idx], r[idx]
        ax_pr.plot(r, p, label=f"{name} (F1={f1:.4f})", color=color, linewidth=2.0)

        fpr, tpr, _ = roc_curve(y_true, y_prob)
        if len(fpr) > 2000:
            idx = np.linspace(0, len(fpr) - 1, 2000).astype(int)
            fpr, tpr = fpr[idx], tpr[idx]
        ax_roc.plot(fpr, tpr, label=f"{name}", color=color, linewidth=2.0)

    ax_pr.set_xlabel("Recall")
    ax_pr.set_ylabel("Precision")
    ax_pr.set_title("Precision-Recall Curves (Out-of-Time Test Set)")
    ax_pr.legend(loc="lower left", frameon=True)
    ax_pr.set_xlim([0.0, 1.02])
    ax_pr.set_ylim([0.25, 1.02])

    ax_roc.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Random Chance")
    ax_roc.set_xlabel("False Positive Rate")
    ax_roc.set_ylabel("True Positive Rate")
    ax_roc.set_title("ROC Curves (Out-of-Time Test Set)")
    ax_roc.legend(loc="lower right", frameon=True)
    ax_roc.set_xlim([-0.02, 1.02])
    ax_roc.set_ylim([-0.02, 1.02])

    plt.tight_layout()
    pr_roc_path = FIG_DIR / "pr_roc_curves.png"
    plt.savefig(pr_roc_path, dpi=300)
    if ARTIFACT_DIR.exists():
        shutil.copy(pr_roc_path, ARTIFACT_DIR / "pr_roc_curves.png")
    plt.close()

    # 2. Plot Confusion Matrices
    fig, axes = plt.subplots(1, len(data), figsize=(4.2 * len(data), 4.0))
    if len(data) == 1:
        axes = [axes]

    for ax, (name, d) in zip(axes, data.items()):
        y_true = d["df"]["y_true"].values
        y_prob = d["df"]["y_prob"].values
        thr = d["thr"]
        y_pred = (y_prob >= thr).astype(int)
        cm = confusion_matrix(y_true, y_pred)

        ax.imshow(cm, cmap="Blues", interpolation="nearest")
        ax.set_title(f"{name}\n(T* = {thr:.2f})", fontsize=10.5)
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["On-time", "Delayed"])
        ax.set_yticklabels(["On-time", "Delayed"])
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")

        for i in range(2):
            for j in range(2):
                color = "white" if cm[i, j] > cm.max() / 2 else "black"
                ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center", color=color, fontweight="bold")

    plt.tight_layout()
    cm_path = FIG_DIR / "confusion_matrices.png"
    plt.savefig(cm_path, dpi=300)
    if ARTIFACT_DIR.exists():
        shutil.copy(cm_path, ARTIFACT_DIR / "confusion_matrices.png")
    plt.close()
    print("✅ Saved PR/ROC curves and Confusion Matrices.", flush=True)


if __name__ == "__main__":
    main()
