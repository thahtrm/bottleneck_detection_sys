from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import duckdb

logger = logging.getLogger(__name__)

STANDARD_DONE_RESOLUTIONS = {
    "fixed",
    "done",
    "resolved",
    "implemented",
    "completed",
    "closed",
}

IN_PROGRESS_STATUSES = {
    "in progress",
    "in_progress",
    "in development",
    "coding",
    "active",
    "review",
    "in review",
    "testing",
    "qa",
    "qa in progress",
}

NEAR_DONE_STATUSES = {
    "resolved",
    "closed",
    "done",
    "ready for review",
    "in review",
    "testing",
    "qa",
    "qa in progress",
    "verification",
}

PRIORITY_NORM = {
    "blocker": 1.0,
    "critical": 0.8,
    "major": 0.6,
    "minor": 0.4,
    "trivial": 0.2,
}


@dataclass
class IssueSnapshot:
    """Historical snapshot of an issue as of a specific simulation date."""

    issue_key: str
    summary: str
    status: str
    priority_norm: float
    created_ts: float
    resolved_ts: float | None
    resolution: str | None
    assignee: str | None
    open_blockers: list[str] = field(default_factory=list)
    days_in_status: float = 0.0
    age_days: float = 0.0
    planned_duration_days: float = 14.0


@dataclass
class DayEvalRecord:
    as_of_date: date
    issue_key: str
    summary: str
    pred_rules: bool  # Cấu hình 1: Chỉ Luật
    pred_ml: bool  # Cấu hình 2: Chỉ ML T0 (p_delay >= 0.39 hoặc is_critical)
    pred_hybrid: bool  # Cấu hình 3: Tổ hợp Hybrid ERW (Rules + ML)
    actual_delayed: bool  # Ground truth: Issue thực tế bị trễ hạn / vượt kế hoạch
    lead_time_days: float | None = None  # Số ngày cảnh báo sớm trước khi hoàn thành
    rule_factors: list[str] = field(default_factory=list)
    p_delay: float | None = None
    crit_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "issue_key": self.issue_key,
            "summary": self.summary,
            "pred_rules": self.pred_rules,
            "pred_ml": self.pred_ml,
            "pred_hybrid": self.pred_hybrid,
            "actual_delayed": self.actual_delayed,
            "lead_time_days": self.lead_time_days,
            "rule_factors": list(self.rule_factors),
            "p_delay": self.p_delay,
            "crit_score": self.crit_score,
        }


@dataclass
class SimulationResult:
    instance: str
    project: str
    from_date: date
    to_date: date
    records: list[DayEvalRecord] = field(default_factory=list)
    total_evaluations: int = 0
    unique_issues_evaluated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance,
            "project": self.project,
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "total_evaluations": self.total_evaluations,
            "unique_issues_evaluated": self.unique_issues_evaluated,
            "records": [r.to_dict() for r in self.records],
        }

    def compute_metrics(self) -> dict[str, dict[str, float]]:
        """Compute performance metrics (Precision, Recall, F1, Accuracy, Lead Time) for all 3 configurations."""
        configs = ("rules", "ml", "hybrid")
        out: dict[str, dict[str, float]] = {}

        for cfg in configs:
            tp = fp = fn = tn = 0
            lead_times: list[float] = []

            for r in self.records:
                pred = getattr(r, f"pred_{cfg}")
                actual = r.actual_delayed

                if pred and actual:
                    tp += 1
                    if r.lead_time_days is not None:
                        lead_times.append(r.lead_time_days)
                elif pred and not actual:
                    fp += 1
                elif not pred and actual:
                    fn += 1
                else:
                    tn += 1

            total = tp + fp + fn + tn
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
            acc = (tp + tn) / total if total > 0 else 0.0
            avg_lead = float(sum(lead_times) / len(lead_times)) if lead_times else 0.0

            out[cfg] = {
                "tp": float(tp),
                "fp": float(fp),
                "fn": float(fn),
                "tn": float(tn),
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "accuracy": round(acc, 4),
                "avg_lead_time_days": round(avg_lead, 2),
            }
        return out


class SimScorers(Protocol):
    def score(
        self, duckdb_path: str | Path, issue_keys: list[str], as_of: float
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Trả về (delay_scores, crit_scores) cho danh sách issue_keys tại thời điểm as_of."""
        ...


class DefaultSimScorers:
    """Default scorer using Dual-Head TGN (bundles/tgn_dual_head) or fallback bundles/heuristics."""

    def __init__(
        self,
        bundles_dir: str | Path | None = None,
        emb_dir: str | Path | None = None,
        ollama_url: str | None = None,
        default_bundle: str = "tgn_dual_head",
    ):
        self.bundles_dir = Path(bundles_dir) if bundles_dir else Path("bundles")
        self.emb_dir = Path(emb_dir) if emb_dir else Path("data")
        self.ollama_url = ollama_url or "http://localhost:11434"
        self.default_bundle = default_bundle
        self._dual_scorer = None
        self._delay_scorer = None
        self._crit_scorer = None
        self._emb = None
        self._load_attempted = False

    def _load(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        try:
            from early_risk_detection import CriticalityScorer, DelayRiskScorer, DualHeadScorer
            from early_risk_detection.embeddings import EmbeddingIndex, OllamaEmbedder

            dual_path = self.bundles_dir / self.default_bundle
            if (dual_path / "manifest.json").exists():
                self._dual_scorer = DualHeadScorer.load(dual_path)
            else:
                delay_path = self.bundles_dir / "delay"
                crit_path = self.bundles_dir / "criticality"
                if delay_path.exists():
                    self._delay_scorer = DelayRiskScorer.load(delay_path)
                if crit_path.exists():
                    self._crit_scorer = CriticalityScorer.load(crit_path)
            self._emb = EmbeddingIndex(
                self.emb_dir, fallback=OllamaEmbedder(endpoint=f"{self.ollama_url}/api/embed")
            )
        except Exception as e:
            logger.info("DefaultSimScorers using heuristic fallback: %s", e)

    def score(
        self, duckdb_path: str | Path, issue_keys: list[str], as_of: float
    ) -> tuple[dict[str, float], dict[str, float]]:
        self._load()
        delay_scores: dict[str, float] = {}
        crit_scores: dict[str, float] = {}

        if self._dual_scorer is not None and self._emb is not None:
            try:
                df = self._dual_scorer.score(
                    duckdb_path, self._emb, issue_keys=issue_keys, as_of=as_of
                )
                for row in df.itertuples(index=False):
                    k = getattr(row, "issue_key", None) or getattr(row, "uid", "").split("|")[-1]
                    delay_scores[k] = float(getattr(row, "p_delay", 0.0))
                    crit_scores[k] = float(getattr(row, "score", 0.0))
            except Exception as e:
                logger.warning("DualHeadScorer failed, falling back: %s", e)
        else:
            if self._delay_scorer is not None and self._emb is not None:
                try:
                    df = self._delay_scorer.score(
                        duckdb_path, self._emb, issue_keys=issue_keys, as_of=as_of
                    )
                    for row in df.itertuples(index=False):
                        k = getattr(row, "issue_key", None) or getattr(row, "uid", "").split("|")[-1]
                        delay_scores[k] = float(getattr(row, "p_delay", 0.0))
                except Exception as e:
                    logger.warning("Delay scorer failed, falling back: %s", e)

            if self._crit_scorer is not None and self._emb is not None:
                try:
                    df = self._crit_scorer.score(
                        duckdb_path, self._emb, issue_keys=issue_keys, as_of=as_of
                    )
                    for row in df.itertuples(index=False):
                        k = getattr(row, "issue_key", None) or getattr(row, "uid", "").split("|")[-1]
                        crit_scores[k] = float(getattr(row, "score", 0.0))
                except Exception as e:
                    logger.warning("Criticality scorer failed, falling back: %s", e)

        # Ensure every requested key has a score
        for k in issue_keys:
            short_k = k.split("|")[-1]
            if short_k not in delay_scores:
                delay_scores[short_k] = 0.20
            if short_k not in crit_scores:
                crit_scores[short_k] = 0.01

        return delay_scores, crit_scores


def reconstruct_issue_snapshot(
    issue: dict[str, Any],
    changelogs: list[dict[str, Any]],
    links: list[dict[str, Any]],
    all_issues_meta: dict[str, dict[str, Any]],
    d_ts: float,
    planned_duration_days: float = 14.0,
) -> IssueSnapshot:
    """Reconstruct an issue's attributes, status, and blockers at historical timestamp d_ts."""
    issue_key = issue["issue_key"]
    summary = issue.get("summary") or ""
    created_ts = float(issue["created_ts"])
    resolved_ts = float(issue["resolved_ts"]) if issue.get("resolved_ts") is not None else None
    resolution = issue.get("resolution")
    age_days = max(0.0, (d_ts - created_ts) / 86400.0)

    # 1. Status & Dwell Time
    st_cls = [c for c in changelogs if c["field"].lower() == "status"]
    past_st = [c for c in st_cls if c["created_ts"] <= d_ts]
    if past_st:
        status = past_st[-1]["to_value"] or issue.get("status") or "Open"
        status_since_ts = past_st[-1]["created_ts"]
    else:
        if st_cls:
            status = st_cls[0]["from_value"] or issue.get("status") or "Open"
        else:
            status = issue.get("status") or "Open"
        status_since_ts = created_ts

    days_in_status = max(0.0, (d_ts - status_since_ts) / 86400.0)

    # 2. Priority
    pr_cls = [c for c in changelogs if c["field"].lower() == "priority"]
    past_pr = [c for c in pr_cls if c["created_ts"] <= d_ts]
    if past_pr:
        raw_prio = (past_pr[-1]["to_value"] or "").lower()
        priority_norm = PRIORITY_NORM.get(raw_prio, float(issue.get("priority_norm") or 0.5))
    else:
        if pr_cls:
            raw_prio = (pr_cls[0]["from_value"] or "").lower()
            priority_norm = PRIORITY_NORM.get(raw_prio, float(issue.get("priority_norm") or 0.5))
        else:
            priority_norm = float(issue.get("priority_norm") or 0.5)

    # 3. Assignee
    as_cls = [c for c in changelogs if c["field"].lower() == "assignee"]
    past_as = [c for c in as_cls if c["created_ts"] <= d_ts]
    if past_as:
        assignee = past_as[-1]["to_value"]
    else:
        if as_cls:
            assignee = as_cls[0]["from_value"]
        else:
            assignee = issue.get("assignee")

    # 4. Open Blockers
    open_blockers: list[str] = []
    for lk in links:
        if lk["approx_ts"] > d_ts:
            continue

        blocker_candidate: str | None = None
        s_key = lk["source_key"]
        t_key = lk["target_key"]
        std_type = lk.get("link_type_std")
        dir_val = lk.get("direction")
        is_block_dep = bool(lk.get("is_block_or_depend"))

        if s_key == issue_key:
            # issue is source
            # Inward (dir=0) Block => source is blocked by target
            # Outward (dir=1) Depend => source depends on target
            if (
                (std_type == "Block" and dir_val == 0)
                or (std_type == "Depend" and dir_val == 1)
                or (is_block_dep and dir_val == 0)
            ):
                blocker_candidate = t_key
        elif t_key == issue_key:
            # issue is target
            # Outward (dir=1) Block => source blocks target
            # Inward (dir=0) Depend => target depends on source
            if (
                (std_type == "Block" and dir_val == 1)
                or (std_type == "Depend" and dir_val == 0)
                or (is_block_dep and dir_val == 1)
            ):
                blocker_candidate = s_key

        if blocker_candidate:
            meta = all_issues_meta.get(blocker_candidate)
            is_open = True
            if meta is not None:
                b_res = meta.get("resolved_ts")
                if b_res is not None:
                    is_open = (b_res > d_ts)
                else:
                    b_status = (meta.get("status") or "").lower()
                    if b_status in ("resolved", "closed", "done"):
                        is_open = False
            if is_open and blocker_candidate not in open_blockers:
                open_blockers.append(blocker_candidate)

    return IssueSnapshot(
        issue_key=issue_key,
        summary=summary,
        status=status,
        priority_norm=priority_norm,
        created_ts=created_ts,
        resolved_ts=resolved_ts,
        resolution=resolution,
        assignee=assignee,
        open_blockers=open_blockers,
        days_in_status=days_in_status,
        age_days=age_days,
        planned_duration_days=planned_duration_days,
    )


def run_simulation(
    duckdb_path: str | Path,
    instance: str,
    project: str,
    from_date: date | datetime,
    to_date: date | datetime,
    *,
    step_days: int = 1,
    scorers: SimScorers | None = None,
    delay_threshold: float = 0.39,
    crit_top_pct: float = 0.05,
    planned_duration_days: float = 14.0,
) -> SimulationResult:
    """Run historical simulation on DuckDB across date range [from_date, to_date]."""
    start_date = from_date.date() if isinstance(from_date, datetime) else from_date
    end_date = to_date.date() if isinstance(to_date, datetime) else to_date
    if start_date > end_date:
        raise ValueError(f"from_date ({start_date}) must be <= to_date ({end_date})")

    if scorers is None:
        scorers = DefaultSimScorers()

    is_memory = str(duckdb_path) == ":memory:"
    con = duckdb.connect(str(duckdb_path), read_only=not is_memory)
    try:
        # Load all issues for this project
        issue_rows = con.execute(
            """
            SELECT instance, issue_key, project, summary, issuetype, issuetype_theme,
                   priority_raw, priority_norm, status, resolution, created_ts, updated_ts,
                   resolved_ts, assignee, reporter, num_changelogs, num_links, num_comments,
                   has_block_or_depend
            FROM issues
            WHERE instance = ? AND project = ?
            ORDER BY issue_key
            """,
            [instance, project],
        ).fetchall()
        cols = [desc[0] for desc in con.description]
        issues = [dict(zip(cols, r)) for r in issue_rows]

        # Load changelogs
        cl_rows = con.execute(
            """
            SELECT c.instance, c.issue_key, c.change_id, c.author, c.created_ts, c.field,
                   c.from_value, c.to_value
            FROM issue_changelogs c
            JOIN issues i ON c.instance = i.instance AND c.issue_key = i.issue_key
            WHERE i.instance = ? AND i.project = ?
            ORDER BY c.created_ts ASC
            """,
            [instance, project],
        ).fetchall()
        cl_cols = [desc[0] for desc in con.description]
        changelogs_by_key: dict[str, list[dict[str, Any]]] = {}
        for r in cl_rows:
            d = dict(zip(cl_cols, r))
            changelogs_by_key.setdefault(d["issue_key"], []).append(d)

        # Load all links for this instance
        lk_rows = con.execute(
            """
            SELECT instance, source_key, target_key, link_type_raw, link_type_std,
                   direction, is_block_or_depend, approx_ts
            FROM issue_links
            WHERE instance = ?
            """,
            [instance],
        ).fetchall()
        lk_cols = [desc[0] for desc in con.description]
        links = [dict(zip(lk_cols, r)) for r in lk_rows]
        links_by_key: dict[str, list[dict[str, Any]]] = {}
        for lk in links:
            links_by_key.setdefault(lk["source_key"], []).append(lk)
            links_by_key.setdefault(lk["target_key"], []).append(lk)

        # Lookup for all issues in the instance (for checking blocker resolution)
        all_inst_issues = con.execute(
            """
            SELECT issue_key, status, resolution, created_ts, resolved_ts
            FROM issues
            WHERE instance = ?
            """,
            [instance],
        ).fetchall()
        meta_cols = [desc[0] for desc in con.description]
        all_issues_meta = {r[0]: dict(zip(meta_cols, r)) for r in all_inst_issues}
    finally:
        con.close()

    records: list[DayEvalRecord] = []
    current_date = start_date

    while current_date <= end_date:
        # As-of timestamp at end of day (UTC)
        d_dt = datetime(current_date.year, current_date.month, current_date.day, 23, 59, 59, tzinfo=UTC)
        d_ts = d_dt.timestamp()

        # Identify open issues at as_of = d_ts
        open_issues = [
            iss for iss in issues
            if iss["created_ts"] <= d_ts and (iss["resolved_ts"] is None or iss["resolved_ts"] > d_ts)
        ]

        # Reconstruct historical state for open issues
        snapshots: list[IssueSnapshot] = []
        for iss in open_issues:
            k = iss["issue_key"]
            snap = reconstruct_issue_snapshot(
                iss,
                changelogs_by_key.get(k, []),
                links_by_key.get(k, []),
                all_issues_meta,
                d_ts,
                planned_duration_days=planned_duration_days,
            )
            snapshots.append(snap)

        open_keys = [s.issue_key for s in snapshots]
        if open_keys:
            raw_delay, raw_crit = scorers.score(duckdb_path, open_keys, d_ts)
            # Normalize key mapping
            delay_scores = {k.split("|")[-1]: float(v) for k, v in raw_delay.items()}
            crit_scores = {k.split("|")[-1]: float(v) for k, v in raw_crit.items()}
        else:
            delay_scores, crit_scores = {}, {}

        for snap in snapshots:
            # 1. Ground Truth (actual_delayed)
            if snap.resolved_ts is not None:
                actual_duration_days = (snap.resolved_ts - snap.created_ts) / 86400.0
                res = (snap.resolution or "").strip().lower()
                is_std_done = res in STANDARD_DONE_RESOLUTIONS
                actual_delayed = (actual_duration_days > planned_duration_days) or (not is_std_done)
            else:
                actual_delayed = True

            # 2. Config 1: Rules Only (pred_rules)
            rule_factors: list[str] = []
            if snap.open_blockers:
                rule_factors.append(f"blocked:{','.join(sorted(snap.open_blockers))}")

            is_in_prog = snap.status.lower() in IN_PROGRESS_STATUSES
            if is_in_prog and snap.days_in_status > 7.0:
                rule_factors.append(f"stagnant_in_progress:{round(snap.days_in_status, 1)}d")

            if snap.age_days > planned_duration_days:
                rule_factors.append(f"overdue:{round(snap.age_days - planned_duration_days, 1)}d")
            elif snap.age_days > 0.7 * planned_duration_days:
                rule_factors.append(f"age_over_70pct:{round(snap.age_days, 1)}d")

            pred_rules = len(rule_factors) > 0

            # 3. Config 2: ML Only (pred_ml)
            p_del = delay_scores.get(snap.issue_key)
            c_score = crit_scores.get(snap.issue_key)
            is_delay_risk = p_del is not None and p_del >= delay_threshold
            is_critical = c_score is not None and c_score >= crit_top_pct
            pred_ml = bool(is_delay_risk or is_critical)

            # 4. Config 3: Hybrid ERW (pred_hybrid)
            is_near_done = snap.status.lower() in NEAR_DONE_STATUSES
            has_risk_signals = (
                pred_rules
                or (snap.priority_norm is not None and snap.priority_norm >= 0.8)
                or (snap.age_days >= 0.5 * planned_duration_days)
                or (is_in_prog and snap.days_in_status > 3.0)
            )

            if is_near_done:
                pred_hybrid = False
            elif pred_rules:
                pred_hybrid = True
            elif pred_ml and has_risk_signals:
                pred_hybrid = True
            elif pred_ml and p_del is not None and p_del >= 0.70:
                pred_hybrid = True
            else:
                pred_hybrid = False

            # 5. Lead Time (lead_time_days)
            lead_time_days: float | None = None
            if actual_delayed and snap.resolved_ts is not None:
                lead_time_days = round(max(0.0, (snap.resolved_ts - d_ts) / 86400.0), 2)

            records.append(
                DayEvalRecord(
                    as_of_date=current_date,
                    issue_key=snap.issue_key,
                    summary=snap.summary,
                    pred_rules=pred_rules,
                    pred_ml=pred_ml,
                    pred_hybrid=pred_hybrid,
                    actual_delayed=actual_delayed,
                    lead_time_days=lead_time_days,
                    rule_factors=rule_factors,
                    p_delay=p_del,
                    crit_score=c_score,
                )
            )

        current_date += timedelta(days=step_days)

    unique_issues = len({r.issue_key for r in records})
    return SimulationResult(
        instance=instance,
        project=project,
        from_date=start_date,
        to_date=end_date,
        records=records,
        total_evaluations=len(records),
        unique_issues_evaluated=unique_issues,
    )
