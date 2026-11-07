import assert from 'node:assert/strict';
import test from 'node:test';
import { jiraIssueUrl, jiraProjectUrl } from './jiraLinks.js';

test('jira issue url points at browse', () => {
  assert.equal(
    jiraIssueUrl('https://example.atlassian.net/', 'DEMO-12'),
    'https://example.atlassian.net/browse/DEMO-12',
  );
});

test('jira project url points at the software project', () => {
  assert.equal(
    jiraProjectUrl('https://example.atlassian.net', 'DEMO'),
    'https://example.atlassian.net/jira/software/projects/DEMO',
  );
});

test('missing base or key yields no url', () => {
  assert.equal(jiraIssueUrl('', 'DEMO-1'), null);
  assert.equal(jiraProjectUrl('https://example.atlassian.net', ''), null);
});
