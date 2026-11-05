# erd verification map

This directory is the maintained source for verifying the user-facing behavior of the `erd` CLI. Read the index before driving the app, then use the matching feature file as the recipe.

## Baseline preconditions

- The repo root is the current directory, and `.venv/bin/erd` exists (see the skill's Launch section).
- Doctor has exited 0 in this checkout's venv.
- Scratch for this run is `/tmp/verify-erd-$RUN_ID`. Proof goes to `.cursor/skills/verify-erd/proof/` and is not deleted during cleanup.
- `bundles/delay` and `bundles/criticality` are the shipped model directories. Read them. Do not edit them.
- `data/jira.duckdb` and `data/emb_row_to_unique_all.npy` plus `data/emb_unique_all_fp16.npy` are required only by scoring. They are gitignored. If they are missing, the score journeys fail; do not point score at a different database and call it the same journey.

## Driving conventions

- Start every recipe from the baseline unless its preconditions say otherwise.
- Treat every command as literal. Keep flags and paths unchanged except `$RUN_ID` and paths the recipe says to fill.
- Run `.venv/bin/erd`, not a globally installed `erd`.
- Do not pass `--no-verify` to `bundle info`.
- Do not pass `erd eval` without `--leaderboard` pointing inside the scratch directory.

## Proof and skip reporting

- Capture the command, stdout, stderr, and exit code.
- Record the feature ID and the entry point with every artifact.
- A missing DuckDB, embedding, or ground-truth file is a failed journey. Report the command and the missing path. Do not mark the feature verified through `bundle info` instead.
- Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features`
2. `How to get to it (user POV)`
3. `Driving it with erd`
4. `Gotchas`

## Features

- [Bundle info](./bundle-info.md) prints a bundle manifest and rejects a file whose bytes no longer match the manifest.
- [Score delay](./score-delay.md) writes delay-risk rows for issues in a Jira DuckDB.
- [Score criticality](./score-criticality.md) writes criticality ranks for issues in a Jira DuckDB.
- [Eval delay](./eval-delay.md) scores a delay prediction CSV and writes a leaderboard entry.
- [Eval criticality](./eval-criticality.md) scores a criticality prediction file against a ground-truth parquet and writes a leaderboard entry.
