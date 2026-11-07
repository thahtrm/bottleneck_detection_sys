import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { CHIPS, GROUPINGS } from './boardModel.js';

export const VIEWS = ['board', 'list', 'graph', 'settings'];

export const DEFAULT_STATE = Object.freeze({
  project: '',
  q: '',
  view: 'board',
  group: 'triage',
  chips: [],
  issue: null,
  sprint: null,
});

export function parseDashboardState(search) {
  const params = new URLSearchParams(search);
  const view = params.get('view');
  const group = params.get('group');
  const chips = new Set((params.get('chips') ?? '').split(','));
  const sprint = Number(params.get('sprint'));
  return {
    project: params.get('project') ?? DEFAULT_STATE.project,
    q: params.get('q') ?? DEFAULT_STATE.q,
    view: VIEWS.includes(view) ? view : DEFAULT_STATE.view,
    group: Object.hasOwn(GROUPINGS, group ?? '') ? group : DEFAULT_STATE.group,
    chips: CHIPS.map((chip) => chip.id).filter((id) => chips.has(id)),
    issue: params.get('issue') || DEFAULT_STATE.issue,
    sprint: Number.isInteger(sprint) && sprint > 0 ? sprint : DEFAULT_STATE.sprint,
  };
}

export function serializeDashboardState(state) {
  const chips = CHIPS.map((chip) => chip.id).filter((id) => state.chips.includes(id));
  const pairs = [
    ['project', state.project],
    ['q', state.q],
    ['view', state.view !== DEFAULT_STATE.view && state.view],
    ['group', state.group !== DEFAULT_STATE.group && state.group],
    ['chips', chips.join(',')],
    ['sprint', state.sprint != null && String(state.sprint)],
    ['issue', state.issue],
  ].filter(([, value]) => value);
  if (pairs.length === 0) return '';
  return `?${pairs.map(([key, value]) => `${key}=${encodeURIComponent(value).replace(/%2C/g, ',')}`).join('&')}`;
}

export function applyPatch(state, patch) {
  const projectChanged = patch.project !== undefined && patch.project !== state.project;
  return projectChanged ? { ...state, issue: null, sprint: null, ...patch } : { ...state, ...patch };
}

const listeners = new Set();

function subscribe(listener) {
  listeners.add(listener);
  window.addEventListener('popstate', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('popstate', listener);
  };
}

const getSearch = () => window.location.search;

export function useDashboardState() {
  const search = useSyncExternalStore(subscribe, getSearch);
  const state = useMemo(() => parseDashboardState(search), [search]);
  const update = useCallback((patch, { replace = false } = {}) => {
    const next = serializeDashboardState(applyPatch(parseDashboardState(window.location.search), patch));
    if (next === window.location.search) return;
    const typingOnly = Object.keys(patch).every((key) => key === 'q');
    const url = `${window.location.pathname}${next}${window.location.hash}`;
    window.history[replace || typingOnly ? 'replaceState' : 'pushState'](null, '', url);
    listeners.forEach((listener) => listener());
  }, []);
  return [state, update];
}
