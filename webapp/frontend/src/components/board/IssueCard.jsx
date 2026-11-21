import React from 'react';
import { Group, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { describeCard } from '../../dashboard/boardModel.js';
import { AssigneeAvatar, CardMarkers, CardMenu, DeadlineField, StatusField, selectableProps } from './cardParts';
import classes from './board.module.css';

export default function IssueCard({ card, ctx, selected, onSelect, onMoveStatus }) {
  const facts = describeCard(card, ctx);
  const stripe = `var(--color-risk-${facts.level.token})`;
  return (
    <div
      {...selectableProps(card.key, onSelect)}
      role="button"
      className={classes.card}
      data-selected={selected || undefined}
      aria-pressed={selected}
      aria-label={`${card.key}: ${card.summary}`}
      style={{ '--stripe': stripe }}
    >
      <Group justify="space-between" wrap="nowrap" gap={4}>
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <span className={classes.cardKey}>{card.key}</span>
          <CardMarkers card={card} />
        </Group>
        <CardMenu card={card} onMoveStatus={onMoveStatus} />
      </Group>
      <Text className={classes.cardSummary} lineClamp={2} title={card.summary}>
        {card.summary}
      </Text>
      {card.reason && (
        <Text className={classes.cardReason} lineClamp={1} title={card.reason}>
          {card.reason}
        </Text>
      )}
      <span className={classes.riskBadge} title={facts.riskText}>
        <IconAlertTriangle size={12} stroke={2} aria-hidden />
        {facts.riskText}
      </span>
      <div className={classes.metaRow}>
        <div className={classes.metaFields}>
          <DeadlineField text={facts.deadlineText} title={facts.deadlineTitle} overdue={facts.deadlineOverdue} />
          <StatusField status={card.status} />
        </div>
        <AssigneeAvatar facts={facts} />
      </div>
    </div>
  );
}
