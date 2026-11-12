#!/usr/bin/env bash
# Full-Jira (2,685,911 issues) TGN task-criticality pipeline -> bundles/criticality.
# Run from the repo root after `pip install -e ".[train]"`; needs data/jira.duckdb and the
# Ollama embeddings data/emb_{row_to_unique,unique}_all*.npy (erd embed).
set -euo pipefail
PY=${PY:-.venv/bin/python}
D=training/criticality
mkdir -p log/tgn_full
$PY $D/build_dataset.py | tee log/tgn_full/01_build_dataset.log
$PY $D/build_events.py --duckdb data/jira.duckdb --out_dir data/tgn_full | tee log/tgn_full/02_build_events.log
# memory sweep (deterministic): lr {1e-3,5e-4} x epochs {2,3} x seed {42..45}; selection = val P0 linear-probe AP
for lr in 1e-3 5e-4; do for ep in 2 3; do for sd in 42 43 44 45; do
  tag="_lr${lr}_e${ep}_s${sd}"
  $PY $D/train_tgn.py --data_dir data/tgn_full --epochs $ep --lr $lr --seed $sd --tag $tag > log/tgn_full/sweep$tag.log
  $PY $D/probe_memory.py --data_dir data/tgn_full --tag $tag | tail -1 >> log/tgn_full/sweep_results.jsonl
done; done; done
BEST=_lr5e-4_e2_s45   # argmax of is_critical_p0.val_ap in log/tgn_full/sweep_results.jsonl
$PY $D/train_readout.py --data_dir data/tgn_full --z_tag $BEST --trials 20 | tee log/tgn_full/04_train_readout.log
$PY $D/evaluate_all.py | tee log/tgn_full/05_evaluate_all.log
$PY $D/export_bundle.py --data_dir data/tgn_full --out bundles/criticality --overwrite | tee log/tgn_full/06_export_bundle.log
