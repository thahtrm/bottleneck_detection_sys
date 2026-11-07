import React, { useState, useMemo } from 'react';
import {
  Card,
  Stack,
  Group,
  Title,
  Text,
  Badge,
  Button,
  ActionIcon,
  Center,
  ThemeIcon,
  Skeleton,
  Paper,
  Tabs,
  Progress,
  Loader,
  Alert,
  Box,
  Modal,
  Textarea,
  Tooltip,
  Code,
  Divider,
  Avatar,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconX,
  IconSparkles,
  IconCpu,
  IconClock,
  IconAlertTriangle,
  IconAlertCircle,
  IconLock,
  IconLockOpen,
  IconFlame,
  IconCalendarTime,
  IconUserCheck,
  IconArrowsExchange,
  IconMessageDots,
  IconBulb,
  IconEyeOff,
  IconLink,
  IconChecklist,
  IconCheck,
  IconInfoCircle,
  IconShieldCheck,
  IconArrowUpRight,
  IconRefresh,
} from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import {
  getIssueDetail,
  getIssueSuggestion,
  dismissIssueRisk,
} from '../api/client';

/**
 * Tính toán thông tin hạn chót và số ngày còn lại / đã trễ
 */
function calculateDeadlineInfo(deadlineAt, duedate, deadlineLabel) {
  const dateStr = deadlineAt || duedate;
  if (!dateStr) {
    return {
      formattedDate: 'Chưa đặt hạn',
      remainingText: 'Không có thông tin hạn chót',
      color: 'gray',
      isOverdue: false,
    };
  }

  const targetDate = new Date(dateStr);
  if (isNaN(targetDate.getTime())) {
    return {
      formattedDate: dateStr,
      remainingText: 'Hạn chót không xác định',
      color: 'gray',
      isOverdue: false,
    };
  }

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const due = new Date(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate());
  const diffDays = Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));

  const formattedDate = targetDate.toLocaleDateString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  if (diffDays < 0) {
    return {
      formattedDate,
      remainingText: `Đã quá hạn ${Math.abs(diffDays)} ngày`,
      color: 'red',
      isOverdue: true,
    };
  }

  if (diffDays === 0) {
    return {
      formattedDate,
      remainingText: 'Hạn chót hôm nay',
      color: 'orange',
      isOverdue: false,
    };
  }

  if (diffDays === 1) {
    return {
      formattedDate,
      remainingText: 'Còn 1 ngày',
      color: 'orange',
      isOverdue: false,
    };
  }

  return {
    formattedDate,
    remainingText: `Còn ${diffDays} ngày`,
    color: diffDays <= 3 ? 'yellow' : 'teal',
    isOverdue: false,
  };
}

/**
 * Thông tin hiển thị cho từng loại hành động đề xuất từ AI
 */
function getActionTypeInfo(type) {
  switch (type) {
    case 'adjust_deadline':
      return {
        label: 'Gia hạn thời gian',
        color: 'blue',
        icon: IconCalendarTime,
      };
    case 'change_assignee':
      return {
        label: 'Đổi người phụ trách',
        color: 'teal',
        icon: IconUserCheck,
      };
    case 'change_status':
      return {
        label: 'Đổi trạng thái',
        color: 'orange',
        icon: IconArrowsExchange,
      };
    case 'add_comment':
      return {
        label: 'Thêm bình luận',
        color: 'violet',
        icon: IconMessageDots,
      };
    case 'escalate_blocker':
      return {
        label: 'Gỡ chặn công việc',
        color: 'red',
        icon: IconLockOpen,
      };
    default:
      return {
        label: type || 'Hành động đề xuất',
        color: 'gray',
        icon: IconBulb,
      };
  }
}

/**
 * Định dạng nhãn và giá trị của một yếu tố rủi ro
 */
function formatRiskFactor(factor) {
  if (typeof factor === 'string') {
    return { label: factor, value: null, color: 'gray' };
  }
  if (typeof factor === 'object' && factor !== null) {
    const label = factor.label || factor.name || factor.id || 'Yếu tố rủi ro';
    const value = factor.value || null;
    const cat = (factor.category || factor.id || '').toLowerCase();

    let color = 'gray';
    if (cat.includes('overdue') || cat.includes('deadline')) color = 'red';
    else if (cat.includes('block')) color = 'red';
    else if (cat.includes('stagnant') || cat.includes('change')) color = 'orange';
    else if (cat.includes('sprint')) color = 'yellow';
    else if (cat.includes('assignee')) color = 'blue';

    return { label, value, color };
  }
  return { label: String(factor), value: null, color: 'gray' };
}

/**
 * Định dạng liên kết công việc
 */
function formatLink(link, currentKey) {
  const isSource = link.source_key === currentKey;
  const otherKey = isSource ? link.target_key : link.source_key;
  const type = (link.type_std || '').toLowerCase();

  let relationLabel = link.type_std || 'Liên kết';
  let color = 'blue';

  if (type.includes('block')) {
    if (isSource) {
      relationLabel = 'Chặn công việc';
      color = 'orange';
    } else {
      relationLabel = 'Bị chặn bởi';
      color = 'red';
    }
  } else if (type.includes('depend')) {
    if (isSource) {
      relationLabel = 'Phụ thuộc vào';
      color = 'indigo';
    } else {
      relationLabel = 'Là điều kiện cho';
      color = 'cyan';
    }
  } else if (type.includes('relat')) {
    relationLabel = 'Liên quan đến';
    color = 'gray';
  }

  return { otherKey, relationLabel, color };
}

export default function IssuePanel({
  issueKey,
  onClose,
  onOpenConfirmAction,
  projects = [],
  onSelectIssue,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState('overview');
  const [isDismissModalOpen, setIsDismissModalOpen] = useState(false);
  const [dismissReason, setDismissReason] = useState('');
  const [isDismissing, setIsDismissing] = useState(false);

  // 1. Query chi tiết issue
  const {
    data: issueData,
    isLoading: isIssueLoading,
    isError: isIssueError,
    error: issueError,
    refetch: refetchIssue,
  } = useQuery({
    queryKey: ['issue-detail', issueKey],
    queryFn: () => getIssueDetail(issueKey),
    enabled: Boolean(issueKey),
    staleTime: 10000,
  });

  // 2. Query gợi ý LLM với cơ chế poll 3s khi API trả 202 pending
  const {
    data: suggestionData,
    isLoading: isSuggestionLoading,
    isError: isSuggestionError,
    error: suggestionError,
    refetch: refetchSuggestion,
  } = useQuery({
    queryKey: ['issue-suggestion', issueKey],
    queryFn: () => getIssueSuggestion(issueKey),
    enabled: Boolean(issueKey),
    refetchInterval: (query) => {
      if (query.state.data?.status === 'pending') {
        return 3000;
      }
      return false;
    },
    staleTime: 5000,
  });

  const issue = issueData?.issue;
  const riskState = issueData?.risk_state;
  const scores = issueData?.scores || [];
  const links = issueData?.links || [];

  // Trích xuất điểm dự báo học máy (p_delay & crit_score)
  const pDelay = useMemo(() => {
    if (riskState?.delay_value !== undefined && riskState?.delay_value !== null) {
      return Number(riskState.delay_value);
    }
    const delayScore = scores.find((s) => s.scorer === 'delay');
    if (delayScore?.value !== undefined && delayScore?.value !== null) {
      return Number(delayScore.value);
    }
    return null;
  }, [riskState, scores]);

  const critScore = useMemo(() => {
    if (riskState?.crit_score !== undefined && riskState?.crit_score !== null) {
      return Number(riskState.crit_score);
    }
    const critItem = scores.find((s) => s.scorer === 'criticality');
    if (critItem?.value !== undefined && critItem?.value !== null) {
      return Number(critItem.value);
    }
    return null;
  }, [riskState, scores]);

  const isCritical = Boolean(riskState?.is_critical);
  const isBlocked = Boolean(riskState?.blocked);
  const riskLevel = riskState?.level || 'LOW';

  // Kiểm tra quyền PM/Admin
  const isPm = useMemo(() => {
    if (!user) return false;
    if (user.is_admin) return true;
    const projectKey = issue?.project_key || (issueKey ? issueKey.split('-')[0] : null);
    if (!projectKey || !projects || !Array.isArray(projects)) return false;
    const project = projects.find((p) => p.key === projectKey);
    return project?.role === 'pm';
  }, [user, issue?.project_key, issueKey, projects]);

  // Kiểm tra trạng thái dismiss
  const isDismissed = Boolean(
    riskState?.level && riskState?.dismissed_at_level === riskState?.level
  );
  const canDismiss =
    isPm &&
    riskState?.level &&
    riskState?.level !== 'LOW' &&
    riskState?.dismissed_at_level !== riskState?.level;

  // Xử lý gửi yêu cầu bỏ qua rủi ro (Dismiss)
  const handleConfirmDismiss = async () => {
    setIsDismissing(true);
    try {
      await dismissIssueRisk(issueKey, dismissReason);
      notifications.show({
        title: 'Bỏ qua rủi ro thành công',
        message: `Đã bỏ qua cảnh báo rủi ro mức ${riskState?.level} cho công việc ${issueKey}.`,
        color: 'teal',
        icon: <IconCheck size={18} />,
      });
      setIsDismissModalOpen(false);
      setDismissReason('');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['issue-detail', issueKey] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-board'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-graph'] }),
      ]);
    } catch (err) {
      notifications.show({
        title: 'Thao tác thất bại',
        message: err.message || 'Không thể bỏ qua rủi ro cho công việc này.',
        color: 'red',
        icon: <IconAlertCircle size={18} />,
      });
    } finally {
      setIsDismissing(false);
    }
  };

  // Xác định dữ liệu gợi ý từ LLM
  const isPendingSuggestion = suggestionData?.status === 'pending';
  const currentSuggestion = useMemo(() => {
    if (suggestionData?.status === 'ready' && suggestionData?.suggestion) {
      return suggestionData.suggestion;
    }
    return issueData?.suggestion?.output || null;
  }, [suggestionData, issueData]);

  const currentModel =
    suggestionData?.model || issueData?.suggestion?.model || 'qwen3:1.7b';

  // Thông tin thời hạn
  const deadlineInfo = useMemo(() => {
    return calculateDeadlineInfo(
      riskState?.deadline_at,
      issue?.duedate,
      riskState?.deadline_label
    );
  }, [riskState?.deadline_at, issue?.duedate, riskState?.deadline_label]);

  // Loading skeleton khi đang tải thông tin issue
  if (isIssueLoading) {
    return (
      <Card shadow="xs" padding="md" radius="md" withBorder>
        <Stack gap="md">
          <Group justify="space-between">
            <Skeleton height={26} width={120} radius="sm" />
            <Skeleton height={26} width={26} radius="sm" />
          </Group>
          <Skeleton height={20} width="85%" radius="xs" />
          <Skeleton height={14} width="50%" radius="xs" />
          <Skeleton height={36} radius="sm" mt="xs" />
          <Skeleton height={90} radius="md" />
          <Skeleton height={120} radius="md" />
        </Stack>
      </Card>
    );
  }

  // Báo lỗi khi không tải được issue
  if (isIssueError) {
    return (
      <Card shadow="xs" padding="md" radius="md" withBorder>
        <Alert
          icon={<IconAlertCircle size={18} />}
          title="Lỗi tải chi tiết công việc"
          color="red"
          variant="light"
        >
          <Stack gap="xs">
            <Text size="xs">{issueError?.message || 'Không thể tải thông tin công việc.'}</Text>
            <Group justify="flex-end">
              <Button size="xs" color="red" variant="outline" onClick={() => refetchIssue()}>
                Thử lại
              </Button>
            </Group>
          </Stack>
        </Alert>
      </Card>
    );
  }

  return (
    <>
      <Card shadow="xs" padding="md" radius="md" withBorder>
        <Stack gap="sm">
          {/* Header Panel: Key + Summary, Badges & Nút Đóng */}
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Stack gap={4} style={{ flex: 1 }}>
              <Group gap="xs" wrap="wrap">
                <Badge size="md" color="blue" variant="filled" style={{ fontFamily: 'monospace' }}>
                  {issueKey}
                </Badge>
                {issue?.issuetype ? (
                  <Badge size="xs" variant="light" color="blue">
                    {issue.issuetype}
                  </Badge>
                ) : null}
                {issue?.priority ? (
                  <Badge
                    size="xs"
                    variant="dot"
                    color={
                      issue.priority.toLowerCase().includes('high') ||
                      issue.priority.toLowerCase().includes('critical')
                        ? 'red'
                        : 'blue'
                    }
                  >
                    {issue.priority}
                  </Badge>
                ) : null}
                {issue?.status ? (
                  <Badge size="xs" variant="outline" color="gray">
                    {issue.status}
                  </Badge>
                ) : null}
                {issue?.story_points ? (
                  <Badge size="xs" variant="outline" color="indigo">
                    {issue.story_points} SP
                  </Badge>
                ) : null}
              </Group>

              <Text fw={600} size="sm" lineClamp={2} title={issue?.summary}>
                {issue?.summary || 'Không có tiêu đề'}
              </Text>

              <Text size="xs" c="dimmed">
                Người phụ trách:{' '}
                <strong>{issue?.assignee_name || issue?.assignee_id || 'Chưa phân công'}</strong>
              </Text>
            </Stack>

            {onClose && (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={onClose}
                aria-label="Đóng panel chi tiết"
              >
                <IconX size={16} />
              </ActionIcon>
            )}
          </Group>

          <Divider my={4} />

          {/* Mantine Tabs: Tab 1 (Tổng quan & Rủi ro) & Tab 2 (Đề xuất LLM) */}
          <Tabs value={activeTab} onChange={setActiveTab} variant="pills" radius="sm">
            <Tabs.List grow mb="sm">
              <Tabs.Tab
                value="overview"
                leftSection={<IconInfoCircle size={15} />}
              >
                Tổng quan & Rủi ro
              </Tabs.Tab>
              <Tabs.Tab
                value="suggestion"
                leftSection={<IconSparkles size={15} />}
                rightSection={
                  isPendingSuggestion ? (
                    <Badge size="xs" color="blue" variant="filled">
                      Đang xử lý
                    </Badge>
                  ) : currentSuggestion?.actions?.length ? (
                    <Badge size="xs" color="teal" variant="filled">
                      {currentSuggestion.actions.length}
                    </Badge>
                  ) : null
                }
              >
                Đề xuất AI
              </Tabs.Tab>
            </Tabs.List>

            {/* TAB 1: TỔNG QUAN & RỦI RO */}
            <Tabs.Panel value="overview">
              <Stack gap="md">
                {/* 1.1 Card điểm học máy & Mức rủi ro tổng hợp */}
                <Paper p="sm" radius="md" withBorder bg="var(--mantine-color-gray-0)">
                  <Stack gap="xs">
                    <Group justify="space-between" align="center">
                      <Group gap={6}>
                        <ThemeIcon size="xs" color="blue" variant="light">
                          <IconCpu size={12} />
                        </ThemeIcon>
                        <Text size="xs" fw={700} c="dimmed">
                          ĐIỂM DỰ BÁO HỌC MÁY (ML MODELS)
                        </Text>
                      </Group>

                      {/* Mức rủi ro tổng hợp */}
                      <Group gap={4}>
                        {riskLevel === 'HIGH' ? (
                          <Badge color="red" variant="filled" size="sm">
                            RỦI RO CAO
                          </Badge>
                        ) : riskLevel === 'MED' ? (
                          <Badge color="orange" variant="filled" size="sm">
                            RỦI RO TRUNG BÌNH
                          </Badge>
                        ) : (
                          <Badge color="teal" variant="filled" size="sm">
                            RỦI RO THẤP
                          </Badge>
                        )}
                        {isCritical && (
                          <Badge
                            color="violet"
                            variant="filled"
                            size="sm"
                            leftSection={<IconFlame size={11} />}
                          >
                            Trọng yếu
                          </Badge>
                        )}
                        {isBlocked && (
                          <Badge
                            color="red"
                            variant="filled"
                            size="sm"
                            leftSection={<IconLock size={11} />}
                          >
                            Bị chặn
                          </Badge>
                        )}
                      </Group>
                    </Group>

                    {/* Chỉ số p_delay với vạch mốc 0.39 threshold */}
                    <Box mt={4}>
                      <Group justify="space-between" align="baseline" mb={2}>
                        <Text size="xs" fw={600}>
                          Xác suất trễ hạn (p_delay):{' '}
                          <Text
                            span
                            fw={700}
                            c={pDelay !== null && pDelay >= 0.39 ? 'red.7' : 'teal.7'}
                          >
                            {pDelay !== null ? `${(pDelay * 100).toFixed(1)}%` : '—'}
                          </Text>
                        </Text>
                        <Badge
                          size="xs"
                          variant="light"
                          color={pDelay !== null && pDelay >= 0.39 ? 'red' : 'teal'}
                        >
                          {pDelay !== null && pDelay >= 0.39
                            ? 'Vượt ngưỡng rủi ro (≥ 0.39)'
                            : 'An toàn (< 0.39)'}
                        </Badge>
                      </Group>

                      {/* Thanh tiến trình kèm đường đánh dấu 0.39 */}
                      <Box pos="relative" my={6}>
                        <Progress
                          value={pDelay !== null ? Math.min(100, Math.max(0, pDelay * 100)) : 0}
                          color={pDelay !== null && pDelay >= 0.39 ? 'red' : 'teal'}
                          size="md"
                          radius="xl"
                        />
                        {/* Vạch mốc threshold 0.39 */}
                        <Box
                          style={{
                            position: 'absolute',
                            left: '39%',
                            top: -3,
                            bottom: -3,
                            width: '2px',
                            backgroundColor: '#e03131',
                            zIndex: 2,
                            borderRadius: '1px',
                          }}
                          title="Ngưỡng quyết định rủi ro: 0.39 (39%)"
                        />
                      </Box>
                      <Group justify="space-between">
                        <Text size="10px" c="dimmed">
                          0%
                        </Text>
                        <Text size="10px" c="red.7" fw={700}>
                          ▲ Ngưỡng cảnh báo: 0.39 (39%)
                        </Text>
                        <Text size="10px" c="dimmed">
                          100%
                        </Text>
                      </Group>
                    </Box>

                    {/* Chỉ số Độ quan trọng (crit_score) */}
                    <Box mt={4}>
                      <Group justify="space-between" align="baseline" mb={2}>
                        <Text size="xs" fw={600}>
                          Điểm quan trọng (crit_score):{' '}
                          <Text span fw={700} c="violet.7">
                            {critScore !== null ? `${(critScore * 100).toFixed(0)}%` : '—'}
                          </Text>
                        </Text>
                        {isCritical && (
                          <Badge size="xs" variant="light" color="violet">
                            Top 5% công việc trọng yếu
                          </Badge>
                        )}
                      </Group>
                      <Progress
                        value={critScore !== null ? Math.min(100, Math.max(0, critScore * 100)) : 0}
                        color="violet"
                        size="xs"
                        radius="xl"
                      />
                    </Box>

                    {/* Mức rủi ro trước đó nếu có sự thay đổi */}
                    {riskState?.prev_level && riskState.prev_level !== riskState.level && (
                      <Group gap={4} mt={2}>
                        <IconArrowUpRight size={13} color="var(--mantine-color-gray-6)" />
                        <Text size="xs" c="dimmed">
                          Mức rủi ro trước đó: <strong>{riskState.prev_level}</strong>
                          {riskState.level_raised_at
                            ? ` (nâng mức lúc ${new Date(riskState.level_raised_at).toLocaleTimeString('vi-VN')})`
                            : ''}
                        </Text>
                      </Group>
                    )}
                  </Stack>
                </Paper>

                {/* 1.2 Thông tin hạn chót */}
                <Paper p="sm" radius="md" withBorder>
                  <Stack gap="xs">
                    <Group justify="space-between" align="center">
                      <Group gap={6}>
                        <ThemeIcon size="xs" color="blue" variant="light">
                          <IconClock size={12} />
                        </ThemeIcon>
                        <Text size="xs" fw={700} c="dimmed">
                          THỜI HẠN & TIẾN ĐỘ
                        </Text>
                      </Group>
                      <Badge
                        size="xs"
                        variant={deadlineInfo.isOverdue ? 'filled' : 'light'}
                        color={deadlineInfo.color}
                      >
                        {deadlineInfo.remainingText}
                      </Badge>
                    </Group>

                    <Group justify="space-between" align="center">
                      <Text size="xs" c="dimmed">
                        Loại hạn:
                      </Text>
                      <Badge size="xs" variant="outline" color="gray">
                        {riskState?.deadline_type
                          ? riskState.deadline_type.toUpperCase()
                          : issue?.duedate
                          ? 'DUE DATE'
                          : 'CHƯA ĐẶT'}
                      </Badge>
                    </Group>

                    {riskState?.deadline_label && (
                      <Group justify="space-between" align="center">
                        <Text size="xs" c="dimmed">
                          Tên Sprint / Phiên bản:
                        </Text>
                        <Text size="xs" fw={600}>
                          {riskState.deadline_label}
                        </Text>
                      </Group>
                    )}

                    <Group justify="space-between" align="center">
                      <Text size="xs" c="dimmed">
                        Thời điểm hạn chót:
                      </Text>
                      <Text size="xs" fw={600} c={deadlineInfo.isOverdue ? 'red.7' : undefined}>
                        {deadlineInfo.formattedDate}
                      </Text>
                    </Group>
                  </Stack>
                </Paper>

                {/* 1.3 Danh sách Yếu tố Rủi ro (Risk Factors) */}
                <Paper p="sm" radius="md" withBorder>
                  <Stack gap="xs">
                    <Group gap={6}>
                      <ThemeIcon size="xs" color="orange" variant="light">
                        <IconAlertTriangle size={12} />
                      </ThemeIcon>
                      <Text size="xs" fw={700} c="dimmed">
                        YẾU TỐ CẢNH BÁO RỦI RO ({riskState?.factors?.length || 0})
                      </Text>
                    </Group>

                    {riskState?.factors && riskState.factors.length > 0 ? (
                      <Stack gap={6}>
                        {riskState.factors.map((rawFactor, idx) => {
                          const { label, value, color } = formatRiskFactor(rawFactor);
                          return (
                            <Group
                              key={idx}
                              justify="space-between"
                              align="center"
                              p={6}
                              bg="var(--mantine-color-gray-0)"
                              style={{ borderRadius: 6 }}
                            >
                              <Group gap="xs" wrap="nowrap">
                                <ThemeIcon size="xs" color={color} variant="light">
                                  <IconAlertTriangle size={10} />
                                </ThemeIcon>
                                <Text size="xs" fw={500}>
                                  {label}
                                </Text>
                              </Group>
                              {value ? (
                                <Badge size="xs" variant="outline" color={color}>
                                  {value}
                                </Badge>
                              ) : null}
                            </Group>
                          );
                        })}
                      </Stack>
                    ) : (
                      <Text size="xs" c="dimmed" ta="center" py="xs">
                        Không ghi nhận yếu tố rủi ro bất thường nào.
                      </Text>
                    )}
                  </Stack>
                </Paper>

                {/* 1.4 Danh sách Links (Blocked by / Depends on ...) */}
                <Paper p="sm" radius="md" withBorder>
                  <Stack gap="xs">
                    <Group gap={6}>
                      <ThemeIcon size="xs" color="indigo" variant="light">
                        <IconLink size={12} />
                      </ThemeIcon>
                      <Text size="xs" fw={700} c="dimmed">
                        LIÊN KẾT PHỤ THUỘC & BỊ CHẶN ({links.length})
                      </Text>
                    </Group>

                    {links.length > 0 ? (
                      <Stack gap={6}>
                        {links.map((link, idx) => {
                          const { otherKey, relationLabel, color } = formatLink(link, issueKey);
                          return (
                            <Group
                              key={idx}
                              justify="space-between"
                              align="center"
                              p={6}
                              bg="var(--mantine-color-gray-0)"
                              style={{ borderRadius: 6 }}
                            >
                              <Badge size="xs" color={color} variant="light">
                                {relationLabel}
                              </Badge>
                              {onSelectIssue ? (
                                <Button
                                  variant="subtle"
                                  size="xs"
                                  p={0}
                                  h="auto"
                                  color="blue"
                                  style={{ fontFamily: 'monospace' }}
                                  onClick={() => onSelectIssue(otherKey)}
                                  title={`Xem chi tiết ${otherKey}`}
                                >
                                  {otherKey}
                                </Button>
                              ) : (
                                <Text size="xs" fw={600} style={{ fontFamily: 'monospace' }}>
                                  {otherKey}
                                </Text>
                              )}
                            </Group>
                          );
                        })}
                      </Stack>
                    ) : (
                      <Text size="xs" c="dimmed" ta="center" py="xs">
                        Công việc này không có liên kết chặn hoặc phụ thuộc nào.
                      </Text>
                    )}
                  </Stack>
                </Paper>

                {/* 1.5 Nút Bỏ qua rủi ro mức này (Dismiss) */}
                {isDismissed ? (
                  <Paper p="xs" radius="md" bg="var(--mantine-color-gray-1)" withBorder>
                    <Group gap="xs" justify="center">
                      <ThemeIcon size="xs" color="gray" variant="light">
                        <IconShieldCheck size={14} />
                      </ThemeIcon>
                      <Text size="xs" c="dimmed">
                        Đã bỏ qua cảnh báo ở mức <strong>{riskState.level}</strong>. Hệ thống sẽ tạm
                        ngừng cảnh báo cho đến khi rủi ro tăng lên mức cao hơn.
                      </Text>
                    </Group>
                  </Paper>
                ) : canDismiss ? (
                  <Group justify="flex-end" pt="xs">
                    <Button
                      variant="outline"
                      color="orange"
                      size="xs"
                      leftSection={<IconEyeOff size={14} />}
                      onClick={() => setIsDismissModalOpen(true)}
                    >
                      Bỏ qua rủi ro mức này
                    </Button>
                  </Group>
                ) : null}
              </Stack>
            </Tabs.Panel>

            {/* TAB 2: ĐỀ XUẤT HÀNH ĐỘNG TỪ LLM (qwen3:1.7b) */}
            <Tabs.Panel value="suggestion">
              <Stack gap="md">
                {/* 2.1 Trạng thái đang phân tích (Pending: 202 Accepted, đang poll 3s) */}
                {isPendingSuggestion ? (
                  <Paper p="lg" radius="md" bg="var(--mantine-color-blue-light)" withBorder>
                    <Stack align="center" gap="sm" py="md">
                      <ThemeIcon size={48} radius="xl" color="blue" variant="light">
                        <IconSparkles size={24} />
                      </ThemeIcon>
                      <Title order={5} ta="center" fw={600}>
                        AI đang phân tích các yếu tố rủi ro và chuẩn bị phương án khắc phục...
                      </Title>
                      <Text size="xs" c="dimmed" ta="center" maw={380}>
                        Mô hình Ollama <strong>qwen3:1.7b</strong> đang đánh giá đồ thị rủi ro,
                        tổng hợp lịch sử thay đổi và tối ưu hóa giải pháp cho PM. Hệ thống tự động
                        kiểm tra kết quả mỗi 3 giây.
                      </Text>
                      <Progress
                        w="85%"
                        value={100}
                        animated
                        striped
                        size="sm"
                        radius="xl"
                        color="blue"
                        mt="xs"
                      />
                      <Loader size="sm" type="dots" color="blue" />
                    </Stack>
                  </Paper>
                ) : isSuggestionError ? (
                  <Alert
                    icon={<IconAlertCircle size={16} />}
                    title="Lỗi tải đề xuất AI"
                    color="red"
                    variant="light"
                  >
                    <Group justify="space-between">
                      <Text size="xs">
                        {suggestionError?.message || 'Không thể lấy đề xuất từ mô hình AI.'}
                      </Text>
                      <Button
                        size="xs"
                        color="red"
                        variant="outline"
                        onClick={() => refetchSuggestion()}
                      >
                        Thử lại
                      </Button>
                    </Group>
                  </Alert>
                ) : currentSuggestion ? (
                  /* 2.2 Trạng thái đã sẵn sàng (Ready) */
                  <Stack gap="md">
                    {/* Hộp Rationale (Giải thích của AI) */}
                    <Paper p="sm" radius="md" bg="var(--mantine-color-blue-light)" withBorder>
                      <Stack gap={6}>
                        <Group justify="space-between" align="center">
                          <Group gap="xs">
                            <ThemeIcon size="xs" color="blue" variant="filled">
                              <IconSparkles size={12} />
                            </ThemeIcon>
                            <Text fw={700} size="xs" c="blue.9">
                              PHÂN TÍCH & LÝ DO ĐỀ XUẤT (AI RATIONALE)
                            </Text>
                          </Group>
                          <Badge size="xs" variant="outline" color="blue">
                            {currentModel}
                          </Badge>
                        </Group>

                        {currentSuggestion.summary && (
                          <Text fw={600} size="xs" c="blue.9">
                            {currentSuggestion.summary}
                          </Text>
                        )}

                        {currentSuggestion.explanation && (
                          <Text
                            size="xs"
                            c="dark.7"
                            style={{ lineHeight: 1.6, whiteSpace: 'pre-wrap' }}
                          >
                            {currentSuggestion.explanation}
                          </Text>
                        )}
                      </Stack>
                    </Paper>

                    {/* Danh sách các yếu tố được AI dẫn chứng (factors_cited) */}
                    {currentSuggestion.factors_cited &&
                      currentSuggestion.factors_cited.length > 0 && (
                        <Stack gap={4}>
                          <Text size="xs" fw={700} c="dimmed">
                            YẾU TỐ RỦI RO ĐƯỢC AI DẪN CHỨNG:
                          </Text>
                          <Group gap={6} wrap="wrap">
                            {currentSuggestion.factors_cited.map((factor, idx) => (
                              <Badge key={idx} size="xs" variant="light" color="blue">
                                {factor}
                              </Badge>
                            ))}
                          </Group>
                        </Stack>
                      )}

                    {/* Danh sách hành động đề xuất (actions) */}
                    <Stack gap="xs">
                      <Group justify="space-between" align="center">
                        <Text size="xs" fw={700} c="dimmed">
                          DANH SÁCH HÀNH ĐỘNG ĐỀ XUẤT ({currentSuggestion.actions?.length || 0})
                        </Text>
                        <Text size="10px" c="dimmed">
                          Ollama {currentModel}
                        </Text>
                      </Group>

                      {currentSuggestion.actions && currentSuggestion.actions.length > 0 ? (
                        <Stack gap="xs">
                          {currentSuggestion.actions.map((act, idx) => {
                            const actionInfo = getActionTypeInfo(act.action_type);
                            const ActionIconComp = actionInfo.icon;
                            return (
                              <Paper key={idx} p="xs" radius="md" withBorder>
                                <Stack gap={6}>
                                  <Group justify="space-between" align="center">
                                    <Group gap="xs">
                                      <ThemeIcon size="xs" color={actionInfo.color} variant="light">
                                        <ActionIconComp size={12} />
                                      </ThemeIcon>
                                      <Text size="xs" fw={700} c={`${actionInfo.color}.8`}>
                                        {actionInfo.label}
                                      </Text>
                                    </Group>
                                    <Badge size="xs" variant="outline" color={actionInfo.color}>
                                      #{idx + 1}
                                    </Badge>
                                  </Group>

                                  {act.value && (
                                    <Group gap={6}>
                                      <Text size="xs" c="dimmed">
                                        Giá trị đề xuất:
                                      </Text>
                                      <Code color={actionInfo.color}>{act.value}</Code>
                                    </Group>
                                  )}

                                  {act.target && act.target !== act.value && (
                                    <Group gap={6}>
                                      <Text size="xs" c="dimmed">
                                        Đối tượng tác động:
                                      </Text>
                                      <Code>{act.target}</Code>
                                    </Group>
                                  )}

                                  {act.reason && (
                                    <Text
                                      size="xs"
                                      c="dimmed"
                                      style={{ fontStyle: 'italic', lineHeight: 1.5 }}
                                    >
                                      <Text span fw={600} fs="normal">
                                        Lý do:{' '}
                                      </Text>
                                      {act.reason}
                                    </Text>
                                  )}
                                </Stack>
                              </Paper>
                            );
                          })}
                        </Stack>
                      ) : (
                        <Text size="xs" c="dimmed" ta="center" py="xs">
                          Mô hình AI không đưa ra hành động can thiệp trực tiếp nào.
                        </Text>
                      )}
                    </Stack>

                    {/* Nút bấm Xem xét & Xác nhận hành động (Dành cho PM/Admin) */}
                    <Box pt="xs">
                      {isPm ? (
                        <Button
                          fullWidth
                          size="md"
                          color="blue"
                          leftSection={<IconChecklist size={18} />}
                          onClick={() => {
                            if (onOpenConfirmAction) {
                              onOpenConfirmAction({
                                issueKey,
                                suggestion: currentSuggestion,
                                issue,
                                suggestionId:
                                  issueData?.suggestion?.id ||
                                  suggestionData?.suggestion_id ||
                                  null,
                              });
                            }
                          }}
                        >
                          Xem xét & Xác nhận hành động
                        </Button>
                      ) : (
                        <Paper p="xs" radius="sm" bg="var(--mantine-color-gray-1)" withBorder>
                          <Text size="xs" c="dimmed" ta="center">
                            Chỉ Quản lý dự án (PM) hoặc Quản trị viên (Admin) mới có quyền xem xét
                            và xác nhận áp dụng hành động lên Jira.
                          </Text>
                        </Paper>
                      )}
                    </Box>
                  </Stack>
                ) : (
                  /* Trạng thái chưa có đề xuất nào */
                  <Paper p="lg" radius="md" withBorder>
                    <Stack align="center" gap="sm" py="md">
                      <ThemeIcon size={44} radius="xl" color="gray" variant="light">
                        <IconSparkles size={22} />
                      </ThemeIcon>
                      <Text size="xs" c="dimmed" ta="center">
                        Chưa có đề xuất nào được tạo cho công việc này.
                      </Text>
                      <Button
                        size="xs"
                        variant="light"
                        color="blue"
                        leftSection={<IconRefresh size={14} />}
                        onClick={() => refetchSuggestion()}
                      >
                        Yêu cầu AI phân tích ngay
                      </Button>
                    </Stack>
                  </Paper>
                )}
              </Stack>
            </Tabs.Panel>
          </Tabs>
        </Stack>
      </Card>

      {/* Modal Popup xác nhận Bỏ qua rủi ro */}
      <Modal
        opened={isDismissModalOpen}
        onClose={() => !isDismissing && setIsDismissModalOpen(false)}
        title="Xác nhận bỏ qua cảnh báo rủi ro"
        centered
        radius="md"
        size="md"
      >
        <Stack gap="md">
          <Text size="sm">
            Bạn có chắc chắn muốn bỏ qua cảnh báo rủi ro mức{' '}
            <strong style={{ color: 'var(--mantine-color-orange-7)' }}>
              {riskState?.level || 'hiện tại'}
            </strong>{' '}
            cho công việc <strong>{issueKey}</strong>?
          </Text>

          <Text size="xs" c="dimmed">
            Hệ thống sẽ tạm dừng cảnh báo đối với công việc này cho đến khi ghi nhận biến động rủi ro
            ở mức cao hơn.
          </Text>

          <Textarea
            label="Lý do bỏ qua (tùy chọn)"
            placeholder="Ví dụ: Đã trao đổi giải tỏa áp lực thời hạn với khách hàng..."
            value={dismissReason}
            onChange={(e) => setDismissReason(e.currentTarget.value)}
            minRows={3}
          />

          <Group justify="flex-end" gap="xs" mt="sm">
            <Button
              variant="default"
              size="xs"
              onClick={() => setIsDismissModalOpen(false)}
              disabled={isDismissing}
            >
              Hủy bỏ
            </Button>
            <Button
              color="orange"
              size="xs"
              loading={isDismissing}
              onClick={handleConfirmDismiss}
            >
              Xác nhận bỏ qua
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
