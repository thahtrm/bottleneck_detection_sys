import duckdb
import time

con = duckdb.connect("data/jira.duckdb", read_only=True)

print("==================================================")
print("5. DWELL TIME BY STATUS (FROM CHANGELOGS ACROSS DATASET)")
print("==================================================")
t0 = time.time()

# Let's compute dwell time between status changes
# Each status segment starts at previous change and ends at current change
q_dwell = """
WITH status_events AS (
    SELECT 
        instance,
        issue_key,
        to_value as status_id,
        created_ts,
        lead(created_ts) OVER (PARTITION BY issue_key ORDER BY created_ts ASC) as next_ts
    FROM issue_changelogs
    WHERE field = 'status'
),
segments AS (
    SELECT 
        status_id,
        (next_ts - created_ts) / 86400.0 as dwell_days
    FROM status_events
    WHERE next_ts IS NOT NULL AND next_ts >= created_ts
)
SELECT 
    CASE 
        WHEN status_id = '1' THEN 'Open (Backlog / Tồn đọng)'
        WHEN status_id IN ('2', '3', '10002') THEN 'In Progress (Đang thực hiện)'
        WHEN status_id = '4' THEN 'Reopened (Mở lại)'
        WHEN status_id = '5' THEN 'Resolved (Đã giải quyết)'
        WHEN status_id = '6' THEN 'Closed (Đã đóng)'
        WHEN status_id IN ('10011', '10013') THEN 'Waiting / Review'
        ELSE 'Other Status (' || status_id || ')'
    END as status_group,
    count(*) as segment_count,
    round(quantile_cont(dwell_days, 0.25), 2) as p25_days,
    round(quantile_cont(dwell_days, 0.50), 2) as p50_days,
    round(quantile_cont(dwell_days, 0.75), 2) as p75_days,
    round(quantile_cont(dwell_days, 0.90), 2) as p90_days,
    round(quantile_cont(dwell_days, 0.99), 2) as p99_days,
    round(avg(dwell_days), 2) as mean_days
FROM segments
GROUP BY 1
ORDER BY segment_count DESC
LIMIT 10
"""
res_dwell = con.execute(q_dwell).fetchdf()
print(res_dwell.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")

print("==================================================")
print("6. INACTIVITY DURATION FOR OPEN ISSUES (378,115 ISSUES)")
print("==================================================")
t0 = time.time()
# Maximum timestamp in the dataset to act as snapshot time
max_ts_q = "SELECT max(updated_ts) FROM issues"
max_ts = con.execute(max_ts_q).fetchone()[0]

q_idle = f"""
SELECT 
    count(*) as total_open,
    round(quantile_cont(({max_ts} - updated_ts) / 86400.0, 0.25), 2) as p25_idle_days,
    round(quantile_cont(({max_ts} - updated_ts) / 86400.0, 0.50), 2) as p50_idle_days,
    round(quantile_cont(({max_ts} - updated_ts) / 86400.0, 0.75), 2) as p75_idle_days,
    round(quantile_cont(({max_ts} - updated_ts) / 86400.0, 0.90), 2) as p90_idle_days,
    round(quantile_cont(({max_ts} - updated_ts) / 86400.0, 0.99), 2) as p99_idle_days,
    round(avg(({max_ts} - updated_ts) / 86400.0), 2) as mean_idle_days
FROM issues
WHERE resolved_ts IS NULL OR resolved_ts < created_ts
"""
res_idle = con.execute(q_idle).fetchdf()
print(res_idle.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")

print("==================================================")
print("7. INTER-EVENT INTERVAL DYNAMICS (ACROSS ALL EVENTS)")
print("==================================================")
t0 = time.time()
# Inter-event intervals from v_tgn_events or issue_changelogs
q_intervals = """
WITH ev_sample AS (
    SELECT 
        issue_key,
        created_ts,
        lead(created_ts) OVER (PARTITION BY issue_key ORDER BY created_ts ASC) as next_ts
    FROM issue_changelogs
    WHERE instance IN ('Apache', 'Spring', 'Mojang', 'JFrog', 'RedHat')
),
diffs AS (
    SELECT (next_ts - created_ts) / 86400.0 as interval_days
    FROM ev_sample
    WHERE next_ts IS NOT NULL AND next_ts >= created_ts
)
SELECT 
    count(*) as sampled_transitions,
    round(quantile_cont(interval_days, 0.10), 4) as p10_days,
    round(quantile_cont(interval_days, 0.25), 4) as p25_days,
    round(quantile_cont(interval_days, 0.50), 4) as p50_days,
    round(quantile_cont(interval_days, 0.75), 4) as p75_days,
    round(quantile_cont(interval_days, 0.90), 4) as p90_days,
    round(quantile_cont(interval_days, 0.95), 4) as p95_days,
    round(quantile_cont(interval_days, 0.99), 4) as p99_days,
    round(avg(interval_days), 2) as mean_days
FROM diffs
"""
res_int = con.execute(q_intervals).fetchdf()
print(res_int.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")
