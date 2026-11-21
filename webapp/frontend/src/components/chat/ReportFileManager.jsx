import React, { useState } from 'react';
import { Button, Group, Stack, Text, Tooltip } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { IconDownload, IconEye, IconEyeOff, IconFileTypePdf } from '@tabler/icons-react';
import { downloadChatReport, getChatReports, hideChatReport } from '../../api/client';
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
  canHide = true,
  showPdfDownload = true,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [confirmHideId, setConfirmHideId] = useState(null);

  const reports = useQuery({
    queryKey: ['chat-reports', project],
    queryFn: () => getChatReports(project),
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

  const items = reports.data ?? [];

  return (
    <Stack gap="sm" className="pm-chat-files">
      <Group justify="space-between" align="center">
        <Text className="pm-chat-title">Báo cáo sức khỏe</Text>
        {onOpenSettings && (
          <Button variant="subtle" size="compact-sm" className="pm-chat-btn-subtle" onClick={onOpenSettings}>
            Đổi lịch
          </Button>
        )}
      </Group>

      {reports.isError && (
        <Text className="pm-chat-error">{reports.error?.message || 'Không tải được danh sách báo cáo.'}</Text>
      )}

      {!reports.isLoading && items.length === 0 && !reports.isError && (
        <Text className="pm-chat-meta">
          Chưa có báo cáo. PM có thể tạo on-demand hoặc đặt lịch trong Cài đặt.
          {onOpenSettings ? (
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
          const confirming = confirmHideId === id;
          const isOwner = report.owner_user_id == null || report.owner_user_id === user?.id;
          const allowHide = canHide && isOwner;
          const downloadingMd =
            download.isPending && download.variables?.report?.id === id && download.variables?.format === 'md';
          const downloadingPdf =
            download.isPending && download.variables?.report?.id === id && download.variables?.format === 'pdf';
          return (
            <div
              key={id}
              className="pm-chat-file-row"
              data-clickable={onPreview ? 'true' : undefined}
              onClick={onPreview ? () => onPreview(report) : undefined}
              onKeyDown={
                onPreview
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onPreview(report);
                      }
                    }
                  : undefined
              }
              role={onPreview ? 'button' : undefined}
              tabIndex={onPreview ? 0 : undefined}
            >
              <Stack gap={4}>
                <Group gap="xs" wrap="wrap">
                  <Text className="pm-chat-label">{formatReportDate(report.report_date)}</Text>
                  <Text className="pm-chat-meta">{report.slot_hhmm || '—'}</Text>
                  <Text className="pm-chat-meta">{report.project_key || project}</Text>
                </Group>
                <Text className="pm-chat-body">{previewLine(report)}</Text>
                <Group gap="xs" onClick={(event) => event.stopPropagation()}>
                  {onPreview ? (
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
                    confirming ? (
                      <Group gap={4}>
                        <Button
                          className="pm-chat-btn-primary"
                          size="compact-sm"
                          loading={hide.isPending && hide.variables === id}
                          onClick={() => hide.mutate(id)}
                          style={{ height: 32, padding: '0 16px' }}
                        >
                          Ẩn khỏi danh sách
                        </Button>
                        <Button
                          className="pm-chat-btn-secondary"
                          size="compact-sm"
                          onClick={() => setConfirmHideId(null)}
                          style={{ height: 32, padding: '0 16px' }}
                        >
                          Hủy
                        </Button>
                      </Group>
                    ) : (
                      <Button
                        className="pm-chat-btn-secondary"
                        size="compact-sm"
                        leftSection={<IconEyeOff size={14} />}
                        onClick={() => setConfirmHideId(id)}
                        style={{ height: 32, padding: '0 16px' }}
                      >
                        Ẩn
                      </Button>
                    )
                  ) : null}
                </Group>
                {download.isError && download.variables?.report?.id === id && (
                  <Text className="pm-chat-error">{download.error?.message || 'Không tải được.'}</Text>
                )}
                {hide.isError && hide.variables === id && (
                  <Text className="pm-chat-error">{hide.error?.message || 'Không ẩn được.'}</Text>
                )}
              </Stack>
            </div>
          );
        })}
      </Stack>
    </Stack>
  );
}
