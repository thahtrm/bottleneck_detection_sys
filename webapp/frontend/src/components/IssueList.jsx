import React, { useMemo, useState } from 'react';
import { Group, Table, Text } from '@mantine/core';
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronUp,
  IconSelector,
  IconUser,
} from '@tabler/icons-react';
import { LEVELS, describeCard, isDone } from '../dashboard/boardModel.js';
import {
  AssigneeAvatar,
  CardMarkers,
  CardMenu,
  DeadlineField,
  StatusField,
  selectableProps,
} from './board/cardParts';
import classes from './board/board.module.css';

const UNSCORED_RANK = 0;

function riskRank(card) {
  if (isDone(card)) return -1;
  return LEVELS[card.level]?.rank ?? UNSCORED_RANK;
}

function deadlineMs(card) {
  if (!card.deadline?.at) return Number.POSITIVE_INFINITY;
  const value = Date.parse(card.deadline.at);
  return Number.isNaN(value) ? Number.POSITIVE_INFINITY : value;
}

function compareCards(a, b, sortKey, direction) {
  const dir = direction === 'desc' ? -1 : 1;
  let cmp = 0;
  if (sortKey === 'risk') cmp = riskRank(a) - riskRank(b);
  else if (sortKey === 'deadline') cmp = deadlineMs(a) - deadlineMs(b);
  else cmp = a.key.localeCompare(b.key, undefined, { numeric: true });
  if (cmp !== 0) return cmp * dir;
  return a.key.localeCompare(b.key, undefined, { numeric: true });
}

function SortHeader({ label, sortKey, activeKey, direction, onSort }) {
  const active = activeKey === sortKey;
  const Icon = !active ? IconSelector : direction === 'asc' ? IconChevronUp : IconChevronDown;
  return (
    <button
      type="button"
      className={classes.sortButton}
      onClick={() => onSort(sortKey)}
      aria-label={`Sắp xếp theo ${label}`}
    >
      {label}
      <Icon size={14} stroke={1.75} />
    </button>
  );
}

function IssueRow({ card, ctx, selected, onSelect, onMoveStatus }) {
  const facts = describeCard(card, ctx);
  const stripe = `var(--color-risk-${facts.level.token})`;
  return (
    <Table.Tr
      {...selectableProps(card.key, onSelect)}
      className={classes.row}
      data-selected={selected || undefined}
    >
      <Table.Td className={classes.riskCell} style={{ '--stripe': stripe }}>
        <span className={classes.riskBadge} title={facts.riskText}>
          <IconAlertTriangle size={12} stroke={2} aria-hidden />
          {facts.riskText}
        </span>
      </Table.Td>
      <Table.Td>
        <Group gap={8} wrap="nowrap" align="flex-start">
          <span className={classes.listKey}>{card.key}</span>
          <div style={{ minWidth: 0 }}>
            <Text className={classes.listSummary} lineClamp={1} title={card.summary}>
              {card.summary}
            </Text>
            {card.reason && (
              <Text className={classes.cardReason} lineClamp={1} title={card.reason}>
                {card.reason}
              </Text>
            )}
          </div>
          <CardMarkers card={card} />
        </Group>
      </Table.Td>
      <Table.Td>
        <StatusField status={card.status} className={classes.listStatus} />
      </Table.Td>
      <Table.Td>
        <DeadlineField
          text={facts.deadlineText ?? '—'}
          title={facts.deadlineTitle}
          overdue={facts.deadlineOverdue}
          className={classes.listDeadline}
        />
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap" className={classes.listAssignee}>
          <AssigneeAvatar facts={facts} />
          <IconUser size={13} stroke={1.9} className={classes.fieldIcon} aria-hidden />
          <Text size="xs" fw={500} truncate>
            {facts.assigneeName}
          </Text>
        </Group>
      </Table.Td>
      <Table.Td w={40}>
        <CardMenu card={card} onMoveStatus={onMoveStatus} />
      </Table.Td>
    </Table.Tr>
  );
}

export default function IssueList({ columns, ctx, selectedKey, onSelect, onMoveStatus, canMoveStatus }) {
  const [sortKey, setSortKey] = useState('risk');
  const [direction, setDirection] = useState('desc');

  const onSort = (nextKey) => {
    if (sortKey === nextKey) {
      setDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(nextKey);
    setDirection(nextKey === 'key' ? 'asc' : 'desc');
  };

  const sortedColumns = useMemo(
    () =>
      columns.map((column) => ({
        ...column,
        cards: [...column.cards].sort((a, b) => compareCards(a, b, sortKey, direction)),
      })),
    [columns, sortKey, direction],
  );

  return (
    <div className={classes.tableWrap}>
      <Table.ScrollContainer minWidth={760}>
        <Table verticalSpacing={8} stickyHeader withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={200}>
                <SortHeader label="Rủi ro" sortKey="risk" activeKey={sortKey} direction={direction} onSort={onSort} />
              </Table.Th>
              <Table.Th>
                <SortHeader label="Key" sortKey="key" activeKey={sortKey} direction={direction} onSort={onSort} />
              </Table.Th>
              <Table.Th w={140}>Trạng thái</Table.Th>
              <Table.Th w={130}>
                <SortHeader label="Hạn" sortKey="deadline" activeKey={sortKey} direction={direction} onSort={onSort} />
              </Table.Th>
              <Table.Th w={180}>Phụ trách</Table.Th>
              <Table.Th w={40} />
            </Table.Tr>
          </Table.Thead>
          {sortedColumns.map((column) => (
            <Table.Tbody key={column.id}>
              <Table.Tr className={classes.groupRow}>
                <Table.Td colSpan={6}>
                  <Group gap="sm">
                    <span className={classes.groupTitle}>{column.title}</span>
                    <span className={classes.groupMeta}>{column.count} việc</span>
                    {column.highCount > 0 && (
                      <span className={classes.columnHigh}>{column.highCount} Cao</span>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
              {column.cards.map((card) => (
                <IssueRow
                  key={card.key}
                  card={card}
                  ctx={ctx}
                  selected={card.key === selectedKey}
                  onSelect={onSelect}
                  onMoveStatus={canMoveStatus(card) ? onMoveStatus : undefined}
                />
              ))}
            </Table.Tbody>
          ))}
        </Table>
      </Table.ScrollContainer>
    </div>
  );
}
