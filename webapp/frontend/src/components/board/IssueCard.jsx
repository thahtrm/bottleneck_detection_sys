import React from 'react';
import { Group, Text } from '@mantine/core';
import { describeCard } from '../../dashboard/boardModel.js';
import { AssigneeAvatar, CardMarkers, CardMenu, selectableProps } from './cardParts';
import classes from './board.module.css';

export default function IssueCard({ card, ctx, selected, onSelect, onMoveStatus }) {
  const facts = describeCard(card, ctx);
  return (
    <div
      {...selectableProps(card.key, onSelect)}
      role="button"
      className={classes.card}
      data-selected={selected || undefined}
      aria-pressed={selected}
      aria-label={`${card.key}: ${card.summary}`}
      style={{ '--stripe': `var(--mantine-color-${facts.level.color}-6)` }}
    >
      <Group justify="space-between" wrap="nowrap" gap={4}>
        <Group gap={6} wrap="nowrap">
          <Text size="xs" c="dimmed" ff="monospace" fw={600}>
            {card.key}
          </Text>
          <CardMarkers card={card} />
        </Group>
        <CardMenu card={card} onMoveStatus={onMoveStatus} />
      </Group>
      <Text size="sm" fw={500} lineClamp={2} title={card.summary}>
        {card.summary}
      </Text>
      {card.reason && (
        <Text size="xs" c="dimmed" lineClamp={1} title={card.reason}>
          {card.reason}
        </Text>
      )}
      <Text size="xs" fw={600} c={`${facts.level.color}.8`}>
        {facts.riskText}
      </Text>
      <Group justify="space-between" wrap="nowrap" gap={6}>
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          {facts.deadlineText && (
            <Text size="xs" c="dimmed" title={facts.deadlineTitle ?? undefined} style={{ whiteSpace: 'nowrap' }}>
              {facts.deadlineText}
            </Text>
          )}
          <Text size="xs" c="gray.6" truncate>
            {card.status}
          </Text>
        </Group>
        <AssigneeAvatar facts={facts} />
      </Group>
    </div>
  );
}
