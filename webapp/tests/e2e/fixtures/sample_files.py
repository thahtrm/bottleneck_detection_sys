from __future__ import annotations

import base64

# Valid 1x1 transparent PNG
_MINIMAL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def make_text_attachment(
    filename: str = "notes.txt",
    content: bytes = b"Early Risk Web attachment test payload.\n",
) -> tuple[str, bytes, str]:
    """Return (filename, bytes, content_type) tuple suitable for httpx/TestClient files={'file': ...}."""
    return (filename, content, "text/plain")


def make_png_attachment(filename: str = "screenshot.png") -> tuple[str, bytes, str]:
    """Return a valid minimal 1x1 PNG attachment tuple."""
    return (filename, _MINIMAL_PNG_BYTES, "image/png")


def make_empty_attachment(filename: str = "empty.txt") -> tuple[str, bytes, str]:
    """Return a 0-byte attachment tuple for boundary validation tests."""
    return (filename, b"", "text/plain")


def make_oversized_attachment(
    size_bytes: int = 11 * 1024 * 1024,
    filename: str = "oversized.bin",
) -> tuple[str, bytes, str]:
    """Return an oversized binary payload tuple for upload limit tests."""
    return (filename, b"0" * size_bytes, "application/octet-stream")


def make_path_traversal_attachment(
    filename: str = "../../etc/passwd",
) -> tuple[str, bytes, str]:
    """Return a path-traversal filename attachment tuple for sanitization tests."""
    return (filename, b"traversal-probe\n", "text/plain")
