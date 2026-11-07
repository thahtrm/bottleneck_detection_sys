import React, { useEffect, useMemo } from 'react';
import { Alert, Button, Group, SegmentedControl, Skeleton, Stack, Text } from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { GROUPINGS, countChips, groupIssues } from '../../dashboard/boardModel.js';
import { useBoardIssues } from '../../dashboard/useBoardIssues.js';
import PulseStrip from '../PulseStrip';
import IssueList from '../IssueList';
import RiskBoard from './RiskBoard';

const GROUP_OPTIONS = Object.entries(GROUPINGS).map(([value, grouping]) => ({ value, label: grouping.label }));

function BoardSkeleton() {
  return (
    <Stack gap="md">
      <Skeleton height={56} radius="md" />
      <Group gap="sm" align="flex-start" wrap="nowrap">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} height={420} width={290} radius="md" />
        ))}
      </Group>
    </Stack>
  );
}

export default function BoardView({ state, patch, onMoveStatus, canMoveStatus }) {
  const { board, ctx, isLoading, isError, error, refetch } = useBoardIssues(state);
  const sprintMissing = error?.status === 404 && state.sprint != null;
  useEffect(() => {
    if (sprintMissing) patch({ sprint: null }, { replace: true });
  }, [sprintMissing, patch]);
  const counts = useMemo(() => board && countChips(board.cards, ctx), [board, ctx]);
  const columns = useMemo(
    () => board && groupIssues(board.cards, state.group, state.chips, ctx),
    [board, ctx, state.group, state.chips]
  );

  if (isLoading) return <BoardSkeleton />;
  if (isError && !board) {
    return (
      <Alert color="gray" variant="light" icon={<IconAlertCircle size={16} />} title="Không tải được bảng rủi ro">
        <Group justify="space-between">
          <Text size="sm">{error?.message || 'Không thể kết nối đến máy chủ.'}</Text>
          <Button size="xs" variant="default" onClick={() => refetch()}>
            Thử lại
          </Button>
        </Group>
      </Alert>
    );
  }

  const shown = columns.reduce((sum, col) => sum + col.count, 0);
  const high = columns.reduce((sum, col) => sum + col.highCount, 0);
  const toggleChip = (id) =>
    patch({ chips: state.chips.includes(id) ? state.chips.filter((c) => c !== id) : [...state.chips, id] });
  const Renderer = state.view === 'list' ? IssueList : RiskBoard;

  return (
    <Stack gap="sm">
      <PulseStrip
        board={board}
        counts={counts}
        chips={state.chips}
        onToggleChip={toggleChip}
        sprintId={state.sprint}
        onSprintChange={(sprint) => patch({ sprint })}
      />
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="sm">
          <Text size="sm">
            {state.chips.length > 0 ? (
              <>
                Đang lọc <strong>{shown}</strong>/{board.cards.length} việc
              </>
            ) : (
              <>
                <strong>{shown}</strong> việc
              </>
            )}
            {high > 0 && (
              <Text span size="sm" c="red.8" fw={600}>
                {' · '}
                {high} Cao
              </Text>
            )}
          </Text>
          {state.chips.length > 0 && (
            <Button variant="subtle" size="compact-xs" color="gray" onClick={() => patch({ chips: [] })}>
              Bỏ lọc
            </Button>
          )}
        </Group>
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            Nhóm theo
          </Text>
          <SegmentedControl
            size="xs"
            data={GROUP_OPTIONS}
            value={state.group}
            onChange={(group) => patch({ group })}
          />
        </Group>
      </Group>
      <Renderer
        columns={columns}
        ctx={ctx}
        selectedKey={state.issue}
        onSelect={(issue) => patch({ issue })}
        onMoveStatus={onMoveStatus}
        canMoveStatus={canMoveStatus}
      />
    </Stack>
  );
}
