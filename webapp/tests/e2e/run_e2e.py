#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

E2E_ROOT = Path(__file__).resolve().parent
WEBAPP_DIR = E2E_ROOT.parent.parent
REPO_ROOT = WEBAPP_DIR.parent
BACKEND_DIR = WEBAPP_DIR / "backend"
SRC_DIR = REPO_ROOT / "src"
PYTEST_INI = E2E_ROOT / "pytest.ini"
UI_DIR = E2E_ROOT / "ui"
FRONTEND_DIST_INDEX = WEBAPP_DIR / "frontend" / "dist" / "index.html"


def _resolve_python() -> str:
    override = os.environ.get("E2E_PYTHON")
    if override and Path(override).exists():
        return override
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _resolve_npx() -> str:
    npx_path = shutil.which("npx")
    if not npx_path:
        raise RuntimeError("npx not found in PATH. Node.js (>=20) and npm/npx are required for UI E2E.")
    return npx_path


def _resolve_node() -> str:
    node_path = shutil.which("node")
    if not node_path:
        raise RuntimeError("node not found in PATH. Node.js (>=20) is required for UI E2E.")
    return node_path


def _base_python_env(mode: str, features: list[str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    py_paths = [str(E2E_ROOT), str(BACKEND_DIR), str(SRC_DIR)]
    if env.get("PYTHONPATH"):
        py_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(py_paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["OLLAMA_URL"] = ""
    env["SLACK_WEBHOOK_URL"] = ""
    if mode in ("local", "jira_cloud"):
        env["ERW_E2E_MODE"] = mode
    else:
        env.pop("ERW_E2E_MODE", None)
    if features:
        env["ERW_E2E_FEATURES"] = ",".join(features)
    else:
        env.pop("ERW_E2E_FEATURES", None)
    return env


def _build_pytest_marker_expr(tier: str) -> str | None:
    if tier != "all":
        return f"tier{tier}"
    return None


def _build_playwright_grep(tier: str, features: list[str], k_expr: str | None) -> str | None:
    parts: list[str] = []
    if tier != "all":
        parts.append(f"@tier{tier}")
    if features:
        parts.append(f"({'|'.join(f'@{f}' for f in features)})")
    if k_expr:
        parts.append(k_expr)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    # Lookahead regex so Playwright --grep matches all clauses in any order in test title
    return "".join(f"(?=.*{p})" for p in parts)


def _check_python_syntax(verbose: bool) -> int:
    py_files = sorted(
        p for p in E2E_ROOT.rglob("*.py")
        if "node_modules" not in p.parts and ".venv" not in p.parts and "__pycache__" not in p.parts
    )
    with tempfile.TemporaryDirectory(prefix="erw_e2e_pycompile_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        for idx, py_file in enumerate(py_files):
            cfile = tmp_path / f"mod_{idx}.pyc"
            py_compile.compile(str(py_file), cfile=str(cfile), doraise=True)
            if verbose:
                print(f"[dry-run] py_compile OK: {py_file.relative_to(E2E_ROOT)}")
    print(f"[dry-run] py_compile passed for {len(py_files)} Python files (zero workspace bytecode written).")
    return 0


def _check_fixture_imports(python_exe: str, env: dict[str, str]) -> int:
    code = (
        "import erw.main, erw.settings, fixtures, fixtures.capabilities, "
        "fixtures.db, fixtures.auth, fixtures.jira_mock, fixtures.contracts, fixtures.sample_files; "
        "print('fixture-imports-ok')"
    )
    res = subprocess.run(
        [python_exe, "-c", code],
        cwd=str(E2E_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print("[dry-run] Fixture import smoke check FAILED:", file=sys.stderr)
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return res.returncode
    print("[dry-run] Fixture import smoke check passed.")
    return 0


def _run_pytest(
    *,
    python_exe: str,
    env: dict[str, str],
    dirs: list[Path],
    tier: str,
    k_expr: str | None,
    junit_xml: str | None,
    dry_run: bool,
    verbose: bool,
) -> int:
    cmd = [python_exe, "-m", "pytest", "-c", str(PYTEST_INI)]
    cmd.extend(str(d) for d in dirs)
    marker_expr = _build_pytest_marker_expr(tier)
    if marker_expr:
        cmd.extend(["-m", marker_expr])
    if k_expr:
        cmd.extend(["-k", k_expr])
    if dry_run:
        cmd.extend(["--collect-only", "-q"])
    else:
        if junit_xml:
            cmd.extend([f"--junitxml={junit_xml}"])
        if verbose:
            cmd.append("-vv")

    if verbose:
        print(f"[runner] Exec: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(E2E_ROOT), env=env, capture_output=dry_run, text=dry_run)
    if dry_run:
        if res.returncode in (0, 5):
            if res.stdout.strip():
                print(res.stdout.strip())
            if res.returncode == 5:
                print("[dry-run] pytest --collect-only returned exit code 5 (0 tests collected yet in selected suite/tier).")
            return 0
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return res.returncode
    return res.returncode


def _check_ui_mjs(verbose: bool) -> int:
    node_exe = _resolve_node()
    mjs_files = sorted(
        p for p in UI_DIR.rglob("*.mjs")
        if "node_modules" not in p.parts
    )
    for mjs in mjs_files:
        res = subprocess.run([node_exe, "--check", str(mjs)], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[dry-run] node --check FAILED on {mjs}:", file=sys.stderr)
            print(res.stderr, file=sys.stderr)
            return res.returncode
        if verbose:
            print(f"[dry-run] node --check OK: {mjs.relative_to(E2E_ROOT)}")
    print(f"[dry-run] node --check passed for {len(mjs_files)} .mjs files.")
    return 0


def _run_playwright(
    *,
    specs: list[str] | None,
    tier: str,
    features: list[str],
    k_expr: str | None,
    base_url: str | None,
    headed: bool,
    dry_run: bool,
    verbose: bool,
) -> int:
    npx_exe = _resolve_npx()
    pw_bin = UI_DIR / "node_modules" / "@playwright" / "test"
    if not pw_bin.exists():
        print(
            f"Playwright dependencies not installed at {UI_DIR / 'node_modules'}. "
            f"Run: npm install --prefix {UI_DIR}",
            file=sys.stderr,
        )
        return 1

    env = os.environ.copy()
    if dry_run:
        env["E2E_DRY_RUN"] = "1"
    else:
        env.pop("E2E_DRY_RUN", None)

    if base_url:
        env["E2E_BASE_URL"] = base_url
    else:
        env.pop("E2E_BASE_URL", None)
        if not dry_run and not FRONTEND_DIST_INDEX.is_file():
            print(
                f"Built frontend missing at {FRONTEND_DIST_INDEX}. "
                "Build it with `npm --prefix webapp/frontend run build` or pass --base-url <url>.",
                file=sys.stderr,
            )
            return 1

    if headed:
        env["E2E_HEADED"] = "1"
    else:
        env.pop("E2E_HEADED", None)

    cmd = [
        npx_exe,
        "--prefix",
        str(UI_DIR),
        "playwright",
        "test",
        "--config",
        str(UI_DIR / "playwright.config.mjs"),
    ]
    if specs:
        cmd.extend(specs)
    if dry_run:
        cmd.append("--list")
    grep_expr = _build_playwright_grep(tier, features, k_expr)
    if grep_expr:
        cmd.extend(["--grep", grep_expr])
    if headed and not dry_run:
        cmd.append("--headed")

    if verbose:
        print(f"[runner] Exec: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(UI_DIR), env=env, capture_output=dry_run, text=dry_run)
    if dry_run:
        combined = (res.stdout or "") + (res.stderr or "")
        if res.returncode == 0:
            if res.stdout.strip():
                print(res.stdout.strip())
            return 0
        # Playwright --list exits 1 with "No tests found" when a --grep filter matches 0 tests
        if "No tests found" in combined:
            print("[dry-run] playwright test --list: 0 tests matched filter.")
            return 0
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return res.returncode
    return res.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified E2E test runner for Early Risk Web + Local Jira Engine."
    )
    parser.add_argument(
        "--tier",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Select test tier (1=Happy Path, 2=Boundary/Negative, 3=Pairwise, 4=Workflows, all=all tiers).",
    )
    parser.add_argument(
        "--suite",
        choices=["api", "ui", "scenarios", "all"],
        default="all",
        help="Select test suite surface.",
    )
    parser.add_argument(
        "--feature",
        default=None,
        help="Comma-separated feature IDs (e.g. F14 or F14,F17).",
    )
    parser.add_argument(
        "-k",
        dest="k_expr",
        default=None,
        help="Filter expression passed to pytest -k and playwright --grep.",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "jira_cloud", "all"],
        default="all",
        help="Filter/configure dual-mode target via ERW_E2E_MODE.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Target an already-running ERW server URL for UI tests instead of spawning an ephemeral server.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Syntax check, fixture import check, pytest --collect-only, and Playwright --list with zero mutations.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright Chromium in headed mode.",
    )
    parser.add_argument(
        "--junit-xml",
        default=None,
        help="Optional path for Pytest JUnit XML output.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose runner output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    python_exe = _resolve_python()
    features = [f.strip().upper() for f in args.feature.split(",") if f.strip()] if args.feature else []
    env = _base_python_env(args.mode, features)

    if args.dry_run:
        rc = _check_python_syntax(args.verbose)
        if rc != 0:
            return rc
        rc = _check_fixture_imports(python_exe, env)
        if rc != 0:
            return rc

    pytest_dirs: list[Path] = []
    if args.suite in ("api", "all"):
        pytest_dirs.append(E2E_ROOT / "api")
    if args.suite in ("scenarios", "all"):
        pytest_dirs.append(E2E_ROOT / "scenarios")

    if pytest_dirs:
        rc = _run_pytest(
            python_exe=python_exe,
            env=env,
            dirs=pytest_dirs,
            tier=args.tier,
            k_expr=args.k_expr,
            junit_xml=args.junit_xml,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        if rc != 0:
            return rc

    run_ui = args.suite in ("ui", "all")
    tier4_ui_spec = UI_DIR / "specs" / "workflows_tier4.spec.mjs"
    ui_specs: list[str] | None = None
    if args.suite == "scenarios" and args.tier in ("4", "all") and tier4_ui_spec.is_file():
        run_ui = True
        ui_specs = ["specs/workflows_tier4.spec.mjs"]

    if run_ui:
        if args.dry_run:
            rc = _check_ui_mjs(args.verbose)
            if rc != 0:
                return rc
        rc = _run_playwright(
            specs=ui_specs,
            tier=args.tier,
            features=features,
            k_expr=args.k_expr,
            base_url=args.base_url,
            headed=args.headed,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        if rc != 0:
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
