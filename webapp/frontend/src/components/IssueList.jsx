import React from 'react';
import { Group, Table, Text } from '@mantine/core';
import { describeCard } from '../dashboard/boardModel.js';
import { AssigneeAvatar, CardMarkers, CardMenu, selectableProps } from './board/cardParts';
import classes from './board/board.module.css';

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
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table verticalSpacing={6} stickyHeader withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={190}>Rủi ro</Table.Th>
            <Table.Th>Công việc</Table.Th>
            <Table.Th w={130}>Trạng thái</Table.Th>
            <Table.Th w={120}>Hạn</Table.Th>
            <Table.Th w={170}>Phụ trách</Table.Th>
            <Table.Th w={40} />
          </Table.Tr>
        </Table.Thead>
        {columns.map((column) => (
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
  );
}
