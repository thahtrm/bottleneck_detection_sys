import React, { useState } from 'react';
import { Group, Text, Title } from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getIssueTransitions, getProjectBoard, transitionIssue } from '../../api/client';
import { jiraQueryKeys, transitionIdForMove } from '../../dashboard/jiraModel';
import JiraCard from './JiraCard';

export default function JiraBoard({ project, canEdit = false, onSelectIssue }) {
  const queryClient = useQueryClient();
  const [overColumn, setOverColumn] = useState(null);
  const [moveError, setMoveError] = useState('');

  const boardQuery = useQuery({
    queryKey: jiraQueryKeys.board(project),
    queryFn: () => getProjectBoard(project),
    enabled: Boolean(project),
  });

  if (!project) {
    return <Text className="erw-settings-body">Select a project to open the Jira board.</Text>;
  }
  if (boardQuery.isLoading) {
    return <Text className="erw-settings-body">Loading the Jira board.</Text>;
  }
  if (boardQuery.isError) {
    return <Text className="erw-settings-error">The Jira board could not be loaded.</Text>;
  }

  const columns = boardQuery.data?.columns || [];

  const onDrop = async (event, column) => {
    event.preventDefault();
    setOverColumn(null);
    if (!canEdit) return;
    const key = event.dataTransfer.getData('text/plain');
    if (!key) return;
    const cards = columns.flatMap((item) => item.issues || []);
    const card = cards.find((item) => item.key === key);
    const target = column.status || column.name;
    if (!card || card.status === target) return;
    try {
      let transitionId = transitionIdForMove(column, []);
      if (!transitionId) {
        const transitions = await getIssueTransitions(key);
        transitionId = transitionIdForMove(column, transitions);
      }
      if (!transitionId) {
        setMoveError(`No transition moves ${key} to ${target}.`);
        return;
      }
      await transitionIssue(key, transitionId);
      setMoveError('');
      queryClient.invalidateQueries({ queryKey: jiraQueryKeys.root });
    } catch (err) {
      setMoveError(err.message);
    }
  };

  return (
    <div className="erw-settings-scope erw-jira-scope">
      <Group justify="space-between">
        <Title order={3} className="erw-settings-page-title">
          Jira board
        </Title>
        <Text className="erw-settings-meta">{project}</Text>
      </Group>
      {moveError ? <Text className="erw-settings-error">{moveError}</Text> : null}
      {columns.length === 0 ? <Text className="erw-settings-body">This project has no workflow columns.</Text> : null}
      <div className="erw-jira-board">
        {columns.map((column) => {
          const name = column.name || column.status;
          return (
            <section
              key={name}
              className="erw-jira-column"
              data-over={overColumn === name ? 'true' : 'false'}
              onDragOver={(event) => {
                if (!canEdit) return;
                event.preventDefault();
                setOverColumn(name);
              }}
              onDragLeave={() => setOverColumn((current) => (current === name ? null : current))}
              onDrop={(event) => onDrop(event, column)}
            >
              <Text className="erw-settings-label">
                {name} ({(column.issues || []).length})
              </Text>
              {(column.issues || []).map((issue) => (
                <JiraCard key={issue.key} issue={issue} draggable={canEdit} onOpen={onSelectIssue} />
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}
