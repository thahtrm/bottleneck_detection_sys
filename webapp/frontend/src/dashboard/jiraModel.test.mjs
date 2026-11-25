import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  adfToText,
  backlogIssues,
  changedIssueFields,
  issueDescription,
  issuesForSprint,
  openSprints,
  transitionIdForMove,
} from './jiraModel.js';

test('description prefers a plain field and otherwise flattens ADF', () => {
  assert.equal(issueDescription({ description: 'plain' }), 'plain');
  const adf = {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }],
  };
  assert.equal(adfToText(adf).trim(), 'Hello');
  assert.equal(issueDescription({ raw: { fields: { description: adf } } }), 'Hello');
});

test('backlog is issues with no sprint and a sprint keeps its own issues', () => {
  const issues = [
    { key: 'A-1', raw: { fields: { customfield_10020: [] } } },
    { key: 'A-2', raw: { fields: { customfield_10020: [{ id: 4, name: 'Sprint 1' }] } } },
    { key: 'A-3' },
  ];
  assert.deepEqual(backlogIssues(issues).map((issue) => issue.key), ['A-1', 'A-3']);
  assert.deepEqual(issuesForSprint(issues, 4).map((issue) => issue.key), ['A-2']);
});

test('open sprints put the active sprint first and drop closed ones', () => {
  const rows = openSprints([
    { id: 2, state: 'future', name: 'Next' },
    { id: 1, state: 'closed', name: 'Old' },
    { id: 3, state: 'active', name: 'Now' },
  ]);
  assert.deepEqual(rows.map((row) => row.id), [3, 2]);
});

test('a column transition id wins, otherwise the transition whose target status matches', () => {
  const column = { name: 'Done', status: 'Done' };
  assert.equal(transitionIdForMove({ ...column, transition_id: '9' }, []), '9');
  assert.equal(
    transitionIdForMove(column, [
      { id: '11', to_status: 'In Progress' },
      { id: '61', to_status: 'Done' },
    ]),
    '61',
  );
  assert.equal(transitionIdForMove(column, [{ id: '11', to_status: 'In Progress' }]), null);
});

test('field edits send only the values that differ from the issue', () => {
  const issue = {
    summary: 'Ship it',
    description: 'Now',
    assignee_id: 'acc-ada',
    assignee_name: 'Ada',
    priority: 'Medium',
    duedate: '2026-12-01',
  };
  assert.deepEqual(changedIssueFields(issue, {
    summary: 'Ship it',
    description: 'Now',
    assignee: 'acc-ada',
    priority: 'High',
    duedate: '2026-12-01',
  }), { priority: 'High' });
  assert.deepEqual(changedIssueFields(issue, {
    summary: 'Ship it',
    description: 'Now',
    assignee: '',
    priority: 'Medium',
    duedate: '',
  }), { assignee: null, duedate: null });
});
