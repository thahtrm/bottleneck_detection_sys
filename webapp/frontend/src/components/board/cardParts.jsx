import React from 'react';
import { ActionIcon, Avatar, Box, Menu, Tooltip } from '@mantine/core';
import {
  IconArrowsExchange,
  IconCalendarDue,
  IconCircleDot,
  IconDots,
  IconExternalLink,
  IconLock,
  IconStarFilled,
} from '@tabler/icons-react';
import { useJiraLinks } from '../JiraLinks';
import classes from './board.module.css';

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
          <span className={classes.markerCritical} aria-label="Quan trọng">
            <IconStarFilled size={10} stroke={1.75} />
            Quan trọng
          </span>
        </Tooltip>
      )}
      {card.blocked && (
        <Tooltip label="Đang bị chặn" withArrow>
          <IconLock size={14} className={classes.markerBlocked} aria-label="Đang bị chặn" />
        </Tooltip>
      )}
    </>
  );
}

export function DeadlineField({ text, title, overdue = false, className = classes.field }) {
  if (!text) return null;
  return (
    <span className={`${className}${overdue ? ` ${classes.fieldOverdue}` : ''}`} title={title ?? undefined}>
      <IconCalendarDue size={13} stroke={1.9} className={classes.fieldIcon} aria-hidden />
      <span>{text}</span>
    </span>
  );
}

export function StatusField({ status, className = classes.field }) {
  if (!status) return null;
  return (
    <span className={className} title={status}>
      <IconCircleDot size={13} stroke={1.9} className={classes.fieldIcon} aria-hidden />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{status}</span>
    </span>
  );
}

export function AssigneeAvatar({ facts }) {
  return (
    <Tooltip label={facts.assigneeName} withArrow>
      <Avatar size={24} radius="xl" className={classes.assigneeAvatar} color="blue" variant="light">
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
