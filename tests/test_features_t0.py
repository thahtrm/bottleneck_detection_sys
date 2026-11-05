from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from early_risk_detection.features.t0 import (
    add_t0_features,
    chronological_split,
    history_before,
    issue_durations,
    load_issues_t0,
    load_timed_links,
)


def _load(db):
    con = duckdb.connect(db, read_only=True)
    try:
        return load_issues_t0(con), load_timed_links(con)
    finally:
        con.close()


def test_row_order_and_t0_reconstruction(jira_db):
    df, links = _load(jira_db)
    assert np.all(df["row_id"].values == np.arange(len(df)))
    assert np.all(np.diff(df["created_ts"].values) >= 0)
    # issues with a priority change report the FIRST from_value, not the final priority
    changed = df[df.prio_changed == 1]
    assert len(changed) > 0
    assert (df.loc[df.prio_changed == 0, "priority_norm_t0"] == df.loc[df.prio_changed == 0, "priority_norm"]).all()
    # links never get a timestamp before either endpoint exists
    created = df.set_index(df.instance + "|" + df.issue_key)["created_ts"]
    src = created.reindex(links.instance + "|" + links.source_key).values
    tgt = created.reindex(links.instance + "|" + links.target_key).values
    assert np.all(links.link_ts.values >= np.maximum(src, tgt))


def test_history_before_is_strictly_before():
    code = np.array([0, 0, 0, 1], np.int64)
    ts = np.array([10.0, 20.0, 30.0, 5.0])
    cnt, (s,) = history_before(code, ts, [np.array([1.0, 2.0, 4.0, 8.0])], np.array([0, 0, 1], np.int64),
                               np.array([20.0, 31.0, 5.0]))
    assert cnt.tolist() == [1, 3, 0]  # same-second events are not history
    assert s.tolist() == [1.0, 7.0, 0.0]


def test_add_t0_features_train_vs_serve_backoff(jira_db):
    df, links = _load(jira_db)
    dur = issue_durations(df)
    split = chronological_split(df)
    train = df.copy()
    backoff = add_t0_features(train, links, dur, fit_mask=split == "train")
    serve = df.copy()
    backoff2 = add_t0_features(serve, links, dur, backoff=backoff)
    assert backoff2 == backoff
    feats = [c for c in train.columns if c not in df.columns]
    assert len(feats) > 40
    pd.testing.assert_frame_equal(train[feats], serve[feats])
    assert not train[feats].isna().any().any()
    # the first issue of the database has no history at all
    first = train.iloc[0]
    assert first["assignee_hist_completed"] == 0 and first["project_hist_created"] == 0


def test_load_issues_t0_is_deterministic(jira_db):
    # regression: DuckDB arg_max/arg_min break ties arbitrarily unless given a tie-breaker
    a, _ = _load(jira_db)
    for _ in range(3):
        b, _ = _load(jira_db)
        pd.testing.assert_frame_equal(a, b)
