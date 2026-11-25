/** Domain helpers for the local Jira views. Pure: no fetch, no React. */

export const jiraQueryKeys = {
  root: ['jira'],
  board: (project) => ['jira', 'board', project],
  issues: (project, query) => ['jira', 'issues', project, query],
  sprints: (project) => ['jira', 'sprints', project],
  issue: (key) => ['jira', 'issue', key],
  transitions: (key) => ['jira', 'transitions', key],
  comments: (key) => ['jira', 'comments', key],
  components: (project) => ['jira', 'components', project],
  versions: (project) => ['jira', 'versions', project],
};

export const ISSUE_TYPES = ['Task', 'Story', 'Bug', 'Epic', 'Sub-task'];
export const PRIORITIES = ['Highest', 'High', 'Medium', 'Low', 'Lowest'];

export function adfToText(node) {
  if (node == null) return '';
  if (typeof node === 'string') return node;
  if (Array.isArray(node)) return node.map(adfToText).join('');
  if (typeof node !== 'object') return '';
  const own = typeof node.text === 'string' ? node.text : '';
  const kids = Array.isArray(node.content) ? node.content.map(adfToText).join('') : '';
  const gap = node.type === 'paragraph' || node.type === 'heading' ? '\n' : '';
  return `${own}${kids}${gap}`;
}

export function issueDescription(issue) {
  if (!issue) return '';
  if (typeof issue.description === 'string') return issue.description;
  return adfToText(issue.raw?.fields?.description).trim();
}

export function issueSprintIds(issue) {
  const list = issue?.raw?.fields?.customfield_10020;
  if (!Array.isArray(list)) return [];
  return list.map((row) => Number(row?.id)).filter((id) => Number.isInteger(id));
}

export function issuesForSprint(issues, sprintId) {
  const id = Number(sprintId);
  return (issues || []).filter((issue) => issueSprintIds(issue).includes(id));
}

export function backlogIssues(issues) {
  return (issues || []).filter((issue) => issueSprintIds(issue).length === 0);
}

export function openSprints(sprints) {
  return (sprints || [])
    .filter((sprint) => sprint.state !== 'closed')
    .slice()
    .sort((a, b) => {
      if (a.state === 'active' && b.state !== 'active') return -1;
      if (b.state === 'active' && a.state !== 'active') return 1;
      return a.id - b.id;
    });
}

function statusName(column) {
  return String(column?.status || column?.name || '').trim().toLowerCase();
}

export function transitionForColumn(transitions, column) {
  const target = statusName(column);
  if (!target) return null;
  return (
    (transitions || []).find((row) => String(row.to_status || '').trim().toLowerCase() === target) || null
  );
}

/** Prefer an id already on the board column. Otherwise match a transition by target status. */
export function transitionIdForMove(column, transitions) {
  if (column?.transition_id != null && String(column.transition_id) !== '') {
    return String(column.transition_id);
  }
  const embedded = transitionForColumn(column?.transitions, column);
  if (embedded) return String(embedded.id);
  const match = transitionForColumn(transitions, column);
  return match ? String(match.id) : null;
}

export function changedIssueFields(issue, draft) {
  const fields = {};
  if (draft.summary !== (issue.summary || '')) fields.summary = draft.summary;
  if (draft.description !== issueDescription(issue)) fields.description = draft.description;
  const assignee = issue.assignee_name || issue.assignee_id || '';
  if (draft.assignee !== assignee) fields.assignee = draft.assignee.trim() ? draft.assignee.trim() : null;
  if (draft.priority !== (issue.priority || '')) fields.priority = draft.priority;
  const due = (issue.duedate || '').slice(0, 10);
  if (draft.duedate !== due) fields.duedate = draft.duedate || null;
  return fields;
}
