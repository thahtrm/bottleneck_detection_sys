from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from erw.domain.board import card_deadline
from erw.domain.types import Level
from erw.models import Issue, Link, RiskState
from erw.pipeline.digest import MAX_ITEMS, _sprint_line, collect_digest
from erw.settings import Settings

LookupKind = Literal["sprint", "blocked", "risky", "assignee", "due", "overdue", "important", "open", "issue"]

SPRINT_PHRASES = ("tiến độ sprint", "tiến độ", "sprint")
BLOCKED_PHRASES = ("bị block", "đang chặn", "blocker", "block", "chặn")
RISKY_PHRASES = ("nguy cơ trễ", "nên xử lý", "xử lý gì", "ưu tiên", "rủi ro")
ASSIGNEE_PHRASES = ("được giao nhiều", "giao nhiều việc", "nhiều việc chưa xong")
DUE_PHRASES = ("sắp đến hạn", "sắp tới hạn", "đến hạn")
OVERDUE_PHRASES = ("quá hạn", "trễ hạn")
IMPORTANT_PHRASES = ("đánh dấu quan trọng", "quan trọng")
SOON_DAYS = 7
OPEN_PHRASES = (
    "tồn đọng",
    "số lượng công việc",
    "số công việc",
    "bao nhiêu công việc",
    "bao nhiêu việc",
    "bao nhiêu issue",
    "việc chưa xong",
    "chưa hoàn thành",
    "công việc mở",
    "issue mở",
    "việc đang mở",
)

_KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]+-\d+)\b")


@dataclass(frozen=True)
class FactAnswer:
    kind: LookupKind
    facts: str
    allowed_keys: frozenset[str]
    payload: dict
    issue_key: str | None
    skip_recommendation: bool


def _level(name: str | None) -> Level:
    return Level[name] if name in Level.__members__ else Level.LOW


def keys_in_text(text: str) -> frozenset[str]:
    return frozenset(match.group(1).upper() for match in _KEY_RE.finditer(text))


def find_project_issue_key(text: str, project_key: str) -> str | None:
    prefix = project_key.upper()
    for match in _KEY_RE.finditer(text):
        key = match.group(1).upper()
        project, _, _ = key.partition("-")
        if project == prefix:
            return key
    return None


def classify_question(text: str, project_key: str) -> LookupKind | None:
    if find_project_issue_key(text, project_key):
        return "issue"
    folded = text.casefold()
    if any(phrase in folded for phrase in SPRINT_PHRASES):
        return "sprint"
    if any(phrase in folded for phrase in BLOCKED_PHRASES):
        return "blocked"
    if any(phrase in folded for phrase in RISKY_PHRASES):
        return "risky"
    if any(phrase in folded for phrase in ASSIGNEE_PHRASES):
        return "assignee"
    if any(phrase in folded for phrase in DUE_PHRASES):
        return "due"
    if any(phrase in folded for phrase in OVERDUE_PHRASES):
        return "overdue"
    if any(phrase in folded for phrase in IMPORTANT_PHRASES):
        return "important"
    if any(phrase in folded for phrase in OPEN_PHRASES):
        return "open"
    return None


def _links(session: Session, key: str) -> list[Link]:
    return list(session.scalars(select(Link).where(or_(Link.source_key == key, Link.target_key == key))).all())


def blocks_keys(session: Session, key: str) -> list[str]:
    """Issues `key` blocks, using the same link rules as evaluate._blockers."""
    found: set[str] = set()
    for link in _links(session, key):
        type_std = link.type_std or ""
        direction = link.direction or ""
        if type_std == "Block" and direction == "1" and link.source_key == key:
            found.add(link.target_key)
        elif type_std == "Block" and direction == "0" and link.target_key == key:
            found.add(link.source_key)
        elif type_std == "Depend" and direction == "1" and link.target_key == key:
            found.add(link.source_key)
        elif type_std == "Depend" and direction == "0" and link.source_key == key:
            found.add(link.target_key)
    return sorted(found)


def blocker_keys(session: Session, key: str) -> list[str]:
    found: set[str] = set()
    for link in _links(session, key):
        type_std = link.type_std or ""
        direction = link.direction or ""
        if type_std == "Block" and direction == "0" and link.source_key == key:
            found.add(link.target_key)
        elif type_std == "Block" and direction == "1" and link.target_key == key:
            found.add(link.source_key)
        elif type_std == "Depend" and direction == "1" and link.source_key == key:
            found.add(link.target_key)
        elif type_std == "Depend" and direction == "0" and link.target_key == key:
            found.add(link.source_key)
    return sorted(found)


def _assignee(issue: Issue) -> str:
    return issue.assignee_name or issue.assignee_id or "chưa giao"


def issue_fact_line(
    key: str,
    assignee: str,
    level_label: str | None,
    deadline: str | None,
    blocked: bool,
    blocking: list[str],
    blockers: list[str],
    *,
    include_assignee: bool = True,
) -> str:
    """Polished VI fact line (Option A). Omit assignee when the digest is already scoped."""
    parts: list[str] = [key]
    if blocked and blocking:
        parts.append("bị chặn")
        parts.append(f"đang chặn {', '.join(blocking)}")
    elif blocked and blockers:
        parts.append(f"bị chặn bởi {', '.join(blockers)}")
    elif blocked:
        parts.append("bị chặn")
    else:
        if level_label:
            parts.append(f"mức {level_label}")
        if deadline:
            parts.append(deadline)
    if include_assignee:
        parts.append(f"phụ trách {assignee}")
    return " · ".join(parts)


def _finish(kind: LookupKind, facts: str, payload: dict, issue_key: str | None, skip: bool) -> FactAnswer:
    return FactAnswer(kind, facts, keys_in_text(facts), payload, issue_key, skip)


def _local_today(now: datetime, settings: Settings) -> date:
    moment = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(settings.tz)).date()


def _deadline_day(issue: Issue, risk: RiskState | None, settings: Settings) -> date | None:
    deadline = card_deadline(
        deadline_type=risk.deadline_type if risk is not None else None,
        deadline_label=risk.deadline_label if risk is not None else None,
        deadline_at=risk.deadline_at if risk is not None else None,
        duedate=issue.duedate,
    )
    if deadline is None:
        return None
    at = deadline.at if deadline.at.tzinfo is not None else deadline.at.replace(tzinfo=UTC)
    return at.astimezone(ZoneInfo(settings.tz)).date()


def _when(days: int) -> str:
    if days < 0:
        return f"quá hạn {-days} ngày"
    if days == 0:
        return "hạn hôm nay"
    return f"còn {days} ngày"


def _dated_line(issue: Issue, days: int, *, include_assignee: bool = True) -> str:
    parts = [issue.key, _when(days)]
    if include_assignee:
        parts.append(f"phụ trách {_assignee(issue)}")
    return " · ".join(parts)


def _by_risk(issue: Issue, risk: RiskState | None) -> tuple:
    if risk is None:
        return (1, 0, True, 0.0, issue.key)
    return (0, -int(_level(risk.level)), risk.crit_score is None, -(risk.crit_score or 0.0), issue.key)


def _open_issues(session: Session, project: str) -> list[Issue]:
    return list(
        session.scalars(
            select(Issue).where(
                Issue.project_key == project,
                Issue.deleted_at.is_(None),
                Issue.status_category != "done",
            )
        ).all()
    )


def _risk_map(session: Session, keys: list[str]) -> dict[str, RiskState]:
    if not keys:
        return {}
    return {risk.issue_key: risk for risk in session.scalars(select(RiskState).where(RiskState.issue_key.in_(keys))).all()}


def _dated_rows(
    session: Session, project: str, today: date, settings: Settings
) -> list[tuple[int, Issue, RiskState | None]]:
    issues = _open_issues(session, project)
    risks = _risk_map(session, [issue.key for issue in issues])
    rows: list[tuple[int, Issue, RiskState | None]] = []
    for issue in issues:
        risk = risks.get(issue.key)
        day = _deadline_day(issue, risk, settings)
        if day is None:
            continue
        rows.append(((day - today).days, issue, risk))
    return rows


def _open_risk_rows(session: Session, project: str) -> list[tuple[Issue, RiskState]]:
    rows = session.execute(
        select(Issue, RiskState)
        .join(RiskState, RiskState.issue_key == Issue.key)
        .where(Issue.project_key == project, Issue.deleted_at.is_(None), Issue.status_category != "done")
    ).all()
    return [(issue, risk) for issue, risk in rows]


def _issue_struct(session: Session, issue: Issue, risk: RiskState | None) -> dict:
    """Structured row for narrate allowlists + template render (Option B payload-first)."""
    blocked = bool(risk.blocked) if risk is not None else False
    blocking = blocks_keys(session, issue.key) if risk is not None else []
    blockers = blocker_keys(session, issue.key) if risk is not None and risk.blocked else []
    return {
        "key": issue.key,
        "assignee": _assignee(issue),
        "level": _level(risk.level).label_vi if risk is not None and risk.level else None,
        "deadline": risk.deadline_label if risk is not None else None,
        "blocked": blocked,
        "blocking": blocking,
        "blockers": blockers,
    }


def _line_from_struct(row: dict, *, include_assignee: bool = True) -> str:
    if row.get("level") is None and not row.get("blocked"):
        parts = [str(row["key"]), "chưa có mức rủi ro"]
        if include_assignee:
            parts.append(f"phụ trách {row.get('assignee') or 'chưa giao'}")
        return " · ".join(parts)
    return issue_fact_line(
        str(row["key"]),
        str(row.get("assignee") or "chưa giao"),
        row.get("level"),
        row.get("deadline"),
        bool(row.get("blocked")),
        list(row.get("blocking") or []),
        list(row.get("blockers") or []),
        include_assignee=include_assignee,
    )


def _line_for(session: Session, issue: Issue, risk: RiskState, *, include_assignee: bool = True) -> str:
    return _line_from_struct(_issue_struct(session, issue, risk), include_assignee=include_assignee)


def _answer_sprint(session: Session, project: str, now: datetime) -> FactAnswer:
    line = _sprint_line(session, project, now)
    if line is None:
        facts = "Chưa có sprint đang chạy."
    else:
        facts = line if line.endswith(".") else f"{line}."
    return _finish("sprint", facts, {"kind": "sprint", "sprint_line": line}, None, False)


def _answer_blocked(session: Session, project: str) -> FactAnswer:
    rows = [pair for pair in _open_risk_rows(session, project) if pair[1].blocked]
    rows.sort(key=lambda pair: (-int(_level(pair[1].level)), pair[1].crit_score is None, -(pair[1].crit_score or 0.0), pair[0].key))
    lines = [f"Đang có {len(rows)} issue mở bị chặn."]
    listed = []
    for issue, risk in rows[:MAX_ITEMS]:
        row = _issue_struct(session, issue, risk)
        line = _line_from_struct(row)
        lines.append(line)
        listed.append({**row, "line": line})
    facts = "\n".join(lines)
    return _finish("blocked", facts, {"kind": "blocked", "count": len(rows), "issues": listed}, None, False)


def _answer_risky(session: Session, project: str, now: datetime, settings: Settings) -> FactAnswer:
    snap = collect_digest(session, project, now, settings)
    lines = [f"Đang có {snap.risky_count} issue nguy cơ trễ, {snap.raised_24h} tăng bậc trong 24 giờ."]
    listed = []
    keys = [item.key for item in snap.top_risky]
    issues = {issue.key: issue for issue in session.scalars(select(Issue).where(Issue.key.in_(keys))).all()} if keys else {}
    risks = {risk.issue_key: risk for risk in session.scalars(select(RiskState).where(RiskState.issue_key.in_(keys))).all()} if keys else {}
    for item in snap.top_risky:
        issue = issues.get(item.key)
        risk = risks.get(item.key)
        if issue is None or risk is None:
            continue
        row = _issue_struct(session, issue, risk)
        line = _line_from_struct(row)
        lines.append(line)
        listed.append({**row, "line": line})
    facts = "\n".join(lines)
    return _finish(
        "risky",
        facts,
        {"kind": "risky", "risky_count": snap.risky_count, "raised_24h": snap.raised_24h, "issues": listed},
        None,
        False,
    )


def _factor_labels(risk: RiskState | None) -> list[str]:
    labels: list[str] = []
    for factor in (risk.factors or []) if risk is not None else []:
        if isinstance(factor, dict):
            label = factor.get("label") or factor.get("id") or factor.get("name")
            if label:
                labels.append(str(label))
        elif isinstance(factor, str) and factor:
            labels.append(factor)
    return labels


def _answer_open(session: Session, project: str) -> FactAnswer:
    issues = list(
        session.scalars(
            select(Issue).where(
                Issue.project_key == project,
                Issue.deleted_at.is_(None),
                Issue.status_category != "done",
            )
        ).all()
    )
    keys = [issue.key for issue in issues]
    risks = (
        {risk.issue_key: risk for risk in session.scalars(select(RiskState).where(RiskState.issue_key.in_(keys))).all()}
        if keys
        else {}
    )

    def sort_key(issue: Issue) -> tuple:
        risk = risks.get(issue.key)
        if risk is None:
            return (1, 0, True, 0.0, issue.key)
        return (0, -int(_level(risk.level)), risk.crit_score is None, -(risk.crit_score or 0.0), issue.key)

    issues.sort(key=sort_key)
    lines = [f"Đang còn {len(issues)} công việc chưa xong."]
    listed = []
    for issue in issues[:MAX_ITEMS]:
        risk = risks.get(issue.key)
        row = _issue_struct(session, issue, risk)
        line = _line_from_struct(row)
        lines.append(line)
        listed.append({**row, "line": line})
    facts = "\n".join(lines)
    return _finish("open", facts, {"kind": "open", "open_count": len(issues), "issues": listed}, None, True)


def _answer_issue(session: Session, project: str, text: str) -> FactAnswer:
    key = find_project_issue_key(text, project)
    issue = session.get(Issue, key) if key else None
    if issue is None or issue.project_key != project or issue.deleted_at is not None:
        shown = key or project
        facts = f"Không thấy {shown} trong dự án {project}."
        return _finish("issue", facts, {"kind": "issue", "key": key, "found": False}, None, True)
    risk = session.get(RiskState, key)
    level = _level(risk.level).label_vi if risk is not None and risk.level else "chưa có"
    deadline = risk.deadline_label if risk is not None and risk.deadline_label else "chưa có"
    blocking = blocks_keys(session, key)
    blockers = blocker_keys(session, key)
    if risk is not None and risk.blocked and blocking:
        block_sentence = f"Bị chặn và đang chặn {', '.join(blocking)}."
    elif risk is not None and risk.blocked and blockers:
        block_sentence = f"Bị chặn bởi {', '.join(blockers)}."
    elif risk is not None and risk.blocked:
        block_sentence = "Bị chặn."
    elif blocking:
        block_sentence = f"Đang chặn {', '.join(blocking)}."
    else:
        block_sentence = "Không bị chặn."
    factors = ", ".join(_factor_labels(risk)) or "không có"
    facts = (
        f"{key}: {issue.summary or ''}. Mức {level}. Phụ trách {_assignee(issue)}. "
        f"Hạn {deadline}. {block_sentence} Yếu tố: {factors}."
    )
    payload = {
        "kind": "issue",
        "key": key,
        "summary": issue.summary or "",
        "level": level,
        "assignee": _assignee(issue),
        "deadline": deadline,
        "blocked": bool(risk.blocked) if risk is not None else False,
        "blockers": blockers,
        "blocking": blocking,
        "factors": _factor_labels(risk),
    }
    return _finish("issue", facts, payload, key, False)


def _answer_assignee(session: Session, project: str) -> FactAnswer:
    issues = _open_issues(session, project)
    risks = _risk_map(session, [issue.key for issue in issues])
    groups: dict[str, list[Issue]] = {}
    for issue in issues:
        name = (issue.assignee_name or issue.assignee_id or "").strip()
        if not name:
            continue
        groups.setdefault(name, []).append(issue)
    if not groups:
        facts = "Không có ai được giao việc chưa xong."
        return _finish("assignee", facts, {"kind": "assignee", "assignee": None, "count": 0, "issues": []}, None, True)
    winner = sorted(groups, key=lambda name: (-len(groups[name]), name.casefold()))[0]
    owned = sorted(groups[winner], key=lambda issue: _by_risk(issue, risks.get(issue.key)))
    lines = [f"{winner} đang được giao nhiều việc chưa xong nhất: {len(owned)} việc."]
    listed = []
    for issue in owned[:MAX_ITEMS]:
        risk = risks.get(issue.key)
        row = _issue_struct(session, issue, risk)
        row["assignee"] = winner if risk is None else row["assignee"]
        line = _line_from_struct(row, include_assignee=False)
        lines.append(line)
        listed.append({**row, "line": line})
    facts = "\n".join(lines)
    return _finish(
        "assignee",
        facts,
        {"kind": "assignee", "assignee": winner, "count": len(owned), "issues": listed},
        None,
        True,  # A4: list answer is complete — skip bolted-on recommend
    )


def _answer_due(session: Session, project: str, now: datetime, settings: Settings) -> FactAnswer:
    today = _local_today(now, settings)
    upcoming = [row for row in _dated_rows(session, project, today, settings) if row[0] >= 0]
    upcoming.sort(key=lambda row: (row[0], row[1].key))
    soon = [row for row in upcoming if row[0] <= SOON_DAYS]
    if not upcoming:
        facts = "Không có issue nào còn hạn phía trước."
        return _finish("due", facts, {"kind": "due", "count": 0, "issues": []}, None, True)
    if not soon:
        days, issue, _risk = upcoming[0]
        facts = f"Không có issue đến hạn trong {SOON_DAYS} ngày tới. Gần nhất là {issue.key}, còn {days} ngày."
        return _finish(
            "due",
            facts,
            {"kind": "due", "count": 0, "soon_days": SOON_DAYS, "issues": [{"key": issue.key, "days": days}]},
            None,
            False,
        )
    lines = [f"Có {len(soon)} issue đến hạn trong {SOON_DAYS} ngày tới."]
    listed = []
    for days, issue, _risk in soon[:MAX_ITEMS]:
        line = _dated_line(issue, days)
        lines.append(line)
        listed.append(
            {
                "key": issue.key,
                "days": days,
                "assignee": _assignee(issue),
                "line": line,
            }
        )
    facts = "\n".join(lines)
    return _finish(
        "due",
        facts,
        {"kind": "due", "count": len(soon), "soon_days": SOON_DAYS, "issues": listed},
        None,
        True,
    )


def _answer_overdue(session: Session, project: str, now: datetime, settings: Settings) -> FactAnswer:
    today = _local_today(now, settings)
    overdue = [row for row in _dated_rows(session, project, today, settings) if row[0] < 0]
    overdue.sort(key=lambda row: (row[0], row[1].key))
    if not overdue:
        facts = "Không có issue mở nào quá hạn."
        return _finish("overdue", facts, {"kind": "overdue", "count": 0, "issues": []}, None, True)
    lines = [f"Đang có {len(overdue)} issue mở quá hạn."]
    listed = []
    for days, issue, _risk in overdue[:MAX_ITEMS]:
        line = _dated_line(issue, days)
        lines.append(line)
        listed.append(
            {
                "key": issue.key,
                "days": days,
                "assignee": _assignee(issue),
                "line": line,
            }
        )
    facts = "\n".join(lines)
    return _finish("overdue", facts, {"kind": "overdue", "count": len(overdue), "issues": listed}, None, True)


def _answer_important(session: Session, project: str) -> FactAnswer:
    issues = _open_issues(session, project)
    risks = _risk_map(session, [issue.key for issue in issues])
    flagged = [issue for issue in issues if (risk := risks.get(issue.key)) is not None and risk.is_critical]
    flagged.sort(key=lambda issue: _by_risk(issue, risks.get(issue.key)))
    if not flagged:
        facts = "Không có issue mở nào được đánh dấu quan trọng."
        return _finish("important", facts, {"kind": "important", "count": 0, "issues": []}, None, True)
    lines = [f"Đang có {len(flagged)} issue mở được đánh dấu quan trọng."]
    listed = []
    for issue in flagged[:MAX_ITEMS]:
        row = _issue_struct(session, issue, risks[issue.key])
        line = _line_from_struct(row)
        lines.append(line)
        listed.append({**row, "line": line})
    facts = "\n".join(lines)
    return _finish("important", facts, {"kind": "important", "count": len(flagged), "issues": listed}, None, True)


def answer_facts(session: Session, project: str, text: str, now: datetime, settings: Settings) -> FactAnswer | None:
    kind = classify_question(text, project)
    if kind is None:
        return None
    if kind == "sprint":
        return _answer_sprint(session, project, now)
    if kind == "blocked":
        return _answer_blocked(session, project)
    if kind == "risky":
        return _answer_risky(session, project, now, settings)
    if kind == "assignee":
        return _answer_assignee(session, project)
    if kind == "due":
        return _answer_due(session, project, now, settings)
    if kind == "overdue":
        return _answer_overdue(session, project, now, settings)
    if kind == "important":
        return _answer_important(session, project)
    if kind == "open":
        return _answer_open(session, project)
    if kind == "issue":
        return _answer_issue(session, project, text)
    raise AssertionError(kind)
