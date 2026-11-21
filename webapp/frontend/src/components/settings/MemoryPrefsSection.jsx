import React, { useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { IconPencil, IconTrash } from '@tabler/icons-react';
import {
  deleteChatMemory,
  getChatMemories,
  patchChatMemory,
  postChatMemory,
} from '../../api/client';

const MEMORY_KIND_LABEL = {
  preference: 'Ưu tiên',
  note: 'Ghi chú',
};

/** Project-scoped memory prefs — migrated from sticky PmChat. */
export default function MemoryPrefsSection({ project }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const [kind, setKind] = useState('preference');
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState('');

  const memories = useQuery({
    queryKey: ['chat-memories', project],
    queryFn: () => getChatMemories(project),
    enabled: Boolean(project),
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

  if (!project) {
    return <Text className="erw-settings-meta">Chọn dự án trên Header để quản lý ghi nhớ theo project.</Text>;
  }

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
    <Stack gap="sm">
      <Text className="erw-settings-body">
        Ghi nhớ theo dự án <strong>{project}</strong> (ưu tiên / ghi chú). Episode không hiện trong editor.
      </Text>
      {(memories.data ?? []).map((memory) => (
        <Stack key={memory.id} gap={6} className="erw-settings-memory-item">
          <Group justify="space-between" gap="xs" wrap="nowrap">
            <Text className="erw-settings-label">{MEMORY_KIND_LABEL[memory.kind] || memory.kind}</Text>
            <Group gap={4} wrap="nowrap">
              <ActionIcon
                variant="subtle"
                size="sm"
                className="erw-settings-link"
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
                className="erw-settings-input"
                value={editText}
                onChange={(event) => setEditText(event.currentTarget.value)}
                minRows={2}
                autosize
                aria-label="Sửa nội dung ghi nhớ"
              />
              <Group gap="xs">
                <Button
                  className="erw-settings-btn-primary"
                  onClick={submitEdit}
                  loading={update.isPending}
                  disabled={!editText.trim()}
                >
                  Lưu
                </Button>
                <Button
                  className="erw-settings-btn-secondary"
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
            <Text className="erw-settings-body" style={{ whiteSpace: 'pre-wrap' }}>
              {memory.text}
            </Text>
          )}
        </Stack>
      ))}
      {memories.isError && (
        <Text className="erw-settings-error">{memories.error?.message || 'Không tải được ghi nhớ.'}</Text>
      )}
      {!memories.isLoading && (memories.data ?? []).length === 0 && (
        <Text className="erw-settings-meta">Chưa có ưu tiên hay ghi chú nào.</Text>
      )}
      <Select
        className="erw-settings-input"
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
        className="erw-settings-input"
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
        className="erw-settings-btn-secondary"
        onClick={submitCreate}
        loading={create.isPending}
        disabled={!draft.trim()}
      >
        Thêm
      </Button>
      {create.isError && (
        <Text className="erw-settings-error">{create.error?.message || 'Không thêm được ghi nhớ.'}</Text>
      )}
      {update.isError && (
        <Text className="erw-settings-error">{update.error?.message || 'Không lưu được ghi nhớ.'}</Text>
      )}
      {remove.isError && (
        <Text className="erw-settings-error">{remove.error?.message || 'Không xóa được ghi nhớ.'}</Text>
      )}
    </Stack>
  );
}
