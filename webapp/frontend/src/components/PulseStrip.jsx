import React from 'react';
import { Alert, Box, Chip, Group, Paper, Progress, Select, Stack, Text, Tooltip } from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { CHIPS } from '../dashboard/boardModel.js';

const percent = (fraction) => Math.round(fraction * 100);

function sprintRemaining(sprint) {
  if (sprint.days_left == null) return null;
  if (sprint.days_left < 0) return `đã quá ${-sprint.days_left} ngày`;
  if (sprint.days_left === 0) return 'kết thúc hôm nay';
  return `còn ${sprint.days_left} ngày`;
}

function SprintProgress({ sprint, progress }) {
  const unit = progress.unit === 'points' ? 'điểm' : 'việc';
  const remaining = sprintRemaining(sprint);
  const expected = progress.expected_pct == null ? null : percent(progress.expected_pct);
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

export default function PulseStrip({ board, counts, chips, onToggleChip, sprintId, onSprintChange }) {
  const sprintOptions = [
    { value: '', label: 'Tất cả sprint' },
    ...board.sprints.map((s) => ({
      value: String(s.id),
      label: s.state === 'active' ? `${s.name} (đang chạy)` : s.name,
    })),
  ];
  return (
    <Paper withBorder radius="md" p="sm">
      <Stack gap="sm">
        <Group justify="space-between" align="center" gap="md" wrap="wrap">
          <Group gap="xs" wrap="wrap">
            {CHIPS.map((chip) => (
              <Chip
                key={chip.id}
                size="sm"
                variant="outline"
                checked={chips.includes(chip.id)}
                onChange={() => onToggleChip(chip.id)}
              >
                {chip.label} · {counts[chip.id]}
              </Chip>
            ))}
          </Group>
          {board.sprints.length > 0 && (
            <Group gap="md" wrap="nowrap" style={{ flex: '1 1 480px', justifyContent: 'flex-end' }}>
              {board.sprint && board.progress && <SprintProgress sprint={board.sprint} progress={board.progress} />}
              <Select
                size="xs"
                w={190}
                data={sprintOptions}
                value={sprintId == null ? '' : String(sprintId)}
                onChange={(value) => onSprintChange(value ? Number(value) : null)}
                allowDeselect={false}
                aria-label="Lọc theo sprint"
              />
            </Group>
          )}
        </Group>
        {board.truncated && (
          <Alert color="gray" variant="light" icon={<IconAlertCircle size={16} />} py={6}>
            <Text size="xs">
              Đang hiển thị {board.cards.length}/{board.total} việc. Chọn dự án, sprint hoặc tìm kiếm để thu hẹp.
            </Text>
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
