"""Bộ chuyển đổi (Transformer) dữ liệu thô Jira thành các cấu trúc quan hệ DuckDB."""
from __future__ import annotations

from typing import Any

from ..events import _issue_created_ts, _safe_ts, _to_epoch
from ..normalize import (
    ISSUE_THEMES,
    normalize_doc,
    normalize_issue_theme,
    normalize_link_type,
    normalize_priority,
)


def _safe_str(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get("name") or val.get("value") or str(val)
    return str(val).strip()


class JiraTransformer:
    def __init__(self, preview_len: int = 200) -> None:
        self.preview_len = preview_len

    def transform_doc(self, raw_doc: dict, instance: str) -> dict[str, list[tuple]]:
        """Chuyển đổi 1 issue document thô thành 4 tập tuple quan hệ.

        Returns:
            dict with keys: 'issues', 'changelogs', 'links', 'comments'
        """
        doc = normalize_doc(raw_doc)
        key = doc.get("key")
        if not key:
            return {"issues": [], "changelogs": [], "links": [], "comments": []}

        fields = doc.get("fields") or {}
        project = key.split("-")[0] if "-" in key else key

        # --- Created / Updated / Resolved ts ---
        created_ts = _issue_created_ts(doc) or 0.0
        updated_ts = _safe_ts(_to_epoch(fields.get("updated"))) or created_ts
        resolved_ts = _safe_ts(_to_epoch(fields.get("resolutiondate")))

        # --- Issue core fields ---
        summary = fields.get("summary")
        it_obj = fields.get("issuetype")
        it_name = _safe_str(it_obj)
        it_theme_idx = normalize_issue_theme(it_name)
        it_theme = ISSUE_THEMES[it_theme_idx]

        p_obj = fields.get("priority")
        p_raw = _safe_str(p_obj)
        p_norm = normalize_priority(p_obj)

        status_name = _safe_str(fields.get("status"))
        resolution_name = _safe_str(fields.get("resolution"))

        assignee_obj = fields.get("assignee")
        assignee_name = _safe_str(assignee_obj) or "(unassigned)"

        reporter_obj = fields.get("reporter")
        reporter_name = _safe_str(reporter_obj) or "(unassigned)"

        raw_changelogs = doc.get("changelog") or []
        raw_links = doc.get("issueLinks") or []
        raw_comments = doc.get("comments") or []

        # --- Links & has_block_or_depend ---
        link_tuples: list[tuple] = []
        has_block_or_depend = False

        for link in raw_links:
            out_key = (link.get("outwardIssue") or {}).get("key")
            in_key = (link.get("inwardIssue") or {}).get("key")
            other_key = in_key if out_key == key else out_key
            if not other_key or other_key == key:
                continue

            raw_type = (link.get("type") or {}).get("name")
            std_type = normalize_link_type(raw_type)
            direction = 1 if out_key == key else 0
            is_bod = std_type in ("Block", "Depend")
            if is_bod:
                has_block_or_depend = True

            link_tuples.append((
                instance,
                key,
                other_key,
                raw_type,
                std_type,
                direction,
                is_bod,
                created_ts,
            ))

        # --- Changelogs ---
        changelog_tuples: list[tuple] = []
        for change in raw_changelogs:
            chg_ts = _safe_ts(_to_epoch(change.get("created")))
            if chg_ts is None:
                continue
            chg_id = str(change.get("id")) if change.get("id") is not None else None
            author = _safe_str(change.get("user") or change.get("author")) or "(unknown)"

            for item in change.get("items") or []:
                fld = (item.get("field") or "").strip()
                if not fld:
                    continue
                to_val = item.get("to") if item.get("to") is not None else item.get("set")
                changelog_tuples.append((
                    instance,
                    key,
                    chg_id,
                    author,
                    chg_ts,
                    fld,
                    _safe_str(item.get("from")),
                    _safe_str(to_val),
                ))

        # --- Comments ---
        comment_tuples: list[tuple] = []
        for c in raw_comments:
            c_ts = _safe_ts(_to_epoch(c.get("created")))
            if c_ts is None:
                continue
            c_id = str(c.get("id")) if c.get("id") is not None else None
            author = _safe_str(c.get("author") or c.get("updateAuthor")) or "(unknown)"
            body = str(c.get("body") or "")
            body_len = len(body)
            preview = body[:self.preview_len] if self.preview_len > 0 else None

            comment_tuples.append((
                instance,
                key,
                c_id,
                author,
                c_ts,
                body_len,
                preview,
            ))

        # --- Issue Tuple ---
        issue_tuple = (
            instance,
            key,
            project,
            summary,
            it_name,
            it_theme,
            p_raw,
            p_norm,
            status_name,
            resolution_name,
            created_ts,
            updated_ts,
            resolved_ts,
            assignee_name,
            reporter_name,
            len(changelog_tuples),
            len(link_tuples),
            len(comment_tuples),
            has_block_or_depend,
        )

        return {
            "issues": [issue_tuple],
            "changelogs": changelog_tuples,
            "links": link_tuples,
            "comments": comment_tuples,
        }

    def transform_batch(self, docs: list[dict], instance: str) -> dict[str, list[tuple]]:
        """Chuyển đổi 1 lô documents thành các tập hợp tuple."""
        res: dict[str, list[tuple]] = {
            "issues": [],
            "changelogs": [],
            "links": [],
            "comments": [],
        }
        for doc in docs:
            out = self.transform_doc(doc, instance)
            for k in res:
                res[k].extend(out[k])
        return res
