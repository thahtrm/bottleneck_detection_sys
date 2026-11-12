# Kiến trúc POC/MVP — Early Risk Web

| | |
|---|---|
| Ngày | 2026-11-01 |
| Trạng thái | Đã duyệt (2026-11-02) |
| Quan hệ | Bản rút gọn của [thiết kế hệ thống đầy đủ](2026-11-01-early-risk-web-system-design.md) (gọi tắt **TARGET**). Yêu cầu nghiệp vụ theo [SRS](2026-11-01-web-quan-ly-tien-do-du-an-design.md). |
| Mục tiêu | Ít thành phần nhất mà vẫn chạy trọn luồng **Jira → phân tích → dashboard + Slack → PM xác nhận → ghi lại Jira** trên máy demo. |

## 1. Nguyên tắc rút gọn
1. **Một process backend.** FastAPI chạy kèm bộ lập lịch và hàng đợi nội bộ. Không dùng Celery, Redis hay message broker.
2. **Không thêm hạ tầng mới.** Dùng SQLite cộng các thứ đã có trên máy: Ollama, DuckDB nền, các bundle.
3. **Không sửa thư viện ML.** Chấm model theo lô, gọi nguyên `score()` như README.
4. **Chỉ dùng webhook để phát hiện thay đổi**, không có polling định kỳ. Có một lượt đồng bộ bù khi app khởi động và trước lô sáng.
5. **Giữ nguyên ranh giới code theo TARGET** (`domain/`, `integrations/`, `ml/`). Lên TARGET là thay hạ tầng, không phải viết lại logic.

## 2. Sơ đồ

```
                ┌──────────────────── 1 process: uvicorn erw.main:app ────────────────────┐
 Trình duyệt ──▶│ FastAPI  ── /api/*  (REST)                                              │
 (React build)  │          ── /      (static: frontend/dist)                              │
                │ APScheduler (in-process)                                                │
                │ POST /webhooks/jira ← Jira (qua ngrok) → sync_issue → rules → slack     │
                │   ├─ 06:45    : model_batch (thread GPU, khoá độc quyền) → rules → LLM top5 │
                │   └─ 08:00    : digest → Slack                                          │
                │ ThreadPool: llm (1 luồng), jira_write (1 luồng)                         │
                └───────┬──────────────┬───────────────┬───────────────┬──────────────────┘
                        ▼              ▼               ▼               ▼
                  SQLite (erw.db)  DuckDB làm việc  Ollama :11434   Jira Cloud REST ◀─┐
                                   + bundles/       (LLM + embed)   Slack Incoming Webhook
```

**Tổng số thứ phải chạy:** `uvicorn` và Ollama (đã có sẵn). Frontend được build tĩnh và FastAPI phục vụ luôn.

## 3. Tech stack MVP

| Lớp | Chọn | Thay vì (TARGET) |
|---|---|---|
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2 (sync) | giữ nguyên |
| CSDL | **SQLite** (WAL mode), một file `var/erw.db` | PostgreSQL |
| Migration | `Base.metadata.create_all()`; xoá DB khi đổi schema | Alembic |
| Lịch và tác vụ nền | **APScheduler** (BackgroundScheduler) + `ThreadPoolExecutor` | Celery + Redis + beat |
| Jira | httpx, **một API token tài khoản dịch vụ** cho cả đọc và ghi | Atlassian OAuth 3LO theo PM |
| Slack | **Incoming Webhook URL** (một kênh, chỉ POST JSON) | Slack bot + slack_sdk |
| LLM | Ollama `/api/chat` với `format` = JSON schema, model 7–8B Q4 | giữ nguyên |
| Auth web | Tài khoản cục bộ (bcrypt) + cookie session ký bằng `itsdangerous` | Atlassian login + Redis session |
| Frontend | React + Vite (JS) + Mantine + TanStack Query (**polling 30 giây**) | + SSE, ECharts, i18next |
| Triển khai | `make run`: build FE, chạy uvicorn; **ngrok domain tĩnh** cho webhook | docker compose, nginx |

## 4. Phạm vi MVP so với SRS

| SRS | MVP | Ghi chú |
|---|---|---|
| Kết nối Jira, lấy task và lịch sử (FR-J1, J2, J5) | ✅ | Bootstrap + ETL mở rộng (sprint, version, due date) |
| Tự chạy khi Jira có cập nhật (FR-J3) | ✅ **chỉ webhook** (khoảng 5–15 giây) | Không có polling định kỳ (FR-J4 bị lược bớt); có đồng bộ bù khi khởi động và trước lô sáng. Xem 6.1 |
| Hạn theo thứ tự due → sprint → release → SLA (4.1) | ✅ | |
| Tín hiệu luật + tổng hợp mức (6.4) | ✅ | Chạy khi có thay đổi |
| Model delay_t0, criticality_t0 (6.4a, 6.5) | ✅ **chỉ theo lô** (hằng ngày + nút "Chạy ngay" cho Admin) | Task mới có điểm model ở lượt lô kế tiếp |
| Giao diện bộ chấm + chạy bóng (6.3) | ✅ dạng tối giản: registry trong code, cờ `shadow` trong config | Chưa có trang quản lý model |
| LLM giải thích + đề xuất (6.6) | ✅ | Sinh **khi PM mở panel** (cache theo `updated` của task) và cho top 5 của digest |
| Song ngữ (FR-L1b) | ✅ cho nội dung LLM | UI chỉ tiếng Việt |
| Action: sửa → xác nhận → ghi Jira, kiểm tra xung đột (6.7) | ✅ | **Ghi bằng tài khoản dịch vụ** [Chốt cho POC], comment kèm chú thích "(xác nhận bởi PM Nguyễn A qua Early Risk)". Lệch FR-A3 có chủ đích |
| Slack: một kênh, prefix, @tên (6.8) | ✅ | Chống báo dồn dập: chỉ báo khi tăng bậc + giới hạn tin mỗi giờ. Chưa gộp 15 phút, chưa có giờ yên lặng |
| Dashboard A + panel (FR-D1…D4) | ✅ | |
| Trang Tổng quan, trang Hiệu quả (FR-D5, D6) | ❌ để sau | Số liệu hiệu quả xuất bằng script |
| Vai trò Admin / PM / Người xem (mục 3) | ✅ | Admin cấu hình qua một trang Settings đơn giản và file `.env` |
| Nền lịch sử + seed demo (FR-DM1, DM2) | ✅ | Bắt buộc, vì không có thì model không chạy được |
| Mô phỏng (FR-DM3) + đánh giá (FR-V1) | ✅ **dạng script CLI**, không có UI | `erw sim-eval --instance MongoDB --project X --from --to` sinh báo cáo Markdown |

## 5. Mô hình dữ liệu (SQLite, 11 bảng)

```
users(id, email, name, password_hash, is_admin)
project_members(project_key, user_id, role: pm|viewer)
projects(key, name, tracked, status_map JSON, thresholds JSON)
issues(key PK, project_key, summary, description_excerpt, issuetype, priority, status, status_category,
       assignee_id, assignee_name, duedate, story_points, created_at, updated_at, resolved_at, raw JSON)
changelog(issue_key, change_id, idx, at, field, from_val, to_val, PK(issue_key, change_id, idx))
links(source_key, target_key, type_std, PK(source_key, target_key, type_std))
sprints(id PK, name, state, start_at, end_at) ; issue_sprints(issue_key, sprint_id, added_at, removed_at)
versions(id PK, project_key, name, release_date, released) ; issue_versions(issue_key, version_id)
scores(issue_key, scorer, as_of, value, level, is_critical, deadline_type, deadline_at, factors JSON)  -- append
risk_state(issue_key PK, level, prev_level, crit_score, is_critical, blocked, deadline_type, deadline_at,
           factors JSON, last_alerted_level, dismissed_at_level, updated_at)
suggestions(id, issue_key, issue_updated_at, model, output JSON, valid, created_at)
actions(id, issue_key, suggestion_id, items JSON, status, confirmed_by, result JSON, created_at)
notifications(id, kind, issue_key, dedup_key UNIQUE, text, sent_at)
```
Một site Jira, không có cột `workspace`. Mô phỏng chạy bằng script đọc trực tiếp từ DuckDB, không ghi vào SQLite.

## 6. Luồng xử lý

**6.1 Phát hiện thay đổi Jira bằng webhook** (hiện thực SRS FR-J3; kích hoạt K2, K3). **Không có polling định kỳ** [Chốt].

Code: route `api/webhooks.py` → `sync_issue(key)` trong `integrations/jira.py` → `domain/` (luật, mức rủi ro) → `integrations/slack.py`.

1. **Đăng ký:** CLI `erw register-webhook` gọi `POST /rest/webhooks/1.0/webhook` (cần quyền admin site; site demo đáp ứng) với bộ lọc JQL `project in (<tracked>)` và các sự kiện:
   - `jira:issue_created`, `jira:issue_updated`, `jira:issue_deleted`;
   - `issuelink_created`, `issuelink_deleted`;
   - `sprint_created`, `sprint_updated`, `sprint_started`, `sprint_closed`;
   - `jira:version_created`, `jira:version_updated`, `jira:version_released`.

   URL: `https://<ngrok-static-domain>/webhooks/jira/<secret>`.
2. **Nhận:** route `POST /webhooks/jira/{secret}`.
   - `secret` dài 32 byte ngẫu nhiên, so bằng `hmac.compare_digest`; sai thì trả 404.
   - Đọc loại sự kiện và key (issue, sprint hoặc version), đẩy việc vào executor 1 luồng, **trả 200 ngay**.
   - Payload **chỉ là tín hiệu**. Mọi dữ liệu được lấy lại qua REST, nên không bị ảnh hưởng nếu webhook đến trùng hoặc sai thứ tự.
3. **Đồng bộ issue** (`sync_issue(key)`): `GET /rest/api/3/issue/{key}?expand=changelog`. Changelog có hơn 100 mục thì lấy phần còn lại qua `/changelog`. So `change_id` với dữ liệu đã lưu:
   - issue chưa có → **task mới** (K2);
   - có `change_id` mới → **task cập nhật** (K3), kèm danh sách trường đã đổi;
   - không có gì mới → bỏ qua (webhook bị gửi trùng).

   Sau đó upsert `issues`, `changelog`, `links`, `issue_versions`, và dựng lại `issue_sprints`.
4. **Sự kiện sprint hoặc version:** cập nhật bảng `sprints`/`versions`. Ngày kết thúc sprint hoặc ngày release thay đổi thì đánh giá lại các task thuộc sprint hoặc version đó.
5. **Sự kiện `issue_deleted`:** đánh dấu task đã xoá, bỏ khỏi danh sách "Cần xử lý".
6. **Đánh giá:** `rules.evaluate(key)` tính hạn và tín hiệu luật, gộp với điểm model gần nhất thành mức rủi ro, ghi `risk_state`.
7. **Cảnh báo:**
   - task mới đạt mức Cao → `[Nguy cơ trễ]`;
   - mức tăng bậc → `[Tăng rủi ro]`;
   - vừa bị block → `[Bị block]`;
   - task quan trọng → `[Quan trọng]` (sau lượt lô).

   `dedup_key = (issue, loại, mức)`.
8. **Lỗi khi gọi Jira:** 429 hoặc 5xx thì thử lại theo `Retry-After` hoặc backoff 2, 4, 8 giây. Vẫn lỗi thì ghi vào danh sách `pending_sync`, thử lại khi có webhook kế tiếp hoặc ở lượt đồng bộ bù (bước 9).
9. **Đồng bộ bù khi có khoảng trống (không phải polling định kỳ)** [Chốt]:
   - Webhook không lưu lại sự kiện bị lỡ. Nếu app hoặc ngrok tắt, mọi thay đổi trong lúc tắt sẽ **mất hẳn** nếu không có bước này.
   - Do đó hệ thống chạy **một lượt** JQL `updated >= <mốc webhook cuối − 5 phút>` vào hai thời điểm: **khi app khởi động** và **trước lô model 06:45**.
   - Lượt này dùng lại code bootstrap và hàm `sync_issue`, không có job lặp theo phút.

**Độ trễ** từ lúc sửa trên Jira tới tin Slack: khoảng 5–15 giây (ước lượng, chưa đo).

**Phụ thuộc vận hành:** ngrok (domain tĩnh) phải chạy liên tục. Trang Settings hiển thị "webhook cuối nhận lúc …" để phát hiện khi tunnel chết.

**6.2 Lô model (06:45 và khi Admin bấm "Chạy ngay").** Chạy trong một thread, có `threading.Lock` để không bao giờ có hai lô chạy cùng lúc:
1. Gọi `ollama keep_alive=0` để giải phóng LLM khỏi VRAM.
2. Ghi đè các dòng của instance `ERW` vào `var/erw_scoring.duckdb` (bản copy một lần từ `data/jira.duckdb`).
3. Chạy `DelayRiskScorer.score(...)` và `CriticalityScorer.score(...)` cho các issue `ERW` đang mở.
4. Ghi vào `scores`, chạy `rules.evaluate_all`.
5. Sinh LLM cho top 5 của mỗi dự án.
6. Digest được gửi lúc 08:00.

**6.3 LLM.** Panel mở thì gọi `GET /api/issues/{key}/suggestion`. Nếu đã có bản cache ứng với `updated_at` hiện tại của task thì trả luôn; nếu chưa, xếp vào executor 1 luồng và trả 202. Frontend poll mỗi 3 giây cho tới khi có kết quả.
- Đầu ra được validate bằng Pydantic, kiểm tra trích dẫn factor, và kiểm tra danh mục action (SRS FR-L3, L4). Sai thì retry 1 lần, vẫn sai thì `valid=false`.

**6.4 Ghi Jira.** `POST /api/actions/{id}/confirm` chạy theo thứ tự:
1. Kiểm tra quyền PM.
2. Gọi `GET issue?fields=updated`. Nếu khác `expected_updated` thì trả 409 kèm phần đã đổi.
3. Ghi từng item bằng token dịch vụ.
4. Lưu kết quả của từng item.
5. Gửi `[Đã xử lý]` lên Slack, rồi đồng bộ lại issue đó.

**6.5 Đánh giá mô phỏng (CLI).** Với mỗi ngày `d` trong khoảng: `score(as_of=d)` cộng `rules.evaluate(timeline(as_of=d))`, so với kết quả thực tế. Kết quả là precision, recall và lead time cho 3 cấu hình (T0, luật, tổ hợp), xuất ra `reports/sim-<project>.md`.

## 7. Cấu trúc code

```
webapp/
  backend/erw/
    main.py            # FastAPI app, mount static, khởi động scheduler
    settings.py        # pydantic-settings từ .env
    db.py, models.py   # SQLAlchemy + SQLite
    api/               # auth.py, dashboard.py, issues.py, actions.py, admin.py
    domain/            # timeline.py, deadline.py, rules.py, risk.py, actions.py, scorers.py  (giống TARGET)
    integrations/      # jira.py, slack.py, llm.py
    ml/                # duckdb_sync.py, batch.py (gọi early_risk_detection)
    jobs.py            # đăng ký job APScheduler
    cli.py             # erw seed-demo | bootstrap | run-batch | sim-eval | create-admin
  frontend/src/        # pages/Dashboard.jsx, components/IssuePanel.jsx, pages/Settings.jsx, api.js
  .env.example, Makefile
```

## 8. Spike vẫn cần làm, rút từ 4 xuống 3
- **S1.** RAM và thời gian của lô `score()` trên nền 2,68 triệu issue. Lô chạy một lần mỗi ngày nên chỉ cần **≤ 30 phút** và **RAM ≤ 24 GB**. Nếu vượt: thu nhỏ nền, chỉ giữ các instance có sprint.
- **S2.** LLM song ngữ trả đúng JSON schema: kiểm tra 2 model 7–8B.

S3 rút gọn còn: đăng ký webhook admin qua ngrok domain tĩnh và nhận đủ các loại sự kiện ở 6.1 (khoảng 1 giờ). S4 (dựng sprint từ changelog) chuyển sang nhánh model và script đánh giá.

## 9. Cái giá phải trả và đường nâng cấp lên TARGET

| Rút gọn | Rủi ro chấp nhận cho POC | Nâng cấp khi cần |
|---|---|---|
| Chỉ webhook, không polling | Thay đổi xảy ra khi ngrok hoặc app tắt chỉ được bắt lại ở lần khởi động hoặc trước lô sáng; webhook lỗi giữa chừng (app bật nhưng lỡ request) thì mất tới lượt bù kế tiếp | Thêm job polling gọi cùng `sync_issue` |
| Một process, chạy nền trong process | Restart thì mất job đang chạy; lô chiếm RAM của process API | Tách `ml/batch.py` thành worker riêng (Celery) |
| SQLite | Một người ghi tại một thời điểm, đủ cho ≤ 10 người dùng | Đổi URL của SQLAlchemy sang Postgres + thêm Alembic |
| Token dịch vụ ghi Jira | Jira hiển thị người sửa là tài khoản dịch vụ, **lệch FR-A3** | Thêm OAuth 3LO, `jira_write` nhận token theo người dùng |
| Điểm model chỉ theo lô | Task mới chỉ có tín hiệu luật cho tới lượt lô sau | Micro-batch / `prepare()` như TARGET §7.3 |
| Polling FE 30 giây | Dashboard trễ tối đa 30 giây | SSE |
| Mô phỏng chỉ có CLI | Không tua ngày trên giao diện khi demo | Workspace `sim` như TARGET §7.8 |
