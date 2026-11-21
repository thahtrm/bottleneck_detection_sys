import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  NumberInput,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import {
  IconAlertCircle,
  IconAlertTriangle,
  IconArrowLeft,
  IconBell,
  IconCheck,
  IconClock,
  IconCpu,
  IconDeviceFloppy,
  IconFolders,
  IconMessageCircle,
  IconPlayerPlay,
  IconRefresh,
  IconServer,
  IconSettings,
  IconUser,
  IconUsers,
  IconWebhook,
} from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { OpenProjectOnJira } from '../components/JiraLinks';
import MemoryPrefsSection from '../components/settings/MemoryPrefsSection';
import ProjectMembersSection from '../components/settings/ProjectMembersSection';
import ReportScheduleSection from '../components/settings/ReportScheduleSection';
import { useAuth } from '../context/AuthContext';
import { useBubblePref } from '../hooks/useBubblePref';
import {
  getAdminSettings,
  getChatSystemStatus,
  getProjects,
  runModelBatch,
  toggleProjectTracking,
  updateAdminSettings,
} from '../api/client';
import '../styles/kaggleTokens.css';

function formatDateTime(isoString, fallback = 'Chưa có dữ liệu') {
  if (!isoString) return fallback;
  try {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
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

function StatusBadge({ ok, labelOk, labelBad }) {
  return (
    <span className={ok ? 'erw-settings-badge' : 'erw-settings-badge-error'}>
      {ok ? labelOk : labelBad}
    </span>
  );
}

export default function Settings({
  onBackToDashboard,
  project = '',
  projects: projectsProp,
  onOpenChat,
  onOpenUsers,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = Boolean(user?.is_admin);
  const [bubbleEnabled, setBubbleEnabled, bubbleMeta] = useBubblePref(Boolean(user));

  const {
    data: adminSettings,
    isLoading: isLoadingSettings,
    error: settingsError,
    refetch: refetchSettings,
  } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: getAdminSettings,
    enabled: isAdmin,
    staleTime: 10000,
  });

  const {
    data: projectsQuery = [],
    isLoading: isLoadingProjects,
    refetch: refetchProjects,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
    enabled: Boolean(user),
    staleTime: 30000,
  });

  const projects = projectsProp ?? projectsQuery;
  const projectRole = projects.find((item) => item.key === project)?.role;
  const isPmSomewhere = isAdmin || projects.some((item) => item.role === 'pm');
  const canChatSettings = isPmSomewhere;
  const canEditProjectMemory = Boolean(project) && (isAdmin || projectRole === 'pm');
  const canManageMembers = Boolean(project) && (isAdmin || projectRole === 'pm');

  const systemStatus = useQuery({
    queryKey: ['chat-system-status'],
    queryFn: getChatSystemStatus,
    enabled: canChatSettings,
    staleTime: 30000,
  });

  const [delayThreshold, setDelayThreshold] = useState(0.39);
  const [criticalityTopPct, setCriticalityTopPct] = useState(0.05);
  const [llmModel, setLlmModel] = useState('gemma4:e4b');
  const [isRunningBatch, setIsRunningBatch] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [togglingKeys, setTogglingKeys] = useState(new Set());

  useEffect(() => {
    if (!adminSettings) return;
    if (adminSettings.delay_threshold !== undefined && adminSettings.delay_threshold !== null) {
      setDelayThreshold(Number(adminSettings.delay_threshold));
    }
    if (adminSettings.criticality_top_pct !== undefined && adminSettings.criticality_top_pct !== null) {
      setCriticalityTopPct(Number(adminSettings.criticality_top_pct));
    }
    if (adminSettings.llm_model) setLlmModel(String(adminSettings.llm_model));
  }, [adminSettings]);

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

  const handleSaveSettings = async (e) => {
    if (e?.preventDefault) e.preventDefault();
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

  const handleToggleTracking = async (projectKey) => {
    setTogglingKeys((prev) => new Set(prev).add(projectKey));
    try {
      const updated = await toggleProjectTracking(projectKey);
      notifications.show({
        title: 'Cập nhật dự án thành công',
        message: `Dự án ${projectKey} hiện ${updated?.tracked ? 'đang được theo dõi' : 'đã dừng theo dõi'}.`,
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

  const handleRefreshAll = async () => {
    const jobs = [refetchProjects()];
    if (isAdmin) jobs.push(refetchSettings());
    if (canChatSettings) jobs.push(systemStatus.refetch());
    await Promise.all(jobs);
  };

  const status = systemStatus.data;
  const embedModel = status?.embed_model || 'nomic-embed-text';
  const chatModel = status?.llm_model || adminSettings?.llm_model || llmModel;
  const ollamaOk = status ? Boolean(status.ollama_reachable) : null;
  const ragOk = status ? Boolean(status.rag_index_present) : null;
  const slackConfigured = Boolean(status?.slack_webhook_configured);
  const digestTime = status?.digest_time || '08:00';
  const slackMaxPerHour = status?.slack_max_per_hour;
  const statusTz = status?.tz;

  return (
    <div className="erw-settings-scope">
      <Stack gap="xl" maw={1120} mx="auto">
        <Group justify="space-between" align="center" wrap="wrap">
          <Box>
            <Group gap="xs">
              <IconSettings size={28} stroke={1.5} color="var(--color-secondary)" />
              <Title order={2} className="erw-settings-page-title">
                Cài đặt
              </Title>
            </Group>
            <Text className="erw-settings-meta" mt={4}>
              Cấu hình lịch báo cáo, ghi nhớ, bề mặt chat, thông báo và (admin) hệ thống.
            </Text>
          </Box>
          <Group gap="sm">
            <Tooltip label="Làm mới" withArrow position="bottom">
              <ActionIcon
                variant="light"
                color="blue"
                size="lg"
                radius="md"
                onClick={handleRefreshAll}
                aria-label="Làm mới trang cài đặt"
              >
                <IconRefresh size={18} stroke={1.5} />
              </ActionIcon>
            </Tooltip>
            {onBackToDashboard && (
              <Button
                className="erw-settings-btn-secondary"
                leftSection={<IconArrowLeft size={16} />}
                onClick={onBackToDashboard}
              >
                Về Bảng
              </Button>
            )}
          </Group>
        </Group>

        <SettingsCard
          title="Vai trò & dự án"
          icon={<IconUser size={22} color="var(--color-secondary)" />}
          right={
            isAdmin && onOpenUsers ? (
              <Button className="erw-settings-btn-secondary" size="compact-sm" onClick={onOpenUsers}>
                Người dùng hệ thống
              </Button>
            ) : null
          }
        >
          {isLoadingProjects ? (
            <Center py="md">
              <Loader size="sm" type="dots" />
            </Center>
          ) : projects.length === 0 ? (
            <Text className="erw-settings-meta">Chưa có dự án trong tài khoản.</Text>
          ) : (
            <Table.ScrollContainer minWidth={480}>
              <Table verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Mã</Table.Th>
                    <Table.Th>Tên</Table.Th>
                    <Table.Th>Vai trò</Table.Th>
                    <Table.Th>Theo dõi</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {projects.map((item) => (
                    <Table.Tr key={item.key}>
                      <Table.Td>
                        <Badge variant="light" color="blue" size="md">
                          {item.key}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" fw={500}>
                          {item.name || '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{user.is_admin ? 'admin' : item.role || 'viewer'}</Text>
                      </Table.Td>
                      <Table.Td>
                        {item.tracked ? (
                          <Badge color="teal" size="sm" variant="light">
                            Tracked
                          </Badge>
                        ) : (
                          <Badge color="gray" size="sm" variant="light">
                            Off
                          </Badge>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </SettingsCard>

        <SettingsCard title="Thành viên dự án" icon={<IconUsers size={22} color="var(--color-secondary)" />}>
          <ProjectMembersSection project={project} canManage={canManageMembers} />
        </SettingsCard>

        {canChatSettings && (
          <>
            <SettingsCard
              title="Lịch báo cáo chat"
              icon={<IconClock size={22} color="var(--color-secondary)" />}
            >
              <ReportScheduleSection onViewReports={onOpenChat} />
            </SettingsCard>

            <SettingsCard
              title="Ghi nhớ chat"
              icon={<IconMessageCircle size={22} color="var(--color-secondary)" />}
            >
              {!project ? (
                <Text className="erw-settings-meta">
                  Chọn dự án trên Header để quản lý ghi nhớ theo project.
                </Text>
              ) : !canEditProjectMemory ? (
                <Text className="erw-settings-meta">
                  Ghi nhớ chỉ chỉnh được khi bạn là PM (hoặc Admin) trên dự án {project}.
                </Text>
              ) : (
                <MemoryPrefsSection project={project} />
              )}
            </SettingsCard>

            <SettingsCard
              title="Bề mặt chat"
              icon={<IconMessageCircle size={22} color="var(--color-secondary)" />}
            >
              <Stack gap="sm">
                <Switch
                  checked={bubbleEnabled}
                  onChange={(event) => setBubbleEnabled(event.currentTarget.checked)}
                  disabled={bubbleMeta.isLoading || bubbleMeta.isSaving}
                  label="Hiện bubble chat trên Bảng / Danh sách"
                  description="Tắt để chỉ dùng tab Chat (tab-only). Lưu qua /api/chat/prefs."
                  className="erw-settings-switch"
                />
                {bubbleMeta.error && (
                  <Text className="erw-settings-error">
                    {bubbleMeta.error.message || 'Không lưu được pref bubble.'}
                  </Text>
                )}
                <Text className="erw-settings-meta">
                  File báo cáo ngày quản lý trong tab Chat
                  {onOpenChat ? (
                    <>
                      {' — '}
                      <Button variant="subtle" size="compact-xs" className="erw-settings-link" onClick={onOpenChat}>
                        Mở Chat
                      </Button>
                    </>
                  ) : null}
                  .
                </Text>
              </Stack>
            </SettingsCard>

            <SettingsCard
              title="Trạng thái LLM / Ollama / embed"
              icon={<IconCpu size={22} color="var(--color-secondary)" />}
            >
              <Stack gap="sm">
                {systemStatus.isError && (
                  <Text className="erw-settings-error">
                    {systemStatus.error?.message || 'Không tải được system-status.'}
                  </Text>
                )}
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <div className="erw-settings-field">
                    <Text className="erw-settings-label">Chat model</Text>
                    <Text className="erw-settings-body">{chatModel}</Text>
                  </div>
                  <div className="erw-settings-field">
                    <Text className="erw-settings-label">Embed model</Text>
                    <Text className="erw-settings-body">{embedModel}</Text>
                  </div>
                  <div className="erw-settings-field">
                    <Text className="erw-settings-label">Ollama</Text>
                    {systemStatus.isLoading || ollamaOk === null ? (
                      <Text className="erw-settings-meta">Đang kiểm tra…</Text>
                    ) : (
                      <StatusBadge ok={ollamaOk} labelOk="Reachable" labelBad="Offline" />
                    )}
                  </div>
                  <div className="erw-settings-field">
                    <Text className="erw-settings-label">RAG index</Text>
                    {systemStatus.isLoading || ragOk === null ? (
                      <Text className="erw-settings-meta">Đang kiểm tra…</Text>
                    ) : (
                      <StatusBadge ok={ragOk} labelOk="Present" labelBad="Missing" />
                    )}
                  </div>
                </SimpleGrid>
                {statusTz && <Text className="erw-settings-meta">Timezone máy chủ: {statusTz}</Text>}
                {!isAdmin && (
                  <Text className="erw-settings-meta">PM xem trạng thái read-only; admin đổi model ở mục Admin.</Text>
                )}
              </Stack>
            </SettingsCard>

            <SettingsCard
              title="Thông báo / Slack"
              icon={<IconBell size={22} color="var(--color-secondary)" />}
            >
              <Stack gap="sm">
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <div className="erw-settings-field">
                    <Text className="erw-settings-label">Slack webhook</Text>
                    <StatusBadge
                      ok={slackConfigured}
                      labelOk="Đã cấu hình"
                      labelBad="Chưa cấu hình"
                    />
                  </div>
                  <div className="erw-settings-field">
                    <Text className="erw-settings-label">Digest time</Text>
                    <Text className="erw-settings-body">{digestTime}</Text>
                  </div>
                  {isAdmin && slackMaxPerHour != null && (
                    <div className="erw-settings-field">
                      <Text className="erw-settings-label">Slack max / hour</Text>
                      <Text className="erw-settings-body">{slackMaxPerHour}</Text>
                    </div>
                  )}
                </SimpleGrid>
                <Text className="erw-settings-meta">
                  Báo cáo chat vẫn vào timeline theo lịch của bạn. Agent không gửi Slack từ hội thoại.
                </Text>
              </Stack>
            </SettingsCard>
          </>
        )}

        {!canChatSettings && (
          <Alert icon={<IconAlertCircle size={18} />} color="gray" variant="light" radius="md">
            Tài khoản viewer chỉ xem vai trò / dự án. Chat và lịch báo cáo dành cho PM hoặc Admin.
          </Alert>
        )}

        {isAdmin && (
          <>
            <Divider label="Admin hệ thống" labelPosition="center" />

            {settingsError && (
              <Alert icon={<IconAlertCircle size={18} />} title="Không thể tải cấu hình quản trị" color="red" variant="light">
                {settingsError.message || 'Lỗi khi tải thông tin cấu hình từ máy chủ.'}
              </Alert>
            )}

            <SettingsCard
              title="Trạng thái Kết nối & Webhook Jira"
              icon={<IconWebhook size={22} color="var(--color-secondary)" />}
              right={
                <Badge variant="dot" color={adminSettings?.last_webhook_at ? 'green' : 'blue'} size="lg">
                  {adminSettings?.last_webhook_at ? 'Kết nối trực tuyến' : 'Sẵn sàng'}
                </Badge>
              }
            >
              {isLoadingSettings ? (
                <Center py="xl">
                  <Loader size="md" type="dots" />
                </Center>
              ) : (
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <div className="erw-settings-field">
                    <Group gap="xs" mb={4}>
                      <IconServer size={16} stroke={1.5} color="gray" />
                      <Text className="erw-settings-label">Jira Base URL</Text>
                    </Group>
                    <Text className="erw-settings-body" style={{ wordBreak: 'break-all' }}>
                      {adminSettings?.jira_base_url || 'Chưa cấu hình'}
                    </Text>
                  </div>
                  <div className="erw-settings-field">
                    <Group gap="xs" mb={4}>
                      <IconWebhook size={16} stroke={1.5} color="gray" />
                      <Text className="erw-settings-label">Webhook URL</Text>
                    </Group>
                    <Text className="erw-settings-body" style={{ wordBreak: 'break-all' }}>
                      {adminSettings?.webhook_url || 'Chưa cấu hình'}
                    </Text>
                  </div>
                  <div className="erw-settings-field">
                    <Group gap="xs" mb={4}>
                      <IconClock size={16} stroke={1.5} color="gray" />
                      <Text className="erw-settings-label">Webhook gần nhất</Text>
                    </Group>
                    <Text className="erw-settings-body">
                      {formatDateTime(adminSettings?.last_webhook_at, 'Chưa nhận webhook nào')}
                    </Text>
                  </div>
                  <div className="erw-settings-field">
                    <Group gap="xs" mb={4}>
                      <IconRefresh size={16} stroke={1.5} color="gray" />
                      <Text className="erw-settings-label">Catch-up gần nhất</Text>
                    </Group>
                    <Text className="erw-settings-body">
                      {formatDateTime(adminSettings?.last_catch_up_at, 'Chưa thực hiện đồng bộ bù')}
                    </Text>
                  </div>
                </SimpleGrid>
              )}
            </SettingsCard>

            <SettingsCard
              title="Điều khiển mô hình & chạy lô"
              icon={<IconCpu size={22} color="var(--color-secondary)" />}
              right={
                adminSettings?.model_mode ? (
                  <Badge variant="light" color="violet">
                    Chế độ: {adminSettings.model_mode}
                  </Badge>
                ) : null
              }
            >
              <Text className="erw-settings-body" mb="md">
                Quét công việc tracked, tính p_delay / criticality, và tạo đề xuất LLM cho rủi ro cao.
              </Text>
              <div className="erw-settings-field" style={{ marginBottom: 24 }}>
                <Group justify="space-between" align="center" wrap="wrap">
                  <Box style={{ maxWidth: 600 }}>
                    <Text fw={600} size="sm">
                      Chạy lô phân tích rủi ro tức thì
                    </Text>
                    <Text className="erw-settings-meta" mt={2}>
                      Chạy nền; có thể mất 10–60 giây tùy số lượng công việc.
                    </Text>
                  </Box>
                  <Button
                    className="erw-settings-btn-primary"
                    leftSection={<IconPlayerPlay size={18} stroke={2} />}
                    loading={isRunningBatch}
                    onClick={handleRunBatch}
                  >
                    Chạy lô mô hình ngay
                  </Button>
                </Group>
              </div>

              <Divider my="md" label="Ngưỡng & tham số" labelPosition="left" />

              <form onSubmit={handleSaveSettings}>
                <Stack gap="md">
                  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                    <NumberInput
                      className="erw-settings-input"
                      label="Ngưỡng trễ hạn (p_delay)"
                      description="Mặc định: 0.39"
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
                      className="erw-settings-input"
                      label="Ngưỡng quan trọng (criticality_top_pct)"
                      description="Mặc định: 0.05"
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
                    className="erw-settings-input"
                    label="Model LLM"
                    description="Tên mô hình Ollama. Mặc định: gemma4:e4b"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.currentTarget.value)}
                    placeholder="gemma4:e4b"
                    required
                  />
                  <Group justify="flex-end">
                    <Button
                      type="submit"
                      className="erw-settings-btn-primary"
                      leftSection={<IconDeviceFloppy size={18} />}
                      loading={isSavingSettings}
                    >
                      Lưu cấu hình
                    </Button>
                  </Group>
                </Stack>
              </form>
            </SettingsCard>

            <SettingsCard
              title="Quản lý dự án theo dõi"
              icon={<IconFolders size={22} color="var(--color-secondary)" />}
              right={
                <Badge variant="light" color="blue">
                  {projects.filter((p) => p.tracked).length} / {projects.length} đang theo dõi
                </Badge>
              }
            >
              <Text className="erw-settings-body" mb="md">
                Chỉ dự án tracked nhận webhook, tính rủi ro và xuất hiện trong bộ lọc.
              </Text>
              {isLoadingProjects ? (
                <Center py="xl">
                  <Loader size="md" type="dots" />
                </Center>
              ) : projects.length === 0 ? (
                <Alert icon={<IconAlertCircle size={18} />} title="Chưa có dự án nào" color="gray" variant="light">
                  Kiểm tra cấu hình `JIRA_PROJECTS` hoặc tài khoản Jira.
                </Alert>
              ) : (
                <Table.ScrollContainer minWidth={600}>
                  <Table verticalSpacing="sm" highlightOnHover striped>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th style={{ width: 140 }}>Mã dự án</Table.Th>
                        <Table.Th>Tên dự án</Table.Th>
                        <Table.Th style={{ width: 120 }}>Tổng task</Table.Th>
                        <Table.Th style={{ width: 220 }}>Rủi ro</Table.Th>
                        <Table.Th style={{ width: 160, textAlign: 'right' }}>Theo dõi</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {projects.map((item) => {
                        const isToggling = togglingKeys.has(item.key);
                        const isTracked = Boolean(item.tracked);
                        const stats = item.stats || {};
                        return (
                          <Table.Tr key={item.key}>
                            <Table.Td>
                              <Group gap={6} wrap="nowrap">
                                <Badge variant="light" color="blue" size="md">
                                  {item.key}
                                </Badge>
                                <OpenProjectOnJira projectKey={item.key} variant="subtle" px={6}>
                                  Jira
                                </OpenProjectOnJira>
                              </Group>
                            </Table.Td>
                            <Table.Td>
                              <Text fw={500} size="sm">
                                {item.name || (
                                  <Text span c="dimmed" fs="italic">
                                    Chưa đặt tên
                                  </Text>
                                )}
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
                              <Switch
                                checked={isTracked}
                                onChange={() => handleToggleTracking(item.key)}
                                disabled={isToggling}
                                color="blue"
                                size="sm"
                                label={isTracked ? 'Đang theo dõi' : 'Tạm dừng'}
                                aria-label={`Bật tắt theo dõi cho dự án ${item.key}`}
                              />
                            </Table.Td>
                          </Table.Tr>
                        );
                      })}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              )}
            </SettingsCard>
          </>
        )}
      </Stack>
    </div>
  );
}
