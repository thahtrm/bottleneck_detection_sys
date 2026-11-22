import React, { useMemo, useState } from 'react';
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
  UnstyledButton,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  IconChevronDown,
  IconChevronRight,
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

/** Newest → oldest by report_date, then slot, then id. */
function compareReportsNewestFirst(a, b) {
  const dateCmp = String(b.report_date || '').localeCompare(String(a.report_date || ''));
  if (dateCmp !== 0) return dateCmp;
  const slotCmp = String(b.slot_hhmm || '').localeCompare(String(a.slot_hhmm || ''));
  if (slotCmp !== 0) return slotCmp;
  return (Number(b.id) || 0) - (Number(a.id) || 0);
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
  hideHeader = false,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 250);
  const [visibility, setVisibility] = useState('visible');
  const [confirmHideId, setConfirmHideId] = useState(null);
  const [listOpen, setListOpen] = useState(true);

  const queryVisibility = manage ? visibility : 'visible';
  const querySearch = debouncedSearch.trim();

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

  const items = useMemo(
    () => [...(reports.data ?? [])].sort(compareReportsNewestFirst),
    [reports.data],
  );
  const confirmReport = items.find((item) => item.id === confirmHideId) || null;

  const showList = hideHeader || listOpen;

  return (
    <Stack gap="sm" className="pm-chat-files">
      {!hideHeader ? (
        <Group justify="space-between" align="center" wrap="wrap" gap="xs">
          <UnstyledButton
            className="pm-chat-files-collapse-btn"
            onClick={() => setListOpen((open) => !open)}
            aria-expanded={listOpen}
            aria-controls="pm-chat-reports-list"
          >
            <Group gap={6} wrap="nowrap">
              {listOpen ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
              <Text className="pm-chat-title">Báo cáo sức khỏe</Text>
              <Badge size="xs" variant="light" color="gray">
                {items.length}
              </Badge>
            </Group>
          </UnstyledButton>
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
      ) : null}

      {showList ? (
        <>
          <TextInput
            className="pm-chat-input"
            placeholder="Tìm theo ngày, tiêu đề, dự án…"
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
            aria-label="Tìm báo cáo sức khỏe"
          />
          {manage ? (
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
          ) : null}

          {reports.isError && (
            <Text className="pm-chat-error">{reports.error?.message || 'Không tải được danh sách báo cáo.'}</Text>
          )}

          {!reports.isLoading && items.length === 0 && !reports.isError && (
            <Text className="pm-chat-meta">
              {search.trim() || (manage && visibility !== 'visible')
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

          <div id="pm-chat-reports-list" className="pm-chat-files-list" role="list">
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
                  role="listitem"
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
                  tabIndex={onPreview && !isHidden ? 0 : undefined}
                  style={isHidden ? { opacity: 0.72 } : undefined}
                >
                  <Stack gap={2}>
                    <Group gap="xs" wrap="nowrap" justify="space-between">
                      <Group gap={6} wrap="wrap" style={{ minWidth: 0 }}>
                        <Text className="pm-chat-label">{formatReportDate(report.report_date)}</Text>
                        <Text className="pm-chat-meta">{report.slot_hhmm || '—'}</Text>
                        <Text className="pm-chat-meta">{report.project_key || project}</Text>
                        {isHidden ? (
                          <Badge size="xs" variant="outline" color="gray">
                            Đã ẩn
                          </Badge>
                        ) : null}
                      </Group>
                      <Group gap={4} wrap="nowrap" onClick={(event) => event.stopPropagation()}>
                        {onPreview && !isHidden ? (
                          <Tooltip label="Xem trong app" withArrow>
                            <Button
                              className="pm-chat-btn-secondary"
                              size="compact-xs"
                              aria-label="Xem"
                              onClick={() => onPreview(report)}
                              style={{ height: 28, width: 28, padding: 0 }}
                            >
                              <IconEye size={14} />
                            </Button>
                          </Tooltip>
                        ) : null}
                        <Tooltip label="Tải Markdown" withArrow>
                          <Button
                            className="pm-chat-btn-secondary"
                            size="compact-xs"
                            aria-label="Tải Markdown"
                            loading={downloadingMd}
                            onClick={() => download.mutate({ report, format: 'md' })}
                            style={{ height: 28, width: 28, padding: 0 }}
                          >
                            <IconDownload size={14} />
                          </Button>
                        </Tooltip>
                        {showPdfDownload ? (
                          <Tooltip label="Tải PDF" withArrow>
                            <Button
                              className="pm-chat-btn-secondary"
                              size="compact-xs"
                              aria-label="Tải PDF"
                              loading={downloadingPdf}
                              onClick={() => download.mutate({ report, format: 'pdf' })}
                              style={{ height: 28, width: 28, padding: 0 }}
                            >
                              <IconFileTypePdf size={14} />
                            </Button>
                          </Tooltip>
                        ) : null}
                        {allowHide ? (
                          <Tooltip label="Ẩn khỏi danh sách" withArrow>
                            <Button
                              className="pm-chat-btn-secondary"
                              size="compact-xs"
                              aria-label="Ẩn"
                              onClick={() => setConfirmHideId(id)}
                              style={{ height: 28, width: 28, padding: 0 }}
                            >
                              <IconEyeOff size={14} />
                            </Button>
                          </Tooltip>
                        ) : null}
                        {allowUnhide ? (
                          <Tooltip label="Hiện lại" withArrow>
                            <Button
                              className="pm-chat-btn-primary"
                              size="compact-xs"
                              aria-label="Hiện lại"
                              loading={unhide.isPending && unhide.variables === id}
                              onClick={() => unhide.mutate(id)}
                              style={{ height: 28, width: 28, padding: 0 }}
                            >
                              <IconEye size={14} />
                            </Button>
                          </Tooltip>
                        ) : null}
                      </Group>
                    </Group>
                    <Text className="pm-chat-body pm-chat-file-row-preview">{previewLine(report)}</Text>
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
          </div>
        </>
      ) : (
        <Text className="pm-chat-meta">
          Danh sách đang thu gọn · {items.length} báo cáo (mới → cũ). Nhấn tiêu đề để mở.
        </Text>
      )}

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
