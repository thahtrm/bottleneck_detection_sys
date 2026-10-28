import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr
import time

con = duckdb.connect()

print("=== 2.4.6. RISK LABELS & FEATURE CORRELATIONS (ON ALL MODELING DATA) ===")
t0 = time.time()

# 1. Delay rate overall across train, val, test
print("--- 1. Target Label Distribution (is_delayed) ---")
q_splits = """
SELECT 
    'Train (1998-2019)' as split,
    count(*) as total,
    sum(is_delayed) as delayed,
    round(avg(is_delayed)*100, 2) as delay_pct
FROM "data/train.parquet"
UNION ALL
SELECT 
    'Val (2019-2020)',
    count(*),
    sum(is_delayed),
    round(avg(is_delayed)*100, 2)
FROM "data/val.parquet"
UNION ALL
SELECT 
    'Test (2020-2022)',
    count(*),
    sum(is_delayed),
    round(avg(is_delayed)*100, 2)
FROM "data/test.parquet"
"""
print(con.execute(q_splits).fetchdf())

# 2. Delay rate by is_unassigned
print("\n--- 2. Delay Rate by Assignee Status (Train) ---")
q_unassigned = """
SELECT 
    is_unassigned,
    count(*) as total,
    round(avg(is_delayed)*100, 2) as delay_pct
FROM "data/train.parquet"
GROUP BY 1
"""
print(con.execute(q_unassigned).fetchdf())

# 3. Delay rate by Theme
print("\n--- 3. Delay Rate by Issue Theme (Train) ---")
q_theme = """
SELECT 
    issuetype_theme,
    count(*) as total,
    round(avg(is_delayed)*100, 2) as delay_pct
FROM "data/train.parquet"
GROUP BY 1
ORDER BY total DESC
"""
print(con.execute(q_theme).fetchdf())

# 4. Delay rate by Priority
print("\n--- 4. Delay Rate by Priority (Train) ---")
q_prio = """
SELECT 
    priority_raw,
    count(*) as total,
    round(avg(is_delayed)*100, 2) as delay_pct
FROM "data/train.parquet"
GROUP BY 1
ORDER BY total DESC
LIMIT 10
"""
print(con.execute(q_prio).fetchdf())

# 5. Delay rate by has_block_or_depend
print("\n--- 5. Delay Rate by Dependency Link (Train) ---")
q_bod = """
SELECT 
    has_block_or_depend,
    count(*) as total,
    round(avg(is_delayed)*100, 2) as delay_pct
FROM "data/train.parquet"
GROUP BY 1
"""
print(con.execute(q_bod).fetchdf())

# 6. Feature Correlations with is_delayed on Train
print("\n--- 6. Feature Correlations with is_delayed (Train: 1,615,472 samples) ---")
cols_to_pull = [
    "is_delayed",
    "is_unassigned",
    "assignee_active_count",
    "assignee_hist_completed",
    "assignee_hist_delay_rate",
    "assignee_90d_completed",
    "assignee_90d_delay_rate",
    "project_active_count",
    "project_90d_delay_rate",
    "word_count",
    "ambiguity_score",
    "tech_total_risk",
    "num_links",
    "has_block_or_depend",
    "priority_norm",
    "story_points"
]

df_sample = con.execute(f"""
    SELECT {', '.join(cols_to_pull)}
    FROM "data/train.parquet"
""").fetchdf()

# Add active_per_completed
df_sample["active_per_completed"] = df_sample["assignee_active_count"] / (df_sample["assignee_hist_completed"] + 1.0)
df_sample["sp_filled"] = df_sample["story_points"].fillna(0)

features_to_eval = [
    ("active_per_completed", df_sample["active_per_completed"]),
    ("is_unassigned", df_sample["is_unassigned"]),
    ("assignee_active_count", df_sample["assignee_active_count"]),
    ("project_active_count", df_sample["project_active_count"]),
    ("assignee_hist_delay_rate", df_sample["assignee_hist_delay_rate"]),
    ("assignee_hist_completed", df_sample["assignee_hist_completed"]),
    ("assignee_90d_delay_rate", df_sample["assignee_90d_delay_rate"]),
    ("project_90d_delay_rate", df_sample["project_90d_delay_rate"]),
    ("priority_norm", df_sample["priority_norm"]),
    ("ambiguity_score", df_sample["ambiguity_score"]),
    ("tech_total_risk", df_sample["tech_total_risk"]),
    ("word_count", df_sample["word_count"]),
    ("num_links", df_sample["num_links"]),
    ("has_block_or_depend", df_sample["has_block_or_depend"].astype(int)),
    ("story_points", df_sample["sp_filled"])
]

y = df_sample["is_delayed"].values
corr_results = []
for name, s in features_to_eval:
    vals = s.values.astype(float)
    # clean nan/inf
    mask = ~np.isnan(vals) & ~np.isinf(vals)
    r_pearson, _ = pearsonr(vals[mask], y[mask])
    r_spearman, _ = spearmanr(vals[mask], y[mask])
    corr_results.append({
        "feature": name,
        "pearson": round(float(r_pearson), 4),
        "spearman": round(float(r_spearman), 4)
    })

res_df = pd.DataFrame(corr_results).sort_values("pearson", ascending=False)
print(res_df.to_string(index=False))

print(f"\nExecution time: {time.time()-t0:.2f}s")
