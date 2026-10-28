"""Stage 3 — Scalable TGN memory over the full Jira event stream + leak-audited T0 snapshots.

Memory   S in R^{N x 128} on GPU (issues + users + projects + status/priority value nodes).
Message  m = MLP([x_dom(16) || Phi(dt)(16) || s_counterpart(128)]) -> 64   (x_k = first 32 dims)
Agg      mean of messages per receiving node in the chunk (index_add_)
Update   s_u(t) = GRUCell(m_bar_u, s_u(t-))
Training self-supervised temporal link prediction (TGN, Rossi et al. 2020) on events of the TRAIN
         period only: messages of chunk c-1 are applied with gradients, then the events of chunk c
         are scored against shuffled negatives. Memory is detached between chunks.
Snapshot one pass over all events, no gradients. Before applying chunk c, every issue whose T0 is
         <= max ts of chunk c is frozen: Z_i = [s_i || s_reporter || s_assignee(T0) || s_project].
         All applied events therefore have ts < T0 (checked per issue -> leakage_audit.json).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import average_precision_score, roc_auc_score

from build_dataset import log

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
        return {"ts": torch.from_numpy(np.ascontiguousarray(self.cols["ts"][s:e])).to(d),
                "u": torch.from_numpy(self.cols["u_id"][s:e].astype(np.int64)).to(d),
                "v": torch.from_numpy(self.cols["v_id"][s:e].astype(np.int64)).to(d),
                "p": torch.from_numpy(self.cols["p_id"][s:e].astype(np.int64)).to(d),
                "kind": torch.from_numpy(self.cols["kind"][s:e].astype(np.int64)).to(d),
                "ltype": torch.from_numpy(self.cols["ltype"][s:e].astype(np.int64)).to(d),
                "scat": torch.from_numpy(self.cols["scat"][s:e].astype(np.int64)).to(d),
                "blen": torch.from_numpy(self.cols["blen"][s:e].astype(np.float32)).to(d)}


def link_loss(model: TGNMemory, ch: dict, uniq, new, gen: torch.Generator):
    u, v = ch["u"], ch["v"]
    neg = v[torch.randperm(len(v), device=v.device, generator=gen)]
    eu, ev, en = model.embed(u, uniq, new), model.embed(v, uniq, new), model.embed(neg, uniq, new)
    pos, ngs = model.score(eu, ev), model.score(eu, en)
    loss = F.binary_cross_entropy_with_logits(pos, torch.ones_like(pos)) + \
        F.binary_cross_entropy_with_logits(ngs, torch.zeros_like(ngs))
    return loss, pos.detach(), ngs.detach()


def train_memory(model: TGNMemory, stream: EventStream, n_train_chunks: int, epochs: int, lr: float, seed: int):
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    gen = torch.Generator(device=model.device).manual_seed(seed)
    history = []
    for ep in range(epochs):
        model.reset()
        pending, t_ep, losses, aps = None, time.time(), [], []
        for c in range(n_train_chunks):
            ch = stream.get(c)
            if pending is None:
                uniq = new = tmax = None
            else:
                uniq, new, tmax = model.apply(pending)
            loss, pos, ngs = link_loss(model, ch, uniq, new, gen)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            if uniq is not None:
                model.commit(uniq, new, tmax)
            with torch.no_grad():
                pending = model.raw_messages(ch)
            losses.append(loss.item())
            if c % 50 == 0:
                y = np.r_[np.ones(len(pos)), np.zeros(len(ngs))]
                aps.append(average_precision_score(y, torch.cat([pos, ngs]).cpu().numpy()))
            if c % 300 == 0:
                log(f"    epoch {ep + 1} chunk {c}/{n_train_chunks} loss {np.mean(losses[-300:]):.4f}")
        rec = {"epoch": ep + 1, "loss": float(np.mean(losses)), "train_link_ap": float(np.mean(aps)),
               "seconds": round(time.time() - t_ep, 1)}
        history.append(rec)
        log(f"  epoch {ep + 1}: {rec}")
    return history


@torch.no_grad()
def extract_snapshots(model: TGNMemory, stream: EventStream, created: np.ndarray, neigh: np.ndarray,
                      out: Path, period_bounds: dict[str, float], tag: str = ""):
    n_issue = len(created)
    Z = np.lib.format.open_memmap(out / f"z_raw_all{tag}.npy", mode="w+", dtype=np.float16, shape=(n_issue, 4 * MEM))
    aux = np.zeros((n_issue, 5), np.float32)  # log dt since last update (issue, rep, ass, proj), log n_upd(rep)
    applied_max = np.full(n_issue, -np.inf)
    # snapshot before chunk c, c = first chunk whose max ts >= T0 -> all applied events have ts < T0
    snap_chunk = np.searchsorted(stream.max_ts, created, side="left")
    order = np.argsort(snap_chunk, kind="stable")
    bounds = np.searchsorted(snap_chunk[order], np.arange(len(stream.starts) + 2))
    neigh_t = torch.from_numpy(neigh.astype(np.int64)).to(model.device)
    model.reset()
    model.eval()
    cur_max = -np.inf
    link_eval = {k: {"y": [], "s": []} for k in period_bounds}
    gen = torch.Generator(device=model.device).manual_seed(0)
    t0 = time.time()
    for c in range(len(stream.starts) + 1):
        idx = order[bounds[c]:bounds[c + 1]]
        if len(idx):
            it = torch.from_numpy(idx.astype(np.int64)).to(model.device)
            nb = neigh_t[it]  # (k, 3): reporter, assignee_t0, project ; -1 if unknown
            parts, dts = [model.mem[it]], [model.last[it]]
            for j in range(3):
                q = nb[:, j].clamp(min=0)
                ok = (nb[:, j] >= 0).unsqueeze(1)
                parts.append(torch.where(ok, model.mem[q], torch.zeros_like(model.mem[q])))
                dts.append(torch.where(nb[:, j] >= 0, model.last[q], torch.full_like(model.last[q], -1.0)))
            Z[idx] = torch.cat(parts, 1).half().cpu().numpy()
            t_now = torch.from_numpy(created[idx]).to(model.device)
            for j, d in enumerate(dts):
                aux[idx, j] = torch.where(d < 0, torch.full_like(d, 12.0),
                                          torch.log1p((t_now - d).clamp(min=0) / 3600.0)).float().cpu().numpy()
            aux[idx, 4] = torch.log1p(model.n_upd[nb[:, 0].clamp(min=0)].float()).cpu().numpy()
            applied_max[idx] = cur_max
        if c == len(stream.starts):
            break
        ch = stream.get(c)
        # link-prediction quality of the frozen memory on later periods (sampled chunks)
        if c % 20 == 0:
            per = next((k for k, (lo, hi) in period_bounds.items() if lo <= stream.max_ts[c] <= hi), None)
            if per is not None:
                _, pos, ngs = link_loss(model, ch, None, None, gen)
                link_eval[per]["y"].append(np.r_[np.ones(len(pos)), np.zeros(len(ngs))])
                link_eval[per]["s"].append(torch.cat([pos, ngs]).cpu().numpy())
        model.commit(*model.apply(model.raw_messages(ch)))
        cur_max = float(stream.max_ts[c])
        if c % 300 == 0:
            log(f"    snapshot pass chunk {c}/{len(stream.starts)} ({time.time() - t0:.0f}s)")
    Z.flush()
    np.save(out / f"z_aux_all{tag}.npy", aux)
    leak = applied_max >= created
    audit = {
        "rule": "snapshot of issue i taken before the first chunk whose max ts >= T0_i",
        "n_issues": int(n_issue),
        "n_violations_applied_ts_ge_T0": int(leak.sum()),
        "max_applied_ts_minus_T0_seconds": float(np.max(applied_max - created)),
        "median_staleness_hours": float(np.median((created - np.where(np.isfinite(applied_max), applied_max, created)) / 3600)),
        "p95_staleness_hours": float(np.percentile((created - np.where(np.isfinite(applied_max), applied_max, created)) / 3600, 95)),
        "issues_with_nonzero_own_memory_at_T0": int((np.abs(Z[:, :MEM].astype(np.float32)).sum(1) > 0).sum()),
    }
    link = {}
    for k, d in link_eval.items():
        if d["y"]:
            y, s = np.concatenate(d["y"]), np.concatenate(d["s"])
            link[k] = {"link_ap": float(average_precision_score(y, s)), "link_auc": float(roc_auc_score(y, s)),
                       "n_chunks": len(d["y"])}
    return audit, link


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data/tgn_full")
    ap.add_argument("--chunk", type=int, default=10_000)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tag", default="", help="suffix for snapshot / report files (sweeps)")
    args = ap.parse_args()
    # Recurrent memory amplifies atomic-add noise across ~1,300 chunks -> force deterministic kernels.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.manual_seed(args.seed)
    root = Path(args.data_dir)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    meta = json.loads((root / "events" / "meta.json").read_text())
    iss = pd.read_parquet(root / "issues_t0.parquet", columns=["row_id", "created_ts", "split"])
    assert np.all(iss["row_id"].values == np.arange(len(iss)))
    created = iss["created_ts"].values.astype(np.float64)
    neigh = np.stack([np.load(root / "events" / f"issue_{c}.npy") for c in ["r_id", "a_id", "p_id"]], 1)

    stream = EventStream(root / "events", args.chunk, dev)
    train_cutoff = float(created[iss["split"].values == "train"].max())
    val_cutoff = float(created[iss["split"].values == "val"].max())
    n_train_chunks = int(np.searchsorted(stream.max_ts, train_cutoff, side="right"))
    log(f"{meta['n_events']:,} events, {meta['n_nodes']:,} nodes, {len(stream.starts):,} chunks of {args.chunk:,}; "
        f"memory training on first {n_train_chunks:,} chunks (ts <= train cutoff "
        f"{pd.to_datetime(train_cutoff, unit='s').date()})")

    model = TGNMemory(meta["n_nodes"], dev)
    log(f"Memory matrix {tuple(model.mem.shape)} float32 = {model.mem.numel() * 4 / 2**30:.2f} GiB on {dev}")
    history = train_memory(model, stream, n_train_chunks, args.epochs, args.lr, args.seed)
    torch.save({k: v for k, v in model.state_dict().items()}, root / f"tgn_memory{args.tag}.pt")

    log("Snapshot pass over the full stream...")
    audit, link = extract_snapshots(model, stream, created, neigh, root,
                                    {"train": (-np.inf, train_cutoff), "val": (train_cutoff, val_cutoff),
                                     "test": (val_cutoff, np.inf)}, tag=args.tag)
    audit["memory_training_last_event_ts"] = float(stream.max_ts[n_train_chunks - 1])
    audit["train_cutoff_ts"] = train_cutoff
    audit["memory_trained_only_on_train_period"] = bool(stream.max_ts[n_train_chunks - 1] <= train_cutoff)
    report = {"config": vars(args), "meta": meta, "train_history": history, "link_prediction": link,
              "leakage_audit": audit}
    (root / f"tgn_memory_report{args.tag}.json").write_text(json.dumps(report, indent=2))
    log(json.dumps({"link_prediction": link, "leakage_audit": audit}, indent=2))
    assert audit["n_violations_applied_ts_ge_T0"] == 0, "temporal leakage detected"


if __name__ == "__main__":
    main()
