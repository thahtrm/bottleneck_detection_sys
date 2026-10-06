# Phương án gắn nhãn bottleneck bằng LLM cho dữ liệu Jira

**Phạm vi:** Thay nhãn v3 (dependency) bằng nhãn bottleneck theo **episode** do LLM trích xuất tín hiệu và rule xác định, kiểm định bằng gold set người chấm. Pilot trên **300 issue JFrog** qua API trước khi mở rộng.

**Liên quan:** `docs/bao-cao-tap-du-lieu-va-tien-xu-ly.md` (pipeline, nhãn v1/v2/v3), `docs/rubric-label-audit-bottleneck.md` (rubric chấm), `jira_adapter/labels.py`, `jira_adapter/to_tgn.py`.

---

## 0. Quyết định đã chốt

| Câu hỏi | Quyết định | Lý do |
|---|---|---|
| Đơn vị nhãn | **Episode** `(issue, start, end)` | Bottleneck là một giai đoạn, không phải thuộc tính vĩnh viễn; khớp với dự đoán tại thời điểm t của TGN; đo được lead time cảnh báo |
| Issue bị chặn, chờ bên ngoài | **Giữ lại, gắn `role` và `type`**, không loại bỏ | Giữ tối đa thông tin; định nghĩa nhãn huấn luyện chọn sau bằng rule (không phải gọi lại LLM) |
| LLM | **API cho pilot**, cân nhắc model local khi mở rộng | Chất lượng cao để xác lập trần; quyết định local dựa trên kết quả so sánh ở pilot |
| Quy mô pilot | **300 issue JFrog**, 100 trong số đó được 2 người chấm | Đủ để tính kappa và precision/recall theo nhóm; chi phí nhỏ |

---

## 1. Việc cần làm trước: rò rỉ nhãn trong pipeline hiện tại

Nhãn v3 là "issue có ≥1 link Block/Depend", nhưng thông tin này đang nằm sẵn trong đầu vào của mô hình. Đo trực tiếp trên `data/ml_JFrog.*` và `data/ml_Spring.*`:

| Kênh | JFrog | Spring | Mức rò rỉ |
|---|---|---|---|
| **Edge feature** one-hot `Block`/`Depend` trên sự kiện `link` (cột 5–6, `jira_adapter/to_tgn.py:62`) | 460 nút có sự kiện này, **432/432** issue dương nằm trong đó | 2.782 nút, **2.711/2.714** issue dương | **Gần như nhận diện hoàn toàn nhãn.** Với JFrog, sự kiện link luôn đến **trước** sự kiện có nhãn đầu tiên (232/232 ca kiểm tra được) |
| **Node feature** `[7] log1p(n_links)` (đếm từ trạng thái cuối document) | 3.175 nút > 0, chứa **100%** issue dương | — | Một phần (precision ≈ 15%) |
| **Node feature** `[6] has_block_link` | Luôn bằng 0 | Luôn bằng 0 | Không rò rỉ, nhưng là **bug**: `to_tgn.py` chỉ kiểm tra tên link kiểu Block, trong khi JFrog/Spring chỉ có Depend |

Vì vậy AUC 0,839 (JFrog) và 0,768 (Spring) có thể chỉ phản ánh việc mô hình đọc lại feature. Ngoài ra v3 không phân biệt issue **gây chặn** với issue **bị chặn**, và vẫn tính link giữa hai issue đã đóng từ lâu.

**Hành động:**
1. Train lại T1 với nhãn v3 trên hai biến thể. Mức sụt AUC chính là mức rò rỉ:
   - `JFrog_nl1`: bỏ one-hot loại link và direction (edge cột 5–14), bỏ node `[6]`, `[7]`.
   - `JFrog_nl2`: như `nl1` và bỏ hẳn sự kiện `link` (còn 53.541/55.666 sự kiện).

   **Kết quả (2026-10-04, T1 test AUC, 3 lần chạy, cùng cấu hình với báo cáo gốc):**

   | Dataset | Lần 1 | Lần 2 | Lần 3 | Trung bình |
   |---|---|---|---|---|
   | `JFrog` (v3 gốc) | 0,839 | 0,832 | 0,834 | **0,835** |
   | `JFrog_nl1` (bỏ loại link + node `[6]`, `[7]`) | 0,630 | 0,631 | 0,598 | **0,620** |
   | `JFrog_nl2` (`nl1` + bỏ sự kiện link) | 0,523 | 0,459 | 0,469 | **0,484** |

   **Kết luận:** khoảng 0,21 AUC đến trực tiếp từ việc đọc loại link. Phần còn lại (0,62) đến từ việc "có sự kiện link hay không"; bỏ nó đi thì mô hình ngang mức ngẫu nhiên. Nghĩa là **với nhãn v3, TGN không học được tín hiệu bottleneck nào từ diễn biến quy trình** (status/assignee/priority/comment). Kết quả "vượt mục tiêu ≥0,75" trong báo cáo gốc không còn đứng được, và đây là bằng chứng trực tiếp cho việc phải thay nhãn.

2. Với nhãn mới: **không được** có feature nào là hàm trực tiếp của các tín hiệu dùng để tạo nhãn tại cùng thời điểm hoặc tương lai (xem §7.3).

---

## 2. Định nghĩa bottleneck (góc nhìn PM)

> Một issue là **bottleneck** khi nó **cản dòng chảy công việc** và **sự chậm trễ của nó lan sang người khác hoặc sang mục tiêu** (release, khách hàng, issue khác).
> Chậm mà không ai phải chờ thì không phải bottleneck. Nhiều link mà vẫn tiến triển đều cũng không phải.

### 2.1. Điều kiện

`Bottleneck = (F1 ∨ F2 ∨ F3 ∨ F4) ∧ (I1 ∨ I2 ∨ I3)`

| Nhóm | Mã | Tiêu chí | Tín hiệu trong Jira | Ai tính |
|---|---|---|---|---|
| **F – Tắc dòng chảy** | F1 | **Ứ đọng:** ở một trạng thái *đang làm* lâu hơn p80–p90 của dự án (cùng trạng thái, cùng loại issue) | changelog status; thời gian không hoạt động | Code |
| | F2 | **Chờ đợi rõ ràng:** thời gian chờ lớn hơn nhiều so với thời gian làm | comment "waiting for…", "blocked on…", "need input", "pending review"; status *Waiting for…*, *In Review* kéo dài | LLM (trích) + code (đo) |
| | F3 | **Vòng lặp, làm lại:** reopen; In Progress ↔ Review lặp; assignee bị đẩy qua lại ≥3 lần | changelog status, assignee | Code |
| | F4 | **Thiếu nguồn lực:** ưu tiên cao nhưng chưa có người nhận, hoặc người nhận đang ôm nhiều issue ưu tiên cao | assignee, priority, WIP theo người | Code |
| **I – Có tác động** | I1 | **Gây chặn:** có issue khác *đang mở* phụ thuộc vào nó (chuỗi càng dài càng nặng) | link Block/Depend outward + trạng thái issue bên kia tại thời điểm t | Code |
| | I2 | **Trên đường găng release:** có fixVersion sắp tới, hoặc fixVersion bị đẩy lùi nhiều lần | fixVersion trong changelog | Code |
| | I3 | **Bị leo thang:** priority bị nâng, watcher tăng, nhiều người hỏi "any update?" | changelog priority; comment | LLM + code |

**Mức độ:** 0 = không; 1 = thỏa đúng một F và một I; 2 = nhiều F/I hoặc chuỗi chặn dài, ưu tiên cao (tương thích thang 0–2 của rubric).

### 2.2. Ngoại lệ: thường là dương tính giả

| # | Trường hợp | Xử lý |
|---|---|---|
| E1 | **Backlog chưa cam kết:** Open lâu, ưu tiên thấp, chưa ai nhận | Không phải bottleneck, trừ khi thỏa I1 |
| E2 | **Epic, umbrella, tracking issue:** sống lâu, nhiều link theo thiết kế | Loại khỏi F1; chỉ xét nếu có F2 rõ ràng |
| E3 | **Priority "Blocker"** là mức nghiêm trọng, **không phải** nghẽn dòng chảy | Ghi rõ trong prompt; không dùng priority làm tín hiệu F |
| E4 | Đóng với resolution **Duplicate / Won't Fix / Cannot Reproduce** sau thời gian dài mở | Bị bỏ quên, không phải tắc → âm tính |
| E5 | **Hoãn có chủ đích:** "postponed", "deferred to next major", đổi fixVersion kèm lý do | Âm tính, `exclusion = deferred` |
| E6 | **Việc lớn nhưng vẫn tiến triển đều** (comment, cập nhật định kỳ) | Âm tính |
| E7 | **Spike, research, PoC** | Âm tính, trừ khi thỏa I1 |
| E8 | **Artifact dữ liệu:** bulk close/bot, cả dự án ngừng hoạt động (lễ, freeze), ngày placeholder 1969 | Code phát hiện và loại khỏi phép tính dwell |
| E9 | **Issue có rất nhiều duplicate:** có tác động nhưng chưa chắc tắc | Chỉ dương nếu có F |

### 2.3. Ca cần quy ước

| # | Trường hợp | Quy ước |
|---|---|---|
| S1 | **Gây chặn và bị chặn** | Gắn `role = root` cho issue gây chặn, `role = victim` cho issue bị chặn. Nhãn huấn luyện chính dùng `root` |
| S2 | **Chờ bên ngoài** (khách hàng, vendor, upstream) | Dương tính, `type = external` |
| S3 | **Nghẽn hệ thống** (cả hàng chờ review ứ đọng) | Ngoài phạm vi nhãn cấp issue; ghi `type = process` nếu issue thể hiện rõ, phân tích cấp trạng thái làm riêng |
| S4 | **Bottleneck theo giai đoạn** | Một issue có thể có 0..n episode |
| S5 | **Bối cảnh OSS:** "Open" ≠ đã cam kết làm | Áp dụng E1 chặt; Mojang (bug tracker công khai) không phù hợp với định nghĩa |

---

## 3. Các phương án dùng LLM đã cân nhắc

| # | Phương án | Dùng trong đề xuất? |
|---|---|---|
| A | Phân loại trực tiếp zero/few-shot | Không: khó kiểm toán, LLM tính thời gian kém |
| **B** | **LLM trích tín hiệu theo codebook, code ra quyết định** | **Có: lõi của pipeline** |
| C | LLM làm labeling function trong weak supervision (Snorkel, Dawid–Skene) | Dự phòng nếu cần gộp nhiều nguồn nhãn |
| **D** | **LLM-as-judge kiểm tra ứng viên từ heuristic** | **Có: tầng lọc** |
| **E** | **Người kiểm tra ca LLM không chắc** | **Có: gold set và ca bất đồng** |
| F | Distillation sang model nhỏ | Giai đoạn mở rộng (Spring) |
| G | Khám phá taxonomy bằng gom cụm comment | Tùy chọn, để bổ sung `type` |
| H | Agent có công cụ lần theo chuỗi phụ thuộc | Không: chuỗi phụ thuộc tính bằng code rẻ hơn |

**Bẫy cần tránh:**
- **Hindsight:** *nhãn* được dùng thông tin về sau (cách issue kết thúc), *feature* thì không.
- LLM tính khoảng thời gian kém → mọi số liệu thời gian tính sẵn bằng code.
- **Nhiễm dữ liệu:** Spring/JFrog là công khai, LLM có thể đã thấy khi pretrain → ghi nhận như rủi ro.
- Thiên lệch vị trí và độ dài: comment dài ở cuối dễ lấn át → cắt ngắn từng comment, giữ thứ tự thời gian.

---

## 4. Pipeline

```
MongoDB JiraReposAnon
  ─► (1) Hồ sơ issue (code tính sẵn số liệu)
  ─► (2) Lọc ứng viên + mẫu ngẫu nhiên phân tầng
  ─► (3) LLM trích tín hiệu → JSON (self-consistency × 3)
  ─► (4) Rule kết hợp → nhãn + episode + role/type
  ─► (5) Kiểm định với gold set
  ─► (6) Map sang TGN: label(i, t) = 1 ⟺ t ∈ episode(i, role=root)
```

### 4.1. Hồ sơ issue (`jira_adapter/dossier.py`)

- **Metadata:** key, type, priority, resolution, components, fixVersion (kèm lịch sử thay đổi), tuổi issue.
- **Dòng thời gian trạng thái:** mỗi đoạn `(status, từ, đến, số ngày, percentile so với dự án)` (code tính).
- **Assignee:** lịch sử thay đổi; WIP ưu tiên cao của assignee tại từng thời điểm.
- **Link:** loại chuẩn hóa, chiều, trạng thái của issue bên kia **theo thời gian**.
- **Comment:** theo thứ tự thời gian, có timestamp, tác giả đã ẩn danh, mỗi comment cắt ≤500 ký tự, tổng ≤40 comment (giữ đầu và cuối).
- **Cờ code phát hiện:** epic/umbrella, bulk close, dự án ngừng hoạt động, ngày placeholder.

### 4.2. Lọc và lấy mẫu (pilot 300 issue JFrog)

| Tầng | Số issue | Tiêu chí |
|---|---|---|
| Ứng viên heuristic | 120 | Thỏa ≥1 F (F1 theo p90, regex `waiting|blocked|pending|need (input|review)` cho F2, F3, F4) |
| v3 dương | 60 | Có link Block/Depend (để đo v3 sai ở đâu) |
| Ngẫu nhiên phần còn lại | 120 | Không phải ứng viên (để ước lượng recall bị mất) |

Phân tầng thêm theo trạng thái mở/đóng và theme của loại issue (`jira_adapter/sampling.py`, seed 0).

**Đã chạy trên JFrog (2026-10-04):**

| | v3 | Ứng viên | Ngẫu nhiên |
|---|---|---|---|
| Quần thể | 450 | 2.848 | 12.237 |
| Mẫu (chấm đôi) | 60 (20) | 120 (40) | 120 (40) |

- Lý do ứng viên trong quần thể (một issue có thể nhiều lý do): F1 trạng thái đang làm 1.140 · F1 đã nhận nhưng chờ 188 · F2 comment chờ đợi 269 · F3 vòng lặp 931 · F4 ưu tiên cao chưa ai nhận 717.
- Kích thước hồ sơ nhỏ hơn dự kiến: trung vị **~490 token**, p90 ~940, tối đa ~3.600 (issue JFrog ít comment).
- **148/300 issue mẫu bị đóng hàng loạt** (≥20 issue cùng người, cùng phút; 91 đợt trong dự án) → thời gian ứ đọng trước khi đóng của các issue này không phản ánh dòng chảy thật. Cờ `bulk_close` có trong hồ sơ; codebook xử lý theo E8.
- Ví dụ v3 sai: `HAP-601` (v3 dương) chỉ phụ thuộc một issue đã đóng, không có hoạt động từ 2017 → backlog bị bỏ quên, không phải bottleneck.
- Đầu ra: `data/llm_pilot/JFrog/` — `dossiers/*.json`, `text/*.md`, `manifest.csv` (không đưa người chấm), `gold_rater_A.csv` (300), `gold_rater_B.csv` (100), `summary.json`.

### 4.3. Schema đầu ra LLM

```json
{
  "is_bottleneck": "yes | no | unsure",
  "role": "root | victim | none",
  "type": "dependency | external | review | resource | requirement | technical | process | null",
  "signals": {
    "waiting_for": "ai/cái gì đang được chờ, hoặc null",
    "explicit_block_mentions": ["trích nguyên văn"],
    "escalation": true,
    "deliberate_deferral": false
  },
  "episodes": [
    {"start": "ISO-8601", "end": "ISO-8601 | null",
     "start_evidence": "trích changelog/comment", "end_evidence": "trích changelog/comment"}
  ],
  "exclusion": "backlog | epic | deferred | duplicate_or_wontfix | spike | data_artifact | null",
  "confidence": 0.0
}
```

**Ràng buộc prompt (tóm tắt):**
- Đưa codebook §2 vào system prompt (phần cố định, dùng prompt caching).
- Mỗi kết luận phải có trích dẫn nguyên văn từ hồ sơ; không có bằng chứng thì trả `unsure`.
- Không tự tính khoảng thời gian; chỉ dùng số đã cho.
- Nhắc rõ E3: priority "Blocker" không phải bottleneck.
- Episode start/end phải trùng với một timestamp có trong hồ sơ.
- 3–5 ví dụ few-shot, gồm ít nhất một ca epic, một ca backlog và một ca root/victim.

**Self-consistency:** 3 lần lấy mẫu (temperature > 0), lấy đa số cho `is_bottleneck`/`role`/`type`; episode lấy giao các khoảng có ≥2/3 đồng ý.

### 4.4. Rule kết hợp

```
positive(i, episode) ⟺ LLM.is_bottleneck = yes (đa số)
                     ∧ LLM.exclusion = null
                     ∧ (F1 ∨ F2 ∨ F3 ∨ F4) kiểm chứng bằng số liệu code trong khoảng episode
                     ∧ (I1 ∨ I2 ∨ I3) kiểm chứng bằng số liệu code
unsure hoặc LLM và code mâu thuẫn → hàng đợi người chấm
```

Nhãn huấn luyện chính: `role = root`. Biến thể ablation: `root ∪ victim`; loại `external`.

---

## 5. Kiểm định

### 5.1. Gold set

- **300 issue pilot**, chấm theo `docs/rubric-label-audit-bottleneck.md`, mở rộng thêm: `role`, `type`, start/end episode.
- **100 issue** được **2 người chấm độc lập** → đo mức đồng thuận giữa người với người (trần thực tế của bài toán).
- Người chấm **không** xem output LLM trước khi chấm.

### 5.2. Chỉ số và ngưỡng go/no-go

| Chỉ số | Ngưỡng đi tiếp |
|---|---|
| Cohen's κ người–người (100 issue) | ≥ 0,6; nếu thấp hơn → sửa codebook trước, không phải sửa LLM |
| κ LLM–gold (`is_bottleneck`) | ≥ 0,6 **và** ≥ 0,8 × κ người–người |
| Precision lớp dương | ≥ 0,75 |
| Recall ước lượng (tầng ngẫu nhiên) | Báo cáo; nếu bỏ sót nhiều → nới tiêu chí lọc |
| Độ chính xác `role` (root vs victim) | ≥ 0,7 trên các ca dương |
| Biên episode | IoU ≥ 0,5 hoặc lệch start ≤ 7 ngày so với gold |
| Chính xác trên từng nhóm E1–E9 | Báo cáo riêng; nhóm nào sai nhiều → bổ sung few-shot |

Đồng thời đo **v3 so với gold** trên cùng 300 issue để có mốc so sánh.

---

## 6. Chi phí ước tính

- Pilot: hồ sơ thực đo tổng ~170k token cho 300 issue; cộng codebook + few-shot (~3–4k token/lần, cache được) × 3 lần lấy mẫu ≈ **dưới 4M token đầu vào**, cộng ~0,3M token đầu ra.
- Toàn bộ JFrog (15.535 issue): chỉ gửi ứng viên cộng mẫu ngẫu nhiên; số ứng viên đo được sau bước 4.2.
- Giảm chi phí: Batch API; prompt caching cho codebook; khi mở rộng có thể so sánh model nhỏ hơn hoặc model local (Qwen/Llama trên GPU sẵn có) với kết quả API trên chính gold set.

---

## 7. Map sang TGN

### 7.1. Nhãn theo sự kiện

`label(i, t) = 1 ⟺ t ∈ [start, end)` của một episode `role = root` của issue i. Không còn phụ thuộc vào việc issue "có link hay không", nên tách biệt được với feature.

### 7.2. Vấn đề kỹ thuật: issue đang tắc thì ít sự kiện

Issue đang nghẽn thường **không có** sự kiện status/assignee/priority trong episode, nên loader node classification hiện tại (nhãn gắn trên sự kiện) sẽ gần như không thấy điểm dương. Các hướng xử lý:

1. **Sự kiện "tick" định kỳ:** thêm self-loop mỗi tuần cho issue đang mở, edge feature = 0 (chỉ thời gian), để mô hình được truy vấn trong lúc issue tắc. **Đề xuất mặc định.**
2. Gắn nhãn lên mọi sự kiện, kể cả comment, trong episode (ít điểm hơn, thiên lệch về issue có comment).
3. Đánh giá tại các mốc thời gian cố định (snapshot) thay vì tại sự kiện.

### 7.3. Chống rò rỉ

- Bỏ `has_block_link` và các feature tổng hợp từ trạng thái **cuối document** (`n_links` hiện tại) khỏi node feature; nếu cần, tính lại point-in-time.
- Sự kiện link giữ lại (đó là tín hiệu hợp lệ tại thời điểm xảy ra), nhưng timestamp link đang là xấp xỉ (xem giới hạn §1 trong `jira_adapter/README.md`): kiểm tra độ nhạy.
- Kiểm tra tỉ lệ dương trên từng split train/val/test (bài học từ v1: lệch 1,1% / 36% / 55%).

### 7.4. Chỉ số đánh giá mô hình

- AUC/AUPRC trên sự kiện (so sánh được với v3).
- **Lead time:** khoảng thời gian từ khi mô hình vượt ngưỡng đến `start` episode trong gold. Đây là giá trị thực tế cho PM.
- Precision@k theo tuần: top-k issue mỗi tuần có bao nhiêu là bottleneck thật.

---

## 8. Kế hoạch thực hiện

| Bước | Việc | Đầu ra |
|---|---|---|
| P0 ✅ | Đo rò rỉ v3 (§1) | AUC 0,835 → 0,620 → 0,484; sửa bug `has_block_link`, `normalize_priority`; cờ `--leak-safe` |
| P1 ✅ | Code hồ sơ issue + lọc + lấy mẫu (`jira_adapter/dossier.py`, `jira_adapter/sampling.py`) | 300 hồ sơ JFrog + bảng chấm (§4.2) |
| P2 | Người chấm gold set (song song với P3) | `gold_jfrog_300.csv` |
| P3 | Prompt, chạy LLM, rule kết hợp (`jira_adapter/llm_label.py`) | Nhãn LLM cho 300 issue |
| P4 | Kiểm định §5, lặp lại codebook/prompt nếu không đạt | Báo cáo κ, precision, recall, theo nhóm ngoại lệ |
| P5 | Gắn nhãn toàn bộ JFrog, thêm sự kiện tick, train lại TGN | `ml_JFrog_llm.*`, kết quả T1 |
| P6 | Mở rộng Spring (gắn ứng viên + distill), quyết định API hay local | `ml_Spring_llm.*` |

---

## 9. Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Bản thân khái niệm "bottleneck" quá chủ quan (κ người–người thấp) | Sửa codebook trước khi chạy LLM quy mô lớn |
| LLM ảo giác bằng chứng | Bắt buộc trích dẫn nguyên văn; code kiểm tra chuỗi trích có tồn tại trong hồ sơ |
| Quá ít điểm dương sau khi siết tiêu chí | Báo cáo AUPRC; cân nhắc gộp `victim` hoặc hạ ngưỡng F1 xuống p80 |
| Lọc heuristic bỏ sót loại nghẽn chưa biết | Tầng mẫu ngẫu nhiên; khám phá taxonomy (phương án G) |
| Dữ liệu đã có trong pretraining của LLM | Ghi nhận; so sánh với model local khác họ |

---

## Tài liệu tham khảo (cần kiểm tra lại trước khi trích dẫn)

- Montgomery, Lüders, Maalej (2022). *An Alternative Issue Tracking Dataset of Public Jira Repositories.* MSR.
- Lüders, Pietz, Maalej (2022). *Beyond Duplicates: Towards Understanding and Predicting Link Types in Issue Tracking Systems.* MSR.
- Valdivia-Garcia, Shihab (2014). *Characterizing and Predicting Blocking Bugs in Open Source Projects.* MSR.
- Xia et al. (2015). *ELBlocker: Predicting Blocking Bugs with Ensemble Imbalance Learning.* IST.
- Choetkiertikul et al. (2015, 2017). Dự đoán trễ của issue bằng networked classification.
- Gilardi, Alizadeh, Kubli (2023). *ChatGPT Outperforms Crowd-Workers for Text-Annotation Tasks.* PNAS.
- Pangakis, Wolken, Fasching (2023). *Automated Annotation with Generative AI Requires Validation.*
- Ratner et al. (2017). *Snorkel: Rapid Training Data Creation with Weak Supervision.* VLDB.
- Wang et al. (2022). *Self-Consistency Improves Chain of Thought Reasoning in Language Models.*
- Goldratt, *The Goal* (Theory of Constraints); Reinertsen, *The Principles of Product Development Flow*.
