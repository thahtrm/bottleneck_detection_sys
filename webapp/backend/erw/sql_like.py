from __future__ import annotations


def like_contains(needle: str) -> str:
    """Substring LIKE pattern with ``%``, ``_``, and ``\\`` treated as literals."""
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
