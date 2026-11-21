import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  Title,
} from '@mantine/core';
import {
  IconAlertCircle,
  IconCheck,
  IconFolders,
  IconMessageCircle,
  IconUsers,
} from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { OpenProjectOnJira } from '../components/JiraLinks';
import MemoryPrefsSection from '../components/settings/MemoryPrefsSection';
import ProjectMembersSection from '../components/settings/ProjectMembersSection';
import { useAuth } from '../context/AuthContext';
import { toggleProjectTracking } from '../api/client';
import '../styles/kaggleTokens.css';

function SettingsCard({ title, icon, children, right }) {
  return (
    <div className="erw-settings-card">
      <Group justify="space-between" align="center" mb="md" wrap="wrap">
        <Group gap="xs">
          {icon}
          <Text className="erw-settings-headline">{title}</Text>
        </Group>
        {right}
      </Group>
      {children}
    </div>
  );
}

export default function ProjectSettings({
  project = '',
  projects = [],
  onOpenSystemSettings,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = Boolean(user?.is_admin);
  const projectMeta = projects.find((item) => item.key === project);
  const projectRole = projectMeta?.role;
  const canManageMembers = Boolean(project) && (isAdmin || projectRole === 'pm');
  const canEditMemory = Boolean(project) && (isAdmin || projectRole === 'pm');
  const [toggling, setToggling] = useState(false);

  const trackMut = useMutation({
    mutationFn: () => toggleProjectTracking(project),
    onMutate: () => setToggling(true),
    onSuccess: (updated) => {
      notifications.show({
        title: 'Cập nhật dự án thành công',
        message: `Dự án ${project} hiện ${updated?.tracked ? 'đang được theo dõi' : 'đã dừng theo dõi'}.`,
        color: 'teal',
        icon: <IconCheck size={18} />,
      });
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-settings'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-board'] }),
      ]);
    },
    onError: (err) => {
      notifications.show({
        title: 'Cập nhật thất bại',
        message: err.message || `Không thể đổi trạng thái theo dõi dự án ${project}.`,
        color: 'red',
        icon: <IconAlertCircle size={18} />,
      });
    },
    onSettled: () => setToggling(false),
  });

  if (!project) {
    return (
      <div className="erw-settings-scope" style={{ maxWidth: 960, margin: '0 auto' }}>
        <Alert icon={<IconAlertCircle size={18} />} color="gray" variant="light" radius="md">
          Chọn dự án trên thanh trên để mở Cài đặt dự án (thành viên, ghi nhớ, theo dõi).
        </Alert>
      </div>
    );
  }

  if (!projectMeta && !isAdmin) {
    return (
      <div className="erw-settings-scope" style={{ maxWidth: 960, margin: '0 auto' }}>
        <Alert icon={<IconAlertCircle size={18} />} color="red" variant="light" radius="md">
          Bạn không có quyền trên dự án {project}.
        </Alert>
      </div>
    );
  }

  const roleLabel = isAdmin ? 'admin' : projectRole || 'viewer';
  const tracked = Boolean(projectMeta?.tracked);

  return (
    <div className="erw-settings-scope" style={{ maxWidth: 960, margin: '0 auto' }}>
      <Stack gap="xl">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={4}>
            <Title order={2} className="erw-settings-page-title">
              Cài đặt dự án
            </Title>
            <Group gap="sm" wrap="wrap">
              <Badge variant="light" color="blue" size="lg">
                {project}
              </Badge>
              <Text className="erw-settings-body" fw={600}>
                {projectMeta?.name || 'Chưa đặt tên'}
              </Text>
              <Badge variant="light" color={roleLabel === 'pm' || roleLabel === 'admin' ? 'dark' : 'gray'}>
                Vai trò: {roleLabel}
              </Badge>
              <OpenProjectOnJira projectKey={project} variant="subtle" px={6}>
                Mở Jira
              </OpenProjectOnJira>
            </Group>
          </Stack>
          {onOpenSystemSettings ? (
            <Button className="erw-settings-btn-secondary" onClick={onOpenSystemSettings}>
              Cài đặt hệ thống
            </Button>
          ) : null}
        </Group>

        <SettingsCard title="Thành viên dự án" icon={<IconUsers size={22} color="var(--color-secondary)" />}>
          <ProjectMembersSection project={project} canManage={canManageMembers} />
        </SettingsCard>

        {(canEditMemory || projectRole === 'viewer') && (
          <SettingsCard title="Ghi nhớ chat" icon={<IconMessageCircle size={22} color="var(--color-secondary)" />}>
            {canEditMemory ? (
              <MemoryPrefsSection project={project} />
            ) : (
              <Text className="erw-settings-meta">
                Ghi nhớ chỉ chỉnh được khi bạn là PM (hoặc Admin) trên dự án này.
              </Text>
            )}
          </SettingsCard>
        )}

        {isAdmin && (
          <SettingsCard title="Theo dõi dự án" icon={<IconFolders size={22} color="var(--color-secondary)" />}>
            <Stack gap="sm">
              <Text className="erw-settings-body">
                Chỉ dự án tracked nhận webhook, tính rủi ro và xuất hiện trong bộ lọc.
              </Text>
              {projectMeta ? (
                <Switch
                  checked={tracked}
                  onChange={() => trackMut.mutate()}
                  disabled={toggling || trackMut.isPending}
                  color="blue"
                  size="md"
                  label={tracked ? 'Đang theo dõi' : 'Tạm dừng theo dõi'}
                  description={toggling ? 'Đang cập nhật…' : undefined}
                />
              ) : (
                <Group gap="sm">
                  <Loader size="sm" type="dots" />
                  <Text className="erw-settings-meta">Đang tải thông tin dự án…</Text>
                </Group>
              )}
            </Stack>
          </SettingsCard>
        )}
      </Stack>
    </div>
  );
}
