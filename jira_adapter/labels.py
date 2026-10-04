"""Gắn nhãn bottleneck theo §6.1 (bundle C: composite quantile, v1 = trục B1).

Định nghĩa (v1, issue-level):
    B1_score(i, t) = w1 * links_total(i)/max_links(P)
                   + w2 * dwell(i, t)/p90_dwell(P)
                   + w3 * priority_norm(i)
                   + w4 * links_out(i)/max_links_out(P)
    LABEL(i, t)    = 1  nếu B1_score(i, t) nằm top-q% của dự án P (q=5% mặc định)

Lưu ý point-in-time:
- status/dwell tại t lấy từ changelog (chính xác theo thời gian).
- issueLinks KHÔNG có timestamp trong Jira API v2 -> dùng tập link hiện tại của
  document (xấp xỉ; đánh giá sensitivity ở P2).
- Ngưỡng tương đối theo dự án -> miễn dịch khác biệt văn hóa quản lý.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .events import _to_epoch
from .normalize import normalize_priority

RESOLVED_PREFIXES = ("close", "done", "resolved", "complete", "cancel", "won't", "wontfix", "rejected")

#: Trọng số mặc định (tune bằng label-audit rubric)
DEFAULT_W = (0.35, 0.35, 0.15, 0.15)
DEFAULT_Q = 0.05


def _is_resolved(status: str | None) -> bool:
    s = (status or "").strip().lower()
    return any(s.startswith(p) for p in RESOLVED_PREFIXES)


@dataclass
class IssueState:
    key: str
    project: str
    priority: float
    created_ts: float
    last_event_ts: float
    last_status: str | None
    resolved: bool
    links_in_block: int      # issue khác block/depend i (i đang chờ)
    links_out_block: int     # i block/depend issue khác (issue khác chờ i)
    links_total: int         # tổng link Block/Depend 2 chiều


def build_states(docs: list[dict]) -> list[IssueState]:
    """Trạng thái "hiện tại" (cuối document) của mỗi issue — dùng cho context
    dự án (p90 dwell, max links) và làm xấp xỉ point-in-time."""
    states: list[IssueState] = []
    for doc in docs:
        from .normalize import normalize_doc
        doc = normalize_doc(doc)
        f = doc.get("fields") or {}
        key = doc.get("key")
        if not key:
            continue
        created = max(_to_epoch(f.get("created")) or 0.0, 0.0)  # clamp epoch âm (IDE placeholder)
        last_event = created
        for ch in doc.get("changelog") or []:
            ts = _to_epoch(ch.get("created"))
            if ts:
                last_event = max(last_event, ts)
        # dwell tại "now" (cuối dữ liệu)
        # Jira API v2: fields.status = {"name": "Resolved", ...} (dict), không phải string
        st_raw = f.get("status")
        status = st_raw.get("name") if isinstance(st_raw, dict) else (st_raw or "")
        links_in = links_out = 0
        for lk in doc.get("issueLinks") or []:
            raw = (lk.get("type") or {}).get("name") or ""
            if raw.strip().lower() in {"block", "blocked", "blocks", "blocker",
                                       "depend", "depends", "dependency", "dependent",
                                       "gantt dependency"}:
                out_key = (lk.get("outwardIssue") or {}).get("key")
                if out_key == key:
                    links_out += 1
                else:
                    links_in += 1
        states.append(IssueState(
            key=key,
            project=(f.get("project") or {}).get("key") or "(unknown)",
            priority=normalize_priority(f.get("priority")),
            created_ts=created,
            last_event_ts=last_event,
            last_status=status,
            resolved=_is_resolved(status),
            links_in_block=links_in,
            links_out_block=links_out,
            links_total=links_in + links_out,
        ))
    return states


@dataclass
class ProjectContext:
    p90_dwell_days: float
    max_links: int
    max_links_out: int


def build_project_context(states: list[IssueState], now_ts: float) -> dict[str, ProjectContext]:
    by_p: dict[str, list[IssueState]] = defaultdict(list)
    for s in states:
        by_p[s.project].append(s)
    ctx: dict[str, ProjectContext] = {}
    for p, lst in by_p.items():
        dwells = sorted(max((now_ts - s.last_event_ts) / 86400.0, 0.0) for s in lst)
        if dwells:
            idx = min(len(dwells) - 1, int(math.ceil(0.9 * len(dwells))) - 1)
            p90 = dwells[max(idx, 0)]
        else:
            p90 = 30.0
        ctx[p] = ProjectContext(
            p90_dwell_days=max(p90, 1.0),
            max_links=max((s.links_total for s in lst), default=1),
            max_links_out=max((s.links_out_block for s in lst), default=1),
        )
    return ctx


def b1_score(s: IssueState, ctx: ProjectContext, t: float, w=None, use_dwell: bool = False) -> float:
    """B1_score tại thời điểm t.

    v2 (mặc định, use_dwell=False) — **không phụ thuộc thời gian** (tín hiệu
    static của issue: links, priority, links_out). Lý do:
    - v1 (use_dwell=True) có dwell(t) = (t - created) tăng dần theo t -> LABEL
      tương quan mạnh với thời điểm -> với split train/val/test theo thời gian,
      positive rate lệch cực đoan (JFrog: train 1.1% / val 36% / test 55%)
      -> model AUC < 0.5 (xác định trong P0, job T1 đầu tiên).
    - v2: LABEL(i,t) = LABEL(i, t') với mọi t, t' -> sạch cho evaluation temporal.

    v1 (use_dwell=True) giữ lại làm ablation (tín hiệu "issue đã già bao lâu").
    """
    if w is None:
        w = DEFAULT_W
    if use_dwell:
        dwell_days = max((t - s.created_ts) / 86400.0, 0.0)
        dwell_term = min(dwell_days / ctx.p90_dwell_days, 3.0) / 3.0
    else:
        dwell_term = 0.5  # hằng số trung lập — không ảnh hưởng thứ tự hạng (ranking)
    score = (w[0] * (s.links_total / max(ctx.max_links, 1))
             + w[1] * dwell_term
             + w[2] * s.priority
             + w[3] * (s.links_out_block / max(ctx.max_links_out, 1)))
    return float(score)


def label_topq(score: float, project_scores: list[float], q: float = DEFAULT_Q) -> int:
    """1 nếu score >= phân vị (1-q) của dự án."""
    if not project_scores:
        return 0
    thr = sorted(project_scores)[max(0, int(math.ceil((1 - q) * len(project_scores))) - 1)]
    return int(score >= thr)


def assign_labels(
    docs: list[dict],
    events_per_issue: dict[str, list],   # issue key -> [Event]
    w=DEFAULT_W,
    q: float = DEFAULT_Q,
    mode: str = "dependency",
    use_dwell: bool = False,
) -> tuple[list[dict], dict]:
    """Gán LABEL cho mỗi event (dòng CSV) + metadata để debug.

    mode:
    - "dependency" (mặc định, v3): LABEL(i,t) = 1 iff issue có ≥1 link
      Block/Depend (quan hệ chặn/chờ — tín hiệu bottleneck mạnh; mặt bằng
      dữ liệu: 96-97% issue KHÔNG có link, priority gần như hằng số trên
      JFrog -> composite quantile bị pha loãng, xem Phụ lục D báo cáo).
    - "composite" (ablation): top-q% dự án theo B1_score (ranking +
      tie-break); use_dwell=True = biến thể v1 (dwell — bị leakage khi
      evaluate theo split thời gian).

    Trả về (rows, stats): rows = [{event_idx, key, ts, label, score, project}].
    """
    if w is None:
        w = DEFAULT_W
    states = build_states(docs)
    state_by_key = {s.key: s for s in states}
    now_ts = max((s.last_event_ts for s in states), default=0.0)
    if now_ts == 0.0:
        now_ts = 1.0
    ctx = build_project_context(states, now_ts)

    # --- label theo issue ---------------------------------------------------
    label_by_key: dict[str, int] = {}
    if mode == "dependency":
        for s in states:
            label_by_key[s.key] = int((s.links_in_block + s.links_out_block) >= 1)
    elif mode == "composite":
        # ranking theo dự án; tie-break (-score, key) deterministik để tránh
        # "khối điểm đồng nhất" (tied mass) làm quantile naive đánh ~50% issue
        by_project: dict[str, list[IssueState]] = defaultdict(list)
        for s in states:
            by_project[s.project].append(s)
        for p, lst in by_project.items():
            c = ctx.get(p, ProjectContext(30.0, 1, 1))
            ranked = sorted(lst, key=lambda s: (-b1_score(s, c, now_ts, w, use_dwell), s.key))
            k = max(1, int(math.ceil(q * len(ranked))))
            for i, s in enumerate(ranked):
                label_by_key[s.key] = int(i < k)
    else:
        raise ValueError(f"mode chưa biết: {mode!r}")

    rows: list[dict] = []
    n_pos = 0
    for key, evs in events_per_issue.items():
        s = state_by_key.get(key)
        if s is None:
            continue
        c = ctx.get(s.project, ProjectContext(30.0, 1, 1))
        lab = label_by_key.get(key, 0)
        for e in evs:
            if e.kind not in ("status", "assignee", "priority"):
                continue  # label gắn trên sự kiện thay đổi trạng thái của issue
            n_pos += lab
            rows.append({"key": key, "ts": e.ts, "label": lab,
                         "score": round(b1_score(s, c, e.ts, w, use_dwell), 4),
                         "project": s.project, "event_kind": e.kind})
    proj_counts: dict[str, int] = defaultdict(int)
    for s in states:
        proj_counts[s.project] += 1
    stats = {
        "mode": mode, "use_dwell": use_dwell,
        "n_issues": len(states),
        "n_positive_issues": sum(label_by_key.values()),
        "n_labeled_events": len(rows),
        "n_positive": n_pos,
        "pos_rate": round(n_pos / max(len(rows), 1), 4),
        "q": q, "w": list(w),
        "projects": dict(proj_counts),
    }
    return rows, stats
