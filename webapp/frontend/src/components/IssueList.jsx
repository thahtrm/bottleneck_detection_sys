import React, { useMemo, useState } from 'react';
import { Group, Table, Text } from '@mantine/core';
import { IconChevronDown, IconChevronUp, IconSelector } from '@tabler/icons-react';
import { LEVELS, describeCard, isDone } from '../dashboard/boardModel.js';
import { AssigneeAvatar, CardMarkers, CardMenu, selectableProps } from './board/cardParts';
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
  return (
    <Table.Tr
      {...selectableProps(card.key, onSelect)}
      className={classes.row}
      data-selected={selected || undefined}
    >
      <Table.Td className={classes.riskCell} style={{ '--stripe': `var(--mantine-color-${facts.level.color}-6)` }}>
        <Text size="xs" fw={600} c={`${facts.level.color}.8`}>
          {facts.riskText}
        </Text>
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          <Text size="xs" c="dimmed" ff="monospace" fw={600} style={{ whiteSpace: 'nowrap' }}>
            {card.key}
          </Text>
          <Text size="sm" fw={500} lineClamp={1} title={card.summary}>
            {card.summary}
          </Text>
          <CardMarkers card={card} />
        </Group>
        {card.reason && (
          <Text size="xs" c="dimmed" lineClamp={1} title={card.reason}>
            {card.reason}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="gray.6" style={{ whiteSpace: 'nowrap' }}>
          {card.status}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed" title={facts.deadlineTitle ?? undefined} style={{ whiteSpace: 'nowrap' }}>
          {facts.deadlineText ?? '—'}
        </Text>
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          <AssigneeAvatar facts={facts} />
          <Text size="xs" truncate>
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
        <Table verticalSpacing={6} stickyHeader withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={190}>
                <SortHeader label="Rủi ro" sortKey="risk" activeKey={sortKey} direction={direction} onSort={onSort} />
              </Table.Th>
              <Table.Th>
                <SortHeader label="Key" sortKey="key" activeKey={sortKey} direction={direction} onSort={onSort} />
              </Table.Th>
              <Table.Th w={130}>Trạng thái</Table.Th>
              <Table.Th w={120}>
                <SortHeader label="Hạn" sortKey="deadline" activeKey={sortKey} direction={direction} onSort={onSort} />
              </Table.Th>
              <Table.Th w={170}>Phụ trách</Table.Th>
              <Table.Th w={40} />
            </Table.Tr>
          </Table.Thead>
          {sortedColumns.map((column) => (
            <Table.Tbody key={column.id}>
              <Table.Tr className={classes.groupRow}>
                <Table.Td colSpan={6}>
                  <Group gap="sm">
                    <Text size="sm" fw={700}>
                      {column.title}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {column.count} việc
                    </Text>
                    {column.highCount > 0 && (
                      <Text size="xs" fw={600} c="red.8">
                        {column.highCount} Cao
                      </Text>
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
