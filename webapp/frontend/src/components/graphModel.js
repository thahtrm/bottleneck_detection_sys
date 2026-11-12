export const UNASSIGNED = 'person:__unassigned__';

export const RISK = {
  HIGH: { fill: '#fff0f0', border: '#e03131', label: 'Cao', rank: 3 },
  MED: { fill: '#fff6e6', border: '#f08c00', label: 'TB', rank: 2 },
  LOW: { fill: '#ebfbee', border: '#2f9e44', label: 'Thấp', rank: 1 },
  DONE: { fill: '#f1f3f5', border: '#adb5bd', label: 'Đã xong', rank: 0 },
};

const COL_W = 210;
const ROW_H = 84;
const NODE_H = 58;
const LANE_HEAD = 190;
const LANE_PAD = 22;
const FOCUS_COL_W = 230;
const FOCUS_ROW_H = 96;
const PERSON_COL_W = 185;

export const isOpen = (i) => i.status_category !== 'done';
export const riskOf = (i) => (isOpen(i) ? (RISK[i.level] ? i.level : 'LOW') : 'DONE');
const isRisky = (i) => isOpen(i) && (i.level === 'HIGH' || i.is_overdue);
const byRisk = (a, b) =>
  RISK[riskOf(b)].rank - RISK[riskOf(a)].rank || (b.delay_value || 0) - (a.delay_value || 0) || a.key.localeCompare(b.key);

export function buildModel(data) {
  const issues = new Map(data.nodes.map((n) => [n.key, n]));
  const blocks = new Map();
  const blockedBy = new Map();
  for (const k of issues.keys()) {
    blocks.set(k, []);
    blockedBy.set(k, []);
  }
  for (const e of data.edges) {
    if (e.kind !== 'blocks') continue;
    blocks.get(e.from).push(e.to);
    blockedBy.get(e.to).push(e.from);
  }
  return {
    issues,
    blocks,
    blockedBy,
    edges: data.edges,
    people: new Map(data.people.map((p) => [p.id, p])),
    peopleOrder: data.people.map((p) => p.id),
    deadlines: new Map(data.deadlines.map((d) => [d.id, d])),
    criticalPath: data.critical_path,
    threshold: data.overload_threshold,
    summary: data.summary,
  };
}

export const FILTERS = {
  ALL: () => true,
  BOTTLENECK: (i) => i.is_bottleneck,
  OVERDUE: (i) => i.is_overdue,
  BLOCKED: (i) => i.blocked,
  HIGH_RISK: (i) => i.level === 'HIGH' && isOpen(i),
  CRITICAL: (i) => i.is_critical || i.is_critical_path,
  OVERLOADED: (i, m) => m.people.get(i.person_id)?.is_overloaded,
  UNASSIGNED: (i) => i.person_id === UNASSIGNED,
};

export function matchesSearch(model, issue, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const owner = model.people.get(issue.person_id)?.name || '';
  return [issue.key, issue.summary || '', owner].some((s) => s.toLowerCase().includes(q));
}

export function findTarget(model, query) {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  const issue =
    model.issues.get(query.trim().toUpperCase()) ||
    [...model.issues.values()].find((i) => i.key.toLowerCase().includes(q) || (i.summary || '').toLowerCase().includes(q));
  if (issue) return { mode: 'focusIssue', key: issue.key };
  const person = [...model.people.values()].find((p) => p.name.toLowerCase().includes(q));
  return person ? { mode: 'focusPerson', id: person.id } : null;
}

export function downstream(model, key) {
  const seen = new Set();
  const stack = [key];
  while (stack.length) {
    for (const n of model.blocks.get(stack.pop())) {
      if (!seen.has(n)) {
        seen.add(n);
        stack.push(n);
      }
    }
  }
  return seen;
}

function depthWithin(model, keys) {
  const memo = new Map();
  const depth = (k, stack) => {
    if (memo.has(k)) return memo.get(k);
    if (stack.has(k)) return 0;
    stack.add(k);
    const ups = model.blockedBy.get(k).filter((x) => keys.has(x));
    const d = Math.max(0, ...ups.map((x) => depth(x, stack) + 1));
    stack.delete(k);
    memo.set(k, d);
    return d;
  };
  return new Map([...keys].map((k) => [k, depth(k, new Set())]));
}

function groupBy(items, keyOf) {
  const out = new Map();
  for (const it of items) {
    const k = keyOf(it);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(it);
  }
  return out;
}

const truncate = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || '');
const firstName = (name) => name.split(' ').slice(-1)[0];

export function daysLeftText(d) {
  if (d.days_left == null) return 'chưa có hạn';
  if (d.days_left < 0) return `quá hạn ${-d.days_left} ngày`;
  return `còn ${d.days_left} ngày`;
}

function issueNode(model, i, { x, y, focus = false, faded = false } = {}) {
  const r = RISK[riskOf(i)];
  const badges = [i.is_critical_path && '★', i.blocked && '⛔', i.reopen_count > 0 && `↻${i.reopen_count}`]
    .filter(Boolean)
    .join(' ');
  const owner = model.people.get(i.person_id);
  const ownerName = owner.kind === 'unassigned' ? '—' : firstName(owner.name);
  const meta = isOpen(i) ? `${r.label}${i.is_overdue ? ` · +${i.overdue_days}d` : ''}` : r.label;
  return {
    id: i.key,
    x,
    y,
    shape: 'box',
    label: `<b>${i.key}</b>${badges ? `  ${badges}` : ''}\n${truncate(i.summary, 24)}\n<i>${meta} · ${ownerName}</i>`,
    widthConstraint: { minimum: 160, maximum: 160 },
    heightConstraint: { minimum: NODE_H - 12 },
    color: {
      background: r.fill,
      border: r.border,
      highlight: { background: r.fill, border: '#1c7ed6' },
      hover: { background: r.fill, border: '#1c7ed6' },
    },
    font: { color: '#1f2933', size: 12, multi: 'html', bold: { color: r.border, size: 13 }, ital: { color: r.border, size: 11 } },
    borderWidth: focus ? 4 : i.is_critical_path ? 3 : 1.5,
    shapeProperties: { borderDashes: i.is_overdue ? [6, 3] : false, borderRadius: 8 },
    shadow: focus
      ? { enabled: true, color: 'rgba(28,126,214,0.55)', size: 16, x: 0, y: 0 }
      : i.is_bottleneck
      ? { enabled: true, color: 'rgba(224,49,49,0.5)', size: 14, x: 0, y: 0 }
      : false,
    opacity: faded ? 0.55 : 1,
    baseOpacity: faded ? 0.55 : 1,
  };
}

function personNode(p, { x, y, big = false }) {
  if (p.kind === 'unassigned') {
    return {
      id: p.id,
      x,
      y,
      shape: 'box',
      label: `<b>📥 Chưa phân công</b>\n${p.open_count} task · ${p.high_risk_count} cao`,
      color: { background: '#fff9db', border: '#f08c00', highlight: { background: '#fff9db', border: '#1c7ed6' } },
      shapeProperties: { borderDashes: [5, 3], borderRadius: 8 },
      borderWidth: 2,
      font: { multi: 'html', size: 12, color: '#495057' },
    };
  }
  const over = p.is_overloaded;
  return {
    id: p.id,
    x,
    y,
    shape: 'dot',
    size: (big ? 22 : 14) + 3 * Math.min(p.open_count, 10),
    label: `<b>${p.name}</b>\n${p.open_count} mở · ${p.high_risk_count} cao${over ? ' · quá tải' : ''}`,
    color: {
      background: over ? '#fff0f0' : '#f1f3f5',
      border: over ? '#e03131' : '#adb5bd',
      highlight: { background: over ? '#fff0f0' : '#f1f3f5', border: '#1c7ed6' },
    },
    borderWidth: over ? 3 : 1.5,
    font: { multi: 'html', size: 12, color: over ? '#e03131' : '#495057' },
  };
}

function deadlineNode(d, { x, y }) {
  return {
    id: d.id,
    x,
    y,
    shape: 'hexagon',
    size: 22,
    label: `<b>${d.name}</b>\n${daysLeftText(d)}${d.at_risk ? ' · bị đe doạ' : ''}`,
    color: {
      background: d.at_risk ? '#fff0f0' : '#f8f9fa',
      border: d.at_risk ? '#e03131' : '#adb5bd',
      highlight: { background: d.at_risk ? '#fff0f0' : '#f8f9fa', border: '#1c7ed6' },
    },
    borderWidth: 2,
    font: { multi: 'html', size: 12, color: d.at_risk ? '#e03131' : '#495057' },
  };
}

function linkEdges(model, shown, showRelates) {
  return model.edges
    .filter((e) => shown.has(e.from) && shown.has(e.to) && (e.kind === 'blocks' || showRelates))
    .map((e) =>
      e.kind === 'blocks'
        ? {
            id: e.id,
            from: e.from,
            to: e.to,
            arrows: 'to',
            color: { color: e.propagates_risk ? '#e03131' : '#868e96', highlight: '#1c7ed6' },
            width: e.is_critical_path ? 4.5 : 2,
          }
        : {
            id: e.id,
            from: e.from,
            to: e.to,
            arrows: '',
            dashes: [5, 4],
            width: 1.2,
            color: { color: '#ced4da' },
            label: e.label,
            font: { size: 10, color: '#adb5bd', strokeWidth: 0 },
          }
    );
}

const tie = (id, from, to, dashes) => ({
  id,
  from,
  to,
  arrows: '',
  dashes,
  width: 1.2,
  color: { color: '#ced4da' },
  smooth: false,
});

const visibleIssues = (model, showDone) => [...model.issues.values()].filter((i) => showDone || isOpen(i));

const STATIC = { physics: false, layout: { hierarchical: { enabled: false } } };

function sceneLanes(model, { showDone, showRelates }) {
  const issues = visibleIssues(model, showDone);
  const keys = new Set(issues.map((i) => i.key));
  const depth = depthWithin(model, keys);
  const byPerson = groupBy(issues, (i) => i.person_id);
  const nodes = [];
  const lanes = [];
  let y = 0;
  let maxCol = 0;
  for (const pid of model.peopleOrder) {
    const mine = byPerson.get(pid);
    if (!mine) continue;
    const cols = groupBy(mine, (i) => depth.get(i.key));
    const rows = Math.max(...[...cols.values()].map((a) => a.length));
    const h = Math.max(LANE_PAD * 2 + (rows - 1) * ROW_H + NODE_H, 76);
    for (const [c, list] of cols) {
      maxCol = Math.max(maxCol, c);
      list.sort(byRisk).forEach((i, r) => {
        nodes.push(issueNode(model, i, { x: LANE_HEAD + 100 + c * COL_W, y: y + LANE_PAD + NODE_H / 2 + r * ROW_H }));
      });
    }
    lanes.push({ person: model.people.get(pid), y, h });
    y += h + 8;
  }
  const width = LANE_HEAD + 200 + maxCol * COL_W + 40;
  return {
    nodes,
    edges: linkEdges(model, keys, showRelates),
    options: { ...STATIC, edges: { smooth: { type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.45 } } },
    overlay: { lanes, width, labels: [], bounds: { minX: 0, minY: 0, maxX: width, maxY: y } },
  };
}

function sceneDag(model, { showDone, showRelates, dagLayout }) {
  const issues = visibleIssues(model, showDone);
  const keys = new Set(issues.map((i) => i.key));
  const hierarchical = dagLayout !== 'physics';
  return {
    nodes: issues.map((i) => issueNode(model, i)),
    edges: linkEdges(model, keys, showRelates),
    options: {
      layout: {
        randomSeed: 42,
        hierarchical: hierarchical
          ? {
              enabled: true,
              direction: dagLayout === 'hierarchical_ud' ? 'UD' : 'LR',
              sortMethod: 'directed',
              levelSeparation: 220,
              nodeSpacing: 110,
              treeSpacing: 160,
            }
          : { enabled: false },
      },
      physics: hierarchical
        ? false
        : {
            enabled: true,
            solver: 'forceAtlas2Based',
            forceAtlas2Based: { gravitationalConstant: -60, centralGravity: 0.007, springLength: 160, avoidOverlap: 0.8 },
            stabilization: { iterations: 200, fit: true },
          },
      edges: { smooth: { type: hierarchical ? 'cubicBezier' : 'continuous', roundness: 0.3 } },
    },
    overlay: { lanes: [], labels: [] },
  };
}

function bfsLevels(model, key, depth, showDone) {
  const level = new Map([[key, 0]]);
  for (const [adj, dir] of [
    [model.blockedBy, -1],
    [model.blocks, 1],
  ]) {
    let frontier = [key];
    for (let d = 1; d <= depth && frontier.length; d++) {
      const next = [];
      for (const k of frontier) {
        for (const n of adj.get(k)) {
          if (level.has(n) || !(showDone || isOpen(model.issues.get(n)))) continue;
          level.set(n, dir * d);
          next.push(n);
        }
      }
      frontier = next;
    }
  }
  return level;
}

function personRow(model, positioned, y) {
  const byPerson = groupBy(positioned, ([i]) => i.person_id);
  const order = [...byPerson.entries()]
    .map(([pid, list]) => [pid, list.reduce((s, [, p]) => s + p.x, 0) / list.length])
    .sort((a, b) => a[1] - b[1]);
  const xs = positioned.map(([, p]) => p.x);
  const span = (order.length - 1) * 190;
  const start = (Math.min(...xs) + Math.max(...xs)) / 2 - span / 2;
  return order.map(([pid], n) => personNode(model.people.get(pid), { x: start + n * 190, y }));
}

function sceneFocusIssue(model, { key, depth }, { showDone, showRelates }) {
  const level = bfsLevels(model, key, depth, showDone);
  const cols = groupBy([...level.keys()], (k) => level.get(k));
  const minL = Math.min(...cols.keys());
  const positioned = [];
  for (const [l, ks] of cols) {
    const sorted = ks.map((k) => model.issues.get(k)).sort((a, b) => (a.key === key ? -1 : b.key === key ? 1 : byRisk(a, b)));
    sorted.forEach((i, r) => positioned.push([i, { x: (l - minL) * FOCUS_COL_W, y: r * FOCUS_ROW_H }]));
  }
  const nodes = positioned.map(([i, p]) => issueNode(model, i, { ...p, focus: i.key === key }));
  const shown = new Set(level.keys());
  const edges = linkEdges(model, shown, showRelates);

  const maxY = Math.max(...positioned.map(([, p]) => p.y));
  const people = personRow(model, positioned, maxY + 170);
  nodes.push(...people);
  for (const [i] of positioned) edges.push(tie(`own:${i.key}`, i.key, i.person_id, [3, 4]));

  const centerX = -minL * FOCUS_COL_W;
  const focus = model.issues.get(key);
  focus.deadline_ids
    .map((id) => model.deadlines.get(id))
    .filter(Boolean)
    .forEach((d, n, all) => {
      nodes.push(deadlineNode(d, { x: centerX + (n - (all.length - 1) / 2) * 220, y: -190 }));
      for (const [i] of positioned) {
        if (i.deadline_ids.includes(d.id)) edges.push(tie(`dl:${d.id}:${i.key}`, d.id, i.key, [1, 4]));
      }
    });

  const labels = [...cols.keys()].map((l) => ({
    x: (l - minL) * FOCUS_COL_W,
    y: -70,
    text: l < 0 ? `CHẶN NÓ (${-l} BƯỚC)` : l > 0 ? `BỊ ẢNH HƯỞNG (${l} BƯỚC)` : 'TÂM ĐIỂM',
    color: l === 0 ? '#1c7ed6' : '#adb5bd',
    align: 'center',
  }));
  return {
    nodes,
    edges,
    options: { ...STATIC, edges: { smooth: { type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.45 } } },
    overlay: { lanes: [], labels },
  };
}

function sceneFocusPerson(model, { id }, { showDone, showRelates }) {
  const mine = [...model.issues.values()].filter((i) => i.person_id === id && (showDone || isOpen(i))).sort(byRisk);
  const mineKeys = new Set(mine.map((i) => i.key));
  const others = [...new Set(mine.flatMap((i) => model.blocks.get(i.key)))]
    .map((k) => model.issues.get(k))
    .filter((t) => !mineKeys.has(t.key) && (showDone || isOpen(t)))
    .sort(byRisk);
  const nodes = [
    ...mine.map((i, n) => issueNode(model, i, { x: n * PERSON_COL_W, y: 230 })),
    ...others.map((i, n) => issueNode(model, i, { x: n * PERSON_COL_W, y: 0, faded: true })),
  ];
  const personX = ((Math.max(mine.length, 1) - 1) * PERSON_COL_W) / 2;
  nodes.push(personNode(model.people.get(id), { x: personX, y: 470, big: true }));
  const shown = new Set([...mineKeys, ...others.map((i) => i.key)]);
  const edges = [...linkEdges(model, shown, showRelates), ...mine.map((i) => tie(`own:${i.key}`, i.key, id, false))];
  const labels = [{ x: -80, y: 180, text: 'TASK ĐANG PHỤ TRÁCH (RỦI RO GIẢM DẦN →)', color: '#adb5bd', align: 'left' }];
  if (others.length) {
    labels.push({ x: -80, y: -50, text: 'TASK CỦA NGƯỜI KHÁC ĐANG BỊ CHẶN BỞI NGƯỜI NÀY', color: '#adb5bd', align: 'left' });
  }
  return {
    nodes,
    edges,
    options: { ...STATIC, edges: { smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.5 } } },
    overlay: { lanes: [], labels },
  };
}

const SCENES = {
  lanes: (model, _view, opts) => sceneLanes(model, opts),
  dag: (model, _view, opts) => sceneDag(model, opts),
  focusIssue: sceneFocusIssue,
  focusPerson: sceneFocusPerson,
};

export function buildScene(model, view, opts) {
  return SCENES[view.mode](model, view, opts);
}

export function drawOverlay(ctx, overlay) {
  ctx.save();
  for (const { person, y, h } of overlay.lanes) {
    const unassigned = person.kind === 'unassigned';
    ctx.fillStyle = unassigned ? '#fff9db' : person.is_overloaded ? '#fff5f5' : '#f8f9fa';
    ctx.strokeStyle = '#e9ecef';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(0, y, overlay.width, h, 8);
    ctx.fill();
    ctx.stroke();
    ctx.textAlign = 'left';
    ctx.fillStyle = '#1f2933';
    ctx.font = 'bold 14px system-ui, sans-serif';
    const icon = unassigned ? '📥 ' : person.is_overloaded ? '🔴 ' : '◯ ';
    ctx.fillText(icon + truncate(person.name, 18), 14, y + 24);
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillStyle = '#868e96';
    ctx.fillText(`${person.open_count} mở · ${person.high_risk_count} cao`, 14, y + 44);
    if (person.is_overloaded) {
      ctx.fillStyle = '#e03131';
      ctx.font = 'bold 12px system-ui, sans-serif';
      ctx.fillText('quá tải', 14, y + 62);
    }
  }
  for (const { x, y, text, color, align } of overlay.labels) {
    ctx.font = 'bold 11px system-ui, sans-serif';
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.fillText(text, x, y);
  }
  ctx.restore();
}

export function laneAt(overlay, point) {
  return overlay.lanes.find(({ y, h }) => point.x >= 0 && point.x <= LANE_HEAD && point.y >= y && point.y <= y + h)?.person;
}

const factorText = (f) => (typeof f === 'string' ? f : f.detail || f.rule || JSON.stringify(f));

export function issueInsight(model, key) {
  const issue = model.issues.get(key);
  const owner = model.people.get(issue.person_id);
  const down = [...downstream(model, key)].map((k) => model.issues.get(k)).filter(isOpen);
  const upRisky = model.blockedBy
    .get(key)
    .map((k) => model.issues.get(k))
    .filter((u) => isRisky(u) || (isOpen(u) && u.level === 'MED'));
  const own = new Set(issue.deadline_ids);
  const otherDeadlines = [...new Set(down.flatMap((d) => d.deadline_ids))]
    .filter((id) => !own.has(id))
    .map((id) => model.deadlines.get(id))
    .filter(Boolean);
  const downOwners = [...new Set(down.map((d) => d.person_id))]
    .filter((pid) => pid !== UNASSIGNED && pid !== issue.person_id)
    .map((pid) => model.people.get(pid).name);

  const suggestions = [];
  if (owner.is_overloaded) suggestions.push({ text: `Chuyển bớt việc của ${owner.name}`, view: { mode: 'focusPerson', id: owner.id } });
  if (owner.kind === 'unassigned') suggestions.push({ text: 'Giao người phụ trách ngay', view: { mode: 'focusPerson', id: owner.id } });
  for (const u of upRisky) suggestions.push({ text: `Ưu tiên gỡ ${u.key} (đang chặn)`, view: { mode: 'focusIssue', key: u.key } });
  if (downOwners.length) suggestions.push({ text: `Báo trước cho ${downOwners.join(', ')}` });

  return {
    issue,
    owner,
    deadlines: issue.deadline_ids.map((id) => model.deadlines.get(id)).filter(Boolean),
    factors: (issue.factors || []).map(factorText),
    down,
    downHigh: down.filter((d) => d.level === 'HIGH').length,
    otherDeadlines,
    suggestions,
  };
}

export function personInsight(model, id) {
  const person = model.people.get(id);
  const mine = [...model.issues.values()].filter((i) => i.person_id === id && isOpen(i)).sort(byRisk);
  const blockingOthers = mine
    .map((i) => ({
      key: i.key,
      targets: model.blocks
        .get(i.key)
        .map((k) => model.issues.get(k))
        .filter((t) => t.person_id !== id && isOpen(t))
        .map((t) => ({ key: t.key, owner: model.people.get(t.person_id).name })),
    }))
    .filter((b) => b.targets.length);
  const candidates = [...model.people.values()]
    .filter((p) => p.kind === 'person' && p.id !== id)
    .sort((a, b) => a.open_count - b.open_count || a.high_risk_count - b.high_risk_count)
    .slice(0, 2);
  const movable = mine.filter((i) => i.level !== 'HIGH' && !model.blocks.get(i.key).length).slice(0, 2);
  return { person, mine, blockingOthers, candidates, movable };
}

export function overviewInsight(model) {
  const bottlenecks = [...model.issues.values()]
    .filter((i) => i.is_bottleneck)
    .map((i) => ({ issue: i, impact: downstream(model, i.key).size }))
    .sort((a, b) => b.impact - a.impact)
    .slice(0, 6);
  return { bottlenecks, criticalPath: model.criticalPath };
}
