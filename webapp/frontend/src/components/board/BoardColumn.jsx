import React, { useState } from 'react';
import { Button } from '@mantine/core';
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
        <h3 className={classes.columnTitle} title={column.title}>
          {column.title}
        </h3>
        {column.highCount > 0 && <span className={classes.columnHigh}>{column.highCount} Cao</span>}
        <span className={`${classes.columnCount}${column.highCount > 0 ? ` ${classes.columnCountHigh}` : ''}`}>
          {column.count}
        </span>
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
        {column.count === 0 && <p className={classes.emptyHint}>Không có việc</p>}
        {hidden > 0 && (
          <Button variant="subtle" color="dark" size="xs" onClick={() => setExpanded(true)}>
            + {hidden} việc nữa
          </Button>
        )}
      </div>
    </section>
  );
}
