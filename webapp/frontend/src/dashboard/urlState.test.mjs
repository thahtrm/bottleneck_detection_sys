import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_STATE, applyPatch, parseDashboardState, serializeDashboardState } from './urlState.js';

test('an empty URL is the default dashboard and the default serializes to nothing', () => {
  assert.deepEqual(parseDashboardState(''), DEFAULT_STATE);
  assert.equal(serializeDashboardState(DEFAULT_STATE), '');
});

test('a full state survives a round trip through the URL', () => {
  const state = {
    project: 'DEMO',
    q: 'đăng nhập, OTP & SMS',
    view: 'list',
    group: 'assignee',
    chips: ['rising', 'overdue'],
    issue: 'DEMO-12',
    sprint: 7,
  };
  const search = serializeDashboardState(state);
  assert.deepEqual(parseDashboardState(search), state);
  assert.match(search, /chips=rising,overdue/);
});

test('defaults are left out of the URL', () => {
  const search = serializeDashboardState({ ...DEFAULT_STATE, project: 'DEMO', view: 'board', group: 'triage' });
  assert.equal(search, '?project=DEMO');
});

test('unknown views, groups, chips and bad sprint ids fall back to defaults', () => {
  const state = parseDashboardState('?view=kanban&group=color&chips=blocked,bogus&sprint=abc');
  assert.equal(state.view, 'board');
  assert.equal(state.group, 'triage');
  assert.deepEqual(state.chips, ['blocked']);
  assert.equal(state.sprint, null);
});

test('chips come back in one canonical order whatever order they were toggled in', () => {
  const search = serializeDashboardState({ ...DEFAULT_STATE, chips: ['overdue', 'blocked'] });
  assert.equal(search, '?chips=blocked,overdue');
});

test('changing project clears the selected issue and sprint', () => {
  const state = { ...DEFAULT_STATE, project: 'DEMO', issue: 'DEMO-1', sprint: 3, chips: ['blocked'] };
  assert.deepEqual(applyPatch(state, { project: 'OPS' }), { ...state, project: 'OPS', issue: null, sprint: null });
});

test('patches that keep the project keep the selected issue and sprint', () => {
  const state = { ...DEFAULT_STATE, project: 'DEMO', issue: 'DEMO-1', sprint: 3 };
  assert.deepEqual(applyPatch(state, { q: 'login' }), { ...state, q: 'login' });
  assert.deepEqual(applyPatch(state, { project: 'DEMO', view: 'list' }), { ...state, view: 'list' });
});

test('a project change can carry its own issue selection', () => {
  const state = { ...DEFAULT_STATE, project: 'DEMO', issue: 'DEMO-1', sprint: 3 };
  assert.deepEqual(applyPatch(state, { project: 'OPS', issue: 'OPS-4' }), {
    ...state,
    project: 'OPS',
    issue: 'OPS-4',
    sprint: null,
  });
});
