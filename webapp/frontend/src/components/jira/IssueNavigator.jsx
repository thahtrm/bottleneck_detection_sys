import React, { useState } from 'react';
import { Group, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { listProjectIssues } from '../../api/client';
import { ISSUE_TYPES, PRIORITIES, jiraQueryKeys } from '../../dashboard/jiraModel';

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
      <Title order={3} className="erw-settings-page-title">
        Issues
      </Title>
      <Group grow align="flex-end">
        <TextInput
          label="Status"
          value={filters.status}
          onChange={(event) => setFilter('status')(event.currentTarget.value)}
        />
        <Select
          label="Type"
          placeholder="Any"
          data={ISSUE_TYPES}
          value={filters.issuetype || null}
          onChange={(value) => setFilter('issuetype')(value || '')}
          clearable
        />
        <Select
          label="Priority"
          placeholder="Any"
          data={PRIORITIES}
          value={filters.priority || null}
          onChange={(value) => setFilter('priority')(value || '')}
          clearable
        />
        <TextInput
          label="Assignee"
          value={filters.assignee}
          onChange={(event) => setFilter('assignee')(event.currentTarget.value)}
        />
      </Group>
      {issuesQuery.isLoading ? <Text className="erw-settings-body">Loading issues.</Text> : null}
      {issuesQuery.isError ? <Text className="erw-settings-error">Issues could not be loaded.</Text> : null}
      {issuesQuery.isSuccess && issues.length === 0 ? (
        <Text className="erw-settings-body">No issues match these filters.</Text>
      ) : null}
      {issues.length > 0 ? (
        <Stack className="erw-settings-card">
          <Table highlightOnHover>
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
                  <Table.Td>{issue.key}</Table.Td>
                  <Table.Td>{issue.summary}</Table.Td>
                  <Table.Td>{issue.issuetype}</Table.Td>
                  <Table.Td>{issue.status}</Table.Td>
                  <Table.Td>{issue.priority}</Table.Td>
                  <Table.Td>{issue.assignee_name || ''}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      ) : null}
    </div>
  );
}
