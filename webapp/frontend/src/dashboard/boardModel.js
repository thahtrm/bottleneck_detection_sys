const DAY_MS = 86_400_000;

export const LEVELS = {
  HIGH: { label: 'Cao', color: 'red', rank: 3 },
  MED: { label: 'TB', color: 'orange', rank: 2 },
  LOW: { label: 'Thấp', color: 'green', rank: 1 },
};
const UNSCORED = { label: 'Chưa đánh giá', color: 'gray', rank: 0 };
const DONE = { label: 'Đã xong', color: 'gray', rank: 0 };

const DEADLINE_TYPES = {
  sprint: 'Sprint',
  duedate: 'Due date',
  due_date: 'Due date',
  release: 'Release',
  sla: 'SLA',
};

export const isDone = (card) => card.triage === 'done';

const levelOf = (card) => (isDone(card) ? DONE : LEVELS[card.level] ?? UNSCORED);

const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

export const daysUntil = (iso, now) => Math.round((startOfDay(new Date(iso)) - startOfDay(now)) / DAY_MS);

export const isOverdue = (card, ctx) =>
  !isDone(card) && card.deadline != null && daysUntil(card.deadline.at, ctx.now) < 0;

export function boardContext(board, now) {
  return {
    now,
    statusColumns: board.status_columns,
    sprintEnd: board.sprint?.end_at ? new Date(board.sprint.end_at) : null,
  };
}

export const CHIPS = [
  {
    id: 'rising',
    label: 'Tăng rủi ro 24h',
    test: (card, ctx) =>
      (card.level === 'HIGH' || card.level === 'MED') &&
      card.raised_at != null &&
      ctx.now.getTime() - new Date(card.raised_at).getTime() <= DAY_MS,
  },
  { id: 'blocked', label: 'Bị chặn', test: (card) => card.blocked },
  { id: 'critical', label: 'Quan trọng', test: (card) => card.is_critical },
  { id: 'overdue', label: 'Quá hạn', test: isOverdue },
];

const CHIP_TESTS = Object.fromEntries(CHIPS.map((chip) => [chip.id, chip.test]));

export const applyChips = (cards, chipIds, ctx) =>
  cards.filter((card) => chipIds.every((id) => CHIP_TESTS[id](card, ctx)));

export const countChips = (cards, ctx) =>
  Object.fromEntries(CHIPS.map((chip) => [chip.id, cards.filter((card) => chip.test(card, ctx)).length]));

const DONE_COLUMN = { id: 'done', title: 'Xong (7 ngày)' };
const UNASSIGNED = 'assignee:none';

const daysLeftInWeek = (now) => (7 - now.getDay()) % 7;

function deadlineBucket(card, ctx) {
  if (isDone(card)) return 'done';
  if (!card.deadline) return 'none';
  const days = daysUntil(card.deadline.at, ctx.now);
  if (days < 0) return 'overdue';
  if (days <= daysLeftInWeek(ctx.now)) return 'week';
  if (ctx.sprintEnd && days <= daysUntil(ctx.sprintEnd, ctx.now)) return 'sprint';
  return 'later';
}

function assigneeColumns(cards) {
  const people = new Map();
  let hasUnassigned = false;
  for (const card of cards) {
    if (card.assignee) people.set(card.assignee.id, card.assignee.name);
    else hasUnassigned = true;
  }
  const named = [...people]
    .map(([id, name]) => ({ id: `assignee:${id}`, title: name }))
    .sort((a, b) => a.title.localeCompare(b.title, 'vi'));
  return hasUnassigned ? [{ id: UNASSIGNED, title: 'Chưa giao' }, ...named] : named;
}

const fixed = (columns) => () => columns;

export const GROUPINGS = {
  triage: {
    label: 'Phân loại',
    columns: fixed([
      { id: 'needs_action', title: 'Cần xử lý' },
      { id: 'in_hand', title: 'Đã có hành động' },
      { id: 'ok', title: 'Ổn' },
      DONE_COLUMN,
    ]),
    keyOf: (card) => card.triage,
  },
  status: {
    label: 'Trạng thái',
    columns: (_cards, ctx) => ctx.statusColumns.map((col) => ({ id: col.id, title: col.name })),
    keyOf: (card) => card.status_column,
  },
  assignee: {
    label: 'Người làm',
    columns: assigneeColumns,
    keyOf: (card) => (card.assignee ? `assignee:${card.assignee.id}` : UNASSIGNED),
  },
  deadline: {
    label: 'Hạn chót',
    columns: fixed([
      { id: 'overdue', title: 'Quá hạn' },
      { id: 'week', title: 'Tuần này' },
      { id: 'sprint', title: 'Sprint này' },
      { id: 'later', title: 'Sau' },
      { id: 'none', title: 'Chưa có hạn' },
      DONE_COLUMN,
    ]),
    keyOf: deadlineBucket,
  },
  risk: {
    label: 'Mức rủi ro',
    columns: fixed([
      { id: 'HIGH', title: 'Cao' },
      { id: 'MED', title: 'Trung bình' },
      { id: 'LOW', title: 'Thấp' },
      { id: 'none', title: 'Chưa đánh giá' },
      DONE_COLUMN,
    ]),
    keyOf: (card) => (isDone(card) ? 'done' : card.level ?? 'none'),
  },
};

const deadlineMs = (card) => (card.deadline ? Date.parse(card.deadline.at) : Infinity);

const byUrgency = (a, b) =>
  Number(isDone(a)) - Number(isDone(b)) ||
  levelOf(b).rank - levelOf(a).rank ||
  deadlineMs(a) - deadlineMs(b) ||
  a.key.localeCompare(b.key, undefined, { numeric: true });

const isOpenHigh = (card) => !isDone(card) && card.level === 'HIGH';

export function groupIssues(cards, group, chips, ctx) {
  const grouping = GROUPINGS[group];
  const visible = applyChips(cards, chips, ctx);
  const columns = grouping.columns(visible, ctx);
  const buckets = new Map(columns.map((col) => [col.id, []]));
  for (const card of visible) buckets.get(grouping.keyOf(card, ctx)).push(card);
  return columns.map((col) => {
    const colCards = buckets.get(col.id).sort(byUrgency);
    return { ...col, cards: colCards, count: colCards.length, highCount: colCards.filter(isOpenHigh).length };
  });
}

const pad2 = (n) => String(n).padStart(2, '0');
const ddmm = (iso) => {
  const d = new Date(iso);
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}`;
};

function initials(name) {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function deadlineText(card, ctx) {
  if (isDone(card)) return card.resolved_at ? `Xong ${ddmm(card.resolved_at)}` : null;
  if (!card.deadline) return null;
  const days = daysUntil(card.deadline.at, ctx.now);
  if (days < 0) return `Quá hạn ${-days} ngày`;
  if (days === 0) return 'Hạn hôm nay';
  return `Còn ${days} ngày`;
}

function riskText(card) {
  const level = levelOf(card);
  if (isDone(card) || card.delay_value == null) return level.label;
  const deadlineType = card.deadline ? DEADLINE_TYPES[card.deadline.type] ?? card.deadline.type : 'chưa có hạn';
  return `${level.label} · ${Math.round(card.delay_value * 100)}% (${deadlineType})`;
}

export function describeCard(card, ctx) {
  const { label, color } = levelOf(card);
  return {
    level: { label, color },
    riskText: riskText(card),
    deadlineText: deadlineText(card, ctx),
    deadlineTitle: card.deadline?.label ?? null,
    assigneeName: card.assignee?.name ?? 'Chưa giao',
    initials: card.assignee ? initials(card.assignee.name) : '–',
  };
}
