"""Issue document (Jira API v2, expand=changelog) -> dòng sự kiện.

Mỗi sự kiện: (u, v, ts, kind, payload) với u/v là issue key (hoặc assignee username
cho sự kiện assignee), ts = epoch giây.

Loại sự kiện:
- status   : thay đổi trạng thái        (u=issue, v=issue)
- assignee : thay đổi người phụ trách  (u=issue, v=username)
- priority : thay đổi ưu tiên          (u=issue, v=issue)
- link     : issue link tồn tại        (u=issue, v=issue_linked)
- comment  : comment                   (u=issue, v=author)

⚠️ Giới hạn dữ liệu đã biết: API v2 KHÔNG trả timestamp cho issueLinks ->
thời điểm sự kiện link được xấp xỉ = max(created của 2 issue) — ghi nhận trong
báo cáo EDA và đánh giá sensitivity ở P2 (rủi ro: link có thể được tạo sớm hơn
thời điểm xấp xỉ; an toàn cho đánh giá "không nhìn tương lai" vì cả 2 issue
đều tồn tại trước thời điểm đó).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .normalize import link_type_index, normalize_doc, normalize_link_type, normalize_priority

# Các changelog field được coi là "nhiễu" (edit mô tả, sửa title...) — bỏ qua
_IGNORED_FIELDS = {"description", "summary", "comment", "attachment", "worklog"}

#: epoch giây của 1970-01-01 (Jira trả ISO 8601 UTC)
_EPOCH = time.mktime(time.gmtime(0))


@dataclass
class Event:
    u: str                      # issue key nguồn
    v: str                      # issue key đích / username
    ts: float                   # epoch giây
    kind: str                   # status | assignee | priority | link | comment
    detail: dict = field(default_factory=dict)   # from/to, link_type_idx, ...


def _to_epoch(iso: str | None) -> float | None:
    """'2021-05-04T10:20:30.000+0000' -> epoch giây. None nếu rỗng."""
    if not iso:
        return None
    s = str(iso).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        # ISO 8601 với offset; fromisoformat xử lý được "+00:00"
        import datetime as _dt
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.timestamp()
    except ValueError:
        # fallback: định dạng Jira cũ "2021-05-04T10:20:30.000+0000"
        try:
            s2 = s.replace("+0000", "+00:00")
            import datetime as _dt
            return _dt.datetime.fromisoformat(s2).timestamp()
        except ValueError:
            return None


def _issue_created_ts(doc: dict) -> float | None:
    return _safe_ts(_to_epoch((doc.get("fields") or {}).get("created")))


def _safe_ts(ts: float | None) -> float | None:
    """Clamp timestamp âm -> 0.

    Dữ liệu Spring có placeholder date '1969-12-31T16:00:00.000+0000'
    (epoch = -28800s, từ Jira IDE cũ) -> epoch âm vi phạm invariant
    `last_update(0) <= ts` của TGN memory (crash 'Trying to update memory
    to time in the past' ở batch 0 epoch 0). Clamp về 0: giữ thứ tự thời
    gian, không tạo giá trị âm.
    """
    if ts is None:
        return None
    return max(ts, 0.0)


def extract_events(doc: dict, include_comments: bool = True) -> list[Event]:
    """Biến 1 issue document thành danh sách event (chưa sort).

    `doc`: dict theo Jira API v2 search result issue object, gồm
    {key, fields{...}, changelog[...], comments[...], issueLinks[...]}
    (chấp nhận cả shape dataset dump — normalize_doc xử lý)
    """
    doc = normalize_doc(doc)
    key = doc.get("key")
    if not key:
        return []
    events: list[Event] = []
    created_ts = _issue_created_ts(doc) or 0.0

    # --- changelog: status / assignee / priority -------------------------
    for change in doc.get("changelog") or []:
        ts = _safe_ts(_to_epoch(change.get("created")))
        if ts is None:
            continue
        user = (change.get("user") or {}).get("name")
        for item in change.get("items") or []:
            fld = (item.get("field") or "").strip()
            if fld in _IGNORED_FIELDS or fld == "updated":
                continue
            # Jira API v2 changelog item: {"field": "status", "from": "Open", "set": "In Progress"}
            # -> giá trị mới nằm ở "set" (adapter cũ đọc "to" -> None với dữ liệu thật).
            _to_val = item.get("to") if item.get("to") is not None else item.get("set")
            if fld == "status":
                events.append(Event(key, key, ts, "status",
                                    {"from": item.get("from"), "to": _to_val}))
            elif fld == "assignee":
                to = (str(_to_val).strip() if _to_val is not None else "")
                v = to if to else "(unassigned)"
                events.append(Event(key, v, ts, "assignee",
                                    {"from": item.get("from"), "to": to}))
            elif fld == "priority":
                events.append(Event(key, key, ts, "priority",
                                    {"from": item.get("from"), "to": item.get("to")}))
            # resolution, components, labels, fixVersions: không tạo sự kiện riêng
            # (tín hiệu đã nằm trong status_change -> resolved)
        _ = user  # (dùng cho event comment nếu cần gán tác giả)

    # --- issueLinks -------------------------------------------------------
    # Jira: outwardIssue/inwardIssue — 1 trong 2 là CHÍNH issue này (key),
    # bên kia là issue liên kết. Ví dụ issue A "Blocks" B:
    #   doc A: {outwardIssue: A, inwardIssue: B, type: Blocks}
    #   doc B: {outwardIssue: A, inwardIssue: B, type: Blocks}  (cùng payload,
    #           nhưng từ góc nhìn B thì B là inward)
    for link in doc.get("issueLinks") or []:
        out_key = (link.get("outwardIssue") or {}).get("key")
        in_key = (link.get("inwardIssue") or {}).get("key")
        other_key = in_key if out_key == key else out_key
        if not other_key or other_key == key:
            continue
        # xấp xỉ thời điểm: cả 2 issue phải đã tồn tại -> dùng created của issue này
        ts = created_ts if created_ts else None
        if ts is None:
            continue
        raw_type = (link.get("type") or {}).get("name")
        idx = link_type_index(raw_type)
        # direction: 1 = issue này là outward (nguồn quan hệ, vd "A blocks B"),
        #            0 = issue này là inward (vd "B blocked by A")
        direction = 1 if out_key == key else 0
        events.append(Event(key, other_key, ts, "link",
                            {"link_type": normalize_link_type(raw_type),
                             "link_type_idx": idx, "direction": direction}))

    # --- comments ---------------------------------------------------------
    if include_comments:
        for c in doc.get("comments") or []:
            ts = _safe_ts(_to_epoch(c.get("created")))
            if ts is None:
                continue
            author = (c.get("author") or c.get("updateAuthor") or {}).get("name") or "(unknown)"
            events.append(Event(key, author, ts, "comment", {}))

    events.sort(key=lambda e: (e.ts, e.kind))
    return events


def priority_of(doc: dict) -> float:
    """Priority chuẩn hóa của issue (cho node/edge feature)."""
    return normalize_priority((doc.get("fields") or {}).get("priority"))
