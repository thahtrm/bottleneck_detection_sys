"""Dual-Head memory snapshot cache (option B)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from erw.ml.dual_head_memory import (
    invalidate_all,
    load_project_snapshot,
    memory_root,
    save_project_snapshot,
    stream_fingerprint,
    try_dual_scores_from_memory,
)
from erw.models import DualHeadMemorySnapshot
from erw.settings import Settings


def test_stream_fingerprint_stable(tmp_path):
    stream = tmp_path / "stream"
    stream.mkdir()
    (stream / "meta.json").write_text('{"n_events": 12, "n_issue": 3}', encoding="utf-8")
    a = stream_fingerprint(stream, ["DEMO-2", "DEMO-1"], "tag")
    b = stream_fingerprint(stream, ["DEMO-1", "DEMO-2"], "tag")
    c = stream_fingerprint(stream, ["DEMO-1", "DEMO-2"], "other")
    assert a == b
    assert a != c


def test_save_load_invalidate(session, tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        db_url="sqlite://",
        stream_dir=str(tmp_path / "stream"),
        bundles_dir=str(tmp_path / "bundles"),
    )
    (tmp_path / "stream").mkdir()
    (tmp_path / "stream" / "meta.json").write_text('{"n_events": 1}', encoding="utf-8")
    z = np.random.randn(3, 8).astype(np.float32)
    t = np.arange(3, dtype=np.float64)
    keys = ["DEMO-1", "DEMO-2", "DEMO-3"]
    fp = stream_fingerprint(tmp_path / "stream", keys, "dual@test")
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    path = save_project_snapshot(
        session,
        settings,
        project_key="DEMO",
        as_of=now,
        fingerprint=fp,
        model_tag="dual@test",
        issue_keys=keys,
        z=z,
        t_snap=t,
        stream_version="1",
    )
    session.commit()
    assert path.is_file()

    from sqlalchemy import func, select

    n = session.scalar(select(func.count()).select_from(DualHeadMemorySnapshot))
    assert n == 1

    snap = load_project_snapshot(settings, "DEMO", fingerprint=fp, session=session)
    assert snap is not None
    assert snap.issue_keys == keys
    assert snap.z.shape == (3, 8)
    assert np.allclose(snap.z, z, atol=1e-2)  # float16 roundtrip

    miss = load_project_snapshot(settings, "DEMO", fingerprint="nope", session=session)
    assert miss is None

    invalidate_all(session, settings)
    session.commit()
    assert not memory_root(settings).exists() or not any(memory_root(settings).rglob("*.npz"))
    assert session.scalar(select(func.count()).select_from(DualHeadMemorySnapshot)) == 0


def test_try_dual_scores_requires_stream_meta(tmp_path):
    settings = Settings(
        _env_file=None,
        db_url="sqlite://",
        stream_dir=str(tmp_path / "stream"),
        bundles_dir=str(tmp_path / "bundles"),
    )
    (tmp_path / "stream").mkdir()
    # no meta.json → cannot reuse
    assert (
        try_dual_scores_from_memory(
            object(),
            duckdb_path=tmp_path / "missing.duckdb",
            embeddings=object(),
            issue_keys=["ERW|DEMO-1"],
            settings=settings,
        )
        is None
    )
