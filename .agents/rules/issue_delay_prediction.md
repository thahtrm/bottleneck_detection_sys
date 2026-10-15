---
description: "Quy chuẩn & Bài học kinh nghiệm huấn luyện hệ thống Machine Learning dự đoán nguy cơ trễ hạn Issue (Issue Delay Prediction) cho toàn bộ dataset Jira/TGN."
always_on: true
---

# QUY CHUẨN & BÀI HỌC KINH NGHIỆM HUẤN LUYỆN DỰ ĐOÁN TRỄ HẠN ISSUE (GENERALIZED FOR ALL DATASETS)

Tài liệu này đúc kết toàn bộ bài học thực nghiệm từ các pipeline XGBoost, Random Forest, Logistic Regression và Stacking Meta-Learner, áp dụng bắt buộc cho mọi lần huấn luyện tiếp theo trên toàn bộ các project/instances (JFrog, Apache, Spring, Mojang, MariaDB, Qt, RedHat, v.v.).

---

## 1. NGUYÊN TẮC ZERO TEMPORAL DATA LEAKAGE & CHRONOLOGICAL SPLIT

1. **Thứ tự phân chia thời gian bắt buộc**:
   - Dữ liệu luôn phải sắp xếp theo mốc thời gian tạo task (`created_ts`).
   - Phân chia bất biến: **70% Train** (quá khứ xa) $\rightarrow$ **15% Val** (quá khứ gần) $\rightarrow$ **15% Test** (mới nhất, out-of-time).
   - Tuyệt đối không dùng k-fold ngẫu nhiên (Shuffle / StratifiedKFold chuẩn) vì sẽ làm rò rỉ thông tin từ tương lai về quá khứ. Phải dùng `TimeSeriesSplit` hoặc Split tuần tự theo quý/năm.

2. **Khóa dữ liệu tiền xử lý (Strict Featurization Ordering)**:
   - Toàn bộ các bộ mã hóa (`TargetEncoder`, `OneHotEncoder`, `StandardScaler`, `RobustScaler`, `PowerTransformer`) phải được `fit` **DUY NHẤT** trên `train.parquet`.
   - Tuyệt đối không `fit_transform` trên toàn bộ tập dữ liệu trước khi split.

---

## 2. BẪY RIGHT-CENSORING & THIẾT LẬP THỜI HẠN KẾ HOẠCH (PLANNED DURATION / SLA)

1. **Tránh bẫy phân vị lịch sử tĩnh (Static Quantile Trap)**:
   - Trong dữ liệu Jira nguồn mở, trường `duedate` hầu như bị thiếu.
   - **CẤM**: Đặt planned duration bằng phân vị $P_{80}$ tĩnh của toàn bộ lịch sử (ví dụ $P_{80} = 1900$ ngày $\approx$ 5.2 năm). Nếu làm vậy, các issue tạo ở tập Test (chỉ được quan sát tối đa 1–2 năm trước khi dataset kết thúc) sẽ **không bao giờ đạt được 1900 ngày**, dẫn đến tỷ lệ mẫu dương ở tập Test bị sụt về $0\%$!
2. **Quy chuẩn Planned Duration / SLA thực tế (Operational Stationarity)**:
   - Phải gán Planned Duration tại thời điểm `created_ts` theo chu kỳ vận hành thực tế của ngành phần mềm:
     + **Blocker / Critical Bug**: 7 – 14 ngày.
     + **Major / High Bug / Task**: 21 – 30 ngày.
     + **Normal / Minor Bug**: 45 – 60 ngày.
     + **Requirements / New Feature**: 90 – 180 ngày.
   - Nhờ đó, tỷ lệ trễ hạn (`duration > planned_duration`) duy trì tính dừng (stationarity $\approx 40\% - 55\%$) trên cả 3 tập Train, Val và Test.

---

## 3. HIỆN TƯỢNG DỊCH CHUYỂN THỜI GIAN & THAY ĐỔI HÀNH VI (TEMPORAL SHIFT & UNASSIGNED DRIFT)

1. **Hiện tượng biến động nhân sự (Developer Turnover)**:
   - Các dự án phần mềm kéo dài từ 10–15 năm có sự thay đổi lớn về đội ngũ kỹ sư.
   - **CẤM**: Sử dụng mã định danh cá nhân `assignee_id` làm đặc trưng học máy trực tiếp, vì mô hình sẽ học thuộc lòng các kỹ sư của 10 năm trước và hoàn toàn mất phương hướng với các kỹ sư mới ở tập Test.
2. **Hiện tượng trôi phân phối nhóm `(unassigned)`**:
   - Ở giai đoạn đầu (Train), task unassigned thường bị bỏ quên (tỷ lệ trễ hạn $> 90\%$).
   - Ở giai đoạn sau (Test), dự án áp dụng bot triage và quy trình đóng nhanh, khiến task unassigned được xử lý nhanh hơn (tỷ lệ trễ sụt xuống $\approx 45\%$).
   - **Giải pháp**:
     + Không để cây quyết định phụ thuộc duy nhất vào cờ `is_unassigned`.
     + Phải kết hợp cờ này với các điều kiện ràng buộc: `sp_planned_ratio`, `scf`, và độ phức tạp văn bản `summary_len`.
     + Áp dụng ngưỡng quyết định động (Dynamic Threshold) với mức penalty bổ sung cho nhóm unassigned.

---

## 4. BỘ ĐẶC TRƯNG CHUẨN HÓA BỀN VỮNG (STATIONARY FEATURE SUITE)

Khi mở rộng ra toàn bộ 16 instances của `ThePublicJiraDataset`, bắt buộc trích xuất 5 nhóm đặc trưng cốt lõi:

1. **Nhóm Tắc nghẽn Tải làm việc (Assignee Workload)**:
   - `assignee_wci`: Tổng tải điểm story points còn lại chia cho số ngày đến hạn.
   - `active_per_completed`: Tỷ số giữa số task đang mở và số task đã hoàn thành trong quá khứ (**Đặc trưng SHAP số 1**).
   - `assignee_active_count`: Số task active đang đồng thời đảm nhiệm.
2. **Nhóm Nén Thời hạn (Schedule Compression)**:
   - `scf` (Schedule Compression Factor): $\text{PlannedDurationDays} / \max(1, \text{AssigneeHistCycleTime})$. Khi $\text{scf} < 0.6$, rủi ro trễ hạn tăng vọt.
   - `cycle_minus_planned`: Chênh lệch giữa chu kỳ xử lý trung bình của lập trình viên và thời hạn được giao.
3. **Nhóm Mạng lưới Phụ thuộc (Graph Dependency Centrality)**:
   - `blocks_count`, `depends_count`, `has_block_or_depend`, `total_deps`.
   - Task bị chặn (blocked) hoặc đang chặn task khác có độ ứ đọng dây chuyền (Blast Radius) rất cao.
4. **Nhóm Tương tác Quy mô & Kế hoạch**:
   - `sp_planned_ratio` ($\text{StoryPoints} / \text{PlannedDuration}$): Mật độ khối lượng công việc trên mỗi đơn vị thời gian.
   - `sp_planned_product` ($\text{StoryPoints} \times \text{PlannedDuration}$): Quy mô tổng thể của task.
5. **Nhóm Độ mơ hồ Yêu cầu (NLP Ambiguity & Complexity)**:
   - `ambiguity_score`: Tần suất xuất hiện các từ ngữ mơ hồ ("maybe", "could", "should", "consider", "optional", "investigate", "tbd").
   - `summary_len`, `word_count`, `chars_per_word`.

---

## 5. CHIẾN LƯỢC MÔ HÌNH HÓA & STACKING META-LEARNER

1. **Khắc phục trần hiệu năng của mô hình đơn lẻ**:
   - Các mô hình đơn lẻ (XGBoost, Random Forest, Logistic Regression) thường chỉ đạt $F_1 \approx 0.61 - 0.64$ trên tập Out-of-time Test do ảnh hưởng của temporal shift.
2. **Bắt buộc triển khai Track 4 Stacking Meta-Learner**:
   - Thu thập xác suất dự đoán $P_{xgb}, P_{rf}, P_{lr}$ từ 3 họ thuật toán độc lập để tận dụng tối đa **Error Diversity** (đặc biệt Logistic Regression mang lại tương quan thấp $\approx 0.55 - 0.62$, cung cấp tín hiệu bổ khuyết cực mạnh).
   - Không gian đặc trưng Meta:
     + Xác suất cơ sở: $P_{xgb}, P_{rf}, P_{lr}$.
     + Độ bất đồng thuận (Model Disagreement): $|P_{xgb} - P_{rf}|$, $|P_{xgb} - P_{lr}|$, $|P_{rf} - P_{lr}|$.
     + Tương tác tích số: $P_{xgb} \times P_{rf}$, $P_{xgb} \times P_{lr}$.
     + Đặc trưng hiệu chỉnh: `priority_norm`, `sp_planned_ratio`, `is_unassigned`.
   - Huấn luyện Meta-Classifier (LightGBM / Logistic Regression điều chuẩn) kết hợp **Fine-grained Threshold Sweep** trên tập Validation.
   - Kết quả: Stacking đẩy **PR-AUC lên 0.612**, **ROC-AUC lên 0.679**, giảm **Brier Score xuống 0.234**, và giữ vững **Recall $\ge 0.82$**.

---

## 6. QUY TRÌNH THỰC THI CHUẨN TRÊN GIT WORKTREES

- Khi thử nghiệm các nhánh thuật toán mới, luôn khởi tạo các Git Worktrees độc lập:
  ```bash
  git worktree add ../worktree-<track> -b experiment/<track>-pipeline
  ```
- Dùng chung kho dữ liệu parquet và virtual environment qua symlink (`ln -s`).
- Đánh giá thống nhất bằng `evaluation_harness.py` cập nhật vào `experiments/leaderboard.json`.
- Sau khi hoàn tất và kích hoạt Stacking, dọn dẹp worktrees bằng `git worktree remove --force` và merge pipeline vào `main`.
