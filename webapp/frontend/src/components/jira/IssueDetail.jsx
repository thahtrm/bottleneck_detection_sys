import React, { useState } from 'react';
import {
  Button,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  addIssueComment,
  getIssueActivity,
  getIssueDetail,
  getIssueTransitions,
  patchIssue,
  transitionIssue,
} from '../../api/client';
import {
  PRIORITIES,
  changedIssueFields,
  issueDescription,
  jiraQueryKeys,
} from '../../dashboard/jiraModel';

function draftFromIssue(issue) {
  return {
    summary: issue.summary || '',
    description: issueDescription(issue),
    assignee: issue.assignee_name || issue.assignee_id || '',
    priority: issue.priority || 'Medium',
    duedate: (issue.duedate || '').slice(0, 10),
  };
}

export default function IssueDetail({ issueKey, canEdit = false, onClose }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(null);
  const [comment, setComment] = useState('');
  const [error, setError] = useState('');

  const detailQuery = useQuery({
    queryKey: jiraQueryKeys.issue(issueKey),
    queryFn: () => getIssueDetail(issueKey),
    enabled: Boolean(issueKey),
  });
  const transitionsQuery = useQuery({
    queryKey: jiraQueryKeys.transitions(issueKey),
    queryFn: () => getIssueTransitions(issueKey),
    enabled: Boolean(issueKey) && canEdit,
  });
  const commentsQuery = useQuery({
    queryKey: jiraQueryKeys.comments(issueKey),
    queryFn: () => getIssueActivity(issueKey, 'comments'),
    enabled: Boolean(issueKey),
  });

  const issue = detailQuery.data?.issue;
  const stamp = issue ? `${issue.key}|${issue.updated_at || ''}` : '';
  const [stampSeen, setStampSeen] = useState('');
  if (issue && stamp !== stampSeen) {
    setStampSeen(stamp);
    setDraft(draftFromIssue(issue));
  }

  const refreshIssue = () => {
    queryClient.invalidateQueries({ queryKey: jiraQueryKeys.root });
    queryClient.invalidateQueries({ queryKey: ['issue-detail', issueKey] });
  };

  const saveMut = useMutation({
    mutationFn: (fields) => patchIssue(issueKey, { fields, expectedUpdated: issue?.updated_at || null }),
    onSuccess: () => {
      setError('');
      refreshIssue();
    },
    onError: (err) => {
      setError(err.status === 409 ? 'Someone else updated this issue.' : err.message);
      if (err.status === 409) refreshIssue();
    },
  });

  const transitionMut = useMutation({
    mutationFn: (transitionId) => transitionIssue(issueKey, transitionId),
    onSuccess: () => {
      setError('');
      refreshIssue();
    },
    onError: (err) => setError(err.message),
  });

  const commentMut = useMutation({
    mutationFn: (body) => addIssueComment(issueKey, body),
    onSuccess: () => {
      setComment('');
      setError('');
      queryClient.invalidateQueries({ queryKey: jiraQueryKeys.comments(issueKey) });
    },
    onError: (err) => setError(err.message),
  });

  if (detailQuery.isLoading) {
    return <Text className="erw-settings-body">Loading this issue.</Text>;
  }
  if (detailQuery.isError || !issue) {
    return <Text className="erw-settings-error">This issue could not be loaded.</Text>;
  }
  if (!draft) {
    return <Text className="erw-settings-body">Loading this issue.</Text>;
  }

  const priorityData = PRIORITIES.includes(draft.priority) ? PRIORITIES : [draft.priority, ...PRIORITIES];
  const transitionData = (transitionsQuery.data || []).map((row) => ({
    value: String(row.id),
    label: row.name ? `${row.name} (${row.to_status})` : row.to_status,
  }));
  const comments = (commentsQuery.data?.items || []).filter((item) => item.kind === 'comment' || item.body);

  const save = () => {
    const fields = changedIssueFields(issue, draft);
    if (Object.keys(fields).length === 0) return;
    saveMut.mutate(fields);
  };

  return (
    <div className="erw-settings-scope erw-jira-scope">
      <Group justify="space-between">
        <Title order={2} className="erw-settings-page-title">
          {issue.key}
        </Title>
        <Button className="erw-settings-btn-secondary" onClick={onClose}>
          Back
        </Button>
      </Group>
      {error ? <Text className="erw-settings-error">{error}</Text> : null}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <Stack gap="sm">
          <TextInput
            label="Summary"
            value={draft.summary}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, summary: event.currentTarget.value }))}
          />
          <Textarea
            label="Description"
            minRows={8}
            value={draft.description}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, description: event.currentTarget.value }))}
          />
          <Stack gap="xs">
            {commentsQuery.isError ? <Text className="erw-settings-error">Comments could not be loaded.</Text> : null}
            {commentsQuery.isSuccess && comments.length === 0 ? (
              <Text className="erw-settings-body">No comments yet.</Text>
            ) : null}
            {comments.map((item) => (
              <div key={item.id} className="erw-settings-field">
                <Text className="erw-settings-meta">{item.author_name || 'Someone'}</Text>
                <Text className="erw-settings-body">{item.body}</Text>
              </div>
            ))}
          </Stack>
          <Textarea
            label="Comment"
            minRows={3}
            value={comment}
            disabled={!canEdit}
            onChange={(event) => setComment(event.currentTarget.value)}
          />
          <Group>
            <Button
              className="erw-settings-btn-secondary"
              disabled={!canEdit || !comment.trim()}
              loading={commentMut.isPending}
              onClick={() => commentMut.mutate(comment.trim())}
            >
              Comment
            </Button>
          </Group>
        </Stack>
        <Stack gap="sm">
          <Text className="erw-settings-label">Status</Text>
          <Text className="erw-settings-body">{issue.status || 'No status'}</Text>
          {canEdit ? (
            <Select
              label="Transition"
              placeholder="Move to a status"
              data={transitionData}
              value={null}
              disabled={transitionsQuery.isError || transitionData.length === 0}
              onChange={(value) => {
                if (value) transitionMut.mutate(value);
              }}
            />
          ) : null}
          {transitionsQuery.isError ? (
            <Text className="erw-settings-error">Transitions could not be loaded.</Text>
          ) : null}
          <TextInput
            label="Assignee"
            value={draft.assignee}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, assignee: event.currentTarget.value }))}
          />
          <Select
            label="Priority"
            data={priorityData}
            value={draft.priority}
            disabled={!canEdit}
            allowDeselect={false}
            onChange={(value) => setDraft((current) => ({ ...current, priority: value || current.priority }))}
          />
          <TextInput
            label="Due date"
            type="date"
            value={draft.duedate}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, duedate: event.currentTarget.value }))}
          />
          {canEdit ? (
            <Button className="erw-settings-btn-primary" loading={saveMut.isPending} onClick={save}>
              Save
            </Button>
          ) : null}
        </Stack>
      </SimpleGrid>
    </div>
  );
}
