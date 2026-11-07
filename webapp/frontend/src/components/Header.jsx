import React from 'react';
import {
  Group,
  Title,
  ThemeIcon,
  Select,
  SegmentedControl,
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
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import { getAdminSettings } from '../api/client';

const VIEW_OPTIONS = [
  { value: 'board', label: 'Bảng' },
  { value: 'list', label: 'Danh sách' },
  { value: 'graph', label: 'Đồ thị' },
];
const ADMIN_VIEW_OPTIONS = [...VIEW_OPTIONS, { value: 'settings', label: 'Quản trị' }];

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
  view,
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
  const roleColor = user?.is_admin ? 'dark' : 'blue';

  return (
    <Group h="100%" px="md" gap="sm" justify="space-between" wrap="nowrap" style={{ minWidth: 0 }}>
      {/* Khối bên trái: Logo + Chọn dự án. Nút xem không được co, để chữ không bị cắt. */}
      <Group gap="sm" wrap="nowrap" style={{ flex: '1 1 auto' }}>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          <ThemeIcon size="lg" radius="md" color="blue" variant="filled">
            <IconShieldAlert size={22} stroke={1.5} />
          </ThemeIcon>
          <Box visibleFrom="xl">
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
          miw={120}
          maw={230}
          style={{ flex: '1 1 160px' }}
          allowDeselect={false}
          checkIconPosition="right"
          aria-label="Chọn dự án theo dõi"
        />

        <SegmentedControl
          size="sm"
          data={user?.is_admin ? ADMIN_VIEW_OPTIONS : VIEW_OPTIONS}
          value={view}
          onChange={onViewChange}
          aria-label="Chế độ xem"
          style={{ flexShrink: 0 }}
        />
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
            visibleFrom="xl"
            style={{ cursor: 'help', textTransform: 'none' }}
          >
            {webhookLabel}
          </Badge>
        </Tooltip>

        {/* Thông tin người dùng & Đăng xuất */}
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
