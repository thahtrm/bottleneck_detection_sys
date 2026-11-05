import duckdb
import numpy as np
import pandas as pd
import time

con = duckdb.connect("data/jira.duckdb", read_only=True)

print("==================================================")
print("1. OVERALL CYCLE TIME PERCENTILES (2,308,108 RESOLVED ISSUES)")
print("==================================================")
t0 = time.time()
q_overall = """
SELECT 
    count(*) as count_resolved,
    min((resolved_ts - created_ts) / 86400.0) as min_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.05) as p05_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.10) as p10_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.25) as p25_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.50) as p50_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.75) as p75_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.90) as p90_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.95) as p95_days,
    quantile_cont((resolved_ts - created_ts) / 86400.0, 0.99) as p99_days,
    max((resolved_ts - created_ts) / 86400.0) as max_days,
    avg((resolved_ts - created_ts) / 86400.0) as mean_days,
    stddev((resolved_ts - created_ts) / 86400.0) as std_days
FROM issues
WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts
"""
res_overall = con.execute(q_overall).fetchdf()
print(res_overall.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")

print("==================================================")
print("2. CYCLE TIME DISTRIBUTION BY INSTANCE (16 ECOSYSTEMS)")
print("==================================================")
t0 = time.time()
q_inst = """
SELECT 
    instance,
    count(*) as total_resolved,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.25), 2) as p25_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.50), 2) as p50_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.75), 2) as p75_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.90), 2) as p90_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.99), 2) as p99_days,
    round(avg((resolved_ts - created_ts) / 86400.0), 2) as mean_days
FROM issues
WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts
GROUP BY instance
ORDER BY total_resolved DESC
"""
res_inst = con.execute(q_inst).fetchdf()
print(res_inst.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")

print("==================================================")
print("3. CYCLE TIME DISTRIBUTION BY THEME (WORK CATEGORY)")
print("==================================================")
t0 = time.time()
q_theme = """
SELECT 
    issuetype_theme,
    count(*) as total_resolved,
    round(count(*) * 100.0 / (SELECT count(*) FROM issues WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts), 2) as pct_share,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.25), 2) as p25_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.50), 2) as p50_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.75), 2) as p75_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.90), 2) as p90_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.99), 2) as p99_days,
    round(avg((resolved_ts - created_ts) / 86400.0), 2) as mean_days
FROM issues
WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts
GROUP BY issuetype_theme
ORDER BY total_resolved DESC
"""
res_theme = con.execute(q_theme).fetchdf()
print(res_theme.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")

print("==================================================")
print("4. CYCLE TIME DISTRIBUTION BY PRIORITY LEVEL")
print("==================================================")
t0 = time.time()
q_priority = """
SELECT 
    CASE 
        WHEN lower(priority_raw) LIKE '%blocker%' THEN 'Blocker'
        WHEN lower(priority_raw) LIKE '%critical%' THEN 'Critical'
        WHEN lower(priority_raw) LIKE '%major%' THEN 'Major'
        WHEN lower(priority_raw) LIKE '%minor%' THEN 'Minor'
        WHEN lower(priority_raw) LIKE '%trivial%' THEN 'Trivial'
        WHEN lower(priority_raw) LIKE '%high%' THEN 'High'
        WHEN lower(priority_raw) LIKE '%medium%' THEN 'Medium'
        WHEN lower(priority_raw) LIKE '%low%' THEN 'Low'
        ELSE 'Other / Unspecified'
    END as priority_group,
    count(*) as total_resolved,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.25), 2) as p25_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.50), 2) as p50_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.75), 2) as p75_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.90), 2) as p90_days,
    round(quantile_cont((resolved_ts - created_ts) / 86400.0, 0.99), 2) as p99_days,
    round(avg((resolved_ts - created_ts) / 86400.0), 2) as mean_days
FROM issues
WHERE resolved_ts IS NOT NULL AND resolved_ts >= created_ts
GROUP BY 1
ORDER BY total_resolved DESC
"""
res_prio = con.execute(q_priority).fetchdf()
print(res_prio.to_string(index=False))
print(f"Time: {time.time()-t0:.2f}s\n")
