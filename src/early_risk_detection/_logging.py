from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Timestamped console logging for CLIs and training scripts (libraries never call this)."""
    logging.basicConfig(level=level, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S", force=True)
