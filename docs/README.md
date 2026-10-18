# TÀI LIỆU KỸ THUẬT & HỆ THỐNG BÁO CÁO NGHIÊN CỨU (DOCUMENTATION INDEX)

> [!IMPORTANT]
> **🌟 KẾT QUẢ NGHIÊN CỨU MỚI NHẤT & QUY MÔ NHẤT (LATEST RESEARCH RESULTS — 2,685,911 ISSUES)**:
> 1. 📄 [**bao-cao-ky-thuat-track-5-pre-triage-loc-issue-ao-va-du-doan-tre-han.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-ky-thuat-track-5-pre-triage-loc-issue-ao-va-du-doan-tre-han.md)  
>    **Báo Cáo Kỹ Thuật Chuyên Sâu Track 5 (Pre-Triage Two-Stage Pipeline)**: Sàng lọc trước $152,461$ task ảo (Duplicates / Non-Work) với Precision $97.97\%$, giải mã nghịch lý Precision thấp tại $T_0$, chứng minh toán học trần Oracle Bound ($49.77\%$), và đưa Precision dự đoán trễ hạn trên Real Engineering Work từ $22.83\% \to 30.99\%$ tại $T_0$ (giảm $31.4\%$ báo động giả).
> 2. 📄 [**bao-cao-toan-dien-huan-luyen-va-danh-gia-toan-bo-jira-2_68m.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-toan-dien-huan-luyen-va-danh-gia-toan-bo-jira-2_68m.md)  
>    **Báo Cáo Tổng Hợp Toàn Diện 7 Giải Pháp AI Dự Đoán Trễ Hạn Phần Mềm**: Huấn luyện và đánh giá trên $100\%$ dữ liệu $2,685,911$ issues (16 hệ sinh thái Jira), khai thác $100\%$ Ollama 768d embeddings, tích hợp kiến trúc 4 Trụ cột Khử nhiễu Sớm $T_1 \to T_3$ (Prec $57.4\% \to 64.4\%$) và In-Flight Milestones $T_5 \to T_{14}$ (Prec $76.0\% \to 77.4\%$, F1 $0.816$, giảm $-80.8\%$ FP).

---

Thư mục `docs/` chứa toàn bộ các báo cáo kỹ thuật, tài liệu phân tích thực nghiệm, quy trình tiền xử lý dữ liệu và hướng dẫn điều phối hệ thống Machine Learning dự đoán nguy cơ trễ hạn Issue và phát hiện điểm nghẽn trên Jira.

---

## 📌 1. BÁO CÁO THỰC NGHIỆM DỰ ĐOÁN TRỄ HẠN ISSUE (ISSUE DELAY PREDICTION)

| Tài liệu | Mô tả nội dung |
| :--- | :--- |
| 📄 [**bao-cao-ky-thuat-track-5-pre-triage-loc-issue-ao-va-du-doan-tre-han.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-ky-thuat-track-5-pre-triage-loc-issue-ao-va-du-doan-tre-han.md) | **Báo Cáo Kỹ Thuật Track 5 (Mới nhất)**: Pre-Triage Deduplication & Non-Work Gate, giải mã trần Oracle Bound tại $T_0$, loại bỏ 152k task ảo, tối ưu Precision Real-Work. |
| 📄 [**bao-cao-toan-dien-huan-luyen-va-danh-gia-toan-bo-jira-2_68m.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-toan-dien-huan-luyen-va-danh-gia-toan-bo-jira-2_68m.md) | **Báo Cáo Tổng Hợp 7 Tracks (Mới nhất)**: Đánh giá đối đầu 7 giải pháp trên toàn bộ 2.68M issues và 16 instances Jira ($T_0, T_1, T_2, T_3, T_5, T_7, T_{14}$). |
| 📄 [**bao-cao-thuc-nghiem-du-doan-tre-han-issue.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/bao-cao-thuc-nghiem-du-doan-tre-han-issue.md) | **Báo cáo Thực nghiệm Vòng 1 & Vòng 2**: Bảng xếp hạng trung tâm sơ khởi (Stacking Meta-Learner, XGBoost, Random Forest, Logistic Regression). |
| 📄 [**meta-prompt-va-huong-dan-dieu-phoi-da-tac-tu.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/meta-prompt-va-huong-dan-dieu-phoi-da-tac-tu.md) | **Meta-Prompt & Hướng dẫn Điều phối Đa Tác tử (Multi-Agent Orchestrator)**: Thiết lập quy trình nghiên cứu song song trên các Git Worktrees độc lập. |
| 📄 [**kinh-nghiem-va-quy-chuan-huan-luyen-du-doan-tre-han.md**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/kinh-nghiem-va-quy-chuan-huan-luyen-du-doan-tre-han.md) | **Quy chuẩn & Bài học Kinh nghiệm Mở rộng**: Đúc kết 4 bài học lớn để triển khai trên toàn bộ 16 dự án. |

---

## 📊 2. THƯ MỤC HÌNH ẢNH & TRỰC QUAN HÓA THỰC NGHIỆM (`docs/figures/`)

- 🛡️ [**docs/figures/pre_triage_tradeoff.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/pre_triage_tradeoff.png): Đánh đổi Precision - Recall khi quét ngưỡng Cổng lọc Tiền Triage ($T_0^+$ vs $T_{24h}$) và bước nhảy vọt Precision trên Real Engineering Work.
- 🚀 [**docs/figures/solutions_comparison.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/solutions_comparison.png): So sánh 4 bảng đa chiều của 7 giải pháp AI từ $T_0 \to T_1 \to T_2 \to T_3 \to T_5 \to T_7 \to T_{14}$.
- ⚡ [**docs/figures/t1_t3_noise_reduction.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/t1_t3_noise_reduction.png): Phân rã 4 giải pháp khử nhiễu sớm trong 72h đầu tiên (triệt tiêu 53k - 66k FP, đột phá PR-AUC và giải mã hiện tượng đảo ngược thứ hạng rủi ro Bayes).
- 📈 [**docs/figures/pr_roc_curves.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/pr_roc_curves.png): So sánh đường cong Precision-Recall và ROC curves trên Out-of-time Test set.
- 🎯 [**docs/figures/confusion_matrices.png**](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/docs/figures/confusion_matrices.png): Ma trận nhầm lẫn thể hiện chi tiết TP, FP, TN, FN cho các tracks tại ngưỡng tối ưu.

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
