import React from 'react';
import {
  Group,
  Select,
  TextInput,
  ActionIcon,
  Tooltip,
  Badge,
  Text,
  Button,
  Box,
} from '@mantine/core';
import {
  IconSearch,
  IconRefresh,
  IconUser,
  IconLogout,
  IconX,
  IconMenu2,
} from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import { getAdminSettings, listDemoUsers, quickSwitch } from '../api/client';
import { OpenProjectIcon } from './JiraLinks';
import AppLogo from './brand/AppLogo';

/**
 * Format thời gian webhook ISO thành chuỗi hiển thị thân thiện tiếng Việt
 */
function formatWebhookTime(isoString) {
  if (!isoString) return 'Chưa nhận webhook nào';
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoString;
  }
}

export default function Header({
  projects = [],
  selectedProject = '',
  onSelectProject,
  searchQuery = '',
  onSearchChange,
  onRefresh,
  isRefreshing = false,
  mobileNavOpened = false,
  onToggleMobileNav,
  onCreate,
}) {
  const { user, logout, refresh } = useAuth();
  const queryClient = useQueryClient();

  // Chỉ gọi getAdminSettings nếu người dùng có quyền admin
  const { data: adminSettings } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: getAdminSettings,
    enabled: Boolean(user?.is_admin),
    refetchInterval: 30000,
    staleTime: 10000,
  });

  const jiraLocal = user?.jira_mode === 'local' || adminSettings?.jira_mode === 'local';
  const demoUsers = useQuery({
    queryKey: ['demo-users'],
    queryFn: listDemoUsers,
    enabled: jiraLocal,
  });
  const switchMut = useMutation({
    mutationFn: (userId) => quickSwitch(userId),
    onSuccess: async () => {
      await refresh();
      await queryClient.invalidateQueries();
    },
  });
  const userOptions = (demoUsers.data || []).map((item) => ({
    value: String(item.id),
    label: item.name || item.email,
  }));
  const currentUserId = user?.id != null ? String(user.id) : null;
  const switchValue = userOptions.some((item) => item.value === currentUserId) ? currentUserId : null;

  // Chuẩn bị danh sách option cho Select dự án
  const projectOptions = [
    { value: '', label: 'Tất cả dự án' },
    ...projects.map((p) => {
      const key = p.key || p.id || '';
      const name = p.name ? `${key} - ${p.name}` : key;
      return { value: key, label: name };
    }),
  ];

  // Trạng thái hiển thị webhook
  let webhookTooltip = 'Hệ thống đang hoạt động bình thường';
  let webhookLabel = 'Hệ thống: Trực tuyến';

  if (user?.is_admin) {
    if (adminSettings?.last_webhook_at) {
      webhookTooltip = `Webhook cuối: ${formatWebhookTime(adminSettings.last_webhook_at)}`;
      webhookLabel = 'Webhook: Trực tuyến';
    } else {
      webhookTooltip = 'Chưa nhận sự kiện webhook Jira nào gần đây';
      webhookLabel = 'Webhook: Sẵn sàng';
    }
  }

  // Nhãn vai trò người dùng
  const roleLabel = user?.is_admin ? 'Admin' : 'PM / Viewer';
  const roleColor = user?.is_admin ? 'dark' : 'blue';

  return (
    <Group h="100%" px="md" gap="sm" justify="space-between" wrap="nowrap" style={{ minWidth: 0 }}>
      {/* Khối bên trái: hamburger (mobile) + Logo + Chọn dự án */}
      <Group gap="sm" wrap="nowrap" style={{ flex: '1 1 auto' }}>
        <Tooltip
          label={mobileNavOpened ? 'Đóng menu' : 'Mở menu'}
          withArrow
          position="bottom"
        >
          <ActionIcon
            hiddenFrom="md"
            variant="subtle"
            color="gray"
            size="lg"
            radius="md"
            aria-label={mobileNavOpened ? 'Đóng menu điều hướng' : 'Mở menu điều hướng'}
            aria-expanded={mobileNavOpened}
            onClick={onToggleMobileNav}
          >
            {mobileNavOpened ? <IconX size={20} stroke={1.5} /> : <IconMenu2 size={20} stroke={1.5} />}
          </ActionIcon>
        </Tooltip>

        <Box hiddenFrom="xl" style={{ flexShrink: 0 }}>
          <AppLogo variant="mark" size="md" />
        </Box>
        <Box visibleFrom="xl" style={{ flexShrink: 0 }}>
          <AppLogo variant="mark" size="md" showTitle />
        </Box>

        <Select
          data={projectOptions}
          value={selectedProject || ''}
          onChange={(val) => onSelectProject && onSelectProject(val || '')}
          placeholder="Chọn dự án"
          size="sm"
          miw={120}
          maw={230}
          style={{ flex: '1 1 160px' }}
          allowDeselect={false}
          checkIconPosition="right"
          aria-label="Chọn dự án theo dõi"
        />
        {selectedProject ? <OpenProjectIcon projectKey={selectedProject} /> : null}
      </Group>

      {/* Khối ở giữa: Tìm kiếm nhanh */}
      <Box style={{ flex: '1 1 160px', minWidth: 96, maxWidth: 360 }}>
        <TextInput
          placeholder="Tìm task theo key hoặc tóm tắt..."
          leftSection={<IconSearch size={16} stroke={1.5} />}
          value={searchQuery || ''}
          onChange={(e) => onSearchChange && onSearchChange(e.currentTarget.value)}
          rightSection={
            searchQuery ? (
              <ActionIcon
                size="xs"
                variant="subtle"
                color="gray"
                onClick={() => onSearchChange && onSearchChange('')}
                aria-label="Xóa nội dung tìm kiếm"
              >
                <IconX size={12} stroke={1.5} />
              </ActionIcon>
            ) : null
          }
          size="sm"
          aria-label="Tìm kiếm nhanh công việc"
        />
      </Box>

      {/* Khối bên phải: Nút Refresh + Webhook status + User Menu */}
      <Group gap="sm" wrap="nowrap" style={{ flexShrink: 0 }}>
        {jiraLocal ? (
          <Select
            aria-label="Switch user"
            data={userOptions}
            value={switchValue}
            onChange={(value) => {
              if (!value || value === currentUserId) return;
              switchMut.mutate(Number(value));
            }}
            placeholder="Switch user"
            searchable
            size="sm"
            maw={180}
            allowDeselect={false}
            disabled={switchMut.isPending}
            error={
              switchMut.isError
                ? switchMut.error.message
                : demoUsers.isError
                  ? 'Demo users could not be loaded.'
                  : undefined
            }
          />
        ) : null}
        {jiraLocal && onCreate ? (
          <Button size="sm" color="dark" onClick={onCreate}>
            + Create
          </Button>
        ) : null}
        <Tooltip label="Làm mới dữ liệu" withArrow position="bottom">
          <ActionIcon
            variant="light"
            color="blue"
            size="md"
            radius="md"
            onClick={onRefresh}
            loading={isRefreshing}
            aria-label="Làm mới dữ liệu"
          >
            <IconRefresh size={18} stroke={1.5} />
          </ActionIcon>
        </Tooltip>

        <Tooltip label={webhookTooltip} withArrow position="bottom">
          <Badge
            variant="dot"
            color="green"
            size="md"
            visibleFrom="xl"
            style={{ cursor: 'help', textTransform: 'none' }}
          >
            {webhookLabel}
          </Badge>
        </Tooltip>

        <Group gap="xs" wrap="nowrap" ml="xs">
          <Badge color={roleColor} variant="light" size="sm" visibleFrom="lg">
            {roleLabel}
          </Badge>

          <Group gap={6} wrap="nowrap" visibleFrom="xl">
            <IconUser size={16} stroke={1.5} />
            <Text fw={500} size="sm" style={{ whiteSpace: 'nowrap' }}>
              {user?.name || user?.email}
            </Text>
          </Group>

          <Tooltip label="Đăng xuất" withArrow position="bottom">
            <Button
              variant="subtle"
              color="gray"
              size="xs"
              leftSection={<IconLogout size={16} stroke={1.5} />}
              onClick={logout}
              px="xs"
            >
              <Text span visibleFrom="xl">Đăng xuất</Text>
            </Button>
          </Tooltip>
        </Group>
      </Group>
    </Group>
  );
}
