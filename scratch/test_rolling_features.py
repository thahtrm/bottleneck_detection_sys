import duckdb
import pandas as pd
import numpy as np
import time
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, average_precision_score
import lightgbm as lgb
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier

t0 = time.time()
con = duckdb.connect('data/jira.duckdb', read_only=True)
df = con.execute('''
    SELECT issue_key, project, summary, issuetype, issuetype_theme,
           priority_raw, priority_norm, created_ts, resolved_ts,
           (resolved_ts - created_ts)/86400.0 as duration_days,
           assignee, reporter, num_links, has_block_or_depend
    FROM issues
    WHERE instance = 'JFrog' AND resolved_ts IS NOT NULL AND resolved_ts >= created_ts
    ORDER BY created_ts ASC
''').df()
con.close()

p_arr = df['priority_norm'].fillna(0.4).values
t_arr = df['issuetype_theme'].fillna('Other').str.lower().values
it_arr = df['issuetype'].fillna('Bug').str.lower().values
created_arr = df['created_ts'].values
resolved_arr = df['resolved_ts'].values
dur_arr = df['duration_days'].values
assignee_arr = df['assignee'].fillna('(unassigned)').values
reporter_arr = df['reporter'].fillna('(unassigned)').values
proj_arr = df['project'].values

def get_planned(p, t, it):
    if p >= 0.8: return 14.0
    elif p >= 0.6: return 30.0
    elif 'requirement' in t or 'feature' in it: return 90.0
    elif 'task' in it: return 21.0
    else: return 45.0

planned = np.array([get_planned(p_arr[i], t_arr[i], it_arr[i]) for i in range(len(df))])
is_delayed = (dur_arr > planned).astype(int)
df['planned_days'] = planned
df['is_delayed'] = is_delayed

# Compute story points proxy
theme_w = {'requirements': 4.0, 'maintenance': 2.0, 'development': 1.0, 'other': 1.0}
tw = np.array([theme_w.get(t, 1.0) for t in t_arr])
words = np.array([max(1, len(s.split())) for s in df['summary'].fillna('')])
sp_arr = np.round(1.0 + 3.0 * p_arr + tw + np.minimum(words / 15.0, 2.0))

# Chronological simulation
events = []
for i in range(len(df)):
    events.append((created_arr[i], 1, i))
    events.append((resolved_arr[i], 0, i))
events.sort(key=lambda x: (x[0], x[1]))

N = len(df)
# Rolling resolutions in 90d, 180d
# We track resolved events in a deque or list of (ts, dur, is_del, sp)
ass_resolved_history = defaultdict(list)
rep_resolved_history = defaultdict(list)
prj_resolved_history = defaultdict(list)
unassigned_resolved_history = list()

# Active sets: key -> dict of {i: (created_ts, sp)}
ass_active = defaultdict(dict)
prj_active = defaultdict(dict)
unassigned_active = dict()

# Features to collect
f_ass_active_cnt = np.zeros(N)
f_ass_active_sp = np.zeros(N)
f_ass_res_90d_cnt = np.zeros(N)
f_ass_res_90d_del_rate = np.zeros(N)
f_ass_res_90d_cycle = np.zeros(N)

f_rep_res_90d_cnt = np.zeros(N)
f_rep_res_90d_del_rate = np.zeros(N)

f_prj_active_cnt = np.zeros(N)
f_prj_res_90d_cnt = np.zeros(N)
f_prj_res_90d_del_rate = np.zeros(N)
f_prj_res_90d_cycle = np.zeros(N)

f_unass_active_cnt = np.zeros(N)
f_unass_res_90d_del_rate = np.zeros(N)

DAY_90 = 90.0 * 86400.0

for ts, ev_type, i in events:
    ass = assignee_arr[i]
    rep = reporter_arr[i]
    prj = proj_arr[i]
    is_unass = (ass == '(unassigned)')

    if ev_type == 0: # RESOLUTION
        d_val = dur_arr[i]
        del_val = is_delayed[i]
        sp_val = sp_arr[i]

        ass_active[ass].pop(i, None)
        prj_active[prj].pop(i, None)
        if is_unass:
            unassigned_active.pop(i, None)
            unassigned_resolved_history.append((ts, del_val))

        ass_resolved_history[ass].append((ts, d_val, del_val, sp_val))
        rep_resolved_history[rep].append((ts, del_val))
        prj_resolved_history[prj].append((ts, d_val, del_val, sp_val))

    else: # CREATION
        # 1. Assignee active
        f_ass_active_cnt[i] = len(ass_active[ass])
        f_ass_active_sp[i] = sum(x[1] for x in ass_active[ass].values())

        # Assignee 90d
        recent_ass = [x for x in ass_resolved_history[ass] if ts - x[0] <= DAY_90]
        f_ass_res_90d_cnt[i] = len(recent_ass)
        if len(recent_ass) > 0:
            f_ass_res_90d_del_rate[i] = np.mean([x[2] for x in recent_ass])
            f_ass_res_90d_cycle[i] = np.mean([x[1] for x in recent_ass])
        else:
            f_ass_res_90d_del_rate[i] = 0.5
            f_ass_res_90d_cycle[i] = planned[i]

        # Reporter 90d
        recent_rep = [x for x in rep_resolved_history[rep] if ts - x[0] <= DAY_90]
        f_rep_res_90d_cnt[i] = len(recent_rep)
        f_rep_res_90d_del_rate[i] = np.mean([x[1] for x in recent_rep]) if len(recent_rep) > 0 else 0.5

        # Project 90d
        f_prj_active_cnt[i] = len(prj_active[prj])
        recent_prj = [x for x in prj_resolved_history[prj] if ts - x[0] <= DAY_90]
        f_prj_res_90d_cnt[i] = len(recent_prj)
        if len(recent_prj) > 0:
            f_prj_res_90d_del_rate[i] = np.mean([x[2] for x in recent_prj])
            f_prj_res_90d_cycle[i] = np.mean([x[1] for x in recent_prj])
        else:
            f_prj_res_90d_del_rate[i] = 0.5
            f_prj_res_90d_cycle[i] = planned[i]

        # Unassigned 90d
        f_unass_active_cnt[i] = len(unassigned_active)
        recent_unass = [x for x in unassigned_resolved_history if ts - x[0] <= DAY_90]
        f_unass_res_90d_del_rate[i] = np.mean([x[1] for x in recent_unass]) if len(recent_unass) > 0 else 0.5

        # Record active
        ass_active[ass][i] = (ts, sp_arr[i])
        prj_active[prj][i] = (ts, sp_arr[i])
        if is_unass:
            unassigned_active[i] = (ts, sp_arr[i])

print(f'Rolling simulation done in {time.time()-t0:.2f}s')

# Assemble features
df_feat = pd.DataFrame({
    'priority_norm': p_arr,
    'planned_days': planned,
    'story_points': sp_arr,
    'sp_div_planned': sp_arr / (planned + 1e-4),
    'is_unassigned': (assignee_arr == '(unassigned)').astype(int),
    'ass_active_cnt': f_ass_active_cnt,
    'ass_active_sp': f_ass_active_sp,
    'ass_res_90d_cnt': f_ass_res_90d_cnt,
    'ass_res_90d_del_rate': f_ass_res_90d_del_rate,
    'ass_res_90d_cycle': f_ass_res_90d_cycle,
    'ass_cycle_div_planned': f_ass_res_90d_cycle / (planned + 1e-4),
    'rep_res_90d_cnt': f_rep_res_90d_cnt,
    'rep_res_90d_del_rate': f_rep_res_90d_del_rate,
    'prj_active_cnt': f_prj_active_cnt,
    'prj_res_90d_cnt': f_prj_res_90d_cnt,
    'prj_res_90d_del_rate': f_prj_res_90d_del_rate,
    'prj_res_90d_cycle': f_prj_res_90d_cycle,
    'unass_active_cnt': f_unass_active_cnt,
    'unass_res_90d_del_rate': f_unass_res_90d_del_rate,
})

# Split 70 / 15 / 15
n_train = int(0.70 * N)
n_val = int(0.15 * N)

X_tr = df_feat.iloc[:n_train]
y_tr = is_delayed[:n_train]

X_va = df_feat.iloc[n_train:n_train+n_val]
y_va = is_delayed[n_train:n_train+n_val]

X_te = df_feat.iloc[n_train+n_val:]
y_te = is_delayed[n_train+n_val:]

# Train a lightgbm model
m = lgb.LGBMClassifier(n_estimators=100, max_depth=4, learning_rate=0.03, random_state=42)
m.fit(X_tr, y_tr)

p_va = m.predict_proba(X_va)[:, 1]
p_te = m.predict_proba(X_te)[:, 1]

# Find optimal threshold on Val
best_thr = 0.5
best_f1 = 0
for thr in np.arange(0.1, 0.9, 0.01):
    f1 = f1_score(y_va, (p_va >= thr).astype(int), zero_division=0)
    if f1 > best_f1:
        best_f1 = f1
        best_thr = thr

preds_te = (p_te >= best_thr).astype(int)
print(f'Val Best Thr: {best_thr:.2f}, Val F1: {best_f1:.4f}')
print(f'Test F1: {f1_score(y_te, preds_te):.4f}, Prec: {precision_score(y_te, preds_te):.4f}, Rec: {recall_score(y_te, preds_te):.4f}')
best_te_f1 = 0
best_te_thr = 0
for thr in np.arange(0.1, 0.9, 0.01):
    f1 = f1_score(y_te, (p_te >= thr).astype(int), zero_division=0)
    if f1 > best_te_f1:
        best_te_f1 = f1
        best_te_thr = thr
p = precision_score(y_te, (p_te >= best_te_thr).astype(int))
r = recall_score(y_te, (p_te >= best_te_thr).astype(int))
print(f'Max Test F1 possible: {best_te_f1:.4f} at Thr={best_te_thr:.2f} (Prec: {p:.4f}, Rec: {r:.4f})')
print(f'Test ROC-AUC: {roc_auc_score(y_te, p_te):.4f}, PR-AUC: {average_precision_score(y_te, p_te):.4f}')
