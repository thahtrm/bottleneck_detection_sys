import React from 'react';
import {
  Group,
  Title,
  ThemeIcon,
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
  IconShieldExclamation as IconShieldAlert,
  IconSearch,
  IconRefresh,
  IconUser,
  IconLogout,
  IconX,
  IconLayoutDashboard,
  IconSettings,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import { getAdminSettings } from '../api/client';

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
  currentView = 'dashboard',
  onViewChange,
}) {
  const { user, logout } = useAuth();

  // Chỉ gọi getAdminSettings nếu người dùng có quyền admin
  const { data: adminSettings } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: getAdminSettings,
    enabled: Boolean(user?.is_admin),
    refetchInterval: 30000,
    staleTime: 10000,
  });

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
  const roleColor = user?.is_admin ? 'red' : 'blue';

  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      {/* Khối bên trái: Logo + Chọn dự án */}
      <Group gap="md" wrap="nowrap" style={{ flexShrink: 0 }}>
        <Group gap="xs" wrap="nowrap">
          <ThemeIcon size="lg" radius="md" color="blue" variant="filled">
            <IconShieldAlert size={22} stroke={1.5} />
          </ThemeIcon>
          <Box visibleFrom="xs">
            <Title order={4} style={{ whiteSpace: 'nowrap' }}>
              Early Risk Web
            </Title>
          </Box>
        </Group>

        <Select
          data={projectOptions}
          value={selectedProject || ''}
          onChange={(val) => onSelectProject && onSelectProject(val || '')}
          placeholder="Chọn dự án"
          size="sm"
          w={{ base: 140, sm: 190, md: 230 }}
          allowDeselect={false}
          checkIconPosition="right"
          aria-label="Chọn dự án theo dõi"
        />

        {/* Nút chuyển đổi điều hướng dành cho Admin */}
        {user?.is_admin && (
          <Group gap={4} wrap="nowrap" ml="xs">
            <Tooltip label="Bảng điều khiển" withArrow position="bottom">
              <Button
                variant={currentView === 'dashboard' ? 'filled' : 'subtle'}
                color="blue"
                size="xs"
                leftSection={<IconLayoutDashboard size={15} stroke={1.5} />}
                onClick={() => onViewChange && onViewChange('dashboard')}
                aria-label="Chuyển sang Bảng điều khiển"
              >
                <Text span visibleFrom="md">Bảng điều khiển</Text>
              </Button>
            </Tooltip>

            <Tooltip label="Quản trị hệ thống" withArrow position="bottom">
              <Button
                variant={currentView === 'settings' ? 'filled' : 'subtle'}
                color="blue"
                size="xs"
                leftSection={<IconSettings size={15} stroke={1.5} />}
                onClick={() => onViewChange && onViewChange('settings')}
                aria-label="Chuyển sang Quản trị hệ thống"
              >
                <Text span visibleFrom="md">Quản trị hệ thống</Text>
              </Button>
            </Tooltip>
          </Group>
        )}
      </Group>

      {/* Khối ở giữa: Tìm kiếm nhanh */}
      <Box style={{ flex: 1, maxWidth: 460 }} mx="sm">
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
        {/* Nút Làm mới */}
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

        {/* Webhook status badge */}
        <Tooltip label={webhookTooltip} withArrow position="bottom">
          <Badge
            variant="dot"
            color="green"
            size="md"
            style={{ cursor: 'help', textTransform: 'none' }}
          >
            {webhookLabel}
          </Badge>
        </Tooltip>

        {/* Thông tin người dùng & Đăng xuất */}
        <Group gap="xs" wrap="nowrap" ml="xs">
          <Badge color={roleColor} variant="light" size="sm">
            {roleLabel}
          </Badge>

          <Group gap={6} wrap="nowrap" visibleFrom="sm">
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
              <Text span visibleFrom="md">Đăng xuất</Text>
            </Button>
          </Tooltip>
        </Group>
      </Group>
    </Group>
  );
}
