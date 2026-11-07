import React, { useState, useEffect } from 'react';
import {
  Modal,
  Button,
  Group,
  Stack,
  Text,
  Title,
  Badge,
  Paper,
  Checkbox,
  TextInput,
  Textarea,
  Select,
  Alert,
  Divider,
  ThemeIcon,
  Box,
  Code,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconCheck,
  IconAlertCircle,
  IconInfoCircle,
  IconRefresh,
  IconCalendarTime,
  IconUserCheck,
  IconArrowsExchange,
  IconMessageDots,
  IconLockOpen,
  IconSparkles,
  IconSend,
  IconX,
  IconAlertTriangle,
} from '@tabler/icons-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import { proposeAction, confirmAction, getIssueTransitions } from '../api/client';

/**
 * Định nghĩa thông tin nhãn, màu sắc và icon cho từng loại hành động
 */
const ACTION_TYPE_META = {
  adjust_deadline: {
    label: 'Gia hạn thời gian (Due Date)',
    color: 'blue',
    icon: IconCalendarTime,
    inputLabel: 'Hạn chót mới (YYYY-MM-DD)',
    placeholder: '2026-11-30',
  },
  change_assignee: {
    label: 'Đổi người phụ trách (Assignee)',
    color: 'teal',
    icon: IconUserCheck,
    inputLabel: 'Người phụ trách mới (accountId hoặc Tên)',
    placeholder: 'Ví dụ: 712020:xxx hoặc unassigned',
  },
  change_status: {
    label: 'Chuyển trạng thái (Workflow Status)',
    color: 'orange',
    icon: IconArrowsExchange,
    inputLabel: 'Trạng thái Jira đích',
    placeholder: 'Ví dụ: In Progress, In Review, Done',
  },
  add_comment: {
    label: 'Thêm bình luận trao đổi (Jira Comment)',
    color: 'violet',
    icon: IconMessageDots,
    inputLabel: 'Nội dung bình luận ghi vào Jira',
    placeholder: 'Nhập nội dung trao đổi hoặc nhắc nhở tiến độ...',
  },
  escalate_blocker: {
    label: 'Cảnh báo & gỡ chặn (Escalate Blocker)',
    color: 'red',
    icon: IconLockOpen,
    inputLabel: 'Nội dung giải trình gỡ vướng blocker',
    placeholder: 'Mô tả chi tiết nguyên nhân nghẽn và đề xuất chỉ đạo tháo gỡ...',
  },
};

function StatusTransitionInput({ issueKey, value, onChange, disabled }) {
  const meta = ACTION_TYPE_META.change_status;
  const { data, isLoading, isError } = useQuery({
    queryKey: ['issue-transitions', issueKey],
    queryFn: () => getIssueTransitions(issueKey),
    enabled: Boolean(issueKey),
    retry: false,
    staleTime: 0,
  });

  if (isError) {
    return (
      <TextInput
        label={meta.inputLabel}
        placeholder={meta.placeholder}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.currentTarget.value)}
        size="xs"
        description="Không tải được danh sách chuyển trạng thái từ Jira. Nhập tên trạng thái đích."
      />
    );
  }

  const transitions = [...new Map((data || []).map((t) => [t.to_status, t])).values()];
  const options = transitions.map((t) => ({
    value: t.to_status,
    label: t.name && t.name !== t.to_status ? `${t.to_status} (${t.name})` : t.to_status,
  }));
  const empty = !isLoading && options.length === 0;
  return (
    <Select
      label={meta.inputLabel}
      placeholder={isLoading ? 'Đang tải trạng thái từ Jira...' : 'Chọn trạng thái đích'}
      data={options}
      value={value || null}
      onChange={(next) => onChange(next || '')}
      disabled={disabled || isLoading || empty}
      size="xs"
      description={
        empty
          ? 'Jira không cho phép chuyển trạng thái nào từ trạng thái hiện tại.'
          : 'Chỉ hiện các bước chuyển hợp lệ trên workflow Jira'
      }
    />
  );
}

function transitionErrorMessage(detail) {
  const allowed = detail.available.length ? ` Có thể chuyển sang: ${detail.available.join(', ')}.` : '';
  return `Jira không cho phép chuyển sang trạng thái "${detail.target}".${allowed}`;
}

/**
 * Định dạng mốc thời gian ISO cho thông báo xung đột
 */
function formatTimestamp(isoStr) {
  if (!isoStr) return 'không xác định';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoStr;
  }
}

/**
 * ActionConfirmModal
 * Modal cho phép PM xem xét, tinh chỉnh các action item đề xuất từ LLM,
 * kiểm tra xung đột lạc quan (409 Conflict) và xác nhận ghi ngược vào Jira Cloud.
 */
export default function ActionConfirmModal({
  opened,
  onClose,
  proposalData,
  onSuccess,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [items, setItems] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [conflictError, setConflictError] = useState(null);
  const [generalError, setGeneralError] = useState(null);

  const { issueKey, suggestion, issue, suggestionId } = proposalData || {};

  // Khởi tạo danh sách items khi mở modal hoặc thay đổi proposalData
  useEffect(() => {
    if (opened && suggestion?.actions && Array.isArray(suggestion.actions)) {
      const initialItems = suggestion.actions.map((act) => {
        let defaultVal = '';
        if (act.value !== undefined && act.value !== null && String(act.value).trim() !== '') {
          defaultVal = String(act.value);
        } else if (act.target !== undefined && act.target !== null && String(act.target).trim() !== '') {
          defaultVal = String(act.target);
        } else if (
          act.reason &&
          (act.action_type === 'add_comment' || act.action_type === 'escalate_blocker')
        ) {
          defaultVal = String(act.reason);
        }

        return {
          enabled: true,
          action_type: act.action_type,
          target: act.target || '',
          value: defaultVal,
          reason: act.reason || '',
        };
      });

      setItems(initialItems);
      setConflictError(null);
      setGeneralError(null);
      setIsSubmitting(false);
    } else if (!opened) {
      setConflictError(null);
      setGeneralError(null);
      setIsSubmitting(false);
    }
  }, [opened, suggestion, proposalData]);

  // Bật / tắt checkbox từng item
  const handleToggleItem = (index) => {
    setItems((prev) =>
      prev.map((item, idx) =>
        idx === index ? { ...item, enabled: !item.enabled } : item
      )
    );
  };

  // Cập nhật giá trị input của từng item
  const handleUpdateValue = (index, newValue) => {
    setItems((prev) =>
      prev.map((item, idx) =>
        idx === index ? { ...item, value: newValue } : item
      )
    );
  };

  // Bật / tắt tất cả checkbox
  const handleToggleAll = (enable) => {
    setItems((prev) => prev.map((item) => ({ ...item, enabled: enable })));
  };

  // Xử lý làm mới dữ liệu task khi gặp xung đột 409
  const handleRefreshTaskData = async () => {
    if (issueKey) {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['issue-detail', issueKey] }),
        queryClient.invalidateQueries({ queryKey: ['issue-suggestion', issueKey] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-board'] }),
      ]);
    }
    notifications.show({
      title: 'Đang làm mới',
      message: 'Đang tải lại dữ liệu mới nhất của công việc từ Jira...',
      color: 'blue',
      icon: <IconRefresh size={18} />,
    });
    setConflictError(null);
    onClose();
  };

  // Quy trình 2 bước: propose -> confirm (kiểm tra lạc quan 409)
  const handleConfirmAndApply = async () => {
    setGeneralError(null);
    setConflictError(null);

    const enabledItems = items.filter((item) => item.enabled);
    if (enabledItems.length === 0) {
      notifications.show({
        title: 'Chưa chọn hành động',
        message: 'Vui lòng đánh dấu chọn ít nhất một hành động để thực thi ghi Jira.',
        color: 'yellow',
        icon: <IconAlertTriangle size={18} />,
      });
      return;
    }

    if (!issueKey) {
      setGeneralError('Mã công việc không hợp lệ hoặc bị thiếu.');
      return;
    }

    setIsSubmitting(true);
    try {
      // Chuẩn bị payload danh sách hành động đã chọn
      const itemsToApply = enabledItems.map((item) => ({
        action_type: item.action_type,
        target: item.target || undefined,
        value: item.value !== undefined ? item.value : undefined,
        reason: item.reason || undefined,
      }));

      // Bước 1: Tạo action proposal (Draft)
      const proposeRes = await proposeAction(
        issueKey,
        suggestionId || null,
        itemsToApply
      );

      const actionId = proposeRes?.action_id;
      if (!actionId) {
        throw new Error('Máy chủ không trả về mã đề xuất hành động (action_id).');
      }

      // Bước 2: Xác nhận thực thi kèm mốc expected_updated để kiểm tra khóa lạc quan
      const expectedUpdated = issue?.updated_at || new Date().toISOString();
      await confirmAction(actionId, expectedUpdated);

      // Bước 3: Thông báo thành công và gọi callback làm mới
      notifications.show({
        title: 'Cập nhật Jira thành công!',
        message: `Đã áp dụng thành công ${enabledItems.length} hành động cho công việc ${issueKey}.`,
        color: 'teal',
        icon: <IconCheck size={18} />,
      });

      if (onSuccess) {
        await onSuccess();
      }
      onClose();
    } catch (err) {
      if (err.status === 409) {
        // Xử lý xung đột lạc quan
        const detail = err.data?.detail || err.data || {};
        setConflictError({
          current_updated: detail.current_updated,
          expected_updated: detail.expected_updated || issue?.updated_at,
          message:
            typeof detail === 'string'
              ? detail
              : detail.message || detail.error || null,
        });
      } else if (err.status === 422 && err.data?.detail?.error === 'transition_not_allowed') {
        setGeneralError(transitionErrorMessage(err.data.detail));
      } else {
        setGeneralError(
          err.message || 'Đã có lỗi xảy ra trong quá trình ghi dữ liệu lên Jira.'
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const enabledCount = items.filter((i) => i.enabled).length;
  const pmName = user?.name || user?.email || 'Quản lý dự án';

  // Render input field tương ứng cho từng loại hành động
  const renderItemInput = (item, index) => {
    const meta = ACTION_TYPE_META[item.action_type] || {
      inputLabel: 'Giá trị can thiệp',
      placeholder: 'Nhập giá trị...',
    };

    switch (item.action_type) {
      case 'adjust_deadline':
        return (
          <TextInput
            label={meta.inputLabel}
            placeholder={meta.placeholder}
            value={item.value}
            disabled={!item.enabled || isSubmitting}
            onChange={(e) => handleUpdateValue(index, e.currentTarget.value)}
            size="xs"
            description="Định dạng YYYY-MM-DD (ví dụ: 2026-11-30)"
          />
        );

      case 'change_assignee':
        return (
          <TextInput
            label={meta.inputLabel}
            placeholder={meta.placeholder}
            value={item.value}
            disabled={!item.enabled || isSubmitting}
            onChange={(e) => handleUpdateValue(index, e.currentTarget.value)}
            size="xs"
            description="Mã accountId hoặc unassigned để hủy phân công"
          />
        );

      case 'change_status':
        return (
          <StatusTransitionInput
            issueKey={issueKey}
            value={item.value}
            disabled={!item.enabled || isSubmitting}
            onChange={(value) => handleUpdateValue(index, value)}
          />
        );

      case 'add_comment':
        return (
          <Textarea
            label={meta.inputLabel}
            placeholder={meta.placeholder}
            value={item.value}
            disabled={!item.enabled || isSubmitting}
            onChange={(e) => handleUpdateValue(index, e.currentTarget.value)}
            minRows={2}
            autosize
            size="xs"
          />
        );

      case 'escalate_blocker':
        return (
          <Textarea
            label={meta.inputLabel}
            placeholder={meta.placeholder}
            value={item.value}
            disabled={!item.enabled || isSubmitting}
            onChange={(e) => handleUpdateValue(index, e.currentTarget.value)}
            minRows={2}
            autosize
            size="xs"
          />
        );

      default:
        return (
          <TextInput
            label={meta.inputLabel}
            placeholder={meta.placeholder}
            value={item.value}
            disabled={!item.enabled || isSubmitting}
            onChange={(e) => handleUpdateValue(index, e.currentTarget.value)}
            size="xs"
          />
        );
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={() => {
        if (!isSubmitting) onClose();
      }}
      title={
        <Group gap="xs">
          <ThemeIcon size="md" color="blue" variant="light" radius="sm">
            <IconSend size={18} />
          </ThemeIcon>
          <Box>
            <Group gap="xs" align="center">
              <Title order={5}>Xác nhận & Ghi Jira</Title>
              {issueKey && (
                <Badge color="blue" variant="filled" style={{ fontFamily: 'monospace' }}>
                  {issueKey}
                </Badge>
              )}
            </Group>
            {issue?.summary && (
              <Text size="xs" c="dimmed" lineClamp={1} maw={450}>
                {issue.summary}
              </Text>
            )}
          </Box>
        </Group>
      }
      size="lg"
      radius="md"
      closeOnClickOutside={!isSubmitting}
      closeOnEscape={!isSubmitting}
    >
      <Stack gap="md">
        {/* Alert thông báo quy trình và PM attribution */}
        <Alert
          icon={<IconInfoCircle size={18} />}
          color="blue"
          variant="light"
          radius="md"
        >
          <Text size="xs" lh={1.6}>
            Các thay đổi đã chọn sẽ được tài khoản dịch vụ ghi trực tiếp vào Jira Cloud kèm
            chú thích xác nhận từ PM <strong>{pmName}</strong> và bắn cảnh báo [Đã xử lý] lên Slack.
          </Text>
        </Alert>

        {/* Thông báo xung đột lạc quan (409 Conflict) */}
        {conflictError && (
          <Alert
            icon={<IconAlertCircle size={20} />}
            title="Xung đột dữ liệu Jira (409 Conflict)"
            color="red"
            variant="filled"
            radius="md"
          >
            <Stack gap="xs">
              <Text size="xs" lh={1.6}>
                Xung đột dữ liệu Jira! Task này vừa được thay đổi trực tiếp trên Jira lúc{' '}
                <strong>{formatTimestamp(conflictError.current_updated)}</strong> (khác mốc{' '}
                <strong>{formatTimestamp(conflictError.expected_updated)}</strong>). Vui lòng
                tải lại trang để xem cập nhật mới nhất.
              </Text>
              <Group justify="flex-end">
                <Button
                  size="xs"
                  variant="white"
                  color="red"
                  leftSection={<IconRefresh size={14} />}
                  onClick={handleRefreshTaskData}
                >
                  Làm mới dữ liệu task
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}

        {/* Thông báo lỗi thông thường */}
        {generalError && (
          <Alert
            icon={<IconAlertCircle size={18} />}
            title="Thao tác thất bại"
            color="red"
            variant="light"
            radius="md"
            withCloseButton
            onClose={() => setGeneralError(null)}
          >
            <Text size="xs">{generalError}</Text>
          </Alert>
        )}

        {/* Danh sách hành động đề xuất từ AI */}
        <Box>
          <Group justify="space-between" align="center" mb="xs">
            <Text size="sm" fw={600}>
              Danh sách hành động can thiệp ({items.length})
            </Text>
            {items.length > 0 && (
              <Group gap="xs">
                <Button
                  variant="subtle"
                  size="compact-xs"
                  onClick={() => handleToggleAll(true)}
                  disabled={isSubmitting}
                >
                  Chọn tất cả
                </Button>
                <Text size="xs" c="dimmed">
                  |
                </Text>
                <Button
                  variant="subtle"
                  size="compact-xs"
                  color="gray"
                  onClick={() => handleToggleAll(false)}
                  disabled={isSubmitting}
                >
                  Bỏ chọn
                </Button>
              </Group>
            )}
          </Group>

          {items.length === 0 ? (
            <Paper p="md" withBorder radius="md">
              <Text size="xs" c="dimmed" ta="center">
                Mô hình AI không đưa ra hành động can thiệp trực tiếp nào cho công việc này.
              </Text>
            </Paper>
          ) : (
            <Stack gap="sm">
              {items.map((item, idx) => {
                const meta = ACTION_TYPE_META[item.action_type] || {
                  label: item.action_type || 'Hành động',
                  color: 'gray',
                  icon: IconSparkles,
                };
                const IconComp = meta.icon;

                return (
                  <Paper
                    key={idx}
                    p="sm"
                    radius="md"
                    withBorder
                    style={{
                      borderColor: item.enabled
                        ? `var(--mantine-color-${meta.color}-outline)`
                        : 'var(--mantine-color-gray-3)',
                      backgroundColor: item.enabled
                        ? 'var(--mantine-color-body)'
                        : 'var(--mantine-color-gray-0)',
                      opacity: item.enabled ? 1 : 0.65,
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <Stack gap="xs">
                      {/* Tiêu đề & Checkbox hành động */}
                      <Group justify="space-between" align="center">
                        <Group gap="xs">
                          <Checkbox
                            checked={item.enabled}
                            onChange={() => handleToggleItem(idx)}
                            disabled={isSubmitting}
                            size="sm"
                            aria-label={`Bật tắt hành động ${meta.label}`}
                          />
                          <ThemeIcon size="sm" color={meta.color} variant="light">
                            <IconComp size={14} />
                          </ThemeIcon>
                          <Text
                            size="xs"
                            fw={700}
                            c={item.enabled ? `${meta.color}.8` : 'dimmed'}
                          >
                            {meta.label}
                          </Text>
                        </Group>

                        <Badge
                          size="xs"
                          variant={item.enabled ? 'light' : 'outline'}
                          color={meta.color}
                        >
                          #{idx + 1}
                        </Badge>
                      </Group>

                      {/* Lý do đề xuất từ mô hình AI */}
                      {item.reason && (
                        <Text
                          size="xs"
                          c="dimmed"
                          pl={28}
                          style={{ fontStyle: 'italic', lineHeight: 1.4 }}
                        >
                          <Text span fw={600} fs="normal">
                            Lý do từ AI:{' '}
                          </Text>
                          {item.reason}
                        </Text>
                      )}

                      {/* Đối tượng tác động (nếu có và khác value) */}
                      {item.target && item.target !== item.value && (
                        <Group gap={6} pl={28}>
                          <Text size="xs" c="dimmed">
                            Đối tượng tác động:
                          </Text>
                          <Code>{item.target}</Code>
                        </Group>
                      )}

                      {/* Ô nhập liệu tinh chỉnh giá trị */}
                      <Box pl={28} pt={2}>
                        {renderItemInput(item, idx)}
                      </Box>
                    </Stack>
                  </Paper>
                );
              })}
            </Stack>
          )}
        </Box>

        <Divider my="xs" />

        {/* Nút hành động */}
        <Group justify="space-between" align="center">
          <Button
            variant="default"
            size="sm"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Đóng / Hủy
          </Button>

          <Button
            color="blue"
            size="sm"
            leftSection={<IconSend size={16} />}
            loading={isSubmitting}
            disabled={isSubmitting || enabledCount === 0}
            onClick={handleConfirmAndApply}
          >
            Xác nhận & Ghi Jira ({enabledCount})
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
