import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getChatMessages, postChatMessage } from '../api/client';

/** Composer drafts survive bubble ↔ tab remounts (shared thread surface). */
const draftByProject = new Map();

/**
 * Shared PM chat thread state for bubble + Chat tab.
 * Same queryKey/poll so both surfaces stay in sync; draft is keyed by project.
 */
export function usePmChatSession(project) {
  const queryClient = useQueryClient();
  const [, bumpDraft] = useState(0);

  const messages = useQuery({
    queryKey: ['chat-messages', project],
    queryFn: () => getChatMessages(project),
    enabled: Boolean(project),
    refetchInterval: () =>
      typeof document !== 'undefined' && document.visibilityState === 'visible' ? 5000 : false,
    refetchIntervalInBackground: false,
  });

  const send = useMutation({
    mutationFn: (text) => postChatMessage(project, text),
    onSuccess: () => {
      if (project) draftByProject.set(project, '');
      bumpDraft((version) => version + 1);
      queryClient.invalidateQueries({ queryKey: ['chat-messages', project] });
    },
  });

  const draft = project ? (draftByProject.get(project) ?? '') : '';

  const setDraft = (value) => {
    if (!project) return;
    const current = draftByProject.get(project) ?? '';
    const next = typeof value === 'function' ? value(current) : value;
    draftByProject.set(project, next);
    bumpDraft((version) => version + 1);
  };

  const submit = () => {
    const text = draft.trim();
    if (!text || send.isPending || !project) return;
    send.mutate(text);
  };

  return {
    project,
    messages: messages.data ?? [],
    isLoading: messages.isLoading,
    isError: messages.isError,
    error: messages.error,
    draft,
    setDraft,
    submit,
    sendPending: send.isPending,
    sendError: send.error,
    sendFailed: send.isError,
  };
}
