"""Pre-triage gate: is a new issue 'non-work' (duplicate / invalid / won't fix ...) rather than real work?

Two causal (T0-safe) signal families feed the gate models:

* :func:`causal_nonwork_features` - rolling 90-day non-work rate of the project, project x type,
  reporter, assignee (T0) and instance, from resolutions strictly before T0, plus the project's
  90-day resolution volume (6 columns, ``CAUSAL_NW_COLUMNS``).
* :func:`semantic_knn_features` - cosine similarity of the issue's embedding to (a) the last
  ``active_window`` issues of its project still open at T0 and (b) the ``resolved_pool`` issues
  of its project most recently resolved before T0, plus the similarity-weighted non-work rate
  of the ``k`` nearest resolved neighbours (4 columns, ``SEM_KNN_COLUMNS``).

Both are defined per issue (independent of which other issues are queried together), so
training (all rows) and serving (a few rows) compute identical values.

This module re-implements the gate of the delay study, whose feature producer was not kept;
see ``training/delay/train_non_work.py`` for the models trained on these signals.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pandas as pd
import torch

from ..features.t0 import history_before

logger = logging.getLogger(__name__)

NONWORK_PATTERN = (r"duplicate|not a bug|cannot reproduce|will not|won't|invalid|rejected|works as intended|"
                   r"not a problem|automatically closed|incomplete|obsolete|not applicable|by design|timed out|"
                   r"awaiting response")
CAUSAL_NW_COLUMNS = ["nw90_project", "nw90_project_type", "nw90_reporter", "nw90_assignee", "nw90_instance",
                     "log_project_resolved_90d"]
SEM_KNN_COLUMNS = ["max_sim_active", "n_similar_active", "max_sim_resolved", "knn_nonwork_rate"]


def nonwork_labels(resolution: pd.Series) -> np.ndarray:
    return resolution.fillna("Done").str.lower().str.contains(NONWORK_PATTERN, regex=True, na=False).values.astype(np.int8)


def _codes(*cols) -> np.ndarray:
    return pd.MultiIndex.from_arrays(list(cols)).factorize()[0].astype(np.int64) if len(cols) > 1 \
        else pd.factorize(cols[0])[0].astype(np.int64)


def causal_nonwork_features(df: pd.DataFrame, nonwork: np.ndarray, prior: float,
                            smoothing: float = 5.0, window_days: float = 90.0) -> np.ndarray:
    """(N, 6) float32. ``df`` = ``load_issues_t0`` output; ``nonwork`` = label of resolved rows (ignored for open ones)."""
    inst = df["instance"].values
    prj = df["project"].fillna("APP").values
    groups = [_codes(inst, prj), _codes(inst, prj, df["issuetype_t0"].fillna("?").values),
              _codes(inst, df["reporter"].fillna("(unknown)").values), _codes(inst, df["assignee_t0"].values),
              _codes(inst)]
    res = np.flatnonzero(df["is_resolved"].values == 1)
    r_ts = df["resolved_ts"].values[res].astype(np.float64)
    created = df["created_ts"].values.astype(np.float64)
    nw = nonwork[res].astype(np.float64)
    out = np.zeros((len(df), 6), np.float32)
    w = window_days * 86400.0
    for j, code in enumerate(groups):
        cnt, (s,) = history_before(code[res], r_ts, [nw], code, created, window=w)
        out[:, j] = (s + smoothing * prior) / (cnt + smoothing)
        if j == 0:
            out[:, 5] = np.log1p(cnt)
    return out


@torch.no_grad()
def semantic_knn_features(df: pd.DataFrame, nonwork: np.ndarray, get_embeddings: Callable[[np.ndarray], np.ndarray],
                          query_rows: np.ndarray | None = None, prior: float = 0.4, active_window: int = 256,
                          resolved_pool: int = 4096, k: int = 10, dup_sim: float = 0.90,
                          device: torch.device | None = None, chunk: int = 512) -> np.ndarray:
    """(len(query_rows), 4) float32, see module docstring.

    ``get_embeddings(rows)`` returns the 768-d embeddings of the given ``row_id`` s; only the
    queried issues and their candidate pools are fetched.
    """
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    n = len(df)
    query_rows = np.arange(n) if query_rows is None else np.asarray(query_rows, np.int64)
    out = np.zeros((len(query_rows), 4), np.float32)
    out[:, 3] = prior
    created = df["created_ts"].values.astype(np.float64)
    resolved = df["resolved_ts"].fillna(np.inf).values.astype(np.float64)
    grp = _codes(df["instance"].values, df["project"].fillna("APP").values)
    q_pos = np.full(n, -1, np.int64)
    q_pos[query_rows] = np.arange(len(query_rows))
    q_grp = np.unique(grp[query_rows])
    order = np.argsort(grp, kind="stable")  # rows of each group, in creation (row_id) order
    bounds = np.searchsorted(grp[order], np.arange(grp.max() + 2))
    for gi, g in enumerate(q_grp):
        rows = order[bounds[g]:bounds[g + 1]]
        qmask = q_pos[rows] >= 0
        if not qmask.any():
            continue
        r_created, r_resolved = created[rows], resolved[rows]
        res_order = np.argsort(r_resolved, kind="stable")
        n_res = int(np.isfinite(r_resolved).sum())
        res_order = res_order[:n_res]
        res_ts_sorted = r_resolved[res_order]
        qp = np.flatnonzero(qmask)  # positions (within group) of queried issues
        n_before_all = np.searchsorted(res_ts_sorted, r_created[qp], side="left")  # resolved strictly before T0
        # positions needed: queried issues + their active windows + their resolved pools (interval unions)
        d_act = np.zeros(len(rows) + 1, np.int64)
        np.add.at(d_act, np.maximum(0, qp - active_window), 1)
        np.add.at(d_act, qp + 1, -1)
        d_res = np.zeros(n_res + 1, np.int64)
        np.add.at(d_res, np.maximum(0, n_before_all - resolved_pool), 1)
        np.add.at(d_res, n_before_all, -1)
        need = np.cumsum(d_act)[:-1] > 0
        need[res_order[np.cumsum(d_res)[:-1] > 0]] = True
        need_pos = np.flatnonzero(need)
        emb = torch.from_numpy(get_embeddings(rows[need_pos]).astype(np.float32)).to(device)
        emb = torch.nn.functional.normalize(emb, dim=1)
        slot = np.full(len(rows), -1, np.int64)
        slot[need_pos] = np.arange(len(need_pos))
        nw_g = torch.from_numpy(nonwork[rows].astype(np.float32)).to(device)
        res_slot = torch.from_numpy(slot[res_order]).to(device)
        # chunks of <= `chunk` queries spanning <= 4*chunk positions (sparse serving queries stay small)
        starts = [0]
        for i in range(1, len(qp)):
            if i - starts[-1] >= chunk or qp[i] - qp[starts[-1]] > 4 * chunk:
                starts.append(i)
        for c, c_end in zip(starts, starts[1:] + [len(qp)]):
            P = qp[c:c_end]
            Q = emb[torch.from_numpy(slot[P]).to(device)]
            t_q = torch.from_numpy(r_created[P]).to(device)
            # (a) active window: previous `active_window` issues created before T0 and still open at T0
            a0 = max(0, int(P[0]) - active_window)
            cand = np.arange(a0, int(P[-1]))
            if len(cand):
                S = Q @ emb[torch.from_numpy(slot[cand]).to(device)].T
                cp = torch.from_numpy(cand).to(device)
                pp = torch.from_numpy(P).to(device)
                valid = (cp[None, :] < pp[:, None]) & (cp[None, :] >= pp[:, None] - active_window)
                valid &= torch.from_numpy(r_created[cand]).to(device)[None, :] < t_q[:, None]
                valid &= torch.from_numpy(r_resolved[cand]).to(device)[None, :] > t_q[:, None]
                S = torch.where(valid, S, torch.full_like(S, -2.0))
                mx = S.max(1).values
                out[q_pos[rows[P]], 0] = torch.clamp(mx, min=0.0).cpu().numpy()
                out[q_pos[rows[P]], 1] = ((S >= dup_sim) & valid).sum(1).float().cpu().numpy()
            # (b) resolved pool: the `resolved_pool` most recently resolved before each T0
            nbq = n_before_all[c:c_end]
            r_lo, r_hi = max(0, int(nbq.min()) - resolved_pool), int(nbq.max())
            if r_hi > r_lo:
                S = Q @ emb[res_slot[r_lo:r_hi]].T
                ridx = torch.arange(r_lo, r_hi, device=device)
                nbt = torch.from_numpy(nbq).to(device)
                valid = (ridx[None, :] < nbt[:, None]) & (ridx[None, :] >= nbt[:, None] - resolved_pool)
                S = torch.where(valid, S, torch.full_like(S, -2.0))
                kk = min(k, S.shape[1])
                top, ti = S.topk(kk, dim=1)
                ok = top > -2.0
                wts = torch.clamp(top, min=0.0) * ok
                lab = nw_g[torch.from_numpy(res_order[r_lo:r_hi]).to(device)][ti]
                rate = (wts * lab).sum(1) / wts.sum(1).clamp(min=1e-6)
                rate = torch.where(wts.sum(1) > 0, rate, torch.full_like(rate, prior))
                out[q_pos[rows[P]], 2] = torch.clamp(top[:, 0], min=0.0).cpu().numpy() * ok[:, 0].cpu().numpy()
                out[q_pos[rows[P]], 3] = rate.cpu().numpy()
        if gi % 200 == 0:
            logger.info(f"  [semantic kNN] project group {gi:,}/{len(q_grp):,}")
    return out


def gate_mask(p_early_nonwork: np.ndarray, max_sim_resolved: np.ndarray, p_threshold: float,
              sim_threshold: float) -> np.ndarray:
    """Issues the pre-triage gate treats as probable non-work (their delay probability is damped)."""
    return (p_early_nonwork >= p_threshold) | (max_sim_resolved >= sim_threshold)
