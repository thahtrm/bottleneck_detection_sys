import React from 'react';
import { Button, Stack, Text, Textarea } from '@mantine/core';

export default function PmChatComposer({
  draft,
  setDraft,
  onSubmit,
  pending = false,
  failed = false,
  error = null,
  disabled = false,
  placeholder = 'Hỏi về sprint, việc bị block, việc cần ưu tiên, hoặc một mã issue',
}) {
  return (
    <Stack gap="sm">
      <Textarea
        className="pm-chat-input"
        placeholder={placeholder}
        value={draft}
        onChange={(event) => setDraft(event.currentTarget.value)}
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
      {failed && <Text className="pm-chat-error">{error?.message || 'Không gửi được câu hỏi.'}</Text>}
      <Button
        className="pm-chat-btn-primary"
        onClick={onSubmit}
        loading={pending}
        disabled={disabled || !draft.trim()}
      >
        Gửi
      </Button>
    </Stack>
  );
}
