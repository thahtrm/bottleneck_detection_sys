#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [[ -n "${E2E_PYTHON:-}" ]]; then
    PYTHON="$E2E_PYTHON"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" "$SCRIPT_DIR/run_e2e.py" "$@"
