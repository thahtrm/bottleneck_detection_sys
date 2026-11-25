import React, { useState } from 'react';
import { Button, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { completeSprint, createSprint, listProjectIssues, listSprints, rankBacklog, startSprint } from '../../api/client';
import { backlogIssues, issuesForSprint, jiraQueryKeys, openSprints } from '../../dashboard/jiraModel';
import JiraCard from './JiraCard';

function DropLane({ title, meta, over, canDrop, onOver, onLeave, onDrop, empty, children }) {
  return (
    <section
      className="erw-jira-column erw-jira-lane"
      data-over={over ? 'true' : 'false'}
      onDragOver={(event) => {
        if (!canDrop) return;
        event.preventDefault();
        onOver();
      }}
      onDragLeave={onLeave}
      onDrop={onDrop}
    >
      <Group justify="space-between">
        <Text className="erw-settings-label">{title}</Text>
        {meta}
      </Group>
      {empty}
      <Stack gap="xs">{children}</Stack>
    </section>
  );
}

export default function BacklogView({ project, canRank = false, onSelectIssue }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [overLane, setOverLane] = useState(null);
  const [error, setError] = useState('');

  const sprintsQuery = useQuery({
    queryKey: jiraQueryKeys.sprints(project),
    queryFn: () => listSprints(project),
    enabled: Boolean(project),
  });
  const issuesQuery = useQuery({
    queryKey: jiraQueryKeys.issues(project, { scope: 'backlog' }),
    queryFn: () => listProjectIssues({ project }),
    enabled: Boolean(project),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: jiraQueryKeys.root });

  const createMut = useMutation({
    mutationFn: () => createSprint(project, { name: name.trim() }),
    onSuccess: () => {
      setName('');
      setError('');
      refresh();
    },
    onError: (err) => setError(err.message),
  });
  const startMut = useMutation({
    mutationFn: (sprintId) => startSprint(project, sprintId),
    onSuccess: () => {
      setError('');
      refresh();
    },
    onError: (err) => setError(err.message),
  });
  const completeMut = useMutation({
    mutationFn: (sprintId) => completeSprint(project, sprintId),
    onSuccess: () => {
      setError('');
      refresh();
    },
    onError: (err) => setError(err.message),
  });

  if (!project) {
    return <Text className="erw-settings-body">Select a project to open the backlog.</Text>;
  }
  if (sprintsQuery.isLoading || issuesQuery.isLoading) {
    return <Text className="erw-settings-body">Loading the backlog.</Text>;
  }
  if (sprintsQuery.isError || issuesQuery.isError) {
    return <Text className="erw-settings-error">The backlog could not be loaded.</Text>;
  }

  const issues = issuesQuery.data?.issues || [];
  const sprints = openSprints(sprintsQuery.data || []);
  const active = sprints.find((sprint) => sprint.state === 'active');
  const loose = backlogIssues(issues);

  const dropOn = async (event, sprintId) => {
    event.preventDefault();
    setOverLane(null);
    if (!canRank) return;
    const issueKey = event.dataTransfer.getData('text/plain');
    if (!issueKey) return;
    try {
      await rankBacklog(project, { issueKey, sprintId });
      setError('');
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="erw-settings-scope erw-jira-scope">
      <Group justify="space-between" align="flex-end">
        <Title order={3} className="erw-settings-page-title">
          Backlog
        </Title>
        {canRank ? (
          <Group gap="xs">
            <TextInput
              placeholder="Sprint name"
              value={name}
              onChange={(event) => setName(event.currentTarget.value)}
              aria-label="Sprint name"
            />
            <Button
              className="erw-settings-btn-primary"
              disabled={!name.trim()}
              loading={createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              Create sprint
            </Button>
          </Group>
        ) : null}
      </Group>
      {error ? <Text className="erw-settings-error">{error}</Text> : null}
      {!active ? <Text className="erw-settings-body">No active sprint.</Text> : null}
      <Stack gap="md">
        {sprints.map((sprint) => {
          const cards = issuesForSprint(issues, sprint.id);
          return (
            <DropLane
              key={sprint.id}
              title={`${sprint.name} · ${sprint.state}`}
              canDrop={canRank}
              over={overLane === sprint.id}
              onOver={() => canRank && setOverLane(sprint.id)}
              onLeave={() => setOverLane((current) => (current === sprint.id ? null : current))}
              onDrop={(event) => dropOn(event, sprint.id)}
              meta={
                canRank && sprint.state === 'active' ? (
                  <Button
                    className="erw-settings-btn-secondary"
                    size="xs"
                    loading={completeMut.isPending}
                    onClick={() => completeMut.mutate(sprint.id)}
                  >
                    Complete sprint
                  </Button>
                ) : canRank && sprint.state === 'future' ? (
                  <Button
                    className="erw-settings-btn-secondary"
                    size="xs"
                    loading={startMut.isPending}
                    onClick={() => startMut.mutate(sprint.id)}
                  >
                    Start sprint
                  </Button>
                ) : null
              }
              empty={cards.length === 0 ? <Text className="erw-settings-body">This sprint has no issues.</Text> : null}
            >
              {cards.map((issue) => (
                <JiraCard key={issue.key} issue={issue} draggable={canRank} onOpen={onSelectIssue} />
              ))}
            </DropLane>
          );
        })}
        <DropLane
          title="Backlog"
          canDrop={canRank}
          over={overLane === 'backlog'}
          onOver={() => canRank && setOverLane('backlog')}
          onLeave={() => setOverLane((current) => (current === 'backlog' ? null : current))}
          onDrop={(event) => dropOn(event, null)}
          empty={loose.length === 0 ? <Text className="erw-settings-body">The backlog is empty.</Text> : null}
        >
          {loose.map((issue) => (
            <JiraCard key={issue.key} issue={issue} draggable={canRank} onOpen={onSelectIssue} />
          ))}
        </DropLane>
      </Stack>
    </div>
  );
}
