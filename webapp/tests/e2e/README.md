# Early Risk Web + Local Jira Engine — E2E Test Suite (`webapp/tests/e2e/`)

Requirement-driven, opaque-box End-to-End (E2E) test suite verifying all 31 product features (`F01`–`F31`) across 4 coverage tiers (`>= 357` planned tests; 404 allocated in `TEST_INFRA.md`), isolated from unit tests (`webapp/backend/tests/` and `webapp/frontend/src/**/*.test.mjs`).

---

## Prerequisites & Offline Environment

- **Python virtualenv**: Repo-root `.venv/bin/python` (includes `pytest`, `httpx`, `fastapi`, `respx`, `uvicorn`, `duckdb`, and editable `erw` / `early_risk_detection`).
- **Node.js & Playwright (`webapp/tests/e2e/ui/`)**:
  - `@playwright/test@1.62.0` is installed strictly inside `webapp/tests/e2e/ui/` (`npm install --prefix webapp/tests/e2e/ui`), leaving `webapp/frontend/package.json` untouched.
  - Uses pre-cached local Chromium (`~/.cache/ms-playwright/chromium-1234`) via `resolveChromiumExecutable()` in `ui/playwright.config.mjs`.
- **Built Frontend (`webapp/frontend/dist`)**:
  - Required when running `--suite ui` without `--base-url` so the ephemeral FastAPI server can serve the SPA directly (`npm --prefix webapp/frontend run build` or `make build-frontend`).

---

## Quick Start Commands

Run from repo root (`/mnt/Data/0.Workspace/0.SourceCode/tgn`):

```bash
# 1. Dry-run validation (syntax + fixture imports + pytest --collect-only + node --check + playwright --list)
bash webapp/tests/e2e/run_e2e.sh --dry-run --suite all --tier all

# 2. Run API Tier 1 tests
bash webapp/tests/e2e/run_e2e.sh --suite api --tier 1

# 3. Run UI suite against an auto-spawned isolated ephemeral server
bash webapp/tests/e2e/run_e2e.sh --suite ui --tier 1

# 4. Run UI suite against an already-running instance
bash webapp/tests/e2e/run_e2e.sh --suite ui --base-url http://127.0.0.1:8000

# 5. Run tests for a specific feature or filter expression
bash webapp/tests/e2e/run_e2e.sh --feature F17
bash webapp/tests/e2e/run_e2e.sh --suite api -k "optimistic"

# 6. Run full 4-tier suite
bash webapp/tests/e2e/run_e2e.sh --tier all --suite all

# 7. List Playwright UI tests directly (always use --config or npm --prefix)
E2E_DRY_RUN=1 npm --prefix webapp/tests/e2e/ui run test:list

# 8. Invoke pytest directly from repo root (always pass webapp/tests/e2e target path)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -c webapp/tests/e2e/pytest.ini webapp/tests/e2e --collect-only -q
```

### Runner CLI Flags (`run_e2e.sh` / `run_e2e.py`)

| Flag | Values | Default | Behavior |
|---|---|---|---|
| `--tier` | `1`, `2`, `3`, `4`, `all` | `all` | Selects `@pytest.mark.tierN` for Pytest and `--grep @tierN` for Playwright |
| `--suite` | `api`, `ui`, `scenarios`, `all` | `all` | Targets `api/`, `ui/specs/`, `scenarios/` (+ `workflows_tier4.spec.mjs` when `--tier 4` or `all`), or all |
| `--feature` | `F01`..`F31` (comma-separated) | none | Filters Pytest via `ERW_E2E_FEATURES` (matching `@pytest.mark.feature("FXX")`) and Playwright via `@FXX` |
| `-k` | expression | none | Filters Pytest via `-k` and Playwright via `--grep` |
| `--mode` | `local`, `jira_cloud`, `all` | `all` | Exports `ERW_E2E_MODE` for dual-mode fixtures |
| `--base-url` | URL | auto-spawn | Points Playwright UI tests at an external server URL |
| `--dry-run` | flag | `False` | Read-only validation (zero workspace mutations or `__pycache__` writes) |
| `--headed` | flag | `False` | Launches Chromium in headed mode |
| `--junit-xml` | path | none | Emits Pytest JUnit XML report |
| `-v`, `--verbose` | flag | `False` | Verbose runner, Pytest, and Playwright output |

---

## Directory Layout & Milestone Ownership

| Path | Owner | Purpose |
|---|---|---|
| `README.md`, `run_e2e.py`, `run_e2e.sh`, `pytest.ini`, `conftest.py` | `E2E-M1` | Runner, Pytest config, global state isolation |
| `fixtures/{capabilities,db,auth,jira_mock,contracts,sample_files}.py` | `E2E-M1` | Guarded probes, temp SQLite/CLI isolation, role clients, `respx` Jira Cloud mock, v3/ETL contract assertions |
| `ui/{package.json,playwright.config.mjs,helpers/*,specs/smoke.spec.mjs}` | `E2E-M1` | Isolated Playwright Chromium harness, ephemeral server launcher, smoke tests |
| `api/test_e2e_{users_rbac,issues_lifecycle,dual_mode_client}.py` | `E2E-M2` | API Tier 1–2 tests for `F01`–`F18`, `F31` |
| `api/test_e2e_{activity_worklogs,agile_projects,seeder_erw_pipeline}.py` | `E2E-M3` | API/CLI/ML Tier 1–2 tests for `F19`–`F26`, `F29`–`F30` |
| `ui/specs/{nav_rbac,issue_create_detail,board_backlog_nav,admin_seeder_erw}.spec.mjs` | `E2E-M4` | Browser UI Tier 1–2 tests for `F03`–`F05`, `F08`–`F30` |
| `scenarios/test_e2e_{pairwise_tier3,workflows_tier4}.py`, `ui/specs/workflows_tier4.spec.mjs` | `E2E-M5` | Tier 3 cross-feature pairs (`P01`–`P36`) & Tier 4 workflows (`W01`–`W18`) |

---

## Markers & Tags

- **Pytest (`pytest.ini`, `--strict-markers` enabled)**:
  - Tiers: `@pytest.mark.tier1`, `@pytest.mark.tier2`, `@pytest.mark.tier3`, `@pytest.mark.tier4`
  - Feature mapping: `@pytest.mark.feature("F01")` .. `@pytest.mark.feature("F31")`
  - Surface/category tags: `api`, `cli`, `scenario`, `dual_mode`, `erw_ml`
- **Playwright (`ui/specs/*.spec.mjs`)**:
  - Every `test(...)` title carries tier and feature tags, e.g. `test('@tier1 @F13 ...', ...)` so `--grep` and coverage auditing work deterministically.

---

## Isolation & Cleanup Guarantees

1. **Zero `webapp/backend/var/` or `.env` Contamination**:
   - Backend E2E tests use per-test `tmp_path / "e2e.db"` SQLite files, `Settings(_env_file=None, ollama_url="", slack_webhook_url="")`, and isolated `tmp_path` directories for `attachments_dir`, `reports_dir`, `work_duckdb`, `stream_dir`, and `rag_index_path`.
   - CLI subprocesses execute with `cwd=tmp_path` and explicit env vars so Pydantic never loads `webapp/backend/.env`.
2. **Non-Interference with Port `8000`**:
   - When `--base-url` is omitted, `ui/helpers/server.mjs` binds an ephemeral free port on `127.0.0.1`, boots FastAPI from an isolated temp directory after `seed-demo --reset --rich-network`, and cleans up the process and temp dir on teardown.
3. **Multi-Role Cookie Isolation**:
   - `admin_client`, `pm_client`, `developer_client`, `viewer_client`, and `outsider_client` each instantiate an independent `TestClient` cookie jar sharing the same test app and SQLite database.
