# TÀI LIỆU KỸ THUẬT & HỆ THỐNG BÁO CÁO NGHIÊN CỨU (DOCUMENTATION INDEX)

Thư mục `docs/` chứa toàn bộ các báo cáo kỹ thuật, tài liệu phân tích thực nghiệm, quy trình tiền xử lý dữ liệu và hướng dẫn điều phối hệ thống Machine Learning dự đoán nguy cơ trễ hạn Issue và phát hiện điểm nghẽn trên Jira.

---

## 📌 1. BÁO CÁO THỰC NGHIỆM DỰ ĐOÁN TRỄ HẠN ISSUE (ISSUE DELAY PREDICTION)

| Tài liệu | Mô tả nội dung |
| :--- | :--- |
| 📄 [**bao-cao-thuc-nghiem-du-doan-tre-han-issue.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-thuc-nghiem-du-doan-tre-han-issue.md) | **Báo cáo Thực nghiệm Tổng kết Toàn diện (Vòng 1 & Vòng 2)**: Bảng xếp hạng trung tâm (Central Leaderboard) cho 4 tracks (Stacking Meta-Learner, XGBoost, Random Forest, Logistic Regression), chứng minh toán học về trần sai số Bayes cho mục tiêu $F_1 > 0.90$, ma trận nhầm lẫn, biểu đồ PR/ROC, phân tích SHAP và hiện tượng Right-Censoring trong Jira. |
| 📄 [**meta-prompt-va-huong-dan-dieu-phoi-da-tac-tu.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/meta-prompt-va-huong-dan-dieu-phoi-da-tac-tu.md) | **Meta-Prompt & Hướng dẫn Điều phối Đa Tác tử (Multi-Agent Orchestrator)**: Thiết lập quy trình nghiên cứu song song trên các Git Worktrees độc lập, phân bổ nhiệm vụ subagents và bộ đánh giá bất biến `evaluation_harness.py`. |
| 📄 [**kinh-nghiem-va-quy-chuan-huan-luyen-du-doan-tre-han.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/kinh-nghiem-va-quy-chuan-huan-luyen-du-doan-tre-han.md) | **Quy chuẩn & Bài học Kinh nghiệm Mở rộng**: Đúc kết 4 bài học lớn (Bẫy Right-Censoring, Unassigned Drift, Developer Turnover Overfitting, Sức mạnh Stacking) để triển khai trên toàn bộ 16 dự án (2.68M issues) của The Public Jira Dataset. |

---

## 📊 2. THƯ MỤC HÌNH ẢNH & TRỰC QUAN HÓA THỰC NGHIỆM (`docs/figures/`)

- 📈 [**docs/figures/pr_roc_curves.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/pr_roc_curves.png): So sánh đường cong Precision-Recall (với ISO-F1 contours) và ROC curves trên Out-of-time Test set.
- 🎯 [**docs/figures/confusion_matrices.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/confusion_matrices.png): Ma trận nhầm lẫn 2x2 thể hiện chi tiết TP, FP, TN, FN cho 4 tracks tại ngưỡng tối ưu.
- 🔍 [**docs/figures/shap_top10.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/shap_top10.png): Top 10 đặc trưng theo giá trị SHAP (XGBoost), Gini Importance (Random Forest) và Hệ số điều chuẩn (ElasticNet).
- 🌐 [**docs/figures/dynamic_graph.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/dynamic_graph.png): Biểu diễn mạng lưới đồ thị thời gian của tương tác giữa developer và issue.
- 🧠 [**docs/figures/tgn.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/tgn.png): Kiến trúc mô hình Temporal Graph Network (TGN).

---

## 🛠️ 3. DỮ LIỆU, PIPELINE ETL & TIỀN XỬ LÝ

| Tài liệu | Mô tả nội dung |
| :--- | :--- |
| 📄 [**quy-trinh-etl-mongodb-sang-duckdb.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/quy-trinh-etl-mongodb-sang-duckdb.md) | Pipeline trích xuất dữ liệu dung lượng lớn từ MongoDB sang DuckDB với schema chuẩn hóa. |
| 📄 [**bao-cao-tap-du-lieu-va-tien-xu-ly.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-tap-du-lieu-va-tien-xu-ly.md) | Thống kê cấu trúc tập dữ liệu Jira gốc và các kỹ thuật xử lý dữ liệu thiếu, phân tích thời gian. |
| 📄 [**bao-cao-xu-ly-du-lieu-va-phuong-an-huan-luyen.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-xu-ly-du-lieu-va-phuong-an-huan-luyen.md) | Phương án chia tập thời gian bất biến (Chronological Split) và chuẩn bị đặc trưng. |

---

## 🔬 4. NGHIÊN CỨU LÝ THUYẾT ĐIỂM NGHẼN & ỨNG DỤNG LLM/TGN

| Tài liệu | Mô tả nội dung |
| :--- | :--- |
| 📄 [**bao-cao-ky-thuat-eda-tien-xu-ly-va-mo-hinh.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-ky-thuat-eda-tien-xu-ly-va-mo-hinh.md) | Báo cáo kỹ thuật giai đoạn đầu về khám phá dữ liệu (EDA), phân tích phân phối độ trễ. |
| 📄 [**bao-cao-tgn-jira-phat-hien-diem-nghen.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md) | Ứng dụng Temporal Graph Network (TGN) phát hiện nút thắt cổ chai trong quy trình phần mềm. |
| 📄 [**nghien-cuu-ly-thuyet-diem-nghen-va-ung-dung-llm.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/nghien-cuu-ly-thuyet-diem-nghen-va-ung-dung-llm.md) | Khung lý thuyết về điểm nghẽn (Theory of Constraints) và ứng dụng LLM trong phân tích phần mềm. |
| 📄 [**phuong-an-gan-nhan-bottleneck-bang-llm.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/phuong-an-gan-nhan-bottleneck-bang-llm.md) | Phương pháp sử dụng LLM để gán nhãn và kiểm định dữ liệu điểm nghẽn tự động. |
| 📄 [**rubric-label-audit-bottleneck.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/rubric-label-audit-bottleneck.md) | Bộ tiêu chí (rubric) đánh giá chất lượng nhãn điểm nghẽn. |
