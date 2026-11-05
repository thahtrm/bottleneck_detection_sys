from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

from erw.settings import Settings


def _adf_text(node) -> str:
    """Concatenate the `text` nodes of an Atlassian Document Format tree (blocks separated by newline)."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    inner = _adf_text(node.get("content") or [])
    return inner + "\n" if node.get("type") in ("paragraph", "heading", "codeBlock", "listItem") else inner


def to_dump_shape(raw: dict) -> dict:
    """Jira Cloud v3 issue JSON -> shape accepted by early_risk_detection `normalize_doc`."""
    doc = copy.deepcopy(raw)
    fields = doc.setdefault("fields", {})
    comment = fields.get("comment")
    if isinstance(comment, dict) and "comments" in comment and "comments" not in fields:
        fields["comments"] = comment["comments"]
    desc = fields.get("description")
    if isinstance(desc, (dict, list)):
        fields["description"] = _adf_text(desc).strip()
    return doc


def _check_not_base(settings: Settings) -> None:
    base, work = Path(settings.base_duckdb), Path(settings.work_duckdb)
    same = base.resolve() == work.resolve()
    if not same and base.exists() and work.exists():
        same = os.path.samefile(base, work)
    if same:
        raise ValueError(f"work_duckdb must differ from the read-only base_duckdb: {work}")


def ensure_work_db(settings: Settings) -> Path:
    """Copy the (read-only) base DuckDB to the working path once. Never writes to the base."""
    _check_not_base(settings)
    work = Path(settings.work_duckdb)
    if not work.exists():
        work.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(settings.base_duckdb, work)
    return work


def sync_erw_instance(settings: Settings, raws: list[dict]) -> int:
    """Replace the ERW instance in the working DuckDB with `raws`; returns the issue count."""
    _check_not_base(settings)
    from early_risk_detection.data.etl.loader import DuckDBLoader
    from early_risk_detection.data.etl.transformer import JiraTransformer

    batch = JiraTransformer().transform_batch([to_dump_shape(r) for r in raws], settings.erw_instance)
    loader = DuckDBLoader(str(settings.work_duckdb))
    try:
        loader.init_schema()
        loader.clear_instance(settings.erw_instance)
        loader.load_batch(batch)
    finally:
        loader.close()
    return len(batch["issues"])
