#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${ROOT}:${PYTHONPATH:-}"
PY="${COMPARE_PYTHON:-/home/jiooum/0.Workspace/0.SourceCode/tgn/.venv/bin/python}"
LOG_DIR="$ROOT/experiments/compare/logs"
mkdir -p "$LOG_DIR" experiments/compare
echo "START $(date) pid=$$" | tee "$LOG_DIR/pipeline_start.txt"
echo $$ > "$LOG_DIR/pipeline.pid"

echo "[1] Dual-Head reeval..."
"$PY" -m training.compare.reeval_dual_head_snapshots 2>&1 | tee "$LOG_DIR/reeval_dual.log"

echo "[2] Build as-of features..."
"$PY" -m training.compare.build_snapshot_asof_features \
  --snapshots T0_pre T3_change T7_change T_active_change \
  2>&1 | tee "$LOG_DIR/build_asof.log"

echo "[3] Duration regressors @T0_pre..."
for m in xgb logreg rf; do
  "$PY" -m training.compare.train_delay_duration_regressors --model "$m" --snapshot T0_pre \
    2>&1 | tee "$LOG_DIR/duration_${m}_T0_pre.log"
done

SNAPS=(T0_pre T3_change T7_change T_active_change)
echo "[4] Delay classical classifiers..."
for snap in "${SNAPS[@]}"; do
  ASOF_ARGS=()
  if [[ "$snap" != "T0_pre" ]]; then
    ASOF_ARGS=(--asof-parquet "data/tgn_full_v2/classical_asof/X_asof_${snap}.parquet")
  fi
  for m in xgb logreg rf; do
    "$PY" -m training.compare.train_delay_classical_shared \
      --model "$m" --snapshot "$snap" "${ASOF_ARGS[@]}" \
      --duration-pred-dir "experiments/compare/duration_${m}_T0_pre" \
      2>&1 | tee "$LOG_DIR/delay_${m}_${snap}.log"
  done
done

echo "[5] Criticality classical..."
for snap in "${SNAPS[@]}"; do
  ASOF_ARGS=()
  if [[ "$snap" != "T0_pre" ]]; then
    ASOF_ARGS=(--asof-parquet "data/tgn_full_v2/classical_asof/X_asof_${snap}.parquet")
  fi
  for m in xgb logreg rf; do
    "$PY" -m training.compare.train_criticality_classical \
      --model "$m" --snapshot "$snap" "${ASOF_ARGS[@]}" \
      2>&1 | tee "$LOG_DIR/crit_${m}_${snap}.log"
  done
done

echo "ALL_DONE $(date)" | tee "$LOG_DIR/pipeline_done.txt"
