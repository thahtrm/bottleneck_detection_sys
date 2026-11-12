from __future__ import annotations

import hashlib

import duckdb
import numpy as np
import pandas as pd
import torch

from early_risk_detection.bundle import ModelBundle
from early_risk_detection.criticality import CriticalityScorer
from early_risk_detection.criticality.memory import EventStream, TGNMemory, snapshot_memory
from early_risk_detection.criticality.readout import Readout, static_matrix
from early_risk_detection.criticality.scorer import KIND
from early_risk_detection.criticality.stream import build_event_stream, load_neighbours
from early_risk_detection.features.t0 import (
    add_t0_features,
    chronological_split,
    issue_durations,
    load_issues_t0,
    load_timed_links,
)

CPU = torch.device("cpu")


class HashEmbedder:
    """Deterministic stand-in for Ollama."""

    def __call__(self, texts):
        out = np.zeros((len(texts), 768), np.float16)
        for i, t in enumerate(texts):
            seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16)
            out[i] = np.random.default_rng(seed).standard_normal(768)
        return out


def _prepare(jira_db, tmp_path):
    con = duckdb.connect(jira_db, read_only=True)
    df, links = load_issues_t0(con), load_timed_links(con)
    meta = build_event_stream(con, df, tmp_path / "events")
    con.close()
    return df, links, meta


def test_snapshot_never_sees_events_at_or_after_t0(jira_db, tmp_path):
    df, _, meta = _prepare(jira_db, tmp_path)
    created = df["created_ts"].values.astype(np.float64)
    torch.manual_seed(0)
    model = TGNMemory(meta["n_nodes"], CPU)
    stream = EventStream(tmp_path / "events", chunk=50, device=CPU)
    neigh = load_neighbours(tmp_path / "events")
    Z, aux, applied = snapshot_memory(model, stream, created, neigh)
    assert np.all(applied < created)
    assert np.abs(Z.astype(np.float32)).sum() > 0
    # snapshotting a subset (early stop) gives the same memory as the full pass
    rows = np.array([3, 50, 120, len(df) // 2])
    Zs, auxs, _ = snapshot_memory(model, stream, created, neigh, rows=rows)
    np.testing.assert_array_equal(Zs, Z[rows])
    np.testing.assert_array_equal(auxs, aux[rows])


def test_scorer_end_to_end(jira_db, tmp_path):
    df, links, meta = _prepare(jira_db, tmp_path)
    split = chronological_split(df)
    backoff = add_t0_features(df, links, issue_durations(df), fit_mask=split == "train")
    rng = np.random.default_rng(0)
    comps = rng.standard_normal((16, 768)).astype(np.float32) / 30
    emb = HashEmbedder()
    from early_risk_detection.embeddings import embedding_text

    svd = emb(embedding_text(df).tolist()).astype(np.float32) @ comps.T
    for k in range(16):
        df[f"svd_{k}"] = svd[:, k]
    instances = sorted(df.instance.unique())
    types = df.loc[split == "train", "issuetype_t0"].value_counts().index[:30].tolist()
    X, names = static_matrix(df, instances, types)
    tr = split == "train"
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6

    torch.manual_seed(0)
    mem = TGNMemory(meta["n_nodes"], CPU)
    stream = EventStream(tmp_path / "events", chunk=50, device=CPU)
    Z, aux, _ = snapshot_memory(mem, stream, df.created_ts.values.astype(np.float64), load_neighbours(tmp_path / "events"))
    amu, asd = aux[tr].mean(0), aux[tr].std(0) + 1e-6

    b = ModelBundle.create(tmp_path / "bundle", KIND, {
        "chunk": 50, "readout_files": ["readout_seed1.pt", "readout_seed2.pt"], "dropout": 0.2,
        "static_features": names, "instances": instances, "types": types, "propensity_backoff": backoff,
        "top_pct": 0.05})
    torch.save(mem.state_dict(), b.file("tgn_memory.pt"))
    readouts = []
    for s in (1, 2):
        torch.manual_seed(s)
        r = Readout(len(names), use_z=True).eval()
        torch.save(r.state_dict(), b.file(f"readout_seed{s}.pt"))
        readouts.append(r)
    b.save_arrays("normalizers.npz", mu=mu, sd=sd, amu=amu, asd=asd, svd_components=comps)
    b.finalize()

    scorer = CriticalityScorer.load(tmp_path / "bundle", device="cpu")
    as_of = pd.Timestamp(df.created_ts.max() + 1, unit="s", tz="UTC")
    out = scorer.score(jira_db, embeddings=emb, as_of=as_of, stream_dir=tmp_path / "events")
    open_now = df[df.resolved_ts.isna() | (df.resolved_ts > as_of.timestamp())]
    assert set(out.uid) == set(open_now.instance + "|" + open_now.issue_key)
    assert out.score.between(0, 1).all()
    assert out.groupby("instance").is_critical.sum().ge(1).all()

    # same numbers as the training-side computation on the full matrices
    rows = open_now.index.values
    x = ((X[rows] - mu) / sd).astype(np.float32)
    z = np.concatenate([Z[rows], ((aux[rows] - amu) / asd).astype(np.float16)], 1)
    with torch.no_grad():
        want = np.mean([r(torch.from_numpy(x), torch.from_numpy(z).float()).numpy() for r in readouts], 0)
    got = out.set_index("uid").loc[(open_now.instance + "|" + open_now.issue_key).values, "score"].values
    np.testing.assert_allclose(got, want, rtol=1e-5, atol=1e-6)


def test_dual_head_scorer_end_to_end_and_default_scorers(jira_db, tmp_path):
    from early_risk_detection import DEFAULT_BUNDLE_PATH, DelayRiskScorer, DualHeadScorer
    from early_risk_detection.criticality.dual_head import (
        DUAL_HEAD_KIND,
        DualHeadReadout,
        snapshot_memory_dual,
    )
    from early_risk_detection.embeddings import embedding_text

    assert DEFAULT_BUNDLE_PATH == "bundles/tgn_dual_head"

    df, links, meta = _prepare(jira_db, tmp_path)
    split = chronological_split(df)
    backoff = add_t0_features(df, links, issue_durations(df), fit_mask=split == "train")
    rng = np.random.default_rng(0)
    comps = rng.standard_normal((16, 768)).astype(np.float32) / 30
    emb = HashEmbedder()
    svd = emb(embedding_text(df).tolist()).astype(np.float32) @ comps.T
    for k in range(16):
        df[f"svd_{k}"] = svd[:, k]
    instances = sorted(df.instance.unique())
    types = df.loc[split == "train", "issuetype_t0"].value_counts().index[:30].tolist()
    X, names = static_matrix(df, instances, types)
    tr = split == "train"
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6

    torch.manual_seed(0)
    mem = TGNMemory(meta["n_nodes"], CPU)
    stream = EventStream(tmp_path / "events", chunk=50, device=CPU)
    created = df.created_ts.values.astype(np.float64)
    planned_t0 = df.planned_t0.values.astype(np.float32)
    Z, aux, _ = snapshot_memory_dual(
        mem,
        stream,
        created,
        created,
        planned_t0,
        load_neighbours(tmp_path / "events"),
        pre_t0_mode=False,
    )
    amu, asd = aux[tr].mean(0), np.maximum(aux[tr].std(0), 0.1)

    b = ModelBundle.create(
        tmp_path / "tgn_dual_head",
        DUAL_HEAD_KIND,
        {
            "chunk": 50,
            "project_change_mode": True,
            "n_aux": 10,
            "readout_files": ["dual_readout_seed1.pt", "dual_readout_seed2.pt"],
            "dropout": 0.2,
            "static_features": names,
            "instances": instances,
            "types": types,
            "propensity_backoff": backoff,
            "top_pct": 0.05,
            "delay_threshold_max_f1": 0.65,
            "delay_threshold_high_recall": 0.55,
        },
    )
    torch.save(mem.state_dict(), b.file("tgn_memory.pt"))
    for s in (1, 2):
        torch.manual_seed(s)
        r = DualHeadReadout(len(names)).eval()
        torch.save(r.state_dict(), b.file(f"dual_readout_seed{s}.pt"))
    b.save_arrays("normalizers.npz", mu=mu, sd=sd, amu=amu, asd=asd, svd_components=comps)
    b.finalize()

    dual_scorer = DualHeadScorer.load(tmp_path / "tgn_dual_head", device="cpu")
    as_of = pd.Timestamp(df.created_ts.max() + 1, unit="s", tz="UTC")
    out_dual = dual_scorer.score(jira_db, embeddings=emb, as_of=as_of, stream_dir=tmp_path / "events")
    open_now = df[df.resolved_ts.isna() | (df.resolved_ts > as_of.timestamp())]
    assert set(out_dual.uid) == set(open_now.instance + "|" + open_now.issue_key)
    assert out_dual.score.between(0, 1).all()
    assert out_dual.p_delay.between(0, 1).all()
    assert (out_dual.predicted_duration_days >= 0).all()

    # CriticalityScorer and DelayRiskScorer also seamlessly load dual_head_tgn bundles
    crit_scorer = CriticalityScorer.load(tmp_path / "tgn_dual_head", device="cpu")
    out_crit = crit_scorer.score(jira_db, embeddings=emb, as_of=as_of, stream_dir=tmp_path / "events")
    np.testing.assert_allclose(
        out_crit.set_index("uid")["score"], out_dual.set_index("uid")["score"], rtol=1e-5
    )

    delay_scorer = DelayRiskScorer.load(tmp_path / "tgn_dual_head", device="cpu")
    out_delay = delay_scorer.score(jira_db, embeddings=emb, as_of=as_of, stream_dir=tmp_path / "events")
    np.testing.assert_allclose(
        out_delay.set_index("uid").loc[out_dual["uid"], "p_delay"].values,
        out_dual["p_delay"].values,
        rtol=1e-5,
    )
