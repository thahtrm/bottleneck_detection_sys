import duckdb
import numpy as np
import json
import time

con = duckdb.connect("data/jira.duckdb", read_only=True)

print("==================================================")
print("1. OVERALL DATASET SCALE (16 INSTANCES)")
print("==================================================")
t0 = time.time()
n_issues = con.execute("SELECT count(*) FROM issues").fetchone()[0]
n_changelogs = con.execute("SELECT count(*) FROM issue_changelogs").fetchone()[0]
n_comments = con.execute("SELECT count(*) FROM issue_comments").fetchone()[0]
n_links = con.execute("SELECT count(*) FROM issue_links").fetchone()[0]
print(f"Total Issues: {n_issues:,}")
print(f"Total Changelogs: {n_changelogs:,}")
print(f"Total Comments: {n_comments:,}")
print(f"Total Links: {n_links:,}")
print(f"Time: {time.time()-t0:.2f}s\n")

print("==================================================")
print("2. PROCESS BEHAVIOR ANALYSIS (2.4.4)")
print("==================================================")
t0 = time.time()
# 2.1 Reopen Rate
print("--- 2.1 Reopen Rate ---")
reopen_query = """
SELECT 
    count(DISTINCT issue_key) as issues_with_reopen,
    count(*) as total_reopen_events
FROM issue_changelogs 
WHERE field = 'status' 
  AND (
      lower(to_value) LIKE '%reopen%' 
      OR (lower(from_value) IN ('closed', 'resolved', 'done') AND lower(to_value) NOT IN ('closed', 'resolved', 'done'))
  )
"""
reopen_res = con.execute(reopen_query).fetchone()
issues_reopened = reopen_res[0]
total_reopen_events = reopen_res[1]
pct_reopened = (issues_reopened / n_issues) * 100
print(f"Issues Reopened: {issues_reopened:,} ({pct_reopened:.2f}% of all issues)")
print(f"Total Reopen Events: {total_reopen_events:,}")

# 2.2 Ping-Pong Assignment (Assignee changes)
print("\n--- 2.2 Ping-Pong Assignment ---")
pingpong_query = """
WITH chg AS (
    SELECT issue_key, count(*) as n_chg
    FROM issue_changelogs
    WHERE field = 'assignee'
    GROUP BY issue_key
)
SELECT 
    CASE 
        WHEN n_chg = 1 THEN '1 change'
        WHEN n_chg = 2 THEN '2 changes'
        WHEN n_chg >= 3 THEN '>= 3 changes (Ping-Pong)'
    END as bucket,
    count(*) as count_issues
FROM chg
GROUP BY 1
ORDER BY 1
"""
pingpong_res = con.execute(pingpong_query).fetchall()
chg_map = dict(pingpong_res)
n_ge_3 = chg_map.get('>= 3 changes (Ping-Pong)', 0)
n_1 = chg_map.get('1 change', 0)
n_2 = chg_map.get('2 changes', 0)
total_with_chg = n_1 + n_2 + n_ge_3
print(f"Issues with >= 3 assignee changes: {n_ge_3:,} ({n_ge_3/n_issues*100:.2f}% of all issues)")
print(f"Issues with 1 change: {n_1:,} ({n_1/n_issues*100:.2f}%)")
print(f"Issues with 2 changes: {n_2:,} ({n_2/n_issues*100:.2f}%)")
print(f"Issues with at least 1 assignee change: {total_with_chg:,} ({total_with_chg/n_issues*100:.2f}%)")

# 2.3 Bulk Close Anomalies
print("\n--- 2.3 Bulk Close Anomalies ---")
bulk_close_query = """
WITH minute_closures AS (
    SELECT 
        instance,
        author,
        to_timestamp(created_ts)::DATE as close_date,
        epoch(to_timestamp(created_ts)) // 60 as close_minute,
        count(DISTINCT issue_key) as cnt
    FROM issue_changelogs
    WHERE field = 'status'
      AND lower(to_value) IN ('closed', 'resolved', 'done')
    GROUP BY instance, author, close_date, close_minute
    HAVING cnt >= 20
)
SELECT 
    count(*) as num_bulk_episodes,
    sum(cnt) as total_bulk_issues
FROM minute_closures
"""
bulk_res = con.execute(bulk_close_query).fetchone()
num_bulk_episodes = bulk_res[0]
total_bulk_issues = bulk_res[1]
print(f"Bulk Close Episodes (>=20 issues/min by same author): {num_bulk_episodes:,} episodes")
print(f"Total Issues affected by bulk close: {total_bulk_issues:,} ({total_bulk_issues/n_issues*100:.2f}% of all issues)")

# 2.4 Status transition patterns
print("\n--- 2.4 Status Transitions (Direct Close vs In Progress) ---")
trans_query = """
SELECT 
    CASE 
        WHEN lower(from_value) IN ('open', 'new', 'to do', 'created') AND lower(to_value) IN ('closed', 'resolved', 'done') THEN 'Direct Close (Open -> Closed/Resolved)'
        WHEN lower(from_value) IN ('open', 'new', 'to do', 'created') AND lower(to_value) LIKE '%progress%' THEN 'To In Progress (Open -> In Progress)'
        WHEN lower(from_value) LIKE '%progress%' AND lower(to_value) IN ('closed', 'resolved', 'done') THEN 'Resolved from In Progress'
        ELSE 'Other Transitions'
    END as transition_type,
    count(*) as cnt
FROM issue_changelogs
WHERE field = 'status'
GROUP BY 1
ORDER BY 2 DESC
"""
trans_res = con.execute(trans_query).fetchall()
for t_type, cnt in trans_res:
    print(f"  {t_type}: {cnt:,}")

print(f"Time for Process Behavior: {time.time()-t0:.2f}s\n")
