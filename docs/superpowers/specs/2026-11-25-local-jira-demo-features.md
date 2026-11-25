# Phân tích Yêu cầu & Danh sách Feature: Nâng cấp Demo App tích hợp Local Jira Engine

- **Ngày lập**: 2026-11-25
- **Phạm vi**: Ứng dụng web demo Early Risk Web (`webapp/`)
- **Mục tiêu**: Nâng cấp app demo hỗ trợ đầy đủ các tính năng cốt lõi tương đương 100% Jira Software (quản lý user, task, comment, workflow transition, assignee, toàn bộ thuộc tính task, sprint/board/backlog...) để chủ động seed dữ liệu quá khứ và demo trực tiếp không phụ thuộc Jira Cloud.

---

## 1. Phân tích hiện trạng & Bản chất bài toán

Qua khảo sát codebase của app demo **Early Risk Web (`webapp/`)**, hệ thống hiện tại đang hoạt động theo mô hình **đồng bộ 1 chiều & ghi ngược lên Jira Cloud**:

- **Backend hiện có** (`webapp/backend/erw/models.py`, `webapp/backend/erw/api/issues.py`): Mới chỉ có endpoint **đọc** (`GET /api/issues/{key}`) và `dismiss`. Chưa có API CRUD cho Issue, Comment, Link, Sprint, Version, Workflow.
- **Thao tác ghi đang bị khóa cứng vào Jira Cloud** (`webapp/backend/erw/domain/actions.py`, `webapp/backend/erw/integrations/jira.py`): Khi PM xác nhận hành động (đổi trạng thái, đổi assignee, gia hạn due date, thêm comment) hoặc lấy danh sách transition, backend gọi trực tiếp REST API v3 của Jira Cloud.
- **Dữ liệu User & Assignee bị tách rời** (`webapp/backend/erw/demo/seed.py`, `webapp/backend/erw/api/admin.py`): Bảng `users` hiện mới phục vụ đăng nhập và phân quyền `admin`/`pm`/`viewer`, trong khi `assignee_id` trên bảng `issues` đang lưu chuỗi giả lập (`demo-an`, `demo-binh`) không liên kết với `users`.
- **Thiếu các bảng dữ liệu cốt lõi của Jira**: Chưa có `comments`, `attachments`, `worklogs`, `watchers`, `components`, `workflows` trong SQLite.

### Định hướng kiến trúc đề xuất: Built-in Local Jira Engine (Dual-Mode)

Để vừa giải quyết triệt để việc **seed dữ liệu quá khứ (backdate `created_at`, `changelog`, `comments`, `sprints`, `links`)** cho demo, vừa giữ nguyên toàn bộ năng lực AI/ML hiện có của Early Risk Web:

- Xây dựng **Local Jira Service** lưu trữ trực tiếp trên SQLite, triển khai cùng interface với `JiraClient` (chế độ `local` song song với chế độ `jira_cloud`).
- Mọi thao tác trên UI (tạo task, sửa thuộc tính, kéo thả đổi trạng thái, comment, gắn link...) sẽ tự động:
  1. Ghi nhận **Changelog** chuẩn Jira vào bảng `changes`.
  2. Cập nhật trường `Issue.raw` theo đúng định dạng **Jira REST API v3 JSON** (tương thích 100% với pipeline ETL DuckDB & mô hình ML/TGN).
  3. Kích hoạt ngay `evaluate_issue()` (`webapp/backend/erw/pipeline/evaluate.py`) để cập nhật Risk Level, Blocker, Dependency Graph và AI Suggestions theo thời gian thực.

---

## 2. Danh sách Feature triển khai (Chuẩn Jira Software)

### Phân hệ A: Quản lý User & Phân quyền (User Management)
Mở rộng từ `webapp/backend/erw/api/admin.py` và `webapp/backend/erw/api/projects.py`:

1. **Hồ sơ User chuẩn Jira**: Bổ sung `account_id` (UUID/slug chuẩn Jira), `avatar_url` / chữ viết tắt màu, `job_title`, `department`, `timezone`, trạng thái `is_active`.
2. **CRUD User toàn diện**: Tạo user, sửa thông tin, đặt/reset mật khẩu, kích hoạt/vô hiệu hóa (deactivate), xóa user (kèm xử lý fallback assignee thành `Unassigned` nếu user đang giữ task).
3. **Phân quyền 2 tầng (Global & Project Roles)**:
   - Global: `Admin`, `Member`.
   - Project Role: `Project Admin / PM`, `Developer / Member` (được tạo/sửa/transition/comment task), `Viewer` (chỉ xem).
4. **User Picker & Assignable Users API**: Tìm kiếm nhanh user theo tên/email trong project để chọn làm **Assignee**, **Reporter**, **Watcher**, hoặc `@mention` trong comment.
5. **Quick Switch User (Tiện ích Demo)**: Cho phép chuyển nhanh tài khoản đang đăng nhập (Admin / PM / Dev / Viewer) để demo luồng phân quyền và cộng tác nhiều người mà không cần đăng xuất/nhập lại mật khẩu nhiều lần.

### Phân hệ B: Bộ thuộc tính Task chuẩn 100% Jira (Issue Schema)
Mở rộng bảng `issues` và các bảng quan hệ để đầy đủ các trường tiêu chuẩn của Jira Software:

1. **Định danh & Phân cấp**:
   - `key` tự tăng theo Project (`DEMO-101`, `DEMO-102`...), `project_key`.
   - `issuetype`: `Epic`, `Story`, `Task`, `Bug`, `Sub-task` (kèm icon & màu sắc đặc trưng của Jira).
   - `parent_key`: Liên kết phân cấp chuẩn Jira (`Epic → Story/Task/Bug → Sub-task`).
2. **Nội dung & Ngữ cảnh**:
   - `summary` (tiêu đề), `description` (hỗ trợ Rich Text / Markdown & lưu tương thích ADF), `environment` (môi trường lỗi cho Bug).
3. **Trạng thái & Kết quả**:
   - `status` (VD: `To Do`, `Open`, `In Progress`, `In Review`, `Blocked`, `Done`, `Reopened`) gắn với `status_category` (`new` | `indeterminate` | `done`).
   - `resolution` (`Done`, `Won't Do`, `Duplicate`, `Cannot Reproduce`, `Incomplete`, `None`) — tự động gán khi chuyển sang `Done` và xóa khi `Reopen`.
4. **Độ ưu tiên & Ước lượng (Agile & Time Tracking)**:
   - `priority`: `Highest`, `High`, `Medium`, `Low`, `Lowest` (kèm `priority_norm` cho ML).
   - `story_points`, `rank` (thứ tự ưu tiên kéo-thả trên Board/Backlog).
   - `original_estimate`, `remaining_estimate`, `time_spent` (theo chuẩn Jira `1w 2d 4h 30m`).
5. **Con người**:
   - `assignee` (có tùy chọn *Assign to me* và *Unassigned*), `reporter`, `creator`, `watchers` (danh sách người theo dõi), `votes` (lượt bình chọn).
6. **Phân loại & Lập lịch**:
   - `labels` (nhiều tag tự do), `components` (module/thành phần thuộc Project).
   - `sprints` (Sprint hiện tại & lịch sử Sprint), `fix_versions` & `affects_versions` (Release/Phiên bản).
   - `start_date`, `duedate`.
7. **Mốc thời gian & Tài liệu**:
   - `created_at`, `updated_at`, `resolved_at`, `deleted_at`.
   - `attachments` (upload/xem/tải/xóa file đính kèm trên local storage).

### Phân hệ C: Nghiệp vụ Quản lý Task (Issue Lifecycle & Actions)

1. **Tạo Task (`+ Create` Modal chuẩn Jira)**: Chọn Project, Issue Type, Summary, Description, Priority, Assignee, Reporter, Sprint, Due Date, Story Points, Labels, Parent/Epic, Links; hỗ trợ checkbox *"Create another"*.
2. **Chỉnh sửa trực tiếp (Inline Editing)**: Click trực tiếp vào từng thuộc tính trong màn hình chi tiết task để sửa và lưu ngay lập tức (không cần bấm nút Edit toàn trang), có Optimistic Locking dựa trên `updated_at`.
3. **Workflow & Chuyển trạng thái (Status Transitions)**:
   - Cấu hình Workflow theo Project (danh sách Status + bảng chuyển trạng thái hợp lệ + điều kiện gán `Resolution`).
   - Chuyển trạng thái qua Dropdown trong Issue Detail, kéo-thả cột trên Jira Board, hoặc qua `ActionConfirmModal` của ERW.
4. **Quản lý Sub-tasks & Child Issues**: Tạo nhanh Sub-task ngay trong Story/Task, hoặc thêm Child Issues vào Epic, hiển thị thanh tiến độ hoàn thành (% Done).
5. **Liên kết Issue (Issue Links)**: Thêm/xóa liên kết hai chiều chuẩn Jira:
   - `blocks` / `is blocked by`
   - `depends on` / `is depended on by`
   - `relates to`
   - `duplicates` / `is duplicated by`
   - `clones` / `is cloned by`
   - *(Tự động đồng bộ với Dependency Graph và cờ `blocked` của hệ thống cảnh báo rủi ro).*
6. **Thao tác nâng cao trên Task**: Clone Issue (nhân bản task), Move Issue (đổi loại task hoặc chuyển sang Project khác), Delete Issue (xóa kèm xác nhận), Watch/Unwatch, Vote/Unvote.

### Phân hệ D: Bình luận, Worklog & Lịch sử hoạt động (Activity)

1. **Comments chuẩn Jira**:
   - Thêm, sửa (hiển thị nhãn *edited*), xóa bình luận.
   - Hỗ trợ Markdown, `@mention` thành viên trong dự án.
   - Lưu đầy đủ `author`, `created_at`, `updated_at` và đồng bộ vào `Issue.raw.fields.comment` cho ML/LLM.
2. **History (Changelog tự động)**:
   - Tự động ghi log mọi thay đổi trường (`status`, `assignee`, `priority`, `duedate`, `story_points`, `sprint`, `summary`, `description`, `link`, `resolution`...) kèm `author`, `timestamp`, `from_str → to_str`.
3. **Worklog (Ghi nhận thời gian làm việc)**:
   - Log work (`time_spent`, `started_at`, `comment`), tự động trừ `remaining_estimate` và cập nhật thanh tiến độ Time Tracking.
4. **Bộ lọc Activity Tab**: Chuyển đổi giữa **All / Comments / History / Worklog** và sắp xếp mới nhất / cũ nhất giống 100% Jira.

### Phân hệ E: Quản lý Project, Sprint, Release & Board (Jira Software UI)

1. **Quản lý Project**: Tạo/sửa Project mới (`key`, `name`, `project_lead`, `description`), quản lý danh sách `Components`, `Versions/Releases` (Release date, Released/Unreleased), và cấu hình cột Workflow.
2. **Backlog & Quản lý Sprint**:
   - Tạo Sprint mới, sửa tên/mục tiêu/ngày bắt đầu–kết thúc, **Start Sprint**, **Complete Sprint** (chuyển các task chưa xong sang Backlog hoặc Sprint kế tiếp).
   - Kéo thả sắp xếp thứ tự (`rank`) và kéo task giữa Backlog và các Sprint.
3. **Jira Board (Scrum / Kanban)**:
   - Hiển thị các cột theo **Workflow Status** (khác với Risk Triage Board hiện tại của ERW), kéo-thả card giữa các cột để trigger Transition.
   - Thanh Quick Filters chuẩn Jira: Search text, lọc theo Assignee (avatar chips), Only My Issues, Priority, Issue Type, Label, Sprint, Epic.
4. **Issue Navigator (List View & Bộ lọc nâng cao)**:
   - Bảng danh sách tùy chỉnh cột, lọc đa tiêu chí (Project, Type, Status, Priority, Assignee, Reporter, Sprint, Fix Version, Label, Due Date), sắp xếp và tìm kiếm nhanh.
5. **Màn hình Chi tiết Task chuẩn Jira (2 cột)**:
   - Mở dạng Modal lớn hoặc Full Page (`/issues/DEMO-101`): Cột trái (Breadcrumb Epic/Parent, Summary, Description, Attachments, Sub-tasks, Linked Issues, Activity Tabs); Cột phải (Status Transition dropdown, Details panel toàn bộ thuộc tính, Time Tracking, **+ Tab/Widget Risk & AI của ERW**).

### Phân hệ F: Công cụ Demo & Seeding Dữ liệu

1. **Rich Demo Seeder (CLI + Nút trên UI Admin)**:
   - Seed nhanh bộ dữ liệu hoàn chỉnh: nhiều Users (Admin, PM, 4–6 Developers, QA), nhiều Sprints (Closed, Active, Future), Releases, Epics/Stories/Bugs/Sub-tasks, đầy đủ `changelog` quá khứ, `comments` trao đổi thực tế, `links` tạo nút thắt cổ chai, và `worklogs`.
   - Hỗ trợ **Reset Demo** về trạng thái ban đầu chỉ bằng 1 click trước mỗi buổi thuyết trình.
2. **Tích hợp 2 chiều với ERW AI/ML**:
   - Đảm bảo `ActionConfirmModal`, `IssuePanel`, `NetworkGraph`, `PmChat` và `Health Reports` hoạt động trơn tru trên Local Jira Engine mà không cần kết nối Internet/Jira Cloud.

---

## 3. Đề xuất lộ trình triển khai (Phasing)

| Giai đoạn | Trọng tâm | Các hạng mục chính |
| :--- | :--- | :--- |
| **Phase 1** | Core Jira Engine & Issue Management *(Bắt buộc)* | Nâng cấp DB Schema (User profile, Issue full attributes, Comments, Links, Sub-tasks, Sprints, Versions, Components, Workflows); Xây dựng `LocalJiraClient` + REST API CRUD; Tích hợp `execute_action` & real-time `evaluate_issue`; UI Create Issue Modal, Issue Detail 2 cột (inline edit, transition, assign, comment, history, links, sub-tasks), nâng cấp `UsersAdmin`. |
| **Phase 2** | Agile Workspace & Views | Jira Workflow Board (kéo-thả đổi trạng thái), Backlog & Sprint Management (Start/Complete Sprint), Issue Navigator với bộ lọc nâng cao; Project Settings mở rộng (Components, Versions, Workflow statuses). |
| **Phase 3** | Jira Parity Nâng cao & Demo Polish | Attachments (upload/preview), Worklogs & Time Tracking, Watchers/Votes, Clone/Move Issue, Quick Switch User và nút Reset/Seed Demo trên UI. |

---

## 4. Các điểm cần xác nhận trước khi thiết kế chi tiết

1. **Cách tích hợp giao diện**: Các màn hình Jira (Jira Board, Backlog, Issues List, Create Task) nằm chung trong thanh điều hướng trái (`LeftNav`) của app ERW hiện tại (như cụm menu *"Workspace / Jira"* bên cạnh *"Risk & AI"*), hay có nút chuyển đổi mode rõ ràng giữa giao diện **Jira** và giao diện **Early Risk**?
2. **Phạm vi "100% giống Jira"**: Các tính năng Enterprise nặng như *trình biên dịch JQL tự do (custom JQL query parser)*, *Automation Rules builder*, hay *Custom Fields động do user tự định nghĩa* có cần đưa vào đợt này không, hay tập trung hoàn thiện **100% tính năng Jira Software cốt lõi** ở mục 2?
3. **Mức độ triển khai**: Triển khai trọn vẹn cả **3 Phase** hay ưu tiên hoàn thành **Phase 1 + Phase 2** trước?
