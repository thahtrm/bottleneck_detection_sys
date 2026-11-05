from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from erw.sim.eval import DayEvalRecord, SimulationResult
from erw.sim.metrics import (
    ConfigMetrics,
    SimulationAnalysis,
    analyze_simulation,
    format_markdown_report,
    generate_sim_report,
)


def _make_sample_simulation_result() -> SimulationResult:
    """Create a realistic SimulationResult with TP, FP, FN, TN, and distinct case study records."""
    d1 = date(2024, 1, 1)
    records = [
        # Issue 1: Standard TP across all configs
        DayEvalRecord(
            as_of_date=d1,
            issue_key="KAFKA-1",
            summary="Consumer rebalance timeout in high partition cluster",
            pred_rules=True,
            pred_ml=True,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=12.0,
            rule_factors=["in_progress_stagnant"],
            p_delay=0.68,
            crit_score=0.12,
        ),
        # Issue 2: ML False Alarm eliminated by Hybrid
        DayEvalRecord(
            as_of_date=d1,
            issue_key="KAFKA-2",
            summary="Refactor docstring formatting",
            pred_rules=False,
            pred_ml=True,
            pred_hybrid=False,
            actual_delayed=False,
            lead_time_days=None,
            rule_factors=[],
            p_delay=0.42,
            crit_score=0.01,
        ),
        # Issue 3: ML FN rescued by Rules
        DayEvalRecord(
            as_of_date=d1,
            issue_key="KAFKA-3",
            summary="Kerberos ticket renewal race condition",
            pred_rules=True,
            pred_ml=False,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=18.0,
            rule_factors=["open_blocker"],
            p_delay=0.22,
            crit_score=0.02,
        ),
        # Issue 4: Clean TN across all configs
        DayEvalRecord(
            as_of_date=d1,
            issue_key="KAFKA-4",
            summary="Bump version to 3.7.0-SNAPSHOT",
            pred_rules=False,
            pred_ml=False,
            pred_hybrid=False,
            actual_delayed=False,
            lead_time_days=None,
            rule_factors=[],
            p_delay=0.10,
            crit_score=0.00,
        ),
        # Issue 5: High Lead Time TP detected by Hybrid
        DayEvalRecord(
            as_of_date=d1,
            issue_key="KAFKA-5",
            summary="Raft quorum metadata log compaction stall",
            pred_rules=True,
            pred_ml=True,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=25.0,
            rule_factors=["open_blocker", "exceeds_age_threshold"],
            p_delay=0.85,
            crit_score=0.20,
        ),
    ]

    return SimulationResult(
        instance="APACHE",
        project="KAFKA",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 10),
        records=records,
        total_evaluations=5,
        unique_issues_evaluated=5,
    )


def test_config_metrics_dataclass():
    cm = ConfigMetrics(
        name="hybrid",
        display_name="Tổ Hợp Hybrid ERW (Hệ Luật + Học Máy)",
        tp=3,
        fp=0,
        fn=0,
        tn=2,
        precision=1.0,
        recall=1.0,
        f1=1.0,
        accuracy=1.0,
        alert_count=3,
        avg_lead_time_days=18.33,
        median_lead_time_days=18.0,
        min_lead_time_days=12.0,
        max_lead_time_days=25.0,
    )

    d = cm.to_dict()
    assert d["name"] == "hybrid"
    assert d["tp"] == 3
    assert d["alert_count"] == 3
    assert d["avg_lead_time_days"] == 18.33
    assert d["median_lead_time_days"] == 18.0
    assert d["min_lead_time_days"] == 12.0
    assert d["max_lead_time_days"] == 25.0


def test_compute_config_metrics_and_analyze_simulation():
    res = _make_sample_simulation_result()
    analysis = analyze_simulation(res)

    # 1. Check Rules Config
    # Issues: KAFKA-1 (TP), KAFKA-2 (TN), KAFKA-3 (TP), KAFKA-4 (TN), KAFKA-5 (TP)
    # Rules: TP=3, FP=0, FN=0, TN=2
    r_rules = analysis.rules
    assert r_rules.name == "rules"
    assert r_rules.tp == 3
    assert r_rules.fp == 0
    assert r_rules.fn == 0
    assert r_rules.tn == 2
    assert r_rules.precision == 1.0
    assert r_rules.recall == 1.0
    assert r_rules.f1 == 1.0
    assert r_rules.accuracy == 1.0
    assert r_rules.alert_count == 3
    # Lead times for Rules: [12.0, 18.0, 25.0] -> avg = 55.0 / 3 = 18.33, median = 18.0, min = 12.0, max = 25.0
    assert r_rules.avg_lead_time_days == 18.33
    assert r_rules.median_lead_time_days == 18.0
    assert r_rules.min_lead_time_days == 12.0
    assert r_rules.max_lead_time_days == 25.0

    # 2. Check ML Config
    # KAFKA-1: TP (pred=True, act=True)
    # KAFKA-2: FP (pred=True, act=False)
    # KAFKA-3: FN (pred=False, act=True)
    # KAFKA-4: TN (pred=False, act=False)
    # KAFKA-5: TP (pred=True, act=True)
    # ML: TP=2, FP=1, FN=1, TN=1
    r_ml = analysis.ml
    assert r_ml.name == "ml"
    assert r_ml.tp == 2
    assert r_ml.fp == 1
    assert r_ml.fn == 1
    assert r_ml.tn == 1
    assert r_ml.precision == round(2 / 3, 4)
    assert r_ml.recall == round(2 / 3, 4)
    assert r_ml.f1 == round(2 / 3, 4)
    assert r_ml.accuracy == round(3 / 5, 4)
    assert r_ml.alert_count == 3
    # ML Lead times: [12.0, 25.0] -> avg = 18.5, median = 18.5, min = 12.0, max = 25.0
    assert r_ml.avg_lead_time_days == 18.5
    assert r_ml.median_lead_time_days == 18.5
    assert r_ml.min_lead_time_days == 12.0
    assert r_ml.max_lead_time_days == 25.0

    # 3. Check Hybrid Config
    # KAFKA-1: TP
    # KAFKA-2: TN (pred=False, act=False) -> FP eliminated!
    # KAFKA-3: TP (pred=True, act=True) -> FN rescued!
    # KAFKA-4: TN
    # KAFKA-5: TP
    # Hybrid: TP=3, FP=0, FN=0, TN=2
    r_hybrid = analysis.hybrid
    assert r_hybrid.name == "hybrid"
    assert r_hybrid.tp == 3
    assert r_hybrid.fp == 0
    assert r_hybrid.fn == 0
    assert r_hybrid.tn == 2
    assert r_hybrid.precision == 1.0
    assert r_hybrid.recall == 1.0
    assert r_hybrid.f1 == 1.0
    assert r_hybrid.accuracy == 1.0
    assert r_hybrid.alert_count == 3
    assert r_hybrid.avg_lead_time_days == 18.33

    # 4. Check Case Studies
    # Rescued by Rules: KAFKA-3
    assert len(analysis.rescued_by_rules) == 1
    assert analysis.rescued_by_rules[0].issue_key == "KAFKA-3"
    assert "open_blocker" in analysis.rescued_by_rules[0].rule_factors

    # Filtered by Hybrid: KAFKA-2
    assert len(analysis.filtered_by_hybrid) == 1
    assert analysis.filtered_by_hybrid[0].issue_key == "KAFKA-2"

    # Early Warnings: KAFKA-5 (25.0d), KAFKA-3 (18.0d), KAFKA-1 (12.0d)
    assert len(analysis.early_warnings) == 3
    assert analysis.early_warnings[0].issue_key == "KAFKA-5"
    assert analysis.early_warnings[0].lead_time_days == 25.0
    assert analysis.early_warnings[1].issue_key == "KAFKA-3"
    assert analysis.early_warnings[1].lead_time_days == 18.0
    assert analysis.early_warnings[2].issue_key == "KAFKA-1"
    assert analysis.early_warnings[2].lead_time_days == 12.0


def test_simulation_analysis_accessors_and_serialization():
    res = _make_sample_simulation_result()
    analysis = analyze_simulation(res)
    assert isinstance(analysis, SimulationAnalysis)

    # Dictionary indexing
    assert analysis["rules"].name == "rules"
    assert analysis["ml"].name == "ml"
    assert analysis["hybrid"].name == "hybrid"

    with pytest.raises(KeyError, match="not found"):
        _ = analysis["invalid_config"]

    # configs property
    cfg_map = analysis.configs
    assert set(cfg_map.keys()) == {"rules", "ml", "hybrid"}
    assert cfg_map["hybrid"] is analysis.hybrid

    # to_dict serialization
    d = analysis.to_dict()
    assert "rules" in d
    assert "ml" in d
    assert "hybrid" in d
    assert "rescued_by_rules" in d
    assert "filtered_by_hybrid" in d
    assert "early_warnings" in d
    assert d["total_evaluations"] == 5
    assert d["unique_issues"] == 5
    assert len(d["rescued_by_rules"]) == 1
    assert d["rescued_by_rules"][0]["issue_key"] == "KAFKA-3"


def test_empty_simulation_metrics():
    res = SimulationResult(
        instance="APACHE",
        project="EMPTY",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 2),
        records=[],
    )
    analysis = analyze_simulation(res)

    for cfg in (analysis.rules, analysis.ml, analysis.hybrid):
        assert cfg.tp == 0
        assert cfg.fp == 0
        assert cfg.fn == 0
        assert cfg.tn == 0
        assert cfg.precision == 0.0
        assert cfg.recall == 0.0
        assert cfg.f1 == 0.0
        assert cfg.accuracy == 0.0
        assert cfg.alert_count == 0
        assert cfg.avg_lead_time_days is None
        assert cfg.median_lead_time_days is None
        assert cfg.min_lead_time_days is None
        assert cfg.max_lead_time_days is None

    assert analysis.rescued_by_rules == []
    assert analysis.filtered_by_hybrid == []
    assert analysis.early_warnings == []
    assert analysis.total_evaluations == 0
    assert analysis.unique_issues == 0

    # Ensure format_markdown_report doesn't raise errors on empty results
    report = format_markdown_report(analysis, res)
    assert "# Báo Cáo Đánh Giá Mô Phỏng Lịch Sử: Dự Án APACHE/EMPTY" in report
    assert "_Không ghi nhận ca nào trong giai đoạn mô phỏng._" in report


def test_case_studies_deduplication_and_top_n():
    d1 = date(2024, 1, 1)
    d2 = date(2024, 1, 2)

    # Multi-day records for same issues
    records = [
        # Rescued issue evaluated on day 1 and day 2
        DayEvalRecord(
            as_of_date=d1,
            issue_key="PRJ-10",
            summary="Blocker task",
            pred_rules=True,
            pred_ml=False,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=10.0,
            rule_factors=["open_blocker"],
        ),
        DayEvalRecord(
            as_of_date=d2,
            issue_key="PRJ-10",
            summary="Blocker task",
            pred_rules=True,
            pred_ml=False,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=9.0,
            rule_factors=["open_blocker"],
        ),
        # Filtered issue evaluated on day 1 and day 2
        DayEvalRecord(
            as_of_date=d1,
            issue_key="PRJ-20",
            summary="Refactor",
            pred_rules=False,
            pred_ml=True,
            pred_hybrid=False,
            actual_delayed=False,
        ),
        DayEvalRecord(
            as_of_date=d2,
            issue_key="PRJ-20",
            summary="Refactor",
            pred_rules=False,
            pred_ml=True,
            pred_hybrid=False,
            actual_delayed=False,
        ),
        # Early warning issue evaluated on day 1 (lead 15) and day 2 (lead 14)
        DayEvalRecord(
            as_of_date=d1,
            issue_key="PRJ-30",
            summary="Critical issue A",
            pred_rules=True,
            pred_ml=True,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=15.0,
        ),
        DayEvalRecord(
            as_of_date=d2,
            issue_key="PRJ-30",
            summary="Critical issue A",
            pred_rules=True,
            pred_ml=True,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=14.0,
        ),
        # Another early warning issue
        DayEvalRecord(
            as_of_date=d1,
            issue_key="PRJ-31",
            summary="Critical issue B",
            pred_rules=True,
            pred_ml=True,
            pred_hybrid=True,
            actual_delayed=True,
            lead_time_days=8.0,
        ),
    ]

    res = SimulationResult(
        instance="INST",
        project="PRJ",
        from_date=d1,
        to_date=d2,
        records=records,
    )

    # analyze with top_early_warnings=1
    analysis = analyze_simulation(res, top_early_warnings=1)

    # Deduped to 1 distinct issue
    assert len(analysis.rescued_by_rules) == 1
    assert analysis.rescued_by_rules[0].issue_key == "PRJ-10"

    assert len(analysis.filtered_by_hybrid) == 1
    assert analysis.filtered_by_hybrid[0].issue_key == "PRJ-20"

    # Only top 1 early warning returned
    assert len(analysis.early_warnings) == 1
    assert analysis.early_warnings[0].issue_key == "PRJ-30"
    assert analysis.early_warnings[0].lead_time_days == 15.0

    # With top_early_warnings=0 (all), PRJ-30, PRJ-10, and PRJ-31 are returned in sorted lead time order
    analysis_all = analyze_simulation(res, top_early_warnings=0)
    assert len(analysis_all.early_warnings) == 3
    assert analysis_all.early_warnings[0].issue_key == "PRJ-30"
    assert analysis_all.early_warnings[0].lead_time_days == 15.0
    assert analysis_all.early_warnings[1].issue_key == "PRJ-10"
    assert analysis_all.early_warnings[1].lead_time_days == 10.0
    assert analysis_all.early_warnings[2].issue_key == "PRJ-31"
    assert analysis_all.early_warnings[2].lead_time_days == 8.0


def test_format_markdown_report_structure():
    res = _make_sample_simulation_result()
    analysis = analyze_simulation(res)
    report = format_markdown_report(analysis, res)

    # Title
    assert "# Báo Cáo Đánh Giá Mô Phỏng Lịch Sử: Dự Án APACHE/KAFKA" in report

    # 5 sections
    assert "## 1. Bối cảnh & Thiết lập Thực nghiệm" in report
    assert "## 2. Bảng So Sánh Hiệu Năng 3 Cấu Hình" in report
    assert "## 3. Ma Trận Nhầm Lẫn (Confusion Matrix)" in report
    assert "## 4. Phân Tích Các Ca Điển Hình (Case Studies)" in report
    assert "## 5. Kết Luận Khoa Học & Khuyến Nghị" in report

    # Section 1 context details
    assert "APACHE" in report
    assert "KAFKA" in report
    assert "2024-01-01" in report
    assert "2024-01-10" in report
    assert "p_delay >= 0.39" in report

    # Section 2 comparison table
    assert "| Cấu hình | Cảnh báo | TP | FP | FN | Precision | Recall | F1-Score | Lead Time TB (ngày) |" in report
    assert "Chỉ Hệ Luật Nghiệp Vụ" in report
    assert "Chỉ Mô Hình Học Máy T0 (p_delay >= 0.39, criticality >= 0.05)" in report
    assert "Tổ Hợp Hybrid ERW (Hệ Luật + Học Máy)" in report

    # Section 3 confusion matrix sub-sections
    assert "### 3.1. Chỉ Hệ Luật Nghiệp Vụ" in report
    assert "### 3.2. Chỉ Mô Hình Học Máy T0" in report
    assert "### 3.3. Tổ Hợp Hybrid ERW (Hệ Luật + Học Máy)" in report
    assert "TP = 3" in report
    assert "FP = 1" in report

    # Section 4 case studies sub-sections
    assert "### 4.1. Các Ca ML Bỏ Sót Được Hệ Luật Cứu Nguy (Rescued by Rules)" in report
    assert "KAFKA-3" in report
    assert "open_blocker" in report

    assert "### 4.2. Các Ca Cảnh Báo Giả Của ML Được Hybrid Triệt Tiêu (Filtered by Hybrid)" in report
    assert "KAFKA-2" in report

    assert "### 4.3. Các Ca Phát Hiện Sớm Với Lead Time Cao (Early Warnings)" in report
    assert "KAFKA-5" in report
    assert "25.0" in report

    # Section 5 scientific conclusions
    assert "### 5.1. Nhận Định Khoa Học" in report
    assert "### 5.2. Khuyến Nghị Vận Hành" in report
    assert "Tổ Hợp Hybrid ERW" in report


def test_generate_sim_report_file_export(tmp_path: Path):
    res = _make_sample_simulation_result()

    # 1. Export to file in non-existent nested directory
    out_file = tmp_path / "reports" / "sim-kafka.md"
    assert not out_file.parent.exists()

    report = generate_sim_report(res, output_path=out_file)

    assert out_file.exists()
    file_content = out_file.read_text(encoding="utf-8")
    assert file_content == report
    assert "# Báo Cáo Đánh Giá Mô Phỏng Lịch Sử: Dự Án APACHE/KAFKA" in file_content

    # 2. Call with output_path=None
    report_no_file = generate_sim_report(res, output_path=None)
    assert report_no_file == report
