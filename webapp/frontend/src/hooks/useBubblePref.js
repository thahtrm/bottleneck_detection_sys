import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getChatPrefs, putChatPrefs } from '../api/client';

export const CHAT_PREFS_QUERY_KEY = ['chat-prefs'];

/**
 * Pref “Hiện bubble chat trên Bảng / Danh sách”.
 * Source of truth: GET/PUT /api/chat/prefs (`bubble_enabled`, default true).
 */
export function useBubblePref(enabled = true) {
  const queryClient = useQueryClient();

  const prefs = useQuery({
    queryKey: CHAT_PREFS_QUERY_KEY,
    queryFn: getChatPrefs,
    enabled,
    staleTime: 30000,
  });

  const save = useMutation({
    mutationFn: (bubble_enabled) => putChatPrefs({ bubble_enabled: Boolean(bubble_enabled) }),
    onSuccess: (data) => {
      queryClient.setQueryData(CHAT_PREFS_QUERY_KEY, data);
    },
  });

  const bubbleEnabled = prefs.data?.bubble_enabled ?? true;

  const setEnabled = useCallback(
    (next) => {
      save.mutate(Boolean(next));
    },
    [save],
  );

  return [bubbleEnabled, setEnabled, { isLoading: prefs.isLoading, isSaving: save.isPending, error: prefs.error || save.error }];
}
