#!/usr/bin/env bash
# Full-Jira delay-risk pipeline (T0 features) -> bundles/delay. Run from the repo root after
# `pip install -e ".[train]"`; needs data/jira.duckdb and the Ollama embeddings (erd embed).
# Pass PARAMS=1 to reuse the hyper-parameters of the original study instead of re-running Optuna.
set -euo pipefail
PY=${PY:-.venv/bin/python}
D=training/delay
L=log/delay_t0
mkdir -p $L
if [[ "${PARAMS:-0}" == 1 ]]; then
  AFT_P="--params-from experiments/survival_aft/aft_metrics.json"
  CBS_P="--params-from experiments/catboost_survival/catboost_metrics.json"
  CR_P="--params-from experiments/catboost_competing_risks/catboost_metrics.json"
fi
$PY $D/build_dataset.py                                                 | tee $L/01_build_dataset.log
$PY $D/train_xgboost.py                                                 | tee $L/02_xgboost.log
$PY $D/train_aft.py ${AFT_P:-}                                          | tee $L/03_aft.log
$PY $D/train_catboost_survival.py --competing-risks none ${CBS_P:-}     | tee $L/04_catboost.log
$PY $D/train_catboost_survival.py --competing-risks cause_specific ${CR_P:-} | tee $L/05_catboost_cr.log
$PY $D/train_non_work.py                                                | tee $L/06_non_work.log
$PY $D/fit_blend_gate.py                                                | tee $L/07_blend_gate.log
$PY $D/export_bundle.py --overwrite                                     | tee $L/08_export_bundle.log
