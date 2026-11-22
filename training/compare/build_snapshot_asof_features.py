"""Build leak-safe tabular as-of features at Dual-Head project-change snapshots.

Dual-Head-only (NOT included here): TGN memory ``z`` / aux embeddings.
Classical gets: T0 base features ⊕ as-of progress/event counts at ``t_snap``.

Snapshot IDs match ``train_dual_head.py``:
  T0_pre, T3_change, T7_change, T_active_change
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from training.criticality.train_project_change import compute_change_timestamps

HORIZONS = {
    "T0_pre": -1.0,
    "T3_change": 3.0,
    "T7_change": 7.0,
    "T_active_change": None,
}


def _load_issue_frame(root: Path) -> pd.DataFrame:
    cols = [
        "row_id",
        "instance",
        "issue_key",
        "created_ts",
        "resolved_ts",
        "is_resolved",
        "planned_duration_days",
        "duration_days",
        "split",
    ]
    df = pd.read_parquet(root / "issues_t0.parquet", columns=cols)
    df = df.sort_values("row_id").reset_index(drop=True)
    df["uid"] = df["instance"].astype(str) + "|" + df["issue_key"].astype(str)
    return df


def _event_arrays(events_dir: Path) -> dict[str, np.ndarray]:
    return {
        "ts": np.load(events_dir / "ts.npy", mmap_mode="r"),
        "u_id": np.load(events_dir / "u_id.npy", mmap_mode="r"),
        "v_id": np.load(events_dir / "v_id.npy", mmap_mode="r"),
        "kind": np.load(events_dir / "kind.npy", mmap_mode="r"),
        "scat": np.load(events_dir / "scat.npy", mmap_mode="r"),
    }


def compute_t_snap(df: pd.DataFrame, events: dict[str, np.ndarray], horizon_days: float | None) -> np.ndarray:
    created = df["created_ts"].values.astype(np.float64)
    end_ts = np.where(
        df["is_resolved"].values == 1,
        df["resolved_ts"].values.astype(np.float64),
        created + 3650.0 * 86400.0,
    )
    if horizon_days is not None and horizon_days < 0:
        return np.copy(created)
    return compute_change_timestamps(
        created,
        end_ts,
        np.asarray(events["ts"]),
        np.asarray(events["u_id"]),
        np.asarray(events["v_id"]),
        np.asarray(events["kind"]),
        np.asarray(events["scat"]),
        None if horizon_days is None else float(horizon_days),
    )


def asof_feature_matrix(
    df: pd.DataFrame,
    events: dict[str, np.ndarray],
    t_snap: np.ndarray,
) -> tuple[np.ndarray, list[str]]:
    """Tabular as-of features aligned to ``df`` row order (issues_t0 row_id)."""
    n = len(df)
    created = df["created_ts"].values.astype(np.float64)
    planned = df["planned_duration_days"].values.astype(np.float64)
    elapsed = np.maximum(0.0, (t_snap - created) / 86400.0)
    remaining = planned - elapsed
    frac = elapsed / (planned + 1e-4)
    past = (elapsed > planned).astype(np.float32)

    n_events = np.zeros(n, dtype=np.float32)
    n_active = np.zeros(n, dtype=np.float32)
    last_ts = np.copy(created)

    ts = np.asarray(events["ts"])
    u_id = np.asarray(events["u_id"])
    v_id = np.asarray(events["v_id"])
    kind = np.asarray(events["kind"])
    scat = np.asarray(events["scat"])

    # Stream once: count events with created <= ts <= t_snap[issue]
    m_u = (ts >= created[np.clip(u_id, 0, n - 1)]) & (ts <= t_snap[np.clip(u_id, 0, n - 1)]) & (u_id < n)
    u_ok = u_id[m_u]
    np.add.at(n_events, u_ok, 1.0)
    active_u = m_u & (scat != 0)
    np.add.at(n_active, u_id[active_u], 1.0)
    np.maximum.at(last_ts, u_ok, ts[m_u])

    v_in = (kind == 4) & (v_id < n)
    v_safe = np.minimum(v_id, n - 1)
    m_v = v_in & (ts >= created[v_safe]) & (ts <= t_snap[v_safe])
    v_ok = v_id[m_v]
    np.add.at(n_events, v_ok, 1.0)
    np.maximum.at(last_ts, v_ok, ts[m_v])

    days_since_last = np.maximum(0.0, (t_snap - last_ts) / 86400.0)
    has_post = (t_snap > created + 1.0).astype(np.float32)

    feats = np.column_stack(
        [
            elapsed.astype(np.float32),
            remaining.astype(np.float32),
            frac.astype(np.float32),
            past,
            np.log1p(n_events),
            np.log1p(n_active),
            days_since_last.astype(np.float32),
            has_post,
        ]
    )
    names = [
        "asof_elapsed_days",
        "asof_remaining_planned_days",
        "asof_frac_elapsed_of_plan",
        "asof_past_planned",
        "asof_log1p_n_events",
        "asof_log1p_n_active_events",
        "asof_days_since_last_event",
        "asof_has_post_t0_activity",
    ]
    return np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0), names


def main() -> None:
    ap = argparse.ArgumentParser(description="Build classical as-of tabular features per snapshot")
    ap.add_argument("--data-dir", default="data/tgn_full_v2")
    ap.add_argument("--out-dir", default="data/tgn_full_v2/classical_asof")
    ap.add_argument(
        "--snapshots",
        nargs="+",
        default=list(HORIZONS.keys()),
        choices=list(HORIZONS.keys()),
    )
    args = ap.parse_args()
    root = Path(args.data_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = _load_issue_frame(root)
    events = _event_arrays(root / "events")
    meta = {"n_issues": len(df), "snapshots": {}, "dual_head_only": ["tgn_memory_z", "tgn_aux"]}

    for snap in args.snapshots:
        print(f"[asof] computing t_snap + features for {snap}...")
        t_snap = compute_t_snap(df, events, HORIZONS[snap])
        X_asof, names = asof_feature_matrix(df, events, t_snap)
        np.save(out / f"t_snap_{snap}.npy", t_snap.astype(np.float64))
        pd.DataFrame(X_asof, columns=names).assign(uid=df["uid"].values, split=df["split"].values).to_parquet(
            out / f"X_asof_{snap}.parquet", index=False
        )
        meta["snapshots"][snap] = {
            "horizon_days": HORIZONS[snap],
            "feature_names": names,
            "mean_elapsed_days": float(X_asof[:, 0].mean()),
            "frac_has_post_t0": float(X_asof[:, -1].mean()),
        }
        print(f"  wrote X_asof_{snap}.parquet shape={X_asof.shape}")

    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[asof] done → {out.resolve()}")


if __name__ == "__main__":
    main()
