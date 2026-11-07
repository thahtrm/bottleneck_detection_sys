import React from 'react';
import { ActionIcon, Avatar, Badge, Box, Menu, Tooltip } from '@mantine/core';
import { IconArrowsExchange, IconDots, IconExternalLink, IconLock } from '@tabler/icons-react';
import { useJiraLinks } from '../JiraLinks';

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
  const { issueUrl, projectUrl } = useJiraLinks();
  const issueHref = issueUrl(card.key);
  const projectKey = card.project_key || card.key.split('-')[0];
  const projectHref = projectUrl(projectKey);
  if (!onMoveStatus && !issueHref && !projectHref) return null;
  return (
    <Box onClick={stop} onKeyDown={stop}>
      <Menu position="bottom-end" shadow="md">
        <Menu.Target>
          <ActionIcon variant="subtle" color="gray" size="sm" aria-label={`Thao tác cho ${card.key}`}>
            <IconDots size={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          {onMoveStatus && (
            <Menu.Item leftSection={<IconArrowsExchange size={14} />} onClick={() => onMoveStatus(card)}>
              Chuyển trạng thái
            </Menu.Item>
          )}
          {issueHref && (
            <Menu.Item
              component="a"
              href={issueHref}
              target="_blank"
              rel="noopener noreferrer"
              leftSection={<IconExternalLink size={14} />}
            >
              Mở issue trên Jira
            </Menu.Item>
          )}
          {projectHref && (
            <Menu.Item
              component="a"
              href={projectHref}
              target="_blank"
              rel="noopener noreferrer"
              leftSection={<IconExternalLink size={14} />}
            >
              Mở dự án trên Jira
            </Menu.Item>
          )}
        </Menu.Dropdown>
      </Menu>
    </Box>
  );
}
