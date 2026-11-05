import duckdb
import pandas as pd
import numpy as np
import time
import re
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, average_precision_score, confusion_matrix
import lightgbm as lgb
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

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
links_df = con.execute("SELECT source_key, target_key, direction FROM issue_links WHERE instance = 'JFrog'").df()
con.close()

blocks_map = links_df[links_df["direction"] == 1].groupby("source_key").size().to_dict()
depends_map = links_df[links_df["direction"] == 0].groupby("source_key").size().to_dict()

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

# NLP features
summaries = df['summary'].fillna('').tolist()
words = np.array([max(1, len(s.split())) for s in summaries])
lens = np.array([len(s) for s in summaries])

ambiguity_pattern = re.compile(
    r"\b(maybe|could|should|consider|optional|review|investigate|unknown|todo|tbd|tentative|possible|need|depend)\b",
    re.I,
)
amb_counts = np.array([len(ambiguity_pattern.findall(s)) for s in summaries], dtype=int)
amb_score = np.round(amb_counts / words, 4)

theme_weights = {"requirements": 4.0, "maintenance": 2.0, "development": 1.0, "other": 1.0}
theme_w = np.array([theme_weights.get(t, 1.0) for t in t_arr])
sp_arr = np.round(1.0 + 3.0 * p_arr + theme_w + np.minimum(words / 15.0, 2.0)).astype(float)

# Simulation
events = []
for i in range(len(df)):
    events.append((created_arr[i], 1, i))
    events.append((resolved_arr[i], 0, i))
events.sort(key=lambda x: (x[0], x[1]))

N = len(df)
assignee_active = defaultdict(dict)
assignee_resolved = defaultdict(list)
reporter_resolved = defaultdict(list)
project_active = defaultdict(dict)
project_resolved = defaultdict(list)
unassigned_active = dict()
unassigned_resolved = list()

# Arrays
f_ass_act_cnt = np.zeros(N)
f_ass_act_sp = np.zeros(N)
f_ass_hist_completed = np.zeros(N)
f_ass_hist_del_rate = np.zeros(N)
f_ass_hist_cycle = np.zeros(N)
f_ass_90d_del_rate = np.zeros(N)
f_ass_90d_completed = np.zeros(N)
f_ass_90d_cycle = np.zeros(N)
f_ass_wci = np.zeros(N)

f_rep_hist_completed = np.zeros(N)
f_rep_hist_del_rate = np.zeros(N)
f_rep_90d_completed = np.zeros(N)
f_rep_90d_del_rate = np.zeros(N)

f_prj_act_cnt = np.zeros(N)
f_prj_hist_completed = np.zeros(N)
f_prj_hist_del_rate = np.zeros(N)
f_prj_90d_completed = np.zeros(N)
f_prj_90d_del_rate = np.zeros(N)
f_prj_90d_cycle = np.zeros(N)

f_unass_act_cnt = np.zeros(N)
f_unass_90d_del_rate = np.zeros(N)

W90 = 90.0 * 86400.0

for ts, ev_type, i in events:
    ass = assignee_arr[i]
    rep = reporter_arr[i]
    prj = proj_arr[i]
    is_unass = (ass == '(unassigned)')

    if ev_type == 0: # RESOLUTION
        d = dur_arr[i]
        dl = is_delayed[i]
        sp = sp_arr[i]

        assignee_active[ass].pop(i, None)
        project_active[prj].pop(i, None)
        if is_unass:
            unassigned_active.pop(i, None)
            unassigned_resolved.append((ts, dl))

        assignee_resolved[ass].append((ts, d, dl, sp))
        reporter_resolved[rep].append((ts, dl))
        project_resolved[prj].append((ts, d, dl, sp))

    else: # CREATION
        # Assignee stats
        act_dict = assignee_active[ass]
        f_ass_act_cnt[i] = len(act_dict)
        f_ass_act_sp[i] = sum(x[1] for x in act_dict.values())

        # WCI
        wci = 0.0
        items = list(act_dict.values())
        if len(items) > 30: items = items[-30:]
        for due_ts, s_val in items:
            days_left = max(1.0, (due_ts - ts) / 86400.0)
            wci += s_val / days_left
        f_ass_wci[i] = wci

        ass_res = assignee_resolved[ass]
        tot_cnt = len(ass_res)
        f_ass_hist_completed[i] = tot_cnt
        if tot_cnt > 0:
            f_ass_hist_del_rate[i] = np.mean([x[2] for x in ass_res])
            f_ass_hist_cycle[i] = np.mean([x[1] for x in ass_res])
        else:
            f_ass_hist_del_rate[i] = 0.5
            f_ass_hist_cycle[i] = planned[i]

        res_90 = [x for x in ass_res if ts - x[0] <= W90]
        f_ass_90d_completed[i] = len(res_90)
        if len(res_90) > 0:
            f_ass_90d_del_rate[i] = np.mean([x[2] for x in res_90])
            f_ass_90d_cycle[i] = np.mean([x[1] for x in res_90])
        else:
            f_ass_90d_del_rate[i] = f_ass_hist_del_rate[i]
            f_ass_90d_cycle[i] = f_ass_hist_cycle[i]

        # Reporter stats
        rep_res = reporter_resolved[rep]
        r_tot = len(rep_res)
        f_rep_hist_completed[i] = r_tot
        f_rep_hist_del_rate[i] = np.mean([x[1] for x in rep_res]) if r_tot > 0 else 0.5
        r_90 = [x for x in rep_res if ts - x[0] <= W90]
        f_rep_90d_completed[i] = len(r_90)
        f_rep_90d_del_rate[i] = np.mean([x[1] for x in r_90]) if len(r_90) > 0 else f_rep_hist_del_rate[i]

        # Project stats
        f_prj_act_cnt[i] = len(project_active[prj])
        prj_res = project_resolved[prj]
        p_tot = len(prj_res)
        f_prj_hist_completed[i] = p_tot
        if p_tot > 0:
            f_prj_hist_del_rate[i] = np.mean([x[2] for x in prj_res])
        else:
            f_prj_hist_del_rate[i] = 0.5
        p_90 = [x for x in prj_res if ts - x[0] <= W90]
        f_prj_90d_completed[i] = len(p_90)
        if len(p_90) > 0:
            f_prj_90d_del_rate[i] = np.mean([x[2] for x in p_90])
            f_prj_90d_cycle[i] = np.mean([x[1] for x in p_90])
        else:
            f_prj_90d_del_rate[i] = f_prj_hist_del_rate[i]
            f_prj_90d_cycle[i] = planned[i]

        # Unassigned stats
        f_unass_act_cnt[i] = len(unassigned_active)
        u_90 = [x for x in unassigned_resolved if ts - x[0] <= W90]
        f_unass_90d_del_rate[i] = np.mean([x[1] for x in u_90]) if len(u_90) > 0 else 0.5

        # Register active
        due = ts + planned[i] * 86400.0
        assignee_active[ass][i] = (due, sp_arr[i])
        project_active[prj][i] = (due, sp_arr[i])
        if is_unass:
            unassigned_active[i] = (due, sp_arr[i])

created_dt = pd.to_datetime(df['created_ts'], unit='s', utc=True)
k_list = df['issue_key'].tolist()

scf = np.round(planned / np.maximum(1.0, f_ass_hist_cycle), 4)

df_all = pd.DataFrame({
    'issue_key': k_list,
    'priority_norm': p_arr,
    'planned_duration_days': planned,
    'story_points': sp_arr,
    'sp_planned_ratio': sp_arr / (planned + 1e-4),
    'sp_planned_product': sp_arr * planned,
    'summary_len': lens,
    'word_count': words,
    'ambiguity_score': amb_score,
    'num_links': df['num_links'].fillna(0).astype(int).values,
    'has_block_or_depend': df['has_block_or_depend'].astype(int).values,
    'blocks_count': [blocks_map.get(k, 0) for k in k_list],
    'depends_count': [depends_map.get(k, 0) for k in k_list],
    'is_unassigned': (assignee_arr == '(unassigned)').astype(int),
    'is_unassigned_reporter': (reporter_arr == '(unassigned)').astype(int),
    'assignee_active_count': f_ass_act_cnt,
    'assignee_active_sp': f_ass_act_sp,
    'assignee_hist_completed': f_ass_hist_completed,
    'assignee_hist_cycle_time': f_ass_hist_cycle,
    'assignee_hist_delay_rate': f_ass_hist_del_rate,
    'assignee_90d_completed': f_ass_90d_completed,
    'assignee_90d_cycle_time': f_ass_90d_cycle,
    'assignee_90d_delay_rate': f_ass_90d_del_rate,
    'assignee_wci': f_ass_wci,
    'scf': scf,
    'reporter_hist_completed': f_rep_hist_completed,
    'reporter_hist_delay_rate': f_rep_hist_del_rate,
    'reporter_90d_completed': f_rep_90d_completed,
    'reporter_90d_delay_rate': f_rep_90d_del_rate,
    'project_active_count': f_prj_act_cnt,
    'project_hist_completed': f_prj_hist_completed,
    'project_hist_delay_rate': f_prj_hist_del_rate,
    'project_90d_completed': f_prj_90d_completed,
    'project_90d_cycle_time': f_prj_90d_cycle,
    'project_90d_delay_rate': f_prj_90d_del_rate,
    'unassigned_active_count': f_unass_act_cnt,
    'unassigned_90d_delay_rate': f_unass_90d_del_rate,
    'created_year': created_dt.dt.year.values,
    'created_month': created_dt.dt.month.values,
    'created_dayofweek': created_dt.dt.dayofweek.values,
    'project': df['project'].astype('category').cat.codes.values,
    'issuetype': df['issuetype'].astype('category').cat.codes.values,
    'issuetype_theme': df['issuetype_theme'].astype('category').cat.codes.values,
})

# Add TF-IDF from summary
n_train = int(0.70 * N)
n_val = int(0.15 * N)

tfidf = TfidfVectorizer(max_features=30, stop_words='english', ngram_range=(1,2))
tfidf_train = tfidf.fit_transform(summaries[:n_train]).toarray()
tfidf_val = tfidf.transform(summaries[n_train:n_train+n_val]).toarray()
tfidf_test = tfidf.transform(summaries[n_train+n_val:]).toarray()
tfidf_all = np.vstack([tfidf_train, tfidf_val, tfidf_test])
for col_idx, feat in enumerate(tfidf.get_feature_names_out()):
    df_all[f'tfidf_{feat}'] = tfidf_all[:, col_idx]

feat_cols = [c for c in df_all.columns if c not in ['issue_key', 'created_year']]

X_tr = df_all.iloc[:n_train][feat_cols]
y_tr = is_delayed[:n_train]

X_va = df_all.iloc[n_train:n_train+n_val][feat_cols]
y_va = is_delayed[n_train:n_train+n_val]

X_te = df_all.iloc[n_train+n_val:][feat_cols]
y_te = is_delayed[n_train+n_val:]

print(f'Feature matrix shape: {X_tr.shape}')

# Train XGBoost
m_xgb = xgb.XGBClassifier(n_estimators=200, max_depth=5, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=3.0, random_state=42, n_jobs=-1)
m_xgb.fit(X_tr, y_tr)
p_va_xgb = m_xgb.predict_proba(X_va)[:, 1]
p_te_xgb = m_xgb.predict_proba(X_te)[:, 1]

# Train LightGBM
m_lgb = lgb.LGBMClassifier(n_estimators=200, max_depth=5, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=3.0, random_state=42, n_jobs=-1, verbose=-1)
m_lgb.fit(X_tr, y_tr)
p_va_lgb = m_lgb.predict_proba(X_va)[:, 1]
p_te_lgb = m_lgb.predict_proba(X_te)[:, 1]

# Train RF
m_rf = RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=5, random_state=42, n_jobs=-1)
m_rf.fit(X_tr, y_tr)
p_va_rf = m_rf.predict_proba(X_va)[:, 1]
p_te_rf = m_rf.predict_proba(X_te)[:, 1]

p_va_blend = (p_va_xgb + p_va_lgb + p_va_rf) / 3.0
p_te_blend = (p_te_xgb + p_te_lgb + p_te_rf) / 3.0

print(f'Val ROC-AUC: XGB={roc_auc_score(y_va, p_va_xgb):.4f}, LGB={roc_auc_score(y_va, p_va_lgb):.4f}, RF={roc_auc_score(y_va, p_va_rf):.4f}, Blend={roc_auc_score(y_va, p_va_blend):.4f}')
print(f'Test ROC-AUC: XGB={roc_auc_score(y_te, p_te_xgb):.4f}, LGB={roc_auc_score(y_te, p_te_lgb):.4f}, RF={roc_auc_score(y_te, p_te_rf):.4f}, Blend={roc_auc_score(y_te, p_te_blend):.4f}')

# Max possible test F1 on blend
best_f1, best_thr = 0, 0
for thr in np.arange(0.1, 0.9, 0.01):
    f1 = f1_score(y_te, (p_te_blend >= thr).astype(int), zero_division=0)
    if f1 > best_f1:
        best_f1 = f1
        best_thr = thr
p = precision_score(y_te, (p_te_blend >= best_thr).astype(int))
r = recall_score(y_te, (p_te_blend >= best_thr).astype(int))
print(f'Max possible Test F1 (blend): {best_f1:.4f} at thr={best_thr:.2f} (Prec: {p:.4f}, Rec: {r:.4f})')
