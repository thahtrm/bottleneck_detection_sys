# BÁO CÁO NGHIÊN CỨU KHOA HỌC: GIẢI PHÁP ĐỊNH LƯỢNG ĐỘ TRỌNG YẾU TÁC VỤ (TASK CRITICALITY), ĐÁNH GIÁ NGUY CƠ TRỄ DÂY CHUYỀN VÀ HỆ THỐNG CHỈ SỐ ĐÁNH GIÁ (EVALUATION METRICS)

> **Dự án**: Nghiên cứu Hệ thống Học máy Dự đoán Nguy cơ Trễ hạn và Định lượng Độ trọng yếu Tác vụ trong Quản trị Dự án Phần mềm  
> **Cơ sở dữ liệu**: The Public Jira Dataset (Tập thí điểm Spring Framework: 69.154 issues, 1.781 links `Depend` trong `data/jira.duckdb`)  
> **Mã nguồn thực thi**: [`track1_cpm.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track1_cpm.py), [`track2_simulation.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track2_simulation.py), [`track3_tgn.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track3_tgn.py), [`track4_ranker.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track4_ranker.py), [`track5_hybrid_meta.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track5_hybrid_meta.py), [`data/build_criticality_ground_truth.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/data/build_criticality_ground_truth.py), [`evaluation_harness_criticality.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/evaluation_harness_criticality.py)

---

## MỤC LỤC CHI TIẾT

1. [PHẦN 1: NGHIÊN CỨU GIẢI PHÁP XÁC ĐỊNH TASK QUAN TRỌNG VÀ NGUY CƠ TRỄ DÂY CHUYỀN](#phần-1-nghiên-cứu-giải-pháp-xác-định-task-quan-trọng-và-nguy-cơ-trễ-dây-chuyền)
   - 1.1. Đặt Vấn Đề & Nghịch Lý trong Đánh Giá Trọng Yếu
   - 1.2. Khung Lý Thuyết & Bản Chất Toán Học
   - 1.3. Kiến Trúc 5 Hướng Tiếp Cận (5 Research Tracks)
   - 1.4. Bảng Đối Đầu Hiệu Năng Thực Nghiệm (Out-of-Time Test Set)
   - 1.5. Phân Tích Thuộc Tính Chi Phối qua SHAP Values
2. [PHẦN 2: NGUỒN GỐC VÀ QUY TRÌNH THIẾT LẬP NHÃN CHUẨN (GROUND TRUTH LABELING)](#phần-2-nguồn-gốc-và-quy-trình-thiết-lập-nhãn-chuẩn-ground-truth-labeling)
   - 2.1. Tại Sao Không Dùng Trường `Priority` Có Sẵn trong Jira?
   - 2.2. Quy Trình 4 Bước Tạo Nhãn Hồi Cứu Khách Quan (Post-Mortem Graph Analysis)
   - 2.3. Hai Dạng Nhãn Đầu Ra: Điểm Liên Tục và Nhãn Báo Động Đỏ P0
   - 2.4. Nguyên Tắc Bất Biến: Hồi Cứu Tạo Nhãn vs. Tiên Đoán tại T_0
3. [PHẦN 3: GIẢNG GIẢI CHI TIẾT HỆ THỐNG CHỈ SỐ ĐÁNH GIÁ (EVALUATION METRICS)](#phần-3-giảng-giải-chi-tiết-hệ-thống-chỉ-số-đánh-giá-evaluation-metrics)
   - 3.1. Nhóm Metric Phân Loại Nhị Phân (Binary Classification)
   - 3.2. Nhóm Metric Xếp Hạng Thứ Bậc (Learning-to-Rank)
   - 3.3. Bảng Tổng Hợp So Sánh Toàn Bộ Metrics
4. [PHẦN 4: HÀM Ý ỨNG DỤNG THỰC TIỄN VÀ BÍ QUYẾT BẢO VỆ KHÓA LUẬN](#phần-4-hàm-ý-ứng-dụng-thực-tiễn-và-bí-quyết-bảo-vệ-khóa-luận)

---

# PHẦN 1: NGHIÊN CỨU GIẢI PHÁP XÁC ĐỊNH TASK QUAN TRỌNG VÀ NGUY CƠ TRỄ DÂY CHUYỀN

### 1.1. Đặt Vấn Đề & Nghịch Lý trong Đánh Giá Trọng Yếu
Trong quản trị dự án phần mềm truyền thống, "độ quan trọng" thường bị đánh đồng sai lệch với:
- **Trường Priority cảm tính**: Do người tạo thẻ (`reporter`) tự gán chủ quan; thực tế hơn 70% tickets đều được chọn ở mức *Major/High*.
- **Thời gian nằm lâu trong Backlog**: Một task nằm im 500 ngày nhưng không ai chờ đợi thì thực chất là **task rác**, không phải task trọng yếu.

**Định nghĩa chuẩn xác**: Trong kỹ nghệ phần mềm hiện đại, một task được coi là **Trọng yếu (Critical / P0)** khi và chỉ khi:
1. **Nằm trên Đường găng (Critical Path)**: Bất kỳ sự chậm trễ nào của nó cũng kéo lùi trực tiếp thời điểm bàn giao của toàn bộ milestone/release.
2. **Gây nguy cơ Trễ dây chuyền (Cascading Delay Impact)**: Đóng vai trò là tiền đề kỹ thuật (prerequisite) cản trở dòng chảy công việc của các task và kỹ sư hạ lưu trong mạng lưới phụ thuộc có hướng (DAG).

```
                    ┌───────────────────────────┐
                    │   Task u (Bị chậm trễ)    │
                    └─────────────┬─────────────┘
                                  │ (Blocks / Prerequisite)
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
┌──────────────────┐                              ┌──────────────────┐
│  Task v_1 (Chờ)  │                              │  Task v_2 (Chờ)  │
└────────┬─────────┘                              └────────┬─────────┘
         ▼                                                 ▼
┌──────────────────┐                              ┌──────────────────┐
│  Task w_1 (Chờ)  │                              │  Task w_2 (Chờ)  │
└────────┬─────────┘                              └────────┬─────────┘
         └────────────────────────┬────────────────────────┘
                                  ▼
                   ┌──────────────────────────────┐
                   │  MILESTONE / RELEASE BỊ TRỄ  │
                   └──────────────────────────────┘
```

---

### 1.2. Khung Lý Thuyết & Bản Chất Toán Học

Nghiên cứu mô hình hóa các mối quan hệ phụ thuộc trong dự án dưới dạng **Đồ thị có hướng (Directed Acyclic Graph - DAG)** G = (V, E), trong đó mỗi cạnh (u, v) thuộc E thể hiện rằng task u chặn task v (u là tiền đề của v).

#### 1. Thời gian Dự trữ Tổng (Total Slack Time - S_u) qua thuật toán CPM
Áp dụng phương pháp Đường găng (Critical Path Method - CPM) với hai lượt duyệt:
- **Lượt duyệt tiến (Forward Pass)**: Xác định thời điểm sớm nhất có thể bắt đầu (ES) và kết thúc (EF):
  ES_v = max(EF_u) với mọi cạnh (u, v) thuộc E
  EF_v = ES_v + d_v
- **Lượt duyệt lùi (Backward Pass)**: Xác định thời điểm muộn nhất phải bắt đầu (LS) và kết thúc (LF) mà không làm trễ dự án:
  LF_u = min(LS_v) với mọi cạnh (u, v) thuộc E
  LS_u = LF_u - d_u
- **Độ chùng thời gian (Slack Time - S_u)**:
  S_u = LS_u - ES_u (Độ chùng thời gian = Bắt đầu muộn nhất - Bắt đầu sớm nhất)
  *Khi S_u xấp xỉ 0 => Task u nằm trên **Đường găng**, không có độ chùng dự phòng.*

#### 2. Bán kính Lan tỏa Ảnh hưởng (Blast Radius)
Số lượng nhiệm vụ hạ lưu chịu tác động trực tiếp và bắc cầu nếu task u không hoàn thành:
BlastRadius(u) = Tổng số task con cháu hạ lưu chịu phụ thuộc trực tiếp hoặc gián tiếp
Chỉ số **Harmonic Downstream Decay** phản ánh độ suy giảm tác động theo khoảng cách tô-pô đồ thị:
HarmonicImpact(u) = Tổng [ 1 / khoảng_cách(u, v) ] với mọi v thuộc nhóm hạ lưu

#### 3. Độ Trượt Lịch biểu Biên của Dự án (Marginal Schedule Slippage - Delta_D_u)
Thước đo khách quan nhất định lượng thiệt hại khi task u trễ:
Delta_D_u = max( 0, Ngày kết thúc dự án thực tế - Ngày kết thúc dự án khi u hoàn thành đúng hạn )

---

### 1.3. Kiến Trúc 5 Hướng Tiếp Cận (5 Research Tracks)

```
                                  ┌─────────────────────────────┐
                                  │   DỮ LIỆU DỰ ÁN TẠI T_0     │
                                  └──────────────┬──────────────┘
                                                 │
          ┌──────────────────┬───────────────────┼───────────────────┬──────────────────┐
          ▼                  ▼                   ▼                   ▼                  ▼
   ┌──────────────┐   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   ┌──────────────┐
   │   TRACK 1    │   │   TRACK 2    │    │   TRACK 3    │    │   TRACK 4    │   │   TRACK 5    │
   │  Cấu trúc    │   │  Mô phỏng    │    │ Mạng Đồ thị  │    │  Học Máy     │   │   HYBRID     │
   │  Đường găng  │   │  Monte Carlo │    │  Động (TGN)  │    │  Xếp Hạng    │   │  STACKING    │
   │    (CPM)     │   │  (Cascade)   │    │ (Deep Graph) │    │ (LambdaRank) │   │ META-RANKER  │
   └──────┬───────┘   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘   └──────┬───────┘
          │                  │                   │                   │                  │
          └──────────────────┴───────────────────┼───────────────────┴──────────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │   ĐIỂM TRỌNG YẾU TỔNG HỢP   │
                                  │   NDCG@10 = 0.9966          │
                                  │   Precision@Top-5% = 77.26% │
                                  └─────────────────────────────┘
```

- **Track 1: Topological DAG & CPM Specialist** ([`track1_cpm.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track1_cpm.py)): Tiếp cận tất định hình học. Tính toán S_u, chuẩn hóa SlackScore_u = e^(-S_u / 14) và bổ sung áp lực lịch biểu tiên nghiệm tại thời điểm tạo (T_0): Hệ số nén thời gian SCF = PlannedDuration / HistoricalCycleTime.
- **Track 2: Cascading Monte Carlo Specialist** ([`track2_simulation.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track2_simulation.py)): Tiếp cận ngẫu nhiên. Huấn luyện mô hình Phân tích Sinh tồn (Survival AFT Log-Logistic), chạy N=300 vòng mô phỏng Monte Carlo để đo lường xác suất lan truyền trễ dọc các mắt xích DAG.
- **Track 3: Temporal Graph Network (TGN) Specialist** ([`track3_tgn.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track3_tgn.py)): Tiếp cận học sâu trên đồ thị động liên tục. Bộ nhớ node liên tục (GRU 128 chiều) kết hợp Temporal Graph Attention nắm bắt tương tác cộng tác thực thời và nhịp độ issue.
- **Track 4: Learning-to-Rank LGBMRanker Specialist** ([`track4_ranker.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track4_ranker.py)): Tối ưu hóa trực tiếp hàm mục tiêu thứ bậc LambdaRank (NDCG@10) trên 67 đặc trưng bảng và văn bản NLP SVD.
- **Track 5: Hybrid Stacking Meta-Ranker** ([`track5_hybrid_meta.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/track5_hybrid_meta.py)): Học trọng số kết hợp tối ưu không âm (Non-Negative Least Squares - NNLS) trên tập Validation:
  Điểm dự đoán Hybrid = 0.6913 * TGN + 0.1730 * CPM + 0.1082 * Monte_Carlo + 0.0274 * LGBMRanker

---

### 1.4. Bảng Đối Đầu Hiệu Năng Thực Nghiệm (Out-of-Time Test Set)

Kiểm định mù trên **10.374 issues thuộc Spring Framework** (giai đoạn kiểm thử đóng băng 2017 – 2021) từ [`evaluation_harness_criticality.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/evaluation_harness_criticality.py):

| Hạng | Giải pháp / Mô hình | NDCG@10 (Global) | NDCG@10 (Grouped) | Precision@Top-5% (Cảnh báo P0 đúng) | Recall@Top-5% (Bắt trúng P0) | Spearman Rank rho | PR-AUC (P0 Alert) | ROC-AUC | Trạng thái Mục tiêu |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 🥇 **1** | **Track 5: Hybrid Stacking Meta-Ranker** | **0.9966** | **0.9337** | **77.26% (401/519)** | **79.25%** | **0.7606** | **0.8473** | **0.9781** | 🏆 **ALL PASS** |
| 🥈 **2** | **Track 3: Temporal Graph Network (TGN)** | **0.9929** | **0.9332** | 73.03% (379/519) | 74.90% | **0.7604** | 0.8101 | 0.9685 | 🌟 Top Standalone |
| 🥉 **3** | **Track 4: LGBMRanker (LambdaRank)** | 0.9885 | 0.8704 | 59.15% (307/519) | 60.67% | 0.5499 | 0.7119 | 0.9742 | High Capacity |
| 🎖️ **4** | **Track 2: Cascading Monte Carlo (AFT)** | 0.9577 | 0.8668 | 52.22% (271/519) | 53.56% | 0.5294 | 0.6039 | 0.9645 | Probabilistic |
| 🎖️ **5** | **Track 1: Topological DAG CPM Slack** | 0.9964 | 0.8386 | 42.00% (218/519) | 43.08% | 0.3933 | 0.5038 | 0.9293 | Structural Baseline |

---

### 1.5. Phân Tích Thuộc Tính Chi Phối qua SHAP Values

Phân tích giá trị giải thích mô hình (SHAP values) trích xuất từ [`experiments/track4_shap_top10.json`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/experiments/track4_shap_top10.json):
1. `priority_norm` (Mean |SHAP| = 0.1089): Mức độ khẩn cấp cam kết ban đầu.
2. `story_points` (Mean |SHAP| = 0.0626): Quy mô độ phức tạp kỹ thuật.
3. `active_per_completed` (Mean |SHAP| = 0.0282): Tỷ số tải công việc của kỹ sư phụ trách.
4. `proj_enc` (Mean |SHAP| = 0.0238): Rủi ro lịch sử đặc thù của từng phân hệ con.
5. `assignee_active_count` (Mean |SHAP| = 0.0233): Số lượng task đồng thời đang đè nặng lên kỹ sư.
6. `project_90d_completed` (Mean |SHAP| = 0.0228): Vận tốc hoàn thành của dự án gần đây.
7. `assignee_hist_completed` (Mean |SHAP| = 0.0130): Thâm niên và năng lực xử lý của lập trình viên.
8. `blocks_count` (Mean |SHAP| = 0.0121): Số lượng task hạ lưu bị chặn trực tiếp.
9. `type_enc` (Mean |SHAP| = 0.0112): Phân loại thể loại công việc.
10. `assignee_90d_completed` (Mean |SHAP| = 0.0110): Năng suất ngắn hạn của người nhận việc.

---

# PHẦN 2: NGUỒN GỐC VÀ QUY TRÌNH THIẾT LẬP NHÃN CHUẨN (GROUND TRUTH LABELING)

### 2.1. Tại Sao Không Dùng Trường `Priority` Có Sẵn trong Jira?
- Trường `Priority` trong Jira được điền hoàn toàn theo cảm quan chủ quan của người tạo thẻ (`reporter`), thiếu căn cứ toán học.
- Đa phần các ticket đều được gắn nhãn `Major`, làm mất tính phân tách.
- Do đó, để có một thang đo khách quan, đề tài xây dựng quy trình gán nhãn hồi cứu (**Post-Mortem Analysis**) độc lập cài đặt tại [`data/build_criticality_ground_truth.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/data/build_criticality_ground_truth.py).

---

### 2.2. Quy Trình 4 Bước Tạo Nhãn Hồi Cứu Khách Quan

Khi nhìn lại dữ liệu lịch sử sau khi các task đã đóng, ta nắm giữ 100% sự thật: mốc bắt đầu thực tế (C_i), mốc kết thúc thực tế (R_i), và mạng lưới quan hệ phụ thuộc đầy đủ:

1. **Bước 1: Tái thiết Đồ thị Phụ thuộc Thực tế (Realized DAG)**: Nối cạnh có hướng t \to s nếu task t là điều kiện tiên quyết chặn task s.
2. **Bước 2: Phân tích Đường găng CPM Thực tế**: Duyệt tiến/lùi để xác định chính xác thời gian dự trữ S_u. Nếu S_u = 0, task u nằm trên đường găng.
3. **Bước 3: Mô phỏng Phản thực tế (Counterfactual Forward Pass)**: Giả định task u không bị trễ mà hoàn thành đúng hạn u_{\text{plan}}, đo lường sự rút ngắn thời gian bàn giao của toàn dự án (Delta_D_u).
4. **Bước 4: Tính Bán kính Lan tỏa và Trễ dây chuyền**: Tính tổng độ trễ của các task hạ lưu có trọng số suy giảm theo khoảng cách topo: Tổng_{v} \frac{\text{Slip}_u}{\text{dist}(u, v)} + \frac{\text{Slip}_v}{\text{dist}(u, v) + 1}.

---

### 2.3. Hai Dạng Nhãn Đầu Ra

1. **Điểm Trọng Yếu Liên Tục (`ground_truth_criticality` thuộc [0.0, 1.0])**:
   - Tổng hợp có trọng số từ Delta_D_u, trễ hạ lưu, điểm đường găng \exp(-S_u/14), bán kính lan tỏa và Inverted PageRank.
   - Được chuẩn hóa thành **Thứ hạng phân vị (Percentile Rank)** trong từng tập split để bảo toàn phân phối chuẩn.
   - Dùng để tính: **NDCG@10**, **NDCG@50** và **Hệ số tương quan Spearman rho**.
2. **Nhãn Nhị Phân Báo Động Đỏ (`is_critical_p0` thuộc \{0, 1\})**:
   - Gán bằng 1 cho **Top 5% tác vụ có điểm cao nhất** (`ground_truth_criticality >= 0.95`).
   - Dùng để tính: **Precision@Top-5%**, **Recall@Top-5%**, **PR-AUC**, và **ROC-AUC**.

---

### 2.4. Nguyên Tắc Bất Biến: Hồi Cứu Tạo Nhãn vs. Tiên Đoán tại T_0

```
[QUÁ KHỨ: TẠO NHÃN GROUND TRUTH]              [MÔ HÌNH HỌC MÁY (TGN/GBDT)]
Được phép nhìn vào toàn bộ tương lai           CHỈ ĐƯỢC NHÌN TẠI THỜI ĐIỂM T_0 (LÚC TẠO TASK)
sau khi task đã đóng để tính:                 - Đặc trưng ngữ nghĩa (NLP text)
- Thời gian trễ thực tế                        - Tải công việc kỹ sư (WCI, active tasks)
- Đường găng CPM thực tế                       - Cấu trúc đồ thị đã biết trước T_0
- Marginal Slippage Delta D_u                 - Lịch sử hoàn thành quá khứ
          │                                                    │
          ▼                                                    ▼
   [NHÃN CHÂN LÝ: Y_u]  ◄════════ (So sánh đối đầu) ════════  [DỰ ĐOÁN: \hat{Y}_u]
```

- **Khi tạo nhãn (Ground Truth)**: Dùng góc nhìn hồi cứu toàn diện sau khi sự việc đã hoàn thành để xác định ai thực sự là thủ phạm gây trễ dự án.
- **Khi mô hình AI dự đoán (Inference)**: Mô hình bị chặn hoàn toàn thông tin tương lai (**Zero Temporal Leakage**). Tại thời điểm T_0, mô hình phải dự đoán xác suất task này rơi vào nhóm 5% P0 gây trễ dây chuyền.

---

# PHẦN 3: GIẢNG GIẢI CHI TIẾT HỆ THỐNG CHỈ SỐ ĐÁNH GIÁ (EVALUATION METRICS)

### ⚠️ Nghịch lý Accuracy (Accuracy Paradox)
Trong tập dữ liệu mất cân bằng (chỉ có \sim 21.7% task trễ hoặc 5% task P0), nếu một mô hình đoán bừa tất cả là âm tính (`y = 0`), nó vẫn đạt **Accuracy xấp xỉ 78% - 95%** nhưng hoàn toàn vô giá trị trong thực tiễn vì không phát hiện được bất kỳ sự cố nào. Do đó, Accuracy bị loại bỏ và thay thế bằng hệ thống chỉ số dưới đây:

---

### 3.1. Nhóm Metric Phân Loại Nhị Phân (Binary Classification)

```
                       THỰC TẾ (GROUND TRUTH)
                   Trễ (Positive)       Đúng hạn (Negative)
DỰ ĐOÁN    Trễ      True Positive (TP)    False Positive (FP)  --> Precision
MÔ HÌNH    Đúng hạn False Negative (FN)   True Negative (TN)
                      |
                      v
                    Recall
```

1. **Precision (Độ chính xác cảnh báo)**:
   Precision = TP / (TP + FP) = (Số cảnh báo trúng) / (Tổng số lần phát cảnh báo)
   - *Ý nghĩa*: Trong 100 lần hệ thống báo động trễ, có bao nhiêu lần là sự thật?
   - *FDR (False Discovery Rate)*: FDR = 1 - Precision. Nếu FDR > 60%, kỹ sư sẽ gặp **Hội chứng Bội thực Cảnh báo (Alert Fatigue)** và tắt thông báo AI.
2. **Recall (Độ bao phủ phát hiện)**:
   Recall = TP / (TP + FN) = (Số task trễ bắt được) / (Tổng số task thực tế bị trễ)
   - *Ý nghĩa*: Trong 100 task thực tế bị trễ trong dự án, mô hình bắt được bao nhiêu task?
3. **F1-Score (Trung bình điều hòa)**:
   F1-Score = 2 * (Precision * Recall) / (Precision + Recall)
   - *Tại sao dùng trung bình điều hòa?* Phạt nặng nếu một trong hai chỉ số Precision hoặc Recall bị thấp, đảm bảo sự cân bằng thực chất.
4. **PR-AUC (Precision-Recall AUC) vs ROC-AUC**:
   - ROC-AUC thường bị thổi phồng khi số lượng TN quá lớn.
   - PR-AUC chỉ tập trung đo lường trên lớp thiểu số (lớp trễ hạn), là thước đo trung thực và khắt khe nhất cho bài toán dữ liệu mất cân bằng.
5. **Brier Score (Độ hiệu chuẩn xác suất)**:
   Brier Score = (1 / N) * Tổng [ (xác_suất_p_i - nhãn_thực_y_i)^2 ]
   - Đo lường mức độ tin cậy của xác suất dự báo p_i, đảm bảo mô hình không bị tự tin thái quá.

---

### 3.2. Nhóm Metric Xếp Hạng Thứ Bậc (Learning-to-Rank)

1. **DCG và NDCG@k (Normalized Discounted Cumulative Gain)**:
   DCG@k = Tổng [ (2^(r_i) - 1) / log2(i + 1) ] với i chạy từ 1 đến k
NDCG@k = DCG@k / IDCG@k
   - *Ý nghĩa*: Đánh giá năng lực đưa các task nguy hiểm nhất lên đầu danh sách Sprint. Nếu một task P0 bị xếp tụt xuống vị trí số 9 hay 10, giá trị của nó sẽ bị phạt giảm trừ theo hàm log2(i + 1).
2. **Precision@Top-5% (Độ chuẩn xác Cảnh báo Đỏ P0)**:
   - Tỷ lệ các task thực sự là P0 trong số các task mà mô hình xếp vào Top 5% nguy hiểm nhất.
3. **Hệ số Tương quan Hạng Spearman (rho)**:
   Spearman rho = 1 - [ 6 * Tổng(d_i^2) ] / [ n * (n^2 - 1) ]
   - Đo lường mức độ đồng điệu về thứ bậc ưu tiên giữa dự đoán của AI và thực tế diễn ra trong dự án.

---

### 3.3. Bảng Tổng Hợp So Sánh Toàn Bộ Metrics

| Tên Metric | Bài toán áp dụng | Bản chất toán học | Ý nghĩa nghiệp vụ trong quản lý dự án | Kết quả đạt được của đề tài |
| :--- | :--- | :--- | :--- | :---: |
| **Precision** | Phân loại Trễ hạn | TP / (TP + FP) | Cảnh báo trúng đích, triệt tiêu báo động giả, giảm FDR. | **77.44%** |
| **Recall** | Phân loại Trễ hạn | TP / (TP + FN) | Không bỏ sót các sự cố trễ hạn nghiêm trọng. | **86.31%** |
| **F1-Score** | Phân loại Trễ hạn | 2 * (P * R) / (P + R) | Cân bằng hài hòa giữa độ chính xác và độ bao phủ. | **0.8163** |
| **PR-AUC** | Phân loại Trễ hạn | Diện tích dưới đường cong P-R | Thước đo chuẩn mực cho dữ liệu mất cân bằng nhãn. | **0.8806** |
| **NDCG@10** | Xếp hạng Trọng yếu | DCG@10 / IDCG@10 | Đưa task nguy hiểm nhất lên đầu bảng (có phạt vị trí theo log). | **0.9966 (Global)**<br>**0.9337 (Sprint)** |
| **Prec@Top-5%** | Xếp hạng Trọng yếu | (P0 đúng) / (Top 5%) | Bắn cảnh báo đỏ P0 chuẩn xác cho Project Manager. | **77.26%** |
| **Spearman rho**| Xếp hạng Trọng yếu | 1 - [6*Tổng(d_i^2)] / [n*(n^2-1)] | Độ tương quan thứ bậc ưu tiên giữa AI và thực tế. | **0.7606** |

---

# PHẦN 4: HÀM Ý ỨNG DỤNG THỰC TIỄN VÀ BÍ QUYẾT BẢO VỆ KHÓA LUẬN

### 1. Ba Giá Trị Triển Khai Thực Tế
- **Hệ thống Cảnh báo Đỏ P0 không gây mệt mỏi (Zero Alert Fatigue)**: Với Precision@Top-5% đạt **77.26%**, cứ 4 cảnh báo gửi đi thì có gần 3 cảnh báo là sự cố đường găng thực sự.
- **Tự động Cân bằng Tài nguyên (Dynamic Resource Rebalancing)**: Khi phát hiện task nằm trên đường găng giao cho kỹ sư đang có `active_per_completed` cao, hệ thống tự động đề xuất tái phân công sang nhân sự có hàng đợi thông thoáng hơn.
- **Phân tích Tác động Kịch bản "What-If"**: Ứng dụng mô phỏng Monte Carlo để trả lời: *"Nếu task này trễ 1 tuần thì xác suất trễ toàn bộ bản release là bao nhiêu %?"*.

### 2. Bí Quyết Trả Lời Phản Biện Trước Hội Đồng Chấm Khóa Luận
- **Nếu Thầy/Cô hỏi**: *"Tại sao em không dùng Accuracy?"*  
  👉 **Trả lời**: *"Do tập dữ liệu có tỷ lệ mẫu dương chỉ 21.7% trễ hạn và 5% task P0. Một mô hình đoán bừa toàn bộ âm tính vẫn đạt Accuracy >78% nhưng không phát hiện được bất kỳ lỗi nào. Vì vậy em dùng PR-AUC và F1-Score."*
- **Nếu Thầy/Cô hỏi**: *"Nhãn độ quan trọng ở đâu ra trong khi Jira không có nhãn này?"*  
  👉 **Trả lời**: *"Em áp dụng phương pháp hồi cứu (Post-Mortem): phân tích đường găng CPM và mô phỏng phản thực tế (Counterfactual) trên đồ thị phụ thuộc DAG của 69,154 task sau khi đã đóng để đo lường chính xác mức độ làm trượt tiến độ của từng task đối với toàn dự án (Delta_D_u). Top 5% task gây thiệt hại lớn nhất được gán nhãn P0 Ground Truth."*
- **Nếu Thầy/Cô hỏi**: *"NDCG@10 có ý nghĩa gì đối với người quản lý dự án?"*  
  👉 **Trả lời**: *"Người quản lý dự án không thể đọc hết hàng trăm task mỗi tuần. NDCG@10 đánh giá năng lực sắp xếp đúng 10 task rủi ro nhất lên đầu danh sách Sprint. Điểm NDCG@10 = 0.9966 chứng minh AI hỗ trợ người quản lý tập trung chính xác vào các điểm nóng nguy hiểm nhất."*
