import React from 'react';
import { ActionIcon, Button, Tooltip } from '@mantine/core';
import { IconExternalLink } from '@tabler/icons-react';
import { useAuth } from '../context/AuthContext';
import { jiraIssueUrl, jiraProjectUrl } from '../jiraLinks';

const external = {
  component: 'a',
  target: '_blank',
  rel: 'noopener noreferrer',
};

export function useJiraLinks() {
  const { user } = useAuth();
  const base = user?.jira_base_url || '';
  return {
    issueUrl: (issueKey) => jiraIssueUrl(base, issueKey),
    projectUrl: (projectKey) => jiraProjectUrl(base, projectKey),
  };
}

export function OpenIssueOnJira({ issueKey, children = 'Mở issue trên Jira', ...props }) {
  const { issueUrl } = useJiraLinks();
  const href = issueUrl(issueKey);
  if (!href) return null;
  return (
    <Button
      {...external}
      href={href}
      variant="light"
      color="blue"
      size="xs"
      leftSection={<IconExternalLink size={14} />}
      {...props}
    >
      {children}
    </Button>
  );
}

export function OpenProjectOnJira({ projectKey, children = 'Mở dự án trên Jira', ...props }) {
  const { projectUrl } = useJiraLinks();
  const href = projectUrl(projectKey);
  if (!href) return null;
  return (
    <Button
      {...external}
      href={href}
      variant="default"
      size="xs"
      leftSection={<IconExternalLink size={14} />}
      {...props}
    >
      {children}
    </Button>
  );
}

export function OpenProjectIcon({ projectKey }) {
  const { projectUrl } = useJiraLinks();
  const href = projectUrl(projectKey);
  if (!href) return null;
  return (
    <Tooltip label="Mở dự án trên Jira" withArrow position="bottom">
      <ActionIcon
        {...external}
        href={href}
        variant="light"
        color="blue"
        size="md"
        radius="md"
        aria-label={`Mở dự án ${projectKey} trên Jira`}
      >
        <IconExternalLink size={18} stroke={1.5} />
      </ActionIcon>
    </Tooltip>
  );
}
