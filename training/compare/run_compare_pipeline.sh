#!/usr/bin/env bash
# Multi-head vs classical comparison driver (feature worktree).
# Does not touch production :8000. Does not merge to main.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${ROOT}:${PYTHONPATH:-}"
PY="${COMPARE_PYTHON:-/home/jiooum/0.Workspace/0.SourceCode/tgn/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
LOG_DIR="$ROOT/experiments/compare/logs"
mkdir -p "$LOG_DIR" experiments/compare

echo "[1/5] Build as-of tabular features for primary snapshots..."
"$PY" -m training.compare.build_snapshot_asof_features \
  --data-dir data/tgn_full_v2 \
  --out-dir data/tgn_full_v2/classical_asof \
  --snapshots T0_pre T3_change T7_change T_active_change \
  2>&1 | tee "$LOG_DIR/build_asof.log"

echo "[2/5] Re-eval Dual-Head CSVs (no retrain)..."
"$PY" -m training.compare.reeval_dual_head_snapshots \
  2>&1 | tee "$LOG_DIR/reeval_dual.log"

echo "[3/5] Duration regressors @T0_pre (for MAE)..."
for m in xgb logreg rf; do
  "$PY" -m training.compare.train_delay_duration_regressors \
    --model "$m" --snapshot T0_pre \
    2>&1 | tee "$LOG_DIR/duration_${m}_T0_pre.log"
done

echo "[4/5] Delay classifiers on shared X_xgb (+ asof per snap)..."
SNAPS=(T0_pre T3_change T7_change T_active_change)
for snap in "${SNAPS[@]}"; do
  ASOF=""
  if [[ "$snap" != "T0_pre" ]]; then
    ASOF="--asof-parquet data/tgn_full_v2/classical_asof/X_asof_${snap}.parquet"
  fi
  # duration MAE from T0 regressors for all snaps (duration label is outcome, not snap-dependent)
  for m in xgb logreg rf; do
    "$PY" -m training.compare.train_delay_classical_shared \
      --model "$m" --snapshot "$snap" $ASOF \
      --duration-pred-dir "experiments/compare/duration_${m}_T0_pre" \
      2>&1 | tee "$LOG_DIR/delay_${m}_${snap}.log"
  done
done

echo "[5/5] Criticality classical regress-then-rank..."
for snap in "${SNAPS[@]}"; do
  ASOF=""
  if [[ "$snap" != "T0_pre" ]]; then
    ASOF="--asof-parquet data/tgn_full_v2/classical_asof/X_asof_${snap}.parquet"
  fi
  for m in xgb logreg rf; do
    "$PY" -m training.compare.train_criticality_classical \
      --model "$m" --snapshot "$snap" $ASOF \
      2>&1 | tee "$LOG_DIR/crit_${m}_${snap}.log"
  done
done

echo "Pipeline finished. Leaderboard: experiments/leaderboard_multihead_vs_classical.json"
