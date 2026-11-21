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
const REPORT_MARK = /\[\[report:(\d+)\]\]/g;

function splitWithReports(body) {
  const parts = [];
  let last = 0;
  const text = String(body || '');
  for (const match of text.matchAll(REPORT_MARK)) {
    if (match.index > last) parts.push({ type: 'text', text: text.slice(last, match.index) });
    parts.push({ type: 'report', id: Number(match[1]) });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ type: 'text', text: text.slice(last) });
  return parts.length ? parts : [{ type: 'text', text }];
}

function MessageBody({ body, onOpenIssue, onOpenReport }) {
  const chunks = splitWithReports(body);
  return (
    <Text className="pm-chat-body" style={{ whiteSpace: 'pre-wrap' }}>
      {chunks.map((chunk, index) => {
        if (chunk.type === 'report') {
          return (
            <button
              key={`r-${chunk.id}-${index}`}
              type="button"
              className="pm-chat-report-chip"
              onClick={() => onOpenReport?.(chunk.id)}
            >
              Xem báo cáo #{chunk.id}
            </button>
          );
        }
        return splitChatText(chunk.text).map((part, partIndex) =>
          part.type === 'issue' ? (
            <Button
              key={`${part.key}-${index}-${partIndex}`}
              variant="subtle"
              size="compact-xs"
              className="pm-chat-link-btn"
              onClick={() => onOpenIssue(part.key)}
            >
              {part.key}
            </Button>
          ) : (
            <React.Fragment key={`${index}-${partIndex}`}>{part.text}</React.Fragment>
          ),
        );
      })}
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
  onOpenReport,
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
                <MessageBody body={message.body} onOpenIssue={onOpenIssue} onOpenReport={onOpenReport} />
              ) : message.recommendation_status === 'pending' ? null : (
                <Text className="pm-chat-meta"> </Text>
              )}
              {message.report_id && message.kind === 'user' ? (
                <Group gap={6} mt={6}>
                  <button
                    type="button"
                    className="pm-chat-report-chip"
                    onClick={() => onOpenReport?.(message.report_id)}
                  >
                    Đã đính kèm #{message.report_id}
                  </button>
                </Group>
              ) : null}
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
