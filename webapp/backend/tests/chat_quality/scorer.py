"""Score chatbot answers against fixture expectations and board digest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from erw.pipeline.chat_lookup import keys_in_text
from erw.pipeline.digest import collect_digest
from erw.settings import Settings

from .adapter import EvalAnswer, get_answer

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "questions.json"
EMPTY_DATA_PHRASES = (
    "Chưa có trong hệ thống.",
    "Chưa có sprint đang chạy.",
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class CaseScore:
    case_id: str
    question: str
    ok: bool
    checks: list[CheckResult] = field(default_factory=list)
    answer_source: str = ""
    kind: str | None = None
    tool: str | None = None

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]


@dataclass
class EvalReport:
    cases: list[CaseScore]
    fixture_count: int
    passed: int
    failed: int
    source_mode: str

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_count": self.fixture_count,
            "passed": self.passed,
            "failed": self.failed,
            "ok": self.ok,
            "source_mode": self.source_mode,
            "failures": [
                {
                    "id": c.case_id,
                    "question": c.question,
                    "checks": [{"name": f.name, "detail": f.detail} for f in c.failures],
                }
                for c in self.cases
                if not c.ok
            ],
        }


def load_fixtures(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or FIXTURES_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("questions.json must be a list")
    return data


def _open_count(session: Session, project: str) -> int:
    from sqlalchemy import select

    from erw.models import Issue

    return len(
        list(
            session.scalars(
                select(Issue).where(
                    Issue.project_key == project,
                    Issue.deleted_at.is_(None),
                    Issue.status_category != "done",
                )
            ).all()
        )
    )


def _blocked_open(session: Session, project: str) -> int:
    from sqlalchemy import select

    from erw.models import Issue, RiskState

    rows = session.execute(
        select(Issue, RiskState)
        .join(RiskState, RiskState.issue_key == Issue.key)
        .where(
            Issue.project_key == project,
            Issue.deleted_at.is_(None),
            Issue.status_category != "done",
            RiskState.blocked.is_(True),
        )
    ).all()
    return len(rows)


def _digest_value(name: str, session: Session, project: str, now: datetime, settings: Settings) -> int:
    snap = collect_digest(session, project, now, settings)
    if name == "risky_count":
        return snap.risky_count
    if name == "raised_24h":
        return snap.raised_24h
    if name == "blocked_count":
        return snap.blocked_count
    if name == "open_count":
        return _open_count(session, project)
    if name == "blocked_open":
        return _blocked_open(session, project)
    raise KeyError(name)


def _check(name: str, ok: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail)


def score_case(
    case: dict[str, Any],
    answer: EvalAnswer,
    session: Session,
    project: str,
    now: datetime,
    settings: Settings,
) -> CaseScore:
    checks: list[CheckResult] = []
    facts = answer.facts or ""
    case_id = str(case["id"])

    expected_kind = case.get("expected_kind")
    if case.get("expect_out_of_scope"):
        checks.append(_check("out_of_scope", answer.out_of_scope or facts.strip() == "Chưa có trong hệ thống."))
    elif expected_kind is not None:
        checks.append(
            _check(
                "kind",
                answer.kind == expected_kind,
                f"got={answer.kind!r} want={expected_kind!r}",
            )
        )

    expected_tool = case.get("expected_tool")
    if expected_tool is not None and not case.get("expect_out_of_scope"):
        checks.append(
            _check(
                "tool",
                answer.tool == expected_tool,
                f"got={answer.tool!r} want={expected_tool!r}",
            )
        )

    if case.get("forbid_chua_co"):
        hit = next((p for p in EMPTY_DATA_PHRASES if p in facts), None)
        checks.append(_check("forbid_chua_co", hit is None, hit or ""))

    for needle in case.get("require_substrings") or []:
        checks.append(_check(f"require:{needle}", needle in facts, f"missing in facts"))

    for needle in case.get("forbid_substrings") or []:
        checks.append(_check(f"forbid:{needle}", needle not in facts, f"unexpected in facts"))

    for field_name in case.get("require_digest_fields") or []:
        want = _digest_value(field_name, session, project, now, settings)
        checks.append(
            _check(
                f"digest:{field_name}",
                str(want) in facts,
                f"want number {want} in facts",
            )
        )

    for payload_key, digest_name in (case.get("require_payload_fields") or {}).items():
        want = _digest_value(digest_name, session, project, now, settings)
        got = answer.payload.get(payload_key)
        if got is None:
            # Fall back to number appearing in facts (Python-rendered).
            ok = str(want) in facts
            checks.append(_check(f"payload:{payload_key}", ok, f"want {want}"))
        else:
            checks.append(_check(f"payload:{payload_key}", int(got) == int(want), f"got={got} want={want}"))

    mentioned = keys_in_text(facts)
    for key in case.get("must_include_keys") or []:
        checks.append(_check(f"must_key:{key}", key.upper() in mentioned, f"missing {key}"))

    for key in case.get("forbid_keys") or []:
        checks.append(_check(f"forbid_key:{key}", key.upper() not in mentioned, f"unexpected {key}"))

    if case.get("expect_keys_from_facts") or case.get("forbid_hallucinated_keys"):
        # Keys in the answer must be ⊆ allowed_keys (tool discipline).
        extra = mentioned - set(answer.allowed_keys)
        # OUT_OF_SCOPE / RAG with no tools: any issue key is a hallucination.
        if answer.out_of_scope or case.get("rag_ok"):
            extra = mentioned
        checks.append(
            _check(
                "allowed_keys",
                not extra,
                f"hallucinated={sorted(extra)}" if extra else "",
            )
        )

    if case.get("forbid_board_counts"):
        snap = collect_digest(session, project, now, settings)
        board_nums = {
            snap.risky_count,
            snap.raised_24h,
            snap.blocked_count,
            snap.new_24h,
            _open_count(session, project),
            _blocked_open(session, project),
        }
        # Ignore 0/1/2 — common in help prose; board regressions use larger live counts.
        board_nums = {n for n in board_nums if n >= 3}
        leaked = sorted(n for n in board_nums if re.search(rf"(?<!\d){n}(?!\d)", facts))
        checks.append(_check("rag_no_board_counts", not leaked, f"leaked counts={leaked}"))

    if case.get("skip_recommendation") is True:
        checks.append(_check("skip_recommendation", answer.skip_recommendation is True))

    ok = all(c.ok for c in checks)
    return CaseScore(
        case_id=case_id,
        question=str(case["question"]),
        ok=ok,
        checks=checks,
        answer_source=answer.source,
        kind=answer.kind,
        tool=answer.tool,
    )


def run_eval(
    session: Session,
    settings: Settings,
    *,
    project: str,
    now: datetime,
    fixtures: list[dict[str, Any]] | None = None,
) -> EvalReport:
    cases_data = fixtures if fixtures is not None else load_fixtures()
    scores: list[CaseScore] = []
    sources: set[str] = set()
    for case in cases_data:
        answer = get_answer(session, project, str(case["question"]), now, settings)
        sources.add(answer.source)
        scores.append(score_case(case, answer, session, project, now, settings))
    passed = sum(1 for s in scores if s.ok)
    failed = len(scores) - passed
    if sources == {"chat_agent"}:
        mode = "chat_agent"
    elif sources == {"chat_tools"}:
        mode = "chat_tools"
    elif sources <= {"chat_agent", "chat_tools"}:
        mode = "chat_agent+tools"
    elif "chat_agent" in sources or "chat_tools" in sources:
        mode = "mixed"
    elif sources <= {"chat_lookup", "out_of_scope"}:
        mode = "chat_lookup"
    else:
        mode = ",".join(sorted(sources))
    return EvalReport(
        cases=scores,
        fixture_count=len(scores),
        passed=passed,
        failed=failed,
        source_mode=mode,
    )
