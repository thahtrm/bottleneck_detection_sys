# BÁO CÁO KINH NGHIỆM & QUY CHUẨN MỞ RỘNG HUẤN LUYỆN DỰ ĐOÁN TRỄ HẠN ISSUE
## HƯỚNG DẪN MỞ RỘNG TOÀN DIỆN CHO TOÀN BỘ 16 DỰ ÁN CỦA THE PUBLIC JIRA DATASET

---

### 1. BỐI CẢNH & MỤC TIÊU MỞ RỘNG

Thực nghiệm trên `JFrog` (10,229 issues) đã chứng minh tính hiệu quả của quy trình điều phối đa tác tử, kiến trúc Stacking Meta-Learner và phân tách môi trường qua Git Worktrees. Tuy nhiên, khi mở rộng ra toàn bộ 16 instances của `data/jira.duckdb` (với hơn 2.68 triệu issues từ Apache, Mojang, Spring, MongoDB, MariaDB, Qt, RedHat, v.v.), hệ thống phải đối mặt với các đặc thù phân phối phức tạp hơn:

1. **Quy mô dữ liệu (Scale)**:
   - Apache: 1,014,909 issues
   - Mojang: 420,814 issues
   - RedHat: 352,997 issues
   - Jira Ecosystem: 274,535 issues
   - Qt: 148,578 issues
   - MongoDB: 137,150 issues
   - Sonatype: 87,284 issues
   - Spring: 69,156 issues
   - MariaDB: 31,228 issues
   - Hyperledger: 28,146 issues

2. **Mục tiêu**:
   - Chuyển hóa toàn bộ bài học thành quy chuẩn công nghệ có thể áp dụng nhất quán trên bất kỳ instance nào.
   - Ngăn chặn triệt để hiện tượng rò rỉ dữ liệu thời gian, bẫy Right-Censoring và Overfitting định danh nhân sự.

---

### 2. TỔNG HỢP 4 BÀI HỌC KINH NGHIỆM CỐT LÕI (CORE LESSONS LEARNED)

#### Bài học 1: Bẫy Phân vị Lịch sử Tĩnh (Right-Censoring Trap)
- **Vấn đề**: Trong dữ liệu Jira mở, trường `duedate` hầu như bị khuyết. Nếu đặt SLA trễ hạn bằng phân vị thời gian xử lý toàn lịch sử (ví dụ $P_{80} = 1900$ ngày $\approx 5.2$ năm), các issue ở tập Test (chỉ được theo dõi 1–2 năm trước khi dataset dừng ghi nhận) không thể đạt mốc 1900 ngày $\rightarrow$ Positive rate ở Test sụt về 0%.
- **Quy chuẩn**: Luôn xác định **Planned Duration / SLA** dựa trên chu kỳ vận hành thực tế tại thời điểm `created_ts`:
  - `Critical / Blocker`: 7 – 14 ngày
  - `High / Major`: 21 – 30 ngày
  - `Normal / Minor`: 45 – 60 ngày
  - `Feature / Requirement`: 90 – 180 ngày
  - `Task / Sub-task`: 14 – 21 ngày
- **Kết quả**: Duy trì tính dừng phân phối mẫu dương ($\approx 40\% - 55\%$) trên cả 3 tập Train, Val và Test.

---

#### Bài học 2: Hiện tượng Dịch chuyển Phân phối Nhóm Unassigned (Unassigned Drift)
- **Vấn đề**:
  - Giai đoạn đầu (Train 2006–2018): Các issue `(unassigned)` thường bị bỏ quên trong backlog với tỷ lệ trễ hạn lên tới **90.7%**.
  - Giai đoạn sau (Test 2020–2022): Áp dụng bot tự động triage và quy trình dọn dẹp task nhanh, khiến tỷ lệ trễ của nhóm unassigned giảm sốc xuống còn **45.5%**.
  - Cây quyết định học quy luật quá khứ đã dự đoán rủi ro trễ rất cao cho nhóm unassigned, tạo ra **67.7% tổng số False Positives** trên Test set.
- **Quy chuẩn**:
  - Tuyệt đối không để cây quyết định phân nhánh thuần túy dựa vào cờ `is_unassigned`.
  - Phải ràng buộc tương tác với quy mô task (`sp_planned_ratio`) và độ phức tạp văn bản (`summary_len`).
  - Áp dụng hiệu chuẩn xác suất (Probability Calibration) hoặc Dynamic Thresholding điều chỉnh ngưỡng phân loại cho nhóm unassigned.

---

#### Bài học 3: Tránh Học Thuộc Lòng Nhân Sự (Developer Turnover Overfitting)
- **Vấn đề**: Các dự án phần mềm trải dài 15 năm có sự luân chuyển nhân sự gần như hoàn toàn. Nếu mô hình học trực tiếp theo `assignee_id`, mô hình sẽ thuộc lòng các kỹ sư của 10 năm trước và hoàn toàn mất phương hướng với kỹ sư mới ở tập Test.
- **Quy chuẩn**: Bắt buộc trừu tượng hóa định danh cá nhân thành các **chỉ số động thái tải tương đối**:
  - `active_per_completed`: Tỷ số giữa số task đang mở và số task đã giải quyết trong quá khứ (**Đặc trưng SHAP số 1, chiếm 46.2% trọng số giải thích**).
  - `assignee_wci`: Chỉ số tắc nghẽn tải làm việc (Workload Congestion Index).
  - `scf`: Hệ số nén thời gian (Schedule Compression Factor).

---

#### Bài học 4: Sức mạnh Bắt buộc của Track 4 Stacking Meta-Learner
- **Vấn đề**: Do sự thay đổi văn hóa dự án qua 15 năm, một mô hình đơn lẻ (kể cả XGBoost tinh chỉnh Bayesian Optuna) sẽ chạm ngưỡng bão hòa ở mức $F_1 \approx 0.61 - 0.64$ trên tập Test.
- **Quy chuẩn**: Bắt buộc kết hợp **3 họ thuật toán độc lập** để khai thác **Error Diversity**:
  - `XGBoost`: Bắt tương tác phi tuyến cục bộ sắc nhọn.
  - `Random Forest + SMOTE`: Kháng nhiễu ngoại lai, ổn định phương sai.
  - `Logistic Regression + Splines`: Nắm bắt các xu hướng tuyến tính vĩ mô (tạo tương quan xác suất thấp $r \approx 0.55$, bổ trợ cực mạnh).
  - `Meta-Learner`: Tiếp nhận xác suất cơ sở, độ bất đồng thuận ($|P_{xgb} - P_{rf}|$, $|P_{xgb} - P_{lr}|$) và các đặc trưng chuẩn hóa nghiệp vụ để sửa sai, giúp đẩy **PR-AUC lên 0.612**, **ROC-AUC lên 0.679**, giảm **Brier Score xuống 0.234**, và giữ vững **Recall $\ge 0.82$**.

---

### 3. KIẾN TRÚC MÃ NGUỒN TIÊU CHUẨN

```
├── prepare_dataset.py       # Trích xuất và phân chia thời gian 70/15/15 bất biến
├── evaluation_harness.py    # Bộ chấm điểm thống nhất, quét ngưỡng tối ưu trên Val
├── train_xgboost.py         # Track 1: Gradient Boosting + Optuna + SHAP
├── train_rf.py              # Track 2: Random Forest + Bagging & In-CV Resampling
├── train_logreg.py          # Track 3: ElasticNet + Splines + PowerTransformer
├── stacking_meta_learner.py # Track 4: Stacking Meta-Classifier kết hợp đa mô hình
└── experiments/
    └── leaderboard.json     # Bảng tổng sắp trung tâm
```

---
*Tài liệu được ban hành bởi Master ML Orchestrator.*
