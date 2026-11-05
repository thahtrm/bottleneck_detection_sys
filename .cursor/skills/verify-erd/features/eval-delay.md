# Eval delay

Eval delay reads a prediction CSV, prints ROC-AUC, PR-AUC, F1, precision, and recall, and appends an entry to the leaderboard path the user names.

## Sub-features

- `eval-test` scores a test CSV that has `y_true` and `y_prob`.
- `eval-with-val` uses a validation CSV to choose the decision threshold before scoring the test CSV.

## How to get to it (user POV)

- Run `erd eval delay` with `--predictions`, `--track`, and `--leaderboard`.
- Add `--val-predictions` when the threshold should be chosen on validation rows.

## Driving it with erd

Preconditions:

- Doctor passed.
- The prediction CSV exists and has columns `y_true` and `y_prob`. If the file is missing, stop and report that path. Do not invent rows and call them the user's predictions.
- `--leaderboard` is a file inside `/tmp/verify-erd-$RUN_ID/`, not `experiments/leaderboard.json`.

- **Score the CSV.** Run `.venv/bin/erd eval delay --predictions <test.csv> --val-predictions <val.csv> --track verify-erd --leaderboard /tmp/verify-erd-$RUN_ID/leaderboard.json`. Exit code 0. Stdout includes `roc_auc`. The scratch leaderboard JSON contains the track name `verify-erd`.
- **Proof.** Copy stdout and the scratch leaderboard into `.cursor/skills/verify-erd/proof/eval-delay/`.

## Gotchas

- Omitting `--leaderboard` writes `experiments/leaderboard.json` and mixes a verification run into the research board.
- The threshold is swept on the validation file when it is passed. A test-only run uses the harness default. Do not compare those two numbers as if they were the same setting.
