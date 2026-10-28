"""early-risk-detection: early detection of delay-risk and critical tasks in Jira issue trackers.

    from early_risk_detection import CriticalityScorer
    from early_risk_detection.embeddings import EmbeddingIndex

    scorer = CriticalityScorer.load("bundles/criticality")
    ranked = scorer.score("data/jira.duckdb", embeddings=EmbeddingIndex("data"))
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["CriticalityScorer", "DelayRiskScorer", "ModelBundle", "__version__"]


def __getattr__(name: str):
    # Lazy: importing the package must not pull in torch / catboost until a scorer is used.
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
