import React, { useState } from 'react';
import { Button, Group, Stack, Text, Tooltip } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { IconDownload, IconEyeOff } from '@tabler/icons-react';
import { downloadChatReport, getChatReports, hideChatReport } from '../../api/client';

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

export default function ReportFileManager({ project, onOpenSettings }) {
  const queryClient = useQueryClient();
  const [confirmHideId, setConfirmHideId] = useState(null);

  const reports = useQuery({
    queryKey: ['chat-reports', project],
    queryFn: () => getChatReports(project),
    enabled: Boolean(project),
    staleTime: 15000,
  });

  const download = useMutation({
    mutationFn: async (report) => {
      const { blob, filename } = await downloadChatReport(report.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename || report.filename || `report-${report.id}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    },
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
        <Text className="pm-chat-title">Báo cáo ngày</Text>
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
          Chưa có báo cáo. Đặt lịch trong Cài đặt.
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
          return (
            <div key={id} className="pm-chat-file-row">
              <Stack gap={4}>
                <Group gap="xs" wrap="wrap">
                  <Text className="pm-chat-label">{formatReportDate(report.report_date)}</Text>
                  <Text className="pm-chat-meta">{report.slot_hhmm || '—'}</Text>
                  <Text className="pm-chat-meta">{report.project_key || project}</Text>
                </Group>
                <Text className="pm-chat-body">{previewLine(report)}</Text>
                <Group gap="xs">
                  <Tooltip label="Tải file" withArrow>
                    <Button
                      className="pm-chat-btn-secondary"
                      size="compact-sm"
                      leftSection={<IconDownload size={14} />}
                      loading={download.isPending && download.variables?.id === id}
                      onClick={() => download.mutate(report)}
                      style={{ height: 32, padding: '0 16px' }}
                    >
                      Tải
                    </Button>
                  </Tooltip>
                  {confirming ? (
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
                  )}
                </Group>
                {download.isError && download.variables?.id === id && (
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
