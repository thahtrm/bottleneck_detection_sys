import React, { useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Select,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import {
  IconArrowLeft,
  IconCalendar,
  IconFlag,
  IconMessage,
  IconSend,
} from '@tabler/icons-react';
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
import AssigneeSelect from './AssigneeSelect';
import { IssueTypeMark, PersonMark, StatusMark } from './jiraMarks';

function draftFromIssue(issue) {
  return {
    summary: issue.summary || '',
    description: issueDescription(issue),
    assignee: issue.assignee_id || issue.assignee_name || '',
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
      <header className="erw-jira-bar">
        <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Back" onClick={onClose}>
          <IconArrowLeft size={16} />
        </ActionIcon>
        <IssueTypeMark type={issue.issuetype} />
        <span className="erw-jira-key">{issue.key}</span>
        <span className="erw-jira-inline">
          <StatusMark status={issue.status} />
          {issue.status || 'No status'}
        </span>
      </header>
      {error ? <Text className="erw-settings-error">{error}</Text> : null}
      <div className="erw-jira-detail">
        <div className="erw-jira-detail-main">
          <TextInput
            size="sm"
            aria-label="Summary"
            value={draft.summary}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, summary: event.currentTarget.value }))}
          />
          <Textarea
            size="sm"
            aria-label="Description"
            placeholder="Description"
            minRows={4}
            autosize
            maxRows={10}
            value={draft.description}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, description: event.currentTarget.value }))}
          />
          <div className="erw-jira-comments">
            <span className="erw-jira-inline erw-settings-meta">
              <IconMessage size={14} />
              Comments
            </span>
            {commentsQuery.isError ? <Text className="erw-settings-error">Comments could not be loaded.</Text> : null}
            {commentsQuery.isSuccess && comments.length === 0 ? (
              <Text className="erw-jira-empty">No comments yet.</Text>
            ) : null}
            {comments.map((item) => (
              <div key={item.id} className="erw-jira-comment">
                <PersonMark name={item.author_name} />
                <div>
                  <Text className="erw-settings-meta">{item.author_name || 'Someone'}</Text>
                  <Text className="erw-settings-body">{item.body}</Text>
                </div>
              </div>
            ))}
          </div>
          <Group gap={6} align="flex-end" wrap="nowrap">
            <Textarea
              style={{ flex: 1 }}
              size="xs"
              aria-label="Comment"
              placeholder="Comment"
              minRows={1}
              autosize
              maxRows={4}
              value={comment}
              disabled={!canEdit}
              onChange={(event) => setComment(event.currentTarget.value)}
            />
            <ActionIcon
              variant="filled"
              color="dark"
              size="lg"
              aria-label="Comment"
              disabled={!canEdit || !comment.trim()}
              loading={commentMut.isPending}
              onClick={() => commentMut.mutate(comment.trim())}
            >
              <IconSend size={16} />
            </ActionIcon>
          </Group>
        </div>
        <aside className="erw-jira-detail-side">
          {canEdit ? (
            <Select
              size="xs"
              aria-label="Transition"
              placeholder="Move status"
              leftSection={<StatusMark status={issue.status} />}
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
          <AssigneeSelect
            size="xs"
            projectKey={issue.project_key}
            value={draft.assignee}
            currentLabel={issue.assignee_name}
            disabled={!canEdit}
            onChange={(assignee) => setDraft((current) => ({ ...current, assignee }))}
          />
          <Select
            size="xs"
            aria-label="Priority"
            leftSection={<IconFlag size={14} />}
            data={priorityData}
            value={draft.priority}
            disabled={!canEdit}
            allowDeselect={false}
            onChange={(value) => setDraft((current) => ({ ...current, priority: value || current.priority }))}
          />
          <TextInput
            size="xs"
            aria-label="Due date"
            type="date"
            leftSection={<IconCalendar size={14} />}
            value={draft.duedate}
            disabled={!canEdit}
            onChange={(event) => setDraft((current) => ({ ...current, duedate: event.currentTarget.value }))}
          />
          {canEdit ? (
            <Button size="xs" className="erw-settings-btn-primary" loading={saveMut.isPending} onClick={save}>
              Save
            </Button>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
