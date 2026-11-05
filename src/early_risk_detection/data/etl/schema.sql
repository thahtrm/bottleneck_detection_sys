-- Schema DDL cho DuckDB: The Public Jira Dataset
-- 4 bảng quan hệ và 1 view tổng hợp cho mô hình TGN
-- (Lưu ý: Chỉ mục phụ được dời sang indexes.sql để tối ưu tốc độ nạp bulk load)

-- 1. Bảng issues
CREATE TABLE IF NOT EXISTS issues (
    instance            VARCHAR NOT NULL,
    issue_key           VARCHAR NOT NULL,
    project             VARCHAR NOT NULL,
    summary             VARCHAR,
    issuetype           VARCHAR,
    issuetype_theme     VARCHAR,          -- Requirements | Development | Maintenance | User Support | Other
    priority_raw        VARCHAR,
    priority_norm       DOUBLE,           -- 0.1 đến 1.0 (Blocker cao nhất)
    status              VARCHAR,
    resolution          VARCHAR,
    created_ts          DOUBLE,           -- Epoch giây (clamp >= 0)
    updated_ts          DOUBLE,
    resolved_ts         DOUBLE,
    assignee            VARCHAR,
    reporter            VARCHAR,
    num_changelogs      INTEGER DEFAULT 0,
    num_links           INTEGER DEFAULT 0,
    num_comments        INTEGER DEFAULT 0,
    has_block_or_depend BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (instance, issue_key)
);

-- 2. Bảng issue_changelogs
CREATE TABLE IF NOT EXISTS issue_changelogs (
    instance            VARCHAR NOT NULL,
    issue_key           VARCHAR NOT NULL,
    change_id           VARCHAR,
    author              VARCHAR,
    created_ts          DOUBLE NOT NULL,
    field               VARCHAR NOT NULL, -- status | assignee | priority | resolution ...
    from_value          VARCHAR,
    to_value            VARCHAR
);

-- 3. Bảng issue_links
CREATE TABLE IF NOT EXISTS issue_links (
    instance            VARCHAR NOT NULL,
    source_key          VARCHAR NOT NULL,
    target_key          VARCHAR NOT NULL,
    link_type_raw       VARCHAR,
    link_type_std       VARCHAR NOT NULL, -- Block | Depend | Epic | Parent-Child | Subtask | Fix | Duplicate | Relate | Other
    direction           INTEGER NOT NULL,  -- 1: Outward, 0: Inward
    is_block_or_depend  BOOLEAN NOT NULL,
    approx_ts           DOUBLE NOT NULL
);

-- 4. Bảng issue_comments
CREATE TABLE IF NOT EXISTS issue_comments (
    instance            VARCHAR NOT NULL,
    issue_key           VARCHAR NOT NULL,
    comment_id          VARCHAR,
    author              VARCHAR,
    created_ts          DOUBLE NOT NULL,
    body_len            INTEGER DEFAULT 0,
    body_preview        VARCHAR
);

-- 5. View thống nhất dòng sự kiện cho TGN
CREATE OR REPLACE VIEW v_tgn_events AS
SELECT 
    instance,
    issue_key AS u,
    issue_key AS v,
    created_ts AS ts,
    'status' AS kind,
    from_value AS detail_from,
    to_value AS detail_to,
    NULL AS link_type,
    0 AS direction
FROM issue_changelogs
WHERE field = 'status'

UNION ALL

SELECT 
    instance,
    issue_key AS u,
    COALESCE(NULLIF(to_value, ''), '(unassigned)') AS v,
    created_ts AS ts,
    'assignee' AS kind,
    from_value AS detail_from,
    to_value AS detail_to,
    NULL AS link_type,
    0 AS direction
FROM issue_changelogs
WHERE field = 'assignee'

UNION ALL

SELECT 
    instance,
    issue_key AS u,
    issue_key AS v,
    created_ts AS ts,
    'priority' AS kind,
    from_value AS detail_from,
    to_value AS detail_to,
    NULL AS link_type,
    0 AS direction
FROM issue_changelogs
WHERE field = 'priority'

UNION ALL

SELECT 
    instance,
    source_key AS u,
    target_key AS v,
    approx_ts AS ts,
    'link' AS kind,
    NULL AS detail_from,
    NULL AS detail_to,
    link_type_std AS link_type,
    direction
FROM issue_links

UNION ALL

SELECT 
    instance,
    issue_key AS u,
    COALESCE(author, '(unknown)') AS v,
    created_ts AS ts,
    'comment' AS kind,
    NULL AS detail_from,
    NULL AS detail_to,
    NULL AS link_type,
    0 AS direction
FROM issue_comments;
