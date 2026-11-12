import duckdb
import numpy as np
import pandas as pd
import json
import time

con = duckdb.connect("data/jira.duckdb", read_only=True)
n_issues = 2686223

print("=== 2.4.4. PROCESS BEHAVIOR ANALYSIS ===")
# 1. Reopen
reopen_q = """
WITH re AS (
    SELECT 
        issue_key,
        count(*) as reopen_count
    FROM issue_changelogs 
    WHERE field = 'status' 
      AND ((from_value IN ('5', '6') AND to_value NOT IN ('5', '6')) OR to_value = '4' OR lower(to_value) LIKE '%reopen%')
    GROUP BY issue_key
)
SELECT 
    CASE 
        WHEN reopen_count = 1 THEN '1 time'
        WHEN reopen_count = 2 THEN '2 times'
        ELSE '>= 3 times'
    END as bucket,
    count(*) as num_issues,
    sum(reopen_count) as total_reopens
FROM re
GROUP BY 1
ORDER BY 1
"""
print("Reopen breakdown:")
for row in con.execute(reopen_q).fetchall():
    print(" ", row)

# 2. Status Transitions (Direct Close vs In Progress)
direct_close_q = """
WITH status_flows AS (
    SELECT 
        issue_key,
        bool_or(to_value IN ('2', '3', '10002', '10011') OR lower(to_value) LIKE '%progress%') as went_in_progress,
        bool_or(to_value IN ('5', '6') OR lower(to_value) IN ('closed', 'resolved', 'done')) as reached_done
    FROM issue_changelogs
    WHERE field = 'status'
    GROUP BY issue_key
)
SELECT 
    went_in_progress,
    reached_done,
    count(*) as num_issues
FROM status_flows
GROUP BY 1, 2
"""
print("\nStatus Flow Breakdown:")
for row in con.execute(direct_close_q).fetchall():
    print(" ", row)

# 3. Dwell time / cycle time percentiles
print("\nResolution Duration (Cycle Time in days) on resolved issues:")
duration_q = """
SELECT 
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.50) as p50,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.75) as p75,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.90) as p90,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.95) as p95,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.99) as p99,
    avg((resolved_ts - created_ts) / 86400.0) as mean_days
FROM issues
WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts
"""
print(" ", con.execute(duration_q).fetchone())

print("\n=== 2.4.5. DEPENDENCY & RESOURCE NETWORK ANALYSIS ===")
# 1. Links breakdown
link_type_q = """
SELECT 
    link_type_std,
    count(*) as link_count,
    round(count(*) * 100.0 / (SELECT count(*) FROM issue_links), 2) as pct
FROM issue_links
GROUP BY link_type_std
ORDER BY link_count DESC
"""
print("Link Types Distribution:")
for row in con.execute(link_type_q).fetchall():
    print(" ", row)

# Issues with links
issue_links_q = """
SELECT 
    count(DISTINCT issue_key) as issues_with_any_link,
    count(DISTINCT CASE WHEN has_block_or_depend THEN issue_key END) as issues_with_bod
FROM issues
WHERE num_links > 0
"""
print("\nIssues with Links:")
print(" ", con.execute(issue_links_q).fetchone())

# Self-loops in event stream
events_q = """
SELECT 
    kind,
    count(*) as total_events
FROM v_tgn_events
GROUP BY kind
ORDER BY 2 DESC
"""
print("\nTGN Events by Kind:")
try:
    for row in con.execute(events_q).fetchall():
        print(" ", row)
except Exception as e:
    print("  v_tgn_events error:", e)

# 2. Resource Allocation Inequality & Gini
assignee_q = """
SELECT 
    assignee,
    count(*) as task_count
FROM issues
WHERE assignee IS NOT NULL AND assignee NOT IN ('', '(unassigned)')
GROUP BY assignee
ORDER BY task_count ASC
"""
df_ass = con.execute(assignee_q).fetchdf()
n_devs = len(df_ass)
y = df_ass["task_count"].values
n = len(y)
# Gini
gini = (2.0 * np.sum(np.arange(1, n + 1) * y)) / (n * np.sum(y)) - (n + 1) / n
total_tasks = np.sum(y)

# Top shares
y_desc = np.sort(y)[::-1]
top1_n = max(1, int(np.ceil(0.01 * n)))
top5_n = max(1, int(np.ceil(0.05 * n)))
top10_n = max(1, int(np.ceil(0.10 * n)))
top10_abs = min(10, n)

top1_share = np.sum(y_desc[:top1_n]) / total_tasks * 100
top5_share = np.sum(y_desc[:top5_n]) / total_tasks * 100
top10_share = np.sum(y_desc[:top10_n]) / total_tasks * 100
top10_abs_share = np.sum(y_desc[:top10_abs]) / total_tasks * 100

print(f"\nUnique Assignees: {n_devs:,}")
print(f"Gini Coefficient: {gini:.4f}")
print(f"Top 1% assignees ({top1_n:,} people) share: {top1_share:.2f}%")
print(f"Top 5% assignees ({top5_n:,} people) share: {top5_share:.2f}%")
print(f"Top 10% assignees ({top10_n:,} people) share: {top10_share:.2f}%")
print(f"Top 10 individual assignees share: {top10_abs_share:.2f}%")

# Unassigned rate
unassigned_q = """
SELECT 
    count(CASE WHEN assignee IS NULL OR assignee IN ('', '(unassigned)') THEN 1 END) as unassigned_count,
    count(*) as total_count
FROM issues
"""
un_res = con.execute(unassigned_q).fetchone()
print(f"Unassigned Tasks: {un_res[0]:,} / {un_res[1]:,} ({un_res[0]/un_res[1]*100:.2f}%)")
