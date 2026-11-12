# Thiết kế hệ thống — Early Risk Web

| | |
|---|---|
| Ngày | 2026-11-01 |
| Vai trò | Solution Architect |
| Trạng thái | Bản nháp chờ duyệt |
| Đầu vào | [Tài liệu yêu cầu](2026-11-01-web-quan-ly-tien-do-du-an-design.md) (gọi tắt **SRS**; các mã FR-xx tham chiếu tới đó) |
| Stack | Backend **Python**, Frontend **JavaScript** [Chốt] |
| Môi trường | Demo một máy: RTX 4060 Ti 16 GB, RAM 30 GB, 16 nhân; Jira Cloud gói free [Chốt] |

> **Ghi chú (2026-11-02):** đây là kiến trúc đích (TARGET). Bản POC/MVP đang triển khai theo [kiến trúc MVP](2026-11-01-early-risk-web-mvp-architecture.md): chỉ dùng webhook, không polling định kỳ, một process, SQLite.

Quy ước: **[Chốt]** là do product owner quyết; **[ADR-n]** là quyết định kiến trúc, có phân tích đánh đổi ở mục 12.

---

## 1. Tóm tắt kiến trúc

**Modular monolith bằng Python, chạy thành nhiều process** (API, worker I/O, worker GPU, scheduler), dùng chung một codebase và một PostgreSQL làm nguồn dữ liệu chính.

Các thành phần:
- **DuckDB** chỉ là kho đặc trưng cho mô hình. Chỉ worker GPU được mở nó.
- **Redis** làm broker hàng đợi, cache và pub/sub để đẩy cập nhật realtime xuống frontend.
- **Ollama** phục vụ LLM và embedding.
- **Frontend** là SPA React + Vite (JavaScript), nhận cập nhật realtime qua SSE.
- **Webhook từ Jira Cloud** vào qua tunnel ngrok, tới một cổng chỉ mở đúng một đường dẫn.

Ba nguyên tắc xuyên suốt:
1. **Inbox + reconcile:** mọi dữ liệu Jira vào hệ thống đều qua một bảng inbox idempotent, có lượt quét bù JQL định kỳ. Không phụ thuộc vào việc webhook đến đủ.
2. **Một nơi tính rủi ro:** `rules_dynamic`, giao diện bộ chấm và luật tổng hợp mức rủi ro là **hàm thuần** trên một `IssueTimeline`. Cùng một code chạy cho chế độ live, chế độ mô phỏng và việc sinh đặc trưng cho model `delay_anytime`.
3. **GPU là tài nguyên tuần tự:** mọi tác vụ GPU đi qua một hàng đợi có concurrency = 1, và LLM được giải phóng khỏi VRAM trước lượt replay criticality.

## 2. Yêu cầu dẫn dắt kiến trúc

| # | Yêu cầu | Nguồn | Hệ quả kiến trúc |
|---|---|---|---|
| D1 | Cảnh báo theo sự kiện ≤ 5 phút | SRS §7 | Pipeline bất đồng bộ; cần worker chấm điểm có cache nóng (§7.3) |
| D2 | Bản tổng hợp 8:00 cần criticality replay toàn bộ sự kiện | K1, FR-C1 | Lịch lô theo chuỗi 06:30 → 08:00 (§7.5) |
| D3 | Thư viện nạp toàn bộ DuckDB 2,68 triệu issue mỗi lần `score()` | `delay/scorer.py:88`, `criticality/scorer.py:66` | Worker GPU sống lâu, giữ trạng thái; gom micro-batch; phải spike đo RAM và thời gian (§13) |
| D4 | 16 GB VRAM dùng chung cho LLM, embedding và replay | SRS §7 | Hàng đợi GPU tuần tự; `keep_alive=0` khi chuyển tác vụ |
| D5 | Không ghi Jira khi PM chưa xác nhận; ghi bằng OAuth của PM; kiểm tra xung đột | FR-A2…A4 | Action là máy trạng thái có optimistic concurrency theo `updated` của Jira |
| D6 | Dữ liệu demo không có lịch sử; cần chế độ mô phỏng | SRS §9b | Thiết kế "workspace" (live hoặc sim) và đồng hồ `as_of` có ở mọi tầng |
| D7 | Dữ liệu Jira và LLM chạy nội bộ | FR-L1 | Mọi thứ trong docker-compose trên một máy; chỉ mở endpoint webhook |
| D8 | Thay được bộ chấm mà không sửa lõi | FR-P/6.3 | Scorer registry và plugin interface, có chế độ chạy bóng |

## 3. Sơ đồ thành phần

```
                         ┌───────────────────────── Máy demo (docker compose) ─────────────────────────┐
 Jira Cloud ──webhook──▶ │ ngrok ─▶ [gateway :8081]  chỉ cho POST /webhooks/jira                      │
    ▲   ▲                │                  │                                                        │
    │   │ REST/JQL       │                  ▼                                                        │
    │   └────────────────│──── worker-io (Celery: sync, rules, llm-orchestr., notify, jira-write)     │
    │  OAuth 3LO (PM)    │        │   ▲            │                    │                            │
    └────────────────────│────────┘   │ queue      │ HTTP               │ chat.postMessage ──────────│──▶ Slack
                         │            │            ▼                    │                            │
 Trình duyệt ──HTTPS──▶  │ [nginx :443] ─▶ api (FastAPI, uvicorn)  Ollama (LLM + embed, GPU)          │
   SPA React (JS)        │   static FE     │  ▲  SSE                    ▲                            │
                         │                 │  │                         │                            │
                         │                 ▼  │ pub/sub                 │                            │
                         │   PostgreSQL ◀──┴──┴── Redis (broker, cache, pub/sub, debounce)            │
                         │       ▲                    │                                              │
                         │       │                    ▼ queue "gpu" (concurrency 1)                  │
                         │       └──────────── worker-gpu (Celery) ── DuckDB (feature store)         │
                         │                      early_risk_detection: delay_t0, criticality_t0,      │
                         │                      (delay_anytime)  + bundles/                          │
                         │   beat (Celery beat: lịch lô, reconcile, digest)                          │
                         └────────────────────────────────────────────────────────────────────────────┘
```

| Process | Trách nhiệm | Scale demo |
|---|---|---|
| `gateway` | Nhận webhook, xác thực secret, ghi `webhook_inbox`, trả 202 trong < 200 ms. Không chứa logic nghiệp vụ. | 1 |
| `api` | REST `/api/v1`, SSE, auth, RBAC. Phục vụ dashboard; không gọi Jira hay LLM đồng bộ (trừ OAuth callback). | 1 (2 worker uvicorn) |
| `worker-io` | Queue `ingest`, `rules`, `llm`, `notify`, `jira_write`: các tác vụ I/O-bound. | 1 process, concurrency 4 |
| `worker-gpu` | Queue `gpu`: chấm model, xây event stream, embedding batch. Giữ trạng thái nóng. | 1 process, concurrency **1** |
| `beat` | Lên lịch (§7.5). | 1 |
| `ollama` | LLM + `nomic-embed-text`. | container có sẵn |
| `postgres`, `redis`, `nginx`, `ngrok` | Hạ tầng. | 1 mỗi loại |

## 4. Tech stack

### 4.1 Backend (Python 3.13, cùng phiên bản với bundle)

| Lớp | Chọn | Lý do |
|---|---|---|
| Web framework | **FastAPI** + Uvicorn | Async, tự sinh OpenAPI, Pydantic v2 |
| Validation, schema | **Pydantic v2** | Dùng chung cho API, JSON schema của LLM và cấu hình |
| ORM, migration | **SQLAlchemy 2.0** (async, psycopg 3) + **Alembic** | Chuẩn, hỗ trợ JSONB và partial index |
| Hàng đợi, lịch | **Celery 5** + **Redis 7**, Celery beat | Routing queue riêng (`gpu` concurrency 1), retry/backoff, chain/chord cho pipeline lô; đội phổ biến [ADR-3] |
| HTTP client | **httpx** (async + sync) | Gọi Jira, Slack, Ollama; có retry riêng (tenacity) |
| OAuth | **Authlib** | Atlassian OAuth 2.0 (3LO), refresh token |
| Slack | **slack_sdk** (`WebClient.chat_postMessage`, Block Kit) | Bot token, một kênh |
| LLM | **Ollama** HTTP API, tham số `format` = JSON schema (structured outputs) | Đã có trên máy; nạp và giải phóng model qua `keep_alive` [ADR-6] |
| ML | `early_risk_detection` (repo này, cài editable), torch CUDA, xgboost, catboost, duckdb | Tái sử dụng nguyên thư viện |
| Mã hoá secret | `cryptography` (Fernet), khoá lấy từ biến môi trường | Mã hoá token Jira, Slack, OAuth khi lưu |
| Log, metric | **structlog** (JSON), **prometheus-client**; Flower để xem Celery | §10 |
| Kiểm thử | pytest, pytest-asyncio, respx (giả lập HTTP), testcontainers-postgres | |
| Chất lượng code | ruff, mypy (chế độ dần dần) | Giống repo |

### 4.2 Frontend (JavaScript)

| Lớp | Chọn | Lý do |
|---|---|---|
| Build | **Vite** | Nhanh, cấu hình ít |
| UI | **React 18** (JavaScript, JSDoc để gợi ý kiểu) | Phổ biến, hệ sinh thái lớn |
| Component | **Mantine 7** | Đủ component cho dashboard (Table, Drawer, Badge, Notifications), có dark mode, dễ theme theo nguyên tắc FR-D7 |
| Data fetching | **TanStack Query** | Cache và invalidate khi nhận sự kiện SSE |
| Routing | **React Router** | |
| Biểu đồ | **Apache ECharts** (`echarts-for-react`) | Burndown, ma trận, sparkline; hiệu năng tốt |
| i18n | **i18next** + react-i18next | vi/en (FR-L1b) |
| Form | Mantine Form | Panel sửa action |
| Realtime | `EventSource` (SSE) | Một chiều server → client là đủ [ADR-5] |
| Kiểm thử | Vitest + Testing Library; Playwright cho luồng E2E | |

### 4.3 Hạ tầng
Docker Compose; NVIDIA Container Toolkit cho `worker-gpu` và `ollama`; nginx (TLS self-signed hoặc mkcert); ngrok (container đã có) với **domain tĩnh** để URL webhook không đổi khi khởi động lại.

## 5. Cấu trúc repo đề xuất

```
tgn/
  src/early_risk_detection/        # thư viện ML hiện có (giữ nguyên, bổ sung API warm-state §7.3)
  webapp/
    backend/
      pyproject.toml               # package `erw` (early-risk-web), phụ thuộc early-risk-detection
      erw/
        api/                       # FastAPI routers, deps (auth, rbac), SSE
        gateway/                   # app webhook tối giản
        domain/                    # thuần Python, không I/O
          timeline.py              # IssueTimeline: dựng trạng thái tại as_of từ changelog
          deadline.py              # thứ tự due date → sprint → release → SLA (SRS 4.1)
          rules.py                 # rules_dynamic (SRS 6.4)
          risk.py                  # luật tổng hợp mức Cao/TB/Thấp
          scorers.py               # Scorer protocol + registry
          actions.py               # danh mục action, validate params
        integrations/
          jira/                    # client REST, mapping → model nội bộ, OAuth
          slack/                   # formatter prefix, sender
          llm/                     # prompt builder, schema, validator, grounding check
        ml/                        # adapter gọi early_risk_detection, DuckDB sync, warm state
        tasks/                     # Celery tasks theo queue
        db/                        # SQLAlchemy models, repositories, alembic/
        sim/                       # workspace mô phỏng, đồng hồ ảo
        settings.py
      tests/
    frontend/
      package.json, vite.config.js
      src/{app,pages,components,features/{dashboard,issue-panel,admin,sim},api,i18n,theme}
    deploy/
      docker-compose.yml, nginx.conf, ngrok.yml, .env.example
    scripts/
      seed_demo.py                 # FR-DM2
```

## 6. Mô hình dữ liệu (PostgreSQL)

### 6.1 Nguyên tắc
- Mọi bảng nghiệp vụ có cột `workspace_id`. Workspace thuộc một trong hai loại: `live` (site Jira demo) hoặc `sim` (mô phỏng một dự án công khai). Cách này **cô lập dữ liệu mô phỏng** mà không phải nhân đôi schema (D6).
- Lưu cả dữ liệu Jira thô (`raw JSONB`) lẫn các cột đã chuẩn hoá cần cho truy vấn.
- Điểm số là **append-only** (`score_snapshots`). Trạng thái hiện tại nằm ở `issue_risk_state` để dashboard đọc nhanh.

### 6.2 Các bảng chính

```
workspaces(id, kind: live|sim, name, jira_site_url, source_instance, source_project,  -- sim: dự án công khai
           clock_as_of NULL,   -- sim: đồng hồ ảo
           settings JSONB)     -- giờ làm việc, tz, giờ digest, ngưỡng mặc định

users(id, email, display_name, locale, auth_kind: atlassian|local, password_hash NULL, is_admin, active)
atlassian_accounts(user_id PK, account_id, access_token_enc, refresh_token_enc, expires_at, scopes)
project_members(workspace_id, project_key, user_id, role: pm|viewer)       -- RBAC theo dự án

jira_connections(workspace_id PK, site_url, cloud_id, service_email, api_token_enc,
                 webhook_id, webhook_secret_enc, last_reconcile_at)

projects(workspace_id, key, name, tracked, status_map JSONB, thresholds JSONB, pm_user_id)
issues(workspace_id, key, id_jira, project_key, summary, description_excerpt, issuetype, priority,
       status, status_category, assignee_account_id, assignee_name, reporter_account_id,
       duedate, story_points, created_at, updated_at_jira, resolved_at, lang (vi|en|mixed),
       raw JSONB, synced_at,  PK(workspace_id, key))
issue_changelog(workspace_id, issue_key, change_id, item_idx, author, at, field, from_val, to_val,
                PK(workspace_id, issue_key, change_id, item_idx))
issue_links(workspace_id, link_id, source_key, target_key, type_raw, type_std, direction, created_seen_at)
issue_comments(workspace_id, issue_key, comment_id, author, at, body_excerpt)
sprints(workspace_id, id, board_id, name, state, start_at, end_at, complete_at)
issue_sprints(workspace_id, issue_key, sprint_id, added_at, removed_at)     -- dựng lại từ changelog
versions(workspace_id, id, project_key, name, release_date, released)
issue_versions(workspace_id, issue_key, version_id)

webhook_inbox(id, workspace_id, received_at, event_type, issue_key, dedup_key UNIQUE, payload JSONB,
              status: new|processed|failed, attempts, error)
sync_cursors(workspace_id, kind, value)

scorer_registry(id, kind: delay|criticality, impl, version, bundle_sha, mode: off|shadow|active,
                thresholds JSONB, eval_report JSONB)
scoring_runs(id, workspace_id, trigger: batch|event|sim, as_of, scorer_ids[], started_at, finished_at,
             n_issues, status, error)
score_snapshots(id, run_id, workspace_id, issue_key, scorer_id, as_of, value, level, is_critical,
                rank_in_project, deadline_type, deadline_at, factors JSONB)       -- append-only
issue_risk_state(workspace_id, issue_key PK, level, prev_level, level_changed_at, delay_value,
                 crit_score, is_critical, deadline_type, deadline_at, blocked, factors JSONB,
                 last_alerted_level, snoozed_until_level, handled_at, updated_at)

llm_suggestions(id, workspace_id, issue_key, run_id, model, prompt_hash, input JSONB, output_raw TEXT,
                output JSONB, valid bool, rejection_reason, lang, created_at, issue_updated_at_seen)
action_requests(id, suggestion_id NULL, workspace_id, issue_key, created_by, status:
                draft|confirmed|executing|done|partial|conflict|failed|dismissed,
                expected_issue_updated_at, created_at, confirmed_at)
action_items(id, request_id, type, params_suggested JSONB, params_final JSONB, origin: llm|pm,
             outcome: verbatim|edited|added|skipped, jira_status, jira_response JSONB, executed_at)

notifications(id, workspace_id, kind, prefix, project_key, issue_key NULL, dedup_key, payload JSONB,
              status: pending|held|sent|failed|suppressed, scheduled_for, sent_at, slack_ts)
audit_log(id, at, actor, action, target, detail JSONB)                         -- không UPDATE/DELETE
```

Index chính:
- `issue_risk_state(workspace_id, level DESC, crit_score DESC)` cho danh sách "Cần xử lý";
- `score_snapshots(workspace_id, issue_key, as_of)`;
- `notifications(status, scheduled_for)`;
- `webhook_inbox(status, received_at)`;
- partial index `issues(workspace_id, project_key) WHERE resolved_at IS NULL`.

Quyền: role DB của ứng dụng chỉ có `INSERT` trên `audit_log`.

### 6.3 DuckDB (kho đặc trưng của worker-gpu)
- `data/jira.duckdb`: nền công khai 2,68 triệu issue, chỉ đọc. Không bao giờ ghi vào file này.
- `var/erw_scoring.duckdb`: **bản làm việc** do `worker-gpu` sở hữu độc quyền [ADR-2]:
  - Tạo một lần bằng cách copy nền, cộng thêm cột hoặc bảng mở rộng (FR-J5).
  - Đầu mỗi job chấm, xoá rồi chèn lại các dòng của instance `ERW_<workspace>` từ Postgres. Dữ liệu demo nhỏ nên mất vài giây.
  - Không process nào khác mở file này. Nhờ vậy tránh được giới hạn một-ghi-nhiều-đọc giữa các process của DuckDB.
- Embedding: `EmbeddingIndex("data", fallback=OllamaEmbedder())` như README. Embedding của issue demo được cache trong `var/emb_erw.parquet`, khoá theo (key, hash văn bản).
- Event stream của criticality: `var/stream/<hash>`. Xây lại khi số issue thay đổi; thư viện kiểm tra `meta.n_issue` và báo lỗi nếu lệch.

## 7. Luồng xử lý chính

### 7.1 Ingest: webhook → inbox → đồng bộ chuẩn
```
Jira ─POST─▶ gateway: verify secret (header/URL token, so sánh hằng thời gian)
             → INSERT webhook_inbox ON CONFLICT(dedup_key) DO NOTHING → 202
             → celery: ingest.process_inbox(id)                       [queue ingest]
worker-io:   GET /rest/api/3/issue/{key}?expand=changelog (+ sprint, version, link fields)
             → upsert issues/changelog/links/sprints/versions (idempotent theo id)
             → rebuild issue_sprints từ changelog Sprint
             → celery: rules.evaluate(issue_key) ; nếu issue_created → gpu.enqueue_t0(issue_key)
```
- `dedup_key` = hash(`webhookEvent`, `issue.id`, `timestamp`, `changelog.id`).
- **Không tin nội dung payload webhook.** Payload chỉ dùng làm tín hiệu "có thay đổi", sau đó luôn lấy lại bản chuẩn từ REST. Tránh được các trường hợp payload thiếu dữ liệu hoặc đến sai thứ tự.
- **Reconcile** (beat, mỗi 10 phút): JQL `project in (tracked) AND updated >= "<cursor - 2m>"` (chồng lấn 2 phút), phân trang, đẩy cùng tác vụ upsert. Thêm lượt quét sprint và version của các board đang theo dõi.
- **Rate limit:** client Jira tôn trọng `Retry-After`, backoff luỹ thừa có jitter, token bucket chung trong Redis.
- **Bootstrap:** tác vụ tuần tự theo dự án, lưu cursor để tiếp tục được nếu bị ngắt giữa chừng.

### 7.2 Đánh giá rủi ro theo sự kiện (≤ 5 phút)
```
rules.evaluate(key):    timeline = IssueTimeline.build(issue, changelog, sprints, versions, links, as_of=now)
                        deadline = resolve_deadline(timeline)            -- SRS 4.1
                        signals  = rules_dynamic(timeline, project_stats)
                        model    = latest active snapshots (delay_t0, criticality_t0, [delay_anytime])
                        level    = aggregate(signals, model, thresholds)  -- SRS 6.4
                        → INSERT score_snapshots(scorer=rules_dynamic) ; UPSERT issue_risk_state
                        → nếu level tăng bậc || vừa bị block || task mới level Cao/critical:
                              notify.enqueue(kind, dedup_key=(issue, kind, level))
                              llm.enqueue(issue)                          -- ưu tiên cao
                        → redis PUBLISH ws:{workspace} {"type":"risk","issue":key}  → SSE
```
`project_stats` (P75 thời gian lưu theo trạng thái, theo dự án) được tính mỗi đêm và cache trong Redis.

### 7.3 Chấm model và worker GPU có trạng thái nóng
Vấn đề D3: mỗi lần `score()` thư viện phải `load_issues_t0` cho 2,68 triệu issue, chạy `chronological_features` toàn bộ (mô phỏng tải O(N)), rồi dựng cổng ngữ nghĩa kNN. Làm vậy cho từng webhook là không khả thi.

Thiết kế:
1. **Gom micro-batch:** `gpu.enqueue_t0(key)` chỉ ghi key vào Redis set `pending_t0:{ws}`. Một tác vụ debounce chạy mỗi **2 phút** (hoặc khi set đủ 20 key) sẽ gom và chấm một lần với `issue_keys=[...]`.
2. **Mở rộng thư viện để giữ trạng thái nóng** (thay đổi trong `src/early_risk_detection`, bảo đảm tương thích ngược):
   ```python
   state = DelayRiskScorer.prepare(duckdb_path, embeddings)     # nạp df, links, base features một lần
   state.refresh(new_or_changed_rows)                           # chỉ tính lại phần đuôi theo thời gian
   scorer.score_prepared(state, issue_keys=[...])
   ```
   Có thể làm vậy vì đặc trưng T0 của issue i chỉ phụ thuộc vào các sự kiện **trước** `created_i`. Thêm issue demo mới (ở cuối dòng thời gian) không làm đổi đặc trưng của issue cũ, nên `refresh` chỉ cần tính lại phần đuôi. Worker giữ `state` trong RAM suốt vòng đời process.
3. **Phương án dự phòng** nếu spike S1 (§13) cho thấy `prepare` vượt RAM hoặc chưa kịp làm: chấm cả lô với `issue_keys` mỗi 5 phút. Khi đó mục tiêu 5 phút chỉ còn đúng cho tín hiệu luật, còn điểm model đến ở lượt sau. **Đây là lý do cảnh báo theo sự kiện được thiết kế để dựa trên luật trước** (§7.2), điểm model chỉ là phần bổ sung.
4. **Criticality** không chạy theo sự kiện (SRS K2). Lô hằng ngày luôn chạy; có thể thêm lô mỗi giờ trong giờ làm việc nếu S1 cho thấy replay ≤ 3 phút.
5. **Kỷ luật VRAM:** trước tác vụ replay hoặc chấm, worker gọi Ollama `POST /api/generate {"model": X, "keep_alive": 0}` để giải phóng LLM. Queue `llm` bị **tạm dừng** (cờ Redis `gpu_busy`) cho tới khi job GPU xong. Sau đó `torch.cuda.empty_cache()`.

### 7.4 LLM: giải thích và đề xuất
```
llm.suggest(issue): ctx = build_context(issue)   # SRS FR-L2: cắt độ dài, ≤ N comment, factors có id
                    prompt = template[lang](ctx, action_catalog, schema)
                    out = ollama.chat(model, messages, format=SuggestionSchema.model_json_schema(),
                                      options={temperature: 0.2, num_ctx: 8192})
                    validate: pydantic parse → mọi citation ∈ ctx.factor_ids ∪ ctx.field_ids
                              → action.type ∈ catalog, params hợp lệ (assignee ∈ project members,
                                sprint ∈ sprint mở, ngày ≥ hôm nay)
                    sai → retry 1 lần kèm thông báo lỗi; vẫn sai → valid=false, UI "chưa có đề xuất"
                    → INSERT llm_suggestions(issue_updated_at_seen = issue.updated_at_jira)
```
`SuggestionSchema` (rút gọn):
```json
{"explanation":[{"text":"...", "cites":["f:stagnant_status","fld:status"]}],
 "actions":[{"type":"comment|reassign|change_priority|move_sprint|change_duedate|add_link|add_label|flag",
             "params":{}, "rationale":"...", "cites":["f:blocked"], "confidence":0.0}],
 "advice":[{"text":"...", "cites":[]}]}
```
- **Grounding check:** mọi câu phải có ít nhất 1 trích dẫn hợp lệ (`cites`), và mọi con số xuất hiện trong `text` phải có trong dữ liệu đầu vào (kiểm tra bằng regex).
- **Ngôn ngữ:** phát hiện ngôn ngữ task (heuristic dấu tiếng Việt, hoặc fastText `lid.176`) và lưu vào `issues.lang`. Giải thích viết theo locale của người xem; comment ghi Jira mặc định theo `issues.lang`.
- **Thông lượng ước tính:** model 7–8B Q4 trên RTX 4060 Ti đạt khoảng 40–60 token/s, khoảng 400 token đầu ra mỗi task, tức khoảng 8–10 giây mỗi task. Lô sáng 3 dự án × 10 task ≈ 5 phút.

### 7.5 Lô hằng ngày (Celery chain theo từng workspace)
| Giờ | Bước | Queue |
|---|---|---|
| 06:30 | Reconcile đầy đủ và cập nhật `project_stats` | ingest |
| 06:45 | Giải phóng LLM → đồng bộ DuckDB → `delay_t0` (mọi task mở) → build stream → `criticality_t0` → chạy bóng `delay_anytime` | gpu |
| 07:30 | `rules.evaluate_all` → tổng hợp mức → so với hôm qua | rules |
| 07:35 | `llm.suggest` cho top N "Cần xử lý" chưa có đề xuất còn hiệu lực | llm |
| 08:00 | `notify.digest` (một tin cho mỗi dự án) | notify |

Mỗi bước có hạn chót mềm. Nếu bước GPU trễ quá 07:50, digest vẫn được gửi bằng điểm của lần chạy trước, kèm ghi chú "điểm mô hình cập nhật lúc …" (FR-P4).

### 7.6 Thực hiện action lên Jira
```
POST /api/v1/actions/{id}/confirm  {items:[...params_final], expected_issue_updated_at}
api:     RBAC (PM của project) → status=confirmed → enqueue jira_write.execute(id)
worker:  token = refresh_if_needed(PM's atlassian_account)
         current = GET issue (fields=updated)
         nếu current.updated != expected → status=conflict, lưu diff, PUBLISH → UI yêu cầu xem lại
         else lần lượt từng item (idempotency key = action_item.id, lưu trong comment property / label):
              comment  → POST /issue/{key}/comment
              reassign → PUT /issue/{key}/assignee
              priority/duedate/labels → PUT /issue/{key} (fields)
              move_sprint → POST /rest/agile/1.0/sprint/{id}/issue
              add_link → POST /issueLink
              flag     → PUT fields (customfield Flagged)
         → item.jira_status ; request.status = done|partial|failed
         → audit_log ; notify [Đã xử lý] ; ingest lại issue ; rules.evaluate
```
Máy trạng thái của `action_requests`:
`draft → confirmed → executing → done | partial | failed | conflict`, cộng `draft → dismissed`.

Nếu worker chết giữa chừng, khi khởi động lại nó quét các bản ghi `executing` quá 10 phút và tiếp tục từ các item chưa có `executed_at`.

### 7.7 Thông báo Slack
- `notify.enqueue` ghi vào `notifications` với `dedup_key`. Nếu trong 24 giờ đã có bản ghi `sent` cùng `dedup_key` thì đánh dấu `suppressed`.
- **Debounce và gộp:** tác vụ `notify.flush` chạy mỗi phút. Tin cùng `kind` và `project` trong cửa sổ 15 phút được gộp thành một tin Block Kit.
- **Giờ làm việc:** ngoài giờ thì chuyển sang `held` với `scheduled_for` là đầu giờ làm việc kế tiếp. Có giới hạn tốc độ X tin mỗi giờ (token bucket trong Redis).
- **Định dạng** (FR-S2): `[Nguy cơ trễ][PAY] PAY-812 Tích hợp VNPay · Cao 81% · Trễ sprint 24 (04/11) · @Nguyễn Văn An`, cộng dòng lý do và hai nút link (Jira, web). Ở workspace sim, thêm prefix `[MÔ PHỎNG]`.
- Lớp `Notifier` là một protocol (`send(message) -> ref`). `SlackNotifier` là implementation đầu tiên (FR-S7).

### 7.8 Chế độ mô phỏng
- **Tạo workspace `sim`:** chọn `instance` + `project` công khai và ngày bắt đầu. Hệ thống nạp dữ liệu dự án đó từ `data/jira.duckdb` vào các bảng Postgres với `workspace_id = sim`. Các bảng sprint và version lấy từ ETL mở rộng.
- **Đồng hồ ảo:** `workspaces.clock_as_of`. Mọi truy vấn của dashboard đọc dữ liệu **tại `as_of`**: `IssueTimeline.build(..., as_of)` chỉ dùng changelog có `at ≤ as_of`; task được coi là "mở" nếu `created ≤ as_of < resolved`.
- **Tua ngày:** `POST /sim/{id}/advance?days=1` chạy cùng chuỗi lô ở §7.5 với `as_of` mới. Model chấm qua `score(..., as_of=...)`, thư viện đã hỗ trợ sẵn tham số này.
- **Không ghi Jira.** `jira_write` từ chối với workspace sim; action chỉ được ghi nhật ký.
- **Đánh giá** (FR-V1): tác vụ `sim.evaluate(range)` chạy nhanh không qua UI. Với mỗi ngày trong khoảng, chấm và so với kết quả thật. Kết quả lưu vào `scorer_registry.eval_report`, gồm precision/recall ở mức Cao, PR-AUC, lead time, và tách theo `lang`.

## 8. Giao diện bộ chấm (plugin)

```python
class Scorer(Protocol):
    id: str; kind: Literal["delay", "criticality"]; version: str
    needs_gpu: bool; supports_event: bool
    def score(self, ctx: ScoringContext, issue_keys: list[str] | None, as_of: datetime) -> list[ScoreResult]: ...

@dataclass
class ScoreResult:
    issue_key: str; value: float; level: Level | None; is_critical: bool | None
    deadline_type: DeadlineType | None; deadline_at: datetime | None
    factors: list[Factor]          # Factor(id, label_key, value, direction, source)
```
- `ScoringContext` cung cấp đường dẫn DuckDB, trạng thái nóng, embedder, workspace, và tập `IssueTimeline` (cho bộ chấm luật hoặc `delay_anytime`).
- Registry đọc `scorer_registry`. `mode = shadow` thì vẫn chấm và lưu snapshot nhưng `risk.aggregate` bỏ qua. `mode = active` thì tham gia tổng hợp.
- Ngưỡng của từng scorer và từng dự án lấy từ `thresholds` JSONB.
- Model `delay_anytime` (nhánh model song song) chỉ cần cài protocol này và đóng bundle theo chuẩn `ModelBundle`. Web không phải sửa gì.

## 9. API (REST `/api/v1`, JSON, cookie session)

| Nhóm | Endpoint chính |
|---|---|
| Auth | `GET /auth/atlassian/login`, `GET /auth/atlassian/callback`, `POST /auth/local/login`, `POST /auth/logout`, `GET /me` |
| Dashboard | `GET /workspaces/{ws}/projects/{p}/summary?sprint=` (4 KPI + tiến độ), `GET /workspaces/{ws}/projects/{p}/queue?tab=all\|risk\|blocked\|new\|handled&cursor=` |
| Issue | `GET /issues/{ws}/{key}` (trạng thái, factors, deadline), `GET /issues/{ws}/{key}/scores?from=` (xu hướng), `GET /issues/{ws}/{key}/suggestion`, `POST /issues/{ws}/{key}/suggestion:regenerate` |
| Action | `POST /issues/{ws}/{key}/actions` (tạo draft từ suggestion hoặc thủ công), `PATCH /actions/{id}`, `POST /actions/{id}/confirm`, `POST /actions/{id}/dismiss`, `GET /actions/{id}` |
| Overview | `GET /workspaces/{ws}/projects/{p}/overview` (burndown, phân bố, ma trận, tải), `GET /workspaces/{ws}/effectiveness` |
| Admin | `PUT /admin/jira-connection`, `POST /admin/jira-connection:test`, `POST /admin/bootstrap`, `PUT /admin/slack`, `GET/PUT /admin/projects/{p}`, `GET/POST/PATCH /admin/users`, `GET/PATCH /admin/scorers/{id}`, `GET /admin/health` |
| Sim | `POST /sim` (tạo), `POST /sim/{id}/advance`, `POST /sim/{id}/evaluate`, `GET /sim/{id}/report` |
| Realtime | `GET /stream?ws=` (SSE): `risk`, `suggestion`, `action`, `sync`, `run` |
| Webhook (gateway) | `POST /webhooks/jira/{workspace_token}` |

Quy ước chung:
- Lỗi theo RFC 7807 (`application/problem+json`).
- Phân trang bằng cursor.
- Mọi lệnh ghi đều có `Idempotency-Key`.
- RBAC qua dependency `require_role(project, "pm")`.
- OpenAPI được sinh tự động. Frontend dùng client sinh từ OpenAPI (`openapi-fetch` hoặc `orval`) để không lệch hợp đồng.

## 10. Bảo mật, vận hành, quan sát

**Bảo mật**
- **Bề mặt mở ra ngoài:** chỉ `gateway` qua ngrok. nginx chặn mọi đường dẫn khác ở cổng tunnel. `workspace_token` trong URL dài 32 byte ngẫu nhiên, cộng thêm secret riêng để kiểm tra.
- **Secret:** `.env` (không commit) chứa `ERW_FERNET_KEY`, `SLACK_BOT_TOKEN`, Atlassian client id/secret. Token trong DB được mã hoá Fernet.
- **Session:** cookie `HttpOnly`, `Secure`, `SameSite=Lax`; session lưu ở Redis; CSRF double-submit cho mọi lệnh ghi.
- **OAuth scopes** (tối thiểu): `read:jira-work write:jira-work read:jira-user offline_access`, cộng scope agile để chuyển sprint.
- **Prompt injection:** nội dung task được bọc trong khối dữ liệu, có chỉ dẫn hệ thống. Quan trọng hơn: LLM **không có quyền gọi công cụ nào**, mọi action phải qua validator và qua bước PM xác nhận. Vì vậy prompt injection tệ nhất chỉ làm ra một đề xuất xấu, và PM thấy được nó.

**Vận hành**
- `docker compose up` khởi động toàn bộ. `make bootstrap` chạy migration, tạo admin, copy DuckDB làm việc.
- **Sao lưu:** `pg_dump` hằng đêm. Bundle và DuckDB nền là bất biến.
- **Healthcheck:** API `/healthz`; worker tự ghi heartbeat vào Redis. Trang `GET /admin/health` (FR-M4) tổng hợp: webhook gần nhất, độ trễ inbox, lượt reconcile, lượt chạy GPU, trạng thái Ollama, lỗi gửi Slack.

**Quan sát**
- **Log:** structlog JSON có `trace_id` đi xuyên webhook → task → notification.
- **Metric** (Prometheus):
  - `erw_event_to_alert_seconds` (histogram, đo trực tiếp D1);
  - `erw_inbox_lag_seconds`;
  - `erw_gpu_job_seconds{kind}`;
  - `erw_llm_valid_ratio`;
  - `erw_notifications_total{kind,status}`;
  - `erw_jira_api_errors_total{code}`.
- Flower để xem Celery.

## 11. Ước lượng tải và tài nguyên (demo)

| Hạng mục | Ước lượng | Ghi chú |
|---|---|---|
| Issue live | 2–3 dự án × 50–150 = 150–450 | Không đáng kể |
| Webhook | < 1 sự kiện/giây khi demo | Inbox chịu được dư |
| Postgres | < 1 GB (live) + 1–3 GB mỗi workspace sim | Lấy một dự án lớn của Apache/RedHat |
| RAM worker-gpu | **chưa biết**: df 2,68 triệu dòng + base features | Spike S1; dự kiến 8–15 GB. Ngân sách: Postgres 2 GB, Redis 0,5 GB, Ollama CPU-side 2 GB, API/worker-io 2 GB |
| VRAM | LLM 7–8B Q4 ≈ 5–6 GB + nomic ≈ 0,6 GB; replay TGN: chưa đo | Tuần tự hoá (§7.3.5) |
| Thời gian replay criticality | ≈ 1,5 phút / 2,68 triệu issue (README) | Cộng thời gian build stream khi số issue đổi: spike S1 |
| LLM | ≈ 8–10 giây mỗi task | Lô sáng ≈ 5 phút |

## 12. Quyết định kiến trúc và đánh đổi

| ADR | Quyết định | Phương án thay thế | Vì sao chọn | Cái giá phải trả |
|---|---|---|---|---|
| 1 | **Modular monolith**, nhiều process, một codebase | Microservices | Đội nhỏ, một máy, cần ra demo nhanh; ranh giới module (`domain`, `integrations`, `ml`) giữ được khả năng tách sau | Một lần deploy kéo theo mọi phần |
| 2 | **Postgres là nguồn dữ liệu chính; DuckDB chỉ là kho đặc trưng do worker-gpu sở hữu độc quyền** | Chỉ dùng DuckDB; hoặc thư viện đọc thẳng Postgres | Postgres cho nhiều người đọc/ghi đồng thời, giao dịch, JSONB; DuckDB giữ đúng schema thư viện, không phải sửa nó; một process sở hữu tránh khoá file | Đồng bộ hai kho (vài giây mỗi job); copy nền 6,3 GB lúc khởi tạo |
| 3 | **Celery + Redis** | Dramatiq; Procrastinate (queue trên Postgres); RQ | Routing queue, concurrency theo queue, chain/chord cho lô, beat, Flower; phổ biến | Thêm Redis (dùng luôn cho cache, pub/sub, debounce, session nên đáng); cấu hình Celery dài dòng |
| 4 | **Inbox + reconcile JQL** thay vì tin hoàn toàn vào webhook | Chỉ webhook; chỉ polling | Webhook Jira có thể trùng, thiếu, sai thứ tự; URL tunnel có thể chết; reconcile giữ dữ liệu đúng, webhook giữ độ trễ thấp | Tốn thêm lượt gọi API (nhỏ ở quy mô demo) |
| 5 | **SSE** cho realtime | WebSocket; polling | Chỉ cần đẩy một chiều; đi qua nginx đơn giản, tự reconnect | Không có kênh client → server (không cần) |
| 6 | **Ollama** phục vụ LLM | vLLM; llama.cpp server | Có sẵn; JSON-schema `format`; giải phóng VRAM bằng `keep_alive=0` dễ dàng — rất quan trọng khi dùng chung GPU | Thông lượng thấp hơn vLLM (không quan trọng ở quy mô demo) |
| 7 | **Ưu tiên luật cho cảnh báo theo sự kiện; model bổ sung theo micro-batch** | Chờ model chấm xong rồi mới cảnh báo | Bảo đảm D1 kể cả khi model chậm; precision model T0 thấp (≈ 0,30) | Cảnh báo đầu tiên của task mới có thể chưa có điểm model |
| 8 | **Logic rủi ro là hàm thuần trên `IssueTimeline(as_of)`** | Viết riêng cho live, sim và huấn luyện | Một nguồn sự thật; mô phỏng và đánh giá đáng tin; nhánh model dùng lại được để sinh đặc trưng | Phải viết cẩn thận để chạy nhanh trên hàng nghìn issue (vector hoá khi đánh giá) |
| 9 | **SPA React + Vite (JS) + Mantine** | Next.js; Vue | Không cần SSR/SEO; tách biệt với backend; Mantine đủ component cho dashboard | JS không có kiểu tĩnh: bù bằng JSDoc + client sinh từ OpenAPI |
| 10 | **Workspace (live/sim) là cột trong mọi bảng** | Schema hoặc DB riêng cho sim | Cùng code, cùng query; xoá sim dễ (`DELETE … WHERE workspace_id`) | Mọi query phải lọc `workspace_id`: dùng repository bắt buộc tham số này |

## 13. Rủi ro kỹ thuật và spike cần làm trước

| Spike | Câu hỏi | Tiêu chí | Nếu không đạt |
|---|---|---|---|
| **S1. Chấm trên nền 2,68 triệu issue** | RAM đỉnh và thời gian của `DelayRiskScorer.score(issue_keys=[10])`, `CriticalityScorer.score` (kèm build stream), trên máy demo | RAM ≤ 18 GB; delay ≤ 3 phút; criticality ≤ 15 phút cho lô | Làm `prepare/refresh` (§7.3); hoặc **thu nhỏ nền** (chỉ các instance có sprint, khoảng 1,4 triệu issue) — cần kiểm tra lại metric của bundle |
| **S2. LLM song ngữ + JSON** | 2–3 model 7–14B Q4: tỉ lệ JSON hợp lệ, tỉ lệ trích dẫn đúng, chất lượng tiếng Việt, tốc độ | JSON hợp lệ ≥ 95% (sau 1 lần retry); trích dẫn sai ≤ 5% | Thu hẹp schema, dùng few-shot, giảm số action đề xuất |
| **S3. Jira demo end-to-end** | Webhook admin qua ngrok domain tĩnh; OAuth 3LO ghi comment, chuyển sprint, flag; giới hạn gói free | Mọi action trong danh mục FR-L4 chạy được | Bỏ action nào không làm được trên gói free khỏi danh mục |
| **S4. Dựng `issue_sprints` từ changelog** | Có dựng lại chính xác thời điểm vào/ra sprint trên dữ liệu công khai không (dùng cho sim và `delay_anytime`) | Khớp ≥ 95% với danh sách sprint cuối cùng | Chỉ dùng sprint cuối cùng, chấp nhận sai lệch trong mô phỏng |

Các rủi ro khác:
- Bundle T0 với instance chưa từng thấy và văn bản tiếng Việt: xử lý bằng FR-V1/V2 và chế độ chạy bóng.
- Instance ảo `ERW_<ws>` lệch thứ tự `row_id` (`ORDER BY created_ts`): issue demo có `created_ts` năm 2026, nằm sau toàn bộ nền, đúng với giả định của `refresh`.

## 14. Lộ trình kỹ thuật (khớp SRS §12)

| Mốc | Phạm vi | Đầu ra kiểm chứng |
|---|---|---|
| **M0 — Spikes** | S1–S4 | Báo cáo số đo; chốt lại §7.3 và §11 |
| **M1 — Khung** | Compose, auth (local + Atlassian), RBAC, schema, Alembic, client Jira, inbox/reconcile, bootstrap, `seed_demo.py` | Dữ liệu demo đồng bộ đúng; webhook → inbox < 1 giây |
| **M2 — Rủi ro** | `IssueTimeline`, deadline, rules, aggregate, adapter cho hai bundle, lô sáng, dashboard A (chỉ đọc) + SSE, digest Slack | Nghiệm thu SRS 11.1 #1, #2 |
| **M3 — Mô phỏng** | Workspace sim, đồng hồ ảo, `sim.evaluate`, trang báo cáo | Nghiệm thu #5 |
| **M4 — Hành động** | LLM pipeline, panel action, `jira_write` + conflict, thông báo sự kiện, debounce, trang Hiệu quả, i18n | Nghiệm thu #3, #4 |
| **M5 — Model mới** | Bật `delay_anytime` ở chế độ shadow → active | So sánh ở trang báo cáo sim |

Nhánh model song song cung cấp: (1) ETL mở rộng sprint/version/duedate cho DuckDB (M1 cần); (2) bundle `delay_anytime` theo protocol §8 (M5).

## 15. Những điểm sẽ xem lại khi lên production
- Tách `gateway` ra một host public riêng thay cho ngrok; dùng TLS thật và IP allowlist của Atlassian.
- Nhiều site Jira (multi-tenant): `workspace` đã sẵn sàng, cần thêm cô lập theo tenant ở tầng auth.
- Thay micro-batch bằng chấm gia tăng thực sự; tách `worker-gpu` sang máy GPU riêng; LLM chuyển sang vLLM nếu nhiều người dùng.
- Chuyển `score_snapshots` sang partition theo tháng hoặc TimescaleDB khi dữ liệu lớn.
- Thêm SSO công ty; ánh xạ Jira → Slack để @mention thật; cho phép thao tác ngay trong Slack.
- Huấn luyện lại bundle bằng dữ liệu công ty và embedding đa ngôn ngữ.
