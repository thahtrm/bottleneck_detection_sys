# Early Risk Web MVP — Kế hoạch 1/4: Spike + Backend lõi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Một backend Python chạy được, gồm: nhận webhook Jira Cloud → đồng bộ task vào SQLite → tính hạn, tín hiệu luật và mức rủi ro → gửi cảnh báo Slack có prefix; lô model hằng ngày (delay_t0, criticality_t0) và digest 8:00.

**Architecture:** Một process FastAPI. Process này chứa APScheduler và một `ThreadPoolExecutor` cho việc nền. Dữ liệu nằm trong SQLite qua SQLAlchemy 2. Logic rủi ro là các hàm thuần trong `erw/domain/`. Lô model gọi thư viện `early_risk_detection` (nguyên trạng) trên một bản DuckDB làm việc, trong đó các issue của site demo nằm dưới instance `ERW`.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2 (sync), APScheduler 3, httpx, tenacity, pytest, respx; `early_risk_detection` (repo này).

**Spec:**
- `docs/superpowers/specs/2026-11-01-early-risk-web-mvp-architecture.md` (gọi tắt **MVP**)
- `docs/superpowers/specs/2026-11-01-web-quan-ly-tien-do-du-an-design.md` (gọi tắt **SRS**)

**Các kế hoạch tiếp theo** (viết sau khi kế hoạch này xong):
- 2/4: LLM + action ghi Jira + API dashboard + auth/RBAC.
- 3/4: Frontend React.
- 4/4: `seed-demo` + `sim-eval`.

## Global Constraints

- Code backend nằm ở `webapp/backend/`, package `erw`, test ở `webapp/backend/tests/`. Dùng venv của repo: `.venv/bin/python` (3.13.9).
- Không sửa `src/early_risk_detection/` (MVP §1.3).
- Phát hiện thay đổi **chỉ bằng webhook**, không có polling định kỳ. Có đồng bộ bù JQL `updated >= <mốc webhook cuối − 5 phút>` **khi khởi động** và **trước lô 06:45** (MVP §6.1, SRS FR-J4).
- Webhook payload chỉ là tín hiệu; luôn `GET` lại issue qua REST (MVP §6.1 bước 2).
- Ghi Jira bằng tài khoản dịch vụ (kế hoạch 2). Kế hoạch này chỉ **đọc** Jira, ngoài việc đăng ký webhook.
- Múi giờ hiển thị `Asia/Ho_Chi_Minh`. Lưu DB theo UTC (datetime có timezone).
- Instance trong DuckDB làm việc: `ERW`; uid có dạng `ERW|<KEY>`.
- Thứ tự xác định hạn: `duedate` → `endDate` sprint active/future sớm nhất → `releaseDate` Fix Version chưa release sớm nhất → SLA mô hình (SRS 4.1).
- SLA mô hình (ngày): mặc định 45; Task 21; Requirement/Feature 90; `priority_norm ≥ 0,6` thì 30; `≥ 0,8` thì 14. Thứ tự gán như `delay/features.py:35`: gán theo loại issue trước, sau đó priority ghi đè.
- Mức rủi ro: `LOW < MED < HIGH`; hiển thị "Thấp", "TB", "Cao".
- Prefix Slack: `[Tổng hợp ngày]`, `[Nguy cơ trễ]`, `[Tăng rủi ro]`, `[Bị block]`, `[Quan trọng]`, `[Đã xử lý]`, kèm `[<PROJECT>]` ngay sau (SRS FR-S2, FR-S4).
- @ người phụ trách = `displayName` của Jira; không có thì dùng `accountId` (SRS FR-S3).
- `MODEL_MODE` mặc định `shadow`: điểm model được lưu và hiển thị nhưng **không** tham gia tính mức rủi ro (SRS 6.3, FR-V2).
- Lint: `ruff check webapp/backend` sạch (line-length 120, như repo).

## Review Focus

1. **Jira gửi lặp lại cùng một webhook**, hoặc webhook đến cùng lúc với đồng bộ bù → chỉ một bản ghi, không có cảnh báo kép. Kiểm thử ở Task 5 (`test_sync_same_issue_twice_is_unchanged`) và Task 10 (`test_duplicate_alert_suppressed`).
2. **Webhook của dự án không được theo dõi**, hoặc secret sai → bỏ qua hoặc trả 404, không lưu gì. Kiểm thử ở Task 6.
3. **Task không có due date, sprint hay version** → dùng hạn SLA, không crash. Kiểm thử ở Task 7 (`test_deadline_falls_back_to_sla`).
4. **Task đã resolved hoặc bị xoá** → không còn trong rủi ro, không cảnh báo nữa. Kiểm thử ở Task 9 (`test_resolved_issue_is_low_and_not_alerted`) và Task 5 (`test_deleted_issue_marked`).
5. **Tóm tắt có ký tự `<`, `>`, `&` hoặc emoji/tiếng Việt** → tin Slack không vỡ định dạng. Kiểm thử ở Task 10 (`test_format_escapes_slack_control_chars`).

---

## File Structure

```
webapp/backend/
  pyproject.toml                 # package erw; deps; [project.scripts] erw = "erw.cli:main"
  .env.example
  erw/
    __init__.py
    settings.py                  # Settings (pydantic-settings), get_settings()
    db.py                        # engine, SessionLocal, init_db()
    models.py                    # ORM: Issue, Change, Link, Sprint, IssueSprint, Version, IssueVersion,
                                 #      Score, RiskState, Notification, KV
    main.py                      # create_app(): routers, startup (init_db, catch-up, scheduler)
    jobs.py                      # executor + scheduler + job functions
    cli.py                       # erw init-db | register-webhook | catch-up | run-batch | digest
    api/webhooks.py              # POST /webhooks/jira/{secret}
    api/health.py                # GET /healthz
    integrations/jira.py         # JiraClient
    integrations/slack.py        # format_alert, format_digest, SlackSender
    ingest/sync.py               # upsert_issue_json, sync_issue, sync_sprint, sync_version, mark_deleted, catch_up
    domain/types.py              # Level, Deadline, Factor, ModelSignals, Thresholds, IssueTimeline
    domain/timeline.py           # build_timeline
    domain/deadline.py           # sla_days, resolve_deadline
    domain/rules.py              # evaluate_rules
    domain/risk.py               # aggregate
    pipeline/evaluate.py         # evaluate_issue, evaluate_all, RiskChange
    pipeline/alerts.py           # alerts_for, notify
    pipeline/digest.py           # build_digest
    ml/duckdb_sync.py            # ensure_work_db, sync_erw_instance
    ml/batch.py                  # run_model_batch
  tests/
    conftest.py                  # session fixture (SQLite in-memory), settings fixture, load_fixture()
    fixtures/jira/*.json         # issue JSON tối giản theo shape Jira Cloud v3
    test_*.py
webapp/spikes/                   # script thăm dò, không đóng gói
docs/superpowers/spikes/         # báo cáo spike
```

---

## Phần A — Spike (S1, S2 do người dùng làm; S3 làm trước Task 5)

### Task 1–2: Spike S1 (chi phí lô chấm điểm) và S2 (LLM song ngữ, JSON): **người dùng tự thực hiện, ngoài phạm vi kế hoạch này**

Không ai trong kế hoạch này thực hiện hai task này. Các task khác chỉ phụ thuộc vào **kết quả**:
- **S1 →** ngưỡng thời gian và RAM cho smoke test của Task 11, Step 5. Cũng quyết định có cần thu nhỏ nền DuckDB không. Nếu đến lúc làm Task 11 vẫn chưa có kết quả: Step 5 chỉ ghi lại thời gian và RAM quan sát được, không coi là đạt hay trượt.
- **S2 →** giá trị `llm_model` (mặc định tạm thời `qwen2.5:7b` ở Task 4). Task 11 chỉ dùng tên này để giải phóng VRAM. Việc chọn model chính thức thuộc kế hoạch 2.

### Task 3: Spike S3 — webhook Jira Cloud qua ngrok domain tĩnh (runbook)

**Files:**
- Create: `webapp/spikes/s3_receiver.py` (FastAPI một route `POST /webhooks/jira/{secret}`, ghi payload vào `var/s3/<ts>-<event>.json`)
- Create: `docs/superpowers/spikes/2026-11-02-s3-webhook.md`

- [ ] **Step 1:** Tạo site Jira Cloud free và một dự án Scrum `DEMO`. Tạo API token cho tài khoản dịch vụ, và lấy domain tĩnh ngrok.
- [ ] **Step 2:** Chạy receiver, `ngrok http --url=<static-domain> 8000`. Đăng ký webhook bằng `curl -u email:token -X POST https://<site>/rest/webhooks/1.0/webhook` với các sự kiện ở MVP §6.1 bước 1 và `filters.issue-related-events-section = "project = DEMO"`.
- [ ] **Step 3:** Trên Jira, lần lượt: tạo issue, đổi status, gán sprint, đặt due date, tạo link "blocks", tạo và sửa sprint, tạo version, xoá issue.
  Expected: mỗi thao tác sinh **ít nhất một** file payload trong `var/s3/`.
- [ ] **Step 4: Ghi vào báo cáo:**
  - `webhookEvent` thực nhận cho từng thao tác;
  - đường dẫn tới `issue.key`, `sprint.id`, `version.id` trong payload;
  - `customfield` của Sprint và Story Points trên site (lấy từ `GET /rest/api/3/field`);
  - độ trễ quan sát được;
  - các ví dụ payload, để làm fixture cho Task 5 và 6. Chép 3 payload đã ẩn danh vào `webapp/backend/tests/fixtures/jira/`.
- [ ] **Step 5: Commit.** `git commit -m "spike(s3): jira cloud webhook runbook and sample payloads"`

---

## Phần B — Backend lõi

### Task 4: Khung package, cấu hình, schema SQLite

**Files:**
- Create: `webapp/backend/pyproject.toml`, `webapp/backend/.env.example`, `erw/__init__.py`, `erw/settings.py`, `erw/db.py`, `erw/models.py`, `erw/main.py`, `erw/api/health.py`, `tests/conftest.py`, `tests/test_health.py`

**Interfaces:**
- Produces:
  - `Settings` có các trường và giá trị mặc định:
    - `db_url="sqlite:///var/erw.db"`;
    - `jira_base_url: str`, `jira_email: str`, `jira_api_token: str`;
    - `jira_projects: list[str]` (env `JIRA_PROJECTS="DEMO,PAY"`);
    - `jira_webhook_secret: str`;
    - `jira_sprint_field="customfield_10020"`, `jira_story_points_field="customfield_10016"`;
    - `public_base_url: str` (URL ngrok);
    - `slack_webhook_url: str`, `slack_max_per_hour=20`;
    - `ollama_url="http://localhost:11434"`;
    - `base_duckdb="data/jira.duckdb"`, `work_duckdb="var/erw_scoring.duckdb"`;
    - `bundles_dir="bundles"`, `emb_dir="data"`, `stream_dir="var/stream"`;
    - `erw_instance="ERW"`;
    - `tz="Asia/Ho_Chi_Minh"`, `batch_time="06:45"`, `digest_time="08:00"`;
    - `model_mode: Literal["shadow","active"]="shadow"`;
    - `llm_model="qwen2.5:7b"` (giá trị tạm; người dùng chốt sau S2);
    - `pm_name_by_project: dict[str,str] = {}` (env JSON, ví dụ `{"DEMO":"Trần Bình"}`);
    - `status_category_overrides: dict[str,str] = {}` (tên status → `new|indeterminate|done`);
    - `web_base_url="http://localhost:8000"`.
  - `get_settings() -> Settings` (lru_cache).
  - `db.py`: `make_engine(url) -> Engine` (bật `PRAGMA journal_mode=WAL` và `foreign_keys=ON`), `SessionLocal`, `init_db(engine)`.
  - `models.py`: các bảng theo MVP §5 kèm cột bổ sung:
    - `Issue`: `key PK`, `project_key`, `summary`, `issuetype`, `priority`, `priority_norm: float`, `status`, `status_category` (`new|indeterminate|done`), `assignee_id`, `assignee_name`, `duedate: date|None`, `story_points: float|None`, `created_at`, `updated_at`, `resolved_at`, `deleted_at`, `raw: JSON`;
    - `Change(issue_key, change_id, idx, at, field, from_val, to_val, from_str, to_str)`;
    - `Link(source_key, target_key, type_std, direction)`;
    - `Sprint(id, board_id, name, state, start_at, end_at, complete_at)`;
    - `IssueSprint(issue_key, sprint_id)`;
    - `Version(id, project_key, name, release_date, released)`;
    - `IssueVersion(issue_key, version_id)`;
    - `Score(id, issue_key, scorer, as_of, value, level, is_critical, extra: JSON, deadline_type, deadline_at, factors: JSON)`;
    - `RiskState(issue_key PK, level, prev_level, delay_value, crit_score, is_critical, blocked, deadline_type, deadline_at, factors, last_alerted_level, updated_at)`;
    - `Notification(id, kind, issue_key, project_key, dedup_key UNIQUE, text, sent_at, status)`;
    - `KV(key PK, value)` (lưu `last_webhook_at`, `last_catch_up_at`, `pending_sync`).
  - `create_app(settings: Settings | None = None) -> FastAPI`.
  - `GET /healthz → {"status":"ok","last_webhook_at": str|None}`.
  - `tests/conftest.py`: fixture `settings` (giá trị test, `db_url="sqlite://"`), `session` (in-memory, `init_db`), `load_fixture(name) -> dict`.

- [ ] **Step 1: Viết test**

```python
def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_init_db_creates_tables(session):
    from sqlalchemy import inspect
    names = set(inspect(session.bind).get_table_names())
    assert {"issues", "changes", "links", "sprints", "issue_sprints", "versions", "issue_versions",
            "scores", "risk_state", "notifications", "kv"} <= names
```
- [ ] **Step 2:** `cd webapp/backend && ../../.venv/bin/python -m pytest -q`. Expected: FAIL (thiếu module).
- [ ] **Step 3: Cài đặt** các mục ở Interfaces.
  - `pyproject.toml`: deps `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy>=2`, `apscheduler>=3.10,<4`, `httpx`, `tenacity`; extra `dev`: `pytest`, `respx`, `ruff`.
  - Cài: `.venv/bin/pip install -e webapp/backend[dev]`. Thư viện `early-risk-detection` đã được cài editable trong venv.
  - Thêm `var/` vào `.gitignore` nếu chưa có.
- [ ] **Step 4:** Chạy test. Expected: PASS. `ruff check webapp/backend` sạch.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): backend skeleton, settings, sqlite schema, healthz"`

### Task 5: Jira client + đồng bộ issue, sprint, version

**Files:**
- Create: `erw/integrations/jira.py`, `erw/ingest/sync.py`, `tests/test_jira_client.py`, `tests/test_sync.py`
- Fixtures: `tests/fixtures/jira/issue_new.json`, `issue_updated.json` (thêm 1 history đổi status và Sprint), `issue_blocked.json` (có `issuelinks` "is blocked by" tới DEMO-2), `sprint.json`, `version.json`. Dùng shape thật lấy từ Task 3.

**Interfaces:**
- Consumes: `Settings`, ORM models (Task 4).
- Produces:
  - `class JiraClient(base_url: str, email: str, token: str, *, http: httpx.Client | None = None)`, với các phương thức:
    - `get_issue(key: str) -> dict | None`: `GET /rest/api/3/issue/{key}?expand=changelog`; nếu `changelog.total > len(histories)` thì gọi thêm `GET /rest/api/3/issue/{key}/changelog?startAt=` để lấy đủ; trả `None` nếu 404.
    - `search_keys(jql: str) -> list[str]`: `POST /rest/api/3/search/jql`, `fields=["key"]`, phân trang `nextPageToken`.
    - `get_sprint(sprint_id: int) -> dict | None`, `get_version(version_id: int) -> dict | None`.
    - `myself() -> dict`.
    - `register_webhook(url: str, events: list[str], jql: str) -> dict`.
    - Retry bằng tenacity: chỉ khi 429/502/503/504, tối đa 4 lần, chờ `Retry-After` nếu có, không thì 2, 4, 8 giây. Lỗi khác thì raise `JiraError(status, body)`.
  - `@dataclass SyncResult(kind: Literal["created","updated","unchanged","deleted","ignored"], key: str, changed_fields: frozenset[str])`
  - `upsert_issue_json(session, raw: dict, settings) -> SyncResult`:
    - project không thuộc `settings.jira_projects` thì trả `ignored`;
    - `created` nếu chưa có issue;
    - `updated` nếu có `change_id` mới, với `changed_fields` = tập `items[].field` của các history mới (chữ thường, ví dụ `{"status","sprint"}`);
    - `unchanged` nếu không có gì mới.
    - Các cột lấy từ: `fields.status.statusCategory.key`; `fields.priority.name` → `priority_norm` dùng `early_risk_detection.data.normalize.normalize_priority`; `fields.duedate`; `fields[settings.jira_sprint_field]` (list sprint) → upsert `Sprint` + thay `IssueSprint`; `fields.fixVersions` → upsert `Version` + thay `IssueVersion`; `fields.issuelinks` → thay `Link` (`type_std` theo `normalize_link_type`, `direction=1` nếu có `outwardIssue`); `assignee.displayName` / `assignee.accountId`; lưu `raw`.
  - `sync_issue(session, client, key, settings) -> SyncResult`: `get_issue`; trả `None` thì `mark_deleted`; còn lại gọi `upsert_issue_json`.
  - `mark_deleted(session, key) -> SyncResult` (đặt `deleted_at = now`, kind `deleted`).
  - `sync_sprint(session, raw_sprint: dict) -> list[str]` (trả các issue key thuộc sprint, để đánh giá lại).
  - `sync_version(session, raw_version: dict) -> list[str]`.

- [ ] **Step 1: Viết test**

```python
def test_get_issue_fetches_remaining_changelog_pages(respx_mock): ...  # total=150, histories=100 → gọi /changelog
def test_retry_on_429_then_success(respx_mock): ...                   # 429 Retry-After:0 rồi 200
def test_get_issue_404_returns_none(respx_mock): ...

def test_upsert_new_issue_is_created(session, settings):
    r = upsert_issue_json(session, load_fixture("issue_new"), settings)
    assert r.kind == "created"
    i = session.get(Issue, "DEMO-1")
    assert i.status_category == "new" and i.assignee_name == "Nguyễn Văn An"

def test_sync_same_issue_twice_is_unchanged(session, settings):
    upsert_issue_json(session, load_fixture("issue_new"), settings)
    assert upsert_issue_json(session, load_fixture("issue_new"), settings).kind == "unchanged"

def test_update_reports_changed_fields(session, settings):
    upsert_issue_json(session, load_fixture("issue_new"), settings)
    r = upsert_issue_json(session, load_fixture("issue_updated"), settings)
    assert r.kind == "updated" and {"status", "sprint"} <= r.changed_fields

def test_untracked_project_ignored(session, settings): ...   # key "OTHER-1" → kind == "ignored", không có row
def test_blocked_link_stored(session, settings): ...         # Link(DEMO-3 → DEMO-2, type_std == "Block")
def test_deleted_issue_marked(session, settings): ...        # mark_deleted → deleted_at not None
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt** theo Interfaces.
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): jira client and idempotent issue/sprint/version sync"`

### Task 6: Route webhook, executor nền, đồng bộ bù, CLI đăng ký webhook

**Files:**
- Create: `erw/api/webhooks.py`, `erw/jobs.py`, `erw/cli.py`, `tests/test_webhooks.py`, `tests/test_catch_up.py`
- Modify: `erw/main.py` (include router; startup: `init_db`, nộp `catch_up` vào executor, khởi động scheduler ở Task 12)

**Interfaces:**
- Consumes: `JiraClient`, `sync_issue`, `sync_sprint`, `sync_version`, `mark_deleted` (Task 5).
- Produces:
  - `jobs.executor: ThreadPoolExecutor(max_workers=1)` (tuần tự hoá ghi SQLite).
  - `jobs.handle_webhook(payload: dict) -> None`: phân nhánh theo `payload["webhookEvent"]`:
    - `jira:issue_created|jira:issue_updated|issuelink_*` → `sync_issue(key)` (với `issuelink_*`, sync **cả hai** đầu link: `sourceIssueId`/`destinationIssueId` → key qua `get_issue`);
    - `jira:issue_deleted` → `mark_deleted`;
    - `sprint_*` → `get_sprint` + `sync_sprint`;
    - `jira:version_*` → `get_version` + `sync_version`.

    Sau mỗi lần sync, gọi `pipeline.evaluate.on_synced(session, results, now, settings)` (Task 9; trước Task 9 là hàm rỗng cùng chữ ký). Ghi `KV last_webhook_at`. Gặp `JiraError` thì thêm key vào `KV pending_sync` (JSON list).
  - `POST /webhooks/jira/{secret}`: secret sai (so bằng `hmac.compare_digest`) thì trả 404; đúng thì `executor.submit(handle_webhook, payload)` rồi trả `200 {"accepted": true}`.
  - `ingest.sync.catch_up(session, client, settings, now) -> int`:
    - `since = KV last_webhook_at` (nếu không có: `now − 1 ngày`) `− 5 phút`;
    - JQL `project in (<projects>) AND updated >= "<since theo tz của myself().timeZone, định dạng yyyy/MM/dd HH:mm>"`;
    - sync từng key, sync thêm các key trong `pending_sync`, rồi xoá `pending_sync`;
    - ghi `KV last_catch_up_at`; trả số issue đã sync.
  - CLI `erw register-webhook`: `url = f"{public_base_url}/webhooks/jira/{secret}"`; events theo MVP §6.1 bước 1; jql `project in (...)`.
  - CLI `erw catch-up`, `erw init-db`.

- [ ] **Step 1: Viết test**

```python
def test_wrong_secret_404(client): assert client.post("/webhooks/jira/nope", json={}).status_code == 404

def test_valid_webhook_accepted_and_synced(client, fake_jira, session):
    r = client.post(f"/webhooks/jira/{SECRET}", json=load_fixture("wh_issue_created"))
    assert r.status_code == 200
    jobs.executor.submit(lambda: None).result()      # đợi hàng đợi chạy xong
    assert session.get(Issue, "DEMO-1") is not None

def test_jira_error_goes_to_pending_sync(...): ...    # fake_jira.get_issue raise JiraError(500) → KV pending_sync == ["DEMO-1"]
def test_catch_up_uses_last_webhook_minus_5_minutes(...): ...  # JQL chứa mốc đúng tz; pending_sync được xử lý và xoá
```
`fake_jira` là một double của `JiraClient`, được inject qua `jobs.set_client()` (test hook duy nhất).
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt.**
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): jira webhook endpoint, background sync, catch-up and CLI"`

### Task 7: IssueTimeline và xác định hạn

**Files:**
- Create: `erw/domain/types.py`, `erw/domain/timeline.py`, `erw/domain/deadline.py`, `tests/test_deadline.py`, `tests/test_timeline.py`

**Interfaces:**
- Produces (`domain/types.py`, mọi dataclass `frozen=True`):
  - `class Level(IntEnum): LOW=0; MED=1; HIGH=2`, kèm `label_vi` → `"Thấp" | "TB" | "Cao"`.
  - `Deadline(type: Literal["duedate","sprint","release","sla"], at: datetime, label: str)`. `label` ví dụ:
    - `"Trễ due date 05/11"`;
    - `"Trễ sprint Sprint 24 (04/11)"`;
    - `"Vượt release 2.3 (15/11)"`;
    - `"Hạn: SLA mô hình 14 ngày"`.
  - `SprintInfo(id, name, state, start_at, end_at)`, `VersionInfo(id, name, release_date, released)`.
  - `IssueTimeline`, gồm:
    - `key, project, summary, issuetype, priority_norm, status, status_category`;
    - `assignee_id, assignee_name, created_at, resolved_at, deleted_at, duedate`;
    - `sprints: list[SprintInfo]`, `versions: list[VersionInfo]`;
    - `status_since: datetime`;
    - `reopen_count: int` (số lần chuyển từ category `done` về khác `done`, kể từ `start_at` của sprint hiện tại, hoặc từ đầu nếu không có sprint);
    - `duedate_changes: int`, `sprint_changes: int`, `assignee_changes: int`;
    - `closed_sprints_count: int` (số sprint `closed` mà task từng thuộc);
    - `open_blockers: list[str]`, `blocked_since: datetime | None`.
  - `build_timeline(issue: Issue, changes: list[Change], sprints: list[Sprint], versions: list[Version], blockers: list[tuple[str, bool, datetime]], as_of: datetime) -> IssueTimeline`.
    - Chỉ dùng `changes` có `at ≤ as_of`.
    - `blockers` = danh sách (key, đã resolved hay chưa, thời điểm tạo link).
    - Thời điểm tạo link lấy từ changelog `Link` nếu có, không thì dùng `created_at` của issue.
  - `deadline.sla_days(issuetype: str, priority_norm: float) -> float`: theo Global Constraints, khớp `delay/features.py:35`.
  - `deadline.resolve_deadline(tl: IssueTimeline) -> Deadline`: theo thứ tự ở Global Constraints. Sprint chỉ xét `state in {"active","future"}` và có `end_at`. Version chỉ xét `released == False` và có `release_date`.

- [ ] **Step 1: Viết test**

```python
def test_duedate_wins(): assert resolve_deadline(tl(duedate=date(2026,11,5), sprints=[S24])).type == "duedate"
def test_sprint_when_no_duedate(): d = resolve_deadline(tl(sprints=[S23_CLOSED, S24_ACTIVE])); assert d.type == "sprint" and d.at == S24_ACTIVE.end_at
def test_release_when_no_sprint(): ...  # 2 version chưa release → lấy release_date sớm nhất; version released bị bỏ qua
def test_deadline_falls_back_to_sla():
    d = resolve_deadline(tl(issuetype="Task", priority_norm=0.5, created_at=T0))
    assert d.type == "sla" and d.at == T0 + timedelta(days=21)
@pytest.mark.parametrize("it,p,days", [("Bug",0.5,45),("Task",0.5,21),("New Feature",0.5,90),("Task",0.6,30),("Bug",0.8,14)])
def test_sla_days(it, p, days): assert sla_days(it, p) == days

def test_timeline_ignores_changes_after_as_of(): ...
def test_reopen_counted_from_done_to_not_done(): ...
def test_status_since_is_last_status_change(): ...
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt.** Để biết category của một status trong changelog, lấy `status_category` của chính issue cho trạng thái hiện tại. Trạng thái cũ dùng bảng `Settings.status_category_overrides: dict[str,str]`; mặc định các tên `Done|Closed|Resolved` → `done`, `To Do|Open|Backlog` → `new`, còn lại là `indeterminate`.
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): issue timeline and deadline resolution"`

### Task 8: Tín hiệu luật và tổng hợp mức rủi ro

**Files:**
- Create: `erw/domain/rules.py`, `erw/domain/risk.py`, `tests/test_rules.py`, `tests/test_risk.py`
- Modify: `erw/domain/types.py` (thêm `Factor`, `Thresholds`, `ProjectStats`, `ModelSignals`)

**Interfaces:**
- Consumes: `IssueTimeline`, `Deadline`, `Level` (Task 7).
- Produces:
  - `Factor(id: str, label: str, value: str, source: str)`. Ví dụ `label="Đứng ở In Progress"`, `value="6 ngày"`, `source="changelog"`.
  - `Thresholds`, các giá trị mặc định lấy từ SRS 6.4:
    - `sprint_elapsed=0.7`;
    - `blocked_long_days=3`;
    - `reopen_min=1`;
    - `deadline_moves_min=2`;
    - `reassign_min=2`;
    - `unassigned_workdays=3`;
    - `p_med=0.39`;
    - `p_high=0.6` (giá trị này là [quyết định của plan]; SRS chỉ ghi "ngưỡng cao").
  - `ProjectStats(dwell_p75_days: dict[str, float])`: P75 số ngày ở từng status, tính trên các issue của dự án. Nếu thiếu thì mặc định 5 ngày.
  - `ModelSignals(p_delay: float | None, predicted_finish: datetime | None, is_critical: bool, crit_score: float | None)`.
  - `evaluate_rules(tl, deadline, now, stats, th) -> list[Factor]`. Các id và điều kiện (chỉ áp dụng khi task chưa `done` và chưa xoá):

    | id | Điều kiện |
    |---|---|
    | `overdue` | `now > deadline.at` |
    | `sprint_not_started` | deadline là sprint, phần sprint đã trôi qua ≥ `th.sprint_elapsed`, và `status_category == "new"` |
    | `stagnant` | thời gian ở status hiện tại > `dwell_p75_days[status]` |
    | `blocked` | có `open_blockers` |
    | `blocked_long` | `blocked_since` cách `now` > `blocked_long_days` |
    | `reopened` | `reopen_count ≥ reopen_min` |
    | `deadline_moved` | `duedate_changes + sprint_changes ≥ deadline_moves_min` |
    | `reassigned` | `assignee_changes ≥ reassign_min` |
    | `unassigned_near_deadline` | không có assignee và số ngày làm việc tới hạn ≤ `unassigned_workdays` (dùng `numpy.busday_count`) |
    | `carried_over` | `closed_sprints_count ≥ 1` |

  - `aggregate(factors, model: ModelSignals | None, deadline, th, model_mode) -> Level`. Nếu `model_mode == "shadow"` thì coi như `model=None`. Đặt `n` = số factor, không tính `blocked_long` (vì nó đi kèm `blocked`); `overrun = model and model.predicted_finish and model.predicted_finish > deadline.at`.
    - **HIGH** khi: có `overdue`; hoặc `n ≥ 2`; hoặc `n == 1` và (`overrun` hoặc `p_delay ≥ p_high`).
    - **MED** khi: `n == 1`; hoặc `overrun`; hoặc `p_delay ≥ p_med`.
    - **LOW** trong các trường hợp còn lại.
    - Task `done` hoặc đã xoá luôn là LOW.

- [ ] **Step 1: Viết test**, mỗi id rule một test dương và một test âm, cộng:

```python
def test_overdue_alone_is_high(): assert aggregate([F("overdue")], None, DL, TH, "active") is Level.HIGH
def test_two_rules_high(): assert aggregate([F("blocked"), F("stagnant")], None, DL, TH, "active") is Level.HIGH
def test_blocked_long_not_double_counted(): assert aggregate([F("blocked"), F("blocked_long")], None, DL, TH, "active") is Level.MED
def test_one_rule_plus_overrun_high(): ...
def test_p_delay_alone_medium_never_high(): assert aggregate([], MS(p_delay=0.95), DL, TH, "active") is Level.MED
def test_shadow_mode_ignores_model(): assert aggregate([], MS(p_delay=0.95), DL, TH, "shadow") is Level.LOW
def test_done_issue_has_no_factors(): assert evaluate_rules(tl(status_category="done"), ...) == []
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt.**
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): dynamic rule signals and risk level aggregation"`

### Task 9: Pipeline đánh giá — ghi `scores` và `risk_state`

**Files:**
- Create: `erw/pipeline/evaluate.py`, `tests/test_evaluate.py`
- Modify: `erw/jobs.py` (gọi `on_synced`)

**Interfaces:**
- Consumes: Task 5, 7, 8.
- Produces:
  - `RiskChange(key: str, project: str, prev_level: Level | None, level: Level, is_new: bool, newly_blocked: bool, became_critical: bool)`
  - `project_stats(session, project) -> ProjectStats`: P75 thời gian lưu theo status, tính từ `changes` của các issue trong dự án. Cache trong process, tự hết hạn sau 1 giờ.
  - `latest_model_signals(session, key) -> ModelSignals | None`:
    - lấy `Score` mới nhất của `scorer="delay_t0"` (`value=p_delay`, `extra.predicted_duration_days`);
    - `predicted_finish = created_at + predicted_duration_days`;
    - lấy `Score` mới nhất của `scorer="criticality_t0"` (`value=score`, `is_critical`).
  - `evaluate_issue(session, key, now, settings, *, is_new=False) -> RiskChange | None` (trả `None` nếu issue không tồn tại):
    1. dựng timeline, xác định hạn, chạy rules, lấy model signals, tổng hợp mức;
    2. ghi `Score(scorer="rules_dynamic", value=float(level), level, deadline_type, deadline_at, factors=[asdict])`;
    3. upsert `RiskState`: `prev_level` = level cũ, `blocked = "blocked" in factor ids`, cùng `delay_value`, `crit_score`, `is_critical`.
    4. trả `RiskChange`, trong đó `newly_blocked` = trước đó không blocked và giờ blocked; `became_critical` = `is_critical` giờ là true và `RiskState` cũ chưa critical (hoặc chưa tồn tại).
  - `evaluate_all(session, now, settings) -> list[RiskChange]`: mọi issue chưa xoá thuộc dự án được theo dõi.
  - `on_synced(session, results: list[SyncResult], now, settings) -> list[RiskChange]`: đánh giá các key có kind `created` hoặc `updated`; key `deleted` thì xoá `RiskState`. Kết quả chuyển sang `pipeline.alerts.dispatch` (Task 10; trước đó là hàm rỗng).

- [ ] **Step 1: Viết test**

```python
def test_new_blocked_issue_creates_risk_state(session, settings): ...   # fixture issue_blocked → RiskState.blocked and level >= MED
def test_level_increase_tracked(session, settings): ...                 # lần 2 thêm overdue → prev_level MED, level HIGH
def test_resolved_issue_is_low_and_not_alerted(session, settings):
    ...  # issue status_category done → level LOW, factors == [] ; RiskChange.level LOW
def test_model_signals_used_only_in_active_mode(session, settings): ... # chèn Score delay_t0 p=0.95
def test_rules_score_appended_each_evaluation(session, settings): ...   # 2 lần evaluate → 2 Score rows
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt.**
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): evaluation pipeline writing scores and risk state"`

### Task 10: Cảnh báo Slack (prefix, chống trùng, giới hạn tốc độ)

**Files:**
- Create: `erw/integrations/slack.py`, `erw/pipeline/alerts.py`, `tests/test_slack_format.py`, `tests/test_alerts.py`

**Interfaces:**
- Consumes: `RiskChange` (Task 9), `RiskState`, `Issue`.
- Produces:
  - `AlertKind = Literal["risk_new","risk_up","blocked","critical","handled","digest"]`. Prefix tương ứng:
    - `risk_new` → `[Nguy cơ trễ]`;
    - `risk_up` → `[Tăng rủi ro]`;
    - `blocked` → `[Bị block]`;
    - `critical` → `[Quan trọng]`;
    - `handled` → `[Đã xử lý]`;
    - `digest` → `[Tổng hợp ngày]`.
  - `AlertSpec(kind, issue_key: str | None, project: str, level: Level | None, dedup_key: str)`.
  - `alerts_for(change: RiskChange) -> list[AlertSpec]`:
    - `is_new` và `level == HIGH` → `risk_new`;
    - không `is_new` và `level > prev_level` → `risk_up`;
    - `newly_blocked` → `blocked`;
    - `became_critical` → `critical`.

    `dedup_key = f"{kind}:{key}:{level.name}"` (với `blocked`: `f"blocked:{key}:{blocker_keys_sorted}"`).
  - `slack.escape(text) -> str`: thay `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`.
  - `slack.format_alert(spec, issue: Issue, rs: RiskState, settings) -> str`. Định dạng (SRS FR-S2):

    ```
    [Nguy cơ trễ][DEMO] <{jira}/browse/DEMO-1|DEMO-1> {escaped summary} · Cao{ " 81%" nếu delay_value} · {deadline label} · @{assignee_name or assignee_id or "chưa giao"}
    Lý do: {tối đa 3 factor: "label value", nối bằng "; "}
    <{web_base_url}/issues/DEMO-1|Mở trên Early Risk>
    ```

    Với `risk_up` và `critical`, người được @ là PM. Kế hoạch 1 chưa có bảng PM, nên dùng `settings.pm_name_by_project: dict[str,str]`; thiếu thì bỏ @PM.
  - `class SlackSender(url, *, http=None)`, phương thức `post(text) -> None`: POST `{"text": text}`; retry 3 lần nếu 429 hoặc 5xx.
  - `notify(session, spec, text, sender, now, max_per_hour) -> Literal["sent","duplicate","rate_limited","failed"]`:
    - `dedup_key` đã tồn tại thì trả `duplicate`;
    - số tin có `sent_at` trong 60 phút gần nhất ≥ `max_per_hour` thì lưu `status="rate_limited"` (không gửi);
    - ngược lại gửi, rồi lưu `status="sent"`.
  - `dispatch(session, changes, now, settings, sender) -> None`: với mỗi change, gọi `alerts_for` → `format_alert` → `notify`; sau đó cập nhật `RiskState.last_alerted_level`.

- [ ] **Step 1: Viết test**

```python
def test_format_escapes_slack_control_chars():
    t = format_alert(spec_new, issue(summary="Fix <b> & 🚀 lỗi đối soát"), rs_high, S)
    assert "&lt;b&gt; &amp; 🚀 lỗi đối soát" in t and t.startswith("[Nguy cơ trễ][DEMO]")

def test_format_contains_deadline_label_and_mention(): ...   # "Trễ sprint Sprint 24 (04/11)" và "@Nguyễn Văn An"
def test_no_percent_when_no_model_value(): ...
def test_alerts_for_level_up(): assert [a.kind for a in alerts_for(chg(prev=MED, lvl=HIGH))] == ["risk_up"]
def test_alerts_for_new_medium_is_silent(): assert alerts_for(chg(is_new=True, lvl=MED)) == []
def test_duplicate_alert_suppressed(session):
    assert notify(session, spec, "x", fake_sender, NOW, 20) == "sent"
    assert notify(session, spec, "x", fake_sender, NOW, 20) == "duplicate" and fake_sender.calls == 1
def test_rate_limit(session): ...   # max_per_hour=2, tin thứ 3 → "rate_limited"
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt** và nối `dispatch` vào `on_synced`.
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(erw): slack alerts with prefixes, dedup and rate limit"`

### Task 11: Lô model — đồng bộ DuckDB và chấm delay_t0, criticality_t0

**Files:**
- Create: `erw/ml/duckdb_sync.py`, `erw/ml/batch.py`, `tests/test_duckdb_sync.py`, `tests/test_batch.py`
- Modify: `erw/cli.py` (`erw run-batch`)

**Interfaces:**
- Consumes: ORM `Issue.raw`; `early_risk_detection.data.etl.transformer.JiraTransformer`, `...etl.loader.DuckDBLoader` (`init_schema`, `clear_instance`, `load_batch`); `DelayRiskScorer`, `CriticalityScorer`, `EmbeddingIndex`, `OllamaEmbedder`.
- Produces:
  - `to_dump_shape(raw: dict) -> dict`: chuyển JSON Jira Cloud v3 sang shape mà `normalize_doc` chấp nhận:
    - `fields.comment.comments` → `fields.comments`;
    - `fields.description` dạng ADF → chuỗi text, nối các node `text`;
    - giữ nguyên `changelog.histories` và `fields.issuelinks`.
  - `ensure_work_db(settings) -> Path`: nếu `work_duckdb` chưa tồn tại thì `shutil.copyfile(base_duckdb, work_duckdb)`. Không bao giờ ghi vào `base_duckdb`.
  - `sync_erw_instance(settings, raws: list[dict]) -> int`: `DuckDBLoader(work).clear_instance(settings.erw_instance)`, rồi `load_batch(JiraTransformer().transform_batch([to_dump_shape(r) for r in raws], settings.erw_instance))`; trả số issue.
  - `class Scorers(Protocol)`: `delay(db: str, keys: list[str]) -> pd.DataFrame`, `criticality(db: str, keys: list[str]) -> pd.DataFrame`. Implementation thật là `LibraryScorers(settings)`: nạp bundle một lần, `emb = EmbeddingIndex(emb_dir, fallback=OllamaEmbedder(f"{ollama_url}/api/embed"))`, criticality truyền `stream_dir=settings.stream_dir`.
  - `run_model_batch(session, settings, now, scorers: Scorers, *, unload_llm: Callable[[], None]) -> dict` (trả `{"n_issues", "delay_s", "crit_s"}`):
    1. Giữ `threading.Lock` toàn cục; nếu đang có lô khác chạy thì raise `BatchBusy`.
    2. Gọi `unload_llm()`. Implementation thật: `POST {ollama_url}/api/generate {"model": settings.llm_model, "keep_alive": 0}`; lỗi thì bỏ qua.
    3. `ensure_work_db`, `sync_erw_instance` (mọi issue chưa xoá).
    4. `keys = [f"ERW|{k}" for open issues]`.
    5. Chấm delay và ghi `Score(scorer="delay_t0", value=p_delay, extra={"predicted_duration_days", "is_at_risk"})`.
    6. Chấm criticality và ghi `Score(scorer="criticality_t0", value=score, is_critical, extra={"rank_in_instance"})`.
    7. Gọi `evaluate_all` rồi `dispatch`.
    8. Xoá thư mục `stream_dir` **trước** khi chấm criticality nếu số issue thay đổi so với lần trước (thư viện báo lỗi nếu `meta.n_issue` lệch).

- [ ] **Step 1: Viết test**

```python
def test_to_dump_shape_moves_comments_and_flattens_adf(): ...
def test_sync_erw_instance_replaces_rows(tmp_path):
    # tạo work db rỗng bằng DuckDBLoader.init_schema; sync 2 issue rồi sync 1 issue → issues WHERE instance='ERW' có đúng 1 dòng
def test_ensure_work_db_never_touches_base(tmp_path): ...   # mtime base không đổi
def test_batch_writes_scores_and_reevaluates(session, settings, tmp_path):
    fake = FakeScorers(delay=df(uid="ERW|DEMO-1", p_delay=0.7, predicted_duration_days=30, is_at_risk=True),
                       crit=df(uid="ERW|DEMO-1", score=0.9, is_critical=True, rank_in_instance=1))
    rep = run_model_batch(session, settings, NOW, fake, unload_llm=lambda: None)
    assert rep["n_issues"] == 1 and {s.scorer for s in session.query(Score)} >= {"delay_t0", "criticality_t0", "rules_dynamic"}
def test_batch_busy_when_locked(...): ...
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt.**
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Smoke test với thư viện thật.** Cần site demo đã có vài issue (từ Task 3) và `erw catch-up` đã chạy.
  Run: `.venv/bin/erw run-batch`
  Expected: in `n_issues ≥ 1` và thời gian chạy; bảng `scores` có hàng `delay_t0`, `criticality_t0`. So với ngưỡng từ kết quả S1 của người dùng; chưa có kết quả thì chỉ ghi lại số đo.
- [ ] **Step 6: Commit.** `git commit -m "feat(erw): daily model batch over working duckdb with ERW instance"`

### Task 12: Lịch chạy và digest 8:00

**Files:**
- Create: `erw/pipeline/digest.py`, `tests/test_digest.py`, `tests/test_scheduler.py`
- Modify: `erw/jobs.py` (thêm `start_scheduler(settings) -> BackgroundScheduler`), `erw/main.py` (startup và shutdown), `erw/cli.py` (`erw digest --dry-run`)

**Interfaces:**
- Consumes: `catch_up` (Task 6), `run_model_batch` (Task 11), `SlackSender`, `notify` (Task 10).
- Produces:
  - `build_digest(session, project, now, settings) -> str`:
    - **Dòng 1:** `[Tổng hợp ngày][{project}] {dd/MM}`.
    - **Dòng 2:** tiến độ sprint đang active:
      - `Tiến độ Sprint X: {done}% (kỳ vọng {expected}%)`;
      - `done` tính theo story points nếu ≥ 80% issue của sprint có story points, ngược lại đếm task;
      - `expected = (now − start)/(end − start)`, giới hạn trong 0..100%;
      - bỏ dòng này nếu không có sprint active.
    - **Dòng 3:** `Nguy cơ trễ: {n HIGH+MED} ({n tăng bậc 24h}) · Bị block: {n} · Mới 24h: {n} ({n critical})`.
    - **Tối đa 5 dòng task:** xếp theo `level DESC, crit_score DESC NULLS LAST`; mỗi dòng có link, summary đã escape, mức, nhãn hạn, @assignee.
    - **Dòng cuối:** `<{web_base_url}|Xem tất cả trên Early Risk>`.
  - Các job của scheduler (múi giờ `settings.tz`; `coalesce=True`, `max_instances=1`):
    - `batch_time` (06:45), thứ 2 đến thứ 6: `catch_up` → `run_model_batch`. Nếu lô lỗi hoặc `BatchBusy` thì ghi log và vẫn tiếp tục để digest dùng điểm cũ (SRS FR-P4);
    - `digest_time` (08:00), thứ 2 đến thứ 6: với mỗi dự án, gọi `notify(AlertSpec("digest", None, p, None, f"digest:{p}:{date}"))`.
  - Startup của app: `init_db` → nộp `catch_up` vào executor → `start_scheduler`. Shutdown: `scheduler.shutdown()`, `executor.shutdown(wait=True)`.

- [ ] **Step 1: Viết test**

```python
def test_digest_header_and_max_five_items(session, settings): ...   # 7 issue HIGH → đúng 5 dòng task
def test_digest_sprint_progress_story_points_vs_count(...): ...
def test_digest_without_active_sprint_omits_progress(...): ...
def test_scheduler_registers_jobs_in_tz(settings):
    s = start_scheduler(settings); ids = {j.id for j in s.get_jobs()}
    assert ids == {"morning_batch", "daily_digest"} and str(s.timezone) == "Asia/Ho_Chi_Minh"; s.shutdown()
def test_digest_sent_once_per_day(session, ...): ...   # chạy 2 lần → lần 2 trả "duplicate"
```
- [ ] **Step 2:** Chạy test. Expected: FAIL.
- [ ] **Step 3: Cài đặt.**
- [ ] **Step 4:** Chạy test. Expected: PASS.
- [ ] **Step 5: Smoke test end-to-end trên site demo.**
  - `uvicorn erw.main:create_app --factory --port 8000`, cùng ngrok domain tĩnh, và đã chạy `erw register-webhook`.
  - Trên Jira: tạo một issue có due date là hôm qua → trong khoảng ≤ 15 giây, kênh Slack có `[Nguy cơ trễ][DEMO] … Trễ due date …`.
  - Tạo link "is blocked by" → có `[Bị block]`.
  - `erw digest --dry-run` in ra digest.
  - Ghi độ trễ quan sát được vào `docs/superpowers/spikes/2026-11-02-s3-webhook.md`.
- [ ] **Step 6: Commit.** `git commit -m "feat(erw): scheduler for morning batch and daily slack digest"`

---

## Đối chiếu với spec (self-review)

| Yêu cầu | Task |
|---|---|
| FR-J1, J2 (đọc Jira, lịch sử), J5 (DuckDB schema), J6 (rate limit) | 5, 6, 11 |
| FR-J3 webhook; FR-J4 không polling + đồng bộ bù | 3, 6 |
| SRS 4.1 hạn; 4.4 bị block; 4.5 task mới | 7, 8, 12 |
| SRS 6.4 luật và tổng hợp; FR-V2 chế độ shadow | 8, 9 |
| FR-C1 criticality theo lô; 6.4a delay_t0 | 11 |
| FR-P2 ghi lại lượt chạy (rút gọn: báo cáo của `run-batch` + bảng `scores`); FR-P3 lịch sử điểm; FR-P4 lô lỗi vẫn gửi digest | 9, 11, 12 |
| FR-S1…S6 Slack (một kênh, prefix, @tên, digest ≤ 5 task, chống trùng, giới hạn mỗi giờ) | 10, 12 |
| MVP §8 spike S1–S2 (người dùng tự làm), S3 | 3 |
| **Kế hoạch sau:** 6.6 LLM, 6.7 action, 6.9 dashboard, 3 vai trò/auth, FR-DM2 seed, FR-DM3 sim-eval | 2/4, 3/4, 4/4 |
