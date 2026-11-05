-- Chỉ mục phụ cho DuckDB: The Public Jira Dataset
-- Được thực thi sau khi hoàn thành toàn bộ quá trình bulk load

CREATE INDEX IF NOT EXISTS idx_issues_proj ON issues(instance, project);
CREATE INDEX IF NOT EXISTS idx_issues_created ON issues(instance, created_ts);

CREATE INDEX IF NOT EXISTS idx_chg_key ON issue_changelogs(instance, issue_key);
CREATE INDEX IF NOT EXISTS idx_chg_ts ON issue_changelogs(instance, created_ts);
CREATE INDEX IF NOT EXISTS idx_chg_field ON issue_changelogs(instance, field);

CREATE INDEX IF NOT EXISTS idx_links_src ON issue_links(instance, source_key);
CREATE INDEX IF NOT EXISTS idx_links_tgt ON issue_links(instance, target_key);
CREATE INDEX IF NOT EXISTS idx_links_std ON issue_links(instance, link_type_std);

CREATE INDEX IF NOT EXISTS idx_cmt_key ON issue_comments(instance, issue_key);
CREATE INDEX IF NOT EXISTS idx_cmt_ts ON issue_comments(instance, created_ts);
