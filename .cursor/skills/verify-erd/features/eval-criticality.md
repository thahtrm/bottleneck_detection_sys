# Eval criticality

Eval criticality joins a prediction file to a ground-truth parquet on `issue_key`, prints NDCG, Precision@Top-5%, and Spearman rho, and appends an entry to the leaderboard path the user names.

## Sub-features

- `eval-test` scores a test split.
- `eval-val` scores a validation split.

## How to get to it (user POV)

- Run `erd eval criticality` with `--track`, `--pred_file`, `--split`, `--ground_truth_file`, and `--leaderboard`.

## Driving it with erd

Preconditions:

- Doctor passed.
- The prediction file has columns `issue_key` and `pred_score`.
- The ground-truth parquet has `issue_key`, `ground_truth_criticality`, `is_critical_p0`, and `query_group`. The harness default `data/pilot_spring/criticality_test.parquet` is not in git. If the parquet is missing, stop and report that path.
- `--leaderboard` is a file inside `/tmp/verify-erd-$RUN_ID/`, not `experiments/leaderboard_criticality.json`.

- **Score the split.** Run `.venv/bin/erd eval criticality --track verify-erd --pred_file <predictions.csv> --split test --ground_truth_file <criticality_test.parquet> --leaderboard /tmp/verify-erd-$RUN_ID/leaderboard.json`. Exit code 0. Stdout includes `NDCG@10 (Grouped)` and `Precision@Top-5%`. The scratch leaderboard contains the track `verify-erd`.
- **Proof.** Copy stdout and the scratch leaderboard into `.cursor/skills/verify-erd/proof/eval-criticality/`.

## Gotchas

- Omitting `--leaderboard` appends to `experiments/leaderboard_criticality.json`.
- Stdout always prints `Zero Temporal Leakage: VERIFIED`. That line is a fixed label in the harness, not a measurement this command performed. Do not cite it as proof of the T0 snapshot property. That property is checked by `verify-t0-snapshot`.
- An inner join on `issue_key` drops rows that do not match. A zero-match file is an error, not a score of zero.
