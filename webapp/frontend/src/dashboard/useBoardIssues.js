import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useDebouncedValue } from '@mantine/hooks';
import { getBoard } from '../api/client';
import { boardContext } from './boardModel.js';

export function useBoardIssues({ project, q, sprint }) {
  const [search] = useDebouncedValue(q.trim(), 300);
  const { data, dataUpdatedAt, isLoading, isError, error, isFetching, refetch } = useQuery({
    queryKey: ['dashboard-board', project, search, sprint],
    queryFn: () => getBoard({ project, q: search, sprint }),
    refetchInterval: 30000,
    staleTime: 10000,
    retry: (failures, err) => !(err.status >= 400 && err.status < 500) && failures < 3,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === project ? previous : undefined,
  });
  const ctx = useMemo(() => (data ? boardContext(data, new Date()) : null), [data, dataUpdatedAt]);
  return { board: data, ctx, isLoading, isError, error, isFetching, refetch };
}
