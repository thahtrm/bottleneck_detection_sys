# Báo cáo: Xử lý dữ liệu và phương án huấn luyện mô hình — TGN phát hiện điểm nghẽn trên dữ liệu Jira

**Ngày:** 2026-10-05
**Phạm vi:** (a) Toàn bộ pipeline xử lý dữ liệu hiện tại, các lỗi đã phát hiện và sửa, kết quả đo rò rỉ nhãn; (b) pipeline gắn nhãn bottleneck mới bằng LLM và hiện trạng chạy thử; (c) phương án huấn luyện TGN với nhãn mới: bài toán, dữ liệu, cấu hình, baseline, chỉ số, lộ trình và cổng quyết định.
**Tài liệu liên quan:**
- `docs/bao-cao-tap-du-lieu-va-tien-xu-ly.md` — mô tả chi tiết dataset và pipeline v1–v3 (đã có ghi chú đính chính).
- `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` — định nghĩa bottleneck, codebook, thiết kế gắn nhãn LLM.
- `docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md` — báo cáo đề xuất gốc.
- `docs/rubric-label-audit-bottleneck.md` — rubric chấm tay.

---

## Mục lục

1. [Tóm tắt](#1-tóm-tắt)
2. [Dữ liệu nguồn](#2-dữ-liệu-nguồn)
3. [Pipeline xử lý dữ liệu](#3-pipeline-xử-lý-dữ-liệu)
4. [Nhãn bottleneck](#4-nhãn-bottleneck)
5. [Phương án huấn luyện](#5-phương-án-huấn-luyện)
6. [Lộ trình và cổng quyết định](#6-lộ-trình-và-cổng-quyết-định)
7. [Rủi ro](#7-rủi-ro)
8. [Tái lập](#8-tái-lập)

---

## 1. Tóm tắt

| Hạng mục | Trạng thái |
|---|---|
| Pipeline MongoDB → dòng sự kiện → định dạng TGN | ✅ Chạy end-to-end trên JFrog, Spring, Mojang |
| Nhãn v3 ("có link Block/Depend") | ❌ **Không dùng được** — rò rỉ qua feature loại link. JFrog T1 AUC 0,835 → 0,620 khi bỏ feature loại link → 0,484 khi bỏ thêm sự kiện link |
| Lỗi dữ liệu mới phát hiện | ✅ Đã sửa: `has_block_link` luôn 0; priority JFrog bị chuẩn hóa thành hằng số; thêm cờ `--leak-safe` |
| Nhãn mới (episode, LLM + rule) | 🟡 Pipeline xong (`dossier.py`, `sampling.py`, `llm_label.py`); 20/300 issue pilot đã gắn, kết quả hợp lý; chờ chạy hết 300 và chấm gold set |
| Huấn luyện với nhãn mới | ⏳ Chưa bắt đầu — phụ thuộc cổng kiểm định nhãn (§6) |

**Thông điệp chính:**
1. Kết quả T1 trước đây không chứng minh được TGN học tín hiệu bottleneck. Trước khi huấn luyện lại phải có nhãn không phải hàm của feature đầu vào.
2. Nhãn mới gắn theo **episode** (khoảng thời gian issue bị nghẽn), do LLM trích bằng chứng và rule code xác nhận, kiểm định bằng người chấm.
3. Huấn luyện chỉ bắt đầu khi nhãn qua cổng kiểm định (κ LLM–gold ≥ 0,6). Phương án huấn luyện dùng dữ liệu `--leak-safe`, truy vấn tại các mốc thời gian thay vì sự kiện "tick", có trọng số lớp, đánh giá bằng AUPRC, Precision@k và lead time, chạy nhiều seed.

---

## 2. Dữ liệu nguồn

**The Public Jira Dataset** (Montgomery, Lüders, Maalej — MSR 2022; Zenodo 15719919; CC-BY-4.0). Đã restore vào MongoDB local `127.0.0.1:27017`, DB `JiraReposAnon` (2.686.282 document, 16 instance).

| Chỉ số | **JFrog** | **Spring** | **Mojang** (pilot 50k) |
|---|---|---|---|
| Vai trò | Pilot nhãn LLM, sanity | Instance huấn luyện chính | Scale/EDA (bug tracker công khai, không hợp định nghĩa bottleneck) |
| Issue (đang mở) | 15.535 (5.191) | 69.156 (7.594) | 50.000 (3.238) |
| Khoảng thời gian | 2006-10 → 2022-01 | 2003-11 → 2021-12 | 2014-01 → 2022-01 |
| Sự kiện | 55.666 | 372.553 | 210.411 |
| % issue có Block/Depend | 3,01% | 4,04% | 0,03% |
| Assignee (% issue được gán) | 184 (60,9%) | 260 (89,8%) | 20 (1,4%) |

**Đặc điểm quan trọng cho bài toán (JFrog, đo 2026-10-04):**
- Quy trình gần như chỉ có Open → Done/Closed; hiện chỉ ~90 issue ở trạng thái "đang làm" (In Progress, Pending QA, Reopened…). Tín hiệu ứ đọng chủ yếu nằm ở lịch sử, không ở trạng thái hiện tại.
- **91 đợt đóng hàng loạt** (≥20 issue cùng người, cùng phút). Trong mẫu pilot 300 issue có 148 issue thuộc các đợt này → thời gian ứ đọng trước khi đóng không phản ánh dòng chảy thật.
- Priority thực tế: Normal 72% · High 16% · Critical 7% · Blocker 3% (trước đây bị đọc sai thành 100% Normal, xem §3.6).
- Changelog JFrog có mục `field: "Link"` **có timestamp** — dùng được để biết thời điểm tạo link (Jira API v2 không trả timestamp trong `issuelinks`).

---

## 3. Pipeline xử lý dữ liệu

### 3.1. Kiến trúc

```
MongoDB JiraReposAnon.<instance>
 │
 ├─► Nhánh mô hình (jira_adapter/build_mongo.py)
 │     normalize.py   chuẩn hóa shape document + giá trị (link type, priority, issue theme)
 │     events.py      document → dòng sự kiện (status, assignee, priority, link, comment)
 │     labels.py      nhãn v3 / composite (cũ)  ──► sẽ thay bằng nhãn episode từ nhánh LLM
 │     to_tgn.py      → data/ml_{name}.csv / .npy / _node.npy   (tùy chọn --leak-safe)
 │
 └─► Nhánh gắn nhãn (mới)
       dossier.py     hồ sơ issue hồi cứu + tín hiệu F/I tính sẵn
       sampling.py    chọn mẫu pilot 3 tầng + bảng chấm gold
       llm_label.py   LLM (LM Studio) → JSON → kiểm bằng chứng → gộp 3 mẫu → rule → nhãn + episode
```

### 3.2. Chuẩn hóa (`normalize.py`)

- **Shape:** `changelog` dạng `{histories:[…]}` → list; `fields.issuelinks`, `fields.comments` → top-level; `status`/`priority` là dict → đọc `.name`; assignee ẩn danh `<<|author_name|uuid|>>` giữ làm id ổn định.
- **Link type:** ~75 tên thô → hạng mục chuẩn (Block, Depend, Epic, Parent-Child, Subtask, Fix, Duplicate, Relate, …) theo bảng của tác giả dataset. Lưu ý: `labels.py` (nhãn v3) dùng tập tên thô riêng, không gồm các link Gantt, nên số issue v3 (450) khác số issue có link Depend sau chuẩn hóa (460) ở JFrog.
- **Priority:** tên → [0, 1]; nay xử lý tiền tố số kiểu JFrog (`"1 - Blocker"`).
- **Issue type → theme:** Requirements / Development / Maintenance / User Support / Other.
- **Timestamp:** clamp giá trị âm (ngày placeholder 1969 của Spring) về 0.

### 3.3. Dòng sự kiện (`events.py`)

| Loại | u → v | JFrog | Spring |
|---|---|---|---|
| `status` | issue → issue (self-loop) | 31.703 | 128.673 |
| `comment` | issue → issue (self-loop, v1) | 13.152 | 186.077 |
| `assignee` | issue → issue (self-loop, v1) | 6.771 | 41.288 |
| `link` | issue → issue liên kết | 2.125 | 11.053 |
| `priority` | issue → issue (self-loop) | 1.915 | 5.462 |

Mỗi link xuất hiện ở document của cả hai issue → hai sự kiện (một mỗi chiều). Timestamp của sự kiện link hiện được **xấp xỉ** bằng `max(created)` của hai issue; với JFrog có thể thay bằng timestamp thật từ changelog `Link`.

### 3.4. Feature

**Edge feature (24 chiều):**

| Cột | Nội dung | Rò rỉ nhãn v3? | `--leak-safe` |
|---|---|---|---|
| 0–4 | One-hot loại sự kiện | Gián tiếp ("có sự kiện link") | Giữ |
| 5–13 | One-hot loại link (Block, Depend, …) | **Có — trực tiếp** | Bỏ |
| 14 | Chiều link | Có | Bỏ |
| 15 | priority_norm | Không | Giữ |
| 16–20 | One-hot theme | Không | Giữ |
| 21–22 | Giờ trong ngày (sin/cos) | Không | Giữ |
| 23 | Đệm (0) | — | — |

**Node feature (8 chiều ngữ nghĩa, đệm 0 lên 64):** `[0]` priority_norm · `[1–5]` theme · `[6]` has_block_link · `[7]` log1p(n_links) chuẩn hóa. Cột 6–7 tính từ **trạng thái cuối document** (nhìn tương lai) → bị bỏ khi `--leak-safe`. Chiều 64 là bắt buộc vì repo TGN cộng trực tiếp memory với node feature (`memory_dim == node_dim`).

### 3.5. Xuất định dạng TGN (`to_tgn.py`)

- `ml_{name}.csv`: `u, i, ts, label, idx` (id 1-based, sort theo thời gian).
- `ml_{name}.npy`: edge feature `(n_events + 1, 24)`, dòng 0 = 0.
- `ml_{name}_node.npy`: node feature `(n_nodes + 1, 64)`, dòng 0 = 0.
- Loader `utils/data_processing.py` chia train/val/test **theo thời gian** tại quantile 70% / 85% của timestamp sự kiện.

### 3.6. Lỗi đã phát hiện và sửa

| # | Lỗi | Hậu quả | Sửa | Ngày |
|---|---|---|---|---|
| 1 | Timestamp âm (Spring, placeholder 1969) | TGN crash "update memory to time in the past" | Clamp về 0 | 2026-10-01 |
| 2 | `status`/`priority` là dict | Normalize sai hoặc crash | Đọc `.name` | 2026-10-01 |
| 3 | Bug Python 3.13 trong repo TGN (checkpoint early-stop, batch size 1, `random.sample` trên set) | Crash khi train | Sửa trong `train_*.py`, `utils/` | 2026-10-01 |
| 4 | **Nhãn v3 rò rỉ qua edge one-hot loại link** | AUC T1 bị thổi phồng (§4.1) | Cờ `--leak-safe`; thay nhãn | 2026-10-04 |
| 5 | **`has_block_link` luôn 0** (so tên thô với tập chỉ gồm Block; JFrog/Spring chỉ có Depend) | Feature vô dụng | Dùng `normalize_link_type` ∈ {Block, Depend} | 2026-10-04 |
| 6 | **Priority JFrog luôn 0,4** (tên `"4 - Normal"` không khớp bảng) | Feature priority hằng số; kết luận "100% Normal" sai | Bỏ tiền tố số trước khi tra bảng | 2026-10-04 |

Sau sửa 5 và 6, build lại JFrog cho ra CSV nhãn **giống hệt** bản cũ (đã kiểm tra); chỉ feature thay đổi. Các file `data/ml_*` hiện có vẫn mang giá trị priority cũ cho đến khi build lại.

---

## 4. Nhãn bottleneck

### 4.1. Nhãn cũ và kết quả đo rò rỉ (P0)

| Phiên bản | Định nghĩa | T1 test AUC (JFrog) | Kết luận |
|---|---|---|---|
| v1 | Top-5%/dự án theo điểm composite, có dwell(t) | 0,19–0,44 | Bỏ — dwell tương quan với t, rò rỉ qua split thời gian |
| v2 | Composite không dwell | 0,578 | Bỏ — pha loãng (một phần do bug priority) |
| v3 | Có ≥1 link Block/Depend | 0,835 (3 lần chạy) | **Bỏ — rò rỉ** |
| v3, bỏ feature loại link (`JFrog_nl1`) | | 0,620 (0,630 / 0,631 / 0,598) | |
| v3, bỏ thêm sự kiện link (`JFrog_nl2`) | | 0,484 (0,523 / 0,459 / 0,469) | Ngang ngẫu nhiên |

Bằng chứng trực tiếp: 432/432 issue dương JFrog (2.711/2.714 ở Spring) có sự kiện link Block/Depend trong dòng sự kiện, và sự kiện này luôn đến trước sự kiện có nhãn đầu tiên. Ngoài rò rỉ, v3 còn sai về khái niệm: gộp issue gây chặn với issue bị chặn, và tính cả link tới issue đã đóng từ lâu (ví dụ HAP-601: phụ thuộc một issue đã đóng, không có hoạt động từ 2017).

### 4.2. Định nghĩa mới (tóm tắt)

Chi tiết trong `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` §2.

`Bottleneck = (F1 ∨ F2 ∨ F3 ∨ F4) ∧ (I1 ∨ I2 ∨ I3)`

- **F — tắc dòng chảy:** F1 ứ đọng ≥ p90 ở trạng thái đang làm; F2 chờ đợi rõ ràng (comment, trạng thái); F3 vòng lặp, làm lại; F4 thiếu nguồn lực.
- **I — tác động:** I1 có issue khác phụ thuộc; I2 trên đường găng release (fixVersion bị đẩy lùi); I3 bị leo thang.
- **Ngoại lệ (âm tính):** backlog chưa cam kết, epic/umbrella, hoãn có chủ đích, đóng Duplicate/Won't Fix, spike, artifact dữ liệu (đóng hàng loạt). Priority "Blocker" là mức nghiêm trọng, không phải bằng chứng nghẽn.
- **Đơn vị:** episode `(issue, start, end)`, kèm `role` (root / victim) và `type` (dependency, external, review, resource, requirement, technical, process).

### 4.3. Pipeline gắn nhãn LLM

**Bước 1 — Hồ sơ issue (`dossier.py`).** Mọi số liệu thời gian tính bằng code; hồ sơ là hồi cứu (được dùng để tạo nhãn, **không** dùng làm feature):
- Metadata, mô tả (≤1.500 ký tự).
- Dòng thời gian trạng thái, mỗi đoạn có số ngày và **percentile** so với cùng trạng thái và cùng theme trong dự án (phân phối từ các đoạn đã kết thúc, chưa done).
- Lịch sử assignee, priority, fixVersion, link (có timestamp từ changelog).
- Link hiện tại kèm trạng thái của issue bên kia.
- Comment theo thời gian (≤500 ký tự mỗi comment; giữ 10 đầu + 30 cuối).
- Tín hiệu F/I tính sẵn và cờ `bulk_close`, `epic_or_umbrella`, `placeholder_date`.

Kích thước thực đo trên JFrog: trung vị ~490 token, p90 ~940, tối đa ~3.600.

**Bước 2 — Chọn mẫu (`sampling.py`)**, seed 0, phân tầng theo (mở/đóng, theme):

| Tầng | Quần thể JFrog | Mẫu | Chấm đôi |
|---|---|---|---|
| v3 dương | 450 | 60 | 20 |
| Ứng viên heuristic (≥1 tiêu chí F, không thuộc v3) | 2.848 | 120 | 40 |
| Ngẫu nhiên (phần còn lại) | 12.237 | 120 | 40 |

Tầng ngẫu nhiên dùng để ước lượng số bottleneck mà bộ lọc heuristic bỏ sót.

**Bước 3 — LLM (`llm_label.py`).**
- Server: LM Studio local (OpenAI-compatible), cấu hình trong `.env` (không commit). Model đang dùng: `qwen/qwen3.8-27b`.
- System prompt = codebook (định nghĩa, ngoại lệ, quy tắc nhất quán, quy tắc bằng chứng). User prompt = hồ sơ.
- Đầu ra ép theo **JSON schema** (`response_format: json_schema`): `is_bottleneck`, `role`, `type`, `f_criteria`, `i_criteria`, `waiting_for`, `evidence` (trích nguyên văn), `episodes` (start/end phải là timestamp có trong hồ sơ), `exclusion`, `confidence`, `rationale`.
- `reasoning_effort=low`: không giới hạn thì model suy luận 2–8k token/lần (30–136 s, hay bị cắt); ở mức low ~15–25 s/lần.
- 3 lần lấy mẫu mỗi issue (temperature 0,7); mẫu bị cắt hoặc JSON hỏng không tính, tối đa 6 lần gọi.

**Bước 4 — Kiểm tra và gộp.**
- Kiểm tra trích dẫn có trong hồ sơ (chấp nhận tiền tố nhãn và khớp gần đúng ≥80% độ dài); kiểm tra timestamp episode có trong hồ sơ.
- Gộp: đa số cho `is_bottleneck`; `role`/`type`/`exclusion` theo đa số trong nhóm đồng thuận; episode lấy từ mẫu có tổng IoU lớn nhất với các mẫu còn lại.
- Rule: `final = 1` khi LLM đa số "yes" ∧ không có ngoại lệ ∧ F và I được xác nhận bằng số liệu code (hoặc bằng trích dẫn đã kiểm). LLM "no" hoặc có ngoại lệ → `0`. Còn lại (unsure, mâu thuẫn rule, có bằng chứng bịa) → `review` (người chấm).
- Kết quả lưu tại `data/llm_pilot/JFrog/llm_raw/` (mọi lần gọi, cho phép chạy tiếp) và `llm_labels/`, `llm_labels.csv`.

### 4.4. Hiện trạng chạy thử (20/300 issue)

| Nhóm | Số issue | Kết quả |
|---|---|---|
| Đang mở (15 issue đầu theo thứ tự manifest) | 15 | 15 × `0` — backlog (14), 1 issue có 1/3 mẫu "unsure" |
| Đã đóng, có tín hiệu F rõ | 5 xong (+1 trước đó) | 4 × `1`, 2 × `0` (`data_artifact`) |

Ca dương (cả 3 mẫu đồng ý, bằng chứng và episode khớp hồ sơ):
- **BI-459** — ứ ở *Pending QA* 177 ngày (p100), là điều kiện tiên quyết của 3 issue → root / review.
- **TCAP-258** — ứ ở *Pending QA* 64 ngày (p98), fixVersion bị đẩy 2.1.14 → 2.2.0 → root / review.
- **RTFACT-1131** — ứ ở *Reopened* 92 ngày (p97) sau khi QA phát hiện nhiều lỗi UI, có issue phụ thuộc → root / technical.
- **BI-386** — ứ ở *Pending QA* 45 ngày (p96), có issue phụ thuộc → root / review.

Quan sát:
- Chưa có trích dẫn bịa nào (phép kiểm tra đã được thử với câu bịa và bắt được).
- LLM áp dụng đúng ngoại lệ E3: RTFACT-26414 (priority Blocker, chưa ai nhận, không có tác động) → không phải bottleneck.
- **Giới hạn:** I1 được tính dựa trên trạng thái *hiện tại* của issue phụ thuộc; chưa kiểm được issue đó có mở trong khoảng episode hay không. Cần bổ sung trạng thái point-in-time của issue bên kia vào hồ sơ.
- **Sự cố vận hành:** model bị unload giữa lượt chạy (lỗi 500 rồi "No models loaded"). Script nay dừng với thông báo rõ và chạy tiếp được từ chỗ dừng.
- Thời gian: 22–81 s/issue (3 mẫu), trung bình ~45 s → 300 issue ≈ 3,75 giờ.

### 4.5. Kiểm định nhãn (cổng trước khi huấn luyện)

| Chỉ số | Ngưỡng |
|---|---|
| κ người–người (100 issue chấm đôi) | ≥ 0,6 — nếu thấp hơn, sửa codebook trước |
| κ LLM–gold (`is_bottleneck`) | ≥ 0,6 và ≥ 0,8 × κ người–người |
| Precision lớp dương | ≥ 0,75 |
| Độ chính xác `role` | ≥ 0,7 |
| Biên episode | IoU ≥ 0,5 hoặc lệch start ≤ 7 ngày |
| Recall bộ lọc heuristic (từ tầng ngẫu nhiên) | Báo cáo; nếu tầng ngẫu nhiên có nhiều dương → nới bộ lọc |

### 4.6. Mở rộng nhãn ra toàn bộ JFrog

Để huấn luyện cần nhãn cho toàn instance, không chỉ 300 issue pilot.

| Phương án | Phạm vi LLM | Chi phí ước tính (local, ~15 s/lần gọi) |
|---|---|---|
| A. Gắn ứng viên + v3, phần còn lại gán 0 | 3.298 issue × 3 mẫu | ~41 giờ |
| **B. Như A, nhưng 1 mẫu trước; chỉ lấy thêm 2 mẫu khi confidence < 0,8 hoặc kết quả mâu thuẫn rule** | 3.298 issue × ~1,5 mẫu | **~20 giờ** — đề xuất |
| C. Distill: LLM gắn ~1.000 issue, huấn luyện bộ phân loại nhỏ trên hồ sơ cho phần còn lại | 1.000 × 3 | ~12 giờ + huấn luyện |

Gán 0 cho tầng không phải ứng viên chỉ hợp lệ khi tầng ngẫu nhiên của pilot cho thấy tỉ lệ dương ở đó rất thấp; tỉ lệ đo được sẽ được báo cáo như sai số nhãn đã biết. Spring (69k issue) dùng phương án C.

---

## 5. Phương án huấn luyện

### 5.1. Bài toán

| Mã | Bài toán | Nhãn tại sự kiện/truy vấn (i, t) | Ưu tiên |
|---|---|---|---|
| **T1-D** | Phát hiện: issue i có đang nghẽn tại t? | `1` nếu t ∈ [start, end) của một episode `root` của i | Chính |
| T1-E | Cảnh báo sớm: i có bắt đầu nghẽn trong (t, t + 14 ngày]? | `1` nếu start ∈ (t, t + Δt], Δt ∈ {7, 14, 30} | Sau T1-D |
| T2 | Tiền huấn luyện tự giám sát: dự đoán sự kiện tiếp theo (link prediction) | — | Giữ như hiện tại |

Nhãn được phép dùng thông tin hồi cứu (cách issue kết thúc), vì đó là mục tiêu dự đoán; **feature tại t thì không**.

### 5.2. Dữ liệu huấn luyện (bản v4)

- **Build với `--leak-safe`** (bỏ edge cột 5–14, node `[6]`, `[7]`). Có thể thêm lại thông tin link theo cách point-in-time: sự kiện link với timestamp thật từ changelog `Link` của JFrog.
- **Nhãn:** đọc `llm_labels/*.json` (cần thêm `--label-mode llm` vào `build_mongo.py`), gán nhãn theo episode cho **mọi** sự kiện của issue nằm trong episode (không chỉ status/assignee/priority như v3).
- **Vấn đề issue đang tắc thì không có sự kiện.** Phương án ban đầu là chèn sự kiện "tick" hằng tuần, nhưng đo thực tế: JFrog có **~1,6 triệu issue-tuần đang mở** (gấp ~29 lần 55.666 sự kiện thật), Spring ~4,8 triệu. Không khả thi và còn làm sai lệch memory.
- **Phương án chọn: truy vấn tại mốc thời gian (query points).** Mỗi tuần t, lấy tập issue cần đánh giá Q(t) = issue chưa done **và** (đang ở trạng thái "đang làm" **hoặc** có hoạt động trong 90 ngày gần nhất). Tính embedding của các issue này tại t từ memory hiện có mà **không** thêm sự kiện vào đồ thị, rồi đưa qua decoder. Kích thước Q(t) cần đo; backlog không hoạt động bị loại khỏi Q(t) theo đúng ngoại lệ E1.

### 5.3. Mô hình và cấu hình

Cấu hình đã chạy ổn định trên JFrog (giữ làm điểm xuất phát để so sánh với P0):

```
--use_memory --embedding_module graph_attention --memory_updater gru
--message_function mlp --aggregator last --n_layer 2 --n_head 4 --n_degree 10
--node_dim 64 --time_dim 64 --memory_dim 64 --message_dim 64
--bs 128 --lr 0.001 --backprop_every 4 --patience 5
```

**Hai giai đoạn (theo repo):**
1. `train_self_supervised.py` (T2) trên dữ liệu v4, 20 epoch → `saved_models/{prefix}-{data}.pth`.
2. `train_supervised.py` (T1): repo hiện **đóng băng TGN** và chỉ huấn luyện decoder MLP bằng `BCELoss` **không trọng số**.

**Thay đổi đề xuất cho giai đoạn 2:**

| # | Thay đổi | Lý do |
|---|---|---|
| 1 | `BCEWithLogitsLoss(pos_weight = n_neg / n_pos)` hoặc lấy mẫu cân bằng theo batch | Tỉ lệ dương dự kiến vài %; BCE không trọng số khiến decoder nghiêng về lớp âm |
| 2 | Tùy chọn fine-tune end-to-end (mở khóa TGN với lr nhỏ hơn, ví dụ 1e-4) | Embedding từ T2 tối ưu cho dự đoán sự kiện, chưa chắc cho bottleneck |
| 3 | Vòng đánh giá theo query points (§5.2) | Đánh giá đúng issue đang tắc |
| 4 | Seed cấu hình được + chạy ≥5 seed | P0 cho thấy dao động ±0,03 AUC giữa các lần chạy |

### 5.4. Chia dữ liệu

- **Theo thời gian**, giữ quantile 70/15/15 của loader để so sánh được với P0.
- **Kiểm tra bắt buộc:** tỉ lệ dương trên từng split (bài học từ v1: lệch 1,1% / 36% / 55% làm mô hình vô nghĩa). Nếu lệch quá 3 lần, cân nhắc chia theo issue (issue-disjoint) hoặc cắt bớt đầu/cuối dòng thời gian.
- **Inductive:** báo cáo riêng hiệu năng trên issue mới (chưa xuất hiện trong train).
- **Cross-instance (giai đoạn sau):** train Spring, test JFrog.

### 5.5. Baseline

| Baseline | Mô tả | Mục đích |
|---|---|---|
| Heuristic rule | Chỉ dùng tín hiệu F/I tính tại t (không LLM, không học) | Mốc dưới — nếu TGN không vượt thì không cần TGN |
| LR / Gradient boosting | Feature phẳng point-in-time: tuổi, dwell hiện tại và percentile, số handoff, reopen, priority, WIP assignee, số issue phụ thuộc đang mở | Mô hình không đồ thị mạnh |
| TGN không memory | Bỏ `--use_memory` | Giá trị của memory |
| JODIE, DyRep | Có sẵn trong repo | Cùng họ mô hình thời gian |
| TGN + nhãn v3 `--leak-safe` | Tham chiếu P0 | Cho thấy nhãn mới học được hơn |

Lưu ý tính vòng: nhãn mới có dùng rule F/I, nên baseline heuristic có lợi thế tự nhiên. Đây là chủ đích: nó cho biết TGN có thêm giá trị ngoài các rule đã biết hay không.

### 5.6. Chỉ số

- **AUPRC** (chỉ số chính, vì lớp dương hiếm) và AUC-ROC.
- **Precision@k theo tuần:** trong top-k issue mỗi tuần, bao nhiêu là bottleneck thật (k = 10, 20).
- **Lead time** (T1-E): khoảng thời gian từ khi điểm dự đoán vượt ngưỡng đến start của episode.
- Báo cáo trung bình ± độ lệch chuẩn trên ≥5 seed.

### 5.7. Ablation

1. Bỏ memory. 2. `graph_attention` → `graph_sum`. 3. Bỏ edge feature. 4. Có/không sự kiện comment. 5. Có/không sự kiện link point-in-time (timestamp thật). 6. Nhãn `root` so với `root ∪ victim`. 7. Δt = 7 / 14 / 30 ngày (T1-E).

### 5.8. Danh sách kiểm tra rò rỉ (chạy trước mỗi thí nghiệm)

- [ ] Không feature nào tính từ trạng thái cuối document (n_links, has_block, trạng thái hiện tại…).
- [ ] Không feature nào là hàm của t mà nhãn cũng là hàm của t theo cùng cách (bài học v1).
- [ ] Sự kiện link dùng timestamp thật hoặc xấp xỉ không sớm hơn thực tế.
- [ ] Tỉ lệ dương theo split đã kiểm.
- [ ] Ablation "bỏ sự kiện/feature nghi ngờ" không làm AUC rơi về ~0,5 một cách đột ngột (dấu hiệu nhãn chỉ đọc lại feature).

### 5.9. Thay đổi mã nguồn cần làm

| File | Thay đổi | Mức |
|---|---|---|
| `jira_adapter/dossier.py` | Trạng thái point-in-time của issue bên kia link (cho I1) | Nhỏ |
| `jira_adapter/llm_label.py` | Chế độ 1 mẫu trước, thêm mẫu khi cần (phương án B §4.6) | Nhỏ |
| `jira_adapter/labels.py`, `build_mongo.py` | `--label-mode llm`: đọc episode, gán nhãn theo thời gian | Nhỏ |
| `jira_adapter/events.py` | Timestamp link thật từ changelog `Link` (JFrog) | Nhỏ |
| `train_supervised.py` | `pos_weight`, seed, tùy chọn fine-tune end-to-end | Nhỏ |
| `evaluation/evaluation.py` + script mới | Đánh giá theo query points; AUPRC, P@k, lead time | Trung bình |
| Script baseline mới | Heuristic, LR/GBDT trên feature point-in-time | Trung bình |

### 5.10. Tài nguyên và thời gian

- GPU: RTX 4060 Ti 16 GB, dùng chung cho LM Studio và TGN → **chạy tuần tự** (unload model LLM khi huấn luyện).
- TGN trên JFrog (đo ở P0): T2 ~17 s/epoch (~6 phút/20 epoch); T1 ~11 s/epoch (~6 phút/30 epoch). Một thí nghiệm 5 seed ≈ 40 phút. Spring lớn hơn ~7 lần sự kiện.
- LLM: pilot 300 issue ≈ 3,75 giờ; nhãn toàn JFrog theo phương án B ≈ 20 giờ.

---

## 6. Lộ trình và cổng quyết định

| Bước | Việc | Đầu ra | Cổng đi tiếp |
|---|---|---|---|
| P0 ✅ | Đo rò rỉ v3; sửa bug | AUC 0,835 → 0,620 → 0,484 | — |
| P1 ✅ | Hồ sơ, chọn mẫu, LLM labeler | 300 hồ sơ, bảng chấm, 20 nhãn thử | — |
| P2 | Người chấm gold set (A: 300, B: 100) | `gold_rater_A.csv`, `gold_rater_B.csv` | κ người–người ≥ 0,6 |
| P3 | LLM gắn 300 issue pilot | `llm_labels.csv` | — |
| P4 | So LLM với gold; sửa codebook/prompt nếu cần | Báo cáo κ, precision, recall, theo nhóm ngoại lệ | **κ LLM–gold ≥ 0,6, precision ≥ 0,75** |
| P5 | Gắn nhãn toàn JFrog (phương án B) | Nhãn episode cho 15.535 issue | Recall bộ lọc chấp nhận được |
| P6 | Build v4 (`--leak-safe`, `--label-mode llm`); query points; huấn luyện + baseline | Kết quả T1-D, 5 seed | TGN vượt heuristic và GBDT về AUPRC |
| P7 | T1-E (cảnh báo sớm), ablation | Lead time, bảng ablation | — |
| P8 | Mở rộng Spring (distill) | `ml_Spring_v4.*`, kết quả | — |

Nếu ở P6 TGN **không** vượt baseline heuristic/GBDT: báo cáo trung thực đây là kết quả, và xem lại liệu tín hiệu bottleneck nằm ở văn bản (comment) nhiều hơn ở cấu trúc sự kiện — khi đó hướng tiếp theo là đưa embedding văn bản vào feature sự kiện.

---

## 7. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Khái niệm bottleneck quá chủ quan (κ người–người thấp) | Cao | Sửa codebook trước khi chạy quy mô lớn |
| Quá ít ca dương sau khi siết tiêu chí (JFrog chủ yếu Open → Done) | Cao | AUPRC, pos_weight; cân nhắc gộp `victim`; Spring có quy trình đầy đủ hơn |
| Nhãn LLM có sai số hệ thống | Trung bình | Gold set, báo cáo sai số theo nhóm; nhãn mềm (confidence) |
| Thời gian gắn nhãn local dài, model bị unload | Trung bình | Chạy tiếp được từ chỗ dừng; phương án B; chạy qua đêm |
| Đóng hàng loạt làm sai thời gian ứ đọng | Trung bình | Cờ `bulk_close`, ngoại lệ E8; loại khỏi phân phối dwell nếu cần |
| TGN không vượt baseline | Trung bình | Kết quả hợp lệ; hướng đưa văn bản vào feature |
| Dữ liệu công khai có trong pretraining của LLM | Thấp | Ghi nhận; so sánh với model khác họ |

---

## 8. Tái lập

```bash
# MongoDB (dump đã restore trong .tools/mongo-data)
.tools/mongodb-linux-x86_64-enterprise-ubuntu2404-9.0.2/bin/mongod \
  --dbpath .tools/mongo-data --bind_ip 127.0.0.1 --port 27017 --fork --logpath .tools/mongod.log --logappend

# Build không rò rỉ nhãn
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog --out data --leak-safe --as-name JFrog_ls

# Mẫu pilot: hồ sơ + bảng chấm -> data/llm_pilot/JFrog/
PYTHONPATH=.pylibs python -m jira_adapter.sampling --instance JFrog --out data/llm_pilot

# Gắn nhãn LLM (LM Studio đã load model; cấu hình trong .env), chạy tiếp được
python -m jira_adapter.llm_label --pilot-dir data/llm_pilot/JFrog --limit 5     # thử
python -m jira_adapter.llm_label --pilot-dir data/llm_pilot/JFrog              # toàn bộ

# Huấn luyện (cấu hình §5.3)
COMMON="--bs 128 --n_degree 10 --n_head 4 --n_layer 2 --lr 0.001 --patience 5 --node_dim 64 --time_dim 64 \
  --backprop_every 4 --use_memory --embedding_module graph_attention --message_function mlp \
  --message_dim 64 --memory_dim 64 --prefix tgn_jira"
python train_self_supervised.py -d JFrog_ls $COMMON --n_epoch 20 --memory_updater gru
python train_supervised.py      -d JFrog_ls $COMMON --n_epoch 30 --use_validation --n_runs 3
```

**Tệp liên quan:** `jira_adapter/{normalize,events,labels,to_tgn,build_mongo,dossier,sampling,llm_label}.py` · `data/ml_JFrog{,_nl1,_nl2}.*` · `data/llm_pilot/JFrog/` · `.env` (không commit).
