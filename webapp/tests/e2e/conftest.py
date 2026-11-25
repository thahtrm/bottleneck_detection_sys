from __future__ import annotations

import os
import sys
from pathlib import Path

E2E_ROOT = Path(__file__).resolve().parent
WEBAPP_DIR = E2E_ROOT.parent.parent
REPO_ROOT = WEBAPP_DIR.parent
BACKEND_DIR = WEBAPP_DIR / "backend"
SRC_DIR = REPO_ROOT / "src"

for _p in (str(E2E_ROOT), str(BACKEND_DIR), str(SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from fastapi.testclient import TestClient

from erw import jobs
from erw.db import SessionLocal, init_db, make_engine
from erw.integrations import llm
from erw.main import create_app
from erw.pipeline import evaluate
from erw.settings import get_settings

from fixtures.auth import (  # noqa: F401
    admin_client,
    developer_client,
    e2e_accounts,
    outsider_client,
    pm_client,
    viewer_client,
)
from fixtures.capabilities import has_local_jira_client, has_setting
from fixtures.db import make_e2e_paths, make_e2e_settings
from fixtures.jira_mock import dual_mode_env, fake_jira, mock_jira_cloud  # noqa: F401


def pytest_collection_modifyitems(config, items) -> None:
    """Filter collected items by ERW_E2E_FEATURES against @pytest.mark.feature(...) markers."""
    raw = os.environ.get("ERW_E2E_FEATURES", "").strip()
    if not raw:
        return
    selected = {part.strip().upper() for part in raw.split(",") if part.strip()}
    if not selected:
        return

    kept = []
    deselected = []
    for item in items:
        item_features: set[str] = set()
        for mark in item.iter_markers(name="feature"):
            for arg in mark.args:
                if arg is not None:
                    item_features.add(str(arg).strip().upper())
            if "id" in mark.kwargs and mark.kwargs["id"] is not None:
                item_features.add(str(mark.kwargs["id"]).strip().upper())
        if item_features & selected:
            kept.append(item)
        else:
            deselected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


def _clear_llm_in_progress() -> None:
    in_progress = getattr(llm, "_in_progress_keys", None)
    lock = getattr(llm, "_lock", None)
    if isinstance(in_progress, set):
        if lock is not None:
            with lock:
                in_progress.clear()
        else:
            in_progress.clear()


@pytest.fixture(autouse=True)
def _e2e_isolate_global_state():
    """Reset process-wide ERW caches and test-double hooks before and after every E2E test."""
    prev_dispatch = evaluate._dispatch
    prev_jobs_client = getattr(jobs, "_client", None)
    prev_jobs_settings = getattr(jobs, "_settings", None)
    prev_jobs_engine = getattr(jobs, "_engine", None)
    prev_llm_http = getattr(llm, "_http_client", None)
    prev_llm_engine = getattr(llm, "_engine", None)

    evaluate.clear_stats_cache()
    get_settings.cache_clear()
    _clear_llm_in_progress()
    try:
        yield
    finally:
        evaluate.clear_stats_cache()
        evaluate._dispatch = prev_dispatch
        jobs._client = prev_jobs_client
        jobs._settings = prev_jobs_settings
        jobs._engine = prev_jobs_engine
        llm._http_client = prev_llm_http
        llm._engine = prev_llm_engine
        _clear_llm_in_progress()
        get_settings.cache_clear()


@pytest.fixture
def e2e_paths(tmp_path: Path) -> dict[str, Path]:
    return make_e2e_paths(tmp_path)


@pytest.fixture
def jira_mode(request) -> str:
    marker = request.node.get_closest_marker("dual_mode")
    pinned = marker.kwargs.get("mode") if marker else None
    env_mode = os.environ.get("ERW_E2E_MODE", "").strip()
    if env_mode in ("local", "jira_cloud"):
        if pinned in ("local", "jira_cloud") and pinned != env_mode:
            pytest.skip(f"Test pinned to dual_mode(mode={pinned!r}) skipped under ERW_E2E_MODE={env_mode!r}")
        return env_mode
    if pinned in ("local", "jira_cloud"):
        return pinned
    if has_local_jira_client() and has_setting("jira_mode"):
        return "local"
    return "jira_cloud"


@pytest.fixture
def e2e_settings(tmp_path: Path, jira_mode: str):
    return make_e2e_settings(tmp_path, jira_mode=jira_mode)


@pytest.fixture
def e2e_engine(e2e_settings):
    eng = make_engine(e2e_settings.db_url)
    init_db(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def e2e_session(e2e_engine):
    with SessionLocal(bind=e2e_engine) as session:
        yield session


@pytest.fixture
def e2e_app(e2e_settings, e2e_engine):
    return create_app(
        e2e_settings,
        engine=e2e_engine,
        catch_up_on_startup=False,
        start_scheduler_on_startup=False,
    )


@pytest.fixture
def anon_client(e2e_app):
    with TestClient(e2e_app) as client:
        yield client
