from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from erw.settings import Settings

from .capabilities import has_setting

E2E_ROOT = Path(__file__).resolve().parent.parent
WEBAPP_DIR = E2E_ROOT.parent.parent
REPO_ROOT = WEBAPP_DIR.parent
BACKEND_DIR = WEBAPP_DIR / "backend"
SRC_DIR = REPO_ROOT / "src"


def make_e2e_paths(tmp_path: Path) -> dict[str, Path]:
    """Create isolated per-test directories and file paths under tmp_path."""
    attachments_dir = tmp_path / "attachments"
    reports_dir = tmp_path / "reports"
    rag_seed_dir = tmp_path / "rag" / "seed"
    stream_dir = tmp_path / "stream"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    rag_seed_dir.mkdir(parents=True, exist_ok=True)
    stream_dir.mkdir(parents=True, exist_ok=True)

    return {
        "tmp_path": tmp_path,
        "db_path": tmp_path / "e2e.db",
        "attachments_dir": attachments_dir,
        "reports_dir": reports_dir,
        "rag_seed_dir": rag_seed_dir,
        "rag_index_path": tmp_path / "rag" / "faiss.index",
        "base_duckdb": tmp_path / "base_missing.duckdb",
        "work_duckdb": tmp_path / "work.duckdb",
        "stream_dir": stream_dir,
        "bundles_dir": REPO_ROOT / "bundles",
        "emb_dir": REPO_ROOT / "data",
    }


def make_e2e_settings(
    tmp_path: Path,
    *,
    jira_mode: str = "local",
    jira_base_url: str | None = None,
    jira_projects: list[str] | None = None,
    **overrides: Any,
) -> Settings:
    """Build an isolated Settings instance that never reads repo .env or mutates webapp/backend/var/."""
    paths = make_e2e_paths(tmp_path)
    if jira_base_url is None:
        jira_base_url = "https://example.atlassian.net" if jira_mode == "jira_cloud" else ""

    kwargs: dict[str, Any] = {
        "_env_file": None,
        "db_url": f"sqlite:///{paths['db_path']}",
        "jira_base_url": jira_base_url,
        "jira_email": "bot@example.com",
        "jira_api_token": "e2e-api-token",
        "jira_projects": ["DEMO"] if jira_projects is None else list(jira_projects),
        "jira_webhook_secret": "e2e-webhook-secret",
        "public_base_url": "https://example.ngrok.test",
        "ollama_url": "",
        "slack_webhook_url": "",
        "reports_dir": str(paths["reports_dir"]),
        "rag_seed_dir": str(paths["rag_seed_dir"]),
        "rag_index_path": str(paths["rag_index_path"]),
        "base_duckdb": str(paths["base_duckdb"]),
        "work_duckdb": str(paths["work_duckdb"]),
        "stream_dir": str(paths["stream_dir"]),
        "bundles_dir": str(paths["bundles_dir"]),
        "emb_dir": str(paths["emb_dir"]),
        "session_secret": "e2e-test-session-secret",
    }
    if has_setting("jira_mode"):
        kwargs["jira_mode"] = jira_mode
    if has_setting("attachments_dir"):
        kwargs["attachments_dir"] = str(paths["attachments_dir"])

    kwargs.update(overrides)
    return Settings(**kwargs)


def build_cli_env(
    tmp_path: Path,
    *,
    jira_mode: str = "local",
    env_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct an isolated environment dict for invoking `python -m erw.cli` with cwd=tmp_path."""
    paths = make_e2e_paths(tmp_path)
    env = os.environ.copy()
    py_paths = [str(E2E_ROOT), str(BACKEND_DIR), str(SRC_DIR)]
    existing_pp = env.get("PYTHONPATH", "")
    if existing_pp:
        py_paths.append(existing_pp)

    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(py_paths),
            "DB_URL": f"sqlite:///{paths['db_path']}",
            "JIRA_MODE": jira_mode,
            "JIRA_BASE_URL": "" if jira_mode == "local" else "https://example.atlassian.net",
            "JIRA_EMAIL": "bot@example.com",
            "JIRA_API_TOKEN": "e2e-api-token",
            "JIRA_PROJECTS": "DEMO",
            "OLLAMA_URL": "",
            "SLACK_WEBHOOK_URL": "",
            "ATTACHMENTS_DIR": str(paths["attachments_dir"]),
            "REPORTS_DIR": str(paths["reports_dir"]),
            "RAG_SEED_DIR": str(paths["rag_seed_dir"]),
            "RAG_INDEX_PATH": str(paths["rag_index_path"]),
            "BASE_DUCKDB": str(paths["base_duckdb"]),
            "WORK_DUCKDB": str(paths["work_duckdb"]),
            "STREAM_DIR": str(paths["stream_dir"]),
            "BUNDLES_DIR": str(paths["bundles_dir"]),
            "EMB_DIR": str(paths["emb_dir"]),
            "SESSION_SECRET": "e2e-test-session-secret",
        }
    )
    if env_overrides:
        env.update(env_overrides)
    return env


def run_erw_cli(
    args: list[str],
    *,
    tmp_path: Path,
    jira_mode: str = "local",
    env_overrides: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run `python -m erw.cli <args>` in an isolated temp directory without touching repo var/."""
    env = build_cli_env(tmp_path, jira_mode=jira_mode, env_overrides=env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "erw.cli", *args],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )
