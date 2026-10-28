from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest
import torch

from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.features import DelayFeaturizer, TextRiskFeatures, chronological_features
from early_risk_detection.delay.gate import causal_nonwork_features, nonwork_labels, semantic_knn_features
from early_risk_detection.features.t0 import chronological_split, load_issues_t0, load_timed_links


@pytest.fixture(scope="module")
def issues(jira_db):
    con = duckdb.connect(jira_db, read_only=True)
    df, links = load_issues_t0(con), load_timed_links(con)
    con.close()
    return df, links


def _emb(n, seed=0):
    return np.random.default_rng(seed).standard_normal((n, 768)).astype(np.float16)


def test_chronological_features_t0_and_labels(issues):
    df, links = issues
    base = chronological_features(df, links)
    assert len(base) == len(df) and (base.row_id.values == df.row_id.values).all()
    assert (base["priority_norm"].values == df["priority_norm_t0"].fillna(0.4).values.astype(np.float32)).all()
    res = base.is_resolved == 1
    assert ((base.lower_bound > base.planned_duration_label) == (base.is_delayed == 1)).all()
    assert np.isinf(base.loc[~res, "upper_bound"]).all()
    assert base.iloc[0]["assignee_hist_completed"] == 0


def test_featurizer_round_trip(issues, tmp_path):
    df, links = issues
    base = chronological_features(df, links)
    split = chronological_split(df)
    emb = _emb(len(df))
    tr = (split == "train") & (base.is_resolved.values == 1)
    text = TextRiskFeatures().fit(emb[tr], base.is_delayed.values[tr])
    base = pd.concat([base, text.transform(emb, base)], axis=1)
    f = DelayFeaturizer()
    X_tr = f.fit_transform(base[tr].reset_index(drop=True))
    assert X_tr.shape[1] > 150 and not X_tr.isna().any().any()
    test = base[split == "test"].reset_index(drop=True)
    want = f.transform(test)

    b = ModelBundle.create(tmp_path / "b", "delay")
    f.save(b, "xgb")
    text.save(b)
    b.finalize()
    b = ModelBundle.load(tmp_path / "b")
    g = DelayFeaturizer.load(b, "xgb")
    pd.testing.assert_frame_equal(g.transform(test), want)
    t2 = TextRiskFeatures.load(b)
    pd.testing.assert_frame_equal(t2.transform(emb[:20], base.iloc[:20]), text.transform(emb[:20], base.iloc[:20]))


def test_causal_nonwork_matches_brute_force(issues):
    df, _ = issues
    nw = nonwork_labels(pd.Series(np.where(np.arange(len(df)) % 3 == 0, "Duplicate", "Fixed")))
    f = causal_nonwork_features(df, nw, prior=0.3, smoothing=5.0)
    proj = (df.instance + "|" + df.project).values
    for i in [10, 150, len(df) - 1]:
        t = df.created_ts.values[i]
        m = (proj == proj[i]) & (df.is_resolved.values == 1) & \
            (np.floor(df.resolved_ts.values) < np.floor(t)) & (df.resolved_ts.values >= np.floor(t - 90 * 86400))
        assert f[i, 0] == pytest.approx((nw[m].sum() + 5 * 0.3) / (m.sum() + 5), rel=1e-5)


def test_semantic_knn_subset_equals_full_and_brute_force(issues):
    df, _ = issues
    emb = _emb(len(df), seed=1)
    nw = nonwork_labels(pd.Series(np.where(np.arange(len(df)) % 4 == 0, "Invalid", "Fixed")))
    get = lambda rows: emb[rows]  # noqa: E731
    cpu = torch.device("cpu")
    kw = dict(prior=0.4, active_window=8, resolved_pool=16, k=3, device=cpu, chunk=7)
    full = semantic_knn_features(df, nw, get, **kw)
    rows = np.array([5, 77, 200, len(df) - 2])
    sub = semantic_knn_features(df, nw, get, query_rows=rows, **kw)
    np.testing.assert_allclose(sub, full[rows], atol=1e-5)

    e = emb.astype(np.float32)
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    grp = (df.instance + "|" + df.project).values
    created, resolved = df.created_ts.values, df.resolved_ts.fillna(np.inf).values
    for i in rows:
        same = np.flatnonzero(grp == grp[i])
        prev = same[same < i][-8:]
        act = prev[(created[prev] < created[i]) & (resolved[prev] > created[i])]
        want0 = max(0.0, (e[act] @ e[i]).max()) if len(act) else 0.0
        assert full[i, 0] == pytest.approx(want0, abs=1e-5)
        done = same[resolved[same] < created[i]]
        done = done[np.argsort(resolved[done], kind="stable")][-16:]
        want2 = max(0.0, (e[done] @ e[i]).max()) if len(done) else 0.0
        assert full[i, 2] == pytest.approx(want2, abs=1e-5)


def test_issue_resolved_at_creation_instant(tmp_path):
    from conftest import make_jira_db

    db = make_jira_db(tmp_path / "j.duckdb", n_issues=60, seed=3)
    con = duckdb.connect(db)
    k = con.execute("SELECT instance, issue_key, created_ts FROM issues ORDER BY created_ts LIMIT 1 OFFSET 10").fetchone()
    con.execute("UPDATE issues SET resolved_ts = created_ts WHERE instance = ? AND issue_key = ?", [k[0], k[1]])
    df, links = load_issues_t0(con), load_timed_links(con)
    con.close()
    base = chronological_features(df, links)
    row = base[(base.instance == k[0]) & (base.issue_key == k[1])].iloc[0]
    assert row.is_resolved == 1 and row.duration_days == 0
