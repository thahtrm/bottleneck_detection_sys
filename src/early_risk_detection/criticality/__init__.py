"""Critical-task detection: TGN memory over the Jira event stream + ranking-aware readout."""
from .dual_head import DEFAULT_BUNDLE_PATH, DualHeadScorer
from .scorer import CriticalityScorer

__all__ = ["CriticalityScorer", "DualHeadScorer", "DEFAULT_BUNDLE_PATH"]
