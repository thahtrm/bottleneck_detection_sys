"""Survival-model outputs -> P(delay) and the 4-model blend of the delay study."""
from __future__ import annotations

import numpy as np
from scipy.special import expit
from scipy.stats import norm


def survival_delay_prob(log_pred_time: np.ndarray, planned_time: np.ndarray, distribution: str,
                        scale: float) -> np.ndarray:
    """P(T > planned) for an AFT model predicting ln(T_hat) with error ``distribution`` and ``scale``.

    Same formula for XGBoost ``survival:aft`` (pass ``np.log(pred_time)``) and CatBoost
    ``SurvivalAft`` (``predict`` already returns ln(T_hat)).
    """
    z = (np.log(np.maximum(1e-3, planned_time)) - log_pred_time) / max(1e-3, scale)
    z = np.clip(z, -30.0, 30.0)
    dist = distribution.lower()
    if dist == "normal":
        prob = norm.cdf(-z)
    elif dist == "extreme":
        prob = np.exp(-np.exp(z))
    else:
        prob = expit(-z)
    return np.clip(prob, 1e-6, 1.0 - 1e-6)


def blend(p_xgb: np.ndarray, p_aft: np.ndarray, p_cbs: np.ndarray, p_nonwork: np.ndarray,
          weights: list[float], knots_x: list[float], knots_y: list[float]) -> np.ndarray:
    """Weighted blend of the classifier, the two AFT models and (1 - P(non-work)), then a monotone
    piecewise-linear calibration (ranking metrics are those of the raw blend)."""
    w = weights
    raw = w[0] * p_xgb + w[1] * p_aft + w[2] * p_cbs + w[3] * (1.0 - p_nonwork)
    return np.interp(raw, knots_x, knots_y).astype(np.float64)
