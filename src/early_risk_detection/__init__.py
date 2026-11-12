"""early-risk-detection: early detection of delay-risk and critical tasks in Jira issue trackers.

    from early_risk_detection import DualHeadScorer
    from early_risk_detection.embeddings import EmbeddingIndex

    scorer = DualHeadScorer.load()  # defaults to "bundles/tgn_dual_head"
    scores = scorer.score("data/jira.duckdb", embeddings=EmbeddingIndex("data"))
"""
from __future__ import annotations

__version__ = "0.1.0"

DEFAULT_BUNDLE_PATH = "bundles/tgn_dual_head"

__all__ = [
    "DualHeadScorer",
    "CriticalityScorer",
    "DelayRiskScorer",
    "ModelBundle",
    "DEFAULT_BUNDLE_PATH",
    "__version__",
]


def __getattr__(name: str):
    # Lazy: importing the package must not pull in torch / catboost until a scorer is used.
    if name == "DualHeadScorer":
        from .criticality import DualHeadScorer

        return DualHeadScorer
    if name == "CriticalityScorer":
        from .criticality import CriticalityScorer

        return CriticalityScorer
    if name == "DelayRiskScorer":
        from .delay import DelayRiskScorer

        return DelayRiskScorer
    if name == "ModelBundle":
        from .bundle import ModelBundle

        return ModelBundle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
