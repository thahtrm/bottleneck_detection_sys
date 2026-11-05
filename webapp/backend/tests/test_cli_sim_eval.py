from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from erw import cli
from tests.test_sim_eval import _init_test_duckdb


@pytest.fixture
def sim_duckdb(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_sim.duckdb"
    _init_test_duckdb(db_path)
    return db_path


def test_cli_sim_eval_basic(sim_duckdb: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report_file = tmp_path / "custom_report.md"
    args = [
        "sim-eval",
        "--duckdb-path",
        str(sim_duckdb),
        "--instance",
        "INST",
        "--project",
        "PRJ",
        "--from",
        "2024-01-01",
        "--to",
        "2024-01-05",
        "--step-days",
        "2",
        "--output",
        str(report_file),
    ]

    ret = cli.main(args)
    assert ret == 0

    # Verify report file exists and has expected content
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "# Báo Cáo Đánh Giá Mô Phỏng Lịch Sử: Dự Án INST/PRJ" in content
    assert "| Cấu hình | Cảnh báo | TP | FP | FN | Precision | Recall | F1-Score | Lead Time TB (ngày) |" in content
    assert "Tổ Hợp Hybrid ERW" in content
    assert "Chỉ Hệ Luật Nghiệp Vụ" in content
    assert "Chỉ Mô Hình Học Máy T0" in content

    # Verify console output
    captured = capsys.readouterr()
    assert "EARLY RISK WEB — HISTORICAL SIMULATION EVALUATION ENGINE" in captured.out
    assert "Instance: INST | Project: PRJ" in captured.out
    assert "Time range: 2024-01-01 -> 2024-01-05 (step: 2 day(s))" in captured.out
    assert "Summary Results:" in captured.out
    assert "Rules Only" in captured.out
    assert "ML T0 Only" in captured.out
    assert "Hybrid ERW" in captured.out
    assert f"Report generated and saved to: {report_file}" in captured.out


def test_cli_sim_eval_default_output(sim_duckdb: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    args = [
        "sim-eval",
        "--duckdb-path",
        str(sim_duckdb),
        "--instance",
        "INST",
        "--project",
        "PRJ",
        "--from",
        "2024-01-01",
        "--to",
        "2024-01-02",
        "--step-days",
        "1",
    ]

    ret = cli.main(args)
    assert ret == 0

    expected_output = tmp_path / "reports" / "sim-inst-prj.md"
    assert expected_output.exists()
    content = expected_output.read_text(encoding="utf-8")
    assert "# Báo Cáo Đánh Giá Mô Phỏng Lịch Sử: Dự Án INST/PRJ" in content


def test_cli_sim_eval_invalid_dates(capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Invalid date string
    ret1 = cli.main(["sim-eval", "--from", "invalid-date", "--to", "2024-01-05"])
    assert ret1 == 1
    captured1 = capsys.readouterr()
    assert "Error: Invalid date format" in captured1.err

    # 2. from_date > to_date
    ret2 = cli.main(["sim-eval", "--from", "2024-01-10", "--to", "2024-01-05"])
    assert ret2 == 1
    captured2 = capsys.readouterr()
    assert "must be earlier than or equal to" in captured2.err


def test_cli_sim_eval_invalid_step_days(capsys: pytest.CaptureFixture[str]) -> None:
    ret0 = cli.main(["sim-eval", "--from", "2024-01-01", "--to", "2024-01-05", "--step-days", "0"])
    assert ret0 == 1
    cap0 = capsys.readouterr()
    assert "Error: --step-days must be a positive integer." in cap0.err

    ret_neg = cli.main(["sim-eval", "--from", "2024-01-01", "--to", "2024-01-05", "--step-days", "-3"])
    assert ret_neg == 1
    cap_neg = capsys.readouterr()
    assert "Error: --step-days must be a positive integer." in cap_neg.err


def test_cli_sim_eval_missing_duckdb(capsys: pytest.CaptureFixture[str]) -> None:
    ret = cli.main([
        "sim-eval",
        "--duckdb-path",
        "/nonexistent/path/db.duckdb",
        "--from",
        "2024-01-01",
        "--to",
        "2024-01-05",
    ])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Error: DuckDB database not found at" in captured.err


def test_cli_sim_eval_custom_thresholds(sim_duckdb: Path, tmp_path: Path) -> None:
    report_file = tmp_path / "thresholds_report.md"
    args = [
        "sim-eval",
        "--duckdb-path",
        str(sim_duckdb),
        "--instance",
        "INST",
        "--project",
        "PRJ",
        "--from",
        "2024-01-01",
        "--to",
        "2024-01-02",
        "--delay-threshold",
        "0.50",
        "--crit-top-pct",
        "0.10",
        "--output",
        str(report_file),
    ]

    ret = cli.main(args)
    assert ret == 0
    assert report_file.exists()


def test_cli_sim_eval_simulation_error_handling(
    sim_duckdb: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch("erw.sim.eval.run_simulation", side_effect=RuntimeError("Sim engine failed")):
        ret = cli.main([
            "sim-eval",
            "--duckdb-path",
            str(sim_duckdb),
            "--instance",
            "INST",
            "--project",
            "PRJ",
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-02",
            "--output",
            str(tmp_path / "dummy.md"),
        ])
        assert ret == 1
        captured = capsys.readouterr()
        assert "Error running simulation: Sim engine failed" in captured.err
