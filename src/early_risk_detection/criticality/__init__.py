"""Critical-task detection: TGN memory over the Jira event stream + ranking-aware readout."""
from .scorer import CriticalityScorer

__all__ = ["CriticalityScorer"]
