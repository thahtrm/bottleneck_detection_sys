"""Xuất dữ liệu instance ra đúng format repo TGN mong đợi.

Cấu trúc output (trùng `utils/preprocess_data.py` của repo, nhưng kèm node
features THỰC thay vì zero/random):

  data/ml_{name}.csv        : u, i, ts, label, idx   (id 1-based, idx 1-based)
  data/ml_{name}.npy        : edge features (n_events+1, 24), dòng 0 = 0
  data/ml_{name}_node.npy   : node features (n_nodes, 8), dòng 0 = 0

Event feature (24 chiều):
  [0..4)   kind one-hot      : status, assignee, priority, link, comment
  [5..14)  link_type one-hot : Block, Depend, Epic, Parent-Child, Subtask,
                               Fix, Duplicate, Relate, Other
  [14]     direction (link)  : 1 = issue này là outward
  [15]     priority_norm(issue)
  [16..21) issue_theme one-hot : Requirements, Development, Maintenance,
                               User Support, Other
  [21,22)  time-of-day sin/cos (UTC)
  [22]     log1p(số ngày từ event trước của cùng issue)
  [23]     (đệm 0, mở rộng sau)

Node features (8 chiều):
  [0] priority_norm · [1..6) theme one-hot · [6] has_block_link · [7] log1p(n_links)/log1p(max)

v1: đồ thị đơn (mọi nút = issue; sự kiện assignee là self-loop u=v=issue).
Biến thể bipartite issue↔developer cho B2 là bước P2.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np

from .events import Event
from .normalize import ISSUE_THEMES, normalize_issue_theme, normalize_priority

KINDS = ("status", "assignee", "priority", "link", "comment")
LINK_TYPES_ONEHOT = ("Block", "Depend", "Epic", "Parent-Child", "Subtask",
                     "Fix", "Duplicate", "Relate", "Other")
EDGE_DIM = 24
NODE_DIM = 8


def _issue_theme_index(doc: dict) -> int:
    it = ((doc.get("fields") or {}).get("issuetype") or {})
    name = it.get("name") if isinstance(it, dict) else it
    return normalize_issue_theme(name)


def edge_feature(e: Event, priority: float, theme_idx: int,
                 prev_ts: dict[str, float]) -> list[float]:
    f = [0.0] * EDGE_DIM
    try:
        f[KINDS.index(e.kind)] = 1.0
    except ValueError:
        pass
    if e.kind == "link":
        idx = e.detail.get("link_type_idx", 8)
        if 0 <= idx < len(LINK_TYPES_ONEHOT):
            f[5 + idx] = 1.0
        f[14] = float(e.detail.get("direction", 0))
    f[15] = priority
    f[16 + theme_idx] = 1.0
    hour = (e.ts / 3600.0) % 24.0
    f[21] = math.sin(2 * math.pi * hour / 24.0)
    f[22] = math.cos(2 * math.pi * hour / 24.0)
    prev = prev_ts.get(e.u)
    if prev is not None and e.ts > prev:
        f[23] = 0.0  # giữ đệm; delta-time riêng đã có trong repo (time encoder)
    prev_ts[e.u] = max(prev or 0.0, e.ts)
    return f


def node_features(priority: float, theme_idx: int, has_block: bool,
                  n_links: int, max_links: int) -> list[float]:
    f = [0.0] * NODE_DIM
    f[0] = priority
    f[1 + theme_idx] = 1.0
    f[6] = 1.0 if has_block else 0.0
    f[7] = math.log1p(max(n_links, 0)) / math.log1p(max(max_links, 1))
    return f


def write_instance(name: str,
                   docs: list[dict],
                   events_per_issue: dict[str, list[Event]],
                   label_rows: dict[str, dict],   # (issue_key, ts) -> row có 'label'
                   out_dir: str = "data",
                   node_out_dim: int | None = 64) -> dict:
    """Viết 3 file `ml_{name}.*`. Trả về stats.

    node_out_dim: chiều node feature cuối cùng. Adapter sinh 8 chiều ngữ nghĩa
    (NODE_DIM); repo TGN yêu cầu memory_dim == node feature dim nên padding
    zero lên node_out_dim (mặc định 64). Đặt None để giữ đúng 8 chiều.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # --- node ids: thứ tự xuất hiện đầu tiên (ổn định, 0-based) -----------
    node_id: dict[str, int] = {}
    order: list[str] = []
    for key, evs in events_per_issue.items():
        if key not in node_id and evs:
            node_id[key] = len(node_id)
            order.append(key)

    # --- context issue -----------------------------------------------------
    from .normalize import normalize_doc
    docs = [normalize_doc(d) for d in docs]
    doc_by_key = {d.get("key"): d for d in docs if d.get("key")}
    max_links = 1
    meta: dict[str, dict] = {}
    for key in order:
        d = doc_by_key.get(key, {})
        f_ = d.get("fields") or {}
        n_links = sum(1 for _ in (d.get("issueLinks") or []))
        has_block = any(
            ((lk.get("type") or {}).get("name") or "").strip().lower()
            in {"block", "blocked", "blocks", "blocker"}
            for lk in (d.get("issueLinks") or [])
        )
        meta[key] = {
            "priority": normalize_priority(f_.get("priority")),
            "theme": _issue_theme_index(d),
            "has_block": has_block,
            "n_links": n_links,
        }
        max_links = max(max_links, n_links)

    # --- edge rows ---------------------------------------------------------
    rows: list[tuple] = []
    n_labeled = 0
    for key, evs in events_per_issue.items():
        if key not in node_id:
            continue
        m = meta[key]
        prev_ts: dict[str, float] = {}
        for e in evs:
            lab_row = label_rows.get((key, round(e.ts, 3)))
            label = float(lab_row["label"]) if lab_row else 0.0
            n_labeled += 1 if lab_row else 0
            v_key = e.v if e.v in node_id else key  # assignee/comment -> self-loop v1
            feat = edge_feature(e, m["priority"], m["theme"], prev_ts)
            rows.append((node_id[key], node_id[v_key], e.ts, label, *feat))

    rows.sort(key=lambda r: (r[2], r[0]))

    # --- viết file (mô phỏng utils/preprocess_data.py, 1-based) ------------
    csv_path = out / f"ml_{name}.csv"
    with csv_path.open("w", newline="") as fcsv:
        w = csv.writer(fcsv)
        w.writerow(["u", "i", "ts", "label", "idx"])
        for idx, (u, i, ts, label, *_rest) in enumerate(rows, start=1):
            w.writerow([u + 1, i + 1, f"{ts:.6f}", label, idx])

    edge_feats = np.zeros((len(rows) + 1, EDGE_DIM), dtype=np.float32)
    for idx, row in enumerate(rows, start=1):
        edge_feats[idx] = np.asarray(row[4:], dtype=np.float32)
    np.save(out / f"ml_{name}.npy", edge_feats)

    n_nodes = max(node_id.values()) + 1 if node_id else 0
    out_dim = NODE_DIM if node_out_dim is None else max(int(node_out_dim), NODE_DIM)
    node_feats = np.zeros((n_nodes + 1, out_dim), dtype=np.float32)
    for key, idx0 in node_id.items():
        m = meta[key]
        row = node_features(m["priority"], m["theme"], m["has_block"], m["n_links"], max_links)
        node_feats[idx0 + 1, :NODE_DIM] = row  # padding zero các chiều còn lại
    np.save(out / f"ml_{name}_node.npy", node_feats)

    stats = {"instance": name, "n_nodes": n_nodes, "n_events": len(rows),
             "n_labeled_events": n_labeled, "edge_dim": EDGE_DIM, "node_dim": NODE_DIM,
             "files": [str(csv_path), str(out / f"ml_{name}.npy"), str(out / f"ml_{name}_node.npy")]}
    return stats
