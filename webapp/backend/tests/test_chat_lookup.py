from datetime import UTC, date, datetime, timedelta

from erw.models import Issue, IssueSprint, Link, RiskState, Sprint
from erw.pipeline.chat_lookup import answer_facts, classify_question
from erw.pipeline.digest import _sprint_line

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def test_issue_key_wins_over_other_words():
    assert classify_question("Tiến độ sprint của DEMO-41 hôm nay", "DEMO") == "issue"
    assert classify_question("xem demo-41", "DEMO") == "issue"


def test_priority_question_is_risky():
    assert classify_question("Sáng nay mình nên xử lý gì trước?", "DEMO") == "risky"


def test_unmatched_question_is_none():
    assert classify_question("Thời tiết hôm nay thế nào?", "DEMO") is None


def test_open_work_question_counts_remaining():
    assert classify_question("Số lượng công việc còn tồn đọng hiện tại", "DEMO") == "open"


def test_assignee_due_and_overdue_phrases():
    assert classify_question("Ai đang được giao nhiều việc chưa xong nhất?", "DEMO") == "assignee"
    assert classify_question("Có issue nào sắp đến hạn không?", "DEMO") == "due"
    assert classify_question("Có bao nhiêu việc đang quá hạn?", "DEMO") == "overdue"
    assert classify_question("Issue nào được đánh dấu quan trọng?", "DEMO") == "important"
    assert classify_question("DEMO-1 sắp đến hạn không", "DEMO") == "issue"
    assert classify_question("DEMO-2 quá hạn rồi", "DEMO") == "issue"


def test_other_project_key_does_not_force_issue():
    assert classify_question("OTHER-1 nên xử lý gì", "DEMO") == "risky"


def _issue(
    session,
    key,
    level="MED",
    blocked=False,
    assignee="An",
    summary="Việc",
    crit=0.1,
    raised=False,
    cat="indeterminate",
    duedate=None,
    deadline_at=None,
    critical=False,
):
    session.add(
        Issue(
            key=key,
            project_key="DEMO",
            summary=summary,
            status_category=cat,
            assignee_name=assignee,
            duedate=duedate,
            created_at=NOW - timedelta(days=3),
        )
    )
    session.add(
        RiskState(
            issue_key=key,
            level=level,
            blocked=blocked,
            crit_score=crit,
            is_critical=critical,
            deadline_label="hạn mai",
            deadline_at=deadline_at,
            level_raised_at=NOW - timedelta(hours=2) if raised else None,
            updated_at=NOW,
        )
    )


def test_risky_facts_count_everyone_and_list_five(session, settings):
    _issue(session, "DEMO-41", level="HIGH", blocked=True, assignee="Lan", crit=0.9, raised=True)
    _issue(session, "DEMO-18", level="LOW", assignee="Minh")
    session.add(Link(source_key="DEMO-41", target_key="DEMO-18", type_std="Block", direction="1"))
    for n, crit in enumerate((0.5, 0.4, 0.3, 0.2, 0.1), start=1):
        _issue(session, f"DEMO-{n}", crit=crit, raised=(n <= 1))
    session.flush()
    answer = answer_facts(session, "DEMO", "Sáng nay mình nên xử lý gì trước?", NOW, settings)
    assert answer is not None
    assert answer.kind == "risky"
    lines = answer.facts.splitlines()
    assert lines[0] == "Đang có 6 issue nguy cơ trễ, 2 tăng bậc trong 24 giờ."
    assert "DEMO-41 bị block và đang chặn DEMO-18, assignee Lan." in lines
    assert sum(1 for line in lines if line.startswith("DEMO-")) == 5
    assert answer.allowed_keys == frozenset(key for key in ("DEMO-41", "DEMO-18", "DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"))
    assert answer.skip_recommendation is False


def test_blocked_facts_count_open_blocked_only(session, settings):
    _issue(session, "DEMO-1", blocked=True, assignee="Lan")
    _issue(session, "DEMO-2", blocked=True, assignee="Minh")
    _issue(session, "DEMO-3", blocked=True, cat="done")
    session.flush()
    answer = answer_facts(session, "DEMO", "Issue nào đang bị block?", NOW, settings)
    assert answer.kind == "blocked"
    assert answer.facts.splitlines()[0] == "Đang có 2 issue mở bị block."


def test_sprint_facts_follow_sprint_line(session, settings):
    session.add(
        Sprint(
            id=1,
            name="Sprint 24",
            state="active",
            start_at=NOW - timedelta(days=5),
            end_at=NOW + timedelta(days=5),
        )
    )
    _issue(session, "DEMO-1")
    session.flush()
    session.add(IssueSprint(issue_key="DEMO-1", sprint_id=1))
    session.flush()
    answer = answer_facts(session, "DEMO", "Tiến độ sprint thế nào?", NOW, settings)
    assert answer.facts == f"{_sprint_line(session, 'DEMO', NOW)}."
    assert answer.kind == "sprint"
    assert answer.skip_recommendation is False

    empty = answer_facts(session, "OTHER", "sprint này sao?", NOW, settings)
    assert empty.facts == "Chưa có sprint đang chạy."


def test_known_issue_fact_includes_identity(session, settings):
    _issue(session, "DEMO-41", level="HIGH", assignee="Lan", summary="Làm API")
    session.flush()
    answer = answer_facts(session, "DEMO", "DEMO-41 sao rồi", NOW, settings)
    assert answer.kind == "issue"
    assert answer.issue_key == "DEMO-41"
    assert answer.skip_recommendation is False
    assert "DEMO-41" in answer.facts and "Lan" in answer.facts and "Cao" in answer.facts
    assert "DEMO-41" in answer.allowed_keys


def test_open_work_facts_count_not_done(session, settings):
    _issue(session, "DEMO-1", level="HIGH", assignee="Lan")
    _issue(session, "DEMO-2", assignee="Minh")
    _issue(session, "DEMO-3", cat="done")
    session.add(
        Issue(
            key="DEMO-4",
            project_key="DEMO",
            summary="Đã xóa",
            status_category="indeterminate",
            deleted_at=NOW,
            created_at=NOW,
        )
    )
    session.flush()
    answer = answer_facts(session, "DEMO", "Số lượng công việc còn tồn đọng hiện tại", NOW, settings)
    assert answer is not None
    assert answer.kind == "open"
    assert answer.facts.splitlines()[0] == "Đang còn 2 công việc chưa xong."
    assert "DEMO-3" not in answer.facts
    assert "DEMO-4" not in answer.facts
    assert answer.skip_recommendation is False


def test_assignee_load_names_the_busiest_open_assignee(session, settings):
    for n, crit in enumerate((0.9, 0.8, 0.7, 0.6, 0.5, 0.1), start=1):
        _issue(session, f"DEMO-{n}", assignee="Lan", crit=crit)
    _issue(session, "DEMO-7", assignee="Minh", crit=0.95)
    _issue(session, "DEMO-8", assignee=None)
    _issue(session, "DEMO-9", assignee=None)
    _issue(session, "DEMO-10", assignee="Lan", cat="done", crit=0.99)
    session.add(
        Issue(
            key="DEMO-11",
            project_key="DEMO",
            summary="Đã xóa",
            status_category="indeterminate",
            assignee_name="Lan",
            deleted_at=NOW,
            created_at=NOW,
        )
    )
    session.flush()
    answer = answer_facts(session, "DEMO", "Ai đang được giao nhiều việc chưa xong nhất?", NOW, settings)
    assert answer is not None
    assert answer.kind == "assignee"
    lines = answer.facts.splitlines()
    assert lines[0] == "Lan đang được giao nhiều việc chưa xong nhất: 6 việc."
    listed = [line for line in lines if line.startswith("DEMO-")]
    assert len(listed) == 5
    assert "DEMO-6" not in answer.facts
    assert "DEMO-7" not in answer.facts
    assert "DEMO-8" not in answer.facts
    assert "DEMO-10" not in answer.facts
    assert "DEMO-11" not in answer.facts
    assert answer.allowed_keys == frozenset(f"DEMO-{n}" for n in range(1, 6))
    assert answer.skip_recommendation is False

    empty = answer_facts(session, "OTHER", "Ai đang được giao nhiều việc chưa xong nhất?", NOW, settings)
    assert empty.facts == "Không có ai được giao việc chưa xong."
    assert empty.skip_recommendation is True
    assert empty.allowed_keys == frozenset()


def test_due_soon_uses_deadline_or_duedate(session, settings):
    _issue(session, "DEMO-1", duedate=date(2026, 11, 20), deadline_at=NOW + timedelta(days=1))
    _issue(session, "DEMO-2", assignee=None, duedate=date(2026, 11, 5))
    _issue(session, "DEMO-3", duedate=date(2026, 11, 2))
    _issue(session, "DEMO-4", duedate=date(2026, 11, 24))
    _issue(session, "DEMO-5", duedate=date(2026, 11, 3), cat="done")
    session.flush()
    answer = answer_facts(session, "DEMO", "Có issue nào sắp đến hạn không?", NOW, settings)
    assert answer.kind == "due"
    lines = answer.facts.splitlines()
    assert lines[0] == "Có 2 issue đến hạn trong 7 ngày tới."
    assert "DEMO-1 còn 1 ngày, assignee An." in lines
    assert "DEMO-2 còn 1 ngày, assignee chưa giao." in lines
    assert "DEMO-3" not in answer.facts
    assert "DEMO-4" not in answer.facts
    assert "còn 16 ngày" not in answer.facts
    assert answer.skip_recommendation is False

    far = answer_facts(session, "FAR", "Có issue nào sắp đến hạn không?", NOW, settings)
    assert far.facts == "Không có issue nào còn hạn phía trước."
    assert far.skip_recommendation is True


def test_due_soon_names_the_next_date_when_nothing_is_within_a_week(session, settings):
    _issue(session, "DEMO-8", duedate=date(2026, 11, 24))
    _issue(session, "DEMO-9", duedate=date(2026, 11, 2))
    session.flush()
    answer = answer_facts(session, "DEMO", "Có issue nào sắp đến hạn không?", NOW, settings)
    assert answer.facts == "Không có issue đến hạn trong 7 ngày tới. Gần nhất là DEMO-8, còn 20 ngày."
    assert answer.skip_recommendation is False
    assert "DEMO-8" in answer.allowed_keys


def test_overdue_count_ignores_future_done_and_deleted(session, settings):
    _issue(session, "DEMO-1", duedate=date(2026, 11, 2))
    _issue(session, "DEMO-2", duedate=date(2026, 11, 1))
    _issue(session, "DEMO-3", duedate=date(2026, 11, 10))
    _issue(session, "DEMO-4", duedate=date(2026, 11, 1), cat="done")
    session.flush()
    answer = answer_facts(session, "DEMO", "Có bao nhiêu việc đang quá hạn?", NOW, settings)
    assert answer.kind == "overdue"
    lines = answer.facts.splitlines()
    assert lines[0] == "Đang có 2 issue mở quá hạn."
    assert "DEMO-2 quá hạn 3 ngày, assignee An." in lines
    assert "DEMO-1 quá hạn 2 ngày, assignee An." in lines
    assert "DEMO-3" not in answer.facts
    assert "DEMO-4" not in answer.facts
    assert answer.skip_recommendation is False

    none = answer_facts(session, "OTHER", "Có bao nhiêu việc đang quá hạn?", NOW, settings)
    assert none.facts == "Không có issue mở nào quá hạn."
    assert none.skip_recommendation is True


def test_important_lists_open_critical_issues(session, settings):
    _issue(session, "DEMO-1", critical=True, level="HIGH")
    _issue(session, "DEMO-2", critical=False)
    _issue(session, "DEMO-3", critical=True, cat="done")
    session.flush()
    answer = answer_facts(session, "DEMO", "Issue nào được đánh dấu quan trọng?", NOW, settings)
    assert answer.kind == "important"
    assert answer.facts.splitlines()[0] == "Đang có 1 issue mở được đánh dấu quan trọng."
    assert "DEMO-1" in answer.facts
    assert "DEMO-2" not in answer.facts
    assert "DEMO-3" not in answer.facts
    assert answer.skip_recommendation is False

    none = answer_facts(session, "OTHER", "Issue nào được đánh dấu quan trọng?", NOW, settings)
    assert none.facts == "Không có issue mở nào được đánh dấu quan trọng."
    assert none.skip_recommendation is True


def test_missing_issue_skips_recommendation(session, settings):
    answer = answer_facts(session, "DEMO", "Xem DEMO-99", NOW, settings)
    assert answer.facts == "Không thấy DEMO-99 trong dự án DEMO."
    assert answer.skip_recommendation is True
    assert answer.issue_key is None
    assert answer_facts(session, "DEMO", "Thời tiết hôm nay thế nào?", NOW, settings) is None
