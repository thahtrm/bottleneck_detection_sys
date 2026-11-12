"""Stage 6 — Blend the delay components and calibrate the pre-triage gate on VALIDATION only.

p_raw   = interp(0.45 p_xgb + 0.30 p_aft + 0.15 p_catboost + 0.10 (1 - p_non_work); knots)   (study blend)
gate    = p_early_non_work >= p_th  OR  max_sim_resolved >= s_th
p_delay = p_raw * damp if gate else p_raw ; flagged if p_delay >= threshold
p_th / s_th are chosen on val to maximise F1 while keeping recall >= --min_recall (the study's
constraint), then the decision threshold is re-optimised on the gated val scores. Test is only
scored with the frozen choices. Writes blend_gate.json to the staging bundle.
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, recall_score

from early_risk_detection._logging import setup_logging
from early_risk_detection.bundle import ModelBundle
from early_risk_detection.delay.gate import gate_mask
from early_risk_detection.delay.scorer import KIND
from early_risk_detection.delay.survival import blend
from early_risk_detection.evaluation import evaluate_predictions, find_optimal_threshold

log = logging.getLogger(__name__).info

STUDY_BLEND = {"weights": [0.45, 0.30, 0.15, 0.10], "knots_x": [0.0, 0.3250, 0.4350, 1.0],
               "knots_y": [0.0, 0.4600, 0.4699, 0.95], "damp": 0.2}


def load(exp: Path, data: Path, split: str) -> pd.DataFrame:
    m = pd.read_csv(exp / "xgboost" / f"predictions_{split}.csv").rename(columns={"y_prob": "p_xgb"})
    for name, col in [("survival_aft", "p_aft"), ("catboost_survival", "p_cbs")]:
        m = m.merge(pd.read_csv(exp / name / f"predictions_{split}.csv")[["uid", "y_prob"]].rename(columns={"y_prob": col}),
                    on="uid", validate="1:1")
    m = m.merge(pd.read_parquet(data / f"gate_{split}.parquet"), on="uid", validate="1:1")
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="experiments/delay_t0")
    ap.add_argument("--data_dir", default="data/delay_t0")
    ap.add_argument("--stage", default="bundles/staging/delay")
    ap.add_argument("--leaderboard", default="experiments/leaderboard_delay_t0.json")
    ap.add_argument("--min_recall", type=float, default=0.80)
    args = ap.parse_args()
    setup_logging()
    exp, data = Path(args.experiments), Path(args.data_dir)
    va, te = load(exp, data, "val"), load(exp, data, "test")
    cfg = dict(STUDY_BLEND)

    def raw(m):
        return blend(m.p_xgb.values, m.p_aft.values, m.p_cbs.values, m.p_non_work.values,
                     cfg["weights"], cfg["knots_x"], cfg["knots_y"])

    va["p_raw"], te["p_raw"] = raw(va), raw(te)
    t_raw, f1_raw, _, _ = find_optimal_threshold(va.y_true.values, va.p_raw.values)
    log(f"blend (no gate): val F1 {f1_raw:.4f} @ {t_raw:.3f}")

    best = None
    for p_th, s_th in itertools.product([0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.99, 1.01],
                                        [0.90, 0.92, 0.95, 0.97, 0.99, 1.01]):
        g = gate_mask(va.p_early_non_work.values, va.max_sim_resolved.values, p_th, s_th)
        p = np.where(g, va.p_raw.values * cfg["damp"], va.p_raw.values)
        pred = p >= t_raw
        rec = recall_score(va.y_true, pred)
        f1 = f1_score(va.y_true, pred)
        if rec >= args.min_recall and (best is None or f1 > best[0]):
            best = (f1, p_th, s_th, float(g.mean()), rec)
    if best is None:
        log(f"no gate keeps val recall >= {args.min_recall}; gate disabled")
        best = (f1_raw, 1.01, 1.01, 0.0, float("nan"))
    _, p_th, s_th, gated_rate, _ = best
    log(f"gate: p_early >= {p_th}, max_sim_resolved >= {s_th} -> {gated_rate:.2%} of val damped")
    cfg.update({"gate_p_threshold": p_th, "gate_sim_threshold": s_th})

    out = exp / "official"
    out.mkdir(parents=True, exist_ok=True)
    for name, m in [("val", va), ("test", te)]:
        g = gate_mask(m.p_early_non_work.values, m.max_sim_resolved.values, p_th, s_th)
        m["gated"] = g.astype(np.int8)
        m["y_prob"] = np.where(g, m.p_raw.values * cfg["damp"], m.p_raw.values)
        m[["uid", "y_true", "y_prob", "p_raw", "gated"]].to_csv(out / f"predictions_{name}.csv", index=False)
        m[["uid", "y_true"]].assign(y_prob=m.p_raw).to_csv(out / f"predictions_blend_{name}.csv", index=False)
    evaluate_predictions(str(out / "predictions_blend_test.csv"), str(out / "predictions_blend_val.csv"),
                         track="delay_blend_t0", leaderboard_path=args.leaderboard)
    res = evaluate_predictions(str(out / "predictions_test.csv"), str(out / "predictions_val.csv"),
                               track="delay_official_t0", leaderboard_path=args.leaderboard)
    cfg["threshold"] = res["optimal_threshold"]
    stage = ModelBundle.staging(args.stage, KIND)
    stage.save_json("blend_gate.json", cfg)
    (out / "blend_gate.json").write_text(json.dumps(cfg, indent=2))
    log(f"final: {json.dumps(res['test_metrics'])}")


if __name__ == "__main__":
    main()
