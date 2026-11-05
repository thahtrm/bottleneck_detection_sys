# Early Risk Web MVP — Kế hoạch 4/4: Seed Demo & Đánh giá Mô phỏng (Sim-Eval)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện bộ công cụ CLI phục vụ demo thực tế (`erw seed-demo`) và script đánh giá mô phỏng khoa học trên dữ liệu lịch sử (`erw sim-eval`), chứng minh tính vượt trội của phương pháp kết hợp mô hình học máy (TGN + GBDT) với hệ luật nghiệp vụ so với từng phương pháp đơn lẻ.

**Architecture:**
- **Seed Demo (`erw/cli.py`):** Nạp dữ liệu kịch bản demo sống động vào SQLite (kèm đồng bộ các task tương ứng trên dự án Jira DEMO), tạo sẵn tài khoản Admin/PM, thiết lập trạng thái rủi ro đa dạng cho buổi thuyết trình.
- **Sim-Eval Engine (`erw/sim/eval.py`):** Đọc trực tiếp từ file DuckDB lịch sử nền (`data/jira.duckdb`), chạy vòng lặp theo từng ngày `d` trong khoảng `[from_date, to_date]`:
  - Dựng timeline lịch sử tính đến thời điểm `as_of = d`.
  - Chấm điểm rủi ro trễ hạn `p_delay` (ngưỡng 0.39) và `criticality` (top 5%).
  - Đánh giá hệ luật nghiệp vụ `evaluate_rules(timeline)`.
  - So sánh đối chiếu với thời gian hoàn thành thực tế trong tương lai của task.
  - Đo lường: Precision, Recall, F1, và thời gian cảnh báo sớm (lead time tính bằng ngày).
  - Tự động sinh báo cáo khoa học dạng Markdown lưu tại `reports/sim-<project>.md`.

**Spec:**
- `docs/superpowers/specs/2026-11-01-early-risk-web-mvp-architecture.md` (MVP §4, §6.5, §7)
- `docs/superpowers/specs/2026-11-01-web-quan-ly-tien-do-du-an-design.md` (SRS FR-DM1..DM3, FR-V1)

---

## Global Constraints

- Code CLI và script nằm trong `webapp/backend/erw/` hoặc `scripts/`.
- Không sửa đổi mã nguồn gốc trong `src/early_risk_detection/`.
- File báo cáo sinh ra tại thư mục `reports/` (được gitignore hoặc commit có chọn lọc).
- Mọi thao tác mô phỏng đọc DuckDB ở chế độ Read-Only (`read_only=True`).

---

## Tasks

### Task 1: Bộ dữ liệu Seed Demo & Kịch bản Thuyết trình (`erw seed-demo`)
- [ ] Xây dựng module `erw/demo/seed.py`:
  - Khởi tạo tài khoản Admin (`admin@earlyrisk.local` / `Admin@123456`) và PM (`pm@earlyrisk.local`).
  - Nạp các kịch bản demo trực quan:
    1. **Kịch bản 1 (Nguy cơ trễ cao):** Task sắp hết hạn trong sprint nhưng chưa bắt đầu (High risk do sprint_elapsed + p_delay cao).
    2. **Kịch bản 2 (Bị chặn nghiêm trọng):** Task quan trọng bị chặn bởi một blocker chưa giải quyết qua 3 ngày.
    3. **Kịch bản 3 (Task trọng yếu - Critical):** Task thuộc top 5% criticality theo TGN memory.
    4. **Kịch bản 4 (Gợi ý tối ưu LLM sẵn sàng):** Gợi ý hành động từ `qwen3:1.7b` đã được cache sẵn để mở panel hiển thị tức thì.
  - Khởi tạo dự án DEMO trong bảng `projects` ở trạng thái `tracked=True`.
- [ ] Gắn lệnh vào CLI: `erw seed-demo [--reset]`.
- [ ] Viết test `tests/test_seed_demo.py`: kiểm tra DB được nạp đủ bảng, đủ user, và đủ các kịch bản rủi ro.

### Task 2: Core Engine Đánh giá Mô phỏng Lịch sử (`erw/sim/eval.py`)
- [ ] Xây dựng module `erw/sim/eval.py`:
  - Kết nối DuckDB nền, đọc changelog và issue của project chỉ định trong instance lịch sử (ví dụ: Apache, MariaDB, MongoDB).
  - Hàm `simulate_day(db_conn, project, as_of_date, models, settings) -> DayEvalResult`:
    - Dựng trạng thái `as_of_date` cho tất cả các issue đang mở tại ngày đó.
    - Chấm điểm 3 cấu hình:
      - **Cấu hình 1 (Chỉ Luật):** dựa hoàn toàn vào `evaluate_rules`.
      - **Cấu hình 2 (Chỉ ML T0):** dựa vào ngưỡng `p_delay >= 0.39` và `criticality >= 0.05`.
      - **Cấu hình 3 (Tổ hợp Hybrid - ERW):** kết hợp luật + điểm model theo `aggregate()`.
- [ ] Viết unit test `tests/test_sim_eval.py` trên một tập con dữ liệu nhỏ hoặc fixture mô phỏng.

### Task 3: Tổng hợp Thống kê & Xuất Báo cáo Markdown (`reports/sim-<project>.md`)
- [ ] Xây dựng hàm tính toán metric trong `erw/sim/metrics.py`:
  - True Positive, False Positive, False Negative, True Negative.
  - Precision, Recall, F1-Score cho từng cấu hình.
  - Lead time trung bình (số ngày phát hiện nguy cơ trước khi task thực sự bị trễ hạn).
- [ ] Xây dựng template Markdown báo cáo khoa học:
  - Bảng so sánh 3 cấu hình (Chỉ Luật vs Chỉ ML vs Tổ hợp Hybrid ERW).
  - Biểu đồ text / phân phối lead time cảnh báo sớm.
  - Danh sách các ca điển hình: ca mà luật bỏ sót nhưng ML bắt được, ca mà ML cảnh báo giả nhưng luật chặn lại được.
  - Ghi file ra `reports/sim-<instance>-<project>.md`.

### Task 4: CLI Interface & Smoke Test Toàn diện
- [ ] Gắn lệnh CLI `erw sim-eval`:
  - Tham số: `--instance <name> --project <key> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --output <path>`.
  - Hiển thị tiến trình trực quan qua terminal.
- [ ] Chạy thử nghiệm smoke test một khoảng thời gian mẫu (1-2 tuần) trên một dự án lịch sử có sẵn trong DuckDB.
- [ ] Kiểm tra kết quả báo cáo sinh ra đạt yêu cầu khoa học và đúng chuẩn SRS FR-V1.
