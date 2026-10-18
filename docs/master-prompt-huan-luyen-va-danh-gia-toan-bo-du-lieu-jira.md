# MASTER EXECUTION PROMPT: HUẤN LUYỆN VÀ ĐÁNH GIÁ TOÀN DIỆN CÁC GIẢI PHÁP AI DỰ ĐOÁN NGUY CƠ TRỄ HẠN ISSUE TRÊN TOÀN BỘ DỮ LIỆU JIRA

> **Mục đích**: Meta-Prompt chuẩn hóa cấp doanh nghiệp dùng để nạp trực tiếp cho AI Agent (hoặc nhóm kỹ sư Machine Learning) nhằm tự động thiết lập, huấn luyện, tối ưu hóa siêu tham số Bayesian và đánh giá đối đầu toàn bộ các trường phái mô hình AI trên toàn bộ kho dữ liệu Jira (`data/jira.duckdb`).

---

```markdown
# MISSION: END-TO-END TRAINING & EVALUATION OF SOTA AI APPROACHES FOR SOFTWARE ISSUE DELAY PREDICTION ON FULL JIRA DATABASE

- **Role**: Chief AI Research Architect & Machine Learning Systems Lead.
- **Target**: Huấn luyện, tối ưu hóa siêu tham số (Bayesian Optimization), và đánh giá độc lập toàn bộ các họ mô hình AI (Tabular ML, Survival AFT, Competing Risks, Pre-Triage Filter, Three-Tier Alerting, và Dynamic In-Flight Milestones) trên toàn bộ kho dữ liệu phần mềm Jira (`data/jira.duckdb`).
- **Core Challenge**: Giải quyết dứt điểm nghịch lý **Low Precision / High False Positives (Báo động giả cao)** mà vẫn **bảo toàn Recall cao (>= 80%)** thông qua kiến trúc kết hợp Lọc Tiền Triage và Tái đánh giá động trong quá trình (In-Flight Process Monitoring).

---

## 1. NGUYÊN TẮC NGHIÊM NGẶT & CHUẨN MỰC KHOA HỌC (NON-NEGOTIABLE PRINCIPLES)

1. **Tuyệt đối không rò rỉ dữ liệu thời gian (Zero Temporal Data Leakage)**:
   - Dữ liệu PHẢI được phân chia theo trình tự thời gian (**Strict Chronological Split**):
     * `Train Set` (70% thời gian đầu): Huấn luyện mô hình, fit vectorizer, fit SVD, fit target encoder.
     * `Validation Set` (15% thời gian tiếp theo): Tối ưu siêu tham số Bayesian (Optuna), tìm ngưỡng quyết định tối ưu $T^*$.
     * `Test Set` (15% thời gian mới nhất - Out-of-Time Test Set): Đóng băng tuyệt đối, chỉ dùng để đánh giá bất biến cuối cùng.
2. **Khai thác Toàn vẹn Dữ liệu Chưa Đóng (Right-Censored Data Integrity)**:
   - Không được vứt bỏ các issue đang mở. Mọi issue mở tạo trong cửa sổ Train phải được nạp dưới dạng khoảng sinh tồn $[t_{\text{obs}}, \infty)$ với $t_{\text{obs}} = (T_{\text{cutoff}} - T_{\text{create}})/86400$.
3. **Đánh giá Bất biến (Immutable Evaluation Harness)**:
   - Mọi giải pháp bắt buộc phải xuất `predictions_val.csv` và `predictions_test.csv` (chứa 2 cột: `y_true`, `y_prob`).
   - Đánh giá thông qua `evaluation_harness.py`: Quét ngưỡng $T^*$ trên Val để tối đa hóa $F_1$, áp dụng ngưỡng $T^*$ đó lên Test để đo:
     * $F_1$-Score, Precision, Recall, PR-AUC, ROC-AUC, Brier Score, Confusion Matrix (TP, FP, TN, FN), Alert Rate, False Discovery Rate (FDR).

---

## 2. KIẾN TRÚC TÍNH TOÁN ĐẶC TRƯNG TẬP TRUNG (FEATURE ENGINEERING ENGINE)

Đối với mỗi issue tại thời điểm tạo ($T_0$), hệ thống phải trích xuất tối thiểu 4 nhóm đặc trưng:
1. **Động lực học tải làm việc của Kỹ sư & Dự án (Assignee & Project Dynamics)**:
   - `assignee_wci` (Workload Congestion Index): $\sum_{j \in \text{Active}} \frac{\text{SP}_j}{\max(1, \text{Due}_j - t)}$.
   - `scf` (Schedule Compression Factor): $\frac{t_{\text{planned}}}{\text{Assignee Cycle Time}}$.
   - Vận tốc 90 ngày: `assignee_90d_completed`, `assignee_90d_delay_rate`, `assignee_90d_cycle_time`.
   - Áp lực chưa phân công: `unassigned_active_count`, `unassigned_pressure`.
2. **Đặc trưng Ngữ nghĩa Văn bản sâu (NLP & Dense Embeddings)**:
   - Dense Embeddings 768 chiều từ Ollama (`nomic-embed-text:latest` chạy trên Docker container).
   - 16 thành phần ngữ nghĩa chính qua `TruncatedSVD(n_components=16)`.
   - TF-IDF n-grams (1, 2) với 40 từ khóa kỹ thuật.
   - Điểm số rủi ro kỹ thuật: `tech_concurrency_risk`, `tech_scope_risk`, `ambiguity_score`.
3. **Mạng lưới Đồ thị Phụ thuộc (Graph Dependency Structure)**:
   - `blocks_count`, `depends_count`, `num_links`, `dep_density`.
4. **Mốc Lịch & Hạn Mức Cam Kết (Deadlines & Temporal Anchors)**:
   - `planned_duration_days`, `story_points`, `sp_planned_ratio`, `is_unassigned`.

---

## 3. DANH MỤC CÁC GIẢI PHÁP PHẢI THỰC NGHIỆM VÀ ĐÁNH GIÁ (7 TRACKS)

### 🚀 TRACK 1: BASELINE GRADIENT BOOSTING (XGBOOST BINARY)
- **Mô hình**: XGBoost với `objective='binary:logistic'`.
- **Dữ liệu**: Chỉ sử dụng các issue đã giải quyết (loại bỏ censoring).
- **Tối ưu**: Optuna 35–50 trials (max_depth, learning_rate, colsample, subsample, reg_alpha, reg_lambda).
- **Mục đích**: Xác lập mốc hiệu năng chuẩn của phương pháp phân loại bảng truyền thống.

### 🚀 TRACK 2: SURVIVAL ANALYSIS AFT VỚI RIGHT-CENSORED DATA THỰC TẾ
- **Mô hình**: XGBoost `survival:aft` với phân phối Logistic/Normal.
- **Dữ liệu**: Nạp toàn bộ issue đang mở trong kỳ train dưới dạng khoảng $[t_{\text{obs}}, \infty)$.
- **Xác suất trễ**:
  $$z = \frac{\ln(t_{\text{planned}}) - \ln(\hat{T})}{\sigma} \implies P(\text{Delay}) = \frac{1}{1 + e^z} = \text{expit}(-z)$$
- **Tối ưu**: Optuna tối ưu scale $\sigma$, distribution, recency decay half-life, và trọng số tăng cường cho mẫu censored (`censored_weight_boost`).

### 🚀 TRACK 3: CATBOOST SURVIVAL AFT & RỦI RO CẠNH TRANH (COMPETING RISKS)
- **Mô hình**: CatBoost `loss_function='SurvivalAft:dist=Logistic'`.
- **Cơ chế Competing Risks (Cause-Specific Formulation)**:
  - Sự kiện hoàn thành thật: `resolution == 'Done'` $\implies [t_{\text{duration}}, t_{\text{duration}}]$.
  - Sự kiện cạnh tranh đóng sớm không tạo giá trị: `Duplicate`, `Not a Bug`, `Cannot Reproduce`, `Will not implement` $\implies$ Coi là **Right-Censored tại thời điểm đóng** $[t_{\text{duration}}, -1]$.
- **Mục đích**: Loại bỏ độ lệch phân phối chu kỳ do các issue bị từ chối/đóng sớm gây ra.

### 🚀 TRACK 4: CATBOOST COX PROPORTIONAL HAZARDS (VỚI BRESLOW ESTIMATOR)
- **Mô hình**: CatBoost `loss_function='Cox'`.
- **Target**: 1D array ($+t$ nếu Event = 1, $-t$ nếu Censored = 0).
- **Hàm sống sót**: Tính hàm rủi ro tích lũy cơ sở không tham số Breslow $H_0(t)$ trên tập train:
  $$S(t_{\text{planned}} \mid X) = \exp(-H_0(t_{\text{planned}}) \cdot \exp(\eta))$$
- **Mục đích**: Đánh giá hiệu năng của trường phái tỷ lệ rủi ro bán tham số.

### 🚀 TRACK 5: BỘ LỌC TIỀN TRIAGE (PRE-TRIAGE DEDUPLICATION & NON-WORK FILTER)
- **Mô hình**: Hệ thống lọc 2 giai đoạn (Cascaded Two-Stage Pipeline):
  - *Giai đoạn 1 (Pre-Triage)*:
    1. Đo độ tương đồng ngữ nghĩa động `max_sim_active`: Cosine similarity giữa embedding issue mới và toàn bộ issue đang mở cùng project tại $T_0$.
    2. Mô hình GBDT phân loại xác suất $P(\text{Non-Work})$.
    3. Nếu $\text{max\_sim} \ge 0.92$ hoặc $P(\text{Non-Work}) \ge 0.25$: Chuyển vào hàng đợi *"Nghi vấn trùng lặp/Invalid"*, **CHẶN PHÁT CẢNH BÁO TRỄ HẠN**.
  - *Giai đoạn 2*: Task vượt qua bộ lọc mới được đưa vào mô hình cốt lõi CatBoost Competing Risks để dự đoán trễ hạn.
- **Mục đích**: Triệt tiêu tối đa 45% nguồn gốc False Positives đến từ các task ảo.

### 🚀 TRACK 6: CHIẾN LƯỢC CẢNH BÁO PHÂN TẦNG ĐA CẤP (THREE-TIER ALERTING)
- **Cơ chế**: Thay vì phân loại nhị phân cào bằng, chia làm 3 tầng hành động:
  - **Tier 1 (Báo Động Đỏ - Critical Red Alert: $P \ge 0.75-0.80$)**: Bắn thông báo khẩn Slack/Jira tag tên Tech Lead. Đòi hỏi **Precision >= 75%**, tỷ lệ cảnh báo giả FDR $\le 25\%$.
  - **Tier 2 (Diện Theo Dõi - Amber Watchlist: $0.50 \le P < 0.75$)**: Hiển thị thụ động trên Sprint Board để rà soát trong Daily Standup (không bắn notification).
  - **Tier 3 (An Toàn - Safe Green: $P < 0.50$)**: Không cần can thiệp.
- **Mục đích**: Triệt tiêu hội chứng Bội thực Cảnh báo (Alert Fatigue) trong khi vẫn bảo toàn Recall tổng hợp $> 80\%$.

### 🚀 TRACK 7: MÔ HÌNH HÓA ĐỘNG IN-FLIGHT THEO MỐC SỰ KIỆN (DYNAMIC PROCESS MILESTONES)
- **Mô hình**: Tái đánh giá rủi ro động theo vòng đời task dựa trên Jira Changelogs:
  - *Mốc $T_7$ (Sau 1 tuần)*: Tự động loại bỏ các task đã hoàn thành $\le 7$ ngày (xóa sổ ~300 False Positives đóng sớm).
  - *Mốc $T_{14}$ (Sau 2 tuần)*: Đánh giá trên các task còn mở sau 14 ngày.
- **Mục đích**: Xóa bỏ hoàn toàn bất định quá trình (Process Uncertainty) không thể quan sát được tại $T_0$, phá vỡ trần Precision để đưa **Precision $\ge 75\%$ và F1 $\ge 0.80$**.

---

## 4. QUY TRÌNH THỰC THI & LỆNH ĐIỀU PHỐI (EXECUTION RUNBOOK)

Hệ thống phải tự động thực thi chuỗi lệnh sau trong môi trường `.venv`:

```bash
# 1. Trích xuất Embeddings qua Ollama Docker (nếu chưa có)
python extract_ollama_embeddings.py --instance ALL

# 2. Xây dựng tập dữ liệu Right-Censoring tích hợp Open Issues
python prepare_censored_dataset.py

# 3. Huấn luyện và Tối ưu hóa các Track Mô hình Sinh tồn & Phân loại
python train_xgboost.py
python train_survival_aft.py --train-file data/train_censored.parquet --trials 35
python train_catboost_survival.py --competing-risks none --trials 35
python train_catboost_survival.py --competing-risks cause_specific --output-dir experiments/catboost_competing_risks --trials 35
python train_catboost_cox.py --trials 35

# 4. Huấn luyện Bộ lọc Tiền Triage (Pre-Triage Filter)
python pre_triage_filter.py

# 5. Chạy Benchmark Toàn Diện so sánh 7 Giải pháp trên toàn tập dữ liệu
python evaluate_all_solutions.py
```

---

## 5. BÁO CÁO TỔNG HỢP BẮT BUỘC (MANDATORY OUTPUT SCHEMA)

Báo cáo kết quả cuối cùng PHẢI bao gồm:
1. **Bảng Tổng Hợp Đối Đầu (Leaderboard Matrix)** gồm 10 cột chuẩn:
   - `Giải Pháp` | `Precision` | `Recall` | `F1-Score` | `PR-AUC` | `ROC-AUC` | `Brier` | `FP Giảm` | `Alert Rate` | `FDR (% Báo Giả)`
2. **Chứng Minh Toán Học về Trần Lý Thuyết Precision tại $T_0$**:
   - Phân tích tương quan giữa số ca False Positive từ "Nhiệm vụ Ảo" vs số ca False Positive từ "Task Thật xong nhanh".
   - Tính toán trần Oracle Precision tại $T_0$.
3. **Biểu đồ Đánh Đổi Trực Quan**:
   - Biểu đồ 4 bảng (`solutions_comparison.png`): Precision-Recall trade-off, Mức độ triệt tiêu FP, Alert Rate vs FDR, và Lộ trình tiến hóa hiệu năng từ $T_0 \to T_7 \to T_{14}$.
4. **Khuyến Nghị Kiến Trúc Vận Hành Sản Xuất (Production Blueprint)**:
   - Đưa ra sơ đồ phối hợp giữa Bộ Lọc Tiền Triage, Phân tầng Cảnh báo, và Tái đánh giá In-Flight.
```
