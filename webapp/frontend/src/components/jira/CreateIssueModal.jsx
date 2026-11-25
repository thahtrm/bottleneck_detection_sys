import React, { useEffect, useState } from 'react';
import { Button, Checkbox, Group, Modal, Select, Stack, Text, TextInput } from '@mantine/core';
import { IconFlag, IconPlus } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createIssue } from '../../api/client';
import { ISSUE_TYPES, PRIORITIES, jiraQueryKeys } from '../../dashboard/jiraModel';
import AssigneeSelect from './AssigneeSelect';
import { IssueTypeMark } from './jiraMarks';

const EMPTY = { summary: '', issuetype: 'Task', priority: 'Medium', assignee: '' };

export default function CreateIssueModal({ opened, onClose, project = '', projects = [] }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [projectKey, setProjectKey] = useState(project);
  const [createAnother, setCreateAnother] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!opened) return;
    setProjectKey(project);
    setError('');
    setNotice('');
  }, [opened, project]);

  const activeProject = project || projectKey;
  const projectOptions = projects
    .filter((item) => item.origin !== 'jira')
    .map((item) => ({
      value: item.key,
      label: item.name ? `${item.key} — ${item.name}` : item.key,
    }));

  const createMut = useMutation({
    mutationFn: createIssue,
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: jiraQueryKeys.root });
      setError('');
      if (createAnother) {
        setForm((current) => ({ ...current, summary: '' }));
        setNotice(created?.key ? `Created ${created.key}.` : 'Created the issue.');
        return;
      }
      setForm(EMPTY);
      setNotice('');
      onClose();
    },
    onError: (err) => {
      setNotice('');
      setError(err.message || 'Could not create the issue.');
    },
  });

  const submit = () => {
    setError('');
    if (!activeProject) {
      setError('Select a project before creating an issue.');
      return;
    }
    if (!form.summary.trim()) {
      setError('Summary is required.');
      return;
    }
    const body = {
      project_key: activeProject,
      summary: form.summary.trim(),
      issuetype: form.issuetype,
      priority: form.priority,
    };
    if (form.assignee.trim()) body.assignee = form.assignee.trim();
    createMut.mutate(body);
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={(
        <Group gap={6}>
          <IconPlus size={16} />
          <span>Create issue</span>
        </Group>
      )}
      centered
    >
      <Stack gap="sm" className="erw-settings-scope">
        {project ? (
          <Text className="erw-settings-body">Project {project}</Text>
        ) : (
          <Select
            label="Project"
            data={projectOptions}
            value={projectKey || null}
            onChange={(value) => {
              setProjectKey(value || '');
              setForm((current) => ({ ...current, assignee: '' }));
            }}
            placeholder="Select a project"
            searchable
          />
        )}
        <TextInput
          label="Summary"
          size="sm"
          value={form.summary}
          onChange={(event) => setForm((current) => ({ ...current, summary: event.currentTarget.value }))}
          required
        />
        <Group grow>
          <Select
            label="Issue type"
            size="sm"
            leftSection={<IssueTypeMark type={form.issuetype} />}
            data={ISSUE_TYPES}
            value={form.issuetype}
            onChange={(value) => setForm((current) => ({ ...current, issuetype: value || 'Task' }))}
            allowDeselect={false}
          />
          <Select
            label="Priority"
            size="sm"
            leftSection={<IconFlag size={14} />}
            data={PRIORITIES}
            value={form.priority}
            onChange={(value) => setForm((current) => ({ ...current, priority: value || 'Medium' }))}
            allowDeselect={false}
          />
        </Group>
        <AssigneeSelect
          label="Assignee"
          projectKey={activeProject}
          value={form.assignee}
          onChange={(assignee) => setForm((current) => ({ ...current, assignee }))}
        />
        <Checkbox
          label="Create another"
          checked={createAnother}
          onChange={(event) => setCreateAnother(event.currentTarget.checked)}
        />
        {error ? <Text className="erw-settings-error">{error}</Text> : null}
        {notice ? <Text className="erw-settings-meta">{notice}</Text> : null}
        <Group justify="flex-end">
          <Button className="erw-settings-btn-secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button className="erw-settings-btn-primary" leftSection={<IconPlus size={14} />} loading={createMut.isPending} onClick={submit}>
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
