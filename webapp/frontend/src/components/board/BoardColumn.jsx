import React, { useState } from 'react';
import { Badge, Button, Text } from '@mantine/core';
import IssueCard from './IssueCard';
import classes from './board.module.css';

const PREVIEW = 25;

export default function BoardColumn({ column, ctx, selectedKey, onSelect, onMoveStatus, canMoveStatus }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? column.cards : column.cards.slice(0, PREVIEW);
  const hidden = column.count - shown.length;
  return (
    <section className={classes.column} aria-label={`${column.title}: ${column.count} việc`}>
      <header className={classes.columnHeader}>
        <Text fw={700} size="sm" truncate style={{ flex: 1 }} title={column.title}>
          {column.title}
        </Text>
        {column.highCount > 0 && (
          <Text size="xs" fw={600} c="red.8">
            {column.highCount} Cao
          </Text>
        )}
        <Badge variant="light" color="gray" size="sm">
          {column.count}
        </Badge>
      </header>
      <div className={classes.columnBody}>
        {shown.map((card) => (
          <IssueCard
            key={card.key}
            card={card}
            ctx={ctx}
            selected={card.key === selectedKey}
            onSelect={onSelect}
            onMoveStatus={canMoveStatus(card) ? onMoveStatus : undefined}
          />
        ))}
        {column.count === 0 && (
          <Text size="xs" c="dimmed" ta="center" py="md">
            Không có việc
          </Text>
        )}
        {hidden > 0 && (
          <Button variant="subtle" color="gray" size="xs" onClick={() => setExpanded(true)}>
            + {hidden} việc nữa
          </Button>
        )}
      </div>
    </section>
  );
}
