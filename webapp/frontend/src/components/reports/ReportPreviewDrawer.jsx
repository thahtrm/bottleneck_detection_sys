import React from 'react';
import { Button, Drawer, Group, Loader, Stack, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { IconDownload, IconFileTypePdf, IconMessageCircle } from '@tabler/icons-react';
import { downloadChatReport, getChatReportContent } from '../../api/client';
import ReportMarkdown from './ReportMarkdown';
import '../../styles/kaggleTokens.css';

async function saveDownload(reportId, format) {
  const { blob, filename } = await downloadChatReport(reportId, format);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || `report-${reportId}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function ReportPreviewDrawer({
  reportId,
  opened,
  onClose,
  onAskInChat,
}) {
  const content = useQuery({
    queryKey: ['chat-report-content', reportId],
    queryFn: () => getChatReportContent(reportId),
    enabled: Boolean(opened && reportId),
  });

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        content.data
          ? `Báo cáo ${content.data.report_date || ''} · ${content.data.slot_hhmm || ''}`
          : 'Xem báo cáo'
      }
      classNames={{ body: 'erw-report-scope' }}
    >
      <Stack gap="md">
        <Group gap="sm" wrap="wrap">
          <Button
            className="erw-settings-btn-secondary"
            leftSection={<IconDownload size={14} />}
            size="compact-sm"
            disabled={!reportId}
            onClick={() => saveDownload(reportId, 'md')}
          >
            Tải MD
          </Button>
          <Button
            className="erw-settings-btn-secondary"
            leftSection={<IconFileTypePdf size={14} />}
            size="compact-sm"
            disabled={!reportId}
            onClick={() => saveDownload(reportId, 'pdf')}
          >
            Tải PDF
          </Button>
          {onAskInChat ? (
            <Button
              className="erw-settings-btn-primary"
              leftSection={<IconMessageCircle size={14} />}
              size="compact-sm"
              disabled={!reportId}
              onClick={() => onAskInChat(reportId, content.data)}
            >
              Hỏi trong Chat
            </Button>
          ) : null}
        </Group>
        {content.isLoading && <Loader size="sm" type="dots" />}
        {content.isError && (
          <Text className="erw-settings-error">{content.error?.message || 'Không tải được nội dung.'}</Text>
        )}
        {content.data?.markdown ? <ReportMarkdown markdown={content.data.markdown} /> : null}
      </Stack>
    </Drawer>
  );
}
