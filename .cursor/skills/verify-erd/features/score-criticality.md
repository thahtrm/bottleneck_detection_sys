# Score criticality

Score criticality writes one row per selected issue with `score`, `rank_in_instance`, and `is_critical`, using the criticality bundle on a Jira DuckDB.

## Sub-features

- `score-open` scores issues that are still open, the default.
- `score-keys` scores only the uids listed in a file.
- `score-cached-stream` reuses an event-stream directory from an earlier score of the same database.

## How to get to it (user POV)

- Run `erd score criticality` with `--bundle`, `--db`, `--emb-dir`, `--stream-dir`, and `--out`.
- Add `--keys-file` with one `instance|issue_key` per line.
- Point `--stream-dir` at an existing directory only when that directory was built for the same DuckDB.

## Driving it with erd

Preconditions:

- Doctor passed.
- `bundles/criticality` exists.
- `data/jira.duckdb` exists.
- Embedding arrays exist under `data/`, the same files as score delay. If they are missing, stop and report that path.

- **Score open issues.** Run `.venv/bin/erd score criticality --bundle bundles/criticality --db data/jira.duckdb --emb-dir data --stream-dir /tmp/verify-erd-$RUN_ID/stream --out /tmp/verify-erd-$RUN_ID/criticality.csv`. Exit code 0. Stdout contains `wrote` and a row count. The CSV header includes `score`, `rank_in_instance`, and `is_critical`.
- **Proof.** Copy the CSV and the stdout into `.cursor/skills/verify-erd/proof/score-criticality/`. Re-read the CSV and confirm the row count matches the `wrote` line.

## Gotchas

- The command replays the event stream before it scores. On the full database that is on the order of a minute and a half on an RTX 4060 Ti and much slower on CPU. Do not kill it and treat a partial CSV as proof.
- `--stream-dir` is private to this run. A stream built for a different database raises an error about the issue count. Do not reuse `data/` as the stream directory.
- Two criticality scores must not share a stream directory.
