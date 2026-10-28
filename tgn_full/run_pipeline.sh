#!/usr/bin/env bash
# Full-Jira (2,685,911 issues) TGN task-criticality pipeline. Run from the repo root.
set -euo pipefail
PY=${PY:-.venv/bin/python}
mkdir -p log/tgn_full
$PY tgn_full/build_dataset.py                                   | tee log/tgn_full/01_build_dataset.log
(cd tgn_full && ../$PY build_events.py --duckdb ../data/jira.duckdb --out_dir ../data/tgn_full) | tee log/tgn_full/02_build_events.log
# memory sweep (deterministic): lr {1e-3,5e-4} x epochs {2,3} x seed {42..45}; selection = val P0 linear-probe AP
for lr in 1e-3 5e-4; do for ep in 2 3; do for sd in 42 43 44 45; do
  tag="_lr${lr}_e${ep}_s${sd}"
  (cd tgn_full && ../$PY train_tgn.py --data_dir ../data/tgn_full --epochs $ep --lr $lr --seed $sd --tag $tag) > log/tgn_full/sweep$tag.log
  (cd tgn_full && ../$PY probe_memory.py --data_dir ../data/tgn_full --tag $tag) | tail -1 >> log/tgn_full/sweep_results.jsonl
done; done; done
BEST=_lr5e-4_e2_s45   # argmax of is_critical_p0.val_ap in log/tgn_full/sweep_results.jsonl
(cd tgn_full && ../$PY train_readout.py --data_dir ../data/tgn_full --z_tag $BEST --trials 20) | tee log/tgn_full/04_train_readout.log
(cd tgn_full && ../$PY leakage_demo.py)                         | tee log/tgn_full/04b_leakage_demo.log
(cd tgn_full && ../$PY evaluate_all.py)                         | tee log/tgn_full/05_evaluate_all.log
