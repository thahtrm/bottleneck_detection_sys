import React from 'react';
import { Select } from '@mantine/core';
import { IconUser } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { listProjectMembers } from '../../api/client';

export function memberAccountId(member) {
  return member.account_id || `local-${member.user_id}`;
}

export default function AssigneeSelect({
  projectKey,
  value,
  onChange,
  disabled = false,
  size = 'sm',
  label,
  placeholder = 'Unassigned',
  currentLabel,
}) {
  const membersQuery = useQuery({
    queryKey: ['project-members', projectKey],
    queryFn: () => listProjectMembers(projectKey),
    enabled: Boolean(projectKey),
    staleTime: 30000,
  });
  const data = (membersQuery.data || [])
    .filter((member) => member.is_active !== false)
    .map((member) => ({
      value: memberAccountId(member),
      label: member.name || member.email,
    }));
  if (value && !data.some((item) => item.value === value)) {
    data.unshift({ value, label: currentLabel || value });
  }

  return (
    <Select
      label={label}
      size={size}
      aria-label={label || 'Assignee'}
      placeholder={membersQuery.isLoading ? 'Loading members' : placeholder}
      leftSection={<IconUser size={14} />}
      data={data}
      value={value || null}
      disabled={disabled || !projectKey}
      searchable
      clearable
      nothingFoundMessage="Không có thành viên"
      onChange={(next) => onChange(next || '')}
    />
  );
}
