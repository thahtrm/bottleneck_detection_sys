"""Scalable TGN memory over the full Jira event stream + leak-safe T0 snapshots.

Memory   S in R^{N x 128} (issues + users + projects + status/priority value nodes).
Message  m = MLP([x_dom(16) || Phi(dt)(16) || s_counterpart(128)]) -> 64   (x_k = first 32 dims)
Agg      mean of messages per receiving node in the chunk (index_add_)
Update   s_u(t) = GRUCell(m_bar_u, s_u(t-))
Snapshot one pass over all events, no gradients. Before applying chunk c, every issue whose T0 is
         <= max ts of chunk c is frozen: Z_i = [s_i || s_reporter || s_assignee(T0) || s_project].
         All applied events therefore have ts < T0.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

N_KIND, MEM, MSG = 6, 128, 64


class TGNMemory(nn.Module):
    def __init__(self, n_nodes: int, device: torch.device):
        super().__init__()
        self.register_buffer("freqs", 1.0 / (10.0 ** torch.linspace(0, 4, 8)))  # per hour
        self.msg_fn = nn.Sequential(nn.Linear(32 + MEM, 128), nn.ReLU(), nn.Linear(128, MSG))
        self.gru = nn.GRUCell(MSG, MEM)
        self.decoder = nn.Sequential(nn.Linear(2 * MEM, 128), nn.ReLU(), nn.Linear(128, 1))
        self.n_nodes = n_nodes
        self.device = device
        self.to(device)
        self.reset()

    def reset(self) -> None:
        self.mem = torch.zeros(self.n_nodes, MEM, device=self.device)
        self.last = torch.full((self.n_nodes,), -1.0, dtype=torch.float64, device=self.device)
        self.n_upd = torch.zeros(self.n_nodes, dtype=torch.int32, device=self.device)
        self.slot = torch.full((self.n_nodes,), -1, dtype=torch.long, device=self.device)

    def time_enc(self, dt_h: torch.Tensor) -> torch.Tensor:
        a = dt_h.unsqueeze(-1) * self.freqs
        return torch.stack([torch.cos(a), torch.sin(a)], -1).flatten(1)

    def raw_messages(self, ch: dict) -> dict:
        """Message inputs for one chunk, built from the CURRENT (detached) memory."""
        u, v, p = ch["u"], ch["v"], ch["p"]
        n = len(u)
        dom = torch.zeros(n, 16, device=self.device)
        dom[torch.arange(n, device=self.device), ch["kind"]] = 1.0
        lt = ch["ltype"]
        dom[lt >= 0, 6 + lt[lt >= 0]] = 1.0
        sc = ch["scat"]
        m = (sc >= 0) & (sc < 3)
        dom[m, 10 + sc[m]] = 1.0
        dom[:, 13] = ch["blen"] / 10.0
        recv = torch.cat([u, v, p])
        cpt = torch.cat([v, u, u])
        dom = dom.repeat(3, 1)
        dom[n:2 * n, 14] = 1.0  # role: counterpart
        dom[2 * n:, 15] = 1.0   # role: project
        ts = ch["ts"].repeat(3)
        last = self.last[recv]
        dt_h = torch.where(last < 0, torch.full_like(ts, 1e5), (ts - last) / 3600.0).clamp(0, 1e5).float()
        x = torch.cat([dom, self.time_enc(dt_h), self.mem[cpt]], 1)
        return {"recv": recv, "x": x, "ts": ts}

    def apply(self, raw: dict) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Aggregate + GRU. Returns (unique nodes, new memory, max ts per node)."""
        uniq, inv = torch.unique(raw["recv"], return_inverse=True)
        msg = self.msg_fn(raw["x"])
        agg = torch.zeros(len(uniq), MSG, device=self.device).index_add_(0, inv, msg)
        cnt = torch.zeros(len(uniq), device=self.device).index_add_(0, inv, torch.ones_like(inv, dtype=torch.float))
        new = self.gru(agg / cnt.unsqueeze(1), self.mem[uniq])
        tmax = torch.full((len(uniq),), -1.0, dtype=torch.float64, device=self.device)
        tmax = tmax.scatter_reduce(0, inv, raw["ts"], reduce="amax")
        return uniq, new, tmax

    def commit(self, uniq: torch.Tensor, new: torch.Tensor, tmax: torch.Tensor) -> None:
        self.mem[uniq] = new.detach()
        self.last[uniq] = tmax
        self.n_upd[uniq] += 1

    def embed(self, q: torch.Tensor, uniq: torch.Tensor | None, new: torch.Tensor | None) -> torch.Tensor:
        if uniq is None:
            return self.mem[q]
        self.slot[uniq] = torch.arange(len(uniq), device=self.device)
        s = self.slot[q]
        out = torch.where((s >= 0).unsqueeze(1), new[s.clamp(min=0)], self.mem[q])
        self.slot[uniq] = -1
        return out

    def score(self, a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        return self.decoder(torch.cat([a, b], 1)).squeeze(1)


class EventStream:
    """Chunked reader over the on-disk event memmaps."""

    def __init__(self, root: Path, chunk: int, device: torch.device):
        self.cols = {c: np.load(root / f"{c}.npy", mmap_mode="r")
                     for c in ["ts", "u_id", "v_id", "p_id", "kind", "ltype", "scat", "blen"]}
        self.n = len(self.cols["ts"])
        self.chunk = chunk
        self.device = device
        self.starts = np.arange(0, self.n, chunk)
        ends = np.minimum(self.starts + chunk, self.n)
        self.max_ts = np.asarray(self.cols["ts"][ends - 1])

    def get(self, c: int) -> dict:
        s, e = self.starts[c], min(self.starts[c] + self.chunk, self.n)
        d = self.device
        return {"ts": torch.from_numpy(np.array(self.cols["ts"][s:e])).to(d),
                "u": torch.from_numpy(self.cols["u_id"][s:e].astype(np.int64)).to(d),
                "v": torch.from_numpy(self.cols["v_id"][s:e].astype(np.int64)).to(d),
                "p": torch.from_numpy(self.cols["p_id"][s:e].astype(np.int64)).to(d),
                "kind": torch.from_numpy(self.cols["kind"][s:e].astype(np.int64)).to(d),
                "ltype": torch.from_numpy(self.cols["ltype"][s:e].astype(np.int64)).to(d),
                "scat": torch.from_numpy(self.cols["scat"][s:e].astype(np.int64)).to(d),
                "blen": torch.from_numpy(self.cols["blen"][s:e].astype(np.float32)).to(d)}



@torch.no_grad()
def snapshot_memory(model: TGNMemory, stream: EventStream, created: np.ndarray, neigh: np.ndarray,
                    rows: np.ndarray | None = None, z_out: np.ndarray | None = None,
                    on_chunk: Callable[[int, dict], None] | None = None):
    """Replay the stream and freeze the memory of each issue in ``rows`` just before its T0.

    Returns ``(Z, aux, applied_max)`` aligned with ``rows`` (default: all issues):
    Z (k, 4*MEM) fp16 = [issue || reporter || assignee(T0) || project] memory, aux (k, 5) =
    log hours since last update of the 4 nodes + log update count of the reporter, and the
    max event ts applied before each snapshot (always < T0). ``on_chunk(c, chunk)`` is called
    before chunk c is applied (training uses it for link-prediction evaluation).
    """
    n_issue = len(created)
    rows = np.arange(n_issue, dtype=np.int64) if rows is None else np.asarray(rows, np.int64)
    Z = z_out if z_out is not None else np.zeros((len(rows), 4 * MEM), np.float16)
    aux = np.zeros((len(rows), 5), np.float32)  # log dt since last update (issue, rep, ass, proj), log n_upd(rep)
    applied_max = np.full(len(rows), -np.inf)
    # snapshot before chunk c, c = first chunk whose max ts >= T0 -> all applied events have ts < T0
    snap_chunk = np.searchsorted(stream.max_ts, created[rows], side="left")
    order = np.argsort(snap_chunk, kind="stable")
    bounds = np.searchsorted(snap_chunk[order], np.arange(len(stream.starts) + 2))
    last_needed = int(snap_chunk.max()) if len(rows) else -1
    neigh_t = torch.from_numpy(neigh.astype(np.int64)).to(model.device)
    model.reset()
    model.eval()
    cur_max = -np.inf
    t0 = time.time()
    for c in range(len(stream.starts) + 1):
        k = order[bounds[c]:bounds[c + 1]]
        if len(k):
            idx = rows[k]
            it = torch.from_numpy(idx).to(model.device)
            nb = neigh_t[it]  # (k, 3): reporter, assignee_t0, project ; -1 if unknown
            parts, dts = [model.mem[it]], [model.last[it]]
            for j in range(3):
                q = nb[:, j].clamp(min=0)
                ok = (nb[:, j] >= 0).unsqueeze(1)
                parts.append(torch.where(ok, model.mem[q], torch.zeros_like(model.mem[q])))
                dts.append(torch.where(nb[:, j] >= 0, model.last[q], torch.full_like(model.last[q], -1.0)))
            Z[k] = torch.cat(parts, 1).half().cpu().numpy()
            t_now = torch.from_numpy(created[idx]).to(model.device)
            for j, d in enumerate(dts):
                aux[k, j] = torch.where(d < 0, torch.full_like(d, 12.0),
                                        torch.log1p((t_now - d).clamp(min=0) / 3600.0)).float().cpu().numpy()
            aux[k, 4] = torch.log1p(model.n_upd[nb[:, 0].clamp(min=0)].float()).cpu().numpy()
            applied_max[k] = cur_max
        if c == len(stream.starts) or (on_chunk is None and c >= last_needed):
            break
        ch = stream.get(c)
        if on_chunk is not None:
            on_chunk(c, ch)
        model.commit(*model.apply(model.raw_messages(ch)))
        cur_max = float(stream.max_ts[c])
        if c % 300 == 0:
            logger.info(f"    snapshot pass chunk {c}/{len(stream.starts)} ({time.time() - t0:.0f}s)")
    return Z, aux, applied_max


def load_memory(path: str | Path, n_nodes: int, device: torch.device) -> TGNMemory:
    model = TGNMemory(n_nodes, device)
    model.load_state_dict(torch.load(path, map_location=device))
    return model


def _sub_chunk(ch: dict, mask: torch.Tensor) -> dict:
    return {k: v[mask] for k, v in ch.items()}


@torch.no_grad()
def snapshot_memory_at_change(model: TGNMemory, stream: EventStream, t_snap: np.ndarray, neigh: np.ndarray,
                              rows: np.ndarray | None = None, z_out: np.ndarray | None = None,
                              dynamic_assignee: bool = True):
    """Replay the stream and freeze each issue's memory AT its project-change timestamp ``t_snap[i]``.

    Within the chunk containing ``t_snap[i]``, all active (non-closing, ``scat != 0``) events with
    ``ts <= t_snap[u]`` (and ``ts <= t_snap[v]`` for issue-link events) are applied *before* the
    snapshot is read out, while events after ``t_snap`` or resolution events are applied *after*
    the snapshot so future chunks still see the complete history.
    """
    n_issue = len(t_snap)
    rows = np.arange(n_issue, dtype=np.int64) if rows is None else np.asarray(rows, np.int64)
    Z = z_out if z_out is not None else np.zeros((len(rows), 4 * MEM), np.float16)
    aux = np.zeros((len(rows), 5), np.float32)
    applied_issue_last = np.full(len(rows), -np.inf)
    n_chunks = len(stream.starts)
    snap_chunk_all = np.minimum(np.searchsorted(stream.max_ts, t_snap, side="left"), n_chunks - 1)
    snap_chunk = snap_chunk_all[rows]
    order = np.argsort(snap_chunk, kind="stable")
    bounds = np.searchsorted(snap_chunk[order], np.arange(n_chunks + 1))
    last_needed = int(snap_chunk.max()) if len(rows) else -1
    neigh_t = torch.from_numpy(neigh.astype(np.int64)).to(model.device)
    t_snap_dev = torch.from_numpy(t_snap.astype(np.float64)).to(model.device)
    sc_dev = torch.from_numpy(snap_chunk_all.astype(np.int64)).to(model.device)
    model.reset()
    model.eval()
    t0 = time.time()
    for c in range(n_chunks):
        if c > last_needed:
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
            if dynamic_assignee:
                m_ass = ch_pre["kind"] == 1
                if m_ass.any():
                    neigh_t[ch_pre["u"][m_ass], 1] = ch_pre["v"][m_ass]

        k = order[bounds[c]:bounds[c + 1]]
        if len(k):
            idx = rows[k]
            it = torch.from_numpy(idx).to(model.device)
            nb = neigh_t[it]
            parts, dts = [model.mem[it]], [model.last[it]]
            for j in range(3):
                q = nb[:, j].clamp(min=0)
                ok = (nb[:, j] >= 0).unsqueeze(1)
                parts.append(torch.where(ok, model.mem[q], torch.zeros_like(model.mem[q])))
                dts.append(torch.where(nb[:, j] >= 0, model.last[q], torch.full_like(model.last[q], -1.0)))
            Z[k] = torch.cat(parts, 1).half().cpu().numpy()
            t_now = torch.from_numpy(t_snap[idx]).to(model.device)
            for j, d in enumerate(dts):
                aux[k, j] = torch.where(d < 0, torch.full_like(d, 12.0),
                                        torch.log1p((t_now - d).clamp(min=0) / 3600.0)).float().cpu().numpy()
            aux[k, 4] = torch.log1p(model.n_upd[nb[:, 0].clamp(min=0)].float()).cpu().numpy()
            applied_issue_last[k] = dts[0].cpu().numpy()

        post_mask = ~pre_mask
        if post_mask.any():
            ch_post = _sub_chunk(ch, post_mask)
            model.commit(*model.apply(model.raw_messages(ch_post)))
            if dynamic_assignee:
                m_ass = ch_post["kind"] == 1
                if m_ass.any():
                    neigh_t[ch_post["u"][m_ass], 1] = ch_post["v"][m_ass]

        if c % 300 == 0:
            logger.info(f"    project-change snapshot pass chunk {c}/{n_chunks} ({time.time() - t0:.0f}s)")
    return Z, aux, applied_issue_last

