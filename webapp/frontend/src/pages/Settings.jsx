import React, { useState, useEffect } from 'react';
import {
  Container,
  Stack,
  Title,
  Text,
  Card,
  Group,
  Badge,
  Button,
  NumberInput,
  TextInput,
  Table,
  Switch,
  Alert,
  Loader,
  Center,
  SimpleGrid,
  Paper,
  Divider,
  Box,
  Tooltip,
  ActionIcon,
} from '@mantine/core';
import {
  IconSettings,
  IconPlayerPlay,
  IconCheck,
  IconAlertCircle,
  IconAlertTriangle,
  IconWebhook,
  IconServer,
  IconClock,
  IconRefresh,
  IconArrowLeft,
  IconFolders,
  IconDeviceFloppy,
  IconCpu,
} from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { OpenProjectOnJira } from '../components/JiraLinks';
import { notifications } from '@mantine/notifications';
import { useAuth } from '../context/AuthContext';
import {
  getAdminSettings,
  getProjects,
  updateAdminSettings,
  runModelBatch,
  toggleProjectTracking,
} from '../api/client';

/**
 * Format thời gian ISO thành chuỗi ngày giờ tiếng Việt
 */
function formatDateTime(isoString, fallback = 'Chưa có dữ liệu') {
  if (!isoString) return fallback;
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

export default function Settings({ onBackToDashboard }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  // Queries
  const {
    data: adminSettings,
    isLoading: isLoadingSettings,
    error: settingsError,
    refetch: refetchSettings,
  } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: getAdminSettings,
    enabled: Boolean(user?.is_admin),
    staleTime: 10000,
  });

  const {
    data: projects = [],
    isLoading: isLoadingProjects,
    refetch: refetchProjects,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
    enabled: Boolean(user?.is_admin),
    staleTime: 30000,
  });

  // Form states
  const [delayThreshold, setDelayThreshold] = useState(0.39);
  const [criticalityTopPct, setCriticalityTopPct] = useState(0.05);
  const [llmModel, setLlmModel] = useState('gemma4:e4b');

  // Action loading states
  const [isRunningBatch, setIsRunningBatch] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [togglingKeys, setTogglingKeys] = useState(new Set());

  // Đồng bộ giá trị từ API vào form khi settings tải xong
  useEffect(() => {
    if (adminSettings) {
      if (adminSettings.delay_threshold !== undefined && adminSettings.delay_threshold !== null) {
        setDelayThreshold(Number(adminSettings.delay_threshold));
      }
      if (adminSettings.criticality_top_pct !== undefined && adminSettings.criticality_top_pct !== null) {
        setCriticalityTopPct(Number(adminSettings.criticality_top_pct));
      }
      if (adminSettings.llm_model) {
        setLlmModel(String(adminSettings.llm_model));
      }
    }
  }, [adminSettings]);

  // Kiểm tra quyền Admin
  if (!user?.is_admin) {
    return (
      <Container size="md" py="xl">
        <Alert
          icon={<IconAlertCircle size={20} />}
          title="Từ chối truy cập"
          color="red"
          variant="filled"
          radius="md"
        >
          Bạn không có quyền truy cập trang Quản trị Hệ thống. Trang này chỉ dành cho người dùng có vai trò Quản trị viên (Admin).
        </Alert>
        {onBackToDashboard && (
          <Group mt="md">
            <Button
              variant="light"
              leftSection={<IconArrowLeft size={16} />}
              onClick={onBackToDashboard}
            >
              Quay lại Bảng điều khiển
            </Button>
          </Group>
        )}
      </Container>
    );
  }

  // Xử lý kích hoạt chạy lô mô hình
  const handleRunBatch = async () => {
    setIsRunningBatch(true);
    try {
      const res = await runModelBatch();
      notifications.show({
        title: 'Kích hoạt thành công',
        message: res?.message || 'Đã kích hoạt chạy lô mô hình trong tiến trình nền!',
        color: 'teal',
        icon: <IconCheck size={18} />,
      });
      // Làm mới dữ liệu sau khi chạy
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-settings'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-board'] }),
      ]);
    } catch (err) {
      if (err.status === 409) {
        notifications.show({
          title: 'Hệ thống đang chạy lô',
          message: 'Lô mô hình đang được chạy, vui lòng chờ hoàn tất!',
          color: 'yellow',
          icon: <IconAlertTriangle size={18} />,
        });
      } else {
        notifications.show({
          title: 'Kích hoạt thất bại',
          message: err.message || 'Không thể khởi chạy lô mô hình.',
          color: 'red',
          icon: <IconAlertCircle size={18} />,
        });
      }
    } finally {
      setIsRunningBatch(false);
    }
  };

  // Xử lý lưu cấu hình ngưỡng
  const handleSaveSettings = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    setIsSavingSettings(true);
    try {
      await updateAdminSettings({
        delay_threshold: Number(delayThreshold),
        criticality_top_pct: Number(criticalityTopPct),
        llm_model: String(llmModel).trim(),
      });
      notifications.show({
        title: 'Lưu cấu hình thành công',
        message: 'Đã lưu cấu hình ngưỡng rủi ro và mô hình LLM.',
        color: 'teal',
        icon: <IconCheck size={18} />,
      });
      await queryClient.invalidateQueries({ queryKey: ['admin-settings'] });
    } catch (err) {
      notifications.show({
        title: 'Lưu cấu hình thất bại',
        message: err.message || 'Không thể lưu cấu hình quản trị.',
        color: 'red',
        icon: <IconAlertCircle size={18} />,
      });
    } finally {
      setIsSavingSettings(false);
    }
  };

  // Xử lý bật/tắt theo dõi dự án Jira
  const handleToggleTracking = async (projectKey) => {
    setTogglingKeys((prev) => new Set(prev).add(projectKey));
    try {
      const updated = await toggleProjectTracking(projectKey);
      const isNowTracked = updated?.tracked;
      notifications.show({
        title: 'Cập nhật dự án thành công',
        message: `Dự án ${projectKey} hiện ${isNowTracked ? 'đang được theo dõi' : 'đã dừng theo dõi'}.`,
        color: 'teal',
        icon: <IconCheck size={18} />,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-settings'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-board'] }),
      ]);
    } catch (err) {
      notifications.show({
        title: 'Cập nhật thất bại',
        message: err.message || `Không thể đổi trạng thái theo dõi dự án ${projectKey}.`,
        color: 'red',
        icon: <IconAlertCircle size={18} />,
      });
    } finally {
      setTogglingKeys((prev) => {
        const next = new Set(prev);
        next.delete(projectKey);
        return next;
      });
    }
  };

  // Làm mới toàn bộ dữ liệu quản trị
  const handleRefreshAll = async () => {
    await Promise.all([refetchSettings(), refetchProjects()]);
  };

  return (
    <Stack gap="xl">
      {/* Tiêu đề & Điều hướng phụ */}
      <Group justify="space-between" align="center" wrap="wrap">
        <Box>
          <Group gap="xs">
            <IconSettings size={28} stroke={1.5} color="var(--mantine-color-blue-filled)" />
            <Title order={2}>Quản trị Hệ thống</Title>
          </Group>
          <Text c="dimmed" size="sm" mt={4}>
            Quản lý trạng thái webhook Jira, kích hoạt lô tính toán rủi ro, cấu hình tham số mô hình và danh sách dự án.
          </Text>
        </Box>

        <Group gap="sm">
          <Tooltip label="Làm mới thông tin trang quản trị" withArrow position="bottom">
            <ActionIcon
              variant="light"
              color="blue"
              size="lg"
              radius="md"
              onClick={handleRefreshAll}
              aria-label="Làm mới trang quản trị"
            >
              <IconRefresh size={18} stroke={1.5} />
            </ActionIcon>
          </Tooltip>

          {onBackToDashboard && (
            <Button
              variant="default"
              size="sm"
              leftSection={<IconArrowLeft size={16} />}
              onClick={onBackToDashboard}
            >
              Về Bảng điều khiển
            </Button>
          )}
        </Group>
      </Group>

      {settingsError && (
        <Alert
          icon={<IconAlertCircle size={18} />}
          title="Không thể tải cấu hình quản trị"
          color="red"
          variant="light"
          radius="md"
        >
          {settingsError.message || 'Lỗi khi tải thông tin cấu hình từ máy chủ.'}
        </Alert>
      )}

      {/* PHẦN 1: Trạng thái Kết nối & Webhook */}
      <Card withBorder radius="md" padding="lg">
        <Group justify="space-between" align="center" mb="md">
          <Group gap="xs">
            <IconWebhook size={22} color="var(--mantine-color-blue-filled)" />
            <Title order={4}>1. Trạng thái Kết nối & Webhook Jira</Title>
          </Group>
          <Badge
            variant="dot"
            color={adminSettings?.last_webhook_at ? 'green' : 'blue'}
            size="lg"
          >
            {adminSettings?.last_webhook_at ? 'Kết nối trực tuyến' : 'Sẵn sàng'}
          </Badge>
        </Group>

        {isLoadingSettings ? (
          <Center py="xl">
            <Loader size="md" type="dots" />
          </Center>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <Paper withBorder p="sm" radius="sm">
              <Group gap="xs" mb={4}>
                <IconServer size={16} stroke={1.5} color="gray" />
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Jira Base URL
                </Text>
              </Group>
              <Text fw={500} size="sm" style={{ wordBreak: 'break-all' }}>
                {adminSettings?.jira_base_url || 'Chưa cấu hình'}
              </Text>
            </Paper>

            <Paper withBorder p="sm" radius="sm">
              <Group gap="xs" mb={4}>
                <IconWebhook size={16} stroke={1.5} color="gray" />
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Webhook URL (Bảo mật)
                </Text>
              </Group>
              <Text fw={500} size="sm" style={{ wordBreak: 'break-all' }}>
                {adminSettings?.webhook_url || 'Chưa cấu hình (Thiếu public URL hoặc secret)'}
              </Text>
            </Paper>

            <Paper withBorder p="sm" radius="sm">
              <Group gap="xs" mb={4}>
                <IconClock size={16} stroke={1.5} color="gray" />
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Webhook gần nhất
                </Text>
              </Group>
              <Text fw={500} size="sm">
                {formatDateTime(adminSettings?.last_webhook_at, 'Chưa nhận webhook nào')}
              </Text>
            </Paper>

            <Paper withBorder p="sm" radius="sm">
              <Group gap="xs" mb={4}>
                <IconRefresh size={16} stroke={1.5} color="gray" />
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Đồng bộ bù gần nhất (Catch-up)
                </Text>
              </Group>
              <Text fw={500} size="sm">
                {formatDateTime(adminSettings?.last_catch_up_at, 'Chưa thực hiện đồng bộ bù')}
              </Text>
            </Paper>
          </SimpleGrid>
        )}
      </Card>

      {/* PHẦN 2: Điều khiển Mô hình & Chạy Lô Tức thì */}
      <Card withBorder radius="md" padding="lg">
        <Group justify="space-between" align="center" mb="sm">
          <Group gap="xs">
            <IconCpu size={22} color="var(--mantine-color-blue-filled)" />
            <Title order={4}>2. Điều khiển Mô hình & Chạy Lô Tức thì</Title>
          </Group>
          {adminSettings?.model_mode && (
            <Badge variant="light" color="violet">
              Chế độ: {adminSettings.model_mode}
            </Badge>
          )}
        </Group>

        <Text size="sm" c="dimmed" mb="lg">
          Kích hoạt tiến trình quét toàn bộ công việc trong các dự án được theo dõi, tính toán xác suất trễ hạn (p_delay), điểm quan trọng (criticality), và tự động tạo đề xuất giảm thiểu rủi ro (LLM) cho các công việc rủi ro cao.
        </Text>

        {/* Nút lớn chạy lô mô hình */}
        <Paper
          withBorder
          p="md"
          radius="md"
          bg="var(--mantine-color-gray-0)"
          mb="xl"
        >
          <Group justify="space-between" align="center" wrap="wrap">
            <Box style={{ maxWidth: 600 }}>
              <Text fw={600} size="sm">
                Chạy Lô Phân Tích & Đánh Giá Rủi Ro Tức Thì (Batch Scoring)
              </Text>
              <Text size="xs" c="dimmed" mt={2}>
                Chạy ngầm qua Background Tasks mà không chặn luồng giao diện người dùng. Có thể mất từ 10 - 60 giây tùy số lượng công việc.
              </Text>
            </Box>

            <Button
              size="md"
              color="blue"
              leftSection={<IconPlayerPlay size={20} stroke={2} />}
              loading={isRunningBatch}
              onClick={handleRunBatch}
            >
              Chạy lô mô hình ngay
            </Button>
          </Group>
        </Paper>

        <Divider my="md" label="Cấu hình Ngưỡng & Tham số Mô hình" labelPosition="left" />

        {/* Form cấu hình ngưỡng */}
        <form onSubmit={handleSaveSettings}>
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <NumberInput
                label="Ngưỡng trễ hạn (p_delay)"
                description="Mức xác suất trễ hạn tối thiểu để phân loại công việc vào nhóm Rủi ro Cao (HIGH). Mặc định: 0.39"
                value={delayThreshold}
                onChange={(val) => setDelayThreshold(val === '' ? 0.39 : Number(val))}
                min={0.01}
                max={0.99}
                step={0.01}
                decimalScale={2}
                fixedDecimalScale
                required
              />

              <NumberInput
                label="Ngưỡng quan trọng (criticality_top_pct)"
                description="Tỷ lệ top phần trăm công việc quan trọng nhất dự án theo đồ thị phụ thuộc (vd: 0.05 là top 5%). Mặc định: 0.05"
                value={criticalityTopPct}
                onChange={(val) => setCriticalityTopPct(val === '' ? 0.05 : Number(val))}
                min={0.01}
                max={0.5}
                step={0.01}
                decimalScale={2}
                fixedDecimalScale
                required
              />
            </SimpleGrid>

            <TextInput
              label="Model LLM (Mô hình ngôn ngữ đề xuất hành động)"
              description="Tên mô hình Ollama được dùng để tạo khuyến nghị và giải thích nguyên nhân rủi ro. Mặc định: gemma4:e4b"
              value={llmModel}
              onChange={(e) => setLlmModel(e.currentTarget.value)}
              placeholder="gemma4:e4b"
              required
            />

            <Group justify="flex-end" mt="xs">
              <Button
                type="submit"
                color="blue"
                leftSection={<IconDeviceFloppy size={18} />}
                loading={isSavingSettings}
              >
                Lưu cấu hình
              </Button>
            </Group>
          </Stack>
        </form>
      </Card>

      {/* PHẦN 3: Quản lý Dự án Theo dõi (Tracked Projects) */}
      <Card withBorder radius="md" padding="lg">
        <Group justify="space-between" align="center" mb="sm">
          <Group gap="xs">
            <IconFolders size={22} color="var(--mantine-color-blue-filled)" />
            <Title order={4}>3. Quản lý Dự án Theo dõi (Tracked Projects)</Title>
          </Group>
          <Badge variant="light" color="blue">
            {projects.filter((p) => p.tracked).length} / {projects.length} đang theo dõi
          </Badge>
        </Group>

        <Text size="sm" c="dimmed" mb="md">
          Chỉ các dự án được bật trạng thái theo dõi mới được hệ thống nhận sự kiện webhook, tính toán rủi ro và xuất hiện trong bộ lọc thống kê.
        </Text>

        {isLoadingProjects ? (
          <Center py="xl">
            <Loader size="md" type="dots" />
          </Center>
        ) : projects.length === 0 ? (
          <Alert
            icon={<IconAlertCircle size={18} />}
            title="Chưa có dự án nào"
            color="gray"
            variant="light"
            radius="md"
          >
            Hệ thống chưa tìm thấy dự án Jira nào. Hãy kiểm tra cấu hình `JIRA_PROJECTS` trong file thiết lập hoặc tài khoản Jira.
          </Alert>
        ) : (
          <Table.ScrollContainer minWidth={600}>
            <Table verticalSpacing="sm" highlightOnHover striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th style={{ width: 140 }}>Mã dự án (Key)</Table.Th>
                  <Table.Th>Tên dự án</Table.Th>
                  <Table.Th style={{ width: 120 }}>Tổng số task</Table.Th>
                  <Table.Th style={{ width: 220 }}>Tình trạng rủi ro</Table.Th>
                  <Table.Th style={{ width: 160, textAlign: 'right' }}>Theo dõi</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {projects.map((project) => {
                  const isToggling = togglingKeys.has(project.key);
                  const isTracked = Boolean(project.tracked);
                  const stats = project.stats || {};

                  return (
                    <Table.Tr key={project.key}>
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          <Badge variant="light" color="blue" size="md">
                            {project.key}
                          </Badge>
                          <OpenProjectOnJira projectKey={project.key} variant="subtle" px={6}>
                            Jira
                          </OpenProjectOnJira>
                        </Group>
                      </Table.Td>

                      <Table.Td>
                        <Text fw={500} size="sm">
                          {project.name || <Text span c="dimmed" fs="italic">Chưa đặt tên</Text>}
                        </Text>
                      </Table.Td>

                      <Table.Td>
                        <Text fw={600} size="sm">
                          {stats.total_issues ?? 0}
                        </Text>
                      </Table.Td>

                      <Table.Td>
                        <Group gap={6}>
                          {stats.high_risk_issues > 0 ? (
                            <Badge color="red" size="sm" variant="filled">
                              {stats.high_risk_issues} cao
                            </Badge>
                          ) : null}
                          {stats.med_risk_issues > 0 ? (
                            <Badge color="yellow" size="sm" variant="filled">
                              {stats.med_risk_issues} tb
                            </Badge>
                          ) : null}
                          {stats.blocked_issues > 0 ? (
                            <Badge color="orange" size="sm" variant="outline">
                              {stats.blocked_issues} nghẽn
                            </Badge>
                          ) : null}
                          {!stats.high_risk_issues && !stats.med_risk_issues && !stats.blocked_issues ? (
                            <Badge color="gray" size="sm" variant="light">
                              An toàn
                            </Badge>
                          ) : null}
                        </Group>
                      </Table.Td>

                      <Table.Td style={{ textAlign: 'right' }}>
                        <Group justify="flex-end" gap="xs">
                          <Switch
                            checked={isTracked}
                            onChange={() => handleToggleTracking(project.key)}
                            disabled={isToggling}
                            color="blue"
                            size="sm"
                            label={isTracked ? 'Đang theo dõi' : 'Tạm dừng'}
                            aria-label={`Bật tắt theo dõi cho dự án ${project.key}`}
                          />
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>
    </Stack>
  );
}
