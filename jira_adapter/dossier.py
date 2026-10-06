"""Hồ sơ issue (dossier) cho gắn nhãn bottleneck bằng LLM — §4.1 của
`docs/phuong-an-gan-nhan-bottleneck-bang-llm.md`.

Mọi số liệu thời gian và tín hiệu F/I tính bằng code ở đây; LLM chỉ đọc hồ sơ
và trích bằng chứng. Hồ sơ là *hồi cứu* (toàn bộ lịch sử issue): được dùng để
tạo NHÃN, không được dùng làm feature cho mô hình.

    ctx = build_project_context(docs)       # percentile dwell, status category...
    d   = build_dossier(doc, ctx)           # dict JSON-safe
    txt = render_text(d)                    # văn bản cho LLM / người chấm
"""
from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .events import _safe_ts, _to_epoch
from .normalize import (ISSUE_THEMES, normalize_doc, normalize_issue_theme,
                        normalize_link_type, normalize_priority)

DAY = 86400.0

#: Tín hiệu chờ đợi trong comment (F2) — chỉ dùng để lọc ứng viên, LLM xác nhận
WAIT_RE = re.compile(
    r"\b(waiting (for|on)|blocked (by|on)|pending (review|approval|merge|qa|feedback)"
    r"|need(s|ed)? (input|feedback|info|information|review|approval)"
    r"|on hold|any (update|news|progress)|still (waiting|pending|no)"
    r"|depends on|awaiting)\b", re.I)

#: Tên trạng thái chưa xuất hiện ở trạng thái hiện tại của issue nào -> đoán category
_DONE_HINT = ("done", "closed", "resolved", "complete", "cancel", "won't", "will not",
              "wontfix", "reject", "deferred", "duplicate")
_NEW_HINT = ("open", "backlog", "to do", "todo", "new", "ready for dev", "triage")

#: Số issue chuyển sang done cùng (người, phút) để coi là đóng hàng loạt (E8)
BULK_CLOSE_MIN = 20

#: Cắt văn bản
DESC_MAX = 1500
COMMENT_MAX = 500
COMMENTS_HEAD, COMMENTS_TAIL = 10, 30


def _anon(raw: str | None) -> str | None:
    """'<<|author_name|9439a3a4-...|>>' -> 'dev-9439a3a4' (ổn định, ngắn)."""
    if not raw:
        return None
    m = re.search(r"\|([0-9a-f]{8})[0-9a-f-]*\|>>", str(raw))
    return f"dev-{m.group(1)}" if m else str(raw)


def _name(obj) -> str | None:
    if isinstance(obj, dict):
        return obj.get("name") or obj.get("value")
    return obj


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trunc(s: str | None, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# --- Dòng thời gian thô từ changelog ------------------------------------------
def _histories(doc: dict) -> list[tuple[float, str | None, dict]]:
    """[(ts, author, item)] sort theo thời gian."""
    out = []
    for h in doc.get("changelog") or []:
        ts = _safe_ts(_to_epoch(h.get("created")))
        if ts is None:
            continue
        author = _anon(_name(h.get("author") or h.get("user")))
        for it in h.get("items") or []:
            out.append((ts, author, it))
    out.sort(key=lambda r: r[0])
    return out


def _status_segments(doc: dict, created: float, end_ts: float) -> list[dict]:
    """Chia đời issue thành các đoạn trạng thái [start, end)."""
    f = doc.get("fields") or {}
    changes = [(ts, it.get("fromString"), it.get("toString"))
               for ts, _a, it in _histories(doc) if it.get("field") == "status"]
    first = changes[0][1] if changes else _name(f.get("status"))
    segs, cur, start = [], first, created
    for ts, _frm, to in changes:
        segs.append({"status": cur, "start": start, "end": ts})
        cur, start = to, ts
    segs.append({"status": cur, "start": start, "end": None})  # đoạn cuối: còn mở
    for s in segs:
        s["days"] = max(((s["end"] or end_ts) - s["start"]) / DAY, 0.0)
    return segs


# --- Ngữ cảnh dự án -------------------------------------------------------------
@dataclass
class ProjectContext:
    end_ts: float                                   # thời điểm cuối dữ liệu
    status_cat: dict[str, str]                      # tên trạng thái -> new|indeterminate|done
    dwell: dict[tuple[str, int], list[float]]       # (status, theme) -> số ngày (đã sort)
    status_by_key: dict[str, str]                   # key -> trạng thái hiện tại
    cat_by_key: dict[str, str]
    bulk_close: set[tuple[str, int]] = field(default_factory=set)   # (author, phút)
    wip_high: dict[str, int] = field(default_factory=dict)          # assignee -> số issue mở ưu tiên cao

    def category(self, status: str | None) -> str:
        s = (status or "").strip()
        if s in self.status_cat:
            return self.status_cat[s]
        low = s.lower()
        if any(low.startswith(h) for h in _DONE_HINT):
            return "done"
        if any(low.startswith(h) for h in _NEW_HINT):
            return "new"
        return "indeterminate"

    def pct_rank(self, status: str | None, theme: int, days: float) -> float | None:
        dist = self.dwell.get((status or "", theme)) or self.dwell.get((status or "", -1))
        if not dist or len(dist) < 20:
            return None
        return bisect.bisect_left(dist, days) / len(dist)


def build_project_context(docs: list[dict]) -> ProjectContext:
    docs = [normalize_doc(d) for d in docs]
    end_ts = 0.0
    cat_votes: dict[str, Counter] = defaultdict(Counter)
    status_by_key, cat_by_key = {}, {}
    for d in docs:
        f = d.get("fields") or {}
        st = f.get("status") or {}
        name = _name(st)
        cat = ((st.get("statusCategory") or {}).get("key") if isinstance(st, dict) else None)
        if name and cat:
            cat_votes[name][cat] += 1
        if d.get("key"):
            status_by_key[d["key"]] = name
        for ts, _a, _it in _histories(d):
            end_ts = max(end_ts, ts)
        end_ts = max(end_ts, _safe_ts(_to_epoch(f.get("created"))) or 0.0)
    status_cat = {n: c.most_common(1)[0][0] for n, c in cat_votes.items()}
    ctx = ProjectContext(end_ts=end_ts, status_cat=status_cat, dwell={},
                         status_by_key=status_by_key, cat_by_key={})
    ctx.cat_by_key = {k: ctx.category(s) for k, s in status_by_key.items()}

    dwell: dict[tuple[str, int], list[float]] = defaultdict(list)
    closes: Counter = Counter()
    wip: Counter = Counter()
    for d in docs:
        f = d.get("fields") or {}
        created = _safe_ts(_to_epoch(f.get("created")))
        if created is None:
            continue
        theme = normalize_issue_theme(_name(f.get("issuetype")))
        for s in _status_segments(d, created, end_ts):
            if s["end"] is None or ctx.category(s["status"]) == "done":
                continue  # chỉ đoạn đã kết thúc, chưa done -> phân phối dwell
            dwell[(s["status"], theme)].append(s["days"])
            dwell[(s["status"], -1)].append(s["days"])
        for ts, author, it in _histories(d):
            if it.get("field") == "status" and ctx.category(it.get("toString")) == "done":
                closes[(author, int(ts // 60))] += 1
        assignee = _anon(_name(f.get("assignee")))
        if assignee and ctx.cat_by_key.get(d.get("key")) != "done" \
                and normalize_priority(f.get("priority")) >= 0.6:
            wip[assignee] += 1
    ctx.dwell = {k: sorted(v) for k, v in dwell.items()}
    ctx.bulk_close = {k for k, n in closes.items() if n >= BULK_CLOSE_MIN}
    ctx.wip_high = dict(wip)
    return ctx


# --- Hồ sơ -----------------------------------------------------------------------
def build_dossier(doc: dict, ctx: ProjectContext) -> dict:
    doc = normalize_doc(doc)
    f = doc.get("fields") or {}
    key = doc.get("key")
    created = _safe_ts(_to_epoch(f.get("created"))) or 0.0
    resolved_at = _safe_ts(_to_epoch(f.get("resolutiondate")))
    itype = _name(f.get("issuetype"))
    theme = normalize_issue_theme(itype)
    prio_raw = _name(f.get("priority"))
    prio = normalize_priority(f.get("priority"))
    status_now = _name(f.get("status"))
    cat_now = ctx.category(status_now)
    hist = _histories(doc)
    flags: list[str] = []

    if (_to_epoch(f.get("created")) or 0.0) < 0:
        flags.append("placeholder_date")

    # trạng thái
    segs = _status_segments(doc, created, ctx.end_ts)
    timeline = []
    for s in segs:
        cat = ctx.category(s["status"])
        timeline.append({
            "status": s["status"], "category": cat,
            "start": _iso(s["start"]), "end": _iso(s["end"]),
            "days": round(s["days"], 1),
            "pct_rank": (None if cat == "done"
                         else _round(ctx.pct_rank(s["status"], theme, s["days"]))),
            "ongoing": s["end"] is None,
        })

    # assignee, priority, fixVersion, link (có timestamp ở changelog)
    assignees, prio_changes, fixv_changes, link_log = [], [], [], []
    reopen = 0
    status_seq = []
    for ts, author, it in hist:
        fld = it.get("field")
        if fld == "assignee":
            assignees.append({"at": _iso(ts), "to": _anon(it.get("to") or it.get("toString"))})
        elif fld == "priority":
            prio_changes.append({"at": _iso(ts), "from": it.get("fromString"), "to": it.get("toString")})
        elif fld == "Fix Version":
            fixv_changes.append({"at": _iso(ts), "from": it.get("fromString"), "to": it.get("toString")})
        elif fld == "Link":
            link_log.append({"at": _iso(ts), "added": it.get("toString"), "removed": it.get("fromString")})
        elif fld == "status":
            status_seq.append(it.get("toString"))
            if ctx.category(it.get("fromString")) == "done" and ctx.category(it.get("toString")) != "done":
                reopen += 1
            if ctx.category(it.get("toString")) == "done" and (author, int(ts // 60)) in ctx.bulk_close:
                flags.append("bulk_close")

    # ping-pong: A -> B -> A trong chuỗi trạng thái
    pingpong = sum(1 for i in range(2, len(status_seq)) if status_seq[i] == status_seq[i - 2]
                   and status_seq[i] != status_seq[i - 1])
    handoffs = max(len(assignees) - 1, 0)

    # links + trạng thái hiện tại của issue bên kia
    links = []
    for lk in doc.get("issueLinks") or []:
        t = lk.get("type") or {}
        if lk.get("outwardIssue"):
            other, phrase, direction = lk["outwardIssue"], t.get("outward"), "outward"
        else:
            other, phrase, direction = lk.get("inwardIssue") or {}, t.get("inward"), "inward"
        okey = other.get("key")
        ostatus = ctx.status_by_key.get(okey) or _name((other.get("fields") or {}).get("status"))
        links.append({"type_raw": t.get("name"), "type_std": normalize_link_type(t.get("name")),
                      "relation": f"this issue {phrase} {okey}", "direction": direction,
                      "other_key": okey, "other_status_now": ostatus,
                      "other_open_now": ctx.category(ostatus) != "done"})

    # comment
    comments_all = []
    for c in doc.get("comments") or []:
        ts = _safe_ts(_to_epoch(c.get("created")))
        comments_all.append((ts or 0.0, _anon(_name(c.get("author"))), c.get("body") or ""))
    comments_all.sort(key=lambda r: r[0])
    wait_hits = [i for i, (_t, _a, b) in enumerate(comments_all) if WAIT_RE.search(b)]
    if len(comments_all) > COMMENTS_HEAD + COMMENTS_TAIL:
        keep = list(range(COMMENTS_HEAD)) + list(range(len(comments_all) - COMMENTS_TAIL, len(comments_all)))
    else:
        keep = list(range(len(comments_all)))
    comments = [{"i": i, "at": _iso(comments_all[i][0]), "author": comments_all[i][1],
                 "body": _trunc(comments_all[i][2], COMMENT_MAX)} for i in keep]

    # hoạt động cuối
    last_ts = max([created] + [ts for ts, _a, _it in hist] + [c[0] for c in comments_all])
    assignee_now = _anon(_name(f.get("assignee")))
    if (itype or "").lower() in {"epic", "umbrella"} or any(
            l["type_std"] in {"Epic", "Parent-Child"} and l["direction"] == "outward" for l in links):
        flags.append("epic_or_umbrella")

    # tín hiệu F/I (§2.1) — tính sẵn, LLM không tự tính
    active = [s for s in timeline if s["category"] == "indeterminate" and s["pct_rank"] is not None]
    waiting_new = [s for s in timeline if s["category"] == "new" and s["pct_rank"] is not None]
    signals = {
        "F1_max_active_dwell_pct": max((s["pct_rank"] for s in active), default=None),
        "F1_max_new_dwell_pct": max((s["pct_rank"] for s in waiting_new), default=None),
        "F2_wait_comment_idx": wait_hits,
        "F3_reopen": reopen, "F3_status_pingpong": pingpong, "F3_assignee_handoffs": handoffs,
        "F4_high_prio_unassigned": prio >= 0.6 and assignee_now is None and cat_now != "done",
        "F4_assignee_open_high_prio": ctx.wip_high.get(assignee_now, 0) if assignee_now else 0,
        "I1_open_dependents": sum(1 for l in links if l["type_std"] in {"Block", "Depend"}
                                  and l["direction"] == "outward" and l["other_open_now"]),
        "I1_block_depend_links": sum(1 for l in links if l["type_std"] in {"Block", "Depend"}),
        "I2_fixversion_changes": len(fixv_changes),
        "I3_priority_raised": sum(1 for p in prio_changes
                                  if normalize_priority(p["to"]) > normalize_priority(p["from"])),
        "I3_watchers": (f.get("watches") or {}).get("watchCount", 0),
        "I3_votes": (f.get("votes") or {}).get("votes", 0),
    }

    return {
        "key": key,
        "project": (f.get("project") or {}).get("key"),
        "issue_type": itype, "theme": ISSUE_THEMES[theme],
        "priority": prio_raw, "priority_norm": prio,
        "status_now": status_now, "status_category_now": cat_now,
        "resolution": _name(f.get("resolution")),
        "created": _iso(created), "resolved": _iso(resolved_at),
        "age_days": round(((resolved_at or ctx.end_ts) - created) / DAY, 1),
        "last_activity": _iso(last_ts),
        "inactive_days_at_data_end": round((ctx.end_ts - last_ts) / DAY, 1),
        "data_end": _iso(ctx.end_ts),
        "assignee_now": assignee_now,
        "fix_versions": [_name(v) for v in f.get("fixVersions") or []],
        "components": [_name(v) for v in f.get("components") or []],
        "summary": _trunc(f.get("summary"), 300),
        "description": _trunc(f.get("description"), DESC_MAX),
        "status_timeline": timeline,
        "assignee_changes": assignees,
        "priority_changes": prio_changes,
        "fixversion_changes": fixv_changes,
        "link_changes": link_log,
        "links": links,
        "n_comments": len(comments_all),
        "comments": comments,
        "signals": signals,
        "flags": sorted(set(flags)),
    }


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


# --- Văn bản cho LLM / người chấm --------------------------------------------------
def render_text(d: dict) -> str:
    L = [f"# {d['key']} — {d['summary']}",
         f"Type: {d['issue_type']} ({d['theme']}) | Priority: {d['priority']} | "
         f"Status now: {d['status_now']} [{d['status_category_now']}] | Resolution: {d['resolution']}",
         f"Created: {d['created']} | Resolved: {d['resolved']} | Age: {d['age_days']} d | "
         f"Last activity: {d['last_activity']} | Data ends: {d['data_end']}",
         f"Assignee now: {d['assignee_now']} | Fix versions: {', '.join(filter(None, d['fix_versions'])) or '-'}"
         f" | Components: {', '.join(filter(None, d['components'])) or '-'}",
         f"Flags: {', '.join(d['flags']) or '-'}", "",
         "## Description", d["description"] or "-", "",
         "## Status timeline (pct = dwell percentile vs. same status & theme in project)"]
    for s in d["status_timeline"]:
        pct = "-" if s["pct_rank"] is None else f"p{int(s['pct_rank'] * 100)}"
        L.append(f"- {s['start']} → {s['end'] or 'now'}: {s['status']} [{s['category']}] "
                 f"{s['days']} d ({pct})")
    for title, rows, fmt in [
        ("Assignee changes", d["assignee_changes"], lambda r: f"- {r['at']}: → {r['to']}"),
        ("Priority changes", d["priority_changes"], lambda r: f"- {r['at']}: {r['from']} → {r['to']}"),
        ("Fix version changes", d["fixversion_changes"], lambda r: f"- {r['at']}: {r['from']} → {r['to']}"),
        ("Link changes", d["link_changes"], lambda r: f"- {r['at']}: +{r['added']} / -{r['removed']}"),
        ("Links (current)", d["links"],
         lambda r: f"- [{r['type_std']}] {r['relation']} (status now: {r['other_status_now']})"),
    ]:
        if rows:
            L += ["", f"## {title}"] + [fmt(r) for r in rows]
    L += ["", f"## Comments ({d['n_comments']} total, showing {len(d['comments'])})"]
    for c in d["comments"]:
        L.append(f"- [c{c['i']}] {c['at']} {c['author']}: {c['body']}")
    L += ["", "## Computed signals"] + [f"- {k}: {v}" for k, v in d["signals"].items()]
    return "\n".join(L)
