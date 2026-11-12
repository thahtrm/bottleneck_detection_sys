# Score delay

Score delay writes one row per selected issue with `p_delay`, `is_at_risk`, and `predicted_duration_days`, using the delay bundle on a Jira DuckDB.

## Sub-features

- `score-open` scores issues that are still open, the default.
- `score-keys` scores only the uids listed in a file.
- `score-as-of` scores issues open at a timestamp the user passes.

## How to get to it (user POV)

- Run `erd score delay` with `--bundle`, `--db`, `--emb-dir`, and `--out`.
- Add `--keys-file` with one `instance|issue_key` per line.
- Add `--as-of` with a UTC timestamp. Add `--all-issues` to include issues already resolved by that time.

## Driving it with erd

Preconditions:

- Doctor passed.
- `bundles/delay` exists.
- `data/jira.duckdb` exists.
- `data/` contains the Ollama embedding arrays the README names (`emb_row_to_unique_all.npy` and `emb_unique_all_fp16.npy`, or the uid parquet plus the fp16 matrix). If they are missing, stop. The failure reason is the missing path.

- **Score open issues.** Run `.venv/bin/erd score delay --bundle bundles/delay --db data/jira.duckdb --emb-dir data --out /tmp/verify-erd-$RUN_ID/delay.csv`. Exit code 0. Stdout contains `wrote` and a row count. The CSV header includes `p_delay` and `is_at_risk`.
- **Proof.** Copy the CSV and the stdout into `.cursor/skills/verify-erd/proof/score-delay/`. Re-read the CSV and confirm the row count matches the `wrote` line.

## Gotchas

- The default scores issues open at the current time. An empty CSV can mean nothing is open. That is a result, not a license to switch the database.
- `--out` is the only file this command should create. Do not reuse another run's path.
- This command reads the whole DuckDB to rebuild T0 features. It does not need a GPU. It can take a long time on the full 2.68 million issue database.
- Do not pass `--ollama` unless the missing-embedding path is the journey under test. A live embedding server is a different entry point.
