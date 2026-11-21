import React from 'react';
import { Alert, Box, Chip, Group, Progress, Select, Stack, Text, Tooltip } from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { CHIPS } from '../dashboard/boardModel.js';

const percent = (fraction) => Math.round(fraction * 100);

function sprintRemaining(sprint) {
  if (sprint.days_left == null) return null;
  if (sprint.days_left < 0) return `đã quá ${-sprint.days_left} ngày`;
  if (sprint.days_left === 0) return 'kết thúc hôm nay';
  return `còn ${sprint.days_left} ngày`;
}

function SprintProgress({ sprint, progress, compact = false }) {
  const unit = progress.unit === 'points' ? 'điểm' : 'việc';
  const remaining = sprintRemaining(sprint);
  const expected = progress.expected_pct == null ? null : percent(progress.expected_pct);
  if (compact) {
    const label = `${sprint.name}${remaining ? ` · ${remaining}` : ''} · Xong ${progress.done}/${progress.total} ${unit} (${percent(progress.done_pct)}%)${expected != null ? ` · kỳ vọng ${expected}%` : ''}`;
    return (
      <Tooltip label={label} withArrow multiline maw={280}>
        <Group gap={6} wrap="nowrap" style={{ flex: '0 1 160px', minWidth: 120 }}>
          <Progress
            value={percent(progress.done_pct)}
            size="sm"
            radius="sm"
            color="blue"
            style={{ flex: 1, minWidth: 64 }}
            aria-label="Tiến độ sprint"
          />
          <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
            {percent(progress.done_pct)}%
          </Text>
        </Group>
      </Tooltip>
    );
  }
  return (
    <Stack gap={4} style={{ flex: '1 1 320px', minWidth: 240 }}>
      <Group justify="space-between" gap="xs">
        <Text size="xs" fw={600}>
          {sprint.name}
          {remaining && (
            <Text span size="xs" c="dimmed" fw={400}>
              {' · '}
              {remaining}
            </Text>
          )}
        </Text>
        <Text size="xs" c="dimmed">
          Xong {progress.done}/{progress.total} {unit} ({percent(progress.done_pct)}%)
          {expected != null && ` · kỳ vọng ${expected}%`}
        </Text>
      </Group>
      <Box pos="relative">
        <Progress value={percent(progress.done_pct)} size="md" radius="sm" color="blue" aria-label="Tiến độ sprint" />
        {expected != null && (
          <Tooltip label={`Kỳ vọng theo thời gian: ${expected}%`} withArrow>
            <Box pos="absolute" top={-4} bottom={-4} w={2} bg="dark.5" style={{ left: `calc(${expected}% - 1px)` }} />
          </Tooltip>
        )}
      </Box>
    </Stack>
  );
}

export default function PulseStrip({
  board,
  counts,
  chips,
  onToggleChip,
  sprintId,
  onSprintChange,
  embedded = false,
}) {
  const sprintOptions = [
    { value: '', label: 'Tất cả sprint' },
    ...board.sprints.map((s) => ({
      value: String(s.id),
      label: s.state === 'active' ? `${s.name} (đang chạy)` : s.name,
    })),
  ];

  const chipRow = (
    <Group gap={6} wrap="wrap">
      {CHIPS.map((chip) => (
        <Chip
          key={chip.id}
          size={embedded ? 'xs' : 'sm'}
          variant="outline"
          checked={chips.includes(chip.id)}
          onChange={() => onToggleChip(chip.id)}
        >
          {chip.label} · {counts[chip.id]}
        </Chip>
      ))}
    </Group>
  );

  const sprintControls =
    board.sprints.length > 0 ? (
      <Group gap="xs" wrap="nowrap" style={{ flex: embedded ? '0 1 auto' : '1 1 480px', justifyContent: 'flex-end' }}>
        {board.sprint && board.progress && (
          <SprintProgress sprint={board.sprint} progress={board.progress} compact={embedded} />
        )}
        <Select
          size="xs"
          w={embedded ? 168 : 190}
          data={sprintOptions}
          value={sprintId == null ? '' : String(sprintId)}
          onChange={(value) => onSprintChange(value ? Number(value) : null)}
          allowDeselect={false}
          aria-label="Lọc theo sprint"
        />
      </Group>
    ) : null;

  // Embedded toolbar owns truncated alert (keeps chips+sprint on one row).
  if (embedded) {
    return (
      <Group gap="sm" align="center" wrap="wrap" style={{ flex: '1 1 auto', minWidth: 0 }}>
        {chipRow}
        {sprintControls}
      </Group>
    );
  }

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center" gap="md" wrap="wrap">
        {chipRow}
        {sprintControls}
      </Group>
      {board.truncated && (
        <Alert color="gray" variant="light" icon={<IconAlertCircle size={16} />} py={6}>
          <Text size="xs">
            Đang hiển thị {board.cards.length}/{board.total} việc. Chọn dự án, sprint hoặc tìm kiếm để thu hẹp.
          </Text>
        </Alert>
      )}
    </Stack>
  );
}
