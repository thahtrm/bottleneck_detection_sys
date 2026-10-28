"""End-to-end: tiny delay components trained with the library API -> bundle -> DelayRiskScorer."""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest
import torch
import xgboost as xgb
from test_criticality import HashEmbedder

from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay import DelayRiskScorer
from early_risk_detection.delay.features import DelayFeaturizer, TextRiskFeatures, chronological_features
from early_risk_detection.delay.gate import (
    CAUSAL_NW_COLUMNS,
    SEM_KNN_COLUMNS,
    causal_nonwork_features,
    gate_mask,
    nonwork_labels,
    semantic_knn_features,
)
from early_risk_detection.delay.scorer import KIND
from early_risk_detection.delay.survival import blend, survival_delay_prob
from early_risk_detection.embeddings import embedding_text
from early_risk_detection.features.t0 import chronological_split, load_issues_t0, load_timed_links, select_issues

catboost = pytest.importorskip("catboost")
GATE = {"prior": 0.3, "smoothing": 5.0, "window_days": 90.0, "active_window": 16, "resolved_pool": 64, "k": 5,
        "dup_sim": 0.9, "early_days": 7.0}
BLEND = {"weights": [0.45, 0.30, 0.15, 0.10], "knots_x": [0.0, 0.325, 0.435, 1.0], "knots_y": [0.0, 0.46, 0.4699, 0.95],
         "damp": 0.2, "gate_p_threshold": 0.6, "gate_sim_threshold": 0.95, "threshold": 0.45}


def test_delay_scorer_end_to_end(jira_db, tmp_path):
    con = duckdb.connect(jira_db, read_only=True)
    df, links = load_issues_t0(con), load_timed_links(con)
    con.close()
    base = chronological_features(df, links)
    split = chronological_split(df)
    emb_fn = HashEmbedder()
    emb = emb_fn(embedding_text(df).tolist())
    tr = (split == "train") & (base.is_resolved.values == 1)
    text = TextRiskFeatures().fit(emb[tr], base.is_delayed.values[tr])
    base = base.join(text.transform(emb, base))
    fx, fs = DelayFeaturizer(), DelayFeaturizer()
    Xtr = fx.fit_transform(base[tr].reset_index(drop=True))
    Str = fs.fit_transform(base[split == "train"].reset_index(drop=True))
    y = base.is_delayed.values[tr]
    cens = base[split == "train"].reset_index(drop=True)

    b = ModelBundle.create(tmp_path / "delay", KIND)
    text.save(b)
    fx.save(b, "xgb")
    fs.save(b, "surv")
    for k in range(2):
        xgb.XGBClassifier(n_estimators=5, max_depth=3, random_state=k).fit(Xtr, y).save_model(b.file(f"xgb_fold{k}.ubj"))
    d = xgb.DMatrix(Str)
    d.set_float_info("label_lower_bound", cens.lower_bound.values)
    d.set_float_info("label_upper_bound", cens.upper_bound.values)
    xgb.train({"objective": "survival:aft", "aft_loss_distribution": "normal", "aft_loss_distribution_scale": 1.0},
              d, 5).save_model(b.file("aft.ubj"))
    b.save_json("aft_config.json", {"distribution": "normal", "scale": 1.0})
    target = np.stack([np.maximum(0.01, cens.lower_bound.values),
                       np.where(np.isinf(cens.upper_bound.values), -1.0, cens.lower_bound.values)], 1)
    for name in ["cbs", "cbs_cr"]:
        m = catboost.CatBoostRegressor(iterations=5, depth=3, loss_function="SurvivalAft:dist=Normal;scale=1.0", verbose=False)
        m.fit(catboost.Pool(Str, target))
        m.save_model(str(b.file(f"{name}.cbm")))
        b.save_json(f"{name}_config.json", {"distribution": "Normal", "scale": 1.0})
    nw = nonwork_labels(df.resolution) * (df.is_resolved.values == 1)
    rows_tr = np.flatnonzero(tr)
    causal = causal_nonwork_features(df, nw, GATE["prior"])
    get = lambda r: emb[r]  # noqa: E731
    sem = semantic_knn_features(df, nw, get, prior=GATE["prior"], active_window=16, resolved_pool=64, k=5,
                                device=torch.device("cpu"))
    xgb.XGBClassifier(n_estimators=5, max_depth=3).fit(Xtr, nw[rows_tr]).save_model(b.file("nonwork.ubj"))
    gx = pd.concat([Xtr, pd.DataFrame(np.hstack([causal[rows_tr], sem[rows_tr]]), columns=CAUSAL_NW_COLUMNS + SEM_KNN_COLUMNS)], axis=1)
    xgb.XGBClassifier(n_estimators=5, max_depth=3).fit(gx, nw[rows_tr]).save_model(b.file("early_nonwork.ubj"))
    b.save_json("gate_config.json", GATE)
    b.save_json("blend_gate.json", BLEND)
    b.finalize()

    scorer = DelayRiskScorer.load(tmp_path / "delay", device="cpu")
    as_of = pd.Timestamp(df.created_ts.max() + 1, unit="s", tz="UTC")
    out = scorer.score(jira_db, embeddings=emb_fn, as_of=as_of)
    open_rows = select_issues(df, as_of=as_of)
    assert set(out.uid) == set((df.instance + "|" + df.issue_key).values[open_rows])
    assert out.p_delay.between(0, 1).all() and (out.predicted_duration_days > 0).all()

    # recompose by hand from the training-side objects
    sub = base.iloc[open_rows].reset_index(drop=True)
    Xx, Xs = fx.transform(sub), fs.transform(sub)
    planned = sub.planned_duration_days.values.astype(np.float32)
    p_x = np.mean([scorer.xgb_folds[k].predict_proba(Xx)[:, 1] for k in range(2)], 0)
    p_a = survival_delay_prob(np.log(np.maximum(1e-3, scorer.aft.predict(xgb.DMatrix(Xs)))), planned, "normal", 1.0)
    p_c = survival_delay_prob(scorer.cbs.predict(Xs), planned, "Normal", 1.0)
    p_nw = scorer.nonwork.predict_proba(Xx)[:, 1]
    extra = pd.DataFrame(np.hstack([causal[open_rows], sem[open_rows]]), columns=CAUSAL_NW_COLUMNS + SEM_KNN_COLUMNS)
    p_e = scorer.early.predict_proba(pd.concat([Xx, extra], axis=1))[:, 1]
    raw = blend(p_x, p_a, p_c, p_nw, BLEND["weights"], BLEND["knots_x"], BLEND["knots_y"])
    g = gate_mask(p_e, sem[open_rows, 2], BLEND["gate_p_threshold"], BLEND["gate_sim_threshold"])
    want = pd.Series(np.where(g, raw * BLEND["damp"], raw), index=sub.instance + "|" + sub.issue_key)
    got = out.set_index("uid").p_delay.loc[want.index]
    np.testing.assert_allclose(got.values, want.values, rtol=1e-5, atol=1e-6)
