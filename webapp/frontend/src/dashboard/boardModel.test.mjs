import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CHIPS, GROUPINGS, countChips, describeCard, groupIssues } from './boardModel.js';

const now = new Date('2026-11-04T10:00:00');
const ctx = {
  now,
  sprintEnd: new Date('2026-11-12T17:00:00'),
  statusColumns: [
    { id: 'status:to-do', name: 'To Do' },
    { id: 'status:in-progress', name: 'In Progress' },
    { id: 'status:in-review', name: 'In Review' },
    { id: 'status:done', name: 'Done' },
  ],
};

const card = (key, fields) => ({
  key,
  summary: `Việc ${key}`,
  status: 'To Do',
  status_column: 'status:to-do',
  assignee: null,
  level: null,
  delay_value: null,
  blocked: false,
  is_critical: false,
  raised_at: null,
  deadline: null,
  resolved_at: null,
  triage: 'ok',
  ...fields,
});

const an = { id: 'acc-1', name: 'Nguyễn An' };
const binh = { id: 'acc-2', name: 'Bùi Bình' };
const chau = { id: 'acc-3', name: 'Cao Châu' };

const cards = [
  card('A-1', {
    level: 'HIGH', delay_value: 0.82, triage: 'needs_action', assignee: an,
    status: 'In Progress', status_column: 'status:in-progress',
    deadline: { type: 'sprint', label: 'Sprint 1', at: '2026-11-12T17:00:00' },
    raised_at: '2026-11-04T02:00:00',
  }),
  card('A-2', {
    level: 'MED', delay_value: 0.55, triage: 'in_hand', blocked: true,
    deadline: { type: 'duedate', label: 'Due date', at: '2026-11-02T23:59:00' },
    raised_at: '2026-11-01T08:00:00',
  }),
  card('A-3', { level: 'LOW', assignee: binh, is_critical: true }),
  card('A-4', {
    assignee: an, status: 'In Progress', status_column: 'status:in-progress',
    deadline: { type: 'duedate', label: 'Due date', at: '2026-11-06T23:59:00' },
  }),
  card('A-5', {
    level: 'HIGH', triage: 'done', assignee: binh, status: 'Done', status_column: 'status:done',
    deadline: { type: 'duedate', label: 'Due date', at: '2026-11-01T23:59:00' },
    resolved_at: '2026-11-03T15:00:00',
  }),
  card('A-6', {
    level: 'HIGH', delay_value: 0.9, triage: 'needs_action', assignee: chau, blocked: true, is_critical: true,
    status: 'In Review', status_column: 'status:in-review',
    deadline: { type: 'release', label: 'Release 2', at: '2026-12-20T23:59:00' },
    raised_at: '2026-11-04T09:00:00',
  }),
  card('A-7', {
    level: 'MED', delay_value: 0.6, triage: 'needs_action',
    deadline: { type: 'sprint', label: 'Sprint 1', at: '2026-11-10T17:00:00' },
  }),
];

const keysByTitle = (columns) => Object.fromEntries(columns.map((col) => [col.title, col.cards.map((c) => c.key)]));
const total = (columns) => columns.reduce((sum, col) => sum + col.count, 0);

test('every card lands in exactly one column for every grouping', () => {
  const allKeys = cards.map((c) => c.key).sort();
  for (const group of Object.keys(GROUPINGS)) {
    const placed = groupIssues(cards, group, [], ctx).flatMap((col) => col.cards.map((c) => c.key));
    assert.deepEqual(placed.sort(), allKeys, `grouping ${group}`);
  }
});

test('triage, deadline and risk columns stay on the board when empty', () => {
  const titles = (group) => groupIssues([], group, [], ctx).map((col) => col.title);
  assert.deepEqual(titles('triage'), ['Cần xử lý', 'Đã có hành động', 'Ổn', 'Xong (7 ngày)']);
  assert.deepEqual(titles('deadline'), ['Quá hạn', 'Tuần này', 'Sprint này', 'Sau', 'Chưa có hạn', 'Xong (7 ngày)']);
  assert.deepEqual(titles('risk'), ['Cao', 'Trung bình', 'Thấp', 'Chưa đánh giá', 'Xong (7 ngày)']);
});

test('triage columns follow the server triage and sort by risk, then nearest deadline', () => {
  assert.deepEqual(keysByTitle(groupIssues(cards, 'triage', [], ctx)), {
    'Cần xử lý': ['A-1', 'A-6', 'A-7'],
    'Đã có hành động': ['A-2'],
    'Ổn': ['A-3', 'A-4'],
    'Xong (7 ngày)': ['A-5'],
  });
});

test('deadline grouping buckets by today, end of this week and end of the sprint', () => {
  assert.deepEqual(keysByTitle(groupIssues(cards, 'deadline', [], ctx)), {
    'Quá hạn': ['A-2'],
    'Tuần này': ['A-4'],
    'Sprint này': ['A-1', 'A-7'],
    'Sau': ['A-6'],
    'Chưa có hạn': ['A-3'],
    'Xong (7 ngày)': ['A-5'],
  });
});

test('deadline grouping has no sprint bucket without an active sprint', () => {
  const columns = groupIssues(cards, 'deadline', [], { ...ctx, sprintEnd: null });
  assert.deepEqual(keysByTitle(columns)['Sprint này'], []);
  assert.deepEqual(keysByTitle(columns)['Sau'], ['A-1', 'A-6', 'A-7']);
});

test('status grouping uses the payload status columns in order', () => {
  const columns = groupIssues(cards, 'status', [], ctx);
  assert.deepEqual(columns.map((col) => col.title), ['To Do', 'In Progress', 'In Review', 'Done']);
  assert.deepEqual(keysByTitle(columns)['In Review'], ['A-6']);
});

test('assignee grouping puts unassigned work first, then people by name', () => {
  const columns = groupIssues(cards, 'assignee', [], ctx);
  assert.deepEqual(columns.map((col) => col.title), ['Chưa giao', 'Bùi Bình', 'Cao Châu', 'Nguyễn An']);
  assert.deepEqual(columns[0].cards.map((c) => c.key), ['A-2', 'A-7']);
});

test('risk grouping keeps finished work out of the level columns', () => {
  assert.deepEqual(keysByTitle(groupIssues(cards, 'risk', [], ctx)), {
    'Cao': ['A-1', 'A-6'],
    'Trung bình': ['A-2', 'A-7'],
    'Thấp': ['A-3'],
    'Chưa đánh giá': ['A-4'],
    'Xong (7 ngày)': ['A-5'],
  });
});

test('chips combine with AND', () => {
  const shown = (chips) => groupIssues(cards, 'triage', chips, ctx).flatMap((col) => col.cards.map((c) => c.key)).sort();
  assert.deepEqual(shown(['blocked']), ['A-2', 'A-6']);
  assert.deepEqual(shown(['critical']), ['A-3', 'A-6']);
  assert.deepEqual(shown(['blocked', 'critical']), ['A-6']);
  assert.deepEqual(shown(['rising']), ['A-1', 'A-6']);
  assert.deepEqual(shown(['overdue']), ['A-2']);
  assert.deepEqual(shown(['overdue', 'critical']), []);
});

test('chip counts equal the cards the board renders for that chip', () => {
  const counts = countChips(cards, ctx);
  assert.deepEqual(counts, { rising: 2, blocked: 2, critical: 2, overdue: 1 });
  for (const chip of CHIPS) {
    for (const group of Object.keys(GROUPINGS)) {
      assert.equal(total(groupIssues(cards, group, [chip.id], ctx)), counts[chip.id], `${chip.id} in ${group}`);
    }
  }
});

test('column counts match their cards and the Cao count ignores finished work', () => {
  const columns = groupIssues(cards, 'triage', [], ctx);
  for (const col of columns) assert.equal(col.count, col.cards.length);
  const high = Object.fromEntries(columns.map((col) => [col.title, col.highCount]));
  assert.deepEqual(high, { 'Cần xử lý': 2, 'Đã có hành động': 0, 'Ổn': 0, 'Xong (7 ngày)': 0 });
});

test('card description always names the deadline type next to P(trễ)', () => {
  const byKey = Object.fromEntries(cards.map((c) => [c.key, describeCard(c, ctx)]));
  assert.equal(byKey['A-1'].riskText, 'Cao · 82% (Sprint)');
  assert.equal(byKey['A-2'].riskText, 'TB · 55% (Due date)');
  assert.equal(byKey['A-6'].riskText, 'Cao · 90% (Release)');
  assert.equal(byKey['A-3'].riskText, 'Thấp');
  assert.equal(byKey['A-4'].riskText, 'Chưa đánh giá');
  assert.equal(byKey['A-5'].riskText, 'Đã xong');
  assert.equal(
    describeCard(card('X-1', { level: 'HIGH', delay_value: 0.7, triage: 'needs_action' }), ctx).riskText,
    'Cao · 70% (chưa có hạn)',
  );
  const seeded = card('X-3', {
    level: 'HIGH', delay_value: 0.65, triage: 'needs_action',
    deadline: { type: 'due_date', label: 'Quá hạn', at: '2026-11-06T16:19:06+00:00' },
  });
  assert.equal(describeCard(seeded, ctx).riskText, 'Cao · 65% (Due date)');
});

test('card description counts down to the deadline and names the assignee', () => {
  const byKey = Object.fromEntries(cards.map((c) => [c.key, describeCard(c, ctx)]));
  assert.equal(byKey['A-1'].deadlineText, 'Còn 8 ngày');
  assert.equal(byKey['A-2'].deadlineText, 'Quá hạn 2 ngày');
  assert.equal(byKey['A-3'].deadlineText, null);
  assert.equal(byKey['A-5'].deadlineText, 'Xong 03/11');
  assert.equal(describeCard(card('X-2', { deadline: { type: 'sla', label: 'SLA', at: '2026-11-04T23:00:00' } }), ctx).deadlineText, 'Hạn hôm nay');
  assert.equal(byKey['A-1'].assigneeName, 'Nguyễn An');
  assert.equal(byKey['A-1'].initials, 'NA');
  assert.equal(byKey['A-2'].assigneeName, 'Chưa giao');
  assert.equal(byKey['A-1'].level.color, 'red');
  assert.equal(byKey['A-5'].level.color, 'gray');
});
