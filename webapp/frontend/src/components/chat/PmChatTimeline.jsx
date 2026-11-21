import React, { useEffect, useRef } from 'react';
import { Button, Group, ScrollArea, Stack, Text } from '@mantine/core';
import { pinChatToLatest, splitChatText } from '../pmChatText';

const FAILED_LINE = 'Chưa tạo được đề xuất bám dữ liệu.';
const PENDING_LINE = 'Đang trả lời…';
const KIND_LABEL = {
  user: 'PM',
  assistant: 'Hệ thống',
  report: 'Báo cáo',
  urgent: 'Việc gấp',
};

function MessageBody({ body, onOpenIssue }) {
  return (
    <Text className="pm-chat-body" style={{ whiteSpace: 'pre-wrap' }}>
      {splitChatText(body).map((part, index) =>
        part.type === 'issue' ? (
          <Button
            key={`${part.key}-${index}`}
            variant="subtle"
            size="compact-xs"
            className="pm-chat-link-btn"
            onClick={() => onOpenIssue(part.key)}
          >
            {part.key}
          </Button>
        ) : (
          <React.Fragment key={index}>{part.text}</React.Fragment>
        ),
      )}
    </Text>
  );
}

function CitationChips({ citations }) {
  if (!Array.isArray(citations) || citations.length === 0) return null;
  return (
    <Group gap={6} mt={4}>
      {citations.map((citation, index) => {
        const label = citation?.label || citation?.id || citation?.type || `Nguồn ${index + 1}`;
        return (
          <span key={`${label}-${index}`} className="pm-chat-citation" title={label}>
            {label}
          </span>
        );
      })}
    </Group>
  );
}

export default function PmChatTimeline({
  messages = [],
  isError = false,
  error = null,
  onOpenIssue,
  style,
}) {
  const viewport = useRef(null);

  useEffect(() => {
    pinChatToLatest(viewport.current);
  }, [messages]);

  return (
    <ScrollArea style={{ flex: 1, minHeight: 0, ...style }} viewportRef={viewport} offsetScrollbars>
      <Stack gap="sm">
        {messages.map((message) => (
          <Stack key={message.id} gap={4} align={message.kind === 'user' ? 'flex-end' : 'flex-start'}>
            {message.kind === 'urgent' ? (
              <span className="pm-chat-badge">Việc gấp</span>
            ) : (
              <Text className="pm-chat-meta">{KIND_LABEL[message.kind] || message.kind}</Text>
            )}
            <div className={`pm-chat-bubble${message.kind === 'user' ? ' pm-chat-bubble-user' : ''}`}>
              {message.body ? (
                <MessageBody body={message.body} onOpenIssue={onOpenIssue} />
              ) : message.recommendation_status === 'pending' ? null : (
                <Text className="pm-chat-meta"> </Text>
              )}
              <CitationChips citations={message.citations} />
            </div>
            {message.recommendation_status === 'pending' && (
              <Text className="pm-chat-meta">{PENDING_LINE}</Text>
            )}
            {message.recommendation_status === 'failed' && !(message.body || '').includes(FAILED_LINE) && (
              <Text className="pm-chat-error">{FAILED_LINE}</Text>
            )}
          </Stack>
        ))}
        {isError && (
          <Text className="pm-chat-error">{error?.message || 'Không tải được tin nhắn.'}</Text>
        )}
      </Stack>
    </ScrollArea>
  );
}
