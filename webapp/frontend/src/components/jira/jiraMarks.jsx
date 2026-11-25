import React from 'react';
import {
  IconArrowDown,
  IconArrowUp,
  IconBolt,
  IconBookmark,
  IconBug,
  IconCheckbox,
  IconChevronsDown,
  IconChevronsUp,
  IconCircle,
  IconCircleCheck,
  IconCircleDot,
  IconEqual,
  IconSubtask,
  IconUser,
} from '@tabler/icons-react';

function typeIcon(type) {
  const key = (type || '').toLowerCase();
  if (key.includes('bug')) return IconBug;
  if (key.includes('story')) return IconBookmark;
  if (key.includes('epic')) return IconBolt;
  if (key.includes('sub')) return IconSubtask;
  return IconCheckbox;
}

function priorityIcon(priority) {
  const key = (priority || '').toLowerCase();
  if (key === 'highest') return IconChevronsUp;
  if (key === 'high') return IconArrowUp;
  if (key === 'low') return IconArrowDown;
  if (key === 'lowest') return IconChevronsDown;
  return IconEqual;
}

function statusIcon(status) {
  const key = (status || '').toLowerCase();
  if (key.includes('done') || key.includes('closed') || key.includes('resolved')) return IconCircleCheck;
  if (key.includes('progress') || key.includes('review')) return IconCircleDot;
  return IconCircle;
}

function initials(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

export function IssueTypeMark({ type, size = 14 }) {
  const Icon = typeIcon(type);
  return <Icon size={size} stroke={1.75} aria-hidden className="erw-jira-type" data-type={(type || 'task').toLowerCase()} />;
}

export function PriorityMark({ priority, size = 14 }) {
  const Icon = priorityIcon(priority);
  return (
    <Icon
      size={size}
      stroke={1.75}
      aria-hidden
      className="erw-jira-priority"
      data-priority={(priority || 'medium').toLowerCase()}
      title={priority || 'Medium'}
    />
  );
}

export function StatusMark({ status, size = 14 }) {
  const Icon = statusIcon(status);
  return <Icon size={size} stroke={1.75} aria-hidden className="erw-jira-status" data-status={(status || '').toLowerCase()} />;
}

export function PersonMark({ name }) {
  const label = initials(name);
  if (!label) {
    return <IconUser size={14} stroke={1.75} aria-hidden className="erw-jira-person erw-jira-person-empty" />;
  }
  return (
    <span className="erw-jira-person" title={name}>
      {label}
    </span>
  );
}
