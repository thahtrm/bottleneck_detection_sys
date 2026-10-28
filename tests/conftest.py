"""Shared fixture: a small synthetic Jira DuckDB with the ETL schema."""
from __future__ import annotations

from importlib import resources

import duckdb
import numpy as np
import pandas as pd
import pytest

DAY = 86400.0
T_START = 1_500_000_000.0


def make_jira_db(path, n_issues: int = 400, seed: int = 0) -> str:
    rng = np.random.default_rng(seed)
    con = duckdb.connect(str(path))
    con.execute(resources.files("early_risk_detection.data.etl").joinpath("schema.sql").read_text())
    instances = np.array(["Alpha", "Beta"])
    inst = instances[rng.integers(0, 2, n_issues)]
    proj = np.array([f"P{rng.integers(0, 3)}" for _ in range(n_issues)])
    created = np.sort(T_START + rng.uniform(0, 700 * DAY, n_issues))
    resolved = np.where(rng.random(n_issues) < 0.8, created + rng.exponential(30 * DAY, n_issues), np.nan)
    users = [f"<<|author_name|u{k:02d}|>>" for k in range(12)]
    prio_raw = np.array(["Blocker", "Critical", "Major", "Minor", "Trivial"])
    prio_norm = {"Blocker": 1.0, "Critical": 0.8, "Major": 0.6, "Minor": 0.4, "Trivial": 0.2}
    types = np.array(["Bug", "Task", "New Feature", "Improvement"])
    themes = {"Bug": "Maintenance", "Task": "Development", "New Feature": "Requirements", "Improvement": "Development"}
    words = ["fix", "deadlock", "refactor", "release", "maybe", "timeout", "migrate", "add", "button", "crash"]
    issues = []
    for i in range(n_issues):
        key = f"{proj[i]}-{i}"
        pr = prio_raw[rng.integers(0, 5)]
        it = types[rng.integers(0, 4)]
        issues.append(dict(
            instance=inst[i], issue_key=key, project=proj[i],
            summary=" ".join(rng.choice(words, rng.integers(3, 9))), issuetype=it, issuetype_theme=themes[it],
            priority_raw=pr, priority_norm=prio_norm[pr], status="Closed" if not np.isnan(resolved[i]) else "Open",
            resolution=None, created_ts=created[i], updated_ts=(resolved[i] if not np.isnan(resolved[i]) else created[i] + DAY),
            resolved_ts=resolved[i], assignee=users[rng.integers(0, 12)] if rng.random() < 0.8 else None,
            reporter=users[rng.integers(0, 12)], num_changelogs=0, num_links=0, num_comments=0,
            has_block_or_depend=False))
    idf = pd.DataFrame(issues)
    con.register("idf", idf)
    con.execute("INSERT INTO issues SELECT * FROM idf")
    cl, cm, lk = [], [], []
    for i, r in idf.iterrows():
        t = r.created_ts
        for k in range(rng.integers(0, 4)):
            t += rng.exponential(5 * DAY)
            fld = ["status", "assignee", "priority"][k % 3]
            frm, to = {"status": ("1", "3"), "assignee": (None, users[rng.integers(0, 12)]),
                       "priority": (r.priority_raw, prio_raw[rng.integers(0, 5)])}[fld]
            cl.append(dict(instance=r.instance, issue_key=r.issue_key, change_id=f"c{i}{k}", author=users[0],
                           created_ts=t, field=fld, from_value=frm, to_value=to))
        if not np.isnan(r.resolved_ts):
            cl.append(dict(instance=r.instance, issue_key=r.issue_key, change_id=f"r{i}", author=users[1],
                           created_ts=r.resolved_ts, field="status", from_value="3", to_value="6"))
        for k in range(rng.integers(0, 3)):
            cm.append(dict(instance=r.instance, issue_key=r.issue_key, comment_id=f"m{i}{k}",
                           author=users[rng.integers(0, 12)], created_ts=r.created_ts + rng.exponential(3 * DAY),
                           body_len=int(rng.integers(10, 500)), body_preview="..."))
        if i > 5 and rng.random() < 0.3:
            same = idf.index[(idf.instance == r.instance) & (idf.index < i)]
            if len(same):
                j = int(rng.choice(same))
                lt = ["Block", "Depend", "Relate"][rng.integers(0, 3)]
                lk.append(dict(instance=r.instance, source_key=r.issue_key, target_key=idf.issue_key[j],
                               link_type_raw=lt, link_type_std=lt, direction=1,
                               is_block_or_depend=lt in ("Block", "Depend"), approx_ts=r.created_ts))
    for name, rows in [("issue_changelogs", cl), ("issue_comments", cm), ("issue_links", lk)]:
        con.register("tmp", pd.DataFrame(rows))
        con.execute(f"INSERT INTO {name} SELECT * FROM tmp")
        con.unregister("tmp")
    con.close()
    return str(path)


@pytest.fixture(scope="session")
def jira_db(tmp_path_factory) -> str:
    return make_jira_db(tmp_path_factory.mktemp("db") / "jira.duckdb")
