import React, { useState } from 'react';
import {
  Badge,
  Button,
  Group,
  Modal,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  IconDownload,
  IconEye,
  IconEyeOff,
  IconFileTypePdf,
  IconRefresh,
  IconSearch,
} from '@tabler/icons-react';
import {
  downloadChatReport,
  getChatReports,
  hideChatReport,
  unhideChatReport,
} from '../../api/client';
import { useAuth } from '../../context/AuthContext';

function previewLine(report) {
  const raw = report.preview || report.filename || '';
  const line = String(raw).split('\n').find((part) => part.trim()) || '';
  return line.length > 80 ? `${line.slice(0, 77)}…` : line || '—';
}

function formatReportDate(value) {
  if (!value) return '—';
  // Backend sends YYYY-MM-DD; avoid timezone shift from Date parsing.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-');
    return `${d}/${m}/${y}`;
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString('vi-VN');
  } catch {
    return String(value);
  }
}

async function saveBlob(report, format) {
  const { blob, filename } = await downloadChatReport(report.id, format);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || report.filename || `report-${report.id}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function ReportFileManager({
  project,
  onOpenSettings,
  onPreview,
  onRegenerate,
  regeneratePending = false,
  canHide = true,
  canUnhide = true,
  showPdfDownload = true,
  manage = false,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [visibility, setVisibility] = useState('visible');
  const [confirmHideId, setConfirmHideId] = useState(null);

  const queryVisibility = manage ? visibility : 'visible';
  const querySearch = manage ? search : '';

  const reports = useQuery({
    queryKey: ['chat-reports', project, queryVisibility, querySearch],
    queryFn: () => getChatReports(project, { q: querySearch, visibility: queryVisibility }),
    enabled: Boolean(project),
    staleTime: 15000,
  });

  const download = useMutation({
    mutationFn: ({ report, format }) => saveBlob(report, format),
  });

  const hide = useMutation({
    mutationFn: (id) => hideChatReport(id),
    onSuccess: () => {
      setConfirmHideId(null);
      queryClient.invalidateQueries({ queryKey: ['chat-reports', project] });
    },
  });

  const unhide = useMutation({
    mutationFn: (id) => unhideChatReport(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-reports', project] });
    },
  });

  const items = reports.data ?? [];
  const confirmReport = items.find((item) => item.id === confirmHideId) || null;

  return (
    <Stack gap="sm" className="pm-chat-files">
      <Group justify="space-between" align="center" wrap="wrap">
        <Text className="pm-chat-title">Báo cáo sức khỏe</Text>
        <Group gap="xs">
          {manage && onRegenerate ? (
            <Button
              className="pm-chat-btn-primary"
              size="compact-sm"
              leftSection={<IconRefresh size={14} />}
              loading={regeneratePending}
              onClick={onRegenerate}
              style={{ height: 32, padding: '0 16px' }}
            >
              Tạo lại hôm nay
            </Button>
          ) : null}
          {onOpenSettings && (
            <Button variant="subtle" size="compact-sm" className="pm-chat-btn-subtle" onClick={onOpenSettings}>
              Đổi lịch
            </Button>
          )}
        </Group>
      </Group>

      {manage ? (
        <Stack gap="xs">
          <TextInput
            className="pm-chat-input"
            placeholder="Tìm theo ngày, tiêu đề, dự án…"
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
          />
          <SegmentedControl
            size="xs"
            value={visibility}
            onChange={setVisibility}
            data={[
              { label: 'Đang hiện', value: 'visible' },
              { label: 'Đã ẩn', value: 'hidden' },
              { label: 'Tất cả', value: 'all' },
            ]}
          />
        </Stack>
      ) : null}

      {reports.isError && (
        <Text className="pm-chat-error">{reports.error?.message || 'Không tải được danh sách báo cáo.'}</Text>
      )}

      {!reports.isLoading && items.length === 0 && !reports.isError && (
        <Text className="pm-chat-meta">
          {manage && (search.trim() || visibility !== 'visible')
            ? 'Không có báo cáo khớp bộ lọc.'
            : 'Chưa có báo cáo. PM có thể tạo on-demand hoặc đặt lịch trong Cài đặt.'}
          {!manage && onOpenSettings ? (
            <>
              {' '}
              <Button variant="subtle" size="compact-xs" className="pm-chat-link-btn" onClick={onOpenSettings}>
                Mở Cài đặt
              </Button>
            </>
          ) : null}
        </Text>
      )}

      <Stack gap={6}>
        {items.map((report) => {
          const id = report.id;
          const isHidden = Boolean(report.hidden);
          const isOwner = report.owner_user_id == null || report.owner_user_id === user?.id;
          const allowHide = canHide && isOwner && !isHidden;
          const allowUnhide = manage && canUnhide && isOwner && isHidden;
          const downloadingMd =
            download.isPending && download.variables?.report?.id === id && download.variables?.format === 'md';
          const downloadingPdf =
            download.isPending && download.variables?.report?.id === id && download.variables?.format === 'pdf';
          return (
            <div
              key={id}
              className="pm-chat-file-row"
              data-clickable={onPreview && !isHidden ? 'true' : undefined}
              data-hidden={isHidden ? 'true' : undefined}
              onClick={onPreview && !isHidden ? () => onPreview(report) : undefined}
              onKeyDown={
                onPreview && !isHidden
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onPreview(report);
                      }
                    }
                  : undefined
              }
              role={onPreview && !isHidden ? 'button' : undefined}
              tabIndex={onPreview && !isHidden ? 0 : undefined}
              style={isHidden ? { opacity: 0.72 } : undefined}
            >
              <Stack gap={4}>
                <Group gap="xs" wrap="wrap">
                  <Text className="pm-chat-label">{formatReportDate(report.report_date)}</Text>
                  <Text className="pm-chat-meta">{report.slot_hhmm || '—'}</Text>
                  <Text className="pm-chat-meta">{report.project_key || project}</Text>
                  {isHidden ? (
                    <Badge size="xs" variant="outline" color="gray">
                      Đã ẩn
                    </Badge>
                  ) : null}
                </Group>
                <Text className="pm-chat-body">{previewLine(report)}</Text>
                <Group gap="xs" onClick={(event) => event.stopPropagation()}>
                  {onPreview && !isHidden ? (
                    <Tooltip label="Xem trong app" withArrow>
                      <Button
                        className="pm-chat-btn-secondary"
                        size="compact-sm"
                        leftSection={<IconEye size={14} />}
                        onClick={() => onPreview(report)}
                        style={{ height: 32, padding: '0 16px' }}
                      >
                        Xem
                      </Button>
                    </Tooltip>
                  ) : null}
                  <Tooltip label="Tải Markdown" withArrow>
                    <Button
                      className="pm-chat-btn-secondary"
                      size="compact-sm"
                      leftSection={<IconDownload size={14} />}
                      loading={downloadingMd}
                      onClick={() => download.mutate({ report, format: 'md' })}
                      style={{ height: 32, padding: '0 16px' }}
                    >
                      MD
                    </Button>
                  </Tooltip>
                  {showPdfDownload ? (
                    <Tooltip label="Tải PDF" withArrow>
                      <Button
                        className="pm-chat-btn-secondary"
                        size="compact-sm"
                        leftSection={<IconFileTypePdf size={14} />}
                        loading={downloadingPdf}
                        onClick={() => download.mutate({ report, format: 'pdf' })}
                        style={{ height: 32, padding: '0 16px' }}
                      >
                        PDF
                      </Button>
                    </Tooltip>
                  ) : null}
                  {allowHide ? (
                    <Button
                      className="pm-chat-btn-secondary"
                      size="compact-sm"
                      leftSection={<IconEyeOff size={14} />}
                      onClick={() => setConfirmHideId(id)}
                      style={{ height: 32, padding: '0 16px' }}
                    >
                      Ẩn
                    </Button>
                  ) : null}
                  {allowUnhide ? (
                    <Button
                      className="pm-chat-btn-primary"
                      size="compact-sm"
                      leftSection={<IconEye size={14} />}
                      loading={unhide.isPending && unhide.variables === id}
                      onClick={() => unhide.mutate(id)}
                      style={{ height: 32, padding: '0 16px' }}
                    >
                      Hiện lại
                    </Button>
                  ) : null}
                </Group>
                {download.isError && download.variables?.report?.id === id && (
                  <Text className="pm-chat-error">{download.error?.message || 'Không tải được.'}</Text>
                )}
                {hide.isError && hide.variables === id && (
                  <Text className="pm-chat-error">{hide.error?.message || 'Không ẩn được.'}</Text>
                )}
                {unhide.isError && unhide.variables === id && (
                  <Text className="pm-chat-error">{unhide.error?.message || 'Không hiện lại được.'}</Text>
                )}
              </Stack>
            </div>
          );
        })}
      </Stack>

      <Modal
        opened={Boolean(confirmHideId)}
        onClose={() => setConfirmHideId(null)}
        title="Ẩn báo cáo khỏi danh sách?"
        centered
        classNames={{ content: 'pm-chat-scope' }}
      >
        <Stack gap="md">
          <Text className="pm-chat-body">
            Báo cáo
            {confirmReport
              ? ` ${formatReportDate(confirmReport.report_date)} · ${confirmReport.slot_hhmm || ''}`
              : ''}{' '}
            sẽ biến khỏi file manager. Tin nhắn trên Chat vẫn giữ — không xóa file trên đĩa.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button className="pm-chat-btn-secondary" onClick={() => setConfirmHideId(null)}>
              Hủy
            </Button>
            <Button
              className="pm-chat-btn-primary"
              loading={hide.isPending && hide.variables === confirmHideId}
              onClick={() => confirmHideId && hide.mutate(confirmHideId)}
            >
              Ẩn khỏi danh sách
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
