# Early Risk Web MVP — Kế hoạch 3/4: Frontend React + Mantine (Dashboard Bố cục A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng giao diện web Single Page Application (SPA) hiện đại bằng React + Vite (JS) + Mantine UI, tích hợp TanStack Query (polling 30s) và kết nối trọn vẹn với FastAPI backend. Hoàn thiện Dashboard bố cục A, panel phân tích LLM, modal xác nhận & ghi Jira, và trang quản trị hệ thống.

**Architecture:**
- **Thư mục:** `webapp/frontend/`.
- **Framework & Libraries:** React 18+, Vite, `@mantine/core`, `@mantine/hooks`, `@mantine/notifications`, `@tabler/icons-react`, `@tanstack/react-query`.
- **Phục vụ tĩnh (Production):** `npm run build` xuất file tĩnh vào `webapp/frontend/dist/`. FastAPI mount `StaticFiles(directory="webapp/frontend/dist", html=True)` phục vụ trực tiếp trên cùng cổng 8000.
- **Polling & Cập nhật:** TanStack Query cấu hình `refetchInterval: 30000` (30 giây) cho danh sách task và thống kê dashboard.
- **Auth State:** React Context lưu trữ `user` hiện tại từ `GET /api/auth/me`. Quản lý điều hướng tới `/login` nếu chưa đăng nhập.

**Spec:**
- `docs/superpowers/specs/2026-11-01-early-risk-web-mvp-architecture.md` (MVP §3, §4, §6.3, §6.4, §6.7)
- `docs/superpowers/specs/2026-11-01-web-quan-ly-tien-do-du-an-design.md` (SRS FR-D1..D4, Giao diện Dashboard A)

---

## Global Constraints

- Code frontend nằm hoàn toàn trong `webapp/frontend/`.
- Build output nằm ở `webapp/frontend/dist/`.
- FastAPI backend phục vụ `frontend/dist` tại route `/`.
- Không sử dụng TypeScript cho frontend (dùng React JSX chuẩn theo chỉ đạo của spec MVP).
- Giao diện tiếng Việt chuẩn hóa, các thuật ngữ kỹ thuật Agile / Jira giữ nguyên hoặc chú thích rõ ràng.
- Đảm bảo responsive trên độ phân giải máy tính xách tay demo (tối thiểu 1366x768).

---

## Tasks

### Task 1: Khởi tạo Project Frontend Vite + Mantine & Kết nối Build với FastAPI
- [ ] Khởi tạo project trong `webapp/frontend/`:
  - `package.json` với Vite, React, `@mantine/core`, `@mantine/hooks`, `@mantine/notifications`, `@tabler/icons-react`, `@tanstack/react-query`.
  - Cấu hình `vite.config.js`: proxy API sang `http://localhost:8000/api` khi chạy dev server; build ra thư mục `dist`.
  - Cấu hình theme Mantine, notifications container trong `App.jsx`.
- [ ] Cập nhật `webapp/backend/erw/main.py`:
  - Mount thư mục `webapp/frontend/dist` vào FastAPI root app (`StaticFiles(html=True)`) nếu thư mục tồn tại.
- [ ] Viết script / Makefile / npm test để kiểm tra build thành công.

### Task 2: Auth Context, Màn hình Đăng nhập & Điều hướng Bảo vệ
- [ ] Xây dựng `src/api/client.js`: wrap fetch / axios với credentials `include` để tự động gửi session cookie.
- [ ] Xây dựng `src/context/AuthContext.jsx`:
  - Trạng thái `user`, `loading`, hàm `login(email, password)`, hàm `logout()`.
  - Gọi `GET /api/auth/me` khi ứng dụng khởi động.
- [ ] Xây dựng `src/pages/Login.jsx`:
  - Giao diện đăng nhập Mantine (Card, TextInput, PasswordInput, Button, thông báo lỗi).
- [ ] Điều hướng bảo vệ (`ProtectedRoute`): chuyển hướng về `/login` nếu chưa xác thực; kiểm tra quyền Admin khi truy cập `/admin`.

### Task 3: Header, Thanh Trạng thái Webhook & Bộ Thẻ Thống kê (Stat Cards)
- [ ] Xây dựng `src/components/Header.jsx`:
  - Dropdown chọn dự án ("Tất cả dự án" hoặc dự án cụ thể từ `GET /api/projects`).
  - Ô tìm kiếm nhanh (query key/summary).
  - Badge trạng thái webhook: hiển thị chấm xanh và thời gian "Webhook cuối: X phút trước" lấy từ `GET /api/admin/settings`.
  - Menu người dùng: Tên, Avatar, Vai trò (Admin/PM/Viewer), Nút Đăng xuất.
- [ ] Xây dựng `src/components/StatCards.jsx`:
  - 5 thẻ thống kê (SRS FR-D2) với số liệu từ `GET /api/dashboard/stats`:
    1. Tổng việc có nguy cơ trễ (Badge Đỏ/Cam)
    2. Tăng rủi ro trong 24h (Icon xu hướng tăng)
    3. Đang bị chặn (Blockers)
    4. Task quan trọng (Critical tasks)
    5. Đã xử lý gần đây (Đã xác nhận action)

### Task 4: Bảng Danh sách Task Rủi ro & Bộ lọc Đa tiêu chí (Left Column)
- [ ] Xây dựng `src/components/TaskTable.jsx`:
  - Tabs bộ lọc nhanh: "Cần xử lý" (Cao + TB), "Tất cả", "Bị block", "Quan trọng", "Đã xong".
  - Bộ lọc phụ: Chọn mức rủi ro (Cao, TB, Thấp), Chọn người phụ trách, Lọc theo thời hạn.
  - Bảng hiển thị (Mantine Table):
    - Cột Issue Key + Summary.
    - Cột Loại & Mức ưu tiên (Icon + Text).
    - Cột Mức rủi ro (Badge Cao - Đỏ, TB - Cam, Thấp - Xanh).
    - Cột Tín hiệu: Icon Cảnh báo, Icon Bị Block, Icon Quan trọng.
    - Cột Hạn chót & Nhãn hạn (Sprint / Release / SLA) kèm cảnh báo còn X ngày / đã trễ X ngày.
    - Cột Người phụ trách (Avatar + Tên).
    - Cột Hành động: Nút "Xem chi tiết / Đề xuất LLM" để mở panel phải.
  - Phân trang Mantine Pagination.

### Task 5: Panel Chi tiết Task & Gợi ý LLM (Right Column / Drawer)
- [ ] Xây dựng `src/components/IssuePanel.jsx`:
  - Mở dạng Side Drawer hoặc cột bên phải khi click vào task.
  - Tab 1: Tổng quan & Rủi ro:
    - Điểm mô hình: Xác suất trễ hạn (`p_delay`), Điểm quan trọng (`criticality`).
    - Danh sách yếu tố rủi ro (Risk factors) giải thích rõ: ví dụ "Sprint còn 2 ngày nhưng task chưa bắt đầu", "Bị block bởi DEMO-2 4 ngày".
    - Timeline tóm tắt tiến trình task.
  - Tab 2: Đề xuất hành động từ LLM (Ollama `qwen3:1.7b`):
    - Trạng thái tải: hiển thị Skeleton hoặc Loader khi API trả 202 ("Đang phân tích đề xuất tối ưu..."), tự động poll mỗi 3 giây đến khi có kết quả.
    - Hộp giải thích (Rationale): Giải thích nguyên nhân bằng tiếng Việt song ngữ, dẫn chứng yếu tố thực tế.
    - Danh sách hành động đề xuất (Action Items): mỗi item hiển thị loại hành động, giá trị đề xuất, lý do.
    - Nút "Xem xét & Xác nhận hành động" (chỉ hiển thị nếu user là PM của dự án).
    - Nút "Bỏ qua mức rủi ro này" (Dismiss risk level).

### Task 6: Modal Xác nhận & Ghi Jira (Action Confirmation Modal)
- [ ] Xây dựng `src/components/ActionConfirmModal.jsx`:
  - Hiển thị danh sách các thay đổi sẽ ghi ngược vào Jira.
  - Cho phép PM chỉnh sửa giá trị trước khi ghi:
    - Sửa ngày hạn mới (DatePicker).
    - Đổi người phụ trách (Select assignee).
    - Chỉnh sửa nội dung bình luận (Textarea).
  - Cảnh báo rõ ràng: "Hành động này sẽ cập nhật trực tiếp vào Jira Cloud với ghi chú xác nhận từ PM {user.name}."
  - Nút "Xác nhận & Ghi Jira" (gọi `POST /api/actions/{id}/confirm` kèm `expected_updated`).
  - Xử lý xung đột (HTTP 409): nếu task vừa bị cập nhật trên Jira, hiển thị cảnh báo xung đột dữ liệu và tải lại thông tin mới nhất.
  - Thông báo thành công qua `@mantine/notifications` và cập nhật lại danh sách.

### Task 7: Trang Quản trị Hệ thống (Admin Page)
- [ ] Xây dựng `src/pages/Settings.jsx`:
  - Thông tin kết nối Jira Cloud & trạng thái webhook (URL webhook, thời gian webhook cuối nhận được).
  - Cấu hình mô hình: Hiển thị model LLM (`qwen3:1.7b`), ngưỡng `p_delay` (0.39), ngưỡng `criticality` (top 5%).
  - Nút "Chạy lô mô hình ngay" (POST `/api/admin/run-batch`): hiển thị thanh tiến trình / thông báo đang xử lý trong nền.
  - Danh sách dự án đang theo dõi: Bảng danh sách dự án Jira, nút gạt (Switch) bật/tắt theo dõi dự án.
