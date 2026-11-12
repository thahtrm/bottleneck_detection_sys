"""Unified Dual-Head TGN (1 TGN Backbone -> 2 Heads: Task Criticality & Task Delay Risk/Survival).

Architecture:
  Shared TGN Memory Backbone:
    TGNMemory (128-d per node over issues, users, projects, status/priority value nodes)
    Snapshot at project change t_change: Z_i(t) in R^{512} + rich temporal aux in R^{10} -> 522-d
  Shared Encoder:
    z_embed: Linear(522 -> 192) -> LayerNorm -> SiLU
    shared_trunk: Linear(192 + 119 -> 256) -> BatchNorm1d -> SiLU -> Dropout -> Linear(256 -> 128) -> BatchNorm1d -> SiLU
  Head 1 (Task Criticality & Top-5% P0 Ranking):
    crit_tower([shared_h(128) || z_embed(192)]) -> Linear(320 -> 128) -> BN -> SiLU -> Dropout -> Linear(128 -> 64) -> SiLU
    crit_out: Linear(64 -> 1) -> Sigmoid (criticality_score)
    crit_aux: Linear(64 -> 2) (future_blocker logit, slip_ratio logit)
  Head 2 (Task Delay Risk Probability & Right-Censored AFT Duration):
    delay_tower([shared_h(128) || xs(119)]) -> Linear(247 -> 128) -> BN -> SiLU -> Dropout -> Linear(128 -> 64) -> SiLU
    delay_logit: Linear(64 -> 1) -> Sigmoid (p_delay_bce)
    aft_mu: Linear(64 -> 1) (predicted log-duration in days, trained with Right-Censored AFT loss)
    p_delay = 0.65 * p_delay_bce + 0.35 * S_aft(planned_duration | aft_mu, sigma)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .memory import MEM, EventStream, TGNMemory, _sub_chunk

logger = logging.getLogger(__name__)

N_AUX_DUAL = 10


@torch.no_grad()
def snapshot_memory_dual(
    model: TGNMemory,
    stream: EventStream,
    t_snap: np.ndarray,
    created: np.ndarray,
    planned_days: np.ndarray,
    neigh: np.ndarray,
    rows: np.ndarray | None = None,
    z_out: np.ndarray | None = None,
    pre_t0_mode: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Replay the event stream and extract (Z, aux_10d, applied_last) for Dual-Head TGN.

    aux_10d columns:
      0..3: log1p((t_snap - last_ts[issue, reporter, assignee, project]) / 3600)
      4:    log1p(n_upd[reporter])
      5:    log1p(n_upd[issue])
      6:    log1p(n_upd[assignee])
      7:    log1p((t_snap - created_ts) / 3600)          (elapsed open hours at event t_snap)
      8:    clip(((t_snap - created_ts)/86400) / planned_days, 0, 5)  (elapsed SLA fraction)
      9:    float(curr_assignee != assignee_t0)          (whether reassigned by t_snap)
    """
    n_issue = len(t_snap)
    rows = np.arange(n_issue, dtype=np.int64) if rows is None else np.asarray(rows, np.int64)
    Z = z_out if z_out is not None else np.zeros((len(rows), 4 * MEM), np.float16)
    aux = np.zeros((len(rows), N_AUX_DUAL), np.float32)
    applied_last = np.full(len(rows), -np.inf)

    n_chunks = len(stream.starts)
    snap_chunk_all = np.minimum(np.searchsorted(stream.max_ts, t_snap, side="left"), n_chunks - 1)
    if pre_t0_mode:
        snap_chunk_all = np.searchsorted(stream.max_ts, created, side="left")
    snap_chunk = snap_chunk_all[rows]
    order = np.argsort(snap_chunk, kind="stable")
    bounds = np.searchsorted(snap_chunk[order], np.arange(n_chunks + 2))
    last_needed = int(snap_chunk.max()) if len(rows) else -1

    neigh_t0 = torch.from_numpy(neigh.astype(np.int64)).to(model.device)
    neigh_t = neigh_t0.clone()
    t_snap_dev = torch.from_numpy(t_snap.astype(np.float64)).to(model.device)
    sc_dev = torch.from_numpy(snap_chunk_all.astype(np.int64)).to(model.device)

    model.reset()
    model.eval()
    cur_max = -np.inf
    t0 = time.time()

    for c in range(n_chunks + 1):
        if pre_t0_mode:
            k = order[bounds[c] : bounds[c + 1]]
            if len(k):
                idx = rows[k]
                it = torch.from_numpy(idx).to(model.device)
                nb = neigh_t0[it]
                parts, dts = [model.mem[it]], [model.last[it]]
                for j in range(3):
                    q = nb[:, j].clamp(min=0)
                    ok = (nb[:, j] >= 0).unsqueeze(1)
                    parts.append(torch.where(ok, model.mem[q], torch.zeros_like(model.mem[q])))
                    dts.append(torch.where(nb[:, j] >= 0, model.last[q], torch.full_like(model.last[q], -1.0)))
                Z[k] = torch.cat(parts, 1).half().cpu().numpy()
                t_now = torch.from_numpy(created[idx]).to(model.device)
                for j, d in enumerate(dts):
                    aux[k, j] = (
                        torch.where(d < 0, torch.full_like(d, 12.0), torch.log1p((t_now - d).clamp(min=0) / 3600.0))
                        .float()
                        .cpu()
                        .numpy()
                    )
                aux[k, 4] = torch.log1p(model.n_upd[nb[:, 0].clamp(min=0)].float()).cpu().numpy()
                aux[k, 5] = 0.0
                aux[k, 6] = torch.log1p(
                    torch.where(nb[:, 1] >= 0, model.n_upd[nb[:, 1].clamp(min=0)], torch.zeros_like(nb[:, 1])).float()
                ).cpu().numpy()
                aux[k, 7] = 0.0
                aux[k, 8] = 0.0
                aux[k, 9] = 0.0
                applied_last[k] = cur_max
            if c == n_chunks or c >= last_needed:
                break
            ch = stream.get(c)
            model.commit(*model.apply(model.raw_messages(ch)))
            cur_max = float(stream.max_ts[c])
            continue

        if c >= n_chunks or c > last_needed:
            break
        ch = stream.get(c)
        u, v, ts, kind, scat = ch["u"], ch["v"], ch["ts"], ch["kind"], ch["scat"]
        v_safe = v.clamp(max=n_issue - 1)
        u_ok = (sc_dev[u] < c) | ((ts <= t_snap_dev[u]) & (scat != 0))
        v_ok = (kind != 4) | (v >= n_issue) | (sc_dev[v_safe] < c) | (ts <= t_snap_dev[v_safe])
        pre_mask = u_ok & v_ok
        if pre_mask.any():
            ch_pre = _sub_chunk(ch, pre_mask)
            model.commit(*model.apply(model.raw_messages(ch_pre)))
            m_ass = ch_pre["kind"] == 1
            if m_ass.any():
                neigh_t[ch_pre["u"][m_ass], 1] = ch_pre["v"][m_ass]

        k = order[bounds[c] : bounds[c + 1]]
        if len(k):
            idx = rows[k]
            it = torch.from_numpy(idx).to(model.device)
            nb = neigh_t[it]
            nb0 = neigh_t0[it]
            parts, dts = [model.mem[it]], [model.last[it]]
            for j in range(3):
                q = nb[:, j].clamp(min=0)
                ok = (nb[:, j] >= 0).unsqueeze(1)
                parts.append(torch.where(ok, model.mem[q], torch.zeros_like(model.mem[q])))
                dts.append(torch.where(nb[:, j] >= 0, model.last[q], torch.full_like(model.last[q], -1.0)))
            Z[k] = torch.cat(parts, 1).half().cpu().numpy()
            t_now = torch.from_numpy(t_snap[idx]).to(model.device)
            for j, d in enumerate(dts):
                aux[k, j] = (
                    torch.where(d < 0, torch.full_like(d, 12.0), torch.log1p((t_now - d).clamp(min=0) / 3600.0))
                    .float()
                    .cpu()
                    .numpy()
                )
            aux[k, 4] = torch.log1p(model.n_upd[nb[:, 0].clamp(min=0)].float()).cpu().numpy()
            aux[k, 5] = torch.log1p(model.n_upd[it].float()).cpu().numpy()
            aux[k, 6] = torch.log1p(
                torch.where(nb[:, 1] >= 0, model.n_upd[nb[:, 1].clamp(min=0)], torch.zeros_like(nb[:, 1])).float()
            ).cpu().numpy()
            el_sec = np.maximum(0.0, t_snap[idx] - created[idx])
            aux[k, 7] = np.log1p(el_sec / 3600.0).astype(np.float32)
            aux[k, 8] = np.clip((el_sec / 86400.0) / np.maximum(1.0, planned_days[idx]), 0.0, 5.0).astype(np.float32)
            aux[k, 9] = (nb[:, 1] != nb0[:, 1]).float().cpu().numpy()
            applied_last[k] = dts[0].cpu().numpy()

        post_mask = ~pre_mask
        if post_mask.any():
            ch_post = _sub_chunk(ch, post_mask)
            model.commit(*model.apply(model.raw_messages(ch_post)))
            m_ass = ch_post["kind"] == 1
            if m_ass.any():
                neigh_t[ch_post["u"][m_ass], 1] = ch_post["v"][m_ass]

        if c % 400 == 0:
            logger.info(f"    dual-head snapshot pass chunk {c}/{n_chunks} ({time.time() - t0:.0f}s)")
    return Z, aux, applied_last


class DualHeadReadout(nn.Module):
    """Single TGN Readout with 2 specialized heads:
      - Head 1: Criticality score & Top-5% P0 ranking
      - Head 2: Delay risk probability & Right-Censored AFT duration prediction
    """

    def __init__(self, n_static: int, z_in: int = 4 * MEM + N_AUX_DUAL, dropout: float = 0.2):
        super().__init__()
        self.z_embed = nn.Sequential(
            nn.Linear(z_in, 192),
            nn.LayerNorm(192),
            nn.SiLU(),
        )
        self.shared_trunk = nn.Sequential(
            nn.Linear(192 + n_static, 256),
            nn.BatchNorm1d(256),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(256, 128),
            nn.BatchNorm1d(128),
            nn.SiLU(),
        )
        # Head 1: Criticality Tower (receives shared_trunk + skip connection from z_embed)
        self.crit_tower = nn.Sequential(
            nn.Linear(128 + 192, 128),
            nn.BatchNorm1d(128),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.SiLU(),
        )
        self.crit_out = nn.Linear(64, 1)
        self.crit_aux = nn.Linear(64, 2)  # [future_blocker_logit, slip_ratio_logit]

        # Head 2: Delay & Survival AFT Tower (receives shared_trunk + skip connection from static/workload xs)
        self.delay_tower = nn.Sequential(
            nn.Linear(128 + n_static, 128),
            nn.BatchNorm1d(128),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.SiLU(),
        )
        self.delay_logit = nn.Linear(64, 1)
        self.aft_mu = nn.Linear(64, 1)  # predicted log(duration_days)
        self.aft_log_sigma = nn.Parameter(torch.tensor(-0.2))

    @property
    def aft_sigma(self) -> torch.Tensor:
        return F.softplus(self.aft_log_sigma) + 0.35

    def forward(
        self,
        xs: torch.Tensor,
        zr: torch.Tensor,
        log_planned: torch.Tensor | None = None,
        with_aux: bool = False,
    ) -> dict[str, torch.Tensor]:
        ze = self.z_embed(zr)
        h_shared = self.shared_trunk(torch.cat([ze, xs], dim=1))

        # Head 1: Criticality
        h_crit = self.crit_tower(torch.cat([h_shared, ze], dim=1))
        crit_score = torch.sigmoid(self.crit_out(h_crit)).squeeze(1)

        # Head 2: Delay Risk & Duration
        h_delay = self.delay_tower(torch.cat([h_shared, xs], dim=1))
        d_logit = self.delay_logit(h_delay).squeeze(1)
        p_bce = torch.sigmoid(d_logit)
        mu = self.aft_mu(h_delay).squeeze(1).clamp(-4.0, 9.0)
        sigma = self.aft_sigma
        if log_planned is not None:
            # Logistic AFT survival probability P(T > planned_duration)
            p_aft = torch.sigmoid((mu - log_planned) / sigma)
            p_delay = 0.65 * p_bce + 0.35 * p_aft
        else:
            p_aft = p_bce
            p_delay = p_bce

        out = {
            "crit_score": crit_score,
            "delay_prob": p_delay,
            "delay_logit": d_logit,
            "aft_mu": mu,
            "p_aft": p_aft,
        }
        if with_aux:
            out["crit_aux"] = self.crit_aux(h_crit)
        return out


def aft_logistic_loss(
    mu: torch.Tensor,
    sigma: torch.Tensor,
    log_t_lower: torch.Tensor,
    is_resolved: torch.Tensor,
) -> torch.Tensor:
    """Right-censored Logistic AFT negative log-likelihood.

    For resolved issues (is_resolved == 1): exact density f(y) where z = (y - mu)/sigma,
      -log f(y) = log(sigma) + z + 2 * softplus(-z)
    For right-censored open issues (is_resolved == 0): survival S(y_lower) = sigmoid((mu - y_lower)/sigma),
      -log S(y_lower) = softplus((y_lower - mu) / sigma)
    """
    z = (log_t_lower - mu) / sigma
    nll_uncensored = torch.log(sigma) + z + 2.0 * F.softplus(-z)
    nll_censored = F.softplus(z)
    loss = torch.where(is_resolved > 0.5, nll_uncensored, nll_censored)
    return loss.mean()


@torch.no_grad()
def predict_dual_ensemble(
    models: list[DualHeadReadout],
    x: np.ndarray,
    z: np.ndarray,
    log_planned: np.ndarray,
    device: torch.device,
    batch: int = 65536,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ensemble-averaged (crit_score, delay_prob, pred_duration_days)."""
    crit_all, delay_all, dur_all = [], [], []
    for m in models:
        m.eval()
        cs, ds, mus = [], [], []
        for b in range(0, len(x), batch):
            xs = torch.from_numpy(np.ascontiguousarray(x[b : b + batch])).to(device)
            zr = torch.from_numpy(np.ascontiguousarray(z[b : b + batch])).to(device).float()
            lp = torch.from_numpy(np.ascontiguousarray(log_planned[b : b + batch])).to(device)
            res = m(xs, zr, log_planned=lp, with_aux=False)
            cs.append(res["crit_score"].cpu().numpy())
            ds.append(res["delay_prob"].cpu().numpy())
            mus.append(torch.exp(res["aft_mu"]).cpu().numpy())
        crit_all.append(np.concatenate(cs))
        delay_all.append(np.concatenate(ds))
        dur_all.append(np.concatenate(mus))
    return np.mean(crit_all, axis=0), np.mean(delay_all, axis=0), np.mean(dur_all, axis=0)


DUAL_HEAD_KIND = "dual_head_tgn"
DEFAULT_BUNDLE_PATH = "bundles/tgn_dual_head"

CRITICALITY_COLUMNS = [
    "uid",
    "instance",
    "issue_key",
    "project",
    "created_ts",
    "score",
    "rank_in_instance",
    "is_critical",
]

DELAY_COLUMNS = [
    "uid",
    "instance",
    "issue_key",
    "project",
    "created_ts",
    "planned_duration_days",
    "predicted_duration_days",
    "p_delay",
    "is_at_risk",
    "p_delay_raw",
    "gated",
    "p_non_work",
    "p_early_non_work",
    "max_sim_resolved",
]

DUAL_COLUMNS = [
    "uid",
    "instance",
    "issue_key",
    "project",
    "created_ts",
    "score",
    "rank_in_instance",
    "is_critical",
    "planned_duration_days",
    "predicted_duration_days",
    "p_delay",
    "is_at_risk",
    "p_delay_raw",
    "gated",
    "p_non_work",
    "p_early_non_work",
    "max_sim_resolved",
]


class DualHeadScorer:
    """Default unified TGN scorer (1 TGN Backbone -> 2 Heads: Task Criticality & Delay Risk/Survival)."""

    def __init__(self, bundle, device: str | torch.device | None = None):
        self.bundle = bundle
        cfg = bundle.config
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        st = bundle.load_arrays("normalizers.npz")
        self.mu, self.sd, self.amu, self.asd = st["mu"], st["sd"], st["amu"], st["asd"]
        self.svd_components = st["svd_components"]
        self.instances, self.types = cfg["instances"], cfg["types"]
        self.backoff = cfg["propensity_backoff"]
        self.top_pct = float(cfg.get("top_pct", 0.05))
        self.threshold_max_f1 = float(cfg.get("delay_threshold_max_f1", 0.65))
        self.threshold_high_recall = float(cfg.get("delay_threshold_high_recall", 0.55))
        n_aux = int(cfg.get("n_aux", N_AUX_DUAL))
        self.readouts: list[DualHeadReadout] = []
        for name in cfg["readout_files"]:
            m = DualHeadReadout(
                len(cfg["static_features"]),
                z_in=4 * MEM + n_aux,
                dropout=float(cfg.get("dropout", 0.2)),
            ).to(self.device)
            m.load_state_dict(torch.load(bundle.file(name), map_location=self.device))
            self.readouts.append(m.eval())

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_BUNDLE_PATH,
        device: str | torch.device | None = None,
    ) -> DualHeadScorer:
        from ..bundle import ModelBundle

        return cls(ModelBundle.load(path, kind=DUAL_HEAD_KIND), device)

    @property
    def threshold(self) -> float:
        return self.threshold_high_recall

    def score(
        self,
        duckdb_path: str | Path,
        embeddings,
        issue_keys: list[str] | None = None,
        as_of: float | None = None,
        open_only: bool = True,
        stream_dir: str | Path | None = None,
        top_pct: float | None = None,
        delay_threshold: float | None = None,
        at_project_change: bool | None = None,
    ):
        """Score both Task Criticality (Head 1) and Task Delay Risk & Duration (Head 2) in a single pass."""
        import tempfile

        import duckdb
        import pandas as pd

        from ..embeddings import embed_issues
        from ..features.t0 import (
            add_t0_features,
            issue_durations,
            load_issues_t0,
            load_timed_links,
            select_issues,
        )
        from .readout import static_matrix
        from .stream import build_event_stream

        cfg = self.bundle.config
        top_pct = self.top_pct if top_pct is None else float(top_pct)
        thr = self.threshold if delay_threshold is None else float(delay_threshold)
        if at_project_change is None:
            at_project_change = bool(cfg.get("project_change_mode", True))

        con = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            logger.info("Loading issues and T0 attributes...")
            df = load_issues_t0(con)
            links = load_timed_links(con)
            sel = select_issues(df, issue_keys, as_of, open_only)
            logger.info(f"{len(df):,} issues in database, {len(sel):,} selected for dual-head scoring")
            if len(sel) == 0:
                return pd.DataFrame(columns=DUAL_COLUMNS)
            logger.info("T0 features...")
            add_t0_features(df, links, issue_durations(df), backoff=self.backoff)
            with tempfile.TemporaryDirectory() as tmp:
                sdir = Path(stream_dir) if stream_dir else Path(tmp)
                if not (sdir / "meta.json").exists():
                    logger.info(f"Building event stream in {sdir}...")
                    build_event_stream(con, df, sdir)
                z, t_snap_sel = self._memory_snapshots(
                    df, sel, sdir, as_of=as_of, at_project_change=at_project_change
                )
        finally:
            con.close()

        sub = df.iloc[sel].reset_index(drop=True)
        text_emb = embed_issues(embeddings, sub).astype(np.float32)
        svd = text_emb @ self.svd_components.T
        for k in range(svd.shape[1]):
            sub[f"svd_{k}"] = svd[:, k]
        x, _ = static_matrix(sub, self.instances, self.types)
        x = ((x - self.mu) / self.sd).astype(np.float32)

        planned = sub["planned_t0"].values.astype(np.float32)
        log_planned = np.log(np.maximum(1.0, planned)).astype(np.float32)
        crit_scores, delay_probs, pred_dur_days = predict_dual_ensemble(
            self.readouts, x, z, log_planned, self.device
        )
        elapsed_days = np.maximum(
            0.0, (t_snap_sel - sub["created_ts"].values.astype(np.float64)) / 86400.0
        ).astype(np.float32)
        pred_dur_days = np.maximum(pred_dur_days.astype(np.float32), elapsed_days)

        out = pd.DataFrame(
            {
                "uid": sub["instance"] + "|" + sub["issue_key"],
                "instance": sub["instance"],
                "issue_key": sub["issue_key"],
                "project": sub["project"],
                "created_ts": sub["created_ts"],
                "score": crit_scores.astype(np.float32),
            }
        )
        out["rank_in_instance"] = (
            out.groupby("instance")["score"].rank(ascending=False, method="first").astype(int)
        )
        n_inst = out.groupby("instance")["score"].transform("size")
        out["is_critical"] = out["rank_in_instance"] <= np.ceil(top_pct * n_inst)
        out["planned_duration_days"] = planned
        out["predicted_duration_days"] = pred_dur_days
        out["p_delay"] = delay_probs.astype(np.float32)
        out["is_at_risk"] = out["p_delay"] >= thr
        out["p_delay_raw"] = delay_probs.astype(np.float32)
        out["gated"] = np.zeros(len(sub), dtype=bool)
        out["p_non_work"] = np.zeros(len(sub), dtype=np.float32)
        out["p_early_non_work"] = np.zeros(len(sub), dtype=np.float32)
        out["max_sim_resolved"] = np.zeros(len(sub), dtype=np.float32)
        return out.sort_values(["instance", "rank_in_instance"]).reset_index(drop=True)

    def score_criticality(self, *args, **kwargs):
        df = self.score(*args, **kwargs)
        return (
            df[CRITICALITY_COLUMNS]
            .sort_values(["instance", "rank_in_instance"])
            .reset_index(drop=True)
        )

    def score_delay(self, *args, **kwargs):
        df = self.score(*args, **kwargs)
        return df[DELAY_COLUMNS].sort_values("p_delay", ascending=False).reset_index(drop=True)

    def _memory_snapshots(
        self,
        df,
        sel: np.ndarray,
        sdir: Path,
        as_of: float | None = None,
        at_project_change: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        import json

        import pandas as pd

        from ..features.t0 import issue_durations
        from .memory import load_memory
        from .stream import load_neighbours

        meta = json.loads((sdir / "meta.json").read_text())
        if meta["n_issue"] != len(df):
            raise ValueError(
                f"stream in {sdir} was built for {meta['n_issue']:,} issues, database has {len(df):,}"
            )
        stream = EventStream(sdir, self.bundle.config["chunk"], self.device)
        model = load_memory(self.bundle.file("tgn_memory.pt"), meta["n_nodes"], self.device)
        created = df["created_ts"].values.astype(np.float64)
        planned_t0 = df["planned_t0"].values.astype(np.float32)
        logger.info(
            f"Replaying {meta['n_events']:,} events for {len(sel):,} dual-head snapshots on {self.device}..."
        )
        if not at_project_change:
            t_snap = np.copy(created)
            Z, aux, applied_last = snapshot_memory_dual(
                model,
                stream,
                t_snap,
                created,
                planned_t0,
                load_neighbours(sdir),
                rows=sel,
                pre_t0_mode=True,
            )
            assert np.all(applied_last < created[sel]), "temporal leakage in pre-T0 dual snapshot"
        else:
            dur = issue_durations(df)
            end_ts = created + dur.astype(np.float64) * 86400.0
            cutoff = end_ts - 1.0
            if as_of is not None:
                as_of_ts = float(
                    pd.Timestamp(as_of).timestamp() if not isinstance(as_of, (int, float)) else as_of
                )
                cutoff = np.minimum(cutoff, as_of_ts)
            ts = np.load(sdir / "ts.npy", mmap_mode="r")
            u_id = np.load(sdir / "u_id.npy", mmap_mode="r")
            v_id = np.load(sdir / "v_id.npy", mmap_mode="r")
            kind = np.load(sdir / "kind.npy", mmap_mode="r")
            scat = np.load(sdir / "scat.npy", mmap_mode="r")
            n = len(df)
            t_snap = np.copy(created)
            m_u = (scat != 0) & (ts >= created[u_id]) & (ts <= cutoff[u_id])
            np.maximum.at(t_snap, u_id[m_u], ts[m_u])
            v_in = (kind == 4) & (v_id < n)
            v_safe = np.minimum(v_id, n - 1)
            m_v = v_in & (ts >= created[v_safe]) & (ts <= cutoff[v_safe])
            np.maximum.at(t_snap, v_id[m_v], ts[m_v])
            Z, aux, applied_last = snapshot_memory_dual(
                model,
                stream,
                t_snap,
                created,
                planned_t0,
                load_neighbours(sdir),
                rows=sel,
                pre_t0_mode=False,
            )
            assert np.all(applied_last <= t_snap[sel]) and np.all(
                applied_last < end_ts[sel]
            ), "temporal leakage in dual project-change snapshot"
        del model
        aux_norm = np.clip((aux - self.amu) / self.asd, -50.0, 50.0).astype(np.float16)
        z_norm = np.concatenate([Z, aux_norm], axis=1)
        return z_norm, t_snap[sel]
