"""P1 KernelSHAP around Dual-Head delay head — batch/cache only.

Runtime limits (demo stability)
--------------------------------
- Interpretable feature *groups* (not full TGN memory / 100+ static cols): ~10 features
  mapped to buckets person / dependency / time / content.
- Surrogate = Ridge fitted to Dual-Head ``p_delay`` (RiskState.delay_value) so KernelSHAP
  explains the Dual-Head delay prediction without replaying TGN per coalition.
- KernelExplainer ``nsamples`` default 64; max open issues explained = ``MAX_ISSUES`` (80).
- Dual-Head memory snapshots (option B, ``erw.ml.dual_head_memory``) supply frozen Z so SHAP
  can refresh Dual-Head ``p_delay`` labels without TGN replay; IssueShap (A) still caches φ.
- Never called from HTTP request handlers — only from jobs / explicit refresh enqueue.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erw.db import utcnow
from erw.models import Issue, IssueShap, OverviewSnapshotRecord, RiskState
from erw.pipeline.chat_lookup import blocker_keys, blocks_keys
from erw.settings import Settings

log = logging.getLogger(__name__)

SHAP_METHOD = "kernel_dual_head"
FEATURE_VERSION = "dual_head_groups_v1"
# Raised from 40 after Dual-Head memory cache (option B) removed TGN replay from SHAP path.
MAX_ISSUES = 80
KERNEL_NSAMPLES = 64
BACKGROUND_SIZE = 20

# Interpretable groups around Dual-Head delay signals (bucket → features).
FEATURE_SPECS: list[tuple[str, str]] = [
    ("assignee_open_count", "person"),
    ("assignee_high_share", "person"),
    ("num_blockers", "dependency"),
    ("downstream_count", "dependency"),
    ("days_in_status", "time"),
    ("age_days", "time"),
    ("overdue", "time"),
    ("blocked", "dependency"),
    ("priority_norm", "content"),
    ("summary_len", "content"),
]
FEATURE_NAMES = [name for name, _ in FEATURE_SPECS]
FEATURE_BUCKET = {name: bucket for name, bucket in FEATURE_SPECS}

_LOCK = threading.Lock()


class ShapBusy(RuntimeError):
    pass


def resolve_model_tag(settings: Settings) -> str:
    """Bundle tag for captions: kind@version or folder name."""
    bdir = Path(settings.bundles_dir) / getattr(settings, "default_bundle", "tgn_dual_head")
    manifest = bdir / "manifest.json"
    if manifest.is_file():
        try:
            import json

            data = json.loads(manifest.read_text(encoding="utf-8"))
            kind = data.get("kind") or "dual_head_tgn"
            created = (data.get("created_at") or "")[:10]
            return f"{kind}@{created}" if created else str(kind)
        except Exception:
            log.warning("could not read dual-head manifest", exc_info=True)
    return getattr(settings, "default_bundle", "tgn_dual_head")


def _days_in_status(session: Session, issue: Issue, now: datetime) -> float:
    from erw.models import Change

    last = session.scalars(
        select(Change)
        .where(Change.issue_key == issue.key, Change.field == "status")
        .order_by(Change.at.desc())
        .limit(1)
    ).first()
    since = last.at if last is not None and last.at is not None else issue.created_at or now
    return max(0.0, (now - since).total_seconds() / 86400.0)


def build_feature_matrix(
    session: Session,
    open_rows: list[tuple[Issue, RiskState | None]],
    now: datetime,
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Return X [n, F], issue keys, y Dual-Head p_delay (nan if missing)."""
    open_keys = {i.key for i, _ in open_rows}
    assignee_open: dict[str, int] = defaultdict(int)
    assignee_high: dict[str, int] = defaultdict(int)
    for issue, risk in open_rows:
        name = (issue.assignee_name or issue.assignee_id or "").strip()
        if not name:
            continue
        assignee_open[name] += 1
        if risk is not None and (risk.level or "").upper() == "HIGH":
            assignee_high[name] += 1

    rows_x: list[list[float]] = []
    keys: list[str] = []
    y: list[float] = []
    today = now.date()
    for issue, risk in open_rows:
        name = (issue.assignee_name or issue.assignee_id or "").strip()
        open_n = float(assignee_open.get(name, 0))
        high_n = float(assignee_high.get(name, 0))
        high_share = (high_n / open_n) if open_n else 0.0
        blockers = blocker_keys(session, issue.key)
        downs = [k for k in blocks_keys(session, issue.key) if k in open_keys]
        age = 0.0
        if issue.created_at is not None:
            age = max(0.0, (now - issue.created_at).total_seconds() / 86400.0)
        overdue = 1.0 if issue.duedate is not None and issue.duedate < today else 0.0
        blocked = 1.0 if (risk is not None and risk.blocked) else 0.0
        summary_len = float(len(issue.summary or ""))
        feat = {
            "assignee_open_count": open_n,
            "assignee_high_share": high_share,
            "num_blockers": float(len(blockers)),
            "downstream_count": float(len(downs)),
            "days_in_status": _days_in_status(session, issue, now),
            "age_days": age,
            "overdue": overdue,
            "blocked": blocked,
            "priority_norm": float(issue.priority_norm or 0.0),
            "summary_len": summary_len,
        }
        rows_x.append([feat[n] for n in FEATURE_NAMES])
        keys.append(issue.key)
        y.append(float(risk.delay_value) if risk is not None and risk.delay_value is not None else float("nan"))
    return np.asarray(rows_x, dtype=np.float64), keys, np.asarray(y, dtype=np.float64)


def _fit_surrogate(X: np.ndarray, y: np.ndarray):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    mask = np.isfinite(y)
    if mask.sum() < 3:
        # Constant fallback so KernelSHAP still runs on structure.
        model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        yy = np.nan_to_num(y, nan=0.5)
        model.fit(X, yy)
        return model, float(np.nanmean(yy))
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(X[mask], y[mask])
    return model, float(np.mean(y[mask]))


def _kernel_shap_values(
    model,
    X: np.ndarray,
    *,
    nsamples: int = KERNEL_NSAMPLES,
    background_size: int = BACKGROUND_SIZE,
) -> tuple[np.ndarray, float]:
    """KernelSHAP φ for each row; returns (phi [n,F], base_value)."""
    import shap

    n = X.shape[0]
    if n == 0:
        return np.zeros((0, X.shape[1])), 0.0
    bg_n = min(background_size, n)
    # Deterministic background: lowest-index rows (stable in tests).
    background = X[:bg_n]
    explainer = shap.KernelExplainer(model.predict, background)
    # shap 0.53: nsamples can be int; keep small for demo.
    phi = explainer.shap_values(X, nsamples=nsamples, l1_reg=False)
    base = float(np.mean(explainer.expected_value) if np.ndim(explainer.expected_value) else explainer.expected_value)
    phi_arr = np.asarray(phi, dtype=np.float64)
    if phi_arr.ndim == 1:
        phi_arr = phi_arr.reshape(1, -1)
    return phi_arr, base


def compute_project_shap_summary(
    rows: list[dict[str, Any]],
    *,
    high_only: bool = False,
) -> dict[str, Any]:
    """mean |φ| per feature + bucket rollup."""
    filtered = [r for r in rows if (not high_only) or (r.get("level") == "HIGH")]
    if not filtered:
        filtered = rows
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in filtered:
        for item in row.get("values") or []:
            name = item["feature"]
            sums[name] += abs(float(item["phi"]))
            counts[name] += 1
    features = [
        {
            "feature": name,
            "mean_abs_phi": round(sums[name] / max(1, counts[name]), 5),
            "bucket": FEATURE_BUCKET.get(name, "content"),
        }
        for name in FEATURE_NAMES
        if counts[name]
    ]
    features.sort(key=lambda x: -x["mean_abs_phi"])
    buckets: dict[str, float] = defaultdict(float)
    for f in features:
        buckets[f["bucket"]] += f["mean_abs_phi"]
    bucket_rows = [
        {"bucket": b, "mean_abs_phi": round(v, 5)}
        for b, v in sorted(buckets.items(), key=lambda kv: -kv[1])
    ]
    return {
        "features": features[:10],
        "buckets": bucket_rows,
        "n_issues": len(filtered),
        "high_only": high_only,
    }


def _refresh_delay_labels_from_memory(
    session: Session,
    settings: Settings,
    project: str,
    open_rows: list[tuple[Issue, RiskState | None]],
) -> dict[str, float]:
    """If Dual-Head Z cache (B) exists, readout delay probs without TGN replay."""
    try:
        from erw.ml.batch import LibraryScorers
        from erw.ml.dual_head_memory import delay_probs_from_cached_z, load_project_snapshot
    except Exception:
        log.warning("Dual-Head memory helpers unavailable", exc_info=True)
        return {}

    snap = load_project_snapshot(settings, project, session=session)
    if snap is None:
        return {}
    scorers = LibraryScorers(settings)
    scorers._load()
    if scorers._dual is None:
        return {}
    try:
        probs = delay_probs_from_cached_z(
            scorers._dual,
            duckdb_path=str(settings.work_duckdb),
            embeddings=scorers._emb,
            project_key=project,
            settings=settings,
            snapshot=snap,
        )
    except Exception:
        log.warning("delay readout from memory cache failed; using RiskState labels", exc_info=True)
        return {}
    # Optionally align RiskState for consistency (batch already owns scores; SHAP labels only).
    _ = open_rows
    return probs


def run_shap_batch(
    session: Session,
    project: str,
    now: datetime,
    settings: Settings,
    *,
    nsamples: int = KERNEL_NSAMPLES,
    max_issues: int = MAX_ISSUES,
) -> dict[str, Any]:
    """Compute + persist IssueShap for open issues. Caller commits."""
    if not _LOCK.acquire(blocking=False):
        raise ShapBusy("another SHAP batch is running")
    try:
        model_tag = resolve_model_tag(settings)
        rows = session.execute(
            select(Issue, RiskState)
            .outerjoin(RiskState, RiskState.issue_key == Issue.key)
            .where(Issue.project_key == project, Issue.deleted_at.is_(None))
        ).all()
        open_rows = [(i, r) for i, r in rows if i.status_category != "done"]
        # Prefer HIGH/MED first for the capped set.
        open_rows.sort(
            key=lambda pair: (
                0 if pair[1] and (pair[1].level or "").upper() == "HIGH" else 1 if pair[1] and (pair[1].level or "").upper() == "MED" else 2,
                pair[0].key,
            )
        )
        open_rows = open_rows[:max_issues]
        memory_probs = _refresh_delay_labels_from_memory(session, settings, project, open_rows)
        X, keys, y = build_feature_matrix(session, open_rows, now)
        if memory_probs:
            for i, key in enumerate(keys):
                if key in memory_probs:
                    y[i] = memory_probs[key]
        if len(keys) == 0:
            return {"project": project, "n": 0, "model_tag": model_tag}

        surrogate, _mean_y = _fit_surrogate(X, y)
        phi, base = _kernel_shap_values(surrogate, X, nsamples=nsamples)
        preds = np.asarray(surrogate.predict(X), dtype=np.float64)

        # Replace prior cache for this project+method (keep history via OverviewSnapshotRecord).
        session.execute(
            delete(IssueShap).where(
                IssueShap.project_key == project,
                IssueShap.shap_method == SHAP_METHOD,
            )
        )
        session.flush()
        session.expire_all()

        level_by_key = {
            i.key: (r.level if r else None) for i, r in open_rows
        }
        stored: list[dict[str, Any]] = []
        for idx, key in enumerate(keys):
            values = [
                {
                    "feature": FEATURE_NAMES[j],
                    "phi": round(float(phi[idx, j]), 6),
                    "bucket": FEATURE_BUCKET[FEATURE_NAMES[j]],
                }
                for j in range(len(FEATURE_NAMES))
            ]
            values.sort(key=lambda v: -abs(v["phi"]))
            row = IssueShap(
                project_key=project,
                issue_key=key,
                model_tag=model_tag,
                shap_method=SHAP_METHOD,
                as_of=now,
                base_value=round(base, 6),
                pred=round(float(preds[idx]), 6),
                values=values,
                feature_version=FEATURE_VERSION,
                meta={
                    "dual_head_p_delay": None if not np.isfinite(y[idx]) else round(float(y[idx]), 6),
                    "nsamples": nsamples,
                    "surrogate": "ridge_on_dual_head_p_delay",
                    "memory_cache": bool(memory_probs),
                },
            )
            session.add(row)
            stored.append(
                {
                    "issue_key": key,
                    "level": level_by_key.get(key),
                    "values": values,
                    "base_value": row.base_value,
                    "pred": row.pred,
                }
            )

        summary = compute_project_shap_summary(stored, high_only=False)
        summary_high = compute_project_shap_summary(stored, high_only=True)
        session.add(
            OverviewSnapshotRecord(
                project_key=project,
                as_of=now,
                payload={
                    "kind": "shap_batch",
                    "model_tag": model_tag,
                    "shap_method": SHAP_METHOD,
                    "feature_version": FEATURE_VERSION,
                    "shap_project": summary,
                    "shap_project_high": summary_high,
                    "n_issues": len(stored),
                },
                created_at=utcnow(),
            )
        )
        return {
            "project": project,
            "n": len(stored),
            "model_tag": model_tag,
            "shap_method": SHAP_METHOD,
            "as_of": now.isoformat(),
            "nsamples": nsamples,
            "feature_version": FEATURE_VERSION,
        }
    finally:
        _LOCK.release()


def load_latest_issue_shap(
    session: Session, project: str
) -> tuple[dict[str, IssueShap], dict[str, Any] | None]:
    """Latest SHAP rows per issue for project (by as_of)."""
    rows = session.scalars(
        select(IssueShap)
        .where(IssueShap.project_key == project, IssueShap.shap_method == SHAP_METHOD)
        .order_by(IssueShap.as_of.desc())
    ).all()
    if not rows:
        return {}, None
    latest_as_of = rows[0].as_of
    by_key: dict[str, IssueShap] = {}
    for row in rows:
        if row.as_of != latest_as_of:
            break
        by_key[row.issue_key] = row
    meta = {
        "model_tag": rows[0].model_tag,
        "shap_method": SHAP_METHOD,
        "feature_version": rows[0].feature_version,
        "as_of": latest_as_of.isoformat() if latest_as_of else None,
        "n": len(by_key),
    }
    return by_key, meta


def list_overview_snapshots(session: Session, project: str, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(OverviewSnapshotRecord)
        .where(OverviewSnapshotRecord.project_key == project)
        .order_by(OverviewSnapshotRecord.as_of.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "as_of": r.as_of.isoformat() if r.as_of else None,
            "kind": (r.payload or {}).get("kind"),
            "model_tag": (r.payload or {}).get("model_tag"),
            "n_issues": (r.payload or {}).get("n_issues"),
            "payload": r.payload or {},
        }
        for r in rows
    ]


def compare_shap_snapshots(
    session: Session, project: str, *, newer_id: int | None = None, older_id: int | None = None
) -> dict[str, Any] | None:
    """Compare two SHAP project summaries (bucket / feature mean|φ| deltas)."""
    snaps = list_overview_snapshots(session, project, limit=20)
    shap_snaps = [s for s in snaps if (s.get("payload") or {}).get("shap_project")]
    if len(shap_snaps) < 2 and newer_id is None:
        return None
    by_id = {s["id"]: s for s in snaps}
    if newer_id and older_id and newer_id in by_id and older_id in by_id:
        newer, older = by_id[newer_id], by_id[older_id]
    else:
        if len(shap_snaps) < 2:
            return None
        newer, older = shap_snaps[0], shap_snaps[1]

    def _bucket_map(snap: dict[str, Any]) -> dict[str, float]:
        rows = ((snap.get("payload") or {}).get("shap_project") or {}).get("buckets") or []
        return {r["bucket"]: float(r["mean_abs_phi"]) for r in rows}

    def _feat_map(snap: dict[str, Any]) -> dict[str, float]:
        rows = ((snap.get("payload") or {}).get("shap_project") or {}).get("features") or []
        return {r["feature"]: float(r["mean_abs_phi"]) for r in rows}

    nb, ob = _bucket_map(newer), _bucket_map(older)
    nf, of = _feat_map(newer), _feat_map(older)
    buckets = sorted(set(nb) | set(ob))
    features = sorted(set(nf) | set(of))
    return {
        "newer": {"id": newer["id"], "as_of": newer["as_of"], "model_tag": newer.get("model_tag")},
        "older": {"id": older["id"], "as_of": older["as_of"], "model_tag": older.get("model_tag")},
        "bucket_delta": [
            {"bucket": b, "newer": nb.get(b, 0.0), "older": ob.get(b, 0.0), "delta": round(nb.get(b, 0.0) - ob.get(b, 0.0), 5)}
            for b in buckets
        ],
        "feature_delta": [
            {
                "feature": f,
                "newer": nf.get(f, 0.0),
                "older": of.get(f, 0.0),
                "delta": round(nf.get(f, 0.0) - of.get(f, 0.0), 5),
                "bucket": FEATURE_BUCKET.get(f, "content"),
            }
            for f in features
        ],
        "note": (
            "So sánh mean|φ| giữa 2 batch SHAP đã cache. Không so sánh checkpoint Dual-Head "
            "nặng (runtime); dùng surrogate KernelSHAP quanh p_delay Dual-Head."
        ),
    }
