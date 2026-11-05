---
name: verify-erd
description: "Drive the early-risk-detection CLI (erd) the way a user does: bundle info, delay and criticality scoring, and the eval harnesses. Use to prove a change to the erd command, its bundles, or the score/eval output."
---

# Verify erd

`erd` is a short-lived CLI, not a server. The primary surface is the terminal. The Python scorers (`DelayRiskScorer`, `CriticalityScorer`) are a second surface; this skill drives the CLI that calls them. `erd etl` and `erd embed` need MongoDB and Ollama and are not in the feature map. Do not point them at `data/jira.duckdb` or `data/` during verification.

There is no long-running process. "Launch" means the repo venv can run `erd`. Each drive is its own process. Two `bundle info` runs may read the same bundle. Two `score` runs must not share `--out` or `--stream-dir`. Never run `erd etl --overwrite` against the user's DuckDB.

## Launch

From the repo root:

```bash
test -x .venv/bin/erd || pip install -e ".[dev]"
.venv/bin/erd --help
```

Ready means the process exits 0 and stdout contains the words `score` and `bundle`. There is no migration and no seed database. Scoring and eval need files named in the feature you drive; if those files are absent, that journey fails and the reason goes in that feature's Gotchas. Do not substitute a smaller command and call the journey verified.

Teardown is per run: delete the scratch directory you created (copies, flipped bundles, scratch CSVs, scratch leaderboards). Do not delete `.cursor/skills/verify-erd/proof/`.

## Doctor

Read-only. Run this before driving whenever something looks off. It does not score and does not write a bundle.

```bash
test -x .venv/bin/erd
.venv/bin/python -c "import early_risk_detection; print(early_risk_detection.__version__)"
.venv/bin/erd --help
```

Worth driving when all three exit 0, the version prints (the published tree is `0.1.0`), and help names `score` and `bundle`. If `.venv/bin/erd` is missing, stop and launch first. Do not drive a system `erd` that is not this checkout's venv.

## Drive

Run commands exactly as the feature file writes them. The binary is `.venv/bin/erd` from the repo root. Stable handles are subcommands and flags, not menu positions:

- `erd bundle info <path>` prints the manifest JSON. `--no-verify` skips the SHA-256 check; verification runs do not pass it.
- `erd score delay` and `erd score criticality` take `--bundle`, `--db`, and `--emb-dir` or `--ollama`.
- `erd eval delay` and `erd eval criticality` write a leaderboard. Always pass `--leaderboard` to a file inside the scratch directory. The defaults `experiments/leaderboard.json` and `experiments/leaderboard_criticality.json` are research artifacts.

Proof is the command, its stdout, its stderr, and its exit code, plus a second read of the same user-facing output or of the file the command wrote. A traceback that names `bundle file corrupted or modified` is the expected proof that a tampered copy was rejected. Mocks are not used. `bundle info` reads the real bundle directory.

## Evidence

Write proof under `.cursor/skills/verify-erd/proof/<feature-id>/`. Keep the command line, stdout, stderr, and exit code. For a file the command wrote, copy that file into the same directory. Cleanup must leave this directory in place.

Exercise the real command. Capture the action and the resulting state: for `bundle info`, the JSON (kind, model, metrics) and a second run that still prints the same kind after any scratch copy was deleted. For `score`, the CSV row count the command prints and the CSV itself. For `eval`, the metrics lines on stdout and the scratch leaderboard JSON.

## Cleanup

Delete only the scratch directory for this run, for example `/tmp/verify-erd-$RUN_ID`. Never `killall`, never `pkill erd`, and never delete `bundles/`, `data/`, or `experiments/`. Proof under `.cursor/skills/verify-erd/proof/` stays.

## Helpers

This skill has no helper script. Every command is inlined above and in the feature files.
