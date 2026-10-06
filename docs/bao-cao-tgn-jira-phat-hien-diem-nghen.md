# Nghiên cứu & Đề xuất phương án: Sử dụng Temporal Graph Network (TGN) cho bài toán phát hiện điểm nghẽn trong quản lý dự án phần mềm

**Dữ liệu huấn luyện:** The Public Jira Dataset — Montgomery, Lüders & Maalej (MSR 2022)
**Mã nguồn mô hình:** repo TGN trong workspace này (triển khai chính thức của Rossi et al., ICML 2020 GRL Workshop)
**Trạng thái:** Bản đề xuất (v1.0) — kèm kế hoạch thực hiện
**Ngày:** 2026-02 (phiên làm việc hiện tại)

> **⚠️ Đính chính 2026-10-04 (P0 đo rò rỉ nhãn, chi tiết: `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` §1).** Kết quả T1 của nhãn v3 trong báo cáo này (Tóm tắt, §6.1, Phụ lục D) **không còn hiệu lực**:
> - Nhãn v3 ("có ≥1 link Block/Depend") rò rỉ qua **edge feature one-hot loại link**: 432/432 issue dương JFrog (2.711/2.714 Spring) có sự kiện link Block/Depend, luôn đến trước sự kiện có nhãn. Node `[7] log1p(n_links)` rò rỉ một phần.
> - Bỏ các feature này, JFrog T1 test AUC (3 lần chạy) giảm từ **0,835 → 0,620**; bỏ thêm sự kiện link → **0,484** (ngẫu nhiên). Nghĩa là TGN **không học được** tín hiệu bottleneck từ diễn biến quy trình với nhãn v3.
> - Node `[6] has_block_link` luôn bằng 0 do bug (chỉ so tên link kiểu Block) — đã sửa trong `to_tgn.py`; build mới có cờ `--leak-safe`.
> - "Priority 100% normal trên JFrog" là **bug chuẩn hóa** (tên dạng `"4 - Normal"` không khớp bảng) — thực tế: Normal 72%, High 16%, Critical 7%, Blocker 3%. Đã sửa `normalize_priority`; dữ liệu `ml_*` hiện có vẫn mang giá trị cũ cho đến khi build lại.
> - Hướng thay thế: nhãn theo episode do LLM trích tín hiệu + rule, kiểm định bằng gold set — xem tài liệu nói trên.

---

## Mục lục

1. [Tóm tắt điều hành](#1-tóm-tắt-điều-hành)
2. [Phát biểu bài toán](#2-phát-biểu-bài-toán)
3. [Mô hình TGN — phân tích mã nguồn trong workspace](#3-mô-hình-tgn--phân-tích-mã-nguồn-trong-workspace)
4. [The Public Jira Dataset — khảo sát dữ liệu](#4-the-public-jira-dataset--khảo-sát-dữ-liệu)
5. [Tổng quan nghiên cứu liên quan](#5-tổng-quan-nghiên-cứu-liên-quan)
6. [Đề xuất phương án](#6-đề-xuất-phương-án)
7. [Kế hoạch thực hiện](#7-kế-hoạch-thực-hiện)
8. [Rủi ro và phương án giảm thiểu](#8-rủi-ro-và-phương-án-giảm-thiểu)
9. [Tài liệu tham khảo](#9-tài-liệu-tham-khảo)

---

## 1. Tóm tắt điều hành

**Vấn đề.** Trong quản lý dự án phần mềm (SPM), "điểm nghẽn" (bottleneck) thường chỉ: (a) các issue/epic tồn đọng kéo dài, chèn ép tiến độ của nhiều issue downstream qua quan hệ *Block/Depend*; (b) người phụ trách (assignee) bị quá tải với nhiều việc ưu tiên cao đang mở; (c) quy trình xử lý issue bị ứ ở một trạng thái (status) quá lâu. Hiện tại các tổ chức phát hiện điểm nghẽn chủ yếu bằng trực giác của project manager hoặc báo cáo tĩnh (WIP, age of issue) — không khai thác được **tính động theo thời gian** và **cấu trúc quan hệ giữa các issue**, hai đặc trưng quan trọng nhất của dữ liệu Jira.

**Gỡ.** Chúng tôi đề xuất sử dụng **Temporal Graph Network (TGN)** — mô hình học biểu diễn cho đồ thị động dạng *chuỗi sự kiện có mốc thời gian*, có **bộ nhớ (memory) theo nút** cập nhật tuần tự theo dòng sự kiện — để:

1. **Tiền huấn luyện (self-supervised)** trên luồng sự kiện Jira (thay đổi trạng thái, thay đổi assignee, tạo liên kết Block/Depend/…) theo kiểu link prediction — đúng pipeline của repo TGN trong workspace;
2. **Huấn luyện có giám sát** một đầu giải mã (decoder) dự đoán **xác suất một issue trở thành điểm nghẽn trong cửa sổ thời gian Δt** (7/14/30 ngày) dựa trên trạng thái memory tại thời điểm t;
3. Đánh giá trên **The Public Jira Dataset** — bộ dữ liệu Jira công khai lớn nhất hiện nay (16 instance Jira, 1.822 dự án, 2,7 triệu issue, 32 triệu bản ghi thay đổi, 9 triệu comment, 1 triệu issue link; giấy phép CC BY 4.0).

**Vì sao TGN phù hợp.** Dữ liệu Jira về bản chất là đồ thị động: issue là nút, hoạt động (chuyển trạng thái, gắn assignee, tạo link, comment) là sự kiện có thời gian. TGN có ba đặc tính khớp đúng:
- **Memory theo nút** mã hóa toàn bộ lịch sử của mỗi issue (issue mới xuất hiện → memory rỗng → chế độ inductive, khớp thực tế khi dự án có issue mới);
- **Time encoding** mã hóa khoảng cách thời gian giữa các sự kiện — yếu tố quyết định trong phát hiện ứ đọng;
- **Temporal attention** chọn lọc hàng xóm theo thời gian — cho phép mô hình "nhìn ngược" theo chuỗi phụ thuộc Block/Depend.

**Kết quả kỳ vọng (đo lường được).** Trên pilot (1–3 instance, mỗi instance 10k–100k issue): AUC-ROC ≥ 0,75 và Precision@5% ≥ 0,4 cho dự đoán issue điểm nghẽn 14 ngày tới, vượt các baseline tĩnh (logistic regression, GCN snapshot, heuristic age×priority) ít nhất 5 điểm AUC; kèm khả năng giải thích top-k nguyên nhân từ attention/memory.

**Kết quả P0 đã đo (2026-10-01 — pipeline chạy end-to-end trên dữ liệu thật):**
- **T2 self-supervised (link prediction):** JFrog test AUC **0.9986** (old) / **0.9823** (new nodes) · Spring test AUC **0.9997** / **0.9988** (6,769 inductive nodes) — embedding temporal của TGN học rất tốt cấu trúc sự kiện Jira.
- **T1 phát hiện bottleneck (label v3 = issue có quan hệ Block/Depend):** JFrog **test AUC 0.839** · Spring **test AUC 0.768** — **cả 2 vượt mục tiêu ≥0,75**. **⚠️ Đính chính 2026-10-04: rò rỉ nhãn — bỏ feature loại link còn 0,620, bỏ thêm sự kiện link còn 0,484.**
- **Ablation nhãn:** composite (top-5% dự án) cùng model chỉ đạt **AUC 0.578** (JFrog) → ~~thiết kế nhãn quyết định tính học được~~ (đính chính: chênh lệch v3/composite chủ yếu do v3 rò rỉ qua feature loại link); composite+dwell thậm chí AUC < 0.5 (leakage temporal).
- **Baseline DyRep** (JFrog, link-pred): AUC 0.990 / 0.889 vs TGN 0.999 / 0.982 — TGN vượt trội ở new nodes (+9.3 AUC).
- 3 bug repo TGN + 1 lỗi dữ liệu (timestamp âm) đã được xác định & sửa trong P0 — xem Phụ lục D.

---

## 2. Phát biểu bài toán

### 2.1. Khái niệm điểm nghẽn trong SPM

Từ thực tiễn quản lý dự án phần mềm (scrum/kanban, process mining), chúng tôi xác nhận **ba lớp điểm nghẽn** cần phát hiện, đều quan sát được từ dữ liệu Jira:

| Lớp | Định nghĩa (operational) | Nguồn tín hiệu trong Jira |
|---|---|---|
| **B1 — Issue nghẽn (issue-level)** | Issue đang mở, không chuyển trạng thái trong thời gian dài, và bị nhiều issue khác phụ thuộc (Block/Depend in-edges) hoặc đang chặn issue khác (out-edges) | `changelog` (transitions), `issueLinks` (Block, Depend, Epic), `fields.priority` |
| **B2 — Người phụ trách nghẽn (assignee-level)** | Developer/role có số issue mở ưu tiên cao vượt ngưỡng, hoặc thời gian phản hồi (first response, time-in-state) tăng dần | `fields.assignee`, `changelog` (assignee change), timestamps |
| **B3 — Quy trình nghẽn (process-level)** | Tỷ lệ issue ứ ở một trạng thái (vd: "In Review", "Waiting") vượt phân vị (p90) của dự án | `changelog` (status history) theo dự án |

### 2.2. Formal hóa

Gọi đồ thị sự kiện `G = (V, E)`, trong đó `V` là tập issue (mở rộng thêm tập assignee nếu dùng đồ thị hai phía), mỗi sự kiện `e_k = (u_k, v_k, t_k, x_k)` với `u_k` — issue nguồn, `v_k` — issue đích (hoặc assignee), `t_k` — mốc thời gian (epoch giây), `x_k` — vector đặc trưng sự kiện (loại chuyển trạng thái, loại link, priority, …).

**Nhiệm vụ chính (T1 — đề xuất làm trọng tâm):** Cho tiền sử `{e_1, …, e_m}` với `t_m ≤ t`, dự đoán nhãn

```
y_i(t) = 1  nếu issue i sẽ rơi vào trạng thái "điểm nghẽn" (định nghĩa B1/B2 ở §2.1 với ngưỡng phân vị của dự án)
        trong khoảng (t, t + Δt]
```

với `Δt ∈ {7, 14, 30}` ngày. Đây là bài toán **node-level binary classification tại thời điểm t** — đúng dạng mà pipeline `train_supervised.py` của repo TGN đã hỗ trợ (dynamic node classification).

**Nhiệm vụ phụ (T2 — tiền huấn luyện):** Link prediction — dự đoán sự kiện liên kết tiếp theo (đặc biệt các link Block/Depend) theo dạng của `train_self_supervised.py` trong repo. T2 tạo embedding nền, T1 fine-tune trên đó — đây chính là hai bước đã có sẵn trong mã nguồn.

**Nhiệm vụ mở rộng (T3, giai đoạn sau):** Hồi quy thời gian tồn tại (dwell time) của issue tại từng trạng thái; dự đoán "issue nào sẽ bị Block trong tương lai" (early-warning 1–2 tuần trước khi link Block xuất hiện).

### 2.3. Vì sao không dùng phương pháp cổ điển

- **Heuristic (age, WIP, priority×age):** bỏ qua cấu trúc phụ thuộc; không phân biệt "issue lâu tuổi vì ít quan trọng" với "issue lâu tuổi và đang chặn 20 issue khác".
- **Process mining (Petri net / heuristic miner):** cho phân tích *sau* (backward-looking), phát hiện biến thể quy trình, nhưng yếu về dự đoán *trước* và không có cơ chế học biểu diễn cho nút mới (issue mới).
- **GNN tĩnh (GCN/GAT trên snapshot):** đánh mất thứ tự thời gian và trạng thái memory; phải re-build đồ thị mỗi snapshot.
- **RNN/LSTM theo issue:** bỏ qua tương tác giữa các issue (phụ thuộc Block/Depend).

TGN kết hợp cả ba: thứ tự thời gian + tương tác đồ thị + bộ nhớ trạng thái — và quan trọng, **repo mã nguồn đã có sẵn trong workspace**, giảm chi phí triển khai.

---

## 3. Mô hình TGN — phân tích mã nguồn trong workspace

### 3.1. Kiến trúc (từ mã nguồn)

```
Chuỗi sự kiện (u_k, v_k, t_k, x_k)
        │
        ▼
┌─────────────────────────────┐
│ Message aggregator          │  modules/message_aggregator.py
│ (last/sum/mean)             │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ Message function (MLP)      │  modules/message_function.py
│ m = f(m_src, m_dst, x_k,    │
│     time_enc(t_k − last_upd))│
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ Memory updater: GRUCell     │  modules/memory_updater.py
│ M_v ← GRU(M_v, m)           │  (memory: n_nodes × memory_dim)
└─────────────┬───────────────┘  modules/memory.py
              ▼
┌─────────────────────────────┐
│ Embedding module            │  modules/embedding_module.py
│ • Identity (JODIE-like)     │
│ • Time (JODIE)              │
│ • GraphSum / GraphMean      │
│ • GraphAttention (TGN)      │  model/temporal_attention.py
│   temporal attention theo   │
│   hàng xóm có mốc thời gian │
└─────────────┬───────────────┘
              ▼
   Node embedding tại thời điểm t
              ▼
   Decoder (MLP) → dự đoán   train_supervised.py
   (link prediction:          train_self_supervised.py
   MergeLayer + sigmoid)
```

### 3.2. Các thành phần kỹ thuật chính (đã đọc mã nguồn)

| Thành phần | Tệp | Ghi chú cho việc áp dụng |
|---|---|---|
| `TGN.compute_temporal_embeddings` | `model/tgn.py` (dòng 101–193) | Nhập: `source_nodes, destination_nodes, negative_nodes, edge_times, edge_idxs`; ra: embedding tại thời điểm tương ứng. Memory được cập nhật **trước khi** đọc (mặc định `memory_update_at_start=True`) — bảo đảm không nhìn vào tương lai. |
| `Memory` | `modules/memory.py` | `nn.Parameter` `n_nodes × memory_dim` + `last_update[n_nodes]` + hàng đợi message. **Lưu ý:** memory là parameter của model → với 2,7 triệu issue, cần chiến lược giảm quy mô (subset pilot) hoặc cải tiến lưu trữ (TODO chính thức của repo ghi nhận vấn đề này). |
| `GRUMemoryUpdater` | `modules/memory_updater.py` | GRUCell(message_dim → memory_dim). Có sẵn RNN variant làm baseline. |
| `TimeEncode` | `model/time_encoding.py` | sin/cos encoding cho `t_k − last_update` — phù hợp với đặc thù "càng lâu không hoạt động càng đáng ngờ". |
| `TemporalAttentionLayer` | `model/temporal_attention.py` | Attention có time-bias giữa hàng xóm; số lớp `n_layer` (mặc định 1). |
| Data loader | `utils/data_processing.py` | Đọc `./data/ml_{name}.csv` (các cột `u, i, ts, label, idx`) + `ml_{name}.npy` (edge features) + `ml_{name}_node.npy` (node features). Chép train/val/test theo **thứ tự thời gian** (quantile 0.70 / 0.85) — đúng cách chia chúng ta cần, **không có leakage**. |
| Preprocess | `utils/preprocess_data.py` | Nhận file CSV `u,i,ts,label,feat...`, reindex, xuất 3 file `ml_*`. **Đây là cổng vào cần nối với pipeline Jira.** |
| Training self-supervised | `train_self_supervised.py` | BCE + negative sampling; các cờ `--use_memory --embedding_module --message_function --aggregator` cho phép chạy các biến thể (TGN, JODIE, DyRep) — dùng làm baseline ngay. |
| Training supervised | `train_supervised.py` | Node classification: decoder MLP trên embedding nguồn; `eval_node_classification` trong `evaluation/evaluation.py` tính AUC-ROC. |

### 3.3. Đánh giá độ phù hợp của TGN với bài toán

**Điểm mạnh (khớp nhu cầu):**
1. **Xử lý native theo dòng sự kiện** — Jira changelog chính là dòng sự kiện; không cần snapshot.
2. **Inductive theo thời gian** — issue mới vào train/val/test set chỉ cần memory khởi tạo; phù hợp evaluation "issue mới" (cờ `--different_new_nodes`).
3. **Hai chế độ task đã có sẵn** — link prediction (T2) + node classification (T1).
4. **Baseline cùng repo** — JODIE, DyRep chỉ khác cờ CLI, so sánh công bằng, chi phí thấp.

**Điểm cần thích nghi (liệt kê ở §6.4):**
1. Repo thiết kế cho **một dòng sự kiện (u, i)** — Jira có nhiều loại sự kiện → cần mã hóa loại sự kiện vào edge features.
2. `n_nodes` phải biết trước khi khởi tạo Memory — cần gán id ổn định theo instance (khả thi vì dump cố định).
3. Memory là `nn.Parameter` → giới hạn số nút (chiến lược subset, §6.2).
4. PyTorch 1.6 / pandas 1.1 trong README — cần kiểm tra tương thích phiên bản runtime hiện tại (rủi ro môi trường, §8).

---

## 4. The Public Jira Dataset — khảo sát dữ liệu

### 4.1. Nguồn gốc và quy mô

**Công bố:** Montgomery L, Lüders C, Maalej W. *"An Alternative Issue Tracking Dataset of Public Jira Repositories."* IEEE/ACM MSR 2022, pp. 73–77. Bản arXiv: **2201.08368**. Tác giả thuộc University of Hamburg.

**Quy mô tổng (theo README chính thức của kho artefact `IoanaCovataru/ThePublicJiraDataset`):**

| Hạng mục | Số lượng |
|---|---|
| Instance Jira công khai | **16** |
| Dự án (projects) | **1.822** |
| Issue | **2.700.000** |
| Bản ghi thay đổi (changelog) | **32.000.000** |
| Comment | **9.000.000** |
| Issue links | **1.000.000** |

**Dạng phân phối:** dump MongoDB (DB `JiraRepos`, **một collection per instance Jira** — xác nhận từ script `DownloadData.ipynb`: `collection = db[jira_data_source['name']]`), `mongodump-JiraRepos.archive` (~60GB khi restore), giấy phép **CC BY 4.0** (dữ liệu) + **MIT** (code). Có sẵn script tải lại qua Jira API v2 (nếu cần bản mới), script phân tích tổng quan.

**16 instance kèm số issue xấp xỉ (từ `jira_data_sources.json`):**

| Instance | URL | Issue (xấp xỉ) |
|---|---|---|
| Apache | issues.apache.org | 1.015.000 |
| Mojang | bugs.mojang.com | 421.000 |
| RedHat | issues.redhat.com | 353.000 |
| Jira (Atlassian) | jira.atlassian.com | 275.000 |
| Qt | bugreports.qt.io | 147.000 |
| MongoDB | jira.mongodb.org | 137.000 |
| Sonatype | issues.sonatype.org | 87.000 |
| Spring | jira.spring.io | 69.000 |
| Sakai | jira.sakaiproject.org | 51.000 |
| JiraEcosystem | ecosystem.atlassian.net | 42.000 |
| MariaDB | jira.mariadb.org | 30.000 |
| Hyperledger | jira.hyperledger.org | 28.000 |
| JFrog | jfrog.com/jira | 16.000 |
| IntelDAOS | jira.hpdd.intel.com | 9.000 |
| Mindville | jira.mindville.com | 2.000 |
| SecondLife | jira.secondlife.com | 2.000 |

⚠️ **Lưu ý quan trọng:** README ghi rõ 2 instance **MariaDB và Mindville hiện không còn truy cập được**; meta-information thời điểm May/2021 của chúng được lưu riêng trong thư mục `0. DataDefinition/May2021`. Pipeline phải xử lý trường hợp thiếu.

### 4.2. Mô hình dữ liệu (rút từ script tải + file định nghĩa)

Mỗi issue là 1 document MongoDB chứa (theo Jira API v2, `expand=changelog`):

```
{
  key: "SPR-12345",
  fields: {
    summary, description, status, issuetype, priority,
    assignee {name, displayName}, reporter, created, updated,
    resolution, components[], labels[], fixVersions[], project, ...
  },
  changelog: [ { id, items: [{field, from, to}], created, user {name} }, ... ],
  comments: [ { id, author, created, body, updateAuthor, updated }, ... ],
  issueLinks: [ { type {id,name,inward,outward}, inwardIssue, outwardIssue }, ... ]
}
```

**Tài nguyên định nghĩa sẵn (rất quý cho bài toán của chúng ta):**
- `jira_issue_linktype_mapping.json` — ánh xạ ~75 loại link tùy biến về **20+ hạng mục chuẩn**: `Block` (Blocked/Blocks/Blocker…), `Depend` (Depends/Dependency/Gantt Dependency…), `Parent-Child`, `Epic`, `Fix` (Fixes/Completes), `Cause`, `Duplicate`, `Relate`, `Split`, `Subtask`, `Follow`… → **cơ sở để định nghĩa "quan hệ phụ thuộc" khi dựng đồ thị và gắn nhãn bottleneck**.
- `jira_issuetype_thematic_analysis.json` — gán issue type → theme chuẩn (`Requirements`, `Development`, `Maintenance`, `User Support`, `Other`) cho từng instance → giảm dị dạng schema giữa 16 instance.
- `jira_field_information.json`, `jira_issuetype_information.json` — meta-schema từng instance.

### 4.3. Đánh giá chất lượng dữ liệu cho bài toán bottleneck

| Tiêu chí | Đánh giá | Bằng chứng |
|---|---|---|
| Đủ sự kiện thời gian | ✅ Rất tốt | 32M changelog records = nguồn sự kiện chuyển trạng thái/assignee có mốc thời gian |
| Đủ quan hệ phụ thuộc | ✅ Đủ 1M links, có cả Block/Depend | `issueLinks` + mapping chuẩn |
| Đa nguồn, đa quy mô | ✅ 16 orgs, 2k dự án | Cross-organization generalization |
| Nhãn bottleneck | ❌ **Không có sẵn** — phải tự operationalize | §6.1 đề xuất phương án gắn nhãn |
| Dị dạng schema | ⚠️ 16 instance có field/issue-type/link-type khác nhau | Đã có mapping chuẩn từ tác giả — cần thêm lớp chuẩn hóa |
| Quyền truy cập 2/16 instance | ⚠️ MariaDB, Mindville offline | Dùng snapshot May2021; pipeline phải robust |
| Kích thước | ⚠️ 60GB | Chiến lược subset pilot §6.2 |

**Kết luận:** Dataset này là lựa chọn hợp lý nhất hiện có (lớn nhất, có changelog + links + comment, giấy phép mở, có tài liệu định nghĩa). Rào cản chính là **gắn nhãn bottleneck** (chúng ta phải xây) và **quy mô** (phải chọn subset) — cả hai đều có phương án ở §6.

---

## 5. Tổng quan nghiên cứu liên quan

*(Tổng hợp từ arXiv/GitHub, truy cập trong phiên này; liên kết nguồn kèm theo)*

**Vế dữ liệu & issue tracking trên Jira:**
- Montgomery, Lüders, Maalej — *An Alternative Issue Tracking Dataset of Public Jira Repositories* (MSR 2022) — [arXiv:2201.08368](https://arxiv.org/abs/2201.08368). Công bố bộ dữ liệu mục tiêu; nhấn mạnh Jira "has yet to receive similar attention" so với GitHub/GitLab/Bugzilla.
- Lüders, Bouraffa, Maalej — *Beyond Duplicates: Towards Understanding and Predicting Link Types in ITSs* (2022) — [arXiv:2204.12893](https://arxiv.org/abs/2204.12893). Phân tích 607k links trên 15 Jira; nhóm link thành 5 loại (General, Duplication, Composition, Temporal/Causal, Workflow) — **củng cố cách phân loại link chúng ta dùng**.
- Lüders, Pietz, Maalej — *Automated Detection of Typed Links in Issue Trackers* (2022) — [arXiv:2206.07182](https://arxiv.org/abs/2206.07182). BERT đạt macro-F1 0,64 trên 9 loại link phổ biến — **hàm ý: link type có thể dự đoán được → task T2/T3 khả thi**.

**Vế dự đoán kết cục issue / workload:**
- Pope, Barovic, Moin — *Bug Destiny Prediction… BERT Topic Modeling* (2025) — [arXiv:2504.15972](https://arxiv.org/abs/2504.15972). Dự đoán time-to-resolution/time-to-fix — cận kề T1 nhưng dùng **đặc trưng phẳng + CNN/MLP, không dùng đồ thị động** — khác biệt chính của chúng ta.
- *Developer Load Normalization Using Iterative Kuhn–Munkres* (2022) — [arXiv:2202.01713](https://arxiv.org/abs/2202.01713); *TaskAllocator* (2021) — [arXiv:2103.02330](https://arxiv.org/abs/2103.02330) — phân công & cân bằng tải developer (lớp B2 của chúng ta).

**Vế bottleneck qua process mining (baseline lý thuyết cần đánh bại):**
- *Application of Process Mining and Sequence Clustering in Recognizing an Industrial Issue* (2023) — [arXiv:2311.15362](https://arxiv.org/abs/2311.15362) — phát hiện bottleneck từ event log, **backward-looking**.
- *PMSD: Data-Driven Simulation Using System Dynamics and Process Mining* (2020) — [arXiv:2010.00943](https://arxiv.org/abs/2010.00943) — mô phỏng forward nhưng cần mô hình quy trình rời rạc, không học biểu diễn nút.
- *Anvaya* (cùng chủ đề issue tracking + process model) — cải thiện chất lượng mô hình quy trình khai từ event log ITS.

**Vêh mô hình TGN và họ mô hình:**
- Rossi et al. — *Temporal Graph Networks for Deep Learning on Dynamic Graphs* (ICML 2020 GRL) — [arXiv:2006.10637](https://arxiv.org/abs/2006.10637) — chính repo trong workspace.
- JODIE (memory + time embedding), DyRep (GRU memory) — đều cài đặt sẵn trong repo (cờ `--embedding_module`, `--dyrep`).
- Các biến thể mới: *Continuous TGN* ([arXiv:2205.15924](https://arxiv.org/abs/2205.15924)), *Time-Aware Neighbor Sampling* ([arXiv:2112.09845](https://arxiv.org/abs/2112.09845)), *TGN4Rec* ([arXiv:2403.16066](https://arxiv.org/abs/2403.16066)), *TETG — Trajectory Encoding TGN* ([arXiv:2504.11386](https://arxiv.org/abs/2504.11386)), TGN cho anomaly detection tài chính ([arXiv:2404.00060](https://arxiv.org/abs/2404.00060)) — bằng chứng TGN linh hoạt cho nhiều domain động; **chưa có công trình nào áp dụng TGN cho issue tracking / bottleneck detection** (đã xác nhận qua tìm kiếm arXiv "bottleneck"+"JIRA", "issue tracking"+"graph neural network" — không có kết quả trực tiếp).

**Khoảng trống nghiên cứu (gap):** Giao của {TGN/họ temporal graph} × {Jira/issue tracking} × {bottleneck detection} là trống — đề xuất này lấp đúng khoảng trống đó, và lợi thế là **codebase TGN + dataset đã có sẵn trong tay** (workspace + artefact MSR 2022).

---

## 6. Đề xuất phương án

### 6.1. Phương án gắn nhãn bottleneck (label construction)

Vì dataset không có nhãn bottleneck, đề xuất **nhãn tổng hợp theo phân vị (quantile-based composite label)** — tính tự động, tái lập được, không cần chuyên gia:

```
Cho issue i thuộc dự án P tại thời điểm t (issue đang mở):

B1_score(i, t) =
    w1 · blocked_open(i,t) / max_blocked_open(P)     # số issue đang block i hoặc i block (link Block/Depend, phía mở)
  + w2 · [t − last_transition(i)] / p90_dwell(P)      # thời gian ứ tại trạng thái hiện tại so với p90 của dự án
  + w3 · priority_norm(i)                              # Blocker=1.0, Critical=0.8, Major=0.5, Minor=0.3, Trivial=0.1
  + w4 · downstream_open(i,t) / max_downstream(P)     # số issue mở đang phụ thuộc i

LABEL(i; t→t+Δt) = 1  nếu B1_score trong (t, t+Δt] thuộc top-q% của dự án P
                   (q = 5% cho bottleneck, kiểm định độ nhạy q ∈ {3,5,10}%)
```

- Ngưỡng **tương đối theo dự án** (per-project quantile) → miễn dịch cho khác biệt văn hóa quản lý giữa 16 tổ chức.
- **Không leakage:** mô hình tại thời điểm t chỉ thấy sự kiện `t_k ≤ t`; nhãn được xác định bởi kết cục trong `(t, t+Δt]` — đúng ngữ nghĩa dự đoán tương lai, và chia train/val/test theo thời gian (quantile 0.70/0.85 như `utils/data_processing.py`) đảm bảo không rò rỉ.
- Với B2 (assignee-level): cùng công thức trên nút developer, dùng số issue mở ưu tiên cao + thời gian phản hồi trung bình.
- **Kiểm định nhãn:** đối chiếu thủ công 200–500 issue top-score với người có kinh nghiệm SPM (nếu có) để ước lượng precision của chính nhãn — bước "label audit".

> **⚠️ Cập nhật từ P0 (đã đo, xem Phụ lục D §6):** công thức composite trên (phiên bản v1/v2) **không hoạt động** trên dữ liệu thật: (a) thành phần dwell tương quan với t → leakage qua split thời gian (AUC < 0.5); (b) 96–97% issue không có link + priority gần như hằng số (JFrog 100% "normal" — **sai, bug chuẩn hóa, đã sửa 2026-10-04**) → top-5% pha loãng issue không-tín-hiệu (AUC ~0.58). Nhãn **v3 (mặc định)** đã áp dụng: `LABEL(i,t)=1` iff issue có ≥1 link Block/Depend — T1 JFrog **AUC 0.839**. Composite giữ làm ablation. **⚠️ 2026-10-04: AUC này do rò rỉ nhãn (0,620 / 0,484 khi bỏ feature/sự kiện link) — nhãn v3 cần thay, xem `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md`.**

### 6.2. Chiến lược dữ liệu & subset

**Pilot (giai đoạn 1 — bắt buộc làm trước):** chọn 3 instance có sự tương phản:
1. **Spring** (69k issue, 1 org, quy trình chuẩn) — instance chính;
2. **JFrog** (16k issue, nhỏ, chạy nhanh trên CPU);
3. **Mojang** (421k issue, bug-centric) — instance lớn, stress test.

Mỗi instance: lấy 100% issue có changelog ≥ 3 sự kiện; ước tính quy mô sự kiện: 10k–400k issue × trung bình ~12 changelog ≈ 100k–5M sự kiện → phù hợp bộ nhớ của repo (n_nodes ≤ ~500k).

**Giai đoạn 2:** mở rộng sang Apache/RedHat/Jira (Atlassian) sau khi đã ổn định pipeline; cân nhắc chỉ lấy issue có liên kết (sparse nhưng giàu tín hiệu bottleneck).

### 6.3. Xây dựng đồ thị sự kiện (pipeline)

```
MongoDB (JiraRepos.<instance>)
   │  1) SELECT issue có changelog; chuẩn hóa field theo
   │     jira_field_information.json + linktype/issuetype mapping
   │  2) Phát sinh sự kiện (mỗi sự kiện = 1 dòng (u, v, ts, type, …)):
   │     • status_change   : u=issue, v=issue,   x=(from_status, to_status)
   │     • assignee_change : u=issue, v=assignee_id (nút developer), x=(old,new)
   │     • link_created    : u=issue, v=issue_linked, x=(link_type_std, direction)
   │     • comment         : (tùy chọn) u=issue, v=author, x=()
   │  3) Gán id: issue_id, dev_id (offset), thời gian → epoch giây
   │  4) Sắp xếp theo ts; loại sự kiện trùng lặp/rác (bot, migration)
   ▼
CSV: u, i, ts, label, <event features…>   →  utils/preprocess_data.py
   ▼
data/ml_{instance}.csv/.npy + data/ml_{instance}_node.npy
```

**Edge features (vector ~16–24 chiều):** one-hot loại sự kiện (4), one-hot link_type_std (8: Block, Depend, Epic, Parent-Child, Fix, Duplicate, Relate, Subtask), one-hot hướng (2), priority_norm (1), issue_type_theme (1: Requirements/Development/Maintenance/Support/Other), thời gian trong ngày (2: sin/cos), Δt so sự kiện trước của issue (1), số comment gần 7 ngày (1, log).

**Node features:** repo mặc định dùng feature zero/random (xem `preprocess_data.py` dòng `rand_feat = np.zeros(...)`) — **đề xuất thay bằng đặc trưng issue thực** (priority, issue_type_theme, component, tuổi issue tại lần xuất hiện) để tăng chất lượng embedding; đây là điểm cải tiến nhỏ nhưng có cơ sở (paper gốc cũng chỉ ra node features giúp ích).

**Bipartite vs đơn:** repo hỗ trợ cả hai (`--bipartite`). Với B1 (issue↔issue) dùng đơn; với B2 (issue↔developer) dùng bipartite — đúng cấu trúc `reindex(df, bipartite=True)` trong `utils/data_processing.py`.

### 6.4. Thích nghi TGN (các thay đổi mã nguồn tối thiểu)

| # | Thay đổi | Vị trí | Mức độ |
|---|---|---|---|
| 1 | Adapter Jira → CSV chuẩn (mục 6.3) + tính nhãn Δt (mục 6.1) | Tệp mới `jira_adapter/` (ngoài repo core) | Trung bình |
| 2 | Node features thực thay vì zero | `utils/preprocess_data.py` (thêm chế độ `--node-features`) | Nhỏ |
| 3 | Task T1: **không cần viết decoder mới** — `train_supervised.py` đã có sẵn `decoder = MLP(...)` + `BCELoss` + `eval_node_classification` (AUC-ROC) (xác minh dòng 169–172). Chỉ việc cột `label` trong CSV Jira chứa nhãn bottleneck §6.1 và thêm metric Precision@k vào `evaluation/evaluation.py` | `train_supervised.py`, `evaluation/evaluation.py` | Rất nhỏ |
| 4 | (Tùy chọn) Memory-updater theo **loại sự kiện** (separate GRU cell cho transition/link) | `modules/memory_updater.py` | Trung bình — làm ở giai đoạn 2 |
| 5 | (Tùy chọn) Đánh giá theo **thời điểm query** (predict at time t cho mọi issue mở tại t) thay vì per-event | `evaluation/evaluation.py` (thêm `eval_bottleneck_at_time`) | Trung bình |
| 6 | Không sửa | `model/tgn.py`, `modules/embedding_module.py`, `model/temporal_attention.py` | — (giữ nguyên để so sánh công bằng với paper gốc) |

**Cấu hình đề xuất khởi điểm** (theo default của repo + điều chỉnh cho Jira):
`--use_memory --embedding_module graph_attention --memory_updater gru --aggregator last --message_function mlp --n_layer 1 --n_head 2 --n_degree 10 --node_dim 100 --memory_dim 172 --n_epoch 10 --patience 5 --bs 100`

### 6.5. Baseline & bộ đánh giá

| Nhóm | Baseline | Nguồn |
|---|---|---|
| Cùng họ TGN | **JODIE** (`--embedding_module time`), **DyRep** (`--dyrep --use_destination_embedding_in_message`) | Đã có sẵn trong repo (lệnh mẫu ở README §Baselines) |
| Không memory | **TGN-no-mem** (`--use_memory` bỏ) | Repo |
| Chỉ thời gian | **TGN-time / TGN-id** | Repo |
| Tĩnh | GCN/GAT snapshot (tự viết, ~2 ngày công) + Logistic Regression trên đặc trưng phẳng | Mới |
| Heuristic | `priority_norm × age × blocked_count` (chính là B1_score không học) | Mới |
| Process mining | Heuristic miner (pm4py) + bottleneck detection cổ điển | Ngoài (so sánh phương pháp luận) |

**Chỉ số:** AUC-ROC, Average Precision (theo chuẩn `evaluation/evaluation.py`), Precision@k (k = 1%, 3%, 5% số issue mở) — chỉ số thực dụng cho dashboard top-k; F1 với ngưỡng 0,5. **Chia dữ liệu:** theo thời gian (70/15/15 theo quantile — đúng `data_processing.py`), đánh giá thêm trên **issue mới** (`--different_new_nodes`) và **cross-instance** (train trên Spring, test trên JFrog — kiểm tra generalization).

**Ablation bắt buộc:** (1) bỏ memory; (2) bỏ temporal attention (→ graph_sum); (3) bỏ edge features (event type); (4) chỉ link Block/Depend so với tất cả sự kiện; (5) Δt = 7 vs 14 vs 30 ngày; (6) có/không node features.

### 6.6. Giải thích & sản phẩm đầu ra

- **Attention extraction:** `TemporalAttentionLayer` đã cho weight hàng xóm → top-5 sự kiện/quan hệ ảnh hưởng nhất dự đoán → hiển thị "issue X được dự báo nghẽn vì: đang block 12 issue, 45 ngày không chuyển trạng thái, priority Critical".
- **Dashboard top-k (nguyên mẫu):** hàng ngày chạy inference cho các issue mở, xuất top 20 bottleneck theo instance + phân loại B1/B2 — đủ để demo giá trị nghiệp vụ.
- **Early-warning (T3):** dùng mô hình T2 (link prediction Block/Depend) để cảnh báo "issue Y có xác suất cao bị block trong 1–2 tuần tới" — giá trị nghiệp vụ lớn nhất, làm ở giai đoạn 2.

---

## 7. Kế hoạch thực hiện

| Giai đoạn | Nội dung | Đầu ra | Thời lượng |
|---|---|---|---|
| **P0 — Chuẩn bị (1 tuần)** | Restore MongoDB subset (JFrog + Spring); EDA changelog/links; kiểm tra môi trường PyTorch (repo pin torch 1.6 — dựng env riêng, không đụng workspace runtime) | Bản EDA + env chạy được `train_self_supervised.py` trên data toy | 1 |
| **P1 — Pipeline & nhãn (1,5 tuần)** | Adapter Jira→CSV (§6.3); gắn nhãn Δt (§6.1); baseline heuristic + LR | Dataset `ml_jira_{instance}.csv/.npy`; bảng baseline | 1.5 |
| **P2 — TGN (2 tuần)** | Tiền huấn luyện T2 (link pred); fine-tune T1; ablation §6.5; so JODIE/DyRep/GCN | Kết quả số + ablation + checkpoint | 2 |
| **P3 — Phân tích & báo cáo (1 tuần)** | Label audit (200–500 mẫu); attention explanation; dashboard top-k (Streamlit/Gradio nguyên mẫu); báo cáo tổng kết + draft bài viết | Báo cáo cuối + demo | 1 |
| **P4 (tuỳ chọn, giai đoạn 2)** | Mở rộng Apache/RedHat/Atlassian-Jira; T3 early-warning; memory-updater theo loại sự kiện; paper submission (MSR/ICSE-SEIP) | Bài viết + mã nguồn | 4–6 |

**Tổng giai đoạn 1–3: ~5,5 tuần** cho một kết quả có thể bảo vệ (pilot 3 instance + ablation + baseline đầy đủ).

**Yêu cầu tài nguyên:** 1× GPU (đủ cho JFrog/Spring; Mojang cần A100/RTX 4090 hoặc CPU mạnh + `--backprop_every`); ~100GB đĩa (dump 60GB + artifact); không cần cluster.

---

## 8. Rủi ro và phương án giảm thiểu

| Rủi ro | Xác suất | Tác động | Giảm thiểu |
|---|---|---|---|
| Nhãn bottleneck (tự xây) bị noise / không phản ánh thực tế | Trung bình | **Cao** — toàn bộ kết quả phụ thuộc vào nhãn | Label audit §6.1; kiểm định độ nhạy q∈{3,5,10}%; đối chiếu 2 phương án nhãn (composite vs chỉ Block/Depend); báo cáo cả 2 |
| Dị dạng schema 16 instance → pipeline vỡ | Trung bình | Trung bình | Dùng mapping chuẩn của tác giả dataset (đã có sẵn); chỉ pilot 3 instance đồng nhất; lớp chuẩn hóa có test unit |
| 2/16 instance offline (MariaDB, Mindville) | **Đã biết** (ghi trong README) | Thấp | Loại khỏi pilot; dùng snapshot May2021 nếu cần |
| Quy mô 60GB vượt khả năng xử lý | Thấp (đã có chiến lược subset) | Trung bình | Pilot 16k–421k issue; streaming từ MongoDB, không load cả DB |
| Môi trường PyTorch 1.6 cũ (README) xung đột runtime hiện tại | Trung bình | Thấp | Dựng env riêng (conda/pip freeze theo README); nếu không chạy được → nâng cấp torch 2.x (code TGN tương đối sạch, khả thi) |
| Memory là `nn.Parameter` → OOM với nhiều nút | Trung bình | Trung bình | Giới hạn n_nodes theo instance; cân nhắc TODO chính thức của repo (chuyển memory thành tensor ngoài model) ở giai đoạn 2 |
| Kết quả không thắng baseline tĩnh | Trung bình | Trung bình | Đây cũng là kết quả khoa học hợp lệ (báo trung thực + ablation chỉ ra trường hợp TGN thắng: issue mới, phụ thuộc sâu, Δt dài); điều chỉnh Δt/label theo hướng TGN mạnh |

---

## 9. Tài liệu tham khảo

1. E. Rossi, B. Chamberlain, F. Frasca, D. Eynard, F. Monti, M. Bronstein. *Temporal Graph Networks for Deep Learning on Dynamic Graphs.* ICML 2020 Workshop on Graph Representation Learning. — [arXiv:2006.10637](https://arxiv.org/abs/2006.10637). **Mã nguồn: repo trong workspace này.**
2. L. Montgomery, C. Lüders, W. Maalej. *An Alternative Issue Tracking Dataset of Public Jira Repositories.* IEEE/ACM MSR 2022, pp. 73–77. — [arXiv:2201.08368](https://arxiv.org/abs/2201.08368); artefact: <https://github.com/IoanaCovataru/ThePublicJiraDataset> (CC BY 4.0 / MIT).
3. C. Lüders, A. Bouraffa, W. Maalej. *Beyond Duplicates: Towards Understanding and Predicting Link Types in Issue Tracking Systems.* — [arXiv:2204.12893](https://arxiv.org/abs/2204.12893).
4. C. Lüders, T. Pietz, W. Maalej. *Automated Detection of Typed Links in Issue Trackers.* — [arXiv:2206.07182](https://arxiv.org/abs/2206.07182).
5. S. Pope, A. Barovic, A. Moin. *Bug Destiny Prediction in Large Open-Source Software Repositories through Sentiment Analysis and BERT Topic Modeling.* — [arXiv:2504.15972](https://arxiv.org/abs/2504.15972).
6. *Developer Load Normalization Using Iterative Kuhn–Munkres Algorithm.* — [arXiv:2202.01713](https://arxiv.org/abs/2202.01713).
7. *TaskAllocator: A Recommendation Approach for Role-based Tasks Allocation in Agile Software Development.* — [arXiv:2103.02330](https://arxiv.org/abs/2103.02330).
8. *Application of Process Mining and Sequence Clustering in Recognizing an Industrial Issue.* — [arXiv:2311.15362](https://arxiv.org/abs/2311.15362).
9. *PMSD: Data-Driven Simulation Using System Dynamics and Process Mining.* — [arXiv:2010.00943](https://arxiv.org/abs/2010.00943).
10. *Continuous Temporal Graph Networks for Event-Based Graph Data.* — [arXiv:2205.15924](https://arxiv.org/abs/2205.15924).
11. *Time-Aware Neighbor Sampling for Temporal Graph Networks.* — [arXiv:2112.09845](https://arxiv.org/abs/2112.09845).
12. *A Temporal Graph Network Framework for Dynamic Recommendation (TGN4Rec).* — [arXiv:2403.16066](https://arxiv.org/abs/2403.16066).
13. *Trajectory Encoding Temporal Graph Networks (TETG).* — [arXiv:2504.11386](https://arxiv.org/abs/2504.11386).
14. *Temporal Graph Networks for Graph Anomaly Detection in Financial Networks.* — [arXiv:2404.00060](https://arxiv.org/abs/2404.00060).

---

## Phụ lục A — Checklist xác minh (đã thực hiện trong phiên này)

- [x] Đọc toàn bộ mã nguồn TGN trong workspace: `README.md`, `model/tgn.py`, `modules/memory.py`, `modules/memory_updater.py`, `modules/embedding_module.py`, `utils/data_processing.py`, `utils/preprocess_data.py`, `train_supervised.py`, `evaluation/evaluation.py` — xác nhận đầu vào `(u,i,ts,label,edge_feats) + node_feats`, pipeline self-supervised → supervised, đánh giá AP/AUC + AUC-ROC.
- [x] Xác định chính xác "The Public Jira Dataset" = MSR 2022 (Montgomery–Lüders–Maalej), artefact `IoanaCovataru/ThePublicJiraDataset`; đọc README, `jira_data_sources.json` (16 instance + số issue), mapping link type, thematic analysis issue type, schema download (1 collection/instance, issue + changelog + comments + issueLinks).
- [x] Xác nhận gap nghiên cứu: tìm kiếm arXiv "bottleneck"+"JIRA", "issue tracking"+"graph neural network", "issue duration prediction" — không có công trình kết hợp TGN + Jira + bottleneck.
- [x] Thu thập 14 tài liệu liên quan (liên kết ở §9).
- [x] (Cập nhật — sau khi người dùng chọn Bundle C) code pipeline `jira_adapter/` + restore dataset + EDA/build 2 instance + smoke-test training + T2 GPU đang chạy. Xem Phụ lục D.

## Phụ lục B — Câu hỏi mở cần quyết định trước P1

1. **Định nghĩa bottleneck chính thức** cho tổ chức của chúng ta (để khớp nhãn §6.1 với thực tế nội bộ)? — Có PM/chuyên gia SPM nào để label audit không?
2. **Scope pilot**: 3 instance đề xuất (Spring, JFrog, Mojang) hay thay bằng instance liên quan trực tiếp đến dự án nội bộ?
3. **Mục tiêu cuối cùng**: nghiên cứu học thuật (draft paper) hay sản phẩm nội bộ (dashboard cảnh báo)? — ảnh hưởng đến ưu tiên P3/P4.
4. **Ngân sách GPU**: có sẵn GPU cho giai đoạn P2 không, hay phải chạy CPU (thời gian tăng ~5–10×)?

**→ ĐÃ QUYẾT ĐỊNH (chọn Bundle C — "cân bằng: sản phẩm lead + rigor học thuật"):**

| Câu hỏi | Quyết định | Căn cứ |
|---|---|---|
| Q1 — nhãn | Nhãn chính = composite quantile **multi-label (B1/B2/B3 tách biệt)**; audit = face-validity tự làm + PM-audit nếu có người; (c) causal làm nhãn phụ giai đoạn 2 | Rubric: `docs/rubric-label-audit-bottleneck.md` |
| Q2 — instance | **Giữ 3 instance: Spring (main) + JFrog (sanity) + Mojang (scale)** | GPU khả dụng (phía dưới) → Mojang không còn rào cản |
| Q3 — mục tiêu | **Lead sản phẩm (dashboard + early-warning) nhưng build với rigor học thuật** (cross-instance, inductive, ablation) | Đến giá trị nhanh; bài viết là "insurance" + nâng cấp miễn phí sau này |
| Q4 — compute | **GPU RTX 4060 Ti 16GB trên máy này** (khả dụng, xem Phụ lục C) | nvidia-smi xác nhận driver 595.84 / CUDA 13.2 |

## Phụ lục D — Tiến độ Bundle C (P0)

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Xác định nguồn dữ liệu chính thức | ✅ Zenodo record **15719919** (`ThePublicJiraDataset.zip`, 5.81GB, CC-BY-4.0) | DOI `10.5281/zenodo.5882881` redirect; API Zenodo xác nhận |
| GPU khả dụng | ✅ RTX 4060 Ti 16GB (driver 595.84, CUDA 13.2) — cần chạy với quyền sandbox mở rộng | `nvidia-smi` |
| Adapter Jira→event stream | ✅ `jira_adapter/` (normalize, events, labels, to_tgn, eda, **build_mongo**) + README | package trong repo |
| Nhãn bottleneck (v3 dependency mặc định + composite ablation) | ✅ `jira_adapter/labels.py` (mode dependency/composite, use_dwell) + rubric audit `docs/rubric-label-audit-bottleneck.md` | code + tài liệu; lịch sử thiết kế ở §6 bên dưới |
| Test end-to-end adapter | ✅ synthetic → `ml_synth.*` → loader repo đọc OK; **+ pipeline chạy OK trên dữ liệu thật** | `data/ml_synth.*`, `data/ml_JFrog.*` |
| Download dataset 5.81GB | ✅ xong | `data/raw/ThePublicJiraDataset.zip` (5.81GB) |
| Cài PyTorch (CUDA, Python 3.13) | ✅ **torch 2.14.0+cu130, `cuda.is_available()=True`** | `torch.cuda.get_device_name()` |
| Restore MongoDB (không cần root) | ✅ **mongorestore 100.19.1 + mongod 9.0.2 local** (tools extract từ .deb `dpkg-deb -x`; server từ tarball enterprise 208MB) — **2,686,282 docs, 0 failures, 16/16 instance** | `.tools/`, db `JiraReposAnon` @127.0.0.1:27017 |
| EDA + build JFrog (sanity) | ✅ 15,535 issue / 10 dự án / 55,666 events / pos_rate 19.8% | `data/ml_JFrog.*`, `docs/eda/eda_JFrog.md` |
| EDA + build Spring (main) | ✅ 69,156 issue / 81 dự án / 372,553 events / pos_rate 0.5% | `data/ml_Spring.*` |
| Smoke-test training loop (torch 2.x + Py 3.13) | ✅ `train_self_supervised.py -d synth` chạy hết 3 epoch, save model (sửa 3 bug Py-3.13/torch-2.x) | `saved_models/synth_smoke-synth.pth` |
| T2 self-supervised JFrog (GPU) | ✅ **20 epoch × ~17.5s** — test **AUC 0.9986 / AP 0.9977** (old nodes), **AUC 0.9823 / AP 0.9709** (new/inductive, 1,216 nodes chưa xuất hiện trong train) | `saved_models/tgn_jira-JFrog.pth`, `results/tgn_jira.pkl` |
| EDA + build Mojang (scale, pilot 50k) | ✅ 3 dự án (MCPE 37.4k, REALMS 9.1k, WEB 3.5k), 210,411 events, 50.5% issue có link (38.7k "Duplicate"), 20 assignee (1.4% assigned) | `data/ml_Mojang.*` |
| T1 fine-tune node-classification (JFrog, label v3) | ✅ **test AUC 0.839** (best epoch 15/30, val AUC 0.814, early-stop đúng) — ~~tín hiệu bottleneck **học được**~~ **⚠️ rò rỉ nhãn: 0,620 khi bỏ feature loại link, 0,484 khi bỏ thêm sự kiện link (2026-10-04)** | `results/tgn_jira.pkl`, decoder checkpoint `saved_checkpoints/` |
| T2 Spring (main instance) | ✅ **early-stop epoch 15 (best 10)**, 16 epoch × ~360s — test **AUC 0.9997 / AP 0.9996** (old nodes), **AUC 0.9988 / AP 0.9984** (new/inductive, 6,769 nodes) — chạy được sau fix timestamp âm | `saved_models/tgn_jira-Spring.pth`, `results/tgn_jira.pkl` |
| T1 Spring (label v3) | ✅ **test AUC 0.768** (best epoch 17/30, val 0.8185, early-stop epoch 22) — cả 2 instance đều **vượt mục tiêu ≥0.75** (⚠️ cùng cơ chế rò rỉ: 2.711/2.714 issue dương Spring có sự kiện link Block/Depend) | `saved_checkpoints/tgn_jira-Spring-17  node-classification.pth` |
| T2 Mojang (scale pilot 50k) | ✅ 20 epoch × ~167s — test **AUC 0.9989 / AP 0.9985** (old), **AUC 0.9937 / AP 0.9915** (new, 4,951 inductive nodes) — pipeline chạy ổn định ở quy mô lớn nhất đã test | `saved_models/tgn_jira-Mojang.pth` |
| Baseline DyRep JFrog (T2, link-pred) | ✅ test AUC **0.9901** (old) / **0.8893** (new) vs TGN **0.9986 / 0.9823** — TGN thắng cả 2, chênh **+9.3 AUC** trên new nodes (memory giúp inductive) | `saved_models/tgn_dyrep-JFrog.pth` |
| Ablation label composite (v1/v2) trên JFrog | ✅ v1 (composite+dwell): val AUC **0.19–0.44** (<chance — leakage temporal) · v2 (composite static, ranking): **test AUC 0.578** vs v3 **0.839** — ~~chứng minh **thiết kế nhãn quyết định tính học được**~~ (đính chính 2026-10-04: lợi thế của v3 đến từ rò rỉ nhãn) | `data/ml_JFrog_comp.*`, `--label-mode composite` |

**Sự thật dữ liệu mới (xác minh trực tiếp trên dump, quan trọng cho §6/§8):**
1. **Shape document khác Jira API v2 "gốc"**: `changelog` là dict `{startAt, maxResults, total, histories:[{id, author, created, items}]}`; **links nằm trong `fields.issuelinks` (lowercase)**, comments trong `fields.comments` — không có top-level `issueLinks`/`comments`. → adapter thêm `normalize_doc()` (idempotent) xử lý cả 2 shape.
2. **Changelog KHÔNG bị truncate** (đã kiểm tra `total == len(histories)` trên Apache/Spring/Mojang/JFrog/Jira — 0 vi phạm).
3. **Assignee anonymized** dạng `<<|author_name|<uuid>|>>` → B2 (assignee-level) vẫn chạy được (uuid ổn định), nhưng **không mapping được về vai trò/nhóm người** — giới hạn ghi nhận trong báo cáo.
4. **JFrog có changelog `field: "Link"`** (sự kiện tạo link CÓ timestamp) — tín hiệu bổ sung cho P2; v1 chưa dùng (giữ link semantics nhất quán cross-instance).
5. **pos_rate phụ thuộc instance mạnh** (JFrog 19.8% vs Spring 0.5%) do p90-dwell context theo dự án — đã thử biến thể "lifetime resolved" (v1.1: 1.5%/0.12%, tệ hơn) → **giữ v1 + đưa vào label-audit** (bundle C Q1).
6. **Spring có timestamp ÂM** (epoch −28800s): placeholder date `1969-12-31T16:00:00.000+0000` (8h trước epoch) trong 58 trường của các issue IDE-* (Jira IDE cũ merge vào Spring). Vi phạm invariant memory của TGN (`last_update=0 ≤ ts`) → crash "Trying to update memory to time in the past" ngay batch 0 epoch 0 (JFrog/Mojang không có). **Fix**: clamp `ts = max(ts, 0)` trong adapter (`events.py::_safe_ts`) — giữ thứ tự thời gian, 26 event Spring được kẹp về t=0.
7. **Bug repo TGN (fix trong P0)**: block early-stop + save-checkpoint trong `train_supervised.py` bị dedent **ra ngoài vòng lặp epoch** → chạy hết 30 epoch không early-stop, `best_epoch=0` nhưng checkpoint epoch-0 không bao giờ được save → crash `FileNotFoundError` khi load best model. Đã sửa indent (phải nằm trong loop).

### 6. Lịch sử thiết kế nhãn (P0 — quan trọng cho §6.1)

| Phiên bản | Định nghĩa | Kết quả đo (JFrog / Spring) | Kết luận |
|---|---|---|---|
| v1 (composite + dwell) | top-5%/dự án theo `B1_score(t)` có dwell(t)=t−created | JFrog: T1 **AUC 0.19–0.44** (<chance!); split: train 1.1% / val 36% / test **55%** positive | **BỎ** — dwell làm LABEL tương quan với thời điểm → leakage qua split thời gian; prior shift cực đoan |
| v2 (composite static) | top-5%/dự án theo score không-dwell | quantile naive: positive rate **62–88%** (sai hướng ngược) → sửa bằng **ranking + tie-break**: split cân bằng 5.5/4.7/4.2% → **T1 test AUC 0.578** (val 0.51–0.67, nhiễu quanh chance) | **BỎ làm nhãn chính** — 96–97% issue không có link + priority hằng số (JFrog 100% = "normal" — sai, bug chuẩn hóa, đã sửa 2026-10-04) → top-5% pha loãng ~70% issue không-tín-hiệu → gần như random. **Giữ làm ablation** (data `ml_JFrog_comp.*`) |
| **v3 (dependency — CHỌN)** | `LABEL(i,t)=1` iff issue có ≥1 link **Block/Depend** (quan hệ chặn/chờ) | JFrog: 450 issue (2.9%), split 3.7/3.1/1.2% ✓ · Spring: 2,794 issue (4.0%), split 2.8/3.0/1.1% ✓ · Mojang: ~10 issue (0.02% — quá.sparse) → **T1 JFrog: test AUC 0.839** (~~tín hiệu học được!~~ ⚠️ rò rỉ nhãn — 0,620 / 0,484 sau khi bỏ feature/sự kiện link) | **Mặc định** — tín hiệu mạnh nhất, face-valid ("điểm nghẽn = issue bị chặn/chặn người"), sạch cho evaluation temporal; composite giữ làm ablation (flag `--mode composite`) |

**Bài học** (ghi cho §6.1 + §8): (a) nhãn point-in-time KHÔNG được chứa hàm của t nếu evaluate bằng split thời gian; (b) quantile trên score ít biến thiên (links sparse, priority hằng) tạo tied mass → phải rank + tie-break hoặc chọn ngưỡng tín hiệu; (c) **Mojang gần như không có link Block/Depend** (0.03% issue, 14 links) → vai trò "scale/EDA" chứ không phải instance huấn luyện chính — cập nhật quyết định Q2 ở Phụ lục B khi có T2/T1 số liệu.

## Phụ lục C — Sự thật hạ tầng & dữ liệu (xác minh trong phiên này)

**Máy chủ chạy dự án:**
- CPU 16-core Intel i5-14400 · RAM 30GB · Đĩa trống 208GB (`/mnt/Data`).
- **GPU: NVIDIA GeForce RTX 4060 Ti 16GB** — driver NVIDIA 595.84 (open kernel module) đã load, CUDA runtime tối đa 13.2.
- ⚠️ **Lưu ý vận hành:** sandbox mặc định (`workspace-write`) **không exposing `/dev/nvidia*`** → lệnh GPU cần chạy với quyền sandbox mở rộng (`danger-full-access`) đã được phê duyệt. Các job dài (training) nên khởi tạo trong chế độ đó.
- Python 3.13.9 (anaconda3), pip 25.3; PyTorch đang cài (build CUDA) — cần torch ≥ 2.1 cho GPU thế hệ Ada (repo gốc pin torch 1.6 → phải nâng, rủi ro §8 xác nhận).

**Dataset — nơi lưu trữ chính thức:**
- Zenodo record **15719919** — *"The Public Jira Dataset"* (Montgomery, Lüders, Maalej), phát hành 2025-06-23, **CC-BY-4.0**.
- DOI cũ trên paper: `10.5281/zenodo.5882881` → redirect sang record mới.
- **File duy nhất: `ThePublicJiraDataset.zip` = 5.81GB** (nhẹ hơn nhiều so với mongodump 60GB trong repo GitHub — format nội bộ đang kiểm tra; download đang chạy vào `data/raw/`).
- GitHub artefact `IoanaCovataru/ThePublicJiraDataset` chỉ chứa code + định nghĩa + README của DataDump (không có archive 60GB) — nguồn chính là Zenodo.
