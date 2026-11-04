# Early Risk Web MVP — Kế hoạch 2/4: LLM, Jira Action, Dashboard API & Auth

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng đầy đủ lớp nghiệp vụ, tích hợp LLM cục bộ (Ollama `qwen3:1.7b`), ghi ngược Jira qua tài khoản dịch vụ có kiểm tra xung đột và xác nhận từ PM, hệ thống phân quyền RBAC (Admin, PM, Viewer), cùng toàn bộ REST API phục vụ Dashboard và trang Quản trị.

**Architecture:**
- **Auth & Session:** Cookie session ký HMAC, mật khẩu băm an toàn (PBKDF2/bcrypt). Bảng `users` và `project_members`. Dependencies FastAPI kiểm tra vai trò: `require_admin`, `require_pm(project_key)`, `require_viewer(project_key)`.
- **LLM Engine:** Kết nối Ollama `:11434` gọi model `qwen3:1.7b` với JSON schema. Prompt song ngữ (FR-L1b), trích dẫn chính xác factor rủi ro, đề xuất action thuộc danh mục cho phép. Cache theo `(issue_key, issue_updated_at)` trong bảng `suggestions`. Chạy trong `ThreadPoolExecutor` 1 luồng nền; trả HTTP 202 nếu đang sinh, 200 khi có kết quả.
- **Jira Action:** Thực thi hành động PM phê duyệt (đổi hạn, đổi assignee, đổi trạng thái, thêm bình luận kèm chú thích xác nhận). Kiểm tra xung đột lạc quan (optimistic locking) với `updated` của Jira; trả 409 nếu task đã bị người khác sửa trước. Ghi nhận `actions`, bắn tin Slack `[Đã xử lý] [<PROJECT>]`, và đồng bộ bù lại task.
- **REST APIs:** Bộ API cho Dashboard A (thống kê tổng quan, danh sách task lọc đa tiêu chí, chi tiết task + timeline + factor), API gợi ý & xác nhận action, API quản trị cấu hình và kích hoạt lô model tức thì.

**Spec:**
- `docs/superpowers/specs/2026-11-01-early-risk-web-mvp-architecture.md` (MVP §5, §6.3, §6.4, §6.7)
- `docs/superpowers/specs/2026-11-01-web-quan-ly-tien-do-du-an-design.md` (SRS FR-L1..L4, FR-A1..A4, FR-D1..D4, Auth/RBAC §3)

---

## Global Constraints

- Toàn bộ code backend nằm ở `webapp/backend/`, package `erw`, test ở `webapp/backend/tests/`.
- Dùng Python venv của repo: `.venv/bin/python`.
- TUYỆT ĐỐI không `git add -A` / `git add .` / `git commit -a`; chỉ stage đúng file trong `webapp/backend/`.
- Không sửa `src/early_risk_detection/`. Không commit `var/`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Model LLM mặc định: `qwen3:1.7b`. Ngưỡng `delay_threshold`: `0.39`. Ngưỡng `criticality_top_pct`: `0.05`.
- Ghi Jira bằng tài khoản dịch vụ, comment bắt buộc kèm hậu tố: `\n\n*(xác nhận bởi PM {pm_name} qua Early Risk)*`.
- Múi giờ hiển thị `Asia/Ho_Chi_Minh`. Lưu DB theo UTC.
- Linter: `.venv/bin/ruff check webapp/backend` sạch hoàn toàn (target py311).

---

## Review Focus

1. **Bảo mật và Phân quyền:** Cookie session không bị giả mạo; PM chỉ được confirm action hoặc dismiss rủi ro trên dự án mình quản lý; Viewer chỉ đọc; Admin có quyền hệ thống.
2. **Kiểm tra xung đột Jira (Optimistic Concurrency):** Nếu Jira `updated` khác với `expected_updated` của action panel, API trả về 409 Conflict kèm dữ liệu mới, không ghi đè mất mát thay đổi trên Jira.
3. **Tính toàn vẹn của LLM Output:** Schema JSON trả về từ Ollama được kiểm tra chặt chẽ bởi Pydantic; các factor được trích dẫn phải tồn tại trong tập factor thực tế của issue; các action phải nằm trong whitelist.
4. **Hiệu năng & Tránh chặn luồng:** Gọi Ollama không được làm nghẽn FastAPI event loop hoặc SQLite write lock. Trả về 202 khi đang xử lý nền.

---

## Tasks

### Task 1: Auth & User Domain, Password Hashing, Session Management & RBAC
- [ ] Mở rộng `models.py`:
  - `User`: `id (int PK)`, `email (str unique)`, `name (str)`, `password_hash (str)`, `is_admin (bool)`, `created_at (UTCDateTime)`.
- [ ] Tạo module `erw/auth.py`:
  - Hàm băm & kiểm tra mật khẩu an toàn (PBKDF2 HMAC SHA256 với salt ngẫu nhiên).
  - Hàm ký & xác thực session token bằng HMAC-SHA256 bí mật (`settings.session_secret` hoặc secret tự sinh an toàn).
  - Cookie helper cho session (HttpOnly, SameSite=Lax).
  - FastAPI dependencies: `get_current_user`, `require_authenticated_user`, `require_admin`.
- [ ] Tạo routes `erw/api/auth.py`:
  - `POST /api/auth/login`: nhận email + password, kiểm tra, set cookie session, trả user info.
  - `POST /api/auth/logout`: xoá cookie session.
  - `GET /api/auth/me`: trả thông tin user hiện tại kèm danh sách role dự án.
- [ ] CLI command trong `erw/cli.py`:
  - `erw create-admin --email <email> --name <name> --password <password>`.
- [ ] Viết test `tests/test_auth.py`: đăng nhập thành công, sai mật khẩu, kiểm tra quyền admin, bảo vệ route yêu cầu xác thực.

### Task 2: Project Management & RBAC Permissions
- [ ] Mở rộng `models.py`:
  - `Project`: `key (str PK)`, `name (str)`, `tracked (bool)`, `status_map (JSON)`, `thresholds (JSON)`.
  - `ProjectMember`: `project_key (str PK)`, `user_id (int PK)`, `role (str: "pm" | "viewer")`.
- [ ] Mở rộng dependencies trong `erw/auth.py`:
  - `require_project_role(project_key: str, allowed_roles: set[str])`.
  - `require_pm(project_key: str)` (Admin tự động pass).
  - `require_viewer(project_key: str)` (Admin và PM tự động pass).
- [ ] Tạo routes `erw/api/projects.py`:
  - `GET /api/projects`: trả danh sách dự án mà user có quyền xem (hoặc tất cả với Admin), kèm số lượng issue và số lượng rủi ro.
  - `POST /api/admin/projects/{key}/toggle-tracking`: Admin bật/tắt theo dõi dự án.
- [ ] Viết test `tests/test_projects.py`: phân quyền PM/Viewer/Admin trên từng dự án.

### Task 3: Tích hợp LLM Ollama & Cache Đề xuất Action
- [ ] Mở rộng `models.py`:
  - `Suggestion`: `id (int PK)`, `issue_key (str index)`, `issue_updated_at (UTCDateTime)`, `model (str)`, `output (JSON)`, `valid (bool)`, `created_at (UTCDateTime)`.
- [ ] Tạo module `erw/integrations/llm.py`:
  - Pydantic models cho LLM response: `ActionItem(action_type, target, value, reason)`, `SuggestionOutput(summary, explanation, factors_cited, actions)`.
  - Whitelist action types: `adjust_deadline`, `change_assignee`, `change_status`, `add_comment`, `escalate_blocker`.
  - System prompt & schema injection cho Ollama `/api/chat` (model `settings.llm_model = "qwen3:1.7b"`).
  - Validator: so khớp `factors_cited` với `risk_state.factors`; kiểm tra danh mục action hợp lệ.
  - Hàm `generate_suggestion_sync(session, issue_key, client, settings) -> Suggestion`.
  - Hàng đợi nền `ThreadPoolExecutor(max_workers=1)` quản lý tác vụ sinh gợi ý cho panel.
- [ ] Viết test `tests/test_llm.py`: parse JSON schema từ Ollama, retry khi lỗi cú pháp, validate factor citation, whitelist action, cache hit theo `issue_updated_at`.

### Task 4: Ghi Jira qua Service Account & Xử lý Xung đột
- [ ] Mở rộng `models.py`:
  - `Action`: `id (int PK)`, `issue_key (str index)`, `suggestion_id (int nullable)`, `items (JSON)`, `status (str: pending|applied|failed|conflict)`, `confirmed_by (int FK users.id)`, `result (JSON)`, `created_at (UTCDateTime)`.
- [ ] Mở rộng `JiraClient` trong `erw/integrations/jira.py`:
  - `get_issue_updated(key: str) -> datetime`.
  - `update_issue(key: str, fields: dict) -> None`.
  - `add_comment(key: str, body: str) -> None`.
  - `transition_issue(key: str, transition_id: str) -> None`.
- [ ] Tạo module `erw/domain/actions.py`:
  - `execute_action(session, jira_client, slack_sender, action_id, expected_updated, confirmed_by_user, settings) -> ActionResult`.
  - Kiểm tra `expected_updated == jira_client.get_issue_updated(key)`. Nếu lệch → đổi status `conflict`, trả lỗi 409.
  - Ghi từng item vào Jira; thêm bình luận ghi chú `(xác nhận bởi PM {user.name} qua Early Risk)`.
  - Gửi tin nhắn Slack `[Đã xử lý] [<PROJECT>] Issue {key} đã được xử lý...`.
  - Gọi `sync_issue(session, jira_client, key, settings)` để cập nhật ngay DB cục bộ.
- [ ] Viết test `tests/test_actions.py`: test ghi Jira thành công, test phát hiện xung đột trả 409, test format bình luận và thông báo Slack.

### Task 5: REST API Chi tiết Issue, Gợi ý & Xác nhận Action
- [ ] Tạo module `erw/api/issues.py`:
  - `GET /api/issues/{key}`: trả thông tin chi tiết issue, deadline, status, assignee, risk_state, timeline tóm tắt, lịch sử action.
  - `GET /api/issues/{key}/suggestion`: kiểm tra cache bảng `suggestions`. Nếu có → trả 200; nếu chưa có → đẩy vào worker nền, trả 202 `{ "status": "pending" }`.
  - `POST /api/actions/{id}/confirm`: body `{ "expected_updated": "..." }`, yêu cầu quyền PM của dự án; gọi `execute_action`.
  - `POST /api/issues/{key}/dismiss`: body `{ "reason": "..." }`, set `dismissed_at_level = level` trên `risk_state`.
- [ ] Viết test `tests/test_api_issues.py`: kiểm thử luồng 202/200 của suggestion, confirm action, dismiss rủi ro.

### Task 6: REST API Dashboard Stats & Danh sách Task
- [ ] Tạo module `erw/api/dashboard.py`:
  - `GET /api/dashboard/stats`: trả số liệu tổng quan (tổng task rủi ro, tăng rủi ro 24h, bị block, task quan trọng, đã xử lý gần đây), lọc theo `project` nếu được chọn.
  - `GET /api/dashboard/issues`: truy vấn danh sách issue kèm `risk_state`, hỗ trợ:
    - Filter: `project`, `level` (HIGH, MED, LOW), `status_category` (active/done/all), `is_critical`, `blocked`, `assignee_id`, `q` (tìm kiếm key / summary).
    - Sort: `risk_level` (mặc định), `deadline_at`, `updated_at`.
    - Phân trang: `limit`, `offset`.
- [ ] Viết test `tests/test_api_dashboard.py`: lọc theo project, lọc theo level, tìm kiếm text, tính toán chính xác stats.

### Task 7: REST API Quản trị & Tích hợp Batch Model Top-5 Digest
- [ ] Mở rộng `erw/api/admin.py`:
  - `GET /api/admin/settings`: trả trạng thái webhook (`last_webhook_at`), domain ngrok, model config (`qwen3:1.7b`, delay threshold 0.39, criticality top 0.05).
  - `POST /api/admin/run-batch`: kích hoạt chạy lô ngay lập tức trong thread nền (`run_model_batch`), trả 200 hoặc 409 nếu đang bận.
- [ ] Mở rộng `erw/jobs.py`:
  - Trong job lô sáng 06:45: sau khi chạy batch và evaluate_all, tự động sinh trước LLM suggestion cho top 5 issue có nguy cơ cao nhất của mỗi dự án, chuẩn bị sẵn nội dung cho digest lúc 08:00.
- [ ] Viết test `tests/test_admin.py` và cập nhật test digest trong `tests/test_digest.py`.
