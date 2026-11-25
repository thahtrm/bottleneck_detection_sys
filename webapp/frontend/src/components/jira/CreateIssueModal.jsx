import React, { useEffect, useState } from 'react';
import { Button, Checkbox, Group, Modal, Select, Stack, Text, TextInput } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createIssue } from '../../api/client';
import { ISSUE_TYPES, PRIORITIES, jiraQueryKeys } from '../../dashboard/jiraModel';

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
  const projectOptions = projects.map((item) => ({
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
      title="+ Create"
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
            onChange={(value) => setProjectKey(value || '')}
            placeholder="Select a project"
            searchable
          />
        )}
        <TextInput
          label="Summary"
          value={form.summary}
          onChange={(event) => setForm((current) => ({ ...current, summary: event.currentTarget.value }))}
          required
        />
        <Select
          label="Issue type"
          data={ISSUE_TYPES}
          value={form.issuetype}
          onChange={(value) => setForm((current) => ({ ...current, issuetype: value || 'Task' }))}
          allowDeselect={false}
        />
        <Select
          label="Priority"
          data={PRIORITIES}
          value={form.priority}
          onChange={(value) => setForm((current) => ({ ...current, priority: value || 'Medium' }))}
          allowDeselect={false}
        />
        <TextInput
          label="Assignee"
          value={form.assignee}
          onChange={(event) => setForm((current) => ({ ...current, assignee: event.currentTarget.value }))}
          placeholder="Optional name or account"
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
          <Button className="erw-settings-btn-primary" loading={createMut.isPending} onClick={submit}>
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
