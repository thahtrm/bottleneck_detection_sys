import React, { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconCopy, IconPlus, IconRefresh, IconSearch, IconUsers } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { createAdminUser, listAdminUsers, patchAdminUser, resetDemo } from '../api/client';
import { useAuth } from '../context/AuthContext';
import '../styles/kaggleTokens.css';

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    notifications.show({ color: 'teal', message: 'Đã sao chép mật khẩu tạm.' });
  } catch {
    notifications.show({ color: 'red', message: 'Không sao chép được — hãy chọn và copy thủ công.' });
  }
}

function PasswordReveal({ password, onClose }) {
  if (!password) return null;
  return (
    <Stack gap="sm" className="erw-settings-field">
      <Text className="erw-settings-label">Mật khẩu tạm (chỉ hiện một lần)</Text>
      <Group wrap="nowrap" gap="sm">
        <Text ff="monospace" fw={600} style={{ flex: 1, wordBreak: 'break-all' }}>
          {password}
        </Text>
        <Button className="erw-settings-btn-secondary" leftSection={<IconCopy size={16} />} onClick={() => copyText(password)}>
          Sao chép
        </Button>
      </Group>
      {onClose ? (
        <Button className="erw-settings-btn-primary" onClick={onClose}>
          Đã lưu mật khẩu
        </Button>
      ) : null}
    </Stack>
  );
}

export default function UsersAdmin() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [q, setQ] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [createForm, setCreateForm] = useState({ email: '', name: '', is_admin: false });
  const [editForm, setEditForm] = useState({ name: '', is_admin: false, is_active: true });
  const [revealedPassword, setRevealedPassword] = useState(null);

  const usersQuery = useQuery({
    queryKey: ['admin-users', q],
    queryFn: () => listAdminUsers(q),
    enabled: Boolean(user?.is_admin),
  });

  const createMut = useMutation({
    mutationFn: createAdminUser,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      setCreateOpen(false);
      setCreateForm({ email: '', name: '', is_admin: false });
      setRevealedPassword(data.generated_password);
      notifications.show({ color: 'teal', message: 'Đã tạo người dùng.' });
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  });

  const resetMut = useMutation({
    mutationFn: resetDemo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['jira'] });
      queryClient.invalidateQueries({ queryKey: ['issue-detail'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-board'] });
      notifications.show({ color: 'teal', message: 'Demo data was reset.' });
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  });

  const patchMut = useMutation({
    mutationFn: ({ id, patch }) => patchAdminUser(id, patch),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      if (data.generated_password) setRevealedPassword(data.generated_password);
      setEditUser(null);
      notifications.show({ color: 'teal', message: 'Đã cập nhật người dùng.' });
    },
    onError: (error) => notifications.show({ color: 'red', message: error.message }),
  });

  const rows = useMemo(() => usersQuery.data || [], [usersQuery.data]);

  if (!user?.is_admin) {
    return (
      <div className="erw-settings-scope">
        <Text className="erw-settings-body">Chỉ Admin mới quản lý người dùng hệ thống.</Text>
      </div>
    );
  }

  return (
    <div className="erw-settings-scope" style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Stack gap="lg">
        <Group justify="space-between" wrap="wrap">
          <Group gap="sm">
            <IconUsers size={24} color="var(--color-secondary)" />
            <Title order={2} className="erw-settings-page-title">
              Người dùng
            </Title>
          </Group>
          <Group gap="sm">
            <Button
              className="erw-settings-btn-secondary"
              size="xs"
              leftSection={<IconRefresh size={14} />}
              loading={resetMut.isPending}
              onClick={() => {
                if (!window.confirm('Reset demo data? This replaces the current demo project and issues.')) return;
                resetMut.mutate();
              }}
            >
              Reset demo
            </Button>
            <Button
              className="erw-settings-btn-primary"
              leftSection={<IconPlus size={16} />}
              onClick={() => setCreateOpen(true)}
            >
              Thêm người dùng
            </Button>
          </Group>
        </Group>

        <TextInput
          className="erw-settings-input"
          placeholder="Tìm theo email hoặc tên..."
          leftSection={<IconSearch size={16} />}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
        />

        {revealedPassword ? <PasswordReveal password={revealedPassword} onClose={() => setRevealedPassword(null)} /> : null}

        <div className="erw-settings-card">
          {usersQuery.isLoading ? (
            <Loader size="sm" type="dots" />
          ) : usersQuery.isError ? (
            <Text className="erw-settings-error">{usersQuery.error.message}</Text>
          ) : (
            <Table.ScrollContainer minWidth={720}>
              <Table verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Email</Table.Th>
                    <Table.Th>Tên</Table.Th>
                    <Table.Th>Quyền</Table.Th>
                    <Table.Th>Trạng thái</Table.Th>
                    <Table.Th>Dự án</Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((row) => (
                    <Table.Tr key={row.id}>
                      <Table.Td>
                        <Text size="sm" ff="monospace">
                          {row.email}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" fw={500}>
                          {row.name}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {row.is_admin ? (
                          <Badge color="dark" variant="light">
                            Admin
                          </Badge>
                        ) : (
                          <Badge color="gray" variant="light">
                            User
                          </Badge>
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
                      <Table.Td>
                        <Text size="sm">{row.project_count}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          onClick={() => {
                            setEditUser(row);
                            setEditForm({
                              name: row.name,
                              is_admin: row.is_admin,
                              is_active: row.is_active,
                            });
                          }}
                        >
                          Sửa
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </div>
      </Stack>

      <Modal opened={createOpen} onClose={() => setCreateOpen(false)} title="Thêm người dùng" centered>
        <Stack gap="md">
          <TextInput
            label="Email"
            value={createForm.email}
            onChange={(e) => setCreateForm((prev) => ({ ...prev, email: e.currentTarget.value }))}
          />
          <TextInput
            label="Tên"
            value={createForm.name}
            onChange={(e) => setCreateForm((prev) => ({ ...prev, name: e.currentTarget.value }))}
          />
          <Switch
            label="Admin hệ thống"
            checked={createForm.is_admin}
            onChange={(e) => setCreateForm((prev) => ({ ...prev, is_admin: e.currentTarget.checked }))}
          />
          <Text className="erw-settings-meta">Mật khẩu tạm sẽ được tạo tự động — hãy sao chép ngay.</Text>
          <Button
            className="erw-settings-btn-primary"
            loading={createMut.isPending}
            onClick={() => createMut.mutate(createForm)}
          >
            Tạo
          </Button>
        </Stack>
      </Modal>

      <Modal opened={Boolean(editUser)} onClose={() => setEditUser(null)} title="Sửa người dùng" centered>
        {editUser ? (
          <Stack gap="md">
            <Text size="sm" c="dimmed">
              {editUser.email}
            </Text>
            <TextInput
              label="Tên"
              value={editForm.name}
              onChange={(e) => setEditForm((prev) => ({ ...prev, name: e.currentTarget.value }))}
            />
            <Switch
              label="Admin hệ thống"
              checked={editForm.is_admin}
              onChange={(e) => setEditForm((prev) => ({ ...prev, is_admin: e.currentTarget.checked }))}
            />
            <Switch
              label="Đang hoạt động"
              checked={editForm.is_active}
              onChange={(e) => setEditForm((prev) => ({ ...prev, is_active: e.currentTarget.checked }))}
            />
            <Group>
              <Button
                className="erw-settings-btn-primary"
                loading={patchMut.isPending}
                onClick={() =>
                  patchMut.mutate({
                    id: editUser.id,
                    patch: {
                      name: editForm.name,
                      is_admin: editForm.is_admin,
                      is_active: editForm.is_active,
                    },
                  })
                }
              >
                Lưu
              </Button>
              <Button
                className="erw-settings-btn-secondary"
                leftSection={<IconRefresh size={16} />}
                loading={patchMut.isPending}
                onClick={() => patchMut.mutate({ id: editUser.id, patch: { reset_password: true } })}
              >
                Đặt lại mật khẩu
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
    </div>
  );
}
