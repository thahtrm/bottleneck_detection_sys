import React from 'react';
import { ActionIcon, Avatar, Badge, Box, Menu, Tooltip } from '@mantine/core';
import { IconArrowsExchange, IconDots, IconLock } from '@tabler/icons-react';

export function selectableProps(key, onSelect) {
  return {
    tabIndex: 0,
    onClick: () => onSelect(key),
    onKeyDown: (event) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect(key);
      }
    },
  };
}

export function CardMarkers({ card }) {
  return (
    <>
      {card.is_critical && (
        <Tooltip label="Việc quan trọng (top mô hình)" withArrow>
          <Badge size="xs" color="gray" variant="light" radius="sm">
            ★ Quan trọng
          </Badge>
        </Tooltip>
      )}
      {card.blocked && (
        <Tooltip label="Đang bị chặn" withArrow>
          <IconLock size={14} color="var(--mantine-color-gray-6)" aria-label="Đang bị chặn" />
        </Tooltip>
      )}
    </>
  );
}

export function AssigneeAvatar({ facts }) {
  return (
    <Tooltip label={facts.assigneeName} withArrow>
      <Avatar size={22} radius="xl" color="gray" variant="light">
        {facts.initials}
      </Avatar>
    </Tooltip>
  );
}

const stop = (event) => event.stopPropagation();

export function CardMenu({ card, onMoveStatus }) {
  return (
    <Box onClick={stop} onKeyDown={stop}>
      <Menu position="bottom-end" shadow="md">
        <Menu.Target>
          <ActionIcon variant="subtle" color="gray" size="sm" aria-label={`Thao tác cho ${card.key}`}>
            <IconDots size={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item leftSection={<IconArrowsExchange size={14} />} onClick={() => onMoveStatus(card)}>
            Chuyển trạng thái
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Box>
  );
}
