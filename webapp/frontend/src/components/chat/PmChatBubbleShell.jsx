import React, { useEffect, useState } from 'react';
import { ActionIcon, Button, Group, Paper, Stack, Text, Tooltip, Transition } from '@mantine/core';
import { IconMessageCircle, IconX } from '@tabler/icons-react';
import { usePmChatSession } from '../../hooks/usePmChatSession';
import '../../styles/kaggleTokens.css';
import PmChatComposer from './PmChatComposer';
import PmChatTimeline from './PmChatTimeline';

/**
 * Floating bubble on Board/List only. Shared thread via usePmChatSession.
 */
export default function PmChatBubbleShell({
  project,
  canChatOnProject = false,
  onOpenIssue,
  onOpenSettings,
  onOpenChatTab,
}) {
  const [open, setOpen] = useState(false);
  const session = usePmChatSession(canChatOnProject ? project : '');
  const disabled = !canChatOnProject;

  useEffect(() => {
    if (!canChatOnProject) setOpen(false);
  }, [canChatOnProject]);
  const fabLabel = !project
    ? 'Chọn dự án'
    : !canChatOnProject
      ? 'Chat chỉ dành cho PM/Admin của dự án'
      : open
        ? 'Đóng chat'
        : 'Mở chat';

  return (
    <div className="pm-chat-scope pm-chat-bubble-shell">
      <Transition
        mounted={open && canChatOnProject}
        transition="slide-up"
        duration={300}
        timingFunction="cubic-bezier(0.4, 0, 0.2, 1)"
      >
        {(styles) => (
          <Paper
            className="pm-chat-card pm-chat-float-panel"
            withBorder={false}
            radius="md"
            p="md"
            style={styles}
          >
            <Stack gap="sm" style={{ flex: 1, minHeight: 0, height: '100%' }}>
              <Group justify="space-between" wrap="nowrap">
                <Text className="pm-chat-title">Chat PM</Text>
                <Group gap={4} wrap="nowrap">
                  {onOpenChatTab && (
                    <Button
                      variant="subtle"
                      size="compact-xs"
                      className="pm-chat-btn-subtle"
                      onClick={() => {
                        setOpen(false);
                        onOpenChatTab();
                      }}
                    >
                      Mở tab Chat
                    </Button>
                  )}
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    className="pm-chat-btn-subtle"
                    aria-label="Đóng chat"
                    onClick={() => setOpen(false)}
                  >
                    <IconX size={16} />
                  </ActionIcon>
                </Group>
              </Group>

              <Text className="pm-chat-meta">
                Lịch báo cáo và ghi nhớ chỉnh trong{' '}
                <Button
                  variant="subtle"
                  size="compact-xs"
                  className="pm-chat-link-btn"
                  onClick={onOpenSettings}
                >
                  Cài đặt
                </Button>
                .
              </Text>

              <PmChatTimeline
                messages={session.messages}
                isError={session.isError}
                error={session.error}
                onOpenIssue={onOpenIssue}
              />
              <PmChatComposer
                draft={session.draft}
                setDraft={session.setDraft}
                onSubmit={session.submit}
                pending={session.sendPending}
                failed={session.sendFailed}
                error={session.sendError}
              />
            </Stack>
          </Paper>
        )}
      </Transition>

      <Tooltip label={fabLabel} withArrow position="left">
        <ActionIcon
          className="pm-chat-fab"
          size={56}
          radius="xl"
          aria-label={fabLabel}
          onClick={() => setOpen((value) => !value)}
          disabled={disabled}
        >
          {open && canChatOnProject ? (
            <IconX size={24} stroke={1.75} />
          ) : (
            <IconMessageCircle size={24} stroke={1.75} />
          )}
        </ActionIcon>
      </Tooltip>
    </div>
  );
}
