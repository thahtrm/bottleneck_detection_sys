#!/usr/bin/env python3
"""Run snapshot_memory on generated streams and require a strict T0 cutoff.

The independent loop does not call searchsorted. It walks chunks and stops at
the first chunk whose last timestamp is >= the issue's created_ts.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import torch

from early_risk_detection.criticality.memory import EventStream, TGNMemory, snapshot_memory

CPU = torch.device("cpu")


def expected_applied_max(ts: np.ndarray, chunk: int, created: np.ndarray) -> np.ndarray:
    out = np.full(len(created), -np.inf)
    n = len(ts)
    if n == 0:
        return out
    for i, t0 in enumerate(created):
        cur = -np.inf
        for start in range(0, n, chunk):
            last = float(ts[min(start + chunk, n) - 1])
            if last >= float(t0):
                break
            cur = last
        out[i] = cur
    return out


def write_stream(root: Path, ts: np.ndarray) -> None:
    n = len(ts)
    z = np.zeros(n, np.int64)
    neg = np.full(n, -1, np.int64)
    np.save(root / "ts.npy", np.asarray(ts, np.float64))
    np.save(root / "u_id.npy", z)
    np.save(root / "v_id.npy", z)
    np.save(root / "p_id.npy", z)
    np.save(root / "kind.npy", np.zeros(n, np.int64))
    np.save(root / "ltype.npy", neg)
    np.save(root / "scat.npy", neg)
    np.save(root / "blen.npy", np.zeros(n, np.float32))


def check_case(ts: np.ndarray, chunk: int, created: np.ndarray, rows: np.ndarray | None, label: str) -> str | None:
    created = np.asarray(created, np.float64)
    n_issue = len(created)
    expect = expected_applied_max(ts, chunk, created)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_stream(root, ts)
        stream = EventStream(root, chunk, CPU)
        model = TGNMemory(max(n_issue, 1), CPU)
        neigh = np.full((n_issue, 3), -1, np.int64)
        _z, _aux, applied = snapshot_memory(model, stream, created, neigh, rows=rows)
    got = applied if rows is None else applied
    want = expect if rows is None else expect[rows]
    if got.shape != want.shape or not np.array_equal(got, want):
        return (
            f"FAIL {label}: created_ts={created.tolist()} chunk={chunk} events={np.asarray(ts).tolist()} "
            f"applied_max={got.tolist()} expected={want.tolist()}"
        )
    checked = created if rows is None else created[rows]
    if len(checked) and not np.all(got < checked):
        return (
            f"FAIL {label}: an applied event is at or after creation "
            f"created_ts={checked.tolist()} applied_max={got.tolist()}"
        )
    return None


def cases() -> list[tuple[np.ndarray, int, np.ndarray, np.ndarray | None, str]]:
    out: list[tuple[np.ndarray, int, np.ndarray, np.ndarray | None, str]] = []
    out.append((np.array([]), 4, np.array([10.0]), None, "no events"))
    out.append((np.array([5.0]), 1, np.array([5.0]), None, "t0 equals the only event"))
    out.append((np.array([5.0]), 1, np.array([5.1]), None, "t0 just after the only event"))
    out.append((np.array([1, 2, 3, 10, 11], np.float64), 3, np.array([10.0]), None, "t0 equals a later chunk last ts"))
    out.append((np.array([1, 2, 3, 10, 11], np.float64), 3, np.array([3.0]), None, "t0 equals the first chunk last ts"))
    out.append((np.array([1, 2, 3, 10, 11], np.float64), 3, np.array([4.0]), None, "t0 inside the gap before the next chunk"))
    out.append((np.array([1, 1, 1, 1], np.float64), 2, np.array([1.0, 2.0]), None, "tied timestamps"))
    out.append((np.array([0, 1, 2, 3, 4], np.float64), 5, np.array([-1.0, 0.0, 4.0, 4.5]), None, "one chunk, t0 around it"))
    out.append((np.array([10, 20, 30], np.float64), 1, np.array([0.0]), None, "t0 before the stream"))
    out.append((np.array([10.0, 20.0]), 1, np.array([25.0]), None, "t0 after the stream"))
    created_many = np.array([1.0, 3.0, 10.0, 11.0, 100.0])
    out.append((
        np.array([1, 2, 3, 10, 11], np.float64), 2, created_many,
        np.array([], np.int64), "no issues selected",
    ))
    out.append((
        np.array([1, 2, 3, 10, 11], np.float64), 2, created_many,
        np.array([0, 2, 4]), "subset of issues",
    ))
    rng = np.random.default_rng(0)
    for i in range(80):
        n = int(rng.integers(1, 31))
        steps = rng.integers(0, 3, n)
        ts = np.cumsum(steps).astype(np.float64)
        chunk = int(rng.integers(1, n + 1))
        n_issue = int(rng.integers(1, 6))
        created = rng.choice(np.concatenate([ts, ts + 0.5, [-1.0], [float(ts[-1] + 5)]]), n_issue)
        rows = None
        if rng.random() < 0.3:
            rows = np.sort(rng.choice(n_issue, size=int(rng.integers(0, n_issue + 1)), replace=False))
        out.append((ts, chunk, created.astype(np.float64), rows, f"random-{i}"))
    return out


def main() -> int:
    torch.set_num_threads(1)
    seen: str | None = None
    total = 0
    for ts, chunk, created, rows, label in cases():
        total += 1
        seen = check_case(ts, chunk, created, rows, label)
        if seen:
            print(seen)
            return 1
    print(f"PASS {total} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
