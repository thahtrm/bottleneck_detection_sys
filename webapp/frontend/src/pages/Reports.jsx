import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Stack, Text, Title } from '@mantine/core';
import { IconAlertCircle, IconFileReport, IconMessageCircle, IconSettings } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import ReportFileManager from '../components/chat/ReportFileManager';
import ReportPreviewDrawer from '../components/reports/ReportPreviewDrawer';
import { generateHealthReport } from '../api/client';
import { useAuth } from '../context/AuthContext';
import '../styles/kaggleTokens.css';

export default function Reports({
  project = '',
  projects = [],
  selectedReportId = null,
  onSelectReport,
  onOpenChat,
  onAskReportInChat,
  onOpenProjectSettings,
  onOpenScheduleSettings,
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = Boolean(user?.is_admin);
  const projectMeta = projects.find((item) => item.key === project);
  const projectRole = projectMeta?.role;
  const canGenerate = Boolean(project) && (isAdmin || projectRole === 'pm');
  const canRead = Boolean(project) && (isAdmin || projectRole === 'pm' || projectRole === 'viewer');
  const [previewId, setPreviewId] = useState(selectedReportId);

  useEffect(() => {
    setPreviewId(selectedReportId);
  }, [selectedReportId]);

  const openPreview = (reportOrId) => {
    const id = typeof reportOrId === 'object' ? reportOrId?.id : reportOrId;
    if (!id) return;
    setPreviewId(id);
    onSelectReport?.(id);
  };

  const closePreview = () => {
    setPreviewId(null);
    onSelectReport?.(null);
  };

  const generate = useMutation({
    mutationFn: () => generateHealthReport(project),
    onSuccess: (data) => {
      notifications.show({
        title: 'Đã tạo báo cáo',
        message: `Báo cáo sức khỏe hôm nay cho ${project} đã sẵn sàng.`,
        color: 'teal',
      });
      queryClient.invalidateQueries({ queryKey: ['chat-reports', project] });
      if (data?.report_id) openPreview(data.report_id);
    },
    onError: (err) => {
      notifications.show({
        title: 'Không tạo được báo cáo',
        message: err.message || 'Thử lại sau.',
        color: 'red',
        icon: <IconAlertCircle size={18} />,
      });
    },
  });

  if (!project) {
    return (
      <div className="erw-settings-scope" style={{ maxWidth: 960, margin: '0 auto' }}>
        <Alert icon={<IconAlertCircle size={18} />} color="gray" variant="light" radius="md">
          Chọn dự án trên thanh trên để xem và quản lý báo cáo sức khỏe.
        </Alert>
      </div>
    );
  }

  if (!canRead) {
    return (
      <div className="erw-settings-scope" style={{ maxWidth: 960, margin: '0 auto' }}>
        <Alert icon={<IconAlertCircle size={18} />} color="red" variant="light" radius="md">
          Bạn cần là thành viên dự án {project} để đọc báo cáo.
        </Alert>
      </div>
    );
  }

  return (
    <div className="erw-settings-scope" style={{ maxWidth: 960, margin: '0 auto' }}>
      <Stack gap="xl">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={4}>
            <Title order={2} className="erw-settings-page-title">
              Báo cáo
            </Title>
            <Text className="erw-settings-body">
              Báo cáo sức khỏe hàng ngày cho <strong>{project}</strong>
              {projectMeta?.name ? ` — ${projectMeta.name}` : ''}.
            </Text>
          </Stack>
          <Group gap="sm" wrap="wrap">
            {canGenerate ? (
              <Button
                className="erw-settings-btn-primary"
                leftSection={<IconFileReport size={16} />}
                loading={generate.isPending}
                onClick={() => generate.mutate()}
              >
                Tạo báo cáo hôm nay
              </Button>
            ) : null}
            {onOpenChat ? (
              <Button
                className="erw-settings-btn-secondary"
                leftSection={<IconMessageCircle size={16} />}
                onClick={onOpenChat}
              >
                Xem trong Chat
              </Button>
            ) : null}
            {onOpenProjectSettings ? (
              <Button
                className="erw-settings-btn-secondary"
                leftSection={<IconSettings size={16} />}
                onClick={onOpenProjectSettings}
              >
                Cài đặt dự án
              </Button>
            ) : null}
          </Group>
        </Group>

        <div className="erw-settings-card pm-chat-scope">
          <ReportFileManager
            project={project}
            manage
            canHide={canGenerate}
            canUnhide={canGenerate}
            showPdfDownload
            onOpenSettings={onOpenScheduleSettings}
            onPreview={openPreview}
            onRegenerate={canGenerate ? () => generate.mutate() : undefined}
            regeneratePending={generate.isPending}
          />
        </div>
      </Stack>

      <ReportPreviewDrawer
        reportId={previewId}
        opened={Boolean(previewId)}
        onClose={closePreview}
        onAskInChat={
          onAskReportInChat
            ? (id) => {
                closePreview();
                onAskReportInChat(id);
              }
            : undefined
        }
      />
    </div>
  );
}
