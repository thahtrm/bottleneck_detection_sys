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
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import average_precision_score, roc_auc_score

from early_risk_detection._logging import setup_logging
from early_risk_detection.criticality.memory import MEM, EventStream, TGNMemory, snapshot_memory
from early_risk_detection.criticality.stream import load_neighbours

log = logging.getLogger(__name__).info


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


def extract_snapshots(model: TGNMemory, stream: EventStream, created: np.ndarray, neigh: np.ndarray,
                      out: Path, period_bounds: dict[str, float], tag: str = ""):
    n_issue = len(created)
    Z = np.lib.format.open_memmap(out / f"z_raw_all{tag}.npy", mode="w+", dtype=np.float16, shape=(n_issue, 4 * MEM))
    link_eval = {k: {"y": [], "s": []} for k in period_bounds}
    gen = torch.Generator(device=model.device).manual_seed(0)

    def on_chunk(c: int, ch: dict) -> None:
        # link-prediction quality of the frozen memory on later periods (sampled chunks)
        if c % 20 == 0:
            per = next((k for k, (lo, hi) in period_bounds.items() if lo <= stream.max_ts[c] <= hi), None)
            if per is not None:
                _, pos, ngs = link_loss(model, ch, None, None, gen)
                link_eval[per]["y"].append(np.r_[np.ones(len(pos)), np.zeros(len(ngs))])
                link_eval[per]["s"].append(torch.cat([pos, ngs]).cpu().numpy())

    _, aux, applied_max = snapshot_memory(model, stream, created, neigh, z_out=Z, on_chunk=on_chunk)
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
    ap.add_argument("--snapshot_from", default=None,
                    help="tgn_memory*.pt of an earlier run: skip training, only redo the snapshot pass "
                         "(e.g. after rebuilding issues_t0 / events)")
    args = ap.parse_args()
    setup_logging()
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
    neigh = load_neighbours(root / "events")

    stream = EventStream(root / "events", args.chunk, dev)
    train_cutoff = float(created[iss["split"].values == "train"].max())
    val_cutoff = float(created[iss["split"].values == "val"].max())
    n_train_chunks = int(np.searchsorted(stream.max_ts, train_cutoff, side="right"))
    log(f"{meta['n_events']:,} events, {meta['n_nodes']:,} nodes, {len(stream.starts):,} chunks of {args.chunk:,}; "
        f"memory training on first {n_train_chunks:,} chunks (ts <= train cutoff "
        f"{pd.to_datetime(train_cutoff, unit='s').date()})")

    model = TGNMemory(meta["n_nodes"], dev)
    log(f"Memory matrix {tuple(model.mem.shape)} float32 = {model.mem.numel() * 4 / 2**30:.2f} GiB on {dev}")
    config = vars(args)
    if args.snapshot_from:
        src = Path(args.snapshot_from)
        model.load_state_dict(torch.load(src, map_location=dev))
        prev = json.loads((src.parent / src.name.replace("tgn_memory", "tgn_memory_report").replace(".pt", ".json")).read_text())
        config = {**prev["config"], "data_dir": args.data_dir, "tag": args.tag, "snapshot_from": str(src)}
        history = prev["train_history"]
        log(f"Loaded memory weights from {src} (trained {config['epochs']} epochs, lr {config['lr']}, seed {config['seed']})")
    else:
        history = train_memory(model, stream, n_train_chunks, args.epochs, args.lr, args.seed)
    torch.save({k: v for k, v in model.state_dict().items()}, root / f"tgn_memory{args.tag}.pt")

    log("Snapshot pass over the full stream...")
    audit, link = extract_snapshots(model, stream, created, neigh, root,
                                    {"train": (-np.inf, train_cutoff), "val": (train_cutoff, val_cutoff),
                                     "test": (val_cutoff, np.inf)}, tag=args.tag)
    audit["memory_training_last_event_ts"] = float(stream.max_ts[n_train_chunks - 1])
    audit["train_cutoff_ts"] = train_cutoff
    audit["memory_trained_only_on_train_period"] = bool(stream.max_ts[n_train_chunks - 1] <= train_cutoff)
    report = {"config": config, "meta": meta, "train_history": history, "link_prediction": link,
              "leakage_audit": audit}
    (root / f"tgn_memory_report{args.tag}.json").write_text(json.dumps(report, indent=2))
    log(json.dumps({"link_prediction": link, "leakage_audit": audit}, indent=2))
    assert audit["n_violations_applied_ts_ge_T0"] == 0, "temporal leakage detected"


if __name__ == "__main__":
    main()
