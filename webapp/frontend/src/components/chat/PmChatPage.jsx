import React, { useState } from 'react';
import { Box, Button, Group, Paper, Stack, Text } from '@mantine/core';
import { usePmChatSession } from '../../hooks/usePmChatSession';
import '../../styles/kaggleTokens.css';
import ReportPreviewDrawer from '../reports/ReportPreviewDrawer';
import PmChatComposer from './PmChatComposer';
import PmChatTimeline from './PmChatTimeline';
import ReportFileManager from './ReportFileManager';

/**
 * Full-page Chat tab: timeline (~2/3) + report file manager (~1/3).
 * Issue clicks navigate Board + IssuePanel via onOpenIssue (caller patches view).
 */
export default function PmChatPage({
  project,
  canChatOnProject = false,
  onOpenIssue,
  onOpenSettings,
  initialAttachReportId = null,
}) {
  const session = usePmChatSession(canChatOnProject ? project : '');
  const [previewId, setPreviewId] = useState(null);

  // Seed attach from Reports "Hỏi trong Chat"
  React.useEffect(() => {
    if (!initialAttachReportId || !canChatOnProject) return;
    session.setAttachedReport({
      id: initialAttachReportId,
      report_date: '',
      slot_hhmm: '',
    });
    if (!session.draft.trim()) {
      session.setDraft('Theo báo cáo này, tóm tắt rủi ro và việc cần ưu tiên.');
    }
  }, [initialAttachReportId, canChatOnProject]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!project) {
    return (
      <div className="pm-chat-scope">
        <Paper className="pm-chat-card" p="lg" withBorder={false}>
          <Stack gap="sm">
            <Text className="pm-chat-title">Chat PM</Text>
            <Text className="pm-chat-body">Chọn dự án trên thanh điều hướng để xem hội thoại và báo cáo.</Text>
          </Stack>
        </Paper>
      </div>
    );
  }

  if (!canChatOnProject) {
    return (
      <div className="pm-chat-scope">
        <Paper className="pm-chat-card" p="lg" withBorder={false}>
          <Stack gap="sm">
            <Text className="pm-chat-title">Chat PM</Text>
            <Text className="pm-chat-body">
              Bạn không phải PM/Admin trên dự án {project}. Chọn dự án bạn quản lý để chat và xem báo cáo.
            </Text>
          </Stack>
        </Paper>
      </div>
    );
  }

  return (
    <div className="pm-chat-scope pm-chat-page">
      <Group align="stretch" gap="md" wrap="wrap" style={{ minHeight: 'calc(100dvh - 120px)' }}>
        <Paper
          className="pm-chat-card"
          p="md"
          withBorder={false}
          style={{ flex: '2 1 420px', minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 420 }}
        >
          <Stack gap="sm" style={{ flex: 1, minHeight: 0 }}>
            <Group justify="space-between">
              <Text className="pm-chat-title">Chat PM</Text>
              <Text className="pm-chat-meta">{project}</Text>
            </Group>
            <Text className="pm-chat-meta">
              Đổi lịch báo cáo / ghi nhớ trong{' '}
              <Button variant="subtle" size="compact-xs" className="pm-chat-link-btn" onClick={onOpenSettings}>
                Cài đặt
              </Button>
              . Có thể gõ “tạo báo cáo sức khỏe…” hoặc đính kèm @report.
            </Text>
            <PmChatTimeline
              messages={session.messages}
              isError={session.isError}
              error={session.error}
              onOpenIssue={onOpenIssue}
              onOpenReport={setPreviewId}
            />
            <PmChatComposer
              project={project}
              draft={session.draft}
              setDraft={session.setDraft}
              attachedReport={session.attachedReport}
              setAttachedReport={session.setAttachedReport}
              onSubmit={session.submit}
              pending={session.sendPending}
              failed={session.sendFailed}
              error={session.sendError}
            />
          </Stack>
        </Paper>

        <Box style={{ flex: '1 1 280px', minWidth: 240, maxWidth: 420 }}>
          <Paper className="pm-chat-card" p="md" withBorder={false} style={{ height: '100%' }}>
            <ReportFileManager
              project={project}
              onOpenSettings={onOpenSettings}
              onPreview={(report) => setPreviewId(report.id)}
            />
          </Paper>
        </Box>
      </Group>

      <ReportPreviewDrawer
        reportId={previewId}
        opened={Boolean(previewId)}
        onClose={() => setPreviewId(null)}
        onAskInChat={(id) => {
          setPreviewId(null);
          session.setAttachedReport({ id, report_date: '', slot_hhmm: '' });
          if (!session.draft.trim()) {
            session.setDraft('Theo báo cáo này, tóm tắt rủi ro chính.');
          }
        }}
      />
    </div>
  );
}
