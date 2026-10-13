# Nghiên cứu Lý thuyết Xác định Điểm nghẽn trong Dự án Phần mềm và Ứng dụng Mô hình Ngôn ngữ Lớn (LLM) để Gắn nhãn, Phát hiện Điểm nghẽn

**Tác giả:** Đội ngũ Nghiên cứu Kỹ thuật & Quản lý Dự án Phần mềm (SPM)  
**Tập trung nghiên cứu:** Lý thuyết Điểm nghẽn (Theory of Constraints & Product Flow) · Xử lý Đồ thị Động (Temporal Graph Networks - TGN) · Gắn nhãn Ngữ nghĩa bằng Mô hình Ngôn ngữ Lớn (LLM Labeling & Weak Supervision)  
**Bộ dữ liệu thực nghiệm:** The Public Jira Dataset (JFrog, Spring, Mojang — Montgomery, Lüders & Maalej, MSR 2022)  
**Ngày hoàn thiện:** 2026-10-07  
**Trạng thái:** Báo cáo Nghiên cứu Chuyên sâu & Đặc tả Kỹ thuật Toàn diện (Research & Technical Specification)

---

## Tóm tắt Điều hành (Executive Summary)

Trong kỹ nghệ phần mềm và quản lý dự án hiện đại (Software Project Management - SPM), việc xác định chính xác **điểm nghẽn (bottleneck)** là bài toán then chốt nhằm tối ưu hóa thông lượng (throughput) và giảm thiểu chu kỳ phát hành sản phẩm. Tuy nhiên, phần lớn các phương pháp tiếp cận truyền thống đều vướng vào hai thái cực sai lầm:
1. **Thiên lệch con số bề nổi (Superficial Quantitative Metrics):** Dựa vào các chỉ số heuristic đơn giản như thời gian mở (issue age), độ ưu tiên (priority), hoặc số lượng liên kết (link count) mà bỏ qua hoàn toàn ngữ cảnh công việc và bản chất lan truyền của sự chậm trễ.
2. **Ngộ nhận về nhãn phụ thuộc (Dependency Misconception):** Đồng nhất một cách máy móc "issue có liên kết phụ thuộc (Block/Depend)" với "issue là điểm nghẽn". Thử nghiệm thực tế trong dự án này (P0) đã chứng minh rằng nhãn phụ thuộc tĩnh (v3) dẫn đến **rò rỉ đặc trưng (feature leakage) nghiêm trọng**: mô hình TGN đạt AUC 0,835 chỉ vì "học vẹt" one-hot edge feature của loại liên kết; khi loại bỏ rò rỉ, AUC sụt xuống 0,484 (ngang ngửa đoán ngẫu nhiên). Điều này chứng minh rằng các mô hình học máy trên đồ thị không thể tự học được bản chất điểm nghẽn nếu thiếu một hệ thống nhãn có căn cứ lý thuyết vững chắc.

Báo cáo nghiên cứu này giải quyết triệt để bài toán trên thông qua hai trụ cột:

* **Trụ cột I — Khung Lý thuyết Xác định Điểm nghẽn:** Hệ thống hóa nền tảng từ *Thuyết Điểm nghẽn (Theory of Constraints - Goldratt)*, *Lý thuyết Hàng đợi & Dòng chảy Phát triển Sản phẩm (Queuing Theory & Factory Physics, Reinertsen)*, và *Lý thuyết Đồ thị Phụ thuộc Động (Dynamic Dependency Networks)*. Chúng tôi thiết lập định nghĩa hình thức: Một issue chỉ là điểm nghẽn khi thỏa mãn đồng thời hai điều kiện cần và đủ: **Tắc dòng chảy (Flow Obstruction - $F$)** và **Tác động lan truyền (Systemic Impact - $I$)**, loại trừ các trường hợp âm tính giả (backlog ngủ quên, epic bao trùm, ưu tiên "Blocker" kỹ thuật, hoãn có chủ đích, và các dị vật dọn dẹp dữ liệu hàng loạt). Đồng thời, định nghĩa điểm nghẽn được chuyển hóa thành **giai đoạn động (temporal episode)** thay vì thuộc tính tĩnh vĩnh viễn.
* **Trụ cột II — Phương pháp Ứng dụng LLM Gắn nhãn & Phát hiện:** Thiết kế kiến trúc giải pháp lai (Hybrid Human-in-the-loop / Code + LLM Pipeline). Code chịu trách nhiệm tính toán thời gian, phân vị cư trú ($p_{90}$ dwell time), phát hiện dị vật dữ liệu (bulk close); LLM đóng vai trò bộ suy luận ngữ nghĩa (Semantic Reasoner) phân tích văn bản thảo luận, xác định lý do chờ đợi, phân định vai trò (Root Blocker vs. Victim), và trích xuất bằng chứng nguyên văn (grounded attribution). Quy trình được bảo vệ bằng cơ chế đối chiếu tự động (anti-hallucination guardrail), phương pháp lấy mẫu nhất quán (Self-Consistency with Medoid IoU), và ánh xạ an toàn (leak-safe) sang mô hình Temporal Graph Networks (TGN) thông qua các mốc truy vấn định kỳ (periodic evaluation ticks).

---

## MỤC LỤC CHI TIẾT

- [PHẦN I: CƠ SỞ LÝ THUYẾT VỀ ĐIỂM NGHẼN TRONG DỰ ÁN PHẦN MỀM](#phần-i-cơ-sở-lý-thuyết-về-điểm-nghẽn-trong-dự-án-phần-mềm)
  - [1. Bản chất của Điểm nghẽn trong Kỹ nghệ Phần mềm](#1-bản-chất-của-điểm-nghẽn-trong-kỹ-nghệ-phần-mềm)
    - [1.1. Phân biệt: Chậm (Slow), Phức tạp (Complex) và Nghẽn (Bottleneck)](#11-phân-biệt-chậm-slow-phức-tạp-complex-và-nghẽn-bottleneck)
    - [1.2. Nguyên lý Bảo toàn và Lan truyền Trễ (Propagation of Delays)](#12-nguyên-lý-bảo-toàn-và-lan-truyền-trễ-propagation-of-delays)
  - [2. Các Trường phái Lý thuyết Nền tảng](#2-các-trường-phái-lý-thuyết-nền-tảng)
    - [2.1. Thuyết Điểm nghẽn (Theory of Constraints - TOC, Goldratt)](#21-thuyết-điểm-nghẽn-theory-of-constraints---toc-goldratt)
    - [2.2. Lý thuyết Hàng đợi & Dòng chảy Phát triển Sản phẩm (Queuing Theory & Reinertsen)](#22-lý-thuyết-hàng-đợi--dòng-chảy-phát-triển-sản-phẩm-queuing-theory--reinertsen)
    - [2.3. Lý thuyết Đồ thị & Phân tích Cấu trúc Phụ thuộc (Graph Theory & Dependency Networks)](#23-lý-thuyết-đồ-thị--phân-tích-cấu-trúc-phụ-thuộc-graph-theory--dependency-networks)
    - [2.4. Tổng quan Thực nghiệm Kỹ nghệ Phần mềm (Empirical Software Engineering)](#24-tổng-quan-thực-nghiệm-kỹ-nghệ-phần-mềm-empirical-software-engineering)
  - [3. Phân loại Toàn diện các Dạng Điểm nghẽn (Bottleneck Taxonomy)](#3-phân-loại-toàn-diện-các-dạng-điểm-nghẽn-bottleneck-taxonomy)
    - [3.1. Phân loại theo Cấp độ Thực thể (Entity-level Taxonomy)](#31-phân-loại-theo-cấp-độ-thực-thể-entity-level-taxonomy)
    - [3.2. Tính Động theo Giai đoạn (Temporal Nature of Bottlenecks)](#32-tính-động-theo-giai-đoạn-temporal-nature-of-bottlenecks)
  - [4. Định nghĩa Hình thức & Tiêu chí Xác định Điểm nghẽn](#4-định-nghĩa-hình-thức--tiêu-chí-xác-định-điểm-nghẽn)
    - [4.1. Công thức Logic Tổng quát](#41-công-thức-logic-tổng-quát)
    - [4.2. Chi tiết Nhóm Tiêu chí F (Tắc dòng chảy) và I (Tác động lan truyền)](#42-chi-tiết-nhóm-tiêu-chí-f-tắc-dòng-chảy-và-i-tác-động-lan-truyền)
    - [4.3. Các Trường hợp Ngoại lệ và Âm tính giả (Exclusions & Edge Cases)](#43-các-trường-hợp-ngoại-lệ-và-âm-tính-giả-exclusions--edge-cases)
- [PHẦN II: ỨNG DỤNG MÔ HÌNH LLM ĐỂ GẮN NHÃN VÀ PHÁT HIỆN ĐIỂM NGHẼN](#phần-ii-ứng-dụng-mô-hình-llm-để-gắn-nhãn-và-phát-hiện-điểm-nghẽn)
  - [5. Vai trò và Vị thế Chiến lược của LLM](#5-vai-trò-và-vị-thế-chiến-lược-của-llm)
    - [5.1. Vì sao Heuristics thuần túy và GNN không tự đủ?](#51-vì-sao-heuristics-thuần-túy-và-gnn-không-tự-đủ)
    - [5.2. Sức mạnh Ngữ nghĩa và Khả năng Phân giải Mơ hồ của LLM](#52-sức-mạnh-ngữ-nghĩa-và-khả-năng-phân-giải-mơ-hồ-của-llm)
    - [5.3. Các Cạm bẫy Cố hữu của LLM và Chiến lược Hóa giải](#53-các-cạm-bẫy-cố-hữu-của-llm-và-chiến-lược-hóa-giải)
  - [6. Kiến trúc Hệ thống Gắn nhãn Lai (Hybrid Labeling Pipeline)](#6-kiến-trúc-hệ-thống-gắn-nhãn-lai-hybrid-labeling-pipeline)
    - [6.1. Tầng Hồ sơ Issue (Dossier Generation Engine)](#61-tầng-hồ-sơ-issue-dossier-generation-engine)
    - [6.2. Kỹ nghệ Prompt & Bộ Quy tắc Chuẩn (Codebook Engineering)](#62-kỹ-nghệ-prompt--bộ-quy-tắc-chuẩn-codebook-engineering)
    - [6.3. Cấu trúc Schema Đầu ra và Ràng buộc Trích dẫn (Grounded Schema)](#63-cấu-trúc-schema-đầu-ra-và-ràng-buộc-trích-dẫn-grounded-schema)
    - [6.4. Cơ chế Đảm bảo Nhất quán (Self-Consistency & Medoid IoU Aggregation)](#64-cơ-chế-đảm-bảo-nhất-quán-self-consistency--medoid-iou-aggregation)
    - [6.5. Động cơ Kiểm định Chống Ảo giác (Deterministic Verification Engine)](#65-động-cơ-kiểm-định-chống-ảo-giác-deterministic-verification-engine)
  - [7. Khung Đánh giá Độ tin cậy & Kiểm định Con người (Gold Set & Human Alignment)](#7-khung-đánh-giá-độ-tin-cậy--kiểm-định-con-người-gold-set--human-alignment)
    - [7.1. Thiết kế Thử nghiệm Pilot và Ma trận Lấy mẫu Phân tầng](#71-thiết-kế-thử-nghiệm-pilot-và-ma-trận-lấy-mẫu-phân-tầng)
    - [7.2. Rubric Chấm Chuẩn cho Chuyên gia Quản lý Dự án (B1–B3 Rubric)](#72-rubric-chấm-chuẩn-cho-chuyên-gia-quản-lý-dự-án-b1b3-rubric)
    - [7.3. Đo lường Độ đồng thuận (Inter-Rater Reliability: Cohen’s Kappa & Fleiss’ Kappa)](#73-đo-lường-độ-đồng-thuận-inter-rater-reliability-cohens-kappa--fleiss-kappa)
    - [7.4. Phân tích Sai số và Cổng Quyết định (Go/No-Go Gates)](#74-phân-tích-sai-số-và-cổng-quyết-định-gono-go-gates)
  - [8. Ánh xạ Nhãn sang Mô hình Học máy trên Đồ thị Động (TGN Mapping)](#8-ánh-xạ-nhãn-sang-mô-hình-học-máy-trên-đồ-thị-động-tgn-mapping)
    - [8.1. Chuyển đổi Episode thành Nhãn Sự kiện và Giải quyết Nghịch lý Im lặng (Inactivity Paradox)](#81-chuyển-đổi-episode-thành-nhãn-sự-kiện-và-giải-quyết-nghịch-lý-im-lặng-inactivity-paradox)
    - [8.2. Thiết kế Đặc trưng Chống Rò rỉ Triệt để (Leak-Safe Feature Engineering)](#82-thiết-kế-đặc-trưng-chống-rò-rỉ-triệt-để-leak-safe-feature-engineering)
    - [8.3. Hệ thống Chỉ số Đánh giá Thực tế: AUPRC, Lead Time và Precision@k](#83-hệ-thống-chỉ-số-đánh-giá-thực-tế-auprc-lead-time-và-precisionk)
  - [9. Chiến lược Triển khai, Chưng cất Mô hình và Tối ưu Chi phí](#9-chiến-lược-triển-khai-chưng-cất-mô-hình-và-tối-ưu-chi-phí)
    - [9.1. Khảo sát Chi phí Token và Kỹ thuật Prompt Caching](#91-khảo-sát-chi-phí-token-và-kỹ-thuật-prompt-caching)
    - [9.2. Phương án Chưng cất Mô hình (Knowledge Distillation sang Small LLMs / SLMs)](#92-phương-án-chưng-cất-mô-hình-knowledge-distillation-sang-small-llms--slms)
    - [9.3. Kiến trúc Vận hành Thực tế (Production Architecture: LLM + TGN Dual-Engine)](#93-kiến-trúc-vận-hành-thực-tế-production-architecture-llm--tgn-dual-engine)
- [KẾT LUẬN VÀ LỘ TRÌNH TRIỂN KHAI](#kết-luận-và-lộ-trình-triển-khai)

---

# PHẦN I: CƠ SỞ LÝ THUYẾT VỀ ĐIỂM NGHẼN TRONG DỰ ÁN PHẦN MỀM

## 1. Bản chất của Điểm nghẽn trong Kỹ nghệ Phần mềm

### 1.1. Phân biệt: Chậm (Slow), Phức tạp (Complex) và Nghẽn (Bottleneck)

Một trong những nguyên nhân phổ biến nhất dẫn đến sự thất bại của các hệ thống cảnh báo dự án tự động là sự nhầm lẫn giữa **thời lượng xử lý (duration/latency)** và **tính chất điểm nghẽn (bottleneckness)**.

```
+-------------------------------------------------------------------------------+
|                             MA TRẬN PHÂN LOẠI CÔNG VIỆC                       |
+------------------------------------+------------------------------------------+
|  CHẬM / LÂU (SLOW DURATION)        |  KHÔNG CHẬM (NORMAL / FAST)              |
+------------------------------------+------------------------------------------+
|  [Nhóm 1: Spike / Heavy Task]      |  [Nhóm 2: Dòng chảy êm thuận]            |
|  - Nghiên cứu kiến trúc (Spike)    |  - Công việc tiêu chuẩn (Standard User   |
|  - Refactor lớn, tiến triển đều    |    Story)                                |
|  - Không ai phải chờ đợi           |  - Hoàn thành đúng hạn                   |
|  --> KHÔNG PHẢI BOTTLENECK         |  --> KHÔNG PHẢI BOTTLENECK               |
+------------------------------------+------------------------------------------+
|  [Nhóm 3: Critical Bottleneck]     |  [Nhóm 4: Micro-Bottleneck / Flap]       |
|  - Dừng trệ không rõ nguyên nhân   |  - Khóa downstream ngắn hạn nhưng        |
|  - Ứ đọng ở khâu Review / QA       |    lặp đi lặp lại nhiều lần              |
|  - Nhiều downstream issue bị chặn  |  - Gây trễ cục bộ theo đợt               |
|  --> BOTTLENECK CHÍNH XÁC          |  --> CẦN THEO DÕI TẦN SUẤT               |
+------------------------------------+------------------------------------------+
```

1. **Một công việc kéo dài (Slow):** Một issue nghiên cứu kỹ thuật (Spike) hoặc một thay đổi cơ sở dữ liệu lớn có thể mất 60 ngày để hoàn thành. Nhưng nếu trong suốt 60 ngày đó, kỹ sư làm việc liên tục, không có đầu việc nào khác bị phụ thuộc vào kết quả này để tiếp tục, và không có hạn chót phát hành nào bị vi phạm, thì công việc đó **không phải là điểm nghẽn**.
2. **Một công việc có nhiều liên kết (Highly Connected):** Một Epic quản lý module chứa 50 sub-tasks hoặc liên kết liên quan. Đây là cấu trúc tổ chức dự án, bản thân Epic không phải điểm nghẽn trừ khi sự chậm trễ của nó đang ngăn cản các issue thành phần được triển khai.
3. **Điểm nghẽn thực sự (True Bottleneck):** Một defect nhỏ sửa đổi 2 dòng code, nhưng bị treo tại hàng đợi "Pending Review" trong 3 tuần do người duy nhất có quyền approve đang nghỉ phép, và bản vá này là điều kiện tiên quyết để 5 đội phát triển khác tích hợp hệ thống đóng gói phiên bản Release Candidate. Dù kích thước nhỏ, **đây chính là điểm nghẽn nghiêm trọng nhất của hệ thống.**

### 1.2. Nguyên lý Bảo toàn và Lan truyền Trễ (Propagation of Delays)

Trong một hệ thống phát triển phần mềm, công việc không di chuyển độc lập mà tương tác thông qua đồ thị phụ thuộc (dependency graph) và nguồn lực dùng chung (shared resources). Sự chậm trễ của một issue $u$ sẽ lan truyền sang issue $v$ nếu thỏa mãn quan hệ nhân quả:
$$\text{Start}(v) \ge \text{Completion}(u)$$

Khi $u$ bị tắc nghẽn, thời gian chờ của $v$ tích lũy. Nếu $v$ tiếp tục chặn $w_1, w_2, \dots, w_k$, độ trễ không chỉ tăng tuyến tính mà tăng theo cấp số nhân về mặt tổng thiệt hại dự án. Hiện tượng này được gọi là **Sóng lan truyền trễ (Delay Wavefront)** hay **Bán kính ảnh hưởng (Blast Radius)**.

---

## 2. Các Trường phái Lý thuyết Nền tảng

### 2.1. Thuyết Điểm nghẽn (Theory of Constraints - TOC, Goldratt)

Thuyết Điểm nghẽn do Eliyahu M. Goldratt khởi xướng (1984) đưa ra một định đề mang tính nền tảng: **Bất kỳ hệ thống có thể quản lý nào cũng chỉ có một số rất ít các điểm nghẽn (thường chỉ là 1) hạn chế khả năng đạt được mục tiêu cao hơn của nó.**

#### Cơ chế Trống - Đệm - Dây thừng (Drum-Buffer-Rope - DBR)
Trong quản lý dự án phần mềm:
* **Trống (Drum):** Điểm nghẽn chính là chiếc trống quyết định nhịp độ (pace) của toàn bộ dự án. Dự án không thể hoàn thành nhanh hơn tốc độ xử lý của khâu nghẽn nhất.
* **Đệm (Buffer):** Khoảng thời gian hoặc lượng công việc dự phòng đặt trước điểm nghẽn để đảm bảo điểm nghẽn không bao giờ bị "đói việc" (starved of work). Nếu điểm nghẽn dừng làm việc 1 giờ, toàn bộ dự án mất đi 1 giờ không thể bù đắp.
* **Dây thừng (Rope):** Cơ chế kiểm soát tốc độ tiếp nhận công việc mới vào hệ thống. Nếu thả công việc vào nhanh hơn tốc độ của Drum, công việc chỉ tích tụ thành hàng đợi trước điểm nghẽn, làm tăng lượng công việc dở dang (WIP) mà không hề gia tăng số lượng release hoàn thành.

#### Nghịch lý Tối ưu Cục bộ (Local Optimization Paradox)
Goldratt nhấn mạnh: *"Tối ưu hóa ở một khâu không phải điểm nghẽn là một ảo tưởng, và trong nhiều trường hợp, làm suy giảm hiệu quả của toàn bộ hệ thống."*  
Nếu một nhóm phát triển cố gắng viết thật nhiều code (tăng tốc cục bộ khâu Development) trong khi khâu Code Review hoặc QA đang là điểm nghẽn, kết quả duy nhất đạt được là núi Pull Request ứ đọng, xung đột code gia tăng (merge conflicts), và chi phí chuyển đổi ngữ cảnh tăng vọt.

```
Flow: [Backlog] ---> [Development] ===> [Code Review (BOTTLENECK)] ---> [Testing] ---> [Release]
                           ^                         |
                           |                         v
                  Tăng tốc khâu này       Hàng đợi PR phình to,
                 chỉ làm ngập Review      WIP tăng vọt, lãng phí
```

### 2.2. Lý thuyết Hàng đợi & Dòng chảy Phát triển Sản phẩm (Queuing Theory & Reinertsen)

Donald G. Reinertsen trong tác phẩm kinh điển *"The Principles of Product Development Flow"* (2009) đã áp dụng sâu sắc toán học hàng đợi và Factory Physics vào phát triển sản phẩm trí tuệ.

#### Định luật Little (Little's Law)
Đối với bất kỳ hệ thống dòng chảy ổn định nào:
$$L = \lambda \cdot W \quad \iff \quad \text{WIP} = \text{Throughput} \times \text{Lead Time}$$
Trong đó:
* $\text{WIP}$ (Work-in-Progress): Số lượng issue đang trong quá trình xử lý (chưa Done).
* $\text{Throughput}$ ($\lambda$): Tốc độ hoàn thành công việc bình quân (issues/ngày).
* $\text{Lead Time}$ ($W$): Thời gian trung bình từ khi bắt đầu cam kết cho đến khi hoàn thành một issue.

**Hệ quả trực tiếp:** Nếu Throughput của đội ngũ bị giới hạn bởi năng lực tối đa, cách duy nhất để giảm Lead Time là **kiểm soát và giới hạn lượng WIP**. Khi một issue trở thành điểm nghẽn, nó ngăn cản dòng chảy, dẫn đến tích tụ WIP cục bộ phía trước nó. Việc xuất hiện một nhóm issue có trạng thái ứ đọng kéo dài chính là triệu chứng vi phạm cân bằng Little's Law.

#### Công thức Xấp xỉ Kingman cho Thời gian Chờ (Kingman's Formula)
Trong lý thuyết hàng đợi cho hệ thống phục vụ $G/G/1$, thời gian chờ trung bình trong hàng đợi $T_q$ được xấp xỉ bởi:
$$T_q \approx \left( \frac{\rho}{1 - \rho} \right) \left( \frac{c_a^2 + c_s^2}{2} \right) t_s$$
Trong đó:
* $\rho$: Mức độ sử dụng năng lực (Utilization), $\rho = \lambda / \mu$ (với $\lambda$ là tốc độ đến, $\mu$ là tốc độ phục vụ).
* $c_a, c_s$: Hệ số biến thiên (coefficients of variation) của thời gian giữa hai lần đến và thời gian xử lý.
* $t_s$: Thời gian xử lý trung bình ($1/\mu$).

```
Thời gian chờ
  T_q ^
      |                                        / (Tiệm cận vô cùng khi p -> 1)
      |                                      /
      |                                    /
      |                                  /
      |                           _ . - '
      |               _ . - - ' '
      +---------------------------------------> Mức độ bận rộn (p)
      0%              50%         80%  90%  100%
```

**Ý nghĩa cốt lõi:** Khi một lập trình viên hoặc một khâu (như Tech Lead review) đạt mức độ bận rộn $\rho \ge 90\%$, thời gian chờ của các issue phụ thuộc vào người này **tăng vọt theo hàm số mũ**. Đây là nguyên nhân vì sao các nhân sự chủ chốt (Tech Lead, Senior Architect) dù làm việc không ngừng nghỉ vẫn trở thành điểm nghẽn lớn nhất của dự án.

#### Hiệu suất Dòng chảy (Flow Efficiency)
$$\text{Flow Efficiency} = \frac{\text{Active Work Time (Touch Time)}}{\text{Total Lead Time}} \times 100\%$$
Thực nghiệm trong các tổ chức phần mềm cho thấy: hơn 85% thời gian vòng đời của một ticket là **thời gian chờ (Wait Time)** tại các trạng thái thụ động (chờ review, chờ làm rõ yêu cầu, chờ phụ thuộc bên ngoài), chỉ có 15% là thời gian làm việc thực tế (Touch Time). Issue điểm nghẽn là issue làm cho tỷ lệ thời gian chờ của bản thân nó và các issue liên quan tăng đột biến.

#### Chi phí của sự Chậm trễ (Cost of Delay - CoD)
Mỗi đơn vị thời gian một tính năng hoặc một bản sửa lỗi bị trì hoãn đều làm phát sinh tổn thất kinh tế. Điểm nghẽn không được đo lường bằng kích thước dòng code, mà đo lường bằng **tổng Cost of Delay** mà nó áp đặt lên toàn bộ các hạng mục downstream.

### 2.3. Lý thuyết Đồ thị & Phân tích Cấu trúc Phụ thuộc (Graph Theory & Dependency Networks)

Dự án phần mềm cấu thành một đồ thị có hướng động (Dynamic Directed Graph) $G(t) = (V(t), E(t))$, trong đó đỉnh $V$ là các issue và cạnh $E$ đại diện cho các quan hệ phụ thuộc hoặc chuyển giao quy trình.

#### Đường găng (Critical Path Method - CPM) & Độ chùng (Float/Slack)
Một issue $u$ có thời điểm bắt đầu sớm nhất $ES(u)$, kết thúc sớm nhất $EF(u)$, bắt đầu muộn nhất $LS(u)$, và kết thúc muộn nhất $LF(u)$.
$$\text{Total Slack}(u) = LS(u) - ES(u) = LF(u) - EF(u)$$
* Issue nằm trên **Đường găng (Critical Path)** khi và chỉ khi $\text{Total Slack}(u) = 0$.
* **Định nghĩa Đồ thị của Điểm nghẽn:** Một issue $u$ có nguy cơ trở thành điểm nghẽn khi thời gian cư trú thực tế tại các trạng thái đang làm vượt quá độ chùng của nó: $\Delta t_{\text{dwell}}(u) > \text{Slack}(u)$, khiến đường găng của dự án bị đẩy lùi.

#### Độ trung tâm Đồ thị (Graph Centrality)
* **Betweenness Centrality (Độ trung tâm trung gian):** Đo lường tần suất một issue $u$ nằm trên đường đi ngắn nhất giữa tất cả các cặp issue khác:
  $$C_B(u) = \sum_{s \ne u \ne t} \frac{\sigma_{st}(u)}{\sigma_{st}}$$
  Issue có $C_B(u)$ cao đóng vai trò "cây cầu" kiến trúc; nếu nó tắc nghẽn, các nhánh thông tin và tích hợp giữa các nhóm bị ngắt quãng.
* **Transitive Closure & Blast Radius (Bán kính tác động):** Tập hợp tất cả các issue $v$ có thể tiếp cận được từ $u$ thông qua chuỗi cạnh phụ thuộc có hướng $\text{Reach}(u) = \{v \in V \mid u \rightsquigarrow v\}$. Kích thước $|\text{Reach}(u)|$ và trọng số ưu tiên của các đỉnh trong tập này xác định mức độ nguy hiểm của điểm nghẽn $u$.

### 2.4. Tổng quan Thực nghiệm Kỹ nghệ Phần mềm (Empirical Software Engineering)

Các nghiên cứu thực nghiệm trên các kho lưu trữ lớn (Jira, Bugzilla, GitHub) cung cấp các bằng chứng xác thực quan trọng:

1. **Valdivia-Garcia & Shihab (MSR 2014) - "Characterizing and Predicting Blocking Bugs":**
   * Nghiên cứu trên Chromium và Eclipse chỉ ra rằng các "Blocking Bugs" (những bug chặn sự phát triển của các bug khác) tốn trung bình gấp 2 đến 3 lần thời gian giải quyết so với bug thông thường.
   * Yếu tố dự báo mạnh nhất không phải là độ nghiêm trọng kỹ thuật (severity) được khai báo ban đầu, mà là **vị trí của component bị ảnh hưởng** (các module tầng dưới hoặc giao diện công cộng) và **số lượng người tham gia thảo luận**.
2. **Xia et al. (IST 2015) - "ELBlocker: Predicting Blocking Bugs with Ensemble Imbalance Learning":**
   * Tỷ lệ blocking bugs trong các dự án thực tế chỉ dao động từ **2% đến 6%** tổng số issue (tương tự như tỷ lệ 3%–4% link Block/Depend mà chúng tôi ghi nhận trong JFrog và Spring).
   * Mất cân bằng dữ liệu cực đoan này đòi hỏi các kỹ thuật ensemble chuyên biệt và phương pháp đánh giá tập trung vào AUPRC và Precision-Recall thay vì Accuracy thuần túy.
3. **Choetkiertikul et al. (TSE 2017) - "A Deep Learning Model for Predicting Next Delays in Software Projects":**
   * Mô hình hóa sự tương tác giữa các issue dưới dạng mạng xã hội và kỹ thuật (socio-technical network). Kết quả chỉ ra rằng sự chậm trễ có tính lây lan (contagious): một issue có xác suất trễ hạn cao hơn đáng kể nếu các hàng xóm trong mạng lưới của nó cũng đang bị chậm trễ.
4. **Montgomery, Lüders & Maalej (MSR 2022) - "The Public Jira Dataset":**
   * Công bố bộ dữ liệu chuẩn hóa của 16 tổ chức lớn. Nghiên cứu chỉ ra rằng các liên kết ngữ nghĩa giữa các issue thường bị thiếu hoặc gắn trễ; các kỹ sư thường chỉ thêm liên kết "Block" sau khi xung đột đã xảy ra trên thực tế, khiến việc dựa vào các liên kết tĩnh để dự báo sớm gặp nhiều thách thức.

---

## 3. Phân loại Toàn diện các Dạng Điểm nghẽn (Bottleneck Taxonomy)

Để xây dựng một hệ thống phát hiện chính xác, điểm nghẽn cần được phân loại theo hai trục trực giao: **Cấp độ Thực thể** và **Chiều Thời gian**.

### 3.1. Phân loại theo Cấp độ Thực thể (Entity-level Taxonomy)

```
                              CÁC DẠNG ĐIỂM NGHẼN (TAXONOMY)
                                            |
        +-----------------------------------+-----------------------------------+
        |                                   |                                   |
[Issue/Task-level]                 [Resource-level]                    [Process-level]
  - Root Blocker (Gốc gây nghẽn)     - Overloaded Assignee               - Review Queue Stagnation
  - Victim Issue (Bị phong tỏa)      - Single Point of Failure (SPOF)    - QA / Testing Gate Block
  - Circular Wait (Khóa vòng)        - High WIP thrashing                - External / Vendor Wait
  - Architectural Debt Block         - Reviewer Starvation               - Requirement Ambiguity
```

#### A. Cấp độ Nhiệm vụ / Liên kết (Issue-level)
* **Root Blocker (Issue gốc gây nghẽn):** Issue tự thân bị đình trệ trong quá trình thực thi, khiến cho một hoặc nhiều downstream issue khác không thể bắt đầu hoặc không thể hoàn thành. Đây là đối tượng mục tiêu cần dán nhãn `role = root`.
* **Victim Issue (Issue nạn nhân):** Issue đã sẵn sàng triển khai nhưng bị buộc phải dừng lại do phụ thuộc vào Root Blocker. Bản thân issue này không có lỗi nội tại; dán nhãn `role = victim`.
* **Circular Wait (Khóa vòng tròn / Deadlock):** Tình huống Issue $A$ chờ Issue $B$, trong khi Issue $B$ (trực tiếp hoặc gián tiếp qua $C$) lại đang chờ $A$. Thường xuất hiện trong các bài toán tích hợp microservices hoặc tái cấu trúc cơ sở dữ liệu.

#### B. Cấp độ Con người / Nguồn lực (Resource-level)
* **Single Point of Failure (SPOF / Chuyên gia độc quyền):** Một module hoặc công nghệ chỉ có duy nhất một kỹ sư am hiểu. Dù issue không phức tạp, toàn bộ công việc liên quan đều phải xếp hàng đợi kỹ sư này.
* **Overloaded Assignee / Bão hòa Nguồn lực:** Kỹ sư được giao quá nhiều việc quan trọng cùng lúc ($\text{WIP} \ge 5$ việc High Priority). Chi phí chuyển đổi ngữ cảnh liên tục làm suy giảm năng suất thực tế, dẫn đến tất cả các issue của người này đều bị chậm lại.

#### C. Cấp độ Quy trình / Hệ thống (Process/Queue-level)
* **Review Queue Bottleneck (Nghẽn khâu duyệt mã):** Code đã viết xong, chuyển sang "In Review", nhưng nằm im nhiều tuần do đội ngũ review không đủ thời gian hoặc quy trình phê duyệt rườm rà.
* **External Dependency Bottleneck (Chờ đợi bên ngoài):** Issue bị chặn do phụ thuộc vào bên thứ ba (khách hàng không cung cấp thông tin, đối tác vendor chậm cung cấp API, upstream open-source project chưa merge bugfix).
* **Requirement Ambiguity (Đặc tả mơ hồ):** Issue đang code thì phát sinh mâu thuẫn về nghiệp vụ, phải dừng lại để Product Owner hoặc khách hàng làm rõ.

### 3.2. Tính Động theo Giai đoạn (Temporal Nature of Bottlenecks)

Một trong những đóng góp lý thuyết quan trọng nhất của nghiên cứu này là: **Bottleneck là một giai đoạn thời gian (episode), không phải là một thuộc tính bất biến của issue.**

```
Đời issue: [Created] -------- [In Progress] ====[ EPISODE NGHẼN ]==== [In Progress] -------- [Closed]
                                                |                   |
                                             t_start              t_end
                              (Chặn downstream / tắc review)    (Được gỡ / merge)
```

Một issue có thể:
1. Mở ra trong 3 tháng đầu ở trạng thái Backlog: Hoàn toàn bình thường, **không nghẽn**.
2. Đến tháng thứ 4, nó được chọn vào Sprint để làm tiền đề cho một đợt phát hành, nhưng bị kẹt ở "In Review" và bắt đầu chặn 3 issue khác: **Đây là Episode Bottleneck** $[t_{\text{start}}, t_{\text{end}}]$.
3. Sau 2 tuần, bản review được thông qua, issue quay trở lại tiến độ bình thường: **Hết nghẽn**.

Do đó, bài toán học máy không phải là gán nhãn nhị phân tĩnh $y_i \in \{0, 1\}$ cho issue $i$, mà là xác định hàm nhãn động theo thời gian:
$$y_i(t) = 1 \iff \exists \text{ episode } [t_{\text{start}}, t_{\text{end}}] \text{ sao cho } t \in [t_{\text{start}}, t_{\text{end}}] \land \text{role}(i) = \text{root}$$

---

## 4. Định nghĩa Hình thức & Tiêu chí Xác định Điểm nghẽn

### 4.1. Công thức Logic Tổng quát

Một issue $i$ được xác định là điểm nghẽn tại thời điểm $t$ khi và chỉ khi nó thỏa mãn đồng thời: **Có biểu hiện tắc dòng chảy ($F$)**, **Gây ra tác động hệ thống ($I$)**, và **Không thuộc các diện ngoại lệ ($E$)**:

$$\text{Bottleneck}(i, t) \iff \left( \bigvee_{k=1}^4 F_k(i, t) \right) \land \left( \bigvee_{m=1}^3 I_m(i, t) \right) \land \neg \text{Exclusion}(i, t)$$

### 4.2. Chi tiết Nhóm Tiêu chí F (Tắc dòng chảy) và I (Tác động lan truyền)

| Nhóm | Mã | Tên Tiêu chí | Định nghĩa Vận hành (Operational Definition) | Nguồn Tín hiệu trong Jira | Cơ chế Tính toán |
|---|---|---|---|---|---|
| **F – Dòng chảy** | **F1** | **Ứ đọng trạng thái (Stagnation)** | Thời gian lưu trú liên tục tại trạng thái đang làm việc ($Active/Committed$) $\ge p_{90}$ so với toàn dự án (cùng loại issue). | `changelog.status`, `created` | **Mã nguồn (Code)** |
| | **F2** | **Chờ đợi rõ ràng (Explicit Waiting)** | Xuất hiện trao đổi thể hiện việc đang chờ người hoặc sự kiện khác ("waiting for", "blocked by", "pending review", "need input"). | `fields.comment`, `status` | **LLM (Trích xuất) + Code (Xác nhận)** |
| | **F3** | **Dao động & Làm lại (Churn/Rework)** | Trạng thái bị lặp (Reopen, In Progress $\leftrightarrow$ Review $\ge 2$ lần) hoặc Assignee bị đổi qua lại $\ge 3$ lần. | `changelog.status`, `changelog.assignee` | **Mã nguồn (Code)** |
| | **F4** | **Bão hòa / Thiếu nhân lực (Capacity Starvation)** | Issue ưu tiên cao nhưng không có người nhận ($Assignee = \emptyset$), hoặc Assignee đang ôm $\ge 3$ việc ưu tiên cao khác. | `fields.assignee`, `fields.priority` | **Mã nguồn (Code)** |
| **I – Tác động** | **I1** | **Chặn công việc khác (Blocks Others)** | Có $\ge 1$ issue đang mở ($Open/Unresolved$) phụ thuộc vào nó thông qua liên kết Block/Depend. | `issueLinks`, trạng thái issue đích | **Mã nguồn (Code)** |
| | **I2** | **Nằm trên đường găng Release (Milestone Path)** | Có gắn `fixVersion` sắp phát hành, hoặc lịch sử `fixVersion` bị hoãn/đẩy lùi nhiều lần. | `changelog.fixVersions`, `fields.fixVersions` | **Mã nguồn (Code)** |
| | **I3** | **Leo thang can thiệp (Escalation)** | Priority bị nâng lên trong quá trình làm, hoặc comment từ nhiều người hỏi dồn dập ("any update?", "urgent"). | `changelog.priority`, `fields.comment` | **LLM + Code** |

### 4.3. Các Trường hợp Ngoại lệ và Âm tính giả (Exclusions & Edge Cases)

Các trường hợp này nếu chỉ nhìn vào số liệu thô (ví dụ thời gian mở dài) rất dễ bị phân loại nhầm thành điểm nghẽn (dương tính giả - false positives). Quy tắc kiểm toán yêu cầu phải loại trừ:

```
+---------------------------------------------------------------------------------------------------+
|                              BẢNG QUY TẮC LOẠI TRỪ (EXCLUSIONS CODEBOOK)                          |
+----+----------------------+----------------------------------------------+------------------------+
| Mã | Trường hợp           | Biểu hiện trong Dữ liệu                      | Xử lý                  |
+----+----------------------+----------------------------------------------+------------------------+
| E1 | Backlog ngủ quên     | Trạng thái Open nhiều năm, priority thấp,    | Âm tính (0),           |
|    | (Dormant Backlog)    | chưa ai nhận, không ai hỏi thăm.             | excl = backlog         |
+----+----------------------+----------------------------------------------+------------------------+
| E2 | Epic / Umbrella task | Issue bao trùm, sống lâu và liên kết nhiều   | Âm tính (0),           |
|    |                      | theo đúng thiết kế kiến trúc.                | excl = epic            |
+----+----------------------+----------------------------------------------+------------------------+
| E3 | Nhầm lẫn Priority    | Priority = "Blocker" nhưng tiến độ trôi      | Không dùng Priority để |
|    | "Blocker"            | chảy bình thường. "Blocker" ở đây là mức độ  | kết luận nghẽn dòng    |
|    |                      | nghiêm trọng kỹ thuật (Fatal Bug), không     | chảy.                  |
|    |                      | đồng nghĩa với tắc nghẽn quy trình.          |                        |
+----+----------------------+----------------------------------------------+------------------------+
| E4 | Bỏ quên rồi đóng     | Mở thời gian dài rồi đóng với resolution:    | Âm tính (0),           |
|    | "Won't Fix"          | Won't Fix, Duplicate, Cannot Reproduce.      | excl = duplicate_      |
|    |                      | Bản chất là việc bị hủy, không phải tắc.     | or_wontfix             |
+----+----------------------+----------------------------------------------+------------------------+
| E5 | Hoãn có chủ đích     | Comment nêu rõ: "Deferred to version 2.0",   | Âm tính (0),           |
|    | (Deliberate Defer)   | "Postponed until next milestone".            | excl = deferred        |
+----+----------------------+----------------------------------------------+------------------------+
| E8 | Dị vật dọn dẹp data  | Đóng hàng loạt: >= 20 issue được 1 người     | Âm tính (0),           |
|    | (Bulk Close Artifact)| đóng trong cùng 1 phút. Dwell time tăng vọt  | excl = data_artifact   |
|    |                      | trước lúc đóng là ảo giác số liệu.           |                        |
+----+----------------------+----------------------------------------------+------------------------+
```

---

# PHẦN II: ỨNG DỤNG MÔ HÌNH LLM ĐỂ GẮN NHÃN VÀ PHÁT HIỆN ĐIỂM NGHẼN

## 5. Vai trò và Vị thế Chiến lược của LLM

### 5.1. Vì sao Heuristics thuần túy và GNN không tự đủ?

* **Sự bất lực của Heuristics số học:** Các thuật toán heuristic cổ điển (như tính $Age \times Priority$ hoặc đếm số lượng link) không có khả năng hiểu ngữ cảnh. Chúng không thể phân biệt được một issue bị treo do nhà cung cấp bên ngoài (External Dependency) với một issue bị lãng quên (Dormant Backlog), hay một buổi thảo luận kỹ thuật sâu sắc dẫn đến giải pháp tối ưu.
* **Bài học Đắt giá từ Rò rỉ Nhãn (Label Leakage) của GNN:**  
  Trong giai đoạn P0 của dự án này, mô hình Temporal Graph Network (TGN) được huấn luyện trên nhãn phụ thuộc truyền thống (v3 = "issue có liên kết Block/Depend"). Kết quả ban đầu đạt Test AUC rất cao: **0,835 trên JFrog** và **0,768 trên Spring**.  
  Tuy nhiên, qua phân tích chuyên sâu tại `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` §1, chúng tôi phát hiện:
  - Thông tin nhãn đã bị rò rỉ trực tiếp vào đầu vào thông qua vector one-hot loại liên kết trên cạnh (`Block`/`Depend`). Đối với 432/432 issue dương của JFrog, sự kiện liên kết này luôn xảy ra **trước** mốc đánh giá.
  - Khi thực hiện ablation loại bỏ các đặc trưng liên kết rò rỉ (`JFrog_nl1`), AUC lập tức tụt từ **0,835 xuống 0,620**.
  - Khi loại bỏ hoàn toàn sự kiện liên kết (`JFrog_nl2`), AUC tụt thẳng về **0,484 (ngang ngửa đoán ngẫu nhiên)**.  
  *Kết luận khoa học:* GNN không hề học được bất kỳ quy luật tắc nghẽn nào từ lịch sử quy trình (trạng thái, người phụ trách, độ ưu tiên); nó chỉ đơn thuần làm nhiệm vụ đọc lại đặc trưng liên kết. Do đó, muốn mô hình học máy thực sự nắm bắt được bản chất điểm nghẽn, **bắt buộc phải có một nguồn nhãn khách quan, độc lập với các đặc trưng đầu vào**.

### 5.2. Sức mạnh Ngữ nghĩa và Khả năng Phân giải Mơ hồ của LLM

Mô hình Ngôn ngữ Lớn (LLM) sở hữu năng lực vượt trội trong việc:
1. **Phân tích Sắc thái Giao tiếp:** Hiểu được ý nghĩa thực sự của các bình luận kỹ thuật: *"Waiting for PR #1042 to be merged before we can verify the staging build"* $\implies$ Đây là tín hiệu $F2$ (chờ đợi rõ ràng) và chỉ ra vai trò nạn nhân/gốc.
2. **Nhận diện Lý do Trì hoãn:** Nhận biết khi nào một sự chậm trễ là có chủ đích (*"Per management discussion, we are deferring this feature to Q3"*) $\implies$ Áp dụng loại trừ $E5$ (Deferred).
3. **Phân định Vai trò (Root Cause vs. Victim):** Phân tích ngữ cảnh để trả lời: Issue này đang chủ động gây tắc nghẽn cho người khác (`role = root`) hay nó chỉ là nạn nhân thụ động đang phải chờ đợi một thành phần khác (`role = victim`).

### 5.3. Các Cạm bẫy Cố hữu của LLM và Chiến lược Hóa giải

Dù mạnh mẽ về ngữ nghĩa, việc sử dụng LLM cho bài toán gán nhãn khoa học tiềm ẩn 4 rủi ro lớn cần được triệt tiêu bằng kiến trúc hệ thống:

```
+---------------------------------------------------------------------------------------------------+
|                             CẠM BẪY CỐ HỮU CỦA LLM VÀ CHIẾN LƯỢC HÓA GIẢI                         |
+--------------------------+------------------------------------------+-----------------------------+
| Cạm bẫy của LLM          | Biểu hiện Rủi ro                         | Giải pháp Kỹ thuật Hóa giải |
+--------------------------+------------------------------------------+-----------------------------+
| 1. Khiếm khuyết Thời     | LLM tính nhẩm ngày tháng sai lệch;       | KHÔNG cho LLM tự tính ngày. |
|    gian & Số học         | ảo giác về thời lượng cư trú trạng thái. | Code tính sẵn dwell time và |
|                          |                                          | phân vị p80/p90 đưa vào hồ  |
|                          |                                          | sơ (Dossier).               |
+--------------------------+------------------------------------------+-----------------------------+
| 2. Ảo giác Bằng chứng    | LLM tự bịa ra bình luận hoặc timestamp   | Bắt buộc trích dẫn nguyên   |
|    (Hallucination)       | không có thật trong lịch sử issue.       | văn; Code kiểm tra xâu con  |
|                          |                                          | (verbatim check) trước khi  |
|                          |                                          | chấp nhận.                  |
+--------------------------+------------------------------------------+-----------------------------+
| 3. Thiên lệch Hồi cứu    | Dùng thông tin cách issue đóng để phán   | Quy định rõ: Nhãn hồi cứu   |
|    (Hindsight Bias)      | đoán trạng thái tại thời điểm t.         | được dùng kết cục để định   |
|                          |                                          | nghĩa chân lý; nhưng mô     |
|                          |                                          | hình TGN chỉ nhìn quá khứ.  |
+--------------------------+------------------------------------------+-----------------------------+
| 4. Nhiễm Dữ liệu         | Các repo lớn (Spring, JFrog) có thể đã   | Ẩn danh hóa tên tác giả,    |
|    (Data Contamination)  | nằm trong dữ liệu pretrain của LLM.      | chuẩn hóa cấu trúc; đối     |
|                          |                                          | chiếu mô hình local/API.    |
+--------------------------+------------------------------------------+-----------------------------+
```

---

## 6. Kiến trúc Hệ thống Gắn nhãn Lai (Hybrid Labeling Pipeline)

Kiến trúc triển khai thực tế được xây dựng dựa trên nguyên lý: **Code tính toán chính xác số liệu — LLM suy luận ngữ nghĩa — Rule engine tổng hợp quyết định**.

```
                           SƠ ĐỒ KIẾN TRÚC HYBRID LABELING PIPELINE
                           
  [ MongoDB Jira Database ]
              |
              v
  +-----------------------+
  |  1. DOSSIER ENGINE    |  --> Tính toán thời gian thực: dwell days, p90 status,
  |   (jira_adapter/      |      assignee WIP, phát hiện bulk close, trích xuất text
  |    dossier.py)        |
  +-----------------------+
              |
              v (Văn bản Hồ sơ chuẩn hóa: text/{key}.md + signals)
  +-----------------------+
  |   2. LLM REASONER     |  --> Prompting với Codebook đóng băng
  |   (jira_adapter/      |  --> Structured Output: JSON Schema bắt buộc
  |    llm_label.py)      |  --> Self-Consistency: Lấy mẫu N=3, Temperature=0.7
  +-----------------------+
              |
              v (JSON Output thô + Quotes)
  +-----------------------+
  | 3. VERIFICATION ENGINE|  --> Kiểm tra trích dẫn nguyên văn (Exact Match >= 80%)
  |                       |  --> Kiểm tra timestamp hợp lệ trong changelog
  |                       |  --> Tính toán Medoid IoU cho các Episode
  +-----------------------+
              |
              v
  +-----------------------+
  | 4. HYBRID RULE ENGINE |  --> Gộp: (LLM.yes) AND (Exclusion == None)
  |                       |           AND (F_code OR F_llm_verified)
  |                       |           AND (I_code OR I_llm_verified)
  +-----------------------+
              |
              +----------------------------+
              |                            |
              v                            v
      [ Nhãn Final = 0 / 1 ]      [ Hàng đợi Thẩm định ]
      (Tự động chấp thuận)        (Final = 'review')
                                  - LLM không nhất quán
                                  - Bị phát hiện trích dẫn sai
                                  - Mâu thuẫn giữa LLM và Code
```

### 6.1. Tầng Hồ sơ Issue (Dossier Generation Engine)

Để triệt tiêu nhược điểm tính toán của LLM, module `jira_adapter/dossier.py` chuyển đổi dữ liệu thô từ MongoDB thành một bản hồ sơ hoàn chỉnh:
* **Dòng thời gian Trạng thái Khách quan:** Mỗi phân đoạn trạng thái được gắn kèm số ngày thực tế và phân vị so với toàn bộ dự án: `In Progress (14.2 days, p94 vs project)`.
* **Lịch sử Phân công & Tải công việc:** Ghi nhận số lượng issue ưu tiên cao đang mở của người phụ trách tại từng thời điểm.
* **Cờ Phát hiện Dị vật Dữ liệu:** Tự động gắn cờ `bulk_close = True` nếu issue nằm trong đợt đóng hàng loạt ($\ge 20$ issue/phút/người).
* **Kiểm soát Độ dài Văn bản:** Cắt lọc thông minh phần mô tả ($\le 1.500$ ký tự) và danh sách comment (giữ 10 comment đầu và 30 comment cuối, mỗi comment $\le 500$ ký tự) để chống thiên lệch vị trí (position bias) mà vẫn bảo toàn ngữ cảnh.

### 6.2. Kỹ nghệ Prompt & Bộ Quy tắc Chuẩn (Codebook Engineering)

System Prompt của LLM được thiết kế như một **Bộ quy tắc kiểm toán (Auditing Codebook)** bất biến:
* Cung cấp định nghĩa bản chất điểm nghẽn dựa trên dòng chảy công việc.
* Đưa ra danh mục đầy đủ các tiêu chí $F1-F4$ và $I1-I3$.
* Nhắc lại rõ ràng các cạm bẫy: Cấm dùng Priority "Blocker" làm bằng chứng tắc nghẽn; cấm tự suy đoán số ngày.
* Đòi hỏi bằng chứng cho mọi nhận định: *"Mọi khẳng định phải đi kèm một trích dẫn ngắn (5–25 từ) nguyên văn từ hồ sơ."*

### 6.3. Cấu trúc Schema Đầu ra và Ràng buộc Trích dẫn (Grounded Schema)

Sử dụng tính năng **Strict JSON Schema** của API để ép buộc LLM trả về cấu trúc dữ liệu không thể sai lệch:

```json
{
  "is_bottleneck": "yes | no | unsure",
  "role": "root | victim | none",
  "type": "dependency | external | review | resource | requirement | technical | process | null",
  "f_criteria": ["F1", "F2"],
  "i_criteria": ["I1"],
  "waiting_for": "Mô tả ngắn đối tượng đang được chờ đợi hoặc null",
  "evidence": [
    "trích dẫn nguyên văn 1 từ dossier",
    "trích dẫn nguyên văn 2 từ dossier"
  ],
  "episodes": [
    {
      "start": "2018-04-12T10:30:00Z",
      "end": "2018-05-02T15:00:00Z"
    }
  ],
  "exclusion": "backlog | epic | deferred | duplicate_or_wontfix | spike | data_artifact | null",
  "confidence": 0.85,
  "rationale": "Giải thích ngắn gọn trong 1-2 câu."
}
```

### 6.4. Cơ chế Đảm bảo Nhất quán (Self-Consistency & Medoid IoU Aggregation)

Thay vì chỉ gọi LLM một lần duy nhất (zero-shot có phương sai cao), hệ thống áp dụng cơ chế **Self-Consistency (Wang et al., 2022)** với số lần lấy mẫu $N = 3$ (hoặc $N = 5$ ở các ca phức tạp) tại nhiệt độ $T = 0,7$:
1. **Biểu quyết Đa số (Majority Voting):** Quyết định `is_bottleneck`, `role`, `type`, và `exclusion` được chốt theo phương án chiếm đa số tuyệt đối ($> 50\%$). Nếu không có phương án nào đạt quá bán, issue được gán nhãn `review`.
2. **Thuật toán Medoid IoU cho Khoảng thời gian Episode:**  
   Khoảng thời gian nghẽn của các lần lấy mẫu được so sánh thông qua chỉ số tương đồng giao trên hợp (Intersection over Union - IoU):
   $$\text{IoU}(A, B) = \frac{\sum \text{overlap}(A, B)}{\sum \text{duration}(A) + \sum \text{duration}(B) - \sum \text{overlap}(A, B)}$$
   Hệ thống chọn episode của mẫu có tổng chỉ số IoU cao nhất với tất cả các mẫu đồng thuận còn lại (mẫu đại diện - Medoid sample).

### 6.5. Động cơ Kiểm định Chống Ảo giác (Deterministic Verification Engine)

Trước khi chuyển dữ liệu sang bộ quy tắc gộp nhãn, một hàm kiểm định bằng mã nguồn Python (`verify`) sẽ quét toàn bộ câu trả lời của LLM:
* **Xác thực Bằng chứng (Quote Grounding):** Sử dụng thuật toán so khớp xâu con liên tục dài nhất (Longest Common Substring qua `difflib.SequenceMatcher`). Nếu độ dài đoạn khớp $< 80\%$ độ dài trích dẫn của LLM, trích dẫn đó bị đánh dấu là "Bịa đặt (Fabricated Quote)".
* **Xác thực Mốc thời gian (Timestamp Grounding):** Kiểm tra xem các timestamp $start$ và $end$ trong episode có tồn tại chính xác trong tập hợp các mốc thời gian của changelog/comment trong hồ sơ hay không. Nếu LLM tự bịa ra một mốc thời gian không có trong dữ liệu, mốc đó bị loại bỏ.
* **Cờ Báo động:** Nếu một issue có $\ge 1$ bằng chứng bị phát hiện là bịa đặt, toàn bộ kết quả của LLM sẽ bị hạ cấp xuống diện `final = review` để con người kiểm tra.

---

## 7. Khung Đánh giá Độ tin cậy & Kiểm định Con người (Gold Set & Human Alignment)

### 7.1. Thiết kế Thử nghiệm Pilot và Ma trận Lấy mẫu Phân tầng

Để thẩm định chất lượng nhãn mà không tốn chi phí vô ích, một tập thử nghiệm Pilot gồm **300 issue từ dự án JFrog** được lựa chọn theo phương pháp lấy mẫu phân tầng 3 lớp (Stratified Sampling, seed cố định):

```
                        TỔNG QUẦN THỂ JFROG: 15.535 ISSUES
                                        |
        +-------------------------------+-------------------------------+
        |                               |                               |
  [Tầng 1: v3 Dương]           [Tầng 2: Ứng viên F]            [Tầng 3: Ngẫu nhiên]
  - Có link Block/Depend       - Thỏa >= 1 tiêu chí F          - Không thuộc tầng 1, 2
  - Quần thể: 450 issues       - Quần thể: 2.848 issues        - Quần thể: 12.237 issues
  - Mẫu: 60 issues             - Mẫu: 120 issues               - Mẫu: 120 issues
  (Mục đích: Đo lỗi của v3)    (Mục đích: Đo độ nhạy LLM)      (Mục đích: Đo Recall bỏ sót)
```

Trong 300 issue này:
* **100 issue** được chọn ra để **hai chuyên gia quản lý dự án độc lập (Rater A và Rater B) chấm mù đôi (Double-blind annotation)** mà không nhìn thấy kết quả của LLM.
* **200 issue** còn lại được chấm bởi một chuyên gia để hoàn thành tập Gold Set 300 mẫu.

### 7.2. Rubric Chấm Chuẩn cho Chuyên gia Quản lý Dự án (B1–B3 Rubric)

Chuyên gia con người chấm điểm từng issue dựa trên 3 trục độc lập theo thang điểm 0 – 1 – 2 (chi tiết tại `docs/rubric-label-audit-bottleneck.md`):

| Trục | Câu hỏi Trọng tâm | Mức 0 (Không) | Mức 1 (Nhẹ / Trung bình) | Mức 2 (Nghiêm trọng) |
|---|---|---|---|---|
| **B1 – Nghẽn Phụ thuộc** | Issue có đang bị tắc và chặn các công việc khác không? | Không chặn gì, tiến độ bình thường. | Chậm/chặn 1–2 issue, nhưng vẫn có cập nhật xử lý. | Tồn đọng kéo dài **và** chặn nhiều issue quan trọng / chuỗi phụ thuộc dài. |
| **B2 – Nghẽn Người phụ trách** | Kỹ sư phụ trách có dấu hiệu quá tải nghiêm trọng không? | Tải bình thường, phản hồi kịp thời. | Có nhiều việc mở, phản hồi chậm dần qua các tuần. | Rõ ràng quá tải: ôm hàng loạt việc gấp, ngưng trệ giao tiếp hoàn toàn. |
| **B3 – Nghẽn Quy trình** | Issue có bị kẹt ở trạng thái bất thường của dự án không? | Luân chuyển trạng thái bình thường. | Thời gian ở 1 trạng thái lâu hơn mức trung bình dự án. | Kẹt rất lâu tại các hàng đợi hệ thống (chờ review, chờ QA, chờ phê duyệt). |
| **TỔNG KẾT (PM Call)** | *Nếu là Project Manager, hôm nay bạn có muốn được cảnh báo đỏ về issue này không?* | **KHÔNG** (Bình thường / Backlog) | **CÓ THỂ** (Cần theo dõi thêm) | **CÓ — ĐÂY LÀ BOTTLENECK** (Cần can thiệp ngay) |

### 7.3. Đo lường Độ đồng thuận (Inter-Rater Reliability: Cohen’s Kappa & Fleiss’ Kappa)

Để đánh giá mức độ chủ quan của bài toán, độ đồng thuận giữa hai người chấm (Rater A vs. Rater B) được đo lường bằng hệ số **Cohen's Kappa ($\kappa$)**:
$$\kappa = \frac{p_o - p_e}{1 - p_e}$$
Trong đó $p_o$ là tỷ lệ quan sát đồng thuận, $p_e$ là tỷ lệ đồng thuận kỳ vọng ngẫu nhiên.

* **Trần Thực tế của Bài toán (Human Ceiling):** Nếu $\kappa_{\text{human-human}} \approx 0,65$, điều này khẳng định rằng ngay cả các chuyên gia con người cũng có sự bất đồng tự nhiên ở mức 35% trên các trường hợp biên. Khi đó, mục tiêu của LLM không phải là đạt 100% agreement, mà là đạt $\kappa_{\text{LLM-human}} \ge 0,8 \times \kappa_{\text{human-human}}$.

### 7.4. Phân tích Sai số và Cổng Quyết định (Go/No-Go Gates)

Quy trình áp dụng các ngưỡng kiểm định nghiêm ngặt trước khi cho phép mở rộng quy mô gán nhãn:

```
+---------------------------------------------------------------------------------------------------+
|                                CÁC CỔNG QUYẾT ĐỊNH KIỂM ĐỊNH NHÃN (GATES)                         |
+------------------------------+--------------------+-----------------------------------------------+
| Chỉ số Kiểm tra              | Ngưỡng Tối thiểu   | Hành động nếu Không Đạt Ngưỡng                |
+------------------------------+--------------------+-----------------------------------------------+
| Cohen's Kappa Người - Người  | >= 0,60            | DỪNG LẠI. Rà soát và chuẩn hóa lại Codebook;  |
| (100 issue kiểm tra chéo)    |                    | không cố gắng sửa prompt hay gọi LLM tiếp.    |
+------------------------------+--------------------+-----------------------------------------------+
| Cohen's Kappa LLM - Gold     | >= 0,55            | Hiệu chỉnh Prompt: bổ sung thêm 3-5 ví dụ     |
| (trên 300 issue)             | (hoặc >= 0.8 k_h)  | Few-shot cho các ca bị nhầm lẫn nhiều nhất.   |
+------------------------------+--------------------+-----------------------------------------------+
| Precision lớp Dương          | >= 75%             | Siết chặt điều kiện kết hợp Rule: yêu cầu     |
| (Bottleneck = Yes)           |                    | cả F_code lẫn F_llm đều phải đồng thời thỏa.  |
+------------------------------+--------------------+-----------------------------------------------+
| Tỷ lệ Bịa đặt Bằng chứng     | <= 3%              | Kiểm tra lại cấu hình temperature, giảm bớt   |
| (Fabricated Quotes)          |                    | context length hoặc đổi sang model mạnh hơn.  |
+------------------------------+--------------------+-----------------------------------------------+
| Độ chính xác Biên Episode    | IoU >= 0,50        | Ràng buộc LLM chỉ được chọn timestamp từ danh |
| (So với Gold Set)            | hoặc lệch <= 7 ngày| sách mốc sự kiện được cung cấp sẵn.           |
+------------------------------+--------------------+-----------------------------------------------+
```

---

## 8. Ánh xạ Nhãn sang Mô hình Học máy trên Đồ thị Động (TGN Mapping)

Sau khi nhãn bottleneck chất lượng cao được thiết lập bởi hệ sinh thái LLM + Rule, bước tiếp theo là chuyển đổi nhãn này thành bài toán **Dynamic Node Classification** cho Temporal Graph Networks.

### 8.1. Chuyển đổi Episode thành Nhãn Sự kiện và Giải quyết Nghịch lý Im lặng (Inactivity Paradox)

#### Nghịch lý Im lặng (The Inactivity Paradox)
Trong các kiến trúc Graph Neural Network truyền thống cho đồ thị động (như TGN, DyRep, JODIE), việc huấn luyện phân loại nút thường diễn ra **ngay tại thời điểm xảy ra sự kiện** (event-driven evaluation).
Tuy nhiên, đối với bài toán điểm nghẽn, xuất hiện một nghịch lý:
> **Một issue đang bị nghẽn nặng nề nhất lại chính là lúc nó KHÔNG CÓ BẤT KỲ HOẠT ĐỘNG NÀO.** Nó không được chuyển trạng thái, không ai comment, không đổi assignee trong suốt nhiều tuần.

Nếu chỉ đánh giá nhãn tại các thời điểm phát sinh sự kiện, mô hình sẽ hoàn toàn "mù" trong suốt giai đoạn episode tắc nghẽn, dẫn đến việc tập dữ liệu huấn luyện hầu như không có điểm dương (positive sample starvation).

#### Giải pháp Kỹ thuật: Mốc Truy vấn Định kỳ (Periodic Evaluation Ticks)
Để giải quyết triệt để, chúng tôi áp dụng cơ chế **Truy vấn Trạng thái Bộ nhớ Định kỳ**:
1. Không làm biến dạng đồ thị bằng các cạnh giả mạo.
2. Tại mỗi chu kỳ thời gian cố định $\tau$ (ví dụ: mỗi thứ Hai hàng tuần lúc 00:00:00 UTC), hệ thống thực hiện một truy vấn trạng thái (Memory Query) cho tất cả các issue đang mở:
   $$h_i(t) = \text{Embedding}(i, t) = \text{TGN-Memory}(i, t)$$
   $$\hat{y}_i(t) = \text{MLP-Decoder}(h_i(t))$$
3. Nhãn chân lý tại thời điểm truy vấn:
   $$y_i(t) = 1 \iff t \in [t_{\text{start}}, t_{\text{end}}] \text{ của một episode có } role = root$$

```
Dòng sự kiện:   -- (e1) ------- (e2) --------------------------------- (e3) -->
Episode nghẽn:                      [=========== NGHẼN ===========]
Truy vấn TGN:            |             |             |             |
                       tick_1        tick_2        tick_3        tick_4
Nhãn y_i(t):             0             1             1             0
```

### 8.2. Thiết kế Đặc trưng Chống Rò rỉ Triệt để (Leak-Safe Feature Engineering)

Rút kinh nghiệm sâu sắc từ lỗ hổng rò rỉ của nhãn v3 (P0), toàn bộ pipeline đặc trưng được tái thiết kế theo tiêu chuẩn `--leak-safe`:
1. **Loại bỏ Hoàn toàn One-hot Loại Liên kết Hướng tới Tương lai:** Vector cạnh chỉ ghi nhận sự kiện tương tác mà không mã hóa các thuộc tính dự báo trước kết quả.
2. **Point-in-Time Aggregations:** Mọi đặc trưng số lượng (như số lượng comment, số lượng link) phải được tính lũy kế **chính xác tại thời điểm $t$**, nghiêm cấm việc đọc số liệu tổng kết cuối đời của document trong MongoDB.
3. **Phân tách Rõ ràng giữa Tập Dữ liệu Nhãn và Tập Dữ liệu Huấn luyện:**
   - LLM được phép đọc toàn bộ lịch sử (Hồi cứu - Retrospective) để xác lập chân lý khách quan.
   - Bộ nhớ và Bộ giải mã của TGN tại thời điểm $t$ **tuyệt đối chỉ được tiếp cận các sự kiện có timestamp $\le t$**.

### 8.3. Hệ thống Chỉ số Đánh giá Thực tế: AUPRC, Lead Time và Precision@k

Không sử dụng các chỉ số dễ gây ngộ nhận (như Accuracy hay ROC-AUC trên tập dữ liệu mất cân bằng nghiêm trọng), mô hình được đánh giá trên 3 chỉ số có ý nghĩa thực tiễn cao nhất đối với một Project Manager:

1. **AUPRC (Area Under the Precision-Recall Curve):** Thước đo chuẩn mực cho bài toán có tỷ lệ lớp dương chỉ chiếm 3%–5%. Đường baseline của AUPRC chính là tỷ lệ lớp dương ngẫu nhiên; bất kỳ giá trị AUPRC nào đạt $\ge 0,35$ trên tập test đều thể hiện khả năng phân loại vượt bậc.
2. **Lead Time Cảnh báo Sớm (Early Warning Lead Time):**
   $$\Delta t_{\text{lead}} = t_{\text{start}} - t_{\text{alert}}$$
   Trong đó $t_{\text{alert}}$ là thời điểm đầu tiên mô hình đưa ra dự đoán xác suất vượt ngưỡng cảnh báo ($\hat{y}_i(t) \ge \theta$), và $t_{\text{start}}$ là thời điểm episode nghẽn thực sự bắt đầu trong Gold Set. Một mô hình có giá trị thực tiễn cao phải đạt $\Delta t_{\text{lead}} \ge 7 \text{ đến } 14 \text{ ngày}$, cho phép Project Manager can thiệp tái phân bổ nguồn lực trước khi dự án bị tắc.
3. **Precision@k Hàng tuần (Weekly Top-k Actionable Precision):**  
   Mỗi tuần, hệ thống xếp hạng và gửi cho PM danh sách $k$ issue có nguy cơ cao nhất (ví dụ $k=5$ hoặc $k=10$). Chỉ số đo lường tỷ lệ phần trăm các issue trong top-$k$ thực sự là điểm nghẽn:
   $$\text{Precision@}k = \frac{|\text{Top-}k \cap \text{True Bottlenecks}|}{k}$$
   Ngưỡng kỳ vọng vận hành: $\text{Precision@5} \ge 60\%$.

---

## 9. Chiến lược Triển khai, Chưng cất Mô hình và Tối ưu Chi phí

### 9.1. Khảo sát Chi phí Token và Kỹ thuật Prompt Caching

Đo lường thực tế trên mẫu 300 issue JFrog (`data/llm_pilot/JFrog/summary.json`) cho thấy:
* Kích thước trung bình một hồ sơ: Trung vị **487 tokens**, phân vị $p_{90}$ là **935 tokens**, tối đa **3.586 tokens**.
* Tổng token nội dung cho 300 issue: $\approx 170.000$ tokens.
* Phần System Prompt (Codebook) và Few-shot Examples: $\approx 3.000$ tokens.

**Tối ưu hóa Chi phí:**
* **Prompt Caching:** Do Codebook và Schema hoàn toàn cố định giữa tất cả các lượt gọi, việc kích hoạt cơ chế Prompt Caching (trên Anthropic Claude hoặc OpenAI API) giúp giảm **90% chi phí đọc input tokens** và giảm 80% độ trễ suy luận.
* **Batch API:** Áp dụng chế độ xử lý theo lô phi đồng bộ (Asynchronous Batch Processing) giảm thêm 50% chi phí điện toán đám mây cho các đợt gán nhãn quy mô lớn.

### 9.2. Phương án Chưng cất Mô hình (Knowledge Distillation sang Small LLMs / SLMs)

Đối với các dự án mã nguồn mở khổng lồ như Spring (69.156 issues) hoặc toàn bộ 16 instance Jira (hơn 2,7 triệu issues), việc gọi API thương mại độc quyền cho toàn bộ kho dữ liệu là không khả thi về mặt tài chính. Chiến lược công nghệ đề xuất là **Chưng cất Tri thức (Knowledge Distillation)**:

```
[ Teacher Model: Frontier LLM ]  ---> Sinh nhãn chất lượng cao cho 2.000 - 5.000 issues
(Claude 3.5 Sonnet / GPT-4o)          (Kèm chuỗi suy luận Chain-of-Thought & Evidence)
               |
               v
[ Fine-tuning / QLoRA Dataset ]  ---> Đóng gói cặp (Dossier, JSON Bottleneck Label)
               |
               v
[ Student Model: Local SLM ]     ---> Tinh chỉnh Qwen-2.5-7B-Instruct / Llama-3.1-8B-Instruct
(Chạy trên GPU cục bộ RTX/A100)       Đạt 92-95% độ chính xác của Teacher Model
                                      Chi phí API = $0, tốc độ xử lý hàng trăm ngàn issue
```

### 9.3. Kiến trúc Vận hành Thực tế (Production Architecture: LLM + TGN Dual-Engine)

Trong môi trường triển khai doanh nghiệp thực tế, hai công nghệ này không loại trừ nhau mà kết hợp tạo thành **Hệ thống Động cơ Kép (Dual-Engine Bottleneck Intelligence System)**:

```
+---------------------------------------------------------------------------------------------------+
|                        KIẾN TRÚC VẬN HÀNH DUAL-ENGINE TRONG DOANH NGHIỆP                          |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [ Jira Real-time Webhook Stream ]                                                                |
|                 |                                                                                 |
|                 v                                                                                 |
|  +-------------------------------------------------------------+                                  |
|  | ENGINE 1: TEMPORAL GRAPH NETWORK (TGN - FAST PATH)          |                                  |
|  | - Chạy liên tục 24/7 ở cấp độ milli-giây trên dòng sự kiện. |                                  |
|  | - Cập nhật vector Memory của từng issue và assignee.        |                                  |
|  | - Tính toán xác suất rủi ro nghẽn P(Bottleneck) cho toàn    |                                  |
|  |   bộ 10.000+ issue trong vòng vài giây.                     |                                  |
|  +-------------------------------------------------------------+                                  |
|                 |                                                                                 |
|                 v (Bộ lọc Ngưỡng: Chỉ kích hoạt khi P >= 0.70)                                    |
|  +-------------------------------------------------------------+                                  |
|  | ENGINE 2: LLM AGENT AUDITOR (SLOW PATH / DEEP REASONING)    |                                  |
|  | - Đọc chi tiết Dossier của top 20 issue bị TGN cảnh báo.   |                                  |
|  | - Xác minh bằng chứng trong thảo luận (Review, QA, Vendor). |                                  |
|  | - Thực hiện Phân tích Nguyên nhân Gốc rễ (Root Cause RCA).  |                                  |
|  | - Đưa ra khuyến nghị hành động cụ thể cho Project Manager.  |                                  |
|  +-------------------------------------------------------------+                                  |
|                 |                                                                                 |
|                 v                                                                                 |
|  [ Dashboard Cảnh báo PM & Slack/Teams Actionable Alerts ]                                        |
|  "Cảnh báo: Issue RTFACT-9109 có nguy cơ gây tắc nghẽn bản release 6.2 trong 10 ngày tới.        |
|   Lý do: Đang chờ dev-a12 duyệt PR từ 12 ngày trước (p95 dwell). Downstream: 3 issue đang chờ."  |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
```

---

# KẾT LUẬN VÀ LỘ TRÌNH TRIỂN KHAI

## Kết luận Khoa học

1. **Về mặt Lý thuyết:** Điểm nghẽn trong dự án phần mềm không thể đồng nhất với thời gian mở dài hay mức độ nghiêm trọng kỹ thuật. Điểm nghẽn mang bản chất dòng chảy và lan truyền: nó đòi hỏi sự kết hợp chặt chẽ giữa hiện tượng **Tắc dòng chảy ($F$)** và **Tác động lan truyền ($I$)**, diễn ra trong một **khoảng thời gian động (Episode)** cụ thể.
2. **Về mặt Phương pháp luận Học máy:** Thất bại của nhãn v3 (rò rỉ đặc trưng khiến AUC rớt từ 0,835 về 0,484 khi làm sạch) là minh chứng đắt giá cho thấy các mô hình Graph Neural Network không thể tự bù đắp cho một hệ thống nhãn sai lệch. Việc sử dụng LLM làm bộ trích xuất tín hiệu ngữ nghĩa kết hợp với quy tắc kiểm toán hình thức là giải pháp tối ưu để tạo ra nhãn huấn luyện chuẩn mực.
3. **Về mặt Kỹ thuật Triển khai:** Mô hình lai (Code chuẩn bị số liệu $\to$ LLM suy luận ngữ nghĩa $\to$ Code kiểm định trích dẫn $\to$ TGN dự báo thời gian thực) khắc phục hoàn toàn điểm yếu ảo giác và tính toán kém của LLM, đồng thời phát huy tối đa sức mạnh biểu diễn đồ thị động của TGN.

## Lộ trình Triển khai Chi tiết Tiếp theo (Next Steps Roadmap)

```
[ P0: Hoàn tất ]  --> Đo lường rò rỉ nhãn v3 (AUC 0.835 -> 0.484); sửa các lỗi pipeline;
                      hoàn thiện cờ --leak-safe và chuẩn hóa priority.

[ P1: Hoàn tất ]  --> Xây dựng dossier.py, sampling.py; tạo bộ hồ sơ 300 issue pilot JFrog
                      và phân bổ ma trận chấm mù đôi.

[ P2: Đang làm ]  --> Chạy thực tế người chấm Gold Set trên 100 issue kiểm tra chéo;
                      tính toán hệ số Cohen's Kappa người-người để xác lập trần bài toán.

[ P3: Đang làm ]  --> Chạy llm_label.py trên trọn vẹn 300 issue pilot JFrog;
                      áp dụng cơ chế Self-Consistency và kiểm định trích dẫn chống ảo giác.

[ P4: Kế tiếp ]   --> Đối chiếu LLM vs. Gold Set; kiểm tra các cổng chất lượng (Kappa >= 0.6,
                      Precision >= 75%); tinh chỉnh Codebook nếu phát hiện bất đồng.

[ P5: Kế tiếp ]   --> Mở rộng gán nhãn cho toàn bộ JFrog; bổ sung cơ chế Periodic Evaluation Ticks;
                      huấn luyện lại TGN trên nhãn Episode mới không rò rỉ.

[ P6: Kế tiếp ]   --> Mở rộng sang Spring (69k issue); chưng cất sang Local SLM (Qwen/Llama)
                      để tối ưu hóa chi phí vận hành.
```

---
*Tài liệu này đóng vai trò là kim chỉ nam lý thuyết và đặc tả kiến trúc chính thức cho các pha thực nghiệm tiếp theo của đề tài.*
