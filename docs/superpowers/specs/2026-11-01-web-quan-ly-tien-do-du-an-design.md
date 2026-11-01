# Tài liệu yêu cầu — Web hỗ trợ quản lý tiến độ dự án (Early Risk Web)

| | |
|---|---|
| Ngày | 2026-11-01 |
| Trạng thái | Đã duyệt (2026-11-02) |
| Liên quan | thư viện `early_risk_detection` (repo này), `bundles/delay`, `bundles/criticality` |

Quy ước trong tài liệu:
- **[Chốt]**: người dùng (product owner) đã quyết trong buổi phân tích.
- **[Đề xuất BA]**: BA tự quyết, chưa được duyệt riêng. Có thể đổi mà không ảnh hưởng mục tiêu.
- **[Giả định]**: chưa có thông tin, cần xác nhận (xem mục 15).

---

## 1. Bối cảnh và mục đích

Hiện nay PM phát hiện task trễ hạn hoặc task quan trọng bị bỏ sót một cách thủ công và thường là muộn. Repo này đã có hai mô hình nghiên cứu, được huấn luyện trên The Public Jira Dataset (2,68 triệu issue):

| Mô hình | Câu hỏi | Đầu ra | Thời điểm chấm |
|---|---|---|---|
| Delay risk (`DelayRiskScorer`) | Task có vượt SLA không? | `p_delay`, `is_at_risk`, `predicted_duration_days` | Lúc tạo task (T0) |
| Criticality (`CriticalityScorer`) | Task nào ảnh hưởng lịch dự án nhiều nhất? | `score`, `rank_in_instance`, `is_critical` (top 5%) | Lúc tạo task (T0) |

**Mục đích:** xây một web chạy nội bộ để:
1. Liên kết với Jira Cloud, tự lấy task và lịch sử cập nhật.
2. Tự chạy pipeline phân tích khi có cập nhật trên Jira và theo lịch hằng ngày.
3. Dùng các mô hình trên, cộng các tín hiệu động, để phát hiện task có nguy cơ trễ hạn và task quan trọng, kèm giải thích.
4. Dùng LLM self-host đề xuất action. PM được sửa đề xuất, và sau khi PM xác nhận thì web ghi thay đổi lên Jira.
5. Gửi cảnh báo vào Slack và cung cấp dashboard trực quan.

**Bối cảnh triển khai: bản demo [Chốt].**
- Jira Cloud gói miễn phí, tạo bằng email cá nhân, demo trên một vài dự án.
- Chạy trên một máy, phần cứng như README: RTX 4060 Ti 16 GB, RAM 30 GB, 16 nhân.
- Nội dung task gồm cả tiếng Anh và tiếng Việt.

Các yêu cầu bên dưới được viết cho bản demo này. Những phần chỉ cần khi triển khai thật được ghi rõ "(triển khai thật)".

**Làm song song [Chốt]:** web và **mô hình chấm điểm tại thời điểm bất kỳ** (mục 10) được phát triển song song. Web phải chạy được ngay với hai mô hình T0 hiện có và thay mô hình mới vào mà không phải sửa lõi.

## 2. Mục tiêu, ngoài phạm vi, điều không được để xảy ra

### 2.1 Mục tiêu
- G1. **Giảm số task trễ hạn và bảo đảm tiến độ dự án [Chốt].** Chỉ số đo ở mục 11.
- G2. Mỗi sáng, PM trả lời được 4 câu hỏi trong khoảng 2 phút [Chốt]: tiến độ hiện tại ra sao, có task mới nào, task nào đang bị block, task nào có nguy cơ cần xử lý.
- G3. Cảnh báo đến đúng lúc: bản tổng hợp mỗi ngày là ưu tiên số 1, báo ngay khi có task mới hoặc task được cập nhật cũng bắt buộc phải có [Chốt].
- G4. Mỗi đánh giá đều có giải thích kiểm chứng được, và mỗi đề xuất đều thực hiện được ngay trên web.

### 2.2 Ngoài phạm vi giai đoạn 1
- Thực hiện action trực tiếp từ Slack (bấm nút trong Slack). Giai đoạn 1 chỉ có link về web [Đề xuất BA].
- @mention Slack thật, tức ánh xạ tài khoản Jira sang Slack [Chốt: không làm, hiển thị tên Jira].
- Các kênh khác ngoài Slack (Teams, email…). Kiến trúc phải cho phép thêm về sau.
- Jira Server/Data Center. Chỉ hỗ trợ Jira Cloud [Chốt].
- Huấn luyện lại mô hình từ giao diện web.
- Các yêu cầu của môi trường production: nhiều máy, tính sẵn sàng cao, nhiều site Jira, đánh giá hiệu quả thực tế sau 3 tháng. Bản demo đánh giá bằng mô phỏng (mục 9b, 11).

### 2.3 Những điều sẽ coi là thất bại dù hệ thống "chạy được" [Đề xuất BA]
- **Cảnh báo quá nhiều** khiến PM bỏ qua kênh Slack và dashboard. Lưu ý: model delay T0 ở ngưỡng mặc định 0,39 chỉ có precision ≈ 0,30, nghĩa là khoảng 70% cảnh báo sai nếu dùng thẳng (xem mục 6.4).
- **LLM bịa lý do** không có trong dữ liệu Jira, hoặc đề xuất action không thực hiện được.
- **Web tự sửa Jira** khi PM chưa xác nhận.
- Gửi dữ liệu Jira ra bất kỳ dịch vụ LLM bên ngoài nào.

## 3. Người dùng và vai trò [Chốt: có Admin, PM, Người xem]

| Vai trò | Quyền |
|---|---|
| **Admin** | Kết nối Jira (site, tài khoản dịch vụ, webhook), cấu hình kênh Slack, chọn dự án được theo dõi, cấu hình ngưỡng, giờ làm việc và giờ gửi tổng hợp, quản lý người dùng và vai trò, chọn phiên bản mô hình đang chạy, xem nhật ký hệ thống. |
| **PM** (theo từng dự án) | Xem dashboard và chi tiết task của dự án mình phụ trách, xem, sửa và xác nhận action để ghi lên Jira, đánh dấu "bỏ qua" hoặc "đã xử lý", cấu hình cá nhân (bộ lọc mặc định). |
| **Người xem** | Chỉ xem dashboard và chi tiết các dự án được cấp quyền. Không thấy nút thực hiện action. |

- Một người có thể là PM của dự án này và là Người xem của dự án khác [Đề xuất BA].
- Đăng nhập web: dùng đăng nhập Atlassian (OAuth 2.0 3LO) để có luôn quyền ghi Jira theo người dùng. Người xem không có tài khoản Jira và Admin khởi tạo dùng tài khoản cục bộ do Admin cấp [Đề xuất BA]. PM bắt buộc đăng nhập Atlassian, vì cần OAuth để ghi Jira.

## 4. Định nghĩa nghiệp vụ

### 4.1 "Hạn" của task [Chốt: trễ so với due date và sprint trên Jira]

Kết quả khảo sát dữ liệu huấn luyện (mục 9) cho thấy due date gần như không được điền. Môi trường thật được giả định giống dữ liệu này [Chốt], nên hạn được xác định theo **thứ tự ưu tiên** [Đề xuất BA]:

1. `duedate` của task, nếu có.
2. `endDate` của **sprint đang active hoặc sprint tương lai** chứa task. Nếu task thuộc nhiều sprint thì lấy sprint chưa đóng sớm nhất.
3. `releaseDate` sớm nhất trong các **Fix Version chưa release** của task.
4. Nếu không có cái nào: dùng "SLA mô hình" = ngày tạo + SLA heuristic của thư viện (14/21/30/45/90 ngày theo priority và loại issue, xem `delay/features.py:35`).

Mọi nơi hiển thị rủi ro trễ hạn (dashboard, Slack, panel chi tiết) **phải ghi rõ loại hạn**: "Trễ due date 05/11", "Trễ sprint 24 (kết thúc 04/11)", "Vượt release 2.3", "Hạn: SLA mô hình 14 ngày".

### 4.2 Mức rủi ro trễ hạn
Có ba mức: **Cao, Trung bình, Thấp**. Mức được tổng hợp từ các tín hiệu ở mục 6.4. "Tăng bậc" là khi mức đi từ Thấp lên TB, từ TB lên Cao, hoặc từ Thấp lên Cao.

### 4.3 Task quan trọng
Là task có `is_critical = true` từ model criticality (top 5% theo điểm trong cùng instance; một Jira Cloud site tương ứng một instance). Dashboard hiển thị tag "★ Quan trọng top 5%". Mức quan trọng **chỉ dùng tag riêng (màu tím), không dùng màu của rủi ro** [Đề xuất BA].

### 4.4 Task bị block
Task chưa xong mà có link loại "is blocked by" hoặc "depends on" tới một task khác **chưa resolved** [Đề xuất BA]. Ánh xạ loại link dùng `link_type_std` đã có trong ETL (Depend, Block…).

### 4.5 Task mới
Task được tạo trong 24 giờ gần nhất, tính tới thời điểm xem hoặc thời điểm gửi tổng hợp.

## 5. Kịch bản sử dụng chính

### K1. Bản tổng hợp mỗi ngày (ưu tiên 1) [Chốt]
1. Trước giờ gửi (mặc định 8:00, ngày làm việc, múi giờ Asia/Ho_Chi_Minh) [Đề xuất BA]: đồng bộ bù từ Jira, chạy lô cả hai model (criticality cần replay toàn bộ sự kiện, khoảng 1,5 phút trên GPU với 2,68 triệu issue) và tính lại toàn bộ tín hiệu động.
2. LLM sinh giải thích và đề xuất action cho các task trong danh sách "Cần xử lý".
3. Gửi `[Tổng hợp ngày]` vào kênh Slack (mục 6.8) và cập nhật dashboard.

### K2. Task mới được tạo trên Jira [Chốt]
Jira webhook `issue_created` → web nhận, đồng bộ task → chấm delay T0 + tín hiệu động → nếu mức rủi ro là Cao thì gửi `[Nguy cơ trễ]`. Criticality của task mới được tính ở lượt lô kế tiếp. Lượt lô gần thời gian thực được để ngỏ: tuỳ thời gian chạy đo được, xem mục 14.

### K3. Task được cập nhật [Chốt]
Webhook `issue_updated` (đổi status, assignee, priority, sprint, due date, fix version, link) → đồng bộ → tính lại **tín hiệu động** (mô hình T0 không đổi khi task cập nhật, xem mục 6.4) → nếu mức rủi ro **tăng bậc** thì gửi `[Tăng rủi ro]`; nếu vừa bị block thì gửi `[Bị block]`.

### K4. PM xử lý một task
PM mở dashboard → chọn task → panel phải hiển thị "Vì sao" và các đề xuất → PM chọn, sửa nội dung → bấm **Xác nhận & ghi lên Jira** → web kiểm tra xung đột → ghi bằng tài khoản Jira của PM → gửi `[Đã xử lý]` vào Slack → task chuyển sang tab "Đã xử lý".

## 6. Yêu cầu chức năng

### 6.1 Kết nối Jira Cloud
- FR-J1. Admin cấu hình site Jira Cloud và tài khoản dịch vụ (API token) để **đọc** dữ liệu.
- FR-J2. **Đồng bộ ban đầu (bootstrap):** kéo toàn bộ lịch sử của các dự án được chọn, gồm issue, changelog đầy đủ, comment, issue link, sprint (id, tên, trạng thái, startDate, endDate, completeDate), Fix Version (releaseDate, released), due date. Lý do lấy toàn bộ lịch sử: model criticality replay toàn bộ dòng sự kiện, model delay dùng lịch sử dự án và người làm, và chỉ số mốc (mục 11) cần 3–6 tháng trước triển khai.
- FR-J3. **Webhook** `jira:issue_created`, `jira:issue_updated`, `issuelink_created/deleted`, `sprint_*`, `jira:version_*`, nhận qua một endpoint HTTPS công khai có xác thực secret.
  - Ở bản demo, người dùng tự tạo site nên là **site-admin**, và có thể đăng ký webhook admin (qua giao diện hoặc REST) mà không bị giới hạn 30 ngày như webhook tạo qua OAuth app.
  - Endpoint công khai dùng **tunnel** (ngrok đã chạy sẵn trên máy, hoặc cloudflared), chỉ chuyển tiếp đúng đường dẫn webhook [Đề xuất BA].
  - (Triển khai thật) dùng ingress hoặc reverse proxy.
  - URL tunnel thay đổi sau mỗi lần khởi động thì web phải tự cập nhật lại webhook, hoặc dùng domain tĩnh của tunnel.
- FR-J4. **Không có polling định kỳ [Chốt]**: webhook là cơ chế duy nhất để phát hiện thay đổi, gồm cả sự kiện sprint, version và xoá issue. Chỉ có **một lượt đồng bộ bù** bằng JQL `updated >= <mốc webhook cuối − 5 phút>` khi app khởi động và trước lô sáng [Chốt], để bù các thay đổi xảy ra lúc app hoặc tunnel tắt. Xử lý idempotent theo (issue, changelog id).
- FR-J5. Dữ liệu được ghi vào kho nội bộ và xuất ra **đúng schema DuckDB của `early_risk_detection.data.etl`** (`issues`, `issue_changelogs`, `issue_links`, `issue_comments`). Mở rộng schema với các bảng hoặc cột mới: `sprints`, `issue_sprints` (dựng lại từ changelog `Sprint`), `fix_versions`, `issues.duedate`. Embedding văn bản tạo bằng `nomic-embed-text` qua Ollama nội bộ, như thư viện đang làm.
- FR-J6. Chịu được giới hạn số lần gọi API (rate limit) của Jira Cloud: retry có backoff, đọc header `Retry-After`.

### 6.2 Pipeline phân tích
- FR-P1. Hai loại chạy: **lô** (theo lịch, chấm mọi task đang mở bằng tất cả bộ chấm) và **sự kiện** (theo webhook, chấm một số task bằng delay T0 + tín hiệu động).
- FR-P2. Mỗi lượt chạy ghi lại: thời điểm, phiên bản từng mô hình (theo `manifest.json` của bundle), số task, thời lượng, lỗi.
- FR-P3. **Lưu lịch sử điểm của từng task theo thời gian** (snapshot). Dùng để phát hiện tăng bậc, vẽ xu hướng, và làm dữ liệu đánh giá mô hình (mục 10, 11).
- FR-P4. Pipeline lỗi (ví dụ LLM không phản hồi) thì vẫn gửi cảnh báo dựa trên điểm số và luật, kèm ghi chú "chưa có đề xuất".

### 6.3 Giao diện bộ chấm điểm (để làm song song với model) [Đề xuất BA]
Mọi bộ chấm đều cài một giao diện chung:
```
score(issue_keys | all_open, as_of) -> danh sách {
  issue_key, scorer_id, scorer_version,
  kind: "delay" | "criticality",
  value (0..1), level (Cao/TB/Thấp) | is_critical,
  deadline_type, deadline_date (nếu có),
  factors: [{name, value, direction, source}]   # dùng cho "Vì sao"
}
```
Các bộ chấm ở giai đoạn 1: `delay_t0` (bundle hiện có), `criticality_t0` (bundle hiện có), `rules_dynamic` (mục 6.4). Khi có `delay_anytime` (mục 10), Admin bật lên ở chế độ **chạy bóng**: chấm và lưu điểm nhưng không dùng để cảnh báo, để so sánh. Sau đó Admin chuyển sang chế độ chính thức.

### 6.4 Các tín hiệu rủi ro trễ hạn
Hai mô hình T0 dựng lại thuộc tính tại thời điểm tạo task. Vì vậy **chạy lại sau khi task cập nhật sẽ cho đúng kết quả cũ** (thiết kế chống rò rỉ, `features/t0.py`), và mô hình không biết due date, sprint hay release (ETL hiện tại không lấy các trường này). Rủi ro được tổng hợp từ:

**(a) Mô hình T0** (chấm một lần khi tạo, sau đó giữ nguyên):
- `predicted_finish = created + predicted_duration_days`. Nếu `predicted_finish > hạn` (mục 4.1) thì có tín hiệu "dự kiến vượt hạn X ngày".
- `p_delay` (so với SLA mô hình) dùng như **chỉ số rủi ro chung**. Ngưỡng 0,39 trong bundle cho precision ≈ 0,30 và recall ≈ 0,82. Vì vậy `p_delay` **không được tự nó kích hoạt cảnh báo Cao** [Đề xuất BA], chỉ góp vào mức TB hoặc vào xếp hạng.

**(b) Tín hiệu động theo luật** (tính lại mỗi lần cập nhật và mỗi lượt lô). Ngưỡng mặc định là [Đề xuất BA], Admin chỉnh được theo dự án:

| Tín hiệu | Mặc định |
|---|---|
| Đã quá hạn mà chưa xong | quá hạn ≥ 0 ngày |
| Sprint sắp hết mà task chưa bắt đầu | đã qua ≥ 70% thời gian sprint, task vẫn ở nhóm trạng thái "To Do" |
| Đứng yên ở một trạng thái | lâu hơn P75 thời gian lưu ở trạng thái đó của dự án (tính từ lịch sử) |
| Bị block | theo mục 4.4; mức nặng hơn nếu block > 3 ngày |
| Bị reopen | ≥ 1 lần trong sprint hiện tại |
| Dời hạn nhiều lần | due date hoặc sprint đổi ≥ 2 lần |
| Đổi assignee nhiều lần | ≥ 2 lần |
| Chưa có assignee mà hạn gần | hạn ≤ 3 ngày làm việc |
| Đã trôi sprint trước đó | task từng thuộc ≥ 1 sprint đã đóng |

**(c) Mô hình chấm tại thời điểm bất kỳ** (khi có, mục 10): thay thế dần (a) và một phần (b).

**Quy tắc tổng hợp mức** [Đề xuất BA, cấu hình được]:
- **Cao**: quá hạn; hoặc ≥ 2 tín hiệu luật; hoặc 1 tín hiệu luật và (dự kiến vượt hạn hoặc `p_delay` ≥ ngưỡng cao); hoặc (khi có) `delay_anytime` ≥ ngưỡng Cao.
- **TB**: 1 tín hiệu luật; hoặc dự kiến vượt hạn; hoặc `p_delay` ≥ 0,39.
- **Thấp**: còn lại.

Mỗi tín hiệu đi vào `factors` với giá trị và nguồn, để hiển thị ở "Vì sao" và để LLM trích dẫn.

### 6.4b Kiểm định mô hình trước khi bật cảnh báo [Đề xuất BA]
Hai bundle T0 được fit trên dữ liệu công khai, với văn bản tiếng Anh và embedding `nomic-embed-text`. Với site Jira demo, cần lưu ý:
- Site demo là một **instance chưa từng thấy**. `CriticalityScorer` one-hot theo danh sách instance lúc huấn luyện (`criticality/readout.py:32`), nên site mới nhận vector toàn 0.
- TF-IDF, SVD và target encoding của model delay được fit trên văn bản tiếng Anh. Văn bản tiếng Việt sẽ cho đặc trưng văn bản kém tin cậy. `nomic-embed-text` chủ yếu cho tiếng Anh.
- Dự án demo mới tạo **không có lịch sử**, mà đặc trưng tải, lịch sử dự án và replay criticality đều cần lịch sử (xem mục 9b).

Vì vậy:
- **FR-V1.** Đánh giá bằng **mô phỏng** (mục 9b): chấm tại nhiều mốc `as_of` trên dữ liệu đã biết kết quả, rồi so với thực tế (trễ theo mục 4.1). Đo precision, recall và PR-AUC cho từng bộ chấm (T0, luật, tổ hợp). Đánh giá riêng nhóm task tiếng Việt.
- **FR-V2.** Admin xem kết quả đánh giá và đặt ngưỡng. **Tín hiệu từ mô hình chỉ góp vào cảnh báo khi vượt ngưỡng chất lượng do Admin đặt.** Nếu không đạt thì chạy bằng luật động, mô hình chỉ chạy bóng.
- **FR-V3.** Hạng mục mô hình (mục 10) cần đánh giá và cân nhắc **embedding đa ngôn ngữ** (ví dụ `bge-m3`, có trên Ollama). Đổi embedding thì **phải huấn luyện lại cả hai bundle**, vì không gian vector và số chiều thay đổi.

### 6.5 Mức độ quan trọng
- FR-C1. Chạy `CriticalityScorer` theo lô (ít nhất mỗi ngày trước bản tổng hợp) cho mọi task đang mở.
- FR-C2. Hiển thị tag top 5% và thứ hạng trong dự án [Đề xuất BA: thêm thứ hạng trong dự án vì PM chỉ quan tâm dự án của mình].
- FR-C3. Danh sách "Cần xử lý" xếp theo **mức rủi ro trước, sau đó đến điểm quan trọng** [Đề xuất BA]. Task quan trọng top 5% mà rủi ro Thấp vẫn có mặt trong danh sách khi task mới được tạo (mục 6.8, `[Quan trọng]`).

### 6.6 LLM: giải thích và đề xuất action
- FR-L1. LLM **self-host** [Chốt]. Không gửi dữ liệu Jira ra ngoài. Phục vụ trên Ollama sẵn có của máy [Đề xuất BA]. Ràng buộc phần cứng: 16 GB VRAM dùng chung, nên chọn model khoảng 7–14B lượng tử hoá Q4. Model 27B hiện có (khoảng 17 GB) không vừa VRAM. Model cụ thể để đội xây dựng chọn, xem mục 14.
- FR-L1b. **Song ngữ [Chốt: nội dung gồm tiếng Anh và tiếng Việt].**
  - LLM phải đọc được task viết bằng tiếng Anh, tiếng Việt hoặc lẫn cả hai.
  - Giải thích và đề xuất mặc định viết bằng tiếng Việt, người dùng chuyển sang tiếng Anh được.
  - Comment ghi lên Jira theo ngôn ngữ PM chọn, mặc định cùng ngôn ngữ với task [Đề xuất BA].
  - Giao diện web có hai ngôn ngữ vi/en [Đề xuất BA].
- FR-L2. Đầu vào cho mỗi task: tóm tắt và mô tả (cắt ngắn), trạng thái, assignee, hạn và loại hạn, `factors` từ các bộ chấm, tóm tắt changelog gần đây, task chặn và task bị chặn, tải hiện tại của assignee (số task mở). Không đưa toàn bộ comment, chỉ N comment gần nhất đã cắt ngắn.
- FR-L3. Đầu ra **bắt buộc theo JSON schema**:
  - `explanation`: 1–3 câu tiếng Việt, **mỗi khẳng định phải trỏ tới một factor hoặc một trường Jira có trong đầu vào**;
  - `actions[]`: mỗi action gồm `type` thuộc danh mục ở FR-L4, `params`, `rationale`, `confidence`;
  - `advice[]`: lời khuyên không thực thi được.

  Đầu ra sai schema hoặc trích dẫn factor không tồn tại thì bị loại, và web hiển thị "chưa có đề xuất".
- FR-L4. **Danh mục action web thực thi được** [Đề xuất BA]:

  | Loại | Thao tác trên Jira |
  |---|---|
  | `comment` | Thêm comment (có thể nhắc tên người) |
  | `reassign` | Đổi assignee |
  | `change_priority` | Đổi priority |
  | `move_sprint` | Chuyển sang sprint khác |
  | `change_duedate` | Sửa due date |
  | `add_link` | Tạo link phụ thuộc hoặc block |
  | `add_label` / `flag` | Gắn label hoặc flag |

  Đề xuất `reassign` chỉ được chọn người trong danh sách thành viên dự án, kèm tải hiện tại của họ.
- FR-L5. Lưu prompt, phiên bản model LLM và đầu ra thô cho mỗi lần sinh, để kiểm tra lại.

### 6.7 Thực hiện action lên Jira [Chốt: LLM đề xuất → PM sửa → PM xác nhận → web ghi Jira]
- FR-A1. PM (của dự án) thấy các đề xuất dạng checkbox. Nội dung (comment, assignee, sprint, ngày…) **sửa được** trước khi gửi. PM cũng có thể tự thêm action từ danh mục.
- FR-A2. Một nút **Xác nhận & ghi lên Jira**. Không có đường nào để ghi Jira mà không qua bước PM xác nhận.
- FR-A3. Ghi bằng **OAuth của chính PM** [Đề xuất BA; bản POC dùng tài khoản dịch vụ chung, comment ghi rõ PM xác nhận — Chốt]. Lịch sử Jira hiển thị đúng người sửa, và quyền của web không vượt quá quyền của PM.
- FR-A4. **Kiểm tra xung đột:** nếu `updated` của task trên Jira mới hơn thời điểm sinh đề xuất thì dừng lại, hiển thị phần đã thay đổi và yêu cầu PM xem lại.
- FR-A5. Ghi từng action riêng. Action nào lỗi thì báo rõ action đó và giữ các action đã thành công.
- FR-A6. **Nhật ký:** đề xuất gốc, bản PM đã sửa, người xác nhận, thời điểm, kết quả từ Jira API. Phân loại kết quả: chấp nhận nguyên văn / chấp nhận có sửa / bỏ qua.
- FR-A7. PM có thể đánh dấu "Bỏ qua" (kèm lý do tuỳ chọn) hoặc "Đã xử lý ngoài web". Task đó không được nhắc lại cho đến khi rủi ro tăng bậc.

### 6.8 Cảnh báo Slack [Chốt: một kênh duy nhất, prefix loại cảnh báo, @ người phụ trách]
- FR-S1. Admin cấu hình **một kênh Slack** (Slack app hoặc bot token, hoặc incoming webhook). Mọi thông báo vào kênh này.
- FR-S2. Định dạng tin: `[Loại cảnh báo][MÃ_DỰ_ÁN] <KEY> <tóm tắt> · <mức/%> · <loại hạn> · @<Tên hiển thị Jira>`, cộng một dòng lý do ngắn, link Jira, link panel trên web. Mã dự án trong prefix là [Đề xuất BA] để lọc được khi có nhiều dự án.
- FR-S3. **@ người phụ trách = tên hiển thị Jira** (`displayName`). Nếu không có thì dùng `accountId` [Chốt]. Đây là @ dạng văn bản: Slack **không** gửi thông báo riêng cho người đó.
- FR-S4. Loại cảnh báo [Đề xuất BA]:

  | Prefix | Khi nào | @ ai |
  |---|---|---|
  | `[Tổng hợp ngày]` | 8:00 ngày làm việc, mỗi dự án một tin | PM dự án |
  | `[Nguy cơ trễ]` | Task mới có mức Cao | Assignee (không có thì PM) |
  | `[Tăng rủi ro]` | Mức rủi ro tăng bậc | Assignee + PM |
  | `[Bị block]` | Vừa bị block, hoặc block > 3 ngày | Assignee + assignee của task chặn |
  | `[Quan trọng]` | Task mới thuộc top 5% | PM |
  | `[Đã xử lý]` | PM đã ghi action lên Jira | Assignee |

- FR-S5. Bản tổng hợp gồm: 4 chỉ số (tiến độ sprint so với kỳ vọng, số task nguy cơ trễ, bị block, mới) và **tối đa 5** task cần xử lý nhất. Phần còn lại xem trên web.
- FR-S6. **Chống báo dồn dập** [Đề xuất BA]:
  - một task chỉ được báo lại khi tăng bậc;
  - gộp các cảnh báo cùng loại trong vòng 15 phút;
  - không gửi ngoài giờ làm việc (cấu hình được), tin bị hoãn sẽ gộp vào lượt gửi kế tiếp;
  - có giới hạn số tin mỗi giờ.
- FR-S7. Lớp gửi thông báo được trừu tượng hoá theo "kênh" để thêm Teams, email… về sau.

### 6.9 Dashboard [Chốt: bố cục A "Hộp việc cần xử lý", cần tối ưu UI/UX]
Mockup tham khảo: `.superpowers/brainstorm/*/content/dashboard-a-v2.html`.

- FR-D1. **Thanh trên:** chọn dự án, chọn sprint (mặc định sprint đang active, hiển thị số ngày còn lại), thời điểm cập nhật và đồng bộ Jira gần nhất, kênh Slack.
- FR-D2. **Bốn ô chỉ số, bấm được để lọc danh sách:**
  1. Tiến độ sprint: % hoàn thành so với % kỳ vọng (kỳ vọng tuyến tính theo thời gian sprint [Đề xuất BA]), có vạch kỳ vọng và dự báo cuối sprint. Đơn vị là story points nếu dự án dùng, ngược lại đếm task.
  2. Nguy cơ trễ (số task Cao + TB, kèm số task tăng bậc từ hôm qua).
  3. Bị block (kèm số task block > 3 ngày).
  4. Task mới 24h (kèm số task quan trọng).
- FR-D3. **Danh sách "Cần xử lý hôm nay"** là điểm nhìn chính. Mỗi dòng có:
  - vạch màu mức rủi ro;
  - key và tóm tắt;
  - một dòng lý do ngắn;
  - các tag: loại hạn, ★ top 5%, bị block, tăng bậc, assignee;
  - % khả năng trễ bên phải;
  - số đề xuất.

  Có tab lọc: Tất cả / Nguy cơ / Bị block / Mới / Đã xử lý.
- FR-D4. **Panel chi tiết bên phải:** link Jira, các tag, mục "Vì sao" (các factor kèm số liệu và dòng nguồn dữ liệu), mục đề xuất (FR-A1), nút Bỏ qua và nút Xác nhận, ghi chú về việc ghi bằng tài khoản PM và kiểm tra xung đột. Có thêm biểu đồ nhỏ xu hướng điểm rủi ro của task theo thời gian [Đề xuất BA].
- FR-D5. **Trang phụ "Tổng quan"** (bố cục B, độ ưu tiên thấp hơn): burndown/burnup sprint, phân bố rủi ro, ma trận rủi ro × quan trọng, tải theo assignee.
- FR-D6. **Trang "Hiệu quả"** (cho Admin và PM): các chỉ số ở mục 11.
- FR-D7. **Nguyên tắc UI/UX** [Chốt: cần tối ưu, chi tiết là Đề xuất BA]:
  - một điểm nhìn chính;
  - màu chỉ dùng cho mức rủi ro;
  - mọi con số rủi ro đi kèm loại hạn;
  - giải thích ngắn trên dòng, chi tiết ở panel;
  - thao tác chính tối đa 2 click (chọn task → xác nhận);
  - giao diện tiếng Việt;
  - giờ theo Asia/Ho_Chi_Minh;
  - đạt WCAG 2.1 AA về tương phản và điều hướng bàn phím.

### 6.10 Quản trị
- FR-M1. Quản lý người dùng, vai trò và phân quyền theo dự án.
- FR-M2. Cấu hình theo dự án: theo dõi hay không, ánh xạ nhóm trạng thái (To Do / In Progress / Done) nếu workflow khác chuẩn, ngưỡng tín hiệu, giờ làm việc, PM phụ trách.
- FR-M3. Quản lý mô hình: xem bundle đang chạy (phiên bản, metric test từ `manifest.json`), bật hoặc tắt chạy bóng, chuyển bộ chấm chính thức, đặt ngưỡng Cao/TB.
- FR-M4. Xem trạng thái hệ thống: webhook gần nhất, lượt quét bù, lượt chạy pipeline, lỗi Jira, Slack và LLM.

## 7. Yêu cầu phi chức năng [Đề xuất BA trừ khi ghi khác]
- **Triển khai:** toàn bộ hệ thống (web, kho dữ liệu, mô hình, LLM) chạy nội bộ, **dữ liệu Jira không rời hạ tầng nội bộ** [Chốt về LLM; các phần còn lại suy ra từ đó]. Chỉ mở endpoint webhook ra ngoài.
- **Độ trễ:** cảnh báo theo sự kiện (K2, K3) đến Slack trong ≤ 5 phút kể từ thay đổi trên Jira (mục tiêu, sẽ kiểm chứng ở mục 14). Bản tổng hợp gửi đúng giờ ±5 phút.
- **Tài nguyên GPU dùng chung** cho LLM, embedding và replay criticality: xếp lịch để replay chạy trước giờ tổng hợp, LLM theo sự kiện có hàng đợi.
- **Bảo mật:**
  - token Jira, Slack và OAuth được mã hoá khi lưu;
  - kiểm tra chữ ký hoặc secret của webhook;
  - phân quyền theo vai trò và dự án ở phía server;
  - nhật ký thao tác ghi Jira không xoá được bởi người dùng thường.
- **Độ tin cậy:** idempotent khi nhận lặp webhook. Đồng bộ bù khi khởi động và trước lô sáng giúp dữ liệu tự khớp lại sau thời gian app hoặc tunnel tắt. Rủi ro chấp nhận: webhook bị lỡ khi app đang chạy thì chỉ được bắt lại ở lượt bù kế tiếp. LLM lỗi không chặn cảnh báo.
- **Khả năng truy vết:** mỗi điểm số và đề xuất truy được về phiên bản mô hình, prompt và dữ liệu đầu vào.
- **Quy mô [Chốt: demo trên một vài dự án]:** site demo có 2–3 dự án, ≤ 10 người dùng (giới hạn gói Jira free), vài trăm issue. Nền lịch sử công khai là 2,68 triệu issue (FR-DM1), vì vậy thời gian chấm chủ yếu phụ thuộc vào nền này chứ không phải vào số issue demo.
- **Phần cứng [Chốt: như README]:** một máy với RTX 4060 Ti 16 GB, RAM 30 GB, 16 nhân. Các tác vụ GPU (LLM, embedding, replay criticality) **chạy tuần tự qua một hàng đợi GPU**. Trước lượt replay criticality, giải phóng model LLM khỏi VRAM. RAM 30 GB phải đủ để nạp nền DuckDB khi chấm; đội xây dựng đo và xử lý nếu không đủ (mục 14).

## 8. Kiến trúc đề xuất [Đề xuất BA; đội xây dựng được thay đổi]

```
Jira Cloud ──webhook──▶ [Ingress HTTPS] ──▶ Ingest service ──▶ Kho dữ liệu nội bộ
     ▲   ◀──quét bù JQL (10')──┘                                 │ (issue, changelog, sprint,
     │                                                           │  version, link, snapshot điểm,
     │                                                           │  đề xuất, nhật ký action)
     │                                                           ▼
     │                                        Export DuckDB (schema early_risk_detection)
     │                                                           │
     │                    Scoring workers: delay_t0 | criticality_t0 | rules_dynamic | (delay_anytime)
     │                                                           │
     │                              LLM worker (Ollama self-host, JSON schema)
     │                                                           │
     └──ghi bằng OAuth của PM── Web app (API + UI dashboard) ──▶ Notifier ──▶ Slack (1 kênh)
```

- Backend dùng Python, để gọi trực tiếp thư viện `early_risk_detection` mà không phải bọc thêm một dịch vụ khác.
- Hàng đợi công việc cho chấm theo sự kiện, LLM và gửi Slack.
- Lịch (scheduler) cho lượt lô, tổng hợp và quét bù.
- Công nghệ cụ thể (framework web, CSDL, hàng đợi, frontend) để đội xây dựng chọn.

## 9. Khảo sát dữ liệu: due date, sprint, lịch sử
Quét toàn bộ 2.686.282 issue trong MongoDB gốc của The Public Jira Dataset (16 instance, 1.276 project). Môi trường thật được giả định tương ứng [Chốt].

| Trường | % issue có giá trị | Số project dùng đều (≥ 20% issue) |
|---|---|---|
| Due date | 0,49% | 15 / 1.276 |
| Sprint (có endDate) | 6,1% (≈ 163 nghìn) | 143 / 1.276 |
| Fix Version có releaseDate | 37,6% | phổ biến nhất |

- Sprint tập trung ở MongoDB (37%), Hyperledger (28%), IntelDAOS (24%), RedHat (17%). Mojang, Sakai, JFrog và SecondLife không dùng sprint.
- Trong các issue có sprint và đã xong: **43,7% xong sau endDate của sprint đầu tiên**, và **31,5% thuộc nhiều hơn 1 sprint** (bị trôi sprint).
- Trong các issue có due date và đã xong: 60,3% xong sau due date. Mẫu nhỏ, khoảng 13 nghìn issue.
- Lịch sử: phần lớn instance có 5–20 năm (65–470 tháng).
- Changelog: khoảng 13 triệu sự kiện status, assignee, priority, due date, Sprint, Fix Version, resolution; trung vị 4 sự kiện mỗi issue.
- DuckDB hiện tại **không có** due date, sprint (kèm ngày) và releaseDate. Cần mở rộng ETL (FR-J5).

Hệ quả:
1. Không thể dùng due date làm định nghĩa duy nhất của "hạn", nên có thứ tự ưu tiên ở mục 4.1.
2. Task thường được gán sprint **sau** khi tạo, nên mô hình T0 không thể biết sprint. Đây là lý do cần mô hình ở mục 10.

## 9b. Dữ liệu demo và chế độ mô phỏng [Đề xuất BA]
**Vấn đề:**
- Dự án demo trên Jira free vừa tạo thì không có lịch sử. Lịch sử cũng không thể làm giả: Jira không cho ghi lùi thời gian của changelog.
- Mô hình cần lịch sử: đặc trưng tải và lịch sử dự án của model delay, replay sự kiện của model criticality.
- Chỉ số "giảm task trễ sau 3 tháng" không đo được trong thời gian demo.

**Giải pháp gồm 3 phần:**
- **FR-DM1. Nền lịch sử:** khi chấm, dữ liệu site demo được **nối thêm vào DuckDB của tập dữ liệu công khai** như một instance mới. Nhờ vậy mô hình có quần thể issue đã giải quyết (cho cổng ngữ nghĩa) và dòng sự kiện để replay. Task demo chỉ được so sánh "tải" và "lịch sử" trong chính instance demo.
- **FR-DM2. Script gieo dữ liệu demo (seed):** tạo trên Jira demo vài dự án (ví dụ 2–3 dự án, khoảng 50–150 task mỗi dự án). Dữ liệu gồm:
  - sprint (một sprint đang chạy, các sprint tương lai);
  - Fix Version có ngày release;
  - một số task có due date;
  - story points;
  - link block;
  - người dùng (gói free tối đa 10 người);
  - nội dung **song ngữ**: lấy và chỉnh từ issue của tập công khai (tiếng Anh) cộng các task viết bằng tiếng Việt.

  Có thêm **kịch bản thao tác** (đổi status, gán lại, block, reopen, dời sprint) để chạy trực tiếp lúc demo và kích hoạt K2, K3.
- **FR-DM3. Chế độ mô phỏng (replay):** chọn một dự án công khai có dùng sprint (ví dụ các dự án MongoDB hoặc RedHat ở mục 9), đặt "đồng hồ ảo" `as_of`. Web hiển thị dashboard, bản tổng hợp, các tín hiệu động và cảnh báo **như thể đang ở ngày đó**, và có thể tua theo ngày. Chế độ này phục vụ hai việc:
  1. demo kịch bản dài ngày (task trôi sprint, tăng bậc rủi ro);
  2. **đánh giá định lượng** (FR-V1), vì đã biết kết quả thực tế.

  Ở chế độ mô phỏng, các action **không ghi lên Jira**, chỉ ghi nhật ký. Cảnh báo Slack gửi kèm nhãn `[MÔ PHỎNG]`.

## 10. Hạng mục song song: mô hình chấm điểm tại thời điểm bất kỳ (`delay_anytime`)
Không thuộc phạm vi xây web, nhưng web phụ thuộc vào **giao diện** của nó (mục 6.3).

- **Câu hỏi:** tại thời điểm t, task đang mở có xong trước hạn hiện hành không? Hạn ưu tiên là sprint hiện tại; hạn phụ là release; due date không đủ dữ liệu để làm nhãn.
- **Mẫu:** ảnh chụp (snapshot) của task tại mỗi sự kiện changelog, hoặc mỗi ngày khi task còn mở. Lấy mẫu con để cân bằng giữa các task dài và ngắn.
- **Nhãn chính:** xong trước `endDate` của sprint đang chứa task tại t. Dữ liệu: khoảng 163 nghìn issue có sprint trên 143 project. **Nhãn phụ:** xong trước `releaseDate` của Fix Version, khoảng 1 triệu issue. Có thể thêm nhãn hồi quy là số ngày còn lại.
- **Đặc trưng:** các đặc trưng T0 hiện có, cộng các đặc trưng tại t: tuổi task, thời gian ở trạng thái hiện tại, số lần reopen, đổi assignee, đổi hạn, % sprint đã trôi qua, số ngày còn lại tới hạn, số sprint đã trôi qua, trạng thái của các task chặn, tải của assignee tại t. **Chỉ dùng sự kiện trước t**, đúng quy tắc chống rò rỉ trong `CONTRIBUTING.md`.
- **Lưu ý dữ liệu:** dataset chỉ lưu danh sách sprint cuối cùng của issue. Thời điểm vào hoặc ra từng sprint phải dựng lại từ changelog `Sprint`, và cần kiểm chứng việc dựng lại này.
- **Đánh giá:** chia theo thời gian (giống repo), đo PR-AUC, precision và recall ở ngưỡng Cao, và độ hiệu chỉnh (calibration). So sánh với tổ hợp "T0 + luật" của giai đoạn 1 trên cùng tập.
- **Tiêu chí bật trên web:** chạy bóng ≥ 2 sprint trên dữ liệu thật, và precision ở mức Cao tốt hơn tổ hợp "T0 + luật" với recall không thấp hơn [Đề xuất BA].

## 11. Chỉ số thành công [Chốt mục tiêu: giảm task trễ hạn, bảo đảm tiến độ; chỉ số là Đề xuất BA]

### 11.1 Tiêu chí nghiệm thu bản demo
1. **Đầu cuối, thời gian thực:** tạo hoặc sửa task trên Jira demo → trong ≤ 5 phút có cảnh báo đúng prefix trong kênh Slack, và dashboard cập nhật.
2. **Bản tổng hợp** được gửi đúng giờ, có đủ 4 chỉ số và tối đa 5 task.
3. **Action:** PM sửa đề xuất, xác nhận, thay đổi xuất hiện trên Jira dưới tên PM. Kịch bản xung đột (FR-A4) được chặn đúng.
4. **Song ngữ:** giải thích và đề xuất hợp lý cho cả task tiếng Anh lẫn tiếng Việt. Không có khẳng định nào không trỏ về factor (kiểm tra trên một mẫu).
5. **Mô phỏng (FR-DM3):** báo cáo precision và recall ở mức Cao, và % task trễ được báo trước ≥ N ngày, cho từng bộ chấm (T0, luật, tổ hợp). Có thêm "mô phỏng tác động": nếu PM xử lý mọi cảnh báo Cao thì bao nhiêu task trễ có cơ hội được can thiệp sớm.

### 11.2 Chỉ số khi triển khai thật
Mốc so sánh: 3–6 tháng lịch sử Jira trước khi triển khai, tự tính sau bootstrap. Đánh giá sau 3 tháng.

**Chỉ số kết quả:**
- Tỉ lệ task trễ hạn (theo mục 4.1) giảm.
- Tỉ lệ task bị trôi sang sprint sau giảm (mốc trong dữ liệu nghiên cứu là khoảng 31%).
- Tỉ lệ hoàn thành cam kết sprint tăng; độ lệch giữa ngày release kế hoạch và thực tế giảm.

**Chỉ số dẫn dắt:**
- % cảnh báo được PM mở hoặc xử lý.
- % đề xuất LLM được chấp nhận nguyên văn, chấp nhận có sửa, hoặc bị bỏ qua.
- Thời gian trung vị từ cảnh báo đến action.

**Chất lượng phát hiện:**
- Precision: trong các task bị báo Cao, bao nhiêu % thực sự trễ.
- Recall: trong các task trễ, bao nhiêu % đã được báo trước ít nhất N ngày.

**Lưu ý:** khi PM can thiệp, task có thể không còn trễ, nên precision đo được trên thực tế sẽ bị **đánh giá thấp**. Báo cáo cần tách nhóm task "đã có action" và "không có action".

## 12. Lộ trình [Đề xuất BA]

| Giai đoạn | Nội dung |
|---|---|
| **1a — Nền tảng** | Kết nối Jira (bootstrap, webhook qua tunnel, đồng bộ bù khi khởi động), ETL mở rộng + nối nền lịch sử công khai, script seed dữ liệu demo, scoring T0 + luật theo lô, chế độ mô phỏng + đánh giá (mục 6.4b, 9b), dashboard A (chỉ đọc), bản tổng hợp Slack. |
| **1b — Hành động** | LLM giải thích và đề xuất, panel xác nhận, ghi Jira qua OAuth, cảnh báo theo sự kiện, chống báo dồn dập, trang Hiệu quả. |
| **2** | Bật `delay_anytime` (chạy bóng, rồi chính thức), trang Tổng quan đầy đủ, (tuỳ chọn) thao tác trong Slack, ánh xạ Slack để @ thật, thêm kênh thông báo khác. |

Hạng mục mô hình (mục 10) chạy song song từ đầu.

## 13. Ràng buộc và rủi ro

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Mô hình huấn luyện trên dữ liệu công khai, khác Jira công ty (lệch miền dữ liệu) | Điểm kém chính xác | Chạy bóng, đo precision/recall thực tế, chỉnh ngưỡng theo dự án, huấn luyện lại bằng dữ liệu công ty khi đủ lịch sử |
| Model delay T0 có precision thấp (≈ 0,30) | Báo nhiều, PM bỏ qua | `p_delay` không tự kích hoạt mức Cao; ưu tiên tín hiệu động; giới hạn tin |
| LLM self-host yếu, bịa lý do | Mất niềm tin | JSON schema, danh mục action đóng, bắt buộc trích dẫn factor, loại đầu ra sai |
| Webhook cần endpoint công khai trong khi hệ thống chạy nội bộ | Không nhận được sự kiện | Ingress chỉ mở một endpoint + quét bù JQL |
| Replay criticality tốn GPU, phải replay toàn bộ dòng sự kiện | Chậm, tranh chấp GPU với LLM | Chạy theo lô trước giờ tổng hợp; task mới nhận điểm criticality ở lượt lô sau |
| Dự án demo không có lịch sử; nội dung tiếng Việt nằm ngoài miền dữ liệu huấn luyện | Điểm mô hình trên task demo kém ý nghĩa | Nền lịch sử công khai (FR-DM1), đánh giá bằng mô phỏng, luật động làm trụ chính, embedding đa ngôn ngữ ở hạng mục mô hình |
| URL tunnel thay đổi khi khởi động lại; tunnel tắt | Mất webhook | Domain tĩnh của tunnel; đồng bộ bù khi khởi động; trang Settings hiển thị thời điểm nhận webhook cuối |
| Jira Cloud ẩn email | Không @ thật trên Slack được | Hiển thị tên Jira [Chốt]; ánh xạ ở giai đoạn 2 |
| Workflow và trạng thái khác nhau giữa các dự án | Luật "To Do / In Progress" sai | Admin ánh xạ nhóm trạng thái theo dự án (FR-M2), mặc định dùng `statusCategory` của Jira |

## 14. Phần để đội xây dựng quyết định
- Framework web, CSDL, hàng đợi, frontend, cách đóng gói và triển khai.
- Chọn model LLM self-host cụ thể (cân đối chất lượng tiếng Việt, khả năng tuân thủ JSON và VRAM khi dùng chung GPU với replay).
- **Đo thời gian chấm theo sự kiện:** `DelayRiskScorer.score(issue_keys=[...])` vẫn nạp toàn bộ DataFrame và tính đặc trưng cổng ngữ nghĩa trên toàn bộ dữ liệu. Cần đo trên quy mô thật. Nếu vượt mục tiêu 5 phút thì cache đặc trưng hoặc dùng bản chấm gia tăng (incremental) trong thư viện.
- Có chạy criticality nhiều lần mỗi ngày hay không, dựa trên thời gian replay đo được.
- Cách tính dự báo tiến độ cuối sprint trên ô chỉ số (tuyến tính hay dựa trên điểm rủi ro).
- Nội dung prompt LLM và các mẫu tin Slack (giữ đúng định dạng FR-S2).

## 15. Câu hỏi còn mở
Không còn câu hỏi nào chặn việc lập kế hoạch cho bản demo. Hai điểm sau đã được BA tự quyết, có thể đổi khi triển khai thật:
- Story points: dữ liệu seed có story points. Đơn vị tiến độ là story points nếu dự án dùng, ngược lại đếm task (FR-D2).
- Giờ làm việc và giờ tổng hợp: một cấu hình chung cho site demo, mặc định 8:00, thứ 2 đến thứ 6, Asia/Ho_Chi_Minh.
