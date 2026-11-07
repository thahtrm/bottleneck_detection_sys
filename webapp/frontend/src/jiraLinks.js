function siteBase(baseUrl) {
  return String(baseUrl || '').trim().replace(/\/+$/, '');
}

export function jiraIssueUrl(baseUrl, issueKey) {
  const base = siteBase(baseUrl);
  const key = String(issueKey || '').trim();
  if (!base || !key) return null;
  return `${base}/browse/${encodeURIComponent(key)}`;
}

export function jiraProjectUrl(baseUrl, projectKey) {
  const base = siteBase(baseUrl);
  const key = String(projectKey || '').trim();
  if (!base || !key) return null;
  return `${base}/jira/software/projects/${encodeURIComponent(key)}`;
}
