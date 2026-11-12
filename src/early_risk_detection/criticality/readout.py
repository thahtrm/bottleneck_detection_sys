"""Readout head on [z_i(T0) || x_static] that turns the TGN memory snapshot into a criticality score.

z = Linear(4*128 + 5 -> 128)(memory snapshot)   (TGN embedding module, 128d z_i(T0))
Linear(In,128) -> BatchNorm1d -> ReLU -> Dropout(0.2) -> Linear(128,64) -> ReLU -> Linear(64,1) -> Sigmoid
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

LOG_COLS = ["summary_len", "word_count", "assignee_active_count", "assignee_wci", "assignee_hist_completed",
            "assignee_hist_cycle_time", "assignee_90d_completed", "reporter_hist_created", "reporter_hist_completed",
            "project_active_count", "project_90d_completed", "project_90d_cycle_time", "project_hist_created",
            "scf", "links_t0_any"] + \
           [f"{g}_blockers_before" for g in ["project", "reporter", "assignee", "instance"]] + \
           ["project_blockers_90d", "project_links_90d", "proj_prio_hist_n", "proj_type_hist_n", "inst_prio_hist_n"]
RAW_COLS = ["priority_t0", "planned_t0", "story_points_t0", "ambiguity_score", "tech_concurrency_risk",
            "tech_scope_risk", "umbrella_score", "is_unassigned_t0", "created_month", "created_dow", "created_hour",
            "assignee_hist_delay_rate", "assignee_90d_delay_rate", "reporter_hist_delay_rate",
            "project_90d_delay_rate"] + [f"svd_{k}" for k in range(16)] + \
           [f"{g}_blocker_rate_before" for g in ["project", "reporter", "assignee", "instance"]] + \
           [f"{g}_hist_{st}" for g in ["proj_prio", "proj_type", "inst_prio"] for st in ["slip_ratio", "long_rate", "log_dur"]]
THEMES = ["Maintenance", "Requirements", "Development", "Other", "User Support"]


def static_matrix(df: pd.DataFrame, instances: list[str], types: list[str]) -> tuple[np.ndarray, list[str]]:
    cols = [np.log1p(df[c].values.astype(np.float32).clip(min=0)) for c in LOG_COLS]
    cols += [df[c].values.astype(np.float32) for c in RAW_COLS]
    cols += [(df["issuetype_theme_t0"].values == t).astype(np.float32) for t in THEMES]
    cols += [(df["instance"].values == i).astype(np.float32) for i in instances]
    cols += [(df["issuetype_t0"].values == t).astype(np.float32) for t in types]
    names = [f"log_{c}" for c in LOG_COLS] + RAW_COLS + [f"theme_{t}" for t in THEMES] + \
        [f"inst_{i}" for i in instances] + [f"type_{t}" for t in types]
    return np.nan_to_num(np.stack(cols, 1), nan=0.0, posinf=0.0, neginf=0.0), names


class Readout(nn.Module):
    def __init__(self, n_static: int, use_z: bool, z_in: int = 4 * 128 + 5, dropout: float = 0.2):
        super().__init__()
        self.use_z = use_z
        self.embed = nn.Sequential(nn.Linear(z_in, 128), nn.LayerNorm(128), nn.ReLU()) if use_z else None
        d = n_static + (128 if use_z else 0)
        self.trunk = nn.Sequential(nn.Linear(d, 128), nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(dropout),
                                   nn.Linear(128, 64), nn.ReLU())
        self.out = nn.Linear(64, 1)
        self.aux = nn.Linear(64, 2)  # auxiliary: future-blocker logit, slip-ratio logit (training only)

    def z(self, zr: torch.Tensor) -> torch.Tensor:
        return self.embed(zr)

    def forward(self, xs: torch.Tensor, zr: torch.Tensor | None, with_aux: bool = False):
        h = self.trunk(torch.cat([self.z(zr), xs], 1) if self.use_z else xs)
        score = torch.sigmoid(self.out(h)).squeeze(1)
        return (score, self.aux(h)) if with_aux else score


@torch.no_grad()
def predict_scores(models: list[Readout], x: np.ndarray, z: np.ndarray | None, device: torch.device,
                   batch: int = 65536) -> np.ndarray:
    """Mean score of a seed ensemble; ``x`` is the normalised static matrix, ``z`` the normalised snapshot."""
    out = []
    for m in models:
        m.eval()
        s = []
        for b in range(0, len(x), batch):
            xs = torch.from_numpy(np.ascontiguousarray(x[b:b + batch])).to(device)
            zr = torch.from_numpy(np.ascontiguousarray(z[b:b + batch])).to(device).float() if m.use_z else None
            s.append(m(xs, zr))
        out.append(torch.cat(s).cpu().numpy())
    return np.mean(out, 0)
