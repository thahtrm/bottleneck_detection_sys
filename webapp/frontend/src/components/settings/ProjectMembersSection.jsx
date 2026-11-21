import React, { useState } from 'react';
import { Badge, Button, Group, Loader, Select, Stack, Table, Text, TextInput } from '@mantine/core';
import { IconTrash, IconUserPlus } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import {
  addProjectMember,
  listProjectMembers,
  patchProjectMember,
  removeProjectMember,
} from '../../api/client';

const ROLE_OPTIONS = [
  { value: 'pm', label: 'PM' },
  { value: 'viewer', label: 'Viewer' },
];

export default function ProjectMembersSection({ project, canManage }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('viewer');

  const membersQuery = useQuery({
    queryKey: ['project-members', project],
    queryFn: () => listProjectMembers(project),
    enabled: Boolean(project),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['project-members', project] });

  const addMut = useMutation({
    mutationFn: () => addProjectMember(project, { email: email.trim(), role }),
    onSuccess: () => {
      setEmail('');
      setRole('viewer');
      invalidate();
      notifications.show({ color: 'teal', message: 'Đã thêm thành viên.' });
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  });

  const roleMut = useMutation({
    mutationFn: ({ userId, nextRole }) => patchProjectMember(project, userId, { role: nextRole }),
    onSuccess: () => {
      invalidate();
      notifications.show({ color: 'teal', message: 'Đã đổi vai trò.' });
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  });

  const removeMut = useMutation({
    mutationFn: (userId) => removeProjectMember(project, userId),
    onSuccess: () => {
      invalidate();
      notifications.show({ color: 'teal', message: 'Đã gỡ thành viên.' });
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  });

  if (!project) {
    return <Text className="erw-settings-meta">Chọn dự án trên thanh trên để xem / quản lý thành viên.</Text>;
  }

  if (membersQuery.isLoading) return <Loader size="sm" type="dots" />;
  if (membersQuery.isError) return <Text className="erw-settings-error">{membersQuery.error.message}</Text>;

  const rows = membersQuery.data || [];

  return (
    <Stack gap="md">
      {canManage ? (
        <Group align="flex-end" wrap="wrap" gap="sm">
          <TextInput
            className="erw-settings-input"
            label="Email người dùng đã có"
            placeholder="user@example.com"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            style={{ flex: '1 1 220px' }}
          />
          <Select
            label="Vai trò"
            data={ROLE_OPTIONS}
            value={role}
            onChange={(value) => setRole(value || 'viewer')}
            allowDeselect={false}
            w={140}
          />
          <Button
            className="erw-settings-btn-primary"
            leftSection={<IconUserPlus size={16} />}
            loading={addMut.isPending}
            onClick={() => addMut.mutate()}
            disabled={!email.trim()}
          >
            Thêm
          </Button>
        </Group>
      ) : (
        <Text className="erw-settings-meta">Bạn đang xem danh sách thành viên (chỉ đọc).</Text>
      )}

      <Table.ScrollContainer minWidth={520}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Email</Table.Th>
              <Table.Th>Tên</Table.Th>
              <Table.Th>Vai trò</Table.Th>
              <Table.Th>Trạng thái</Table.Th>
              {canManage ? <Table.Th /> : null}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.user_id}>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {row.email}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{row.name}</Text>
                </Table.Td>
                <Table.Td>
                  {canManage ? (
                    <Select
                      size="xs"
                      data={ROLE_OPTIONS}
                      value={row.role}
                      allowDeselect={false}
                      onChange={(value) => {
                        if (value && value !== row.role) {
                          roleMut.mutate({ userId: row.user_id, nextRole: value });
                        }
                      }}
                      w={120}
                    />
                  ) : (
                    <Badge variant="light">{row.role}</Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  {row.is_active ? (
                    <Badge color="teal" variant="light">
                      Active
                    </Badge>
                  ) : (
                    <Badge color="red" variant="light">
                      Disabled
                    </Badge>
                  )}
                </Table.Td>
                {canManage ? (
                  <Table.Td>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="red"
                      leftSection={<IconTrash size={14} />}
                      loading={removeMut.isPending}
                      onClick={() => removeMut.mutate(row.user_id)}
                    >
                      Gỡ
                    </Button>
                  </Table.Td>
                ) : null}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}
