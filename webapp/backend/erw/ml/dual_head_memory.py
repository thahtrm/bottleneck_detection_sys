"""Project Dual-Head TGN memory / Z snapshot cache (option B).

Interaction with IssueShap (option A)
-------------------------------------
- **B (this module):** frozen ``z_norm`` (TGN Z ‖ aux) per open issue after a Dual-Head
  memory replay. Speeds morning score + SHAP by skipping cold TGN event replay when the
  stream fingerprint still matches.
- **A (IssueShap):** KernelSHAP φ cache for the overview UI. Built from Dual-Head
  ``p_delay`` (RiskState / readout on cached Z) + interpretable feature groups.
- Refresh order: invalidate B on stream rebuild / catch-up → rescore Dual-Head (writes B)
  → SHAP batch (writes A, may reuse B for delay labels).

Invalidate when
---------------
- Event stream dir is reset/rebuilt (``invalidate_all``)
- Catch-up / ingest finishes (``invalidate_all``)
- Explicit model batch before rebuilding stream
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erw.db import utcnow
from erw.models import DualHeadMemorySnapshot
from erw.settings import Settings

log = logging.getLogger(__name__)


def memory_root(settings: Settings) -> Path:
    return Path(settings.stream_dir).resolve().parent / "dual_head_memory"


def model_tag_from_settings(settings: Settings) -> str:
    from erw.pipeline.overview_shap import resolve_model_tag

    return resolve_model_tag(settings)


def stream_fingerprint(stream_dir: Path, issue_keys: list[str], model_tag: str) -> str:
    """Stable id for (stream meta + open keys + model)."""
    meta_path = stream_dir / "meta.json"
    meta_blob = meta_path.read_text(encoding="utf-8") if meta_path.is_file() else ""
    keys_blob = "\n".join(sorted(issue_keys))
    raw = f"{model_tag}\n{meta_blob}\n{keys_blob}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def project_of_key(issue_key: str) -> str:
    project, _, _ = issue_key.partition("-")
    return project or issue_key


@dataclass
class MemorySnapshot:
    project_key: str
    as_of: datetime
    fingerprint: str
    model_tag: str
    issue_keys: list[str]
    z: np.ndarray  # [n, z_dim] float16/float32
    t_snap: np.ndarray  # [n]
    rel_path: str
    stream_version: str | None = None

    def z_for(self, keys: list[str]) -> np.ndarray | None:
        index = {k: i for i, k in enumerate(self.issue_keys)}
        if any(k not in index for k in keys):
            return None
        return np.stack([self.z[index[k]] for k in keys], axis=0)


def _npz_path(settings: Settings, project_key: str, fingerprint: str) -> Path:
    return memory_root(settings) / project_key / f"{fingerprint}.npz"


def invalidate_all(session: Session | None, settings: Settings) -> int:
    """Drop on-disk + DB Dual-Head memory snapshots (stream rebuild / catch-up)."""
    root = memory_root(settings)
    removed = 0
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
        removed += 1
    if session is not None:
        session.execute(delete(DualHeadMemorySnapshot))
        session.flush()
    log.info("invalidated Dual-Head memory snapshots under %s", root)
    return removed


def invalidate_project(session: Session | None, settings: Settings, project_key: str) -> None:
    root = memory_root(settings) / project_key
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    if session is not None:
        session.execute(delete(DualHeadMemorySnapshot).where(DualHeadMemorySnapshot.project_key == project_key))
        session.flush()


def save_project_snapshot(
    session: Session | None,
    settings: Settings,
    *,
    project_key: str,
    as_of: datetime,
    fingerprint: str,
    model_tag: str,
    issue_keys: list[str],
    z: np.ndarray,
    t_snap: np.ndarray,
    stream_version: str | None = None,
) -> Path:
    path = _npz_path(settings, project_key, fingerprint)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        issue_keys=np.asarray(issue_keys, dtype=object),
        z=np.asarray(z, dtype=np.float16),
        t_snap=np.asarray(t_snap, dtype=np.float64),
        fingerprint=np.asarray(fingerprint),
        model_tag=np.asarray(model_tag),
        project_key=np.asarray(project_key),
    )
    meta = {
        "n_issues": len(issue_keys),
        "z_dim": int(z.shape[1]) if z.ndim == 2 else 0,
        "stream_version": stream_version,
    }
    if session is not None:
        session.execute(
            delete(DualHeadMemorySnapshot).where(DualHeadMemorySnapshot.project_key == project_key)
        )
        session.add(
            DualHeadMemorySnapshot(
                project_key=project_key,
                as_of=as_of,
                fingerprint=fingerprint,
                model_tag=model_tag,
                stream_version=stream_version,
                rel_path=str(path.relative_to(memory_root(settings).parent)),
                n_issues=len(issue_keys),
                created_at=utcnow(),
                meta=meta,
            )
        )
        session.flush()
    return path


def load_project_snapshot(
    settings: Settings,
    project_key: str,
    *,
    fingerprint: str | None = None,
    session: Session | None = None,
) -> MemorySnapshot | None:
    """Load latest snapshot for project; if fingerprint given, require match."""
    row = None
    if session is not None:
        row = session.scalars(
            select(DualHeadMemorySnapshot)
            .where(DualHeadMemorySnapshot.project_key == project_key)
            .order_by(DualHeadMemorySnapshot.as_of.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        if fingerprint is not None and row.fingerprint != fingerprint:
            return None
        path = Path(settings.stream_dir).resolve().parent / row.rel_path
        # rel_path stored as dual_head_memory/... relative to var/
        if not path.is_file():
            # try memory_root layout
            path = _npz_path(settings, project_key, row.fingerprint)
    else:
        root = memory_root(settings) / project_key
        if not root.is_dir():
            return None
        files = sorted(root.glob("*.npz"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        path = files[0]
        if fingerprint is not None and path.stem != fingerprint:
            match = root / f"{fingerprint}.npz"
            if not match.is_file():
                return None
            path = match

    if not path.is_file():
        return None
    data = np.load(path, allow_pickle=True)
    keys = [str(k) for k in data["issue_keys"].tolist()]
    fp = str(data["fingerprint"]) if "fingerprint" in data else path.stem
    if fingerprint is not None and fp != fingerprint:
        return None
    as_of = row.as_of if row is not None else utcnow()
    return MemorySnapshot(
        project_key=project_key,
        as_of=as_of,
        fingerprint=fp,
        model_tag=str(data["model_tag"]) if "model_tag" in data else "",
        issue_keys=keys,
        z=np.asarray(data["z"], dtype=np.float32),
        t_snap=np.asarray(data["t_snap"], dtype=np.float64),
        rel_path=str(path),
        stream_version=(row.stream_version if row is not None else None),
    )


def split_and_save_by_project(
    session: Session | None,
    settings: Settings,
    *,
    as_of: datetime,
    fingerprint_all_keys: list[str],
    model_tag: str,
    issue_keys: list[str],
    z: np.ndarray,
    t_snap: np.ndarray,
    stream_dir: Path,
) -> dict[str, int]:
    """Partition a dual-pass Z matrix by project and persist each."""
    meta_path = stream_dir / "meta.json"
    stream_version = None
    if meta_path.is_file():
        try:
            stream_version = str(json.loads(meta_path.read_text(encoding="utf-8")).get("n_events"))
        except Exception:
            stream_version = None
    by_project: dict[str, list[int]] = {}
    for i, key in enumerate(issue_keys):
        by_project.setdefault(project_of_key(key), []).append(i)
    counts: dict[str, int] = {}
    for project, idxs in by_project.items():
        p_keys = [issue_keys[i] for i in idxs]
        fp = stream_fingerprint(stream_dir, p_keys, model_tag)
        save_project_snapshot(
            session,
            settings,
            project_key=project,
            as_of=as_of,
            fingerprint=fp,
            model_tag=model_tag,
            issue_keys=p_keys,
            z=z[np.asarray(idxs)],
            t_snap=t_snap[np.asarray(idxs)],
            stream_version=stream_version,
        )
        counts[project] = len(p_keys)
    return counts


def capture_memory_from_scorer(
    dual_scorer,
    *,
    duckdb_path: str | Path,
    embeddings,
    issue_keys: list[str],
    stream_dir: str | Path,
    settings: Settings,
    as_of: datetime,
    session: Session | None = None,
    top_pct: float | None = None,
    delay_threshold: float | None = None,
) -> tuple[Any, dict[str, int]]:
    """Run DualHeadScorer.score while capturing ``_memory_snapshots`` output; save B cache.

    Returns (score_dataframe, {project: n_issues_saved}).
    """
    captured: dict[str, Any] = {}
    orig = getattr(dual_scorer, "_memory_snapshots", None)

    if orig is not None:

        def _wrapped(df, sel, sdir, as_of=None, at_project_change=True):
            z, t = orig(df, sel, sdir, as_of=as_of, at_project_change=at_project_change)
            sub_keys = [str(k) for k in df.iloc[sel]["issue_key"].tolist()]
            captured["z"] = np.asarray(z)
            captured["t_snap"] = np.asarray(t)
            captured["keys"] = sub_keys
            captured["sdir"] = Path(sdir)
            return z, t

        dual_scorer._memory_snapshots = _wrapped  # type: ignore[method-assign]
    try:
        df = dual_scorer.score(
            duckdb_path,
            embeddings,
            issue_keys=issue_keys,
            as_of=None,
            stream_dir=stream_dir,
            top_pct=top_pct if top_pct is not None else settings.criticality_top_pct,
            delay_threshold=delay_threshold if delay_threshold is not None else settings.delay_threshold,
        )
    finally:
        if orig is not None:
            dual_scorer._memory_snapshots = orig  # type: ignore[method-assign]

    counts: dict[str, int] = {}
    if "z" in captured and captured["keys"]:
        model_tag = model_tag_from_settings(settings)
        counts = split_and_save_by_project(
            session,
            settings,
            as_of=as_of,
            fingerprint_all_keys=captured["keys"],
            model_tag=model_tag,
            issue_keys=captured["keys"],
            z=captured["z"],
            t_snap=captured["t_snap"],
            stream_dir=captured["sdir"],
        )
        log.info("saved Dual-Head memory snapshots: %s", counts)
    else:
        log.warning("Dual-Head score finished without captured memory snapshots")
    return df, counts


def _bare_keys(issue_keys: list[str]) -> list[str]:
    out: list[str] = []
    for k in issue_keys:
        out.append(k.split("|", 1)[1] if "|" in k else k)
    return out


def try_dual_scores_from_memory(
    dual_scorer,
    *,
    duckdb_path: str | Path,
    embeddings,
    issue_keys: list[str],
    settings: Settings,
    session: Session | None = None,
    top_pct: float | None = None,
    delay_threshold: float | None = None,
) -> Any | None:
    """Reuse frozen Z when stream fingerprint still matches — skip TGN replay.

    Returns a Dual-Head score DataFrame, or None if any project cache is missing/stale.
    """
    import duckdb
    import pandas as pd

    from early_risk_detection.criticality.dual_head import DUAL_COLUMNS, predict_dual_ensemble
    from early_risk_detection.criticality.readout import static_matrix
    from early_risk_detection.embeddings import embed_issues
    from early_risk_detection.features.t0 import (
        add_t0_features,
        issue_durations,
        load_issues_t0,
        load_timed_links,
    )

    stream_dir = Path(settings.stream_dir)
    if not (stream_dir / "meta.json").is_file():
        return None

    model_tag = model_tag_from_settings(settings)
    bare = _bare_keys(issue_keys)
    by_project: dict[str, list[str]] = {}
    for k in bare:
        by_project.setdefault(project_of_key(k), []).append(k)

    snaps: dict[str, MemorySnapshot] = {}
    for project, p_keys in by_project.items():
        snap = load_project_snapshot(settings, project, session=session)
        if snap is None or snap.model_tag != model_tag:
            return None
        fp = stream_fingerprint(stream_dir, snap.issue_keys, model_tag)
        if fp != snap.fingerprint:
            return None
        if any(k not in snap.issue_keys for k in p_keys):
            return None
        snaps[project] = snap

    top = float(settings.criticality_top_pct if top_pct is None else top_pct)
    thr = float(settings.delay_threshold if delay_threshold is None else delay_threshold)

    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        df = load_issues_t0(con)
        links = load_timed_links(con)
        add_t0_features(df, links, issue_durations(df), backoff=dual_scorer.backoff)
    finally:
        con.close()

    key_to_row = {str(k): idx for idx, k in enumerate(df["issue_key"].astype(str).tolist())}
    ordered_keys: list[str] = []
    z_rows: list[np.ndarray] = []
    t_rows: list[float] = []
    for project, p_keys in by_project.items():
        snap = snaps[project]
        index = {k: i for i, k in enumerate(snap.issue_keys)}
        for k in p_keys:
            if k not in key_to_row:
                return None
            ordered_keys.append(k)
            z_rows.append(snap.z[index[k]])
            t_rows.append(float(snap.t_snap[index[k]]))

    z = np.stack(z_rows, axis=0).astype(np.float32)
    t_snap_sel = np.asarray(t_rows, dtype=np.float64)
    sel = np.asarray([key_to_row[k] for k in ordered_keys], dtype=np.int64)
    sub = df.iloc[sel].reset_index(drop=True)
    text_emb = embed_issues(embeddings, sub).astype(np.float32)
    svd = text_emb @ dual_scorer.svd_components.T
    for k in range(svd.shape[1]):
        sub[f"svd_{k}"] = svd[:, k]
    x, _ = static_matrix(sub, dual_scorer.instances, dual_scorer.types)
    x = ((x - dual_scorer.mu) / dual_scorer.sd).astype(np.float32)
    planned = sub["planned_t0"].values.astype(np.float32)
    log_planned = np.log(np.maximum(1.0, planned)).astype(np.float32)
    crit_scores, delay_probs, pred_dur_days = predict_dual_ensemble(
        dual_scorer.readouts, x, z, log_planned, dual_scorer.device
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
    out["is_critical"] = out["rank_in_instance"] <= np.ceil(top * n_inst)
    out["planned_duration_days"] = planned
    out["predicted_duration_days"] = pred_dur_days
    out["p_delay"] = delay_probs.astype(np.float32)
    out["is_at_risk"] = out["p_delay"] >= thr
    out["p_delay_raw"] = delay_probs.astype(np.float32)
    out["gated"] = np.zeros(len(sub), dtype=bool)
    out["p_non_work"] = np.zeros(len(sub), dtype=np.float32)
    out["p_early_non_work"] = np.zeros(len(sub), dtype=np.float32)
    out["max_sim_resolved"] = np.zeros(len(sub), dtype=np.float32)
    log.info(
        "reused Dual-Head memory cache for %d issues across %s (no TGN replay)",
        len(ordered_keys),
        sorted(snaps),
    )
    return out[DUAL_COLUMNS].sort_values(["instance", "rank_in_instance"]).reset_index(drop=True)


def delay_probs_from_cached_z(
    dual_scorer,
    *,
    duckdb_path: str | Path,
    embeddings,
    project_key: str,
    settings: Settings,
    snapshot: MemorySnapshot,
) -> dict[str, float]:
    """Cheap Dual-Head delay-head readout using frozen Z (no TGN replay)."""
    import duckdb

    from early_risk_detection.criticality.dual_head import predict_dual_ensemble
    from early_risk_detection.criticality.readout import static_matrix
    from early_risk_detection.embeddings import embed_issues
    from early_risk_detection.features.t0 import (
        add_t0_features,
        issue_durations,
        load_issues_t0,
        load_timed_links,
    )

    keys = list(snapshot.issue_keys)
    z = snapshot.z
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        df = load_issues_t0(con)
        links = load_timed_links(con)
        add_t0_features(df, links, issue_durations(df), backoff=dual_scorer.backoff)
    finally:
        con.close()

    key_to_row = {str(k): idx for idx, k in enumerate(df["issue_key"].astype(str).tolist())}
    missing = [k for k in keys if k not in key_to_row]
    if missing:
        log.warning("memory snapshot keys missing from duckdb: %s", missing[:5])
        keys = [k for k in keys if k in key_to_row]
        if not keys:
            return {}
        z = snapshot.z_for(keys)
        if z is None:
            return {}
    sel = np.asarray([key_to_row[k] for k in keys], dtype=np.int64)
    sub = df.iloc[sel].reset_index(drop=True)
    text_emb = embed_issues(embeddings, sub).astype(np.float32)
    svd = text_emb @ dual_scorer.svd_components.T
    for k in range(svd.shape[1]):
        sub[f"svd_{k}"] = svd[:, k]
    x, _ = static_matrix(sub, dual_scorer.instances, dual_scorer.types)
    x = ((x - dual_scorer.mu) / dual_scorer.sd).astype(np.float32)
    planned = sub["planned_t0"].values.astype(np.float32)
    log_planned = np.log(np.maximum(1.0, planned)).astype(np.float32)
    _crit, delay_probs, _dur = predict_dual_ensemble(
        dual_scorer.readouts, x, z.astype(np.float32), log_planned, dual_scorer.device
    )
    return {keys[i]: float(delay_probs[i]) for i in range(len(keys))}
