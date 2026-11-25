import React, { useState } from 'react';
import { Group, Select, Table, Text, TextInput } from '@mantine/core';
import { IconCircle, IconFlag, IconListSearch } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { listProjectIssues } from '../../api/client';
import { ISSUE_TYPES, PRIORITIES, jiraQueryKeys } from '../../dashboard/jiraModel';
import AssigneeSelect from './AssigneeSelect';
import { IssueTypeMark, PersonMark, PriorityMark, StatusMark } from './jiraMarks';

export default function IssueNavigator({ project, q = '', onSelectIssue }) {
  const [filters, setFilters] = useState({ status: '', issuetype: '', priority: '', assignee: '' });
  const query = { q, ...filters };

  const issuesQuery = useQuery({
    queryKey: jiraQueryKeys.issues(project, query),
    queryFn: () => listProjectIssues({ project, ...query }),
    enabled: Boolean(project),
  });

  if (!project) {
    return <Text className="erw-settings-body">Select a project to browse issues.</Text>;
  }

  const issues = issuesQuery.data?.issues || [];
  const setFilter = (key) => (value) => setFilters((current) => ({ ...current, [key]: value }));

  return (
    <div className="erw-settings-scope erw-jira-scope">
      <header className="erw-jira-bar">
        <IconListSearch size={16} stroke={1.75} aria-hidden />
        <h2>Issues</h2>
        <span className="erw-jira-count">{issues.length}</span>
      </header>
      <Group gap={6} className="erw-jira-filters" align="center">
        <TextInput
          size="xs"
          placeholder="Status"
          aria-label="Status"
          leftSection={<IconCircle size={14} />}
          value={filters.status}
          onChange={(event) => setFilter('status')(event.currentTarget.value)}
        />
        <Select
          size="xs"
          placeholder="Type"
          aria-label="Type"
          data={ISSUE_TYPES}
          value={filters.issuetype || null}
          onChange={(value) => setFilter('issuetype')(value || '')}
          clearable
        />
        <Select
          size="xs"
          placeholder="Priority"
          aria-label="Priority"
          leftSection={<IconFlag size={14} />}
          data={PRIORITIES}
          value={filters.priority || null}
          onChange={(value) => setFilter('priority')(value || '')}
          clearable
        />
        <AssigneeSelect
          size="xs"
          projectKey={project}
          value={filters.assignee}
          placeholder="Assignee"
          onChange={setFilter('assignee')}
        />
      </Group>
      {issuesQuery.isLoading ? <Text className="erw-settings-body">Loading issues.</Text> : null}
      {issuesQuery.isError ? <Text className="erw-settings-error">Issues could not be loaded.</Text> : null}
      {issuesQuery.isSuccess && issues.length === 0 ? (
        <Text className="erw-jira-empty">No issues match these filters.</Text>
      ) : null}
      {issues.length > 0 ? (
        <div className="erw-jira-table">
          <Table highlightOnHover verticalSpacing={4} horizontalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Key</Table.Th>
                <Table.Th>Summary</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Priority</Table.Th>
                <Table.Th>Assignee</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {issues.map((issue) => (
                <Table.Tr key={issue.key} style={{ cursor: 'pointer' }} onClick={() => onSelectIssue(issue.key)}>
                  <Table.Td><span className="erw-jira-key">{issue.key}</span></Table.Td>
                  <Table.Td>{issue.summary}</Table.Td>
                  <Table.Td>
                    <span className="erw-jira-inline">
                      <IssueTypeMark type={issue.issuetype} />
                      {issue.issuetype}
                    </span>
                  </Table.Td>
                  <Table.Td>
                    <span className="erw-jira-inline">
                      <StatusMark status={issue.status} />
                      {issue.status}
                    </span>
                  </Table.Td>
                  <Table.Td>
                    <span className="erw-jira-inline">
                      <PriorityMark priority={issue.priority} />
                      {issue.priority}
                    </span>
                  </Table.Td>
                  <Table.Td>
                    <span className="erw-jira-inline">
                      <PersonMark name={issue.assignee_name} />
                      {issue.assignee_name || ''}
                    </span>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}
