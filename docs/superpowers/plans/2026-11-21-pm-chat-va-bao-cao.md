# PM Chat, Reports, and Urgent Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-scoped PM chat on the Early Risk board and list views that answers four rule-based lookups, sends weekday reports at the PM's own clock times, and shows urgent alerts, without a second Jira write path.

**Architecture:** Python classifies the question and renders the fact paragraph from the same rows the digest uses. Ollama writes only the recommendation, on the existing `erw-llm` executor, and updates that same chat row. Reports and urgent messages share `chat_messages`. Slack `notify` stays as it is; `dispatch` inserts an urgent row after each Slack attempt.

**Tech Stack:** FastAPI, SQLAlchemy 2 `create_all`, APScheduler, the existing Ollama JSON client, React 18, Mantine 7, TanStack Query 5.

**Spec:** `docs/superpowers/specs/2026-11-21-pm-chat-va-bao-cao-design.md`

## Global Constraints

- Facts are rendered by Python. Ollama writes only the recommendation. Out-of-scope questions do not call Ollama.
- Recommendation schema is `{text, actions[]}` with `ActionItem` (`action_type`, `target`, `value`, `reason`). Accept only when every `action_type` is in `ALLOWED_ACTION_TYPES`, every issue key mentioned is in the fact paragraph, and there are at most 3 actions.
- Failure copy, exact: `Chưa tạo được đề xuất bám dữ liệu.`
- Out-of-scope copy, exact: `Chưa có trong hệ thống.`
- Pending UI copy, exact: `Đang viết đề xuất…`
- Lookup order: a selected-project issue key wins; otherwise first match of sprint, then blocked, then risky.
- Sprint phrases, casefold substring: `tiến độ sprint`, `tiến độ`, `sprint`.
- Blocked phrases: `bị block`, `đang chặn`, `blocker`, `block`, `chặn`.
- Risky phrases: `nguy cơ trễ`, `nên xử lý`, `xử lý gì`, `ưu tiên`, `rủi ro`.
- `Sáng nay mình nên xử lý gì trước?` classifies as `risky`.
- Listed issues are capped at `MAX_ITEMS` (5). Counts are the full counts.
- Single-issue questions reuse `get_cached_suggestion` when it returns a row. That path does not call Ollama.
- Report dedup key: `report:{user_id}:{project}:{HH:MM}:{local date}`. Urgent dedup key: `urgent:{user_id}:{AlertSpec.dedup_key}`.
- Schedule: at most 3 values, each `HH:MM` matched by `^([01]\d|2[0-3]):[0-5]\d$`, unique per user. Empty list stores nothing and sends nothing.
- Report job: APScheduler id `pm_chat_reports`, every minute, `day_of_week=mon-fri`, timezone `settings.tz`, `coalesce=True`, `max_instances=1`. The runner also returns immediately when the local weekday is Saturday or Sunday.
- Do not change `digest_job`, `format_alert`, or Slack `notify` sending. Urgent chat is inserted in `dispatch` after `notify` returns.
- Chat does not write Jira. Clicking an issue key calls the existing `patch({ issue: key })` and opens `IssuePanel` on tab `suggestion`. Board and list clicks keep the panel default tab.
- Viewer is 403 on chat read and write. A PM of another project is 403. Admin may read and post on their own thread for any project. Schedule endpoints only touch the logged-in user.
- Poll interval is 5000 ms while `document.visibilityState === 'visible'`, and stops while hidden.
- New tables come from `Base.metadata.create_all` only. No migration framework.
- Imports stay at module top. The only inline imports allowed are the existing ones inside `jobs.py` job bodies; do not add new ones.
- This execution must not commit, push, or change git config. Commit steps below are skipped for that reason.
- Router: `erw.api.chat.chat_router`, prefix `/api/chat`, registered in `erw/main.py`.
- PUT `/api/chat/schedule` body is a JSON array of `HH:MM` strings. GET returns `{"times": ["08:00", "16:30"]}` sorted.
- POST `/api/chat/messages` body is `{"project", "text"}`. Response is `{"user", "assistant"}` with `id`, `project_key`, `kind`, `body`, `recommendation_status`, `created_at`.
- Blank or whitespace `text` is HTTP 422 and stores nothing.

## Review Focus

1. A question that contains both a selected-project issue key and sprint or priority words still classifies as `issue`, and a missing key does not call Ollama.
2. A recommendation that names an issue outside the fact paragraph, uses an unknown `action_type`, or returns a fourth action keeps the facts and becomes `failed`.
3. Two runs in the same local minute do not insert two reports with the same `dedup_key`, and a Saturday slot inserts nothing.
4. One `risk_up` writes one urgent row per PM, none for a viewer, a second `dispatch` does not duplicate them, and Slack `post` still runs when a sender is configured.
5. POST returns the assistant row as `pending` before the worker runs, and the worker updates that same id; an unmatched question never submits LLM work.

---

### Task 1: Chat tables

**Files:**
- Modify: `webapp/backend/erw/models.py`
- Test: `webapp/backend/tests/test_chat_models.py`

**Interfaces:**
- Consumes: `Base`, `UTCDateTime`, `User.id`
- Produces: `ChatMessage` and `ReportSlot` mapped classes. `ChatMessage` columns: `id`, `user_id` FK `users.id`, `project_key`, `kind`, `body`, `recommendation_status`, `created_at`, `dedup_key` nullable unique. Index name `ix_chat_messages_user_project_created` on `(user_id, project_key, created_at)`. `ReportSlot` composite PK `(user_id, time_hhmm)`.

- [ ] **Step 1: Write the failing test**

```python
def test_chat_tables_exist(session):
    names = set(inspect(session.get_bind()).get_table_names())
    assert {"chat_messages", "report_slots"} <= names


def test_report_slot_and_dedup_are_unique(session):
    user = User(email="pm@example.com", name="PM", password_hash="x", is_admin=False, created_at=datetime.now(UTC))
    session.add(user)
    session.flush()
    session.add(ReportSlot(user_id=user.id, time_hhmm="08:00"))
    session.flush()
    session.add(ReportSlot(user_id=user.id, time_hhmm="08:00"))
    with pytest.raises(IntegrityError):
        session.flush()
```

Also assert two `ChatMessage` rows with `dedup_key=None` flush cleanly, and a repeated non-null `dedup_key` raises `IntegrityError`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_models.py -v`
Expected: FAIL because the tables or classes are missing.

- [ ] **Step 3: Add the two models**

Add `Index` to the SQLAlchemy import. Map the columns in the Interfaces block. `created_at` is `UTCDateTime` and required.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 2: Digest snapshot

**Files:**
- Modify: `webapp/backend/erw/pipeline/digest.py`
- Test: `webapp/backend/tests/test_digest.py`

**Interfaces:**
- Consumes: existing `_sprint_line`, `MAX_ITEMS`, `Level`
- Produces: `DigestTopItem(key, summary, level_name, deadline_label, assignee, blocked)` and `DigestSnapshot(project, day_label, sprint_line, risky_count, raised_24h, blocked_count, new_24h, new_critical, top_risky)`. `collect_digest(session, project, now, settings) -> DigestSnapshot`. `build_digest` formats that snapshot with the current Slack strings, unchanged.

- [ ] **Step 1: Write the failing test**

Add `test_collect_digest_counts_and_order` beside the existing digest fixtures. Seed the same rows as `test_digest_counts` and assert `risky_count == 1`, `raised_24h == 1`, `blocked_count == 1`, `new_24h == 1`, `new_critical == 1`, `day_label == "04/11"`. Seed seven open HIGH issues as in `test_digest_header_and_max_five_items` and assert `len(top_risky) == 5` and `top_risky[0].key == "DEMO-7"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_digest.py::test_collect_digest_counts_and_order -v`
Expected: FAIL with `collect_digest` missing.

- [ ] **Step 3: Extract `collect_digest` and keep `build_digest` output**

Move the current queries into `collect_digest`. Sort and slice exactly as `build_digest` does today. `build_digest` only joins the snapshot into the existing lines, including Slack `escape` and the footer link.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_digest.py -v`
Expected: PASS, including the old digest string tests.

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 3: Rule lookup and fact text

**Files:**
- Create: `webapp/backend/erw/pipeline/chat_lookup.py`
- Test: `webapp/backend/tests/test_chat_lookup.py`

**Interfaces:**
- Consumes: `collect_digest`, `_sprint_line`, `MAX_ITEMS`, `Link`, `Issue`, `RiskState`
- Produces:
  - `classify_question(text: str, project_key: str) -> Literal["sprint", "blocked", "risky", "issue"] | None`
  - `FactAnswer(kind, facts, allowed_keys: frozenset[str], payload: dict, issue_key: str | None, skip_recommendation: bool)`
  - `answer_facts(session, project: str, text: str, now: datetime, settings: Settings) -> FactAnswer | None`
  - `None` means out of scope. `allowed_keys` is every Jira-like key rendered in `facts`.
  - Blocking direction matches `evaluate._blockers`: this issue blocks the other side of those links.

- [ ] **Step 1: Write the failing test**

```python
def test_issue_key_wins_over_other_words():
    assert classify_question("Tiến độ sprint của DEMO-41 hôm nay", "DEMO") == "issue"


def test_priority_question_is_risky():
    assert classify_question("Sáng nay mình nên xử lý gì trước?", "DEMO") == "risky"


def test_unmatched_question_is_none():
    assert classify_question("Thời tiết hôm nay thế nào?", "DEMO") is None


def test_other_project_key_does_not_force_issue():
    assert classify_question("OTHER-1 nên xử lý gì", "DEMO") == "risky"
```

Also cover, with rows in the session:

- Risky facts for six open MED-or-higher issues, two with `level_raised_at` inside 24 hours, start with `Đang có 6 issue nguy cơ trễ, 2 tăng bậc trong 24 giờ.` and list at most five keys. DEMO-41 blocked and blocking DEMO-18 (link `source_key=DEMO-41`, `target_key=DEMO-18`, `type_std="Block"`, `direction="1"`) renders `DEMO-41 bị block và đang chặn DEMO-18, assignee Lan.`
- Blocked facts count only open issues with `RiskState.blocked` true.
- Sprint facts equal `_sprint_line` plus a trailing period when a sprint exists, and `Chưa có sprint đang chạy.` when it does not. `skip_recommendation` is false.
- A known issue fact contains the key, assignee, and level label. `issue_key` is that key. `skip_recommendation` is false.
- An unknown `DEMO-99` returns facts `Không thấy DEMO-99 trong dự án DEMO.` and `skip_recommendation` is true.
- `allowed_keys` equals the keys printed in `facts`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_lookup.py -v`
Expected: FAIL with import or attribute error.

- [ ] **Step 3: Implement classification and `answer_facts`**

Use the phrase lists in Global Constraints, checked in that order after the issue-key rule. Issue keys match `(?<![A-Za-z0-9]){project}-\d+` case-insensitively and are returned uppercased. Render Vietnamese facts from `collect_digest` for `risky`. Render sprint facts from `_sprint_line` only. Cap listed issues at `MAX_ITEMS`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_lookup.py tests/test_digest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 4: Recommendation validator and Ollama writer

**Files:**
- Modify: `webapp/backend/erw/integrations/llm.py`
- Create: `webapp/backend/erw/pipeline/chat_recommend.py`
- Test: `webapp/backend/tests/test_chat_recommend.py`

**Interfaces:**
- Consumes: `ActionItem`, `ALLOWED_ACTION_TYPES`, `call_ollama_chat`, `_llm_executor`
- Produces:
  - `submit_to_llm_executor(fn: Callable[[], None]) -> None` in `llm.py`
  - `FAILED_RECOMMENDATION = "Chưa tạo được đề xuất bám dữ liệu."`
  - `validate_recommendation(text: str, actions: list[ActionItem], allowed_keys: set[str]) -> bool`
  - `write_recommendation(user_prompt: str, allowed_keys: set[str], settings: Settings, client: httpx.Client | None = None) -> tuple[str, Literal["ready", "failed"]]`
  - `recommendation_from_stored(output: dict, allowed_keys: set[str]) -> tuple[str, Literal["ready", "failed"]]`
  - `enqueue_message_recommendation(message_id: int, user_prompt: str, allowed_keys: set[str], settings: Settings, engine) -> None`
  - `apply_recommendation(session, message_id: int, text: str, status: str) -> None` appends one blank line plus `text` onto the current body and sets `recommendation_status`. It does nothing when the row is missing or no longer `pending`.

- [ ] **Step 1: Write the failing test**

```python
def test_validator_rejects_unknown_action_and_outside_issue():
    bad_type = ActionItem(action_type="delete_issue", target="DEMO-1", reason="x")
    outside = ActionItem(action_type="add_comment", target="DEMO-99", reason="x")
    assert validate_recommendation("Nên xử lý DEMO-1.", [bad_type], {"DEMO-1"}) is False
    assert validate_recommendation("Nên xử lý DEMO-99.", [outside], {"DEMO-1"}) is False
    assert validate_recommendation("Nên xử lý DEMO-99.", [], {"DEMO-1"}) is False


def test_validator_rejects_fourth_action():
    actions = [
        ActionItem(action_type="add_comment", target="DEMO-1", reason=str(i))
        for i in range(4)
    ]
    assert validate_recommendation("DEMO-1", actions, {"DEMO-1"}) is False
```

Also assert a single allowed action returns true. `write_recommendation` with `ollama_url=""` returns `(FAILED_RECOMMENDATION, "failed")` and does not call `call_ollama_chat`. A mocked JSON object whose action cites `DEMO-99` returns the failed line. A mocked `{"text": "Nên xử lý DEMO-1.", "actions": [{"action_type": "escalate_blocker", "target": "DEMO-1", "value": null, "reason": "đang chặn"}]}` returns that text and `"ready"`. `recommendation_from_stored` uses `summary` and does not need a network call. `enqueue_message_recommendation` submits to the LLM executor rather than calling Ollama on the caller thread: monkeypatch `submit_to_llm_executor` to record the callable, assert the caller returned before it runs, then run it and assert the same `ChatMessage.id` changed from `pending` to `ready`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_recommend.py -v`
Expected: FAIL with missing functions.

- [ ] **Step 3: Implement the validator, one Ollama call, and the executor submit**

`submit_to_llm_executor` submits to the existing `_llm_executor`. `write_recommendation` makes one `call_ollama_chat`. The system prompt requires Vietnamese, the `ActionItem` schema, `ALLOWED_ACTION_TYPES`, and no issue key outside the user payload. Empty `ollama_url`, transport errors, bad JSON, and failed validation all return the failed line. Stored suggestions contribute at most the first three actions, then the same validator. The worker opens `SessionLocal(bind=engine)`, calls `write_recommendation`, then `apply_recommendation`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_recommend.py tests/test_llm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 5: Chat message API

**Files:**
- Create: `webapp/backend/erw/api/chat.py`
- Modify: `webapp/backend/erw/main.py`
- Test: `webapp/backend/tests/test_api_chat.py`

**Interfaces:**
- Consumes: `answer_facts`, `recommendation_from_stored`, `enqueue_message_recommendation`, `get_cached_suggestion`, `build_user_prompt`, `_extract_factors`, `get_user_project_role`, `require_authenticated_user`
- Produces: `chat_router` routes `GET /api/chat/messages`, `POST /api/chat/messages`. `require_chat_access(session, user, project)` allows `is_admin` or role `pm`, else 403. POST stores the user row (`kind=user`, `recommendation_status=skipped`) and the assistant row immediately.

- [ ] **Step 1: Write the failing test**

Use the auth fixtures pattern from `tests/test_api_issues.py` (`create_session_token`, cookie name `settings.session_cookie_name`).

```python
def test_viewer_and_other_pm_are_forbidden(client, settings, session):
    # viewer on DEMO, pm on OTHER
    login(client, viewer, settings)
    assert client.get("/api/chat/messages", params={"project": "DEMO"}).status_code == 403
    login(client, pm_other, settings)
    assert client.post("/api/chat/messages", json={"project": "DEMO", "text": "ưu tiên"}).status_code == 403


def test_unmatched_question_does_not_call_ollama(client, settings, monkeypatch):
    monkeypatch.setattr("erw.api.chat.enqueue_message_recommendation", lambda **k: calls.append(k))
    resp = client.post("/api/chat/messages", json={"project": "DEMO", "text": "Thời tiết hôm nay thế nào?"})
    assert resp.status_code == 200
    assert resp.json()["assistant"]["body"] == "Chưa có trong hệ thống."
    assert resp.json()["assistant"]["recommendation_status"] == "skipped"
    assert calls == []
```

Also assert:

- Unauthenticated GET is 401.
- Admin GET and POST on DEMO return 200 without a `project_members` row.
- `Sáng nay mình nên xử lý gì trước?` stores an assistant row with `recommendation_status=pending`, facts beginning `Đang có`, and enqueues exactly once with that assistant id. Running the captured callable updates that id and does not insert a third row.
- `DEMO-41` with a valid `Suggestion` whose `issue_updated_at` matches the issue does not enqueue, and the assistant body contains the stored `summary` with status `ready`.
- Whitespace text returns 422 and leaves `chat_messages` empty.
- GET returns at most 50 messages, oldest to newest, only for the current user and project.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_api_chat.py -v`
Expected: FAIL with 404 because the router is not registered.

- [ ] **Step 3: Implement the router and register it**

On a matched lookup that needs a model, commit the pending assistant row before `enqueue_message_recommendation`. For a cached suggestion, compose facts and the stored recommendation in the request. For `skip_recommendation` or out of scope, do not enqueue. User prompt for `sprint`, `blocked`, `risky` is the JSON `payload`. User prompt for an uncached issue is `build_user_prompt(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_api_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 6: Report schedule API

**Files:**
- Modify: `webapp/backend/erw/api/chat.py`
- Test: `webapp/backend/tests/test_api_chat.py`

**Interfaces:**
- Consumes: `ReportSlot`, `require_authenticated_user`
- Produces: `replace_schedule(session, user_id: int, times: list[str]) -> list[str]` and routes `GET /api/chat/schedule`, `PUT /api/chat/schedule`. Invalid input is HTTP 422 with detail `Tối đa 3 mốc giờ.` or `Giờ phải là HH:MM.` or `Mốc giờ bị trùng.` The successful body replaces the user's rows.

- [ ] **Step 1: Write the failing test**

```python
def test_put_schedule_rejects_fourth_slot_and_bad_clock(client, settings):
    login(client, pm, settings)
    assert client.put("/api/chat/schedule", json=["08:00", "09:00", "10:00", "11:00"]).status_code == 422
    assert client.put("/api/chat/schedule", json=["8:00"]).status_code == 422
    assert client.put("/api/chat/schedule", json=["08:00", "08:00"]).status_code == 422
    ok = client.put("/api/chat/schedule", json=["16:30", "08:00"])
    assert ok.status_code == 200
    assert ok.json()["times"] == ["08:00", "16:30"]
    assert client.put("/api/chat/schedule", json=[]).json()["times"] == []
```

Also log in as admin and PUT `["09:15"]`. Assert the PM's stored `08:00` row is unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_api_chat.py::test_put_schedule_rejects_fourth_slot_and_bad_clock -v`
Expected: FAIL with 404 or 422 missing.

- [ ] **Step 3: Implement replace-all schedule**

Delete the current user's slots and insert the validated list in one transaction. Sort on read and on the PUT response.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_api_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 7: Weekday report job

**Files:**
- Create: `webapp/backend/erw/pipeline/chat_reports.py`
- Modify: `webapp/backend/erw/jobs.py`
- Modify: `webapp/backend/tests/test_scheduler.py`
- Test: `webapp/backend/tests/test_chat_reports.py`

**Interfaces:**
- Consumes: `ReportSlot`, `ProjectMember`, `ChatMessage`, `collect_digest`, `enqueue_message_recommendation`, `jobs.executor`
- Produces: `run_due_reports(session, now, settings) -> list[DueReport]` where `DueReport` is `message_id`, `user_prompt`, `allowed_keys`. `report_job(now: datetime | None = None) -> None` runs `run_due_reports` on `jobs.executor`, commits, then enqueues one recommendation per new row. Scheduler job id `pm_chat_reports`.

- [ ] **Step 1: Write the failing test**

```python
def test_same_minute_does_not_duplicate_report(session, settings):
    # Wednesday 2026-11-04 01:00 UTC == 08:00 Asia/Ho_Chi_Minh
    now = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
    first = run_due_reports(session, now, settings)
    second = run_due_reports(session, now, settings)
    session.flush()
    assert len(first) == 1 and second == []
    rows = session.query(ChatMessage).all()
    assert len(rows) == 1
    assert rows[0].dedup_key == f"report:{pm.id}:DEMO:08:00:2026-11-04"
    assert rows[0].kind == "report" and rows[0].recommendation_status == "pending"


def test_saturday_slot_inserts_nothing(session, settings):
    now = datetime(2026, 11, 7, 1, 0, tzinfo=UTC)
    assert run_due_reports(session, now, settings) == []
```

Also assert: no slots means no rows; a user who is PM of DEMO and OTHER gets two dedup keys; a viewer slot creates none; report facts contain the same risky count as `collect_digest`; `digest_job` inserts no `ChatMessage`. Extend `test_scheduler_registers_jobs_in_tz` so the job set is `morning_batch`, `daily_digest`, and `pm_chat_reports`. Keep the 3-hour misfire assertion on the two existing jobs only. Assert `pm_chat_reports` is `mon-fri`, minute `*`, `coalesce`, and `max_instances == 1`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_reports.py tests/test_scheduler.py::test_scheduler_registers_jobs_in_tz -v`
Expected: FAIL with `run_due_reports` missing, then the scheduler set mismatch after the function exists. Update the scheduler assertion in the same task before the green run.

- [ ] **Step 3: Implement the runner and register the cron job**

Match `time_hhmm` to the local `HH:MM`. Skip Saturday and Sunday in `settings.tz` even if called directly. Insert one pending report per PM project when the dedup key is absent. Catch `IntegrityError` and continue so a unique collision is a skip. `report_job` uses `executor.submit(...).result()` like `digest_job`. Import `chat_reports` and `enqueue_message_recommendation` at the top of `jobs.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_chat_reports.py tests/test_scheduler.py tests/test_digest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 8: Urgent chat inside dispatch

**Files:**
- Create: `webapp/backend/erw/pipeline/chat_urgent.py`
- Modify: `webapp/backend/erw/pipeline/alerts.py`
- Test: `webapp/backend/tests/test_alerts.py`

**Interfaces:**
- Consumes: `AlertSpec`, `ProjectMember`, `ChatMessage`, `format_alert` text already produced for `notify`
- Produces: `insert_urgent_messages(session, spec: AlertSpec, text: str, now: datetime) -> int`. Kinds outside `risk_new`, `risk_up`, `blocked`, `critical` insert nothing. `dispatch` calls it once per spec after `notify` returns, including when Slack is disabled or failed.

- [ ] **Step 1: Write the failing test**

```python
def test_dispatch_risk_up_writes_one_urgent_per_pm_and_posts_slack(session, settings):
    # two PM members, one viewer, webhook set, FakeSender
    dispatch(session, [chg(prev=Level.MED)], NOW, settings.model_copy(update={"slack_webhook_url": "https://hooks.slack.com/services/xxx"}), sender=sender)
    assert sender.calls == 1
    rows = session.query(ChatMessage).filter_by(kind="urgent").all()
    assert sorted(r.user_id for r in rows) == sorted([pm_a.id, pm_b.id])
    assert rows[0].body == format_alert(...)
    assert rows[0].recommendation_status == "skipped"
    dispatch(session, [chg(prev=Level.MED)], NOW, settings, sender=sender)
    assert session.query(ChatMessage).filter_by(kind="urgent").count() == 2
    assert sender.calls == 1
```

Also assert `insert_urgent_messages` on an `AlertSpec` of kind `digest` returns 0.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_alerts.py::test_dispatch_risk_up_writes_one_urgent_per_pm_and_posts_slack -v`
Expected: FAIL because no urgent rows are written.

- [ ] **Step 3: Insert urgent rows after `notify`**

Import `insert_urgent_messages` at the top of `alerts.py`. Pass the same `text` given to `notify` and the spec after the blocked dedup key has been refined. Do not call Ollama.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest tests/test_alerts.py tests/test_digest.py tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 9: Chat window on board and list

**Files:**
- Modify: `webapp/frontend/src/api/client.js`
- Create: `webapp/frontend/src/components/pmChatText.js`
- Create: `webapp/frontend/src/components/pmChatText.test.mjs`
- Create: `webapp/frontend/src/components/PmChat.jsx`
- Modify: `webapp/frontend/src/components/IssuePanel.jsx`
- Modify: `webapp/frontend/src/App.jsx`

**Interfaces:**
- Consumes: `GET/POST /api/chat/messages`, `GET/PUT /api/chat/schedule`, `useDashboardState`, `IssuePanel` `activeTab`
- Produces: `splitChatText(body) -> Array<{type: "text", text: string} | {type: "issue", key: string}>`. `PmChat` props `{project, onOpenIssue}`. `IssuePanel` accepts `suggestionNonce`. App shows chat only for `board` and `list`, when `user.is_admin` or the selected project's role is `pm`.

- [ ] **Step 1: Write the failing test**

```javascript
import assert from 'node:assert/strict';
import test from 'node:test';
import { splitChatText } from './pmChatText.js';

test('issue keys and slack labels become issue tokens', () => {
  const parts = splitChatText('[Tăng rủi ro] <https://example/browse/DEMO-41|DEMO-41> đang chặn DEMO-18');
  assert.deepEqual(parts.filter((p) => p.type === 'issue').map((p) => p.key), ['DEMO-41', 'DEMO-18']);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && node --test src/components/pmChatText.test.mjs`
Expected: FAIL with module not found.

- [ ] **Step 3: Implement the chat window**

`splitChatText` turns `<url|LABEL>` into an issue token when LABEL matches `[A-Z][A-Z0-9]+-\d+`, and turns bare keys into issue tokens. `PmChat` renders the schedule editor above the messages, sends the question, and polls `['chat-messages', project]` every 5000 ms only while the document is visible. Pending messages show the body plus `Đang viết đề xuất…`. Failed messages show the body, and append the failed line only when the body does not already contain it. Issue buttons call `onOpenIssue(key)`.

In `App.jsx`, place `PmChat` in the main column beside `BoardView` for board and list, with a collapse control. `onOpenIssue` sets a nonce and `patch({ issue: key })`. Board selection clears the suggestion request. `IssuePanel` starts on `suggestion` when mounted with a positive nonce for that issue, and a `useEffect` on `suggestionNonce` switches to `suggestion` when the same issue is already open.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && node --test 'src/**/*.test.mjs'`
Expected: PASS. There is no frontend typecheck or lint script.

- [ ] **Step 5: Commit**

Skipped: the user forbade commits.

### Task 10: Mark the design approved

**Files:**
- Modify: `docs/superpowers/specs/2026-11-21-pm-chat-va-bao-cao-design.md` status cell only

**Interfaces:**
- Consumes: nothing
- Produces: the status cell text `Đã duyệt (2026-11-21)`

- [ ] **Step 1: Replace `Chờ duyệt` with `Đã duyệt (2026-11-21)`**

Do not change any other line in the design doc.

- [ ] **Step 2: Check the diff is one line**

Run: `git diff -- docs/superpowers/specs/2026-11-21-pm-chat-va-bao-cao-design.md`
Expected: one status-cell change.

- [ ] **Step 3: Commit**

Skipped: the user forbade commits.
