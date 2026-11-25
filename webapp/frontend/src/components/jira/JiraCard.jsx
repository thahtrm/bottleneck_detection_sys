import React, { useRef } from 'react';
import { Text } from '@mantine/core';

export default function JiraCard({ issue, draggable = false, onOpen }) {
  const dragged = useRef(false);
  const meta = [issue.issuetype, issue.priority, issue.assignee_name].filter(Boolean).join(' · ');

  return (
    <div
      className="erw-jira-card"
      draggable={draggable}
      role="button"
      tabIndex={0}
      aria-label={`${issue.key}: ${issue.summary}`}
      onDragStart={(event) => {
        dragged.current = true;
        event.dataTransfer.setData('text/plain', issue.key);
        event.dataTransfer.effectAllowed = 'move';
      }}
      onDragEnd={() => {
        setTimeout(() => {
          dragged.current = false;
        }, 0);
      }}
      onClick={() => {
        if (dragged.current) return;
        onOpen(issue.key);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onOpen(issue.key);
        }
      }}
    >
      <Text className="erw-settings-meta" fw={700}>
        {issue.key}
      </Text>
      <Text className="erw-settings-body" lineClamp={3}>
        {issue.summary}
      </Text>
      {meta ? <Text className="erw-settings-meta">{meta}</Text> : null}
    </div>
  );
}
