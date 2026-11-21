import React, { useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Button,
  Collapse,
  Group,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { IconChevronDown, IconChevronRight, IconPencil, IconTrash, IconX } from '@tabler/icons-react';
import {
  deleteChatMemory,
  getChatMemories,
  getChatMessages,
  getChatSchedule,
  patchChatMemory,
  postChatMemory,
  postChatMessage,
  putChatSchedule,
} from '../api/client';
import { pinChatToLatest, splitChatText } from './pmChatText';
import '../styles/kaggleTokens.css';

const FAILED_LINE = 'Chưa tạo được đề xuất bám dữ liệu.';
const PENDING_LINE = 'Đang trả lời…';
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const KIND_LABEL = {
  user: 'PM',
  assistant: 'Hệ thống',
  report: 'Báo cáo',
  urgent: 'Việc gấp',
};
const MEMORY_KIND_LABEL = {
  preference: 'Ưu tiên',
  note: 'Ghi chú',
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

function MemoryPrefs({ project }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [kind, setKind] = useState('preference');
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState('');

  const memories = useQuery({
    queryKey: ['chat-memories', project],
    queryFn: () => getChatMemories(project),
    enabled: Boolean(project) && open,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['chat-memories', project] });

  const create = useMutation({
    mutationFn: () => postChatMemory(project, kind, draft.trim()),
    onSuccess: () => {
      setDraft('');
      invalidate();
    },
  });

  const update = useMutation({
    mutationFn: ({ id, text }) => patchChatMemory(project, id, { text }),
    onSuccess: () => {
      setEditingId(null);
      setEditText('');
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (id) => deleteChatMemory(project, id),
    onSuccess: invalidate,
  });

  const submitCreate = () => {
    if (!draft.trim() || create.isPending) return;
    create.mutate();
  };

  const submitEdit = () => {
    const text = editText.trim();
    if (!editingId || !text || update.isPending) return;
    update.mutate({ id: editingId, text });
  };

  return (
    <Stack gap={6} className="pm-chat-memory">
      <Button
        variant="subtle"
        size="compact-sm"
        className="pm-chat-btn-subtle"
        leftSection={open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
        onClick={() => setOpen((value) => !value)}
        justify="flex-start"
        px={4}
      >
        Ghi nhớ của bạn
      </Button>
      <Collapse in={open}>
        <Stack gap="sm">
          {(memories.data ?? []).map((memory) => (
            <Stack key={memory.id} gap={6} className="pm-chat-memory-item">
              <Group justify="space-between" gap="xs" wrap="nowrap">
                <Text className="pm-chat-label">{MEMORY_KIND_LABEL[memory.kind] || memory.kind}</Text>
                <Group gap={4} wrap="nowrap">
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    className="pm-chat-btn-subtle"
                    aria-label="Sửa ghi nhớ"
                    onClick={() => {
                      setEditingId(memory.id);
                      setEditText(memory.text);
                    }}
                  >
                    <IconPencil size={14} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    color="red"
                    aria-label="Xóa ghi nhớ"
                    loading={remove.isPending && remove.variables === memory.id}
                    onClick={() => remove.mutate(memory.id)}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Group>
              </Group>
              {editingId === memory.id ? (
                <Stack gap={6}>
                  <Textarea
                    className="pm-chat-input"
                    value={editText}
                    onChange={(event) => setEditText(event.currentTarget.value)}
                    minRows={2}
                    autosize
                    aria-label="Sửa nội dung ghi nhớ"
                  />
                  <Group gap="xs">
                    <Button
                      className="pm-chat-btn-primary"
                      size="compact-sm"
                      onClick={submitEdit}
                      loading={update.isPending}
                      disabled={!editText.trim()}
                    >
                      Lưu
                    </Button>
                    <Button
                      className="pm-chat-btn-secondary"
                      size="compact-sm"
                      onClick={() => {
                        setEditingId(null);
                        setEditText('');
                      }}
                    >
                      Hủy
                    </Button>
                  </Group>
                </Stack>
              ) : (
                <Text className="pm-chat-body" style={{ whiteSpace: 'pre-wrap' }}>
                  {memory.text}
                </Text>
              )}
            </Stack>
          ))}
          {memories.isError && (
            <Text className="pm-chat-error">{memories.error?.message || 'Không tải được ghi nhớ.'}</Text>
          )}
          {!memories.isLoading && (memories.data ?? []).length === 0 && (
            <Text className="pm-chat-meta">Chưa có ưu tiên hay ghi chú nào.</Text>
          )}
          <Select
            className="pm-chat-input"
            data={[
              { value: 'preference', label: 'Ưu tiên' },
              { value: 'note', label: 'Ghi chú' },
            ]}
            value={kind}
            onChange={(value) => setKind(value || 'preference')}
            aria-label="Loại ghi nhớ"
            allowDeselect={false}
          />
          <TextInput
            className="pm-chat-input"
            placeholder="Ví dụ: Ưu tiên blocker trước"
            value={draft}
            onChange={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                submitCreate();
              }
            }}
            aria-label="Thêm ghi nhớ"
          />
          <Button
            className="pm-chat-btn-secondary"
            onClick={submitCreate}
            loading={create.isPending}
            disabled={!draft.trim()}
          >
            Thêm
          </Button>
          {create.isError && (
            <Text className="pm-chat-error">{create.error?.message || 'Không thêm được ghi nhớ.'}</Text>
          )}
          {update.isError && (
            <Text className="pm-chat-error">{update.error?.message || 'Không lưu được ghi nhớ.'}</Text>
          )}
          {remove.isError && (
            <Text className="pm-chat-error">{remove.error?.message || 'Không xóa được ghi nhớ.'}</Text>
          )}
        </Stack>
      </Collapse>
    </Stack>
  );
}

export default function PmChat({ project, onOpenIssue }) {
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(false);
  const [draft, setDraft] = useState('');
  const [clock, setClock] = useState('');
  const viewport = useRef(null);
  const messages = useQuery({
    queryKey: ['chat-messages', project],
    queryFn: () => getChatMessages(project),
    enabled: Boolean(project),
    refetchInterval: () => (typeof document !== 'undefined' && document.visibilityState === 'visible' ? 5000 : false),
    refetchIntervalInBackground: false,
  });
  useEffect(() => {
    pinChatToLatest(viewport.current);
  }, [messages.data]);
  const schedule = useQuery({
    queryKey: ['chat-schedule'],
    queryFn: getChatSchedule,
  });
  const send = useMutation({
    mutationFn: (text) => postChatMessage(project, text),
    onSuccess: () => {
      setDraft('');
      queryClient.invalidateQueries({ queryKey: ['chat-messages', project] });
    },
  });
  const saveSchedule = useMutation({
    mutationFn: putChatSchedule,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['chat-schedule'] }),
  });

  const times = schedule.data?.times ?? [];

  const submit = () => {
    const text = draft.trim();
    if (!text || send.isPending) return;
    send.mutate(text);
  };

  const addTime = () => {
    const value = clock.trim();
    if (!HHMM.test(value) || times.includes(value) || times.length >= 3) return;
    setClock('');
    saveSchedule.mutate([...times, value]);
  };

  if (collapsed) {
    return (
      <div className="pm-chat-scope">
        <Button className="pm-chat-btn-secondary" onClick={() => setCollapsed(false)} style={{ alignSelf: 'flex-start' }}>
          Chat
        </Button>
      </div>
    );
  }

  return (
    <div className="pm-chat-scope">
      <Paper
        className="pm-chat-card"
        withBorder={false}
        radius="md"
        p="md"
        w={320}
        style={{
          flex: '0 0 320px',
          height: 'calc(100dvh - 96px)',
          display: 'flex',
          flexDirection: 'column',
          position: 'sticky',
          top: 12,
        }}
      >
        <Stack gap="sm" style={{ flex: 1, minHeight: 0 }}>
          <Group justify="space-between">
            <Text className="pm-chat-title">Chat PM</Text>
            <Button variant="subtle" size="compact-xs" className="pm-chat-btn-subtle" onClick={() => setCollapsed(true)}>
              Thu gọn
            </Button>
          </Group>

          <Stack gap={6} className="pm-chat-schedule">
            <Text className="pm-chat-meta">Giờ báo cáo của bạn</Text>
            <Group gap={6}>
              {times.map((time) => (
                <Group key={time} gap={2}>
                  <Text className="pm-chat-body">{time}</Text>
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    className="pm-chat-btn-subtle"
                    aria-label={`Xóa ${time}`}
                    onClick={() => saveSchedule.mutate(times.filter((item) => item !== time))}
                  >
                    <IconX size={12} />
                  </ActionIcon>
                </Group>
              ))}
            </Group>
            <Group gap="xs">
              <TextInput
                className="pm-chat-input"
                placeholder="HH:MM"
                value={clock}
                onChange={(event) => setClock(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') addTime();
                }}
                w={90}
                size="xs"
                aria-label="Giờ báo cáo"
              />
              <Button
                className="pm-chat-btn-secondary"
                size="compact-sm"
                onClick={addTime}
                disabled={times.length >= 3}
                style={{ height: 32, padding: '0 16px' }}
              >
                Thêm giờ
              </Button>
            </Group>
            {saveSchedule.isError && (
              <Text className="pm-chat-error">{saveSchedule.error?.message || 'Không lưu được giờ báo cáo.'}</Text>
            )}
          </Stack>

          <MemoryPrefs project={project} />

          <ScrollArea style={{ flex: 1, minHeight: 0 }} viewportRef={viewport} offsetScrollbars>
            <Stack gap="sm">
              {(messages.data ?? []).map((message) => (
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
              {messages.isError && (
                <Text className="pm-chat-error">{messages.error?.message || 'Không tải được tin nhắn.'}</Text>
              )}
            </Stack>
          </ScrollArea>

          <Textarea
            className="pm-chat-input"
            placeholder="Hỏi về sprint, việc bị block, việc cần ưu tiên, hoặc một mã issue"
            value={draft}
            onChange={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            minRows={2}
            autosize
            aria-label="Câu hỏi"
          />
          {send.isError && <Text className="pm-chat-error">{send.error?.message || 'Không gửi được câu hỏi.'}</Text>}
          <Button className="pm-chat-btn-primary" onClick={submit} loading={send.isPending} disabled={!draft.trim()}>
            Gửi
          </Button>
        </Stack>
      </Paper>
    </div>
  );
}
