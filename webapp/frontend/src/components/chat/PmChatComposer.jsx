import React, { useMemo, useState } from 'react';
import { Button, Group, Menu, Stack, Text, Textarea } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { IconPaperclip, IconX } from '@tabler/icons-react';
import { getChatReports } from '../../api/client';

export default function PmChatComposer({
  project,
  draft,
  setDraft,
  attachedReport = null,
  setAttachedReport,
  onSubmit,
  pending = false,
  failed = false,
  error = null,
  disabled = false,
  placeholder = 'Hỏi về sprint, tạo báo cáo sức khỏe, hoặc @report…',
}) {
  const [menuOpened, setMenuOpened] = useState(false);
  const wantsAtReport = draft.toLowerCase().includes('@report');
  const reports = useQuery({
    queryKey: ['chat-reports', project],
    queryFn: () => getChatReports(project),
    enabled: Boolean(project) && (menuOpened || wantsAtReport),
    staleTime: 15000,
  });

  const atReportSuggestions = useMemo(() => {
    if (!draft.toLowerCase().includes('@report')) return [];
    return (reports.data || []).slice(0, 5);
  }, [draft, reports.data]);

  const attach = (report) => {
    setAttachedReport?.(report);
    setMenuOpened(false);
    if (draft.toLowerCase().includes('@report')) {
      setDraft((prev) => prev.replace(/@report\b/i, '').replace(/\s{2,}/g, ' ').trim());
    }
  };

  return (
    <Stack gap="sm">
      {attachedReport ? (
        <Group gap="xs">
          <span className="pm-chat-report-chip">
            Báo cáo {attachedReport.report_date} · {attachedReport.slot_hhmm}
          </span>
          <Button
            variant="subtle"
            size="compact-xs"
            className="pm-chat-btn-subtle"
            leftSection={<IconX size={12} />}
            onClick={() => setAttachedReport?.(null)}
          >
            Bỏ đính kèm
          </Button>
        </Group>
      ) : null}
      <Textarea
        className="pm-chat-input"
        placeholder={placeholder}
        value={draft}
        onChange={(event) => {
          const value = event.currentTarget.value;
          setDraft(value);
          if (value.toLowerCase().includes('@report') && !reports.data) {
            setMenuOpened(true);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
        minRows={2}
        autosize
        disabled={disabled}
        aria-label="Câu hỏi"
      />
      {atReportSuggestions.length > 0 && !attachedReport ? (
        <Stack gap={4}>
          <Text className="pm-chat-meta">Chọn báo cáo cho @report:</Text>
          {atReportSuggestions.map((report) => (
            <Button
              key={report.id}
              variant="subtle"
              size="compact-sm"
              className="pm-chat-btn-subtle"
              justify="flex-start"
              onClick={() => attach(report)}
            >
              #{report.id} · {report.report_date} · {report.slot_hhmm}
            </Button>
          ))}
        </Stack>
      ) : null}
      {failed && <Text className="pm-chat-error">{error?.message || 'Không gửi được câu hỏi.'}</Text>}
      <Group gap="sm">
        <Menu opened={menuOpened} onChange={setMenuOpened} position="top-start" withinPortal>
          <Menu.Target>
            <Button
              className="pm-chat-btn-secondary"
              leftSection={<IconPaperclip size={14} />}
              disabled={disabled}
              onClick={() => setMenuOpened((open) => !open)}
            >
              Đính kèm báo cáo
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            {(reports.data || []).slice(0, 12).map((report) => (
              <Menu.Item key={report.id} onClick={() => attach(report)}>
                #{report.id} · {report.report_date} · {report.slot_hhmm}
              </Menu.Item>
            ))}
            {!reports.isLoading && (reports.data || []).length === 0 ? (
              <Menu.Item disabled>Chưa có báo cáo</Menu.Item>
            ) : null}
          </Menu.Dropdown>
        </Menu>
        <Button
          className="pm-chat-btn-primary"
          onClick={onSubmit}
          loading={pending}
          disabled={disabled || !draft.trim()}
        >
          Gửi
        </Button>
      </Group>
    </Stack>
  );
}
