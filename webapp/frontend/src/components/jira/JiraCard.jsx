import React, { useRef } from 'react';
import { IssueTypeMark, PersonMark, PriorityMark } from './jiraMarks';

export default function JiraCard({ issue, draggable = false, onOpen, layout = 'card' }) {
  const dragged = useRef(false);
  const className = layout === 'row' ? 'erw-jira-row' : 'erw-jira-card';

  return (
    <div
      className={className}
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
      <IssueTypeMark type={issue.issuetype} />
      <span className="erw-jira-key">{issue.key}</span>
      <span className={layout === 'row' ? 'erw-jira-row-summary' : 'erw-jira-summary'}>{issue.summary}</span>
      <PriorityMark priority={issue.priority} />
      <PersonMark name={issue.assignee_name} />
    </div>
  );
}
