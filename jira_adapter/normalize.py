"""Chuẩn hóa giá trị dị dạng giữa 16 instance Jira.

Nguồn sự thật: `0. DataDefinition/jira_issue_linktype_mapping.json` và
`jira_issuetype_thematic_analysis.json` trong artefact MSR 2022 (bản copy
cũng nằm trong data/raw nếu đã tải). File này embed bảng mapping chuẩn để
adapter chạy độc lập.
"""
from __future__ import annotations

# --- Link types -----------------------------------------------------------
# Ánh xạ ~75 tên link tùy biến -> 20+ hạng mục (rút từ jira_issue_linktype_mapping.json).
# Chỉ giữ các hạng mục liên quan trực tiếp đến bottleneck + nhóm phổ biến còn lại.
LINK_TYPE_MAP: dict[str, str] = {
    # phụ thuộc / chặn — tín hiệu bottleneck mạnh nhất
    "Blocked": "Block", "Blocks": "Block", "Blocker": "Block",
    "Depend": "Depend", "Depends": "Depend", "Dependency": "Depend",
    "Dependent": "Depend", "Gantt Dependency": "Depend", "Required": "Depend",
    # cấu trúc
    "Child-Issue": "Parent-Child", "Parent Feature": "Parent-Child",
    "Parent/Child": "Parent-Child", "multi-level hierarchy [GANTT]": "Parent-Child",
    "Parent-Relation": "Parent-Child", "Subtask": "Subtask", "Epic": "Epic",
    "Epic-Relation": "Epic",
    # kết cục / chất lượng
    "Completes": "Fix", "Fixes": "Fix", "Resolve": "Fix",
    "Duplicate": "Duplicate", "Cloners": "Duplicate", "Cloners (old)": "Duplicate",
    # nhân quả / thời gian
    "Causality": "Cause", "Cause": "Cause", "Caused": "Cause",
    "Problem/Incident": "Cause", "Regression": "Cause",
    "Follows": "Follow", "Sequence": "Follow", "Preceded By": "Follow",
    # quan hệ chung
    "Reference": "Relate", "Relate": "Relate", "Related": "Relate",
    "Relates": "Relate", "Relationship": "Relate",
    "Incorporate": "Incorporate", "Incorporates": "Incorporate", "Collection": "Incorporate",
    "Container": "Incorporate", "Contains(WBSGantt)": "Incorporate", "Part": "Incorporate",
    "PartOf": "Incorporate", "Superset": "Incorporate",
    "Split": "Split", "Issue split": "Split", "Work Breakdown": "Split",
    "Derived": "Derive", "Detail": "Derive",
    "Documented": "Documented", "Documentation": "Documented",
    "Implement": "Implement", "Implements": "Implement",
    "Replace": "Replace", "Replacement": "Replace",
    "Supercede": "Supercede", "Supercedes": "Supercede", "Supersede": "Supercede",
    "Supersession": "Supercede",
    "Test": "Test", "Tested": "Test", "Trigger": "Trigger",
    "Backports": "Backport",
    # Gantt (ít gặp, gom về Depend để đơn giản)
    "finish-finish [GANTT]": "Depend", "Gantt End to End": "Depend",
    "Gantt: finish-finish": "Depend", "Gantt End to Start": "Depend",
    "Gantt: finish-start": "Depend", "Gantt Start to Start": "Depend",
    "Gantt: start-finish": "Depend",
}

#: Thứ tự ổn định cho one-hot encoding (8 hạng mục chính + khác)
LINK_TYPES_STD: tuple[str, ...] = (
    "Block", "Depend", "Epic", "Parent-Child", "Subtask", "Fix", "Duplicate", "Relate",
)
LINK_TYPE_OTHER = "Other"


def normalize_link_type(raw: str | None) -> str:
    """Tên link thô -> hạng mục chuẩn. Unknown -> 'Other' (không bỏ sót)."""
    if not raw:
        return LINK_TYPE_OTHER
    key = raw.strip()
    if key in LINK_TYPE_MAP:
        return LINK_TYPE_MAP[key]
    # thử không phân biệt hoa thường
    lower = key.lower()
    for k, v in LINK_TYPE_MAP.items():
        if k.lower() == lower:
            return v
    return LINK_TYPE_OTHER


def link_type_index(raw: str | None) -> int:
    """Index trong LINK_TYPES_STD (0..7), 8 = Other."""
    std = normalize_link_type(raw)
    if std in LINK_TYPES_STD:
        return LINK_TYPES_STD.index(std)
    return len(LINK_TYPES_STD)  # 8 = Other


# --- Chuẩn hóa shape document (dataset dump -> shape adapter) ----------------
def normalize_doc(doc: dict) -> dict:
    """Đưa document thô (The Public Jira Dataset) về shape chuẩn của adapter.

    Các biến thể shape đã quan sát trong dump (API v2/v3 trộn):
    - changelog: dict {startAt,maxResults,total,histories:[...]} (mới)
                 hoặc list[...] (cũ). Mỗi history: created|createdAt, user|author.
    - issueLinks: nằm trong fields.issuelinks (lowercase) thay vì top-level.
    - comments:   nằm trong fields.comments thay vì top-level.

    Idempotent: document đã đúng shape -> trả về nguyên vẹn (không copy).
    """
    if not isinstance(doc, dict):
        return doc

    changed = False

    # --- changelog: dict{histories} -> list ---------------------------------
    cl = doc.get("changelog")
    if isinstance(cl, dict) and "histories" in cl:
        norm_hist = []
        for h in cl.get("histories") or []:
            if not isinstance(h, dict):
                continue
            h2 = dict(h)
            if "created" not in h2 and h2.get("createdAt") is not None:
                h2["created"] = h2["createdAt"]
            if h2.get("user") is None and h2.get("author") is not None:
                h2["user"] = h2["author"]
            norm_hist.append(h2)
        cl = norm_hist
        changed = True

    # --- issueLinks / comments: fields.* (lowercase) -> top-level ------------
    f = doc.get("fields") or {}
    il = doc.get("issueLinks")
    if not il:
        il = f.get("issuelinks") or f.get("issueLinks")
    cm = doc.get("comments")
    if not cm:
        cm = f.get("comments")

    if changed or (il is not doc.get("issueLinks")) or (cm is not doc.get("comments")):
        out = dict(doc)
        if changed:
            out["changelog"] = cl
        if il and not doc.get("issueLinks"):
            out["issueLinks"] = il
        if cm and not doc.get("comments"):
            out["comments"] = cm
        return out
    return doc


# --- Priority -------------------------------------------------------------
#: Jira priority chuẩn hóa -> trọng số 0..1 (Blocker cao nhất)
PRIORITY_NORM: dict[str, float] = {
    "blocker": 1.0, "highest": 1.0, "critical": 0.8, "high": 0.6,
    "major": 0.5, "medium": 0.4, "normal": 0.4,
    "minor": 0.3, "low": 0.3, "trivial": 0.1, "lowest": 0.1,
}


def normalize_priority(raw: "str | dict | None") -> float:
    # Jira API v2: fields.priority = {"self": ..., "name": "High", ...} (dict)
    if isinstance(raw, dict):
        raw = raw.get("name")
    if not raw:
        return 0.4  # default "normal"
    return PRIORITY_NORM.get(str(raw).strip().lower(), 0.4)


# --- Issue type themes (tổng hợp từ jira_issuetype_thematic_analysis.json) ---
ISSUE_THEME_MAP: dict[str, str] = {
    # Requirements
    "epic": "Requirements", "story": "Requirements", "new feature": "Requirements",
    "brainstorming": "Requirements", "improvement": "Requirements",
    "request": "Requirements", "wish": "Requirements", "feature request": "Requirements",
    # Development
    "task": "Development", "technical task": "Development", "umbrella": "Development",
    "sub-task": "Development", "subtask": "Development", "new task": "Development",
    # Maintenance
    "bug": "Maintenance", "outage": "Maintenance", "defect": "Maintenance",
    "test": "Maintenance", "technical debt": "Maintenance", "dependency upgrade": "Maintenance",
    "documentation": "Maintenance",
    # User Support
    "it help": "User Support", "question": "User Support", "support": "User Support",
    "help": "User Support", "incident": "User Support",
    # Other
    "github integration": "Other", "new git repo": "Other", "other": "Other",
}

ISSUE_THEMES: tuple[str, ...] = ("Requirements", "Development", "Maintenance", "User Support", "Other")


def normalize_issue_theme(raw: str | None) -> int:
    if not raw:
        return len(ISSUE_THEMES) - 1
    return ISSUE_THEMES.index(ISSUE_THEME_MAP.get(str(raw).strip().lower(), "Other"))
