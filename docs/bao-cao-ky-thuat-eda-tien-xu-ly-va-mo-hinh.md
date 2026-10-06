# Báo cáo kỹ thuật: Khai phá dữ liệu, tiền xử lý và giải pháp mô hình — Phát hiện điểm nghẽn trên dữ liệu Jira bằng Temporal Graph Network

**Ngày:** 2026-10-05
**Phạm vi:** Tài liệu kỹ thuật mô tả đầy đủ (1) khai phá dữ liệu (EDA) trên The Public Jira Dataset, (2) các bước và thuật toán tiền xử lý từ document MongoDB đến định dạng đầu vào của TGN, (3) thuật toán xây dựng nhãn điểm nghẽn, (4) giải pháp mô hình TGN: kiến trúc, huấn luyện, đánh giá.
**Đối tượng đọc:** kỹ sư dữ liệu / ML tiếp nhận hoặc tái lập pipeline.
**Tài liệu liên quan:**
- `docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md` — đề xuất gốc.
- `docs/bao-cao-tap-du-lieu-va-tien-xu-ly.md` — mô tả dataset và pipeline v1–v3.
- `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` — codebook gắn nhãn bằng LLM.
- `docs/bao-cao-xu-ly-du-lieu-va-phuong-an-huan-luyen.md` — hiện trạng và lộ trình.
- `jira_adapter/README.md` — tài liệu gói mã nguồn.

**Nguồn số liệu:** mọi con số trong §3 được đo trực tiếp trên MongoDB `JiraReposAnon` ngày 2026-10-05 bằng chính các hàm của `jira_adapter` (script EDA mở rộng chạy lại được, xem §9). Kết quả huấn luyện lấy từ các lần chạy P0 (2026-10-01 → 2026-10-04).

---

## Mục lục

1. [Tóm tắt](#1-tóm-tắt)
2. [Bài toán và ký hiệu](#2-bài-toán-và-ký-hiệu)
3. [Khai phá dữ liệu (EDA)](#3-khai-phá-dữ-liệu-eda)
4. [Tiền xử lý dữ liệu](#4-tiền-xử-lý-dữ-liệu)
5. [Xây dựng nhãn điểm nghẽn](#5-xây-dựng-nhãn-điểm-nghẽn)
6. [Giải pháp mô hình](#6-giải-pháp-mô-hình)
7. [Kết quả hiện có](#7-kết-quả-hiện-có)
8. [Rủi ro, giới hạn và lộ trình](#8-rủi-ro-giới-hạn-và-lộ-trình)
9. [Tái lập](#9-tái-lập)
10. [Phụ lục: bản đồ mã nguồn](#10-phụ-lục-bản-đồ-mã-nguồn)

---

## 1. Tóm tắt

| Hạng mục | Nội dung |
|---|---|
| Mục tiêu | Phát hiện (và cảnh báo sớm) issue trở thành **điểm nghẽn** trong dự án phần mềm, từ dòng sự kiện Jira |
| Dữ liệu | The Public Jira Dataset (MSR 2022, Zenodo 15719919, CC-BY-4.0): 16 instance, 2,69 triệu issue. Dùng **JFrog** (15.535 issue) để thử nghiệm và **Spring** (69.156 issue) làm instance chính |
| Biểu diễn | Đồ thị thời gian liên tục (CTDG): nút = issue, cạnh = sự kiện có mốc thời gian (`status`, `assignee`, `priority`, `link`, `comment`) với 24 chiều đặc trưng |
| Mô hình | Temporal Graph Network (Rossi et al., 2020): memory GRU + temporal graph attention 2 lớp. Huấn luyện 2 giai đoạn: tự giám sát (dự đoán sự kiện) → phát hiện điểm nghẽn |
| Nhãn | Nhãn cũ (v3: "có link Block/Depend") **rò rỉ qua feature** → bị loại. Nhãn mới theo **episode** do LLM trích bằng chứng + rule code xác nhận + người chấm kiểm định |
| Kết quả đo được | Tự giám sát: AUC 0,998 (JFrog), 0,9997 (Spring). Phát hiện điểm nghẽn với v3: AUC 0,835 → **0,620** khi bỏ feature rò rỉ → **0,484** khi bỏ thêm sự kiện link (ngẫu nhiên) |
| Trạng thái | Pipeline dữ liệu chạy end-to-end; pipeline nhãn LLM chạy được (20/300 issue pilot); huấn luyện với nhãn mới chờ kiểm định nhãn |

**Các phát hiện EDA quyết định thiết kế:**

1. **Đồ thị gần như suy biến:** 96–97% sự kiện là self-loop (cạnh từ issue về chính nó). Chỉ sự kiện `link` nối hai issue khác nhau. Lớp attention trên hàng xóm vì vậy chủ yếu "nhìn" lại lịch sử của chính nút.
2. **Issue đang mở phần lớn là backlog bỏ quên:** trung vị thời gian không hoạt động của issue đang mở là 622 ngày (JFrog) và 2.396 ngày (Spring). Phải loại backlog khỏi tập đánh giá.
3. **Đóng hàng loạt rất phổ biến:** 52% issue JFrog và 38% issue Spring bị đóng trong các đợt ≥20 issue cùng người cùng phút. Thời gian ứ đọng trước các đợt này không phản ánh dòng chảy công việc.
4. **Phân phối thời gian lưu trú đuôi rất dày:** trạng thái "đang làm" có trung vị ~1 ngày nhưng p99 ~140 ngày (JFrog). Ngưỡng ứ đọng phải tính theo **percentile của từng trạng thái** chứ không dùng ngưỡng tuyệt đối.
5. **Tín hiệu phụ thuộc hiếm:** chỉ 3–4% issue có link Block/Depend; chỉ 0,12% (JFrog) / 0,29% (Spring) có issue phụ thuộc **còn mở**. Lớp dương sẽ rất hiếm.
6. **Hai lỗi mới phát hiện khi làm EDA này:** (a) ở Spring, trạng thái tên `Done` mang `statusCategory = indeterminate` (3.145 issue) → bị tính nhầm là "đang làm"; (b) **một nửa số link bị bỏ khi sinh sự kiện**: trong dump mỗi mục link chỉ có một trong hai trường `outwardIssue`/`inwardIssue`, nhưng `events.py` giả định có cả hai → mọi mục inward bị loại và cột chiều link luôn bằng 0.

---

## 2. Bài toán và ký hiệu

### 2.1. Định nghĩa điểm nghẽn

Một issue là **điểm nghẽn** khi nó **cản dòng chảy công việc** và **sự chậm trễ lan sang đối tượng khác** (issue khác, release, khách hàng). Chậm mà không ai phải chờ thì không phải điểm nghẽn.

```
Bottleneck = (F1 ∨ F2 ∨ F3 ∨ F4) ∧ (I1 ∨ I2 ∨ I3)
```

| Mã | Tiêu chí | Tín hiệu Jira |
|---|---|---|
| F1 | Ứ đọng ở trạng thái đang làm ≥ p90 của dự án | changelog status |
| F2 | Chờ đợi rõ ràng ("waiting for", "blocked by", trạng thái *Waiting…*) | comment, status |
| F3 | Vòng lặp: reopen, trạng thái qua lại, ≥3 lần đổi assignee | changelog |
| F4 | Thiếu nguồn lực: ưu tiên cao nhưng chưa ai nhận | assignee, priority |
| I1 | Có issue khác **đang mở** phụ thuộc vào nó | link Block/Depend |
| I2 | Nằm trên đường găng release (có fixVersion, fixVersion bị đẩy lùi) | changelog Fix Version |
| I3 | Bị leo thang: priority bị nâng, nhiều watcher/vote | changelog, fields |

Các ngoại lệ (E1–E9: backlog, epic, hoãn có chủ đích, đóng Duplicate/Won't Fix, spike, artifact dữ liệu, …) được xếp âm tính. Chi tiết: `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` §2.

### 2.2. Biểu diễn đồ thị thời gian

Dữ liệu được mô hình hóa thành **đồ thị động thời gian liên tục** (continuous-time dynamic graph):

- Tập nút `V` = các issue của một instance (`|V|` = 12.165 với JFrog, 67.691 với Spring).
- Dòng sự kiện có thứ tự `E = {e_k = (u_k, v_k, t_k, x_k)}`, với `t_1 ≤ t_2 ≤ … `, `u_k, v_k ∈ V`, `x_k ∈ ℝ^24` là đặc trưng sự kiện.
- Mỗi nút có đặc trưng tĩnh `f_i ∈ ℝ^64`.

### 2.3. Các bài toán

| Mã | Phát biểu | Dạng |
|---|---|---|
| **T1-D** (chính) | Cho lịch sử `{e_k : t_k ≤ t}`, dự đoán `y_i(t) = 1` nếu tại `t` issue `i` đang ở trong một episode điểm nghẽn (vai trò `root`) | Phân loại nhị phân nút tại thời điểm `t` |
| T1-E | `y_i(t) = 1` nếu một episode của `i` **bắt đầu** trong `(t, t + Δt]`, `Δt ∈ {7, 14, 30}` ngày | Cảnh báo sớm |
| T2 | Dự đoán sự kiện tiếp theo `(u, v, t)` | Dự đoán liên kết tự giám sát, dùng để tiền huấn luyện |

**Nguyên tắc chống rò rỉ:** nhãn được phép dùng thông tin hồi cứu (toàn bộ lịch sử issue), nhưng mọi feature tại thời điểm `t` chỉ được dùng thông tin có trước `t`.

---

## 3. Khai phá dữ liệu (EDA)

### 3.1. Phương pháp

| Bước | Cách làm |
|---|---|
| Nguồn | MongoDB local, DB `JiraReposAnon`, mỗi instance là một collection, mỗi document là một issue |
| Chuẩn hóa trước khi đo | Dùng `normalize_doc()` để mọi số liệu đo trên cùng shape với pipeline (§4.2) |
| Phân loại trạng thái | Mỗi tên trạng thái được gán `new` / `indeterminate` (đang làm) / `done` theo **đa số** `statusCategory.key` trên các issue đang ở trạng thái đó; tên chưa gặp thì đoán theo tiền tố (`open`, `backlog` → new; `done`, `closed`, `resolved` → done) |
| Thời gian lưu trú (dwell) | Chia đời issue thành các đoạn `[start, end)` theo changelog status; chỉ lấy đoạn **đã kết thúc** và **chưa done** |
| Thống kê | Trung vị, p75, p90, p99, max — vì hầu hết phân phối lệch phải rất mạnh, trung bình không đại diện |
| Thời điểm cuối dữ liệu | `data_end` = mốc thời gian lớn nhất trong changelog/`created` của instance (JFrog: 2022-01-04) |

Instance phân tích: **JFrog** (thử nghiệm, nhỏ, có changelog `Link` có timestamp) và **Spring** (quy trình đầy đủ nhất, 89,8% issue có assignee). Mojang được đo ở mức tổng quan, không dùng làm instance chính vì là bug tracker công khai (0,03% issue có Block/Depend, 1,4% có assignee).

### 3.2. Quy mô và phân bố thời gian

| Chỉ số | JFrog | Spring |
|---|---|---|
| Issue | 15.535 | 69.156 |
| Dự án | 10 (RTFACT chiếm 12.158) | 81 |
| Khoảng thời gian | 2006-10 → 2022-01 | 2003-11 → 2021-12 |
| Sự kiện (sau tiền xử lý) | 55.666 | 372.553 |
| Năm có nhiều issue tạo mới nhất | 2020 (2.232) | 2014 (6.296) |

**Số issue tạo mới theo năm:**

| Năm | 2007 | 2009 | 2011 | 2013 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| JFrog | 276 | 536 | 582 | 691 | 1.290 | 1.561 | 1.429 | 1.530 | 1.790 | 2.232 | 1.095 |
| Spring | 3.250 | 4.650 | 6.042 | 5.969 | 5.744 | 3.871 | 3.748 | 3.682 | 2.015 | 2.212 | 24 |

**Nhận xét:**
- Hai instance có xu hướng ngược nhau: JFrog tăng dần đến 2020, Spring đạt đỉnh 2010–2015 rồi giảm. Vì loader chia train/val/test theo quantile thời gian của **sự kiện**, mốc chia rơi vào 2019-12-10 / 2021-01-06 (JFrog) và 2016-06-16 / 2019-01-14 (Spring).
- JFrog có 9.065 sự kiện năm 2021 (gần gấp đôi 2020) dù số issue mới giảm: phần lớn là sự kiện đóng hàng loạt cuối đời dữ liệu (§3.9). Điều này làm tập test của JFrog chứa nhiều sự kiện "dọn dẹp" hơn tập train.
- Spring có 26 sự kiện năm 1970: ngày placeholder `1969-12-31` đã bị kẹp về epoch 0 (§4.4).

### 3.3. Thuộc tính issue

**Loại issue và theme** (theme theo bảng phân tích chủ đề của tác giả dataset):

| Theme | JFrog | Spring |
|---|---|---|
| Maintenance (Bug, Defect…) | 8.254 (53%) | 27.118 (39%) |
| Requirements (Improvement, New Feature, Story, Epic) | 5.007 (32%) | 30.203 (44%) |
| Development (Task, Sub-task, Refactoring) | 1.267 (8%) | 10.946 (16%) |
| User Support | 0 | 118 |
| Other | 1.007 (6%) — chủ yếu `RCA(sub)` 812 | 771 |

**Priority** (giá trị thô):

| JFrog | Số issue | Spring | Số issue |
|---|---|---|---|
| 4 - Normal | 11.231 (72%) | Minor | 39.374 (57%) |
| 3 - High | 2.509 (16%) | Major | 23.979 (35%) |
| 2 - Critical | 1.145 (7%) | Trivial | 2.157 |
| 1 - Blocker | 498 (3%) | Critical | 2.128 |
| (null) | 107 | Blocker | 918 |
| 5 - Minor, 6 - Trivial | 45 | (null) | 600 |

Hệ quả: tên priority **khác nhau giữa các instance** (JFrog có tiền tố số `"4 - Normal"`). Phiên bản đầu của bảng chuẩn hóa không xử lý tiền tố, khiến toàn bộ JFrog bị đọc thành Normal (§4.3).

**Resolution:**

| JFrog | | Spring | |
|---|---|---|---|
| Done | 6.695 | Complete | 25.008 |
| (chưa có) | 5.306 | Fixed | 20.910 |
| **Deferred** | **2.442** | (chưa có) | 7.592 |
| Duplicate | 533 | **Won't Fix** | **6.247** |
| Not a Bug | 432 | Duplicate | 2.737 |
| Cannot Reproduce | 113 | Invalid | 2.222 |

Hệ quả: 16% issue JFrog đóng với `Deferred` và 9% issue Spring đóng với `Won't Fix`. Đây chính là các ca "mở lâu nhưng không phải nghẽn" (ngoại lệ E4, E5) — nếu dùng thời gian mở làm nhãn sẽ sinh rất nhiều dương tính giả.

### 3.4. Vòng đời và mức độ hoạt động

| Chỉ số (ngày) | | p50 | p75 | p90 | p99 |
|---|---|---|---|---|---|
| Vòng đời issue đã đóng (`resolutiondate − created`) | JFrog | 46 | 569 | 2.207 | 3.915 |
| | Spring | 11 | 90 | 659 | 2.825 |
| Thời gian không hoạt động của issue **đang mở** (tính đến `data_end`) | JFrog | 622 | 1.176 | 1.941 | 3.772 |
| | Spring | 2.396 | 3.027 | 4.069 | 5.246 |
| Khoảng cách giữa 2 sự kiện liên tiếp của cùng issue | JFrog | 3,0 | 64 | 1.660 | 4.500 |
| | Spring | 0,29 | 35 | 1.161 | 3.868 |

| Chỉ số (số lượng / issue) | | trung bình | p50 | p90 | p99 | max |
|---|---|---|---|---|---|---|
| Sự kiện | JFrog | 3,58 | 3 | 8 | 17 | 62 |
| | Spring | 5,39 | 4 | 10 | 20 | 102 |
| Comment | JFrog | 0,85 | 0 | 2 | 9,7 | 44 |
| | Spring | 2,69 | 2 | 6 | 15 | 97 |

**Nhận xét:**
- Khoảng cách giữa các sự kiện **lưỡng cực**: phần lớn sự kiện cách nhau vài giờ đến vài ngày (làm việc liên tục), nhưng 10% khoảng cách dài hơn 3–4 năm (issue bị bỏ quên rồi được dọn). Time encoder của TGN phải mã hóa được dải từ giây đến hàng nghìn ngày → dùng bộ mã hóa cosine đa tần số (§6.2.4), tần số trải từ `1` đến `10⁻⁹`.
- Issue đang mở gần như **không còn hoạt động**: một nửa số issue mở của Spring đã im lặng hơn 6,5 năm. Nếu đánh giá mô hình trên mọi issue đang mở, đa số điểm đánh giá sẽ là backlog chết → phải lọc (tập truy vấn `Q(t)`, §6.4.2).
- JFrog rất ít comment (trung vị 0) → tín hiệu văn bản F2 gần như chỉ có ở Spring.

### 3.5. Quy trình trạng thái

**Phân loại trạng thái hiện tại:**

| | new | indeterminate (đang làm) | done |
|---|---|---|---|
| JFrog | 5.081 (33%) | **86 (0,6%)** | 10.368 (67%) |
| Spring | 6.994 (10%) | 3.745 (5,4%)* | 58.417 (84%) |

\* Bao gồm 3.145 issue ở trạng thái tên `Done` nhưng mang `statusCategory = indeterminate` — xem §3.9.

**Chuyển trạng thái theo nhóm** (số lần chuyển):

| Chuyển | JFrog | Spring |
|---|---|---|
| new → done (đóng thẳng, không qua "đang làm") | 5.254 | **43.553** |
| new → indeterminate | 6.260 | 23.952 |
| indeterminate → done | 5.796 | 17.466 |
| indeterminate → indeterminate | 5.763 | 8.920 |
| done → done (đổi giữa các trạng thái kết thúc, vd. Resolved → Closed) | 6.569 | 28.866 |
| done → new / done → indeterminate (**reopen**) | 139 / 553 | 3.370 / 65 |
| indeterminate → new (trả về backlog) | 934 | 1.972 |

**Thời gian lưu trú (ngày), các trạng thái nhiều đoạn nhất:**

| Instance | Trạng thái | Số đoạn | p50 | p90 | p99 |
|---|---|---|---|---|---|
| JFrog | Open | 11.148 | 22,8 | 2.152 | 3.857 |
| | Pending QA | 5.901 | 2,1 | 21,8 | 85,9 |
| | In Progress | 3.209 | 0,9 | 17,9 | 142,8 |
| | QA in Progress | 1.549 | 0,1 | 4,3 | 23,0 |
| | Reopened | 1.325 | 0,7 | 31,8 | 2.241 |
| | Ready for Code Review | 700 | 3,9 | 27,0 | 393,0 |
| | Ready For Merge | 434 | 2,1 | 26,2 | 158,7 |
| Spring | Open | 59.206 | 5,9 | 510 | 2.735 |
| | In Progress | 19.932 | 0,15 | 11,9 | 205 |
| | To Do | 5.520 | 6,9 | 205 | 742 |
| | Reopened | 3.252 | 0,01 | 35,6 | 1.435 |
| | **Waiting for Feedback** | 2.329 | 4,4 | 476 | 2.407 |
| | **Waiting for Review** | 2.306 | 2,0 | 34,7 | 928 |
| | Investigating | 2.014 | 0,8 | 168 | 2.141 |

**Nhận xét:**
- **Đóng thẳng chiếm ưu thế ở Spring** (43.553 lần new → done so với 17.466 lần đi qua "đang làm"). Nhiều issue không có pha "đang làm" để đo ứ đọng → F1 chỉ áp dụng được cho một phần nhỏ issue.
- **JFrog có quy trình QA rõ** (Pending QA → QA in Progress), là nơi phát hiện các ca điểm nghẽn đầu tiên của pilot (BI-459 ứ ở Pending QA 177 ngày, xem §5.8).
- **Spring có trạng thái chờ tường minh** (`Waiting for Feedback`, `Waiting for Review`) — tín hiệu F2 lấy trực tiếp từ changelog, không cần đọc comment.
- Phân phối dwell khác nhau **hàng chục lần** giữa các trạng thái (p90 của QA in Progress là 4 ngày, của Waiting for Feedback là 476 ngày). Ngưỡng ứ đọng tuyệt đối (vd. "> 30 ngày") sẽ vô nghĩa → dùng percentile theo `(trạng thái, theme)` (thuật toán A8, §5.3).
- Reopen: 3,92% issue JFrog và 4,45% issue Spring bị mở lại ít nhất một lần.

### 3.6. Quan hệ giữa các issue (link)

| Chỉ số | JFrog | Spring |
|---|---|---|
| Link độc lập (≈ số lần xuất hiện / 2) | 2.125 | 11.046 |
| Link / issue: trung bình, p90, p99, max | 0,27 · 1 · 3 · 13 | 0,32 · 1 · 4 · 24 |
| % issue có ≥1 link | 21,0% | 20,5% |
| % issue có link Block/Depend | 3,01% | 4,04% |
| % issue có issue phụ thuộc **đang mở** (I1 hiện tại) | **0,12%** | **0,29%** |
| Loại link (sau chuẩn hóa) | Relate 1.822 · Duplicate 1.380 · Depend 538 · Trigger 410 · Incorporate 98 | Relate 13.966 · Duplicate 3.580 · Depend 3.565 · Supercede 981 |

**Nhận xét:**
- Không có link loại `Block` ở cả hai instance; quan hệ chặn đều được biểu diễn bằng `Depend`. Đây là nguyên nhân bug `has_block_link` luôn bằng 0 (§4.5).
- Link Block/Depend đã hiếm (3–4%), và đa số trỏ tới issue **đã đóng** → I1 "đang có người chờ" chỉ còn 0,1–0,3%. Lớp dương của nhãn điểm nghẽn sẽ hiếm hơn nhiều so với nhãn v3 (~3%).
- Jira API không trả thời điểm tạo link trong `issuelinks`. JFrog có thêm mục changelog `field = "Link"` có timestamp — dùng được để đặt sự kiện link đúng thời điểm.

### 3.7. Người phụ trách

| Chỉ số | JFrog | Spring |
|---|---|---|
| Số assignee | 184 | 260 |
| % issue có assignee | 60,9% | 89,8% |
| Tỉ trọng 10 người nhận nhiều nhất | 60,6% | 46,2% |
| Hệ số Gini của tải theo người | 0,838 | 0,820 |
| % issue đổi assignee ≥3 lần (F3) | 1,49% | 0,63% |

Tải công việc **tập trung rất mạnh** (Gini > 0,8): một nhóm nhỏ người xử lý phần lớn issue. Điều này ủng hộ hướng mở rộng sang đồ thị hai phía issue–người (§6.7, ablation), nơi nút người có thể mang trạng thái "quá tải". Định danh người đã được ẩn danh bằng UUID ổn định (`<<|author_name|uuid|>>`) nên vẫn dùng làm nút được, nhưng không biết vai trò/nhóm.

### 3.8. Comment và tín hiệu chờ đợi

- Regex chờ đợi (`waiting for|blocked by|pending review|need input|on hold|any update|awaiting|…`, `dossier.py: WAIT_RE`) khớp ít nhất một comment ở **1,79%** issue JFrog và **2,18%** issue Spring.
- Regex có độ chính xác thấp (vd. "depends on" xuất hiện trong mô tả kỹ thuật), nên chỉ dùng để **lọc ứng viên**; quyết định cuối do LLM đọc ngữ cảnh và trích dẫn nguyên văn (§5.6).

### 3.9. Bất thường và lỗi dữ liệu phát hiện qua EDA

| # | Bất thường | Quy mô | Tác động | Xử lý |
|---|---|---|---|---|
| D1 | **Đóng hàng loạt**: ≥20 issue chuyển sang done bởi cùng một người trong cùng một phút | JFrog: 91 đợt, **8.044 issue (52%)**. Spring: 354 đợt, **26.008 issue (38%)** | Dwell trước khi đóng là thời gian "chờ được dọn", không phải thời gian làm. Làm sai F1 và vòng đời | Cờ `bulk_close` trong hồ sơ; ngoại lệ E8 trong codebook; cân nhắc loại các đoạn này khỏi phân phối dwell |
| D2 | **Trạng thái `Done` của Spring có `statusCategory = indeterminate`** | 3.145 issue | Bị coi là "đang làm" → tạo ứng viên F1 giả và tập truy vấn sai | **Chưa sửa.** Đề xuất: ghi đè category theo tên (`Done`, `Closed`, `Resolved` → done) hoặc theo `resolution` khác rỗng |
| D3 | Ngày placeholder `1969-12-31T16:00:00` (issue `IDE-*` của Spring) | 58 trường, 26 sự kiện | Timestamp âm vi phạm bất biến memory của TGN → crash | Kẹp về 0 (§4.4) |
| D4 | Tên priority có tiền tố số (`"4 - Normal"`) | Toàn bộ JFrog | Priority bị đọc thành hằng số 0,4 | Bỏ tiền tố trước khi tra bảng (đã sửa) |
| D5 | Shape document khác Jira API v2 (changelog là dict, link/comment nằm trong `fields`, giá trị mới ở trường `set`) | Toàn bộ dump | Đọc theo API chuẩn sẽ ra rỗng | `normalize_doc()` (§4.2) |
| D6 | Link tự tham chiếu | Rải rác | Sự kiện rác | Loại khi sinh sự kiện |
| D8 | **Mỗi mục link chỉ có một phía** (`outwardIssue` *hoặc* `inwardIssue`), không phải cả hai như giả định của `events.py` | JFrog: 2.125 mục chỉ outward, 2.125 mục chỉ inward, 0 mục có cả hai | Mục inward bị bỏ → mỗi link chỉ 1 sự kiện thay vì 2; cột 14 (chiều link) luôn 0 (đã kiểm: 0/2.125 sự kiện link có direction = 1) | **Chưa sửa.** Đề xuất: `other ← outwardIssue.key nếu có, ngược lại inwardIssue.key`; `direction ← [outwardIssue có mặt]` (cách `dossier.py` đang làm đúng) |
| D7 | Changelog **không** bị cắt | 0 vi phạm `total == len(histories)` trên 5 instance lớn | — | Không cần xử lý |

### 3.10. Đặc trưng của đồ thị sau khi dựng

| Chỉ số | JFrog | Spring |
|---|---|---|
| Nút / sự kiện | 12.165 / 55.666 | 67.691 / 372.553 |
| % sự kiện self-loop (`u = v`) | **96,4%** | **97,1%** |
| Bậc nút: p50 · p90 · p99 · max | 4 · 9 · 19 · 63 | 5 · 10 · 21 · 102 |
| `ts` đơn điệu tăng | Có | Có |

Số nút nhỏ hơn số issue (12.165 < 15.535) vì issue không phát sinh sự kiện nào thì không xuất hiện trong dòng sự kiện.

**Ý nghĩa với mô hình:** với 96–97% self-loop, "hàng xóm thời gian" của một issue chủ yếu là các sự kiện cũ của chính nó; thông tin liên issue chỉ đến qua ~3% sự kiện `link`. TGN trong cấu hình này hoạt động gần với một mô hình chuỗi theo issue có memory, cộng thêm kênh truyền tin qua link. Đây là lý do (a) phải so sánh với baseline không đồ thị (GBDT trên feature theo thời điểm) và (b) đáng thử chế độ hai phía issue–người để tăng mật độ cạnh thật.

### 3.11. Tổng hợp: từ phát hiện EDA đến quyết định thiết kế

| Phát hiện | Quyết định |
|---|---|
| Phân phối dwell lệch mạnh, khác nhau giữa trạng thái | Ngưỡng F1 = percentile theo (trạng thái, theme) trong dự án, không dùng ngưỡng tuyệt đối |
| Issue mở phần lớn là backlog chết | Ngoại lệ E1; tập truy vấn `Q(t)` chỉ gồm issue đang làm hoặc có hoạt động trong 90 ngày |
| 38–52% issue đóng hàng loạt | Cờ `bulk_close`, ngoại lệ E8 |
| Deferred / Won't Fix chiếm 9–16% | Ngoại lệ E4, E5 — nhãn không thể chỉ dựa vào thời gian mở |
| Không có link `Block`, chỉ `Depend` | Gộp Block ∪ Depend khi tính I1 và feature |
| I1 hiện tại chỉ 0,1–0,3% | Dự kiến lớp dương rất hiếm → AUPRC, `pos_weight`, Precision@k |
| 96–97% self-loop | Bắt buộc baseline không đồ thị; thử đồ thị hai phía |
| Khoảng cách sự kiện từ giây đến 12 năm | Time encoding đa tần số; chuẩn hóa Δt theo mean/std |
| Quy trình khác nhau giữa instance | Mọi ngưỡng tính theo dự án; JFrog dùng thử nghiệm, Spring huấn luyện chính |

---

## 4. Tiền xử lý dữ liệu

### 4.1. Kiến trúc pipeline

```
Zenodo 15719919 ── ThePublicJiraDataset.zip (5,81 GB)
   │ mongorestore
   ▼
MongoDB JiraReposAnon.<instance>          (1 document = 1 issue)
   │
   ├── NHÁNH MÔ HÌNH  (jira_adapter/build_mongo.py)
   │     A1 normalize_doc        chuẩn hóa shape document
   │     A2 normalize_*          chuẩn hóa giá trị (link type, priority, theme)
   │     A3 extract_events       document → dòng sự kiện có thời gian
   │     A4 edge/node features   vector đặc trưng (tùy chọn --leak-safe)
   │     A5 write_instance       đánh chỉ số, sắp xếp, xuất ml_{name}.*
   │     ──► data/ml_{name}.csv / .npy / _node.npy
   │
   └── NHÁNH NHÃN  (jira_adapter/dossier.py, sampling.py, llm_label.py)
         A7 build_project_context   phân phối dwell, category trạng thái, đóng hàng loạt
         A8 build_dossier           hồ sơ hồi cứu + tín hiệu F/I
         A9 sample_instance         mẫu phân tầng + bảng chấm gold
         A10 LLM + self-consistency  trích tín hiệu, kiểm trích dẫn
         A11 aggregate + rule        nhãn {1, 0, review} + episode
         ──► llm_labels/*.json  ──► (sẽ nối vào A5 qua --label-mode llm)

Loader TGN (utils/data_processing.py)
   A6 chia train/val/test theo thời gian (quantile 0,70 / 0,85)
```

### 4.2. A1 — Chuẩn hóa shape document (`normalize.py: normalize_doc`)

**Vấn đề:** dump không theo shape của Jira REST API v2 (D5, §3.9).

**Thuật toán** (idempotent: gọi nhiều lần cho cùng kết quả; document đã chuẩn được trả nguyên):

```
normalize_doc(doc):
  if doc.changelog là dict:
      H ← doc.changelog.histories
      với mỗi h ∈ H: h.created ← h.created ?? h.createdAt ; h.user ← h.user ?? h.author
      doc.changelog ← H
  if doc.issueLinks không có:  doc.issueLinks ← doc.fields.issuelinks ?? doc.fields.issueLinks ?? []
  if doc.comments không có:    doc.comments  ← doc.fields.comments ?? []
  return doc
```

Khi đọc một changelog item, giá trị mới lấy theo thứ tự `to` → `set`; `status`/`priority` là dict thì đọc `.name`.

### 4.3. A2 — Chuẩn hóa giá trị (`normalize.py`)

| Hàm | Đầu vào → đầu ra | Thuật toán |
|---|---|---|
| `normalize_link_type` | ~75 tên link thô → hạng mục chuẩn | Tra bảng ánh xạ của tác giả dataset (`jira_issue_linktype_mapping.json`, nhúng trong code), so khớp không phân biệt hoa thường; không khớp → `Other` |
| `link_type_index` | hạng mục → chỉ số one-hot 0..8 | `Block, Depend, Epic, Parent-Child, Subtask, Fix, Duplicate, Relate, Other` |
| `normalize_priority` | tên priority → `[0, 1]` | Lấy `.name` nếu là dict → bỏ tiền tố `^\d+\s*-\s*` → chữ thường → tra bảng: blocker/highest 1,0 · critical 0,8 · high 0,6 · major 0,5 · medium/normal 0,4 (mặc định) · minor/low 0,3 · trivial/lowest 0,1 |
| `normalize_issue_theme` | issue type → chỉ số theme 0..4 | Tra bảng chủ đề của tác giả dataset: Requirements, Development, Maintenance, User Support, Other |

Ví dụ ánh xạ link: `Blocked/Blocks/Blocker → Block`; `Depend/Depends/Dependency/Gantt Dependency/Required/finish-finish… → Depend`; `Completes/Fixes/Resolve → Fix`; `Duplicate/Cloners → Duplicate`; `Reference/Relate/Related → Relate`.

### 4.4. A3 — Sinh dòng sự kiện (`events.py: extract_events`)

**Đầu ra:** danh sách `Event(u, v, ts, kind, detail)`.

```
extract_events(doc, include_comments=True):
  doc ← normalize_doc(doc); key ← doc.key; E ← []
  # 1. changelog
  for h in doc.changelog:
      ts ← safe_ts(to_epoch(h.created)); if ts = None: continue
      for it in h.items:
          f ← it.field
          if f ∈ {description, summary, comment, attachment, worklog, updated}: continue   # nhiễu
          if f = status:   E += Event(key, key, ts, "status",   {from, to ← it.to ?? it.set})
          if f = assignee: E += Event(key, to ?? "(unassigned)", ts, "assignee", {from, to})  # v = người
          if f = priority: E += Event(key, key, ts, "priority", {from, to})
  # 2. link
  for lk in doc.issueLinks:
      other ← (lk.outwardIssue.key = key) ? lk.inwardIssue.key : lk.outwardIssue.key
      # ⚠ lỗi D8: mục chỉ có inwardIssue cho other = None → bị bỏ; direction luôn 0
      if other = None hoặc other = key: continue                                            # tự tham chiếu
      ts ← created(doc)                                                                     # xấp xỉ
      E += Event(key, other, ts, "link",
                 {link_type_idx ← link_type_index(lk.type.name), direction ← [lk.outwardIssue.key = key]})
  # 3. comment
  if include_comments: for c in doc.comments: E += Event(key, c.author, safe_ts(c.created), "comment", {})
  sort E theo (ts, kind)
  return E

to_epoch(iso):  parse ISO-8601 (chấp nhận "+0000" và "Z") → giây UTC
safe_ts(ts):    return None nếu ts = None, ngược lại max(ts, 0)
```

**Các quyết định và lý do:**

| Quyết định | Lý do |
|---|---|
| Kẹp timestamp âm về 0 | TGN kiểm tra `last_update[i] ≤ t` khi cập nhật memory; timestamp âm (D3) làm crash ngay batch đầu. Kẹp về 0 giữ thứ tự tương đối |
| Timestamp link = `created` của issue chứa document | API không có thời điểm tạo link. Mốc này có thể **sớm hơn** thời điểm tạo link thật (link thường được tạo sau khi issue ra đời) và, với issue tạo trước, sớm hơn cả lúc issue bên kia tồn tại. Cải tiến: dùng changelog `Link` có timestamp của JFrog; cách an toàn khi không có là `max(created)` của hai issue |
| Thiết kế: mỗi link sinh 2 sự kiện (mỗi chiều một). **Thực tế: chỉ 1** (lỗi D8) | Mỗi link xuất hiện trong document của cả hai issue, ở phía issue A dưới dạng `outwardIssue = B` và ở phía B dưới dạng `inwardIssue = A`. Code lấy `other = outwardIssue` khi `outwardIssue ≠ key`, nên mục inward (không có `outwardIssue`) cho `other = None` và bị bỏ. JFrog: 4.250 mục link → 2.125 sự kiện. Vì TGN cập nhật memory cho cả nguồn và đích của mỗi sự kiện, cả hai nút vẫn được cập nhật; thiệt hại chính là mất thông tin chiều |
| Assignee/comment mang `v` = người, được đổi thành self-loop ở A5 | Phiên bản v1 dùng đồ thị một loại nút (issue). Đồ thị hai phía (giữ nút người) là ablation |
| Bỏ thay đổi description/summary/attachment/worklog | Chỉnh sửa văn bản không phải sự kiện quy trình; giảm nhiễu |

Phân bố sự kiện thu được:

| kind | JFrog | Spring |
|---|---|---|
| status | 31.703 | 128.673 |
| comment | 13.152 | 186.077 |
| assignee | 6.771 | 41.288 |
| link | 2.125 | 11.053 |
| priority | 1.915 | 5.462 |

### 4.5. A4 — Đặc trưng (`to_tgn.py`)

**Đặc trưng cạnh `x_k ∈ ℝ^24`:**

| Cột | Nội dung | Công thức | `--leak-safe` |
|---|---|---|---|
| 0–4 | Loại sự kiện | one-hot `(status, assignee, priority, link, comment)` | Giữ |
| 5–13 | Loại link | one-hot `link_type_index` (chỉ với `link`) | **Bỏ** |
| 14 | Chiều link | 1 nếu issue này là phía outward — **hiện luôn 0** do lỗi D8 | **Bỏ** |
| 15 | Priority của issue nguồn | `normalize_priority` ∈ [0,1] | Giữ |
| 16–20 | Theme của issue nguồn | one-hot 5 | Giữ |
| 21 | Giờ trong ngày (sin) | `sin(2π · h / 24)`, `h = (ts / 3600) mod 24` | Giữ |
| 22 | Giờ trong ngày (cos) | `cos(2π · h / 24)` | Giữ |
| 23 | Dự phòng | 0 | — |

Mã hóa giờ bằng cặp sin/cos để 23h và 0h gần nhau. Khoảng thời gian giữa các sự kiện **không** đưa vào feature vì time encoder của TGN đã mã hóa `t − last_update`.

**Đặc trưng nút `f_i ∈ ℝ^64`** (8 chiều có nghĩa, đệm 0 đến 64):

| Cột | Nội dung | `--leak-safe` |
|---|---|---|
| 0 | priority | Giữ |
| 1–5 | theme one-hot | Giữ |
| 6 | `has_block_link`: có link Block **hoặc** Depend | **Bỏ** (đặt 0) |
| 7 | `log1p(n_links) / log1p(max_links)` | **Bỏ** (đặt 0) |
| 8–63 | 0 | — |

**Vì sao đệm lên 64:** trong `embedding_module.py`, đặc trưng đầu vào lớp 0 của nút là `memory[i] + f_i` (cộng trực tiếp), nên `node_dim` phải bằng `memory_dim`.

**Vì sao có `--leak-safe`:** cột 6–7 tính từ **trạng thái cuối document** (thông tin tương lai đối với mọi `t` trước đó), còn cột 5–14 mã hóa đúng thứ nhãn v3 dùng để định nghĩa dương tính. Thí nghiệm ở §5.1 cho thấy các cột này giải thích gần như toàn bộ AUC của v3.

### 4.6. A5 — Đánh chỉ số và xuất định dạng TGN (`to_tgn.py: write_instance`)

```
write_instance(name, events_per_issue, docs, label_rows, leak_safe):
  # 1. id nút: mỗi issue có ≥1 sự kiện nhận một id 0-based, theo thứ tự duyệt issue
  id ← {}; for key, evs in events_per_issue: if evs ≠ ∅: id[key] ← |id|
  # 2. dòng cạnh
  for key, evs in events_per_issue; for e in evs:
      v ← e.v nếu e.v ∈ id, ngược lại key     # assignee/comment (v là người) và link tới issue
                                              # không có sự kiện → self-loop
      label ← label_rows[(key, e.ts)] ?? 0
      x ← edge_feature(e); if leak_safe: x[5..14] ← 0
      rows += (id[key], id[v], e.ts, label, x)
  sort rows theo (ts, u)                      # dòng sự kiện toàn cục đúng thứ tự thời gian
  # 3. viết file (mọi chỉ số 1-based; dòng 0 = padding)
  CSV  ml_{name}.csv : với k = 1..|rows|:  u = id+1, i = id_v+1, ts, label, idx = k
  NPY  ml_{name}.npy       : shape (|E|+1, 24), dòng 0 = 0, dòng k = edge_feature(e_k)
  NPY  ml_{name}_node.npy  : shape (|V|+1, 64), dòng 0 = 0, dòng id+1 = node_feature(issue)
```

Kiểm tra sau khi viết (đã chạy trên cả ba instance): dòng 0 của hai mảng bằng 0; `ts` đơn điệu tăng; số `u` duy nhất bằng `|V|`; `min(ts) = 0` ở Spring (xác nhận kẹp D3).

### 4.7. A6 — Chia dữ liệu (`utils/data_processing.py`)

**Phát hiện điểm nghẽn (T1):**

```
val_time, test_time ← quantile(ts, [0,70; 0,85])
train = {e : ts ≤ val_time} ; val = {val_time < ts ≤ test_time} ; test = {ts > test_time}
```

**Tự giám sát (T2), có đánh giá inductive:**

```
1. val_time, test_time như trên
2. N_after ← nút xuất hiện trong sự kiện có ts > val_time
3. New ← lấy ngẫu nhiên 10% của N_after (seed 2020)   # "nút mới" giả lập
4. train ← {e : ts ≤ val_time và u ∉ New và v ∉ New}
5. val/test: mọi sự kiện trong khoảng; thêm tập con new_node_val/test = sự kiện có ≥1 đầu mút ∉ nút của train
```

Chia theo thời gian (không xáo trộn) là bắt buộc với dữ liệu thời gian: xáo trộn sẽ cho mô hình thấy tương lai trong lúc huấn luyện. Bài học từ nhãn v1: nếu nhãn là hàm của `t`, tỉ lệ dương sẽ lệch giữa các split (đo được 1,1% / 36% / 55%) và mô hình học "thời điểm" thay vì "điểm nghẽn". Vì vậy **tỉ lệ dương theo split là một kiểm tra bắt buộc** trước mỗi thí nghiệm. Với nhãn v3 hiện tại: JFrog 3,60% / 3,05% / 1,16%; Spring 2,80% / 3,00% / 1,12%.

### 4.8. Lỗi đã sửa trong quá trình tiền xử lý

| # | Lỗi | Hậu quả | Sửa |
|---|---|---|---|
| 1 | Timestamp âm (D3) | TGN crash "update memory to time in the past" | `safe_ts` |
| 2 | `status`/`priority` là dict | Chuẩn hóa sai | Đọc `.name` |
| 3 | Giá trị mới ở `set` thay vì `to` | Mất trạng thái đích | Fallback `to → set` |
| 4 | `has_block_link` luôn 0 | Feature vô dụng | Dùng `normalize_link_type ∈ {Block, Depend}` |
| 5 | Priority JFrog là hằng số | Mất tín hiệu priority | Bỏ tiền tố số |
| 6 | Repo TGN trên Python 3.13: `random.sample(set)`, early-stop/lưu checkpoint đặt sai thụt lề, batch cỡ 1 | Crash khi chia inductive / không lưu model tốt nhất | Sửa trong `utils/`, `train_*.py` |
| 7 | **Trạng thái `Done` của Spring bị coi là đang làm (D2)** | Ứng viên F1 và tập truy vấn sai | **Cần sửa** trong `ProjectContext.category` |
| 8 | **Mục link inward bị bỏ, chiều link luôn 0 (D8)** | Mất một nửa sự kiện link; feature chiều vô dụng | **Cần sửa** trong `events.py: extract_events` rồi build lại |

---

## 5. Xây dựng nhãn điểm nghẽn

### 5.1. Lịch sử nhãn và thí nghiệm đo rò rỉ

| Phiên bản | Định nghĩa | T1 test AUC (JFrog) | Kết luận |
|---|---|---|---|
| v1 | Top-5%/dự án theo điểm composite có `dwell(t) = t − created` | 0,19–0,44 | Loại: nhãn là hàm của `t` → lệch tỉ lệ dương theo split |
| v2 | Composite không dwell | 0,578 | Loại: tín hiệu yếu (một phần do bug priority) |
| v3 | Issue có ≥1 link Block/Depend | 0,835 | **Loại: rò rỉ** |

**Thuật toán đo rò rỉ (ablation loại bỏ kênh):** huấn luyện lại cùng cấu hình trên các biến thể dữ liệu, mỗi lần bỏ một kênh nghi ngờ; mức sụt AUC là phần đóng góp của kênh đó.

| Biến thể | Thay đổi | AUC (3 lần chạy) | Trung bình |
|---|---|---|---|
| `JFrog` | gốc | 0,839 · 0,832 · 0,834 | 0,835 |
| `JFrog_nl1` | bỏ edge cột 5–14, node cột 6–7 | 0,630 · 0,631 · 0,598 | 0,620 |
| `JFrog_nl2` | `nl1` + bỏ toàn bộ sự kiện `link` | 0,523 · 0,459 · 0,469 | **0,484** |

Bằng chứng trực tiếp: 432/432 issue dương JFrog (2.711/2.714 Spring) có sự kiện link Block/Depend, và sự kiện đó luôn đến trước sự kiện mang nhãn đầu tiên. Kết luận: với v3, mô hình chỉ đọc lại feature; **không có bằng chứng TGN học được tín hiệu điểm nghẽn từ diễn biến quy trình**. Đây là lý do thiết kế nhãn mới tách biệt khỏi feature đầu vào.

### 5.2. Thiết kế nhãn mới

| Thuộc tính | Lựa chọn |
|---|---|
| Đơn vị | **Episode** `(issue, start, end)` — một issue có 0..n episode |
| Thuộc tính đi kèm | `role ∈ {root, victim}`, `type ∈ {dependency, external, review, resource, requirement, technical, process}` |
| Người quyết định | LLM trích tín hiệu và bằng chứng; **code** tính mọi số liệu thời gian và xác nhận F/I; người chấm kiểm định |
| Nhãn huấn luyện chính | `y_i(t) = 1 ⟺ ∃ episode root của i: start ≤ t < end` |

### 5.3. A7 — Ngữ cảnh dự án (`dossier.py: build_project_context`)

Tính một lần cho mỗi instance:

```
build_project_context(docs):
  end_ts ← max mọi timestamp changelog / created
  # 1. category của trạng thái: đa số statusCategory.key trên các issue đang ở trạng thái đó
  votes[name][cat] += 1 cho mỗi issue;  status_cat[name] ← argmax_cat votes[name]
  # 2. phân phối dwell theo (trạng thái, theme) và (trạng thái, mọi theme = -1)
  for d in docs:
      segs ← status_segments(d)                       # đoạn [start, end) từ changelog
      for s in segs: if s.end ≠ None và category(s.status) ≠ done:
          dwell[(s.status, theme(d))].append(s.days); dwell[(s.status, -1)].append(s.days)
  sort từng danh sách dwell
  # 3. đóng hàng loạt
  closes[(author, ⌊ts/60⌋)] += 1 với mỗi lần chuyển sang trạng thái done
  bulk_close ← {(a, m) : closes[(a, m)] ≥ 20}
  # 4. WIP ưu tiên cao theo người: số issue chưa done, priority ≥ 0,6, của từng assignee

pct_rank(status, theme, days):
  D ← dwell[(status, theme)] hoặc dwell[(status, -1)]
  if |D| < 20: return None                            # quá ít dữ liệu để tin percentile
  return bisect_left(D, days) / |D|                   # O(log n)
```

`status_segments(d)`: lấy chuỗi `(ts, from, to)` của changelog status theo thời gian; đoạn đầu bắt đầu tại `created` với trạng thái `from` của lần chuyển đầu tiên (hoặc trạng thái hiện tại nếu chưa từng chuyển); đoạn cuối có `end = None` (còn mở), độ dài tính đến `end_ts`.

Chỉ dùng đoạn **đã kết thúc** để dựng phân phối, tránh thiên lệch do các đoạn còn mở bị cắt cụt ở `end_ts`.

### 5.4. A8 — Hồ sơ issue và tín hiệu F/I (`dossier.py: build_dossier`)

Hồ sơ là bản tóm tắt hồi cứu của toàn bộ đời issue, dùng cho LLM và người chấm. **Không được dùng làm feature.**

| Phần | Nội dung | Giới hạn |
|---|---|---|
| Metadata | key, type, theme, priority, resolution, fixVersion, components, tuổi, hoạt động cuối, số ngày im lặng đến `data_end` | — |
| Mô tả | văn bản | ≤ 1.500 ký tự |
| Dòng thời gian trạng thái | mỗi đoạn: trạng thái, category, start, end, số ngày, **percentile** | — |
| Lịch sử | assignee, priority, fixVersion, link (changelog `Link`) | — |
| Link hiện tại | loại chuẩn, chiều, issue bên kia, trạng thái hiện tại của issue đó | — |
| Comment | thời gian, tác giả ẩn danh, nội dung | ≤ 500 ký tự/comment; giữ 10 đầu + 30 cuối |
| Cờ | `bulk_close`, `epic_or_umbrella`, `placeholder_date` | — |

**Tín hiệu tính sẵn:**

| Tín hiệu | Công thức |
|---|---|
| `F1_max_active_dwell_pct` | max percentile các đoạn có category `indeterminate` |
| `F1_max_new_dwell_pct` | max percentile các đoạn có category `new` |
| `F2_wait_comment_idx` | chỉ số các comment khớp `WAIT_RE` |
| `F3_reopen` | số lần chuyển done → không done |
| `F3_status_pingpong` | số vị trí `i` với `s[i] = s[i−2] ≠ s[i−1]` trong chuỗi trạng thái (mẫu A → B → A) |
| `F3_assignee_handoffs` | `max(số lần đổi assignee − 1, 0)` |
| `F4_high_prio_unassigned` | priority ≥ 0,6 ∧ không assignee ∧ chưa done |
| `F4_assignee_open_high_prio` | WIP ưu tiên cao của assignee hiện tại |
| `I1_open_dependents` | số link Block/Depend outward tới issue **đang mở** |
| `I2_fixversion_changes` | số lần đổi fixVersion |
| `I3_priority_raised` | số lần priority tăng |
| `I3_watchers`, `I3_votes` | từ `fields.watches`, `fields.votes` |

Kích thước hồ sơ JFrog (xấp xỉ 4 ký tự/token): trung vị ~490 token, p90 ~940, tối đa ~3.600.

### 5.5. A9 — Chọn mẫu phân tầng (`sampling.py`)

**Lọc ứng viên** (heuristic rộng tay, `candidate_reasons`):

```
F1_active             : F1_max_active_dwell_pct ≥ 0,9
F1_committed_waiting  : F1_max_new_dwell_pct ≥ 0,9 ∧ có assignee ∧ priority ≥ 0,6
F2_wait_comment       : có comment khớp WAIT_RE
F3_churn              : reopen ≥ 1 ∨ pingpong ≥ 2 ∨ handoffs ≥ 3
F4_unassigned_high    : F4_high_prio_unassigned
```

Kết quả: JFrog 2.972 issue thỏa ≥1 tiêu chí (F1_active 1.220 · F3 974 · F4 719 · F2 278 · F1_committed 193); Spring 11.722 (F1_active 7.035 · F3 3.744 · F2 1.505) — con số Spring bị thổi phồng bởi lỗi D2.

**Ba tầng không chồng lấn** (theo thứ tự ưu tiên):

| Tầng | Định nghĩa | Quần thể JFrog | Mẫu | Chấm đôi | Mục đích |
|---|---|---|---|---|---|
| v3 | ≥1 link Block/Depend | 450 | 60 | 20 | Đo v3 sai ở đâu |
| candidate | ≥1 tiêu chí F, không thuộc v3 | 2.848 | 120 | 40 | Nơi tập trung dương tính |
| random | phần còn lại | 12.237 | 120 | 40 | Ước lượng số dương bị bộ lọc bỏ sót (recall) |

**Phân bổ trong tầng — largest remainder theo tầng con `(đã đóng?, theme)`:**

```
stratified(keys, strata, n, rng):
  if |keys| ≤ n: return keys
  G ← nhóm keys theo strata
  quota[g] ← n · |G[g]| / |keys|; alloc[g] ← ⌊quota[g]⌋
  phần dư r ← n − Σ alloc; cộng 1 cho r nhóm có (quota − alloc) lớn nhất
  return ∪_g rng.sample(sorted(G[g]), alloc[g])          # seed 0 → tái lập được
```

Bảng chấm gold cho người chấm được xáo thứ tự (seed 1) và **không** lộ tầng, để người chấm không bị neo theo tầng.

### 5.6. A10 — Trích xuất bằng LLM (`llm_label.py`)

**Cấu hình:** server OpenAI-compatible (LM Studio local), model `qwen/qwen3.8-27b`, `temperature = 0,7`, `reasoning_effort = low`, đầu ra ép theo **JSON schema** (`response_format = json_schema`, `strict`).

**Prompt:** system = codebook (định nghĩa F/I, ngoại lệ, quy tắc nhất quán, vai trò, loại, quy tắc bằng chứng); user = hồ sơ dạng văn bản. Các quy tắc then chốt:
- Mọi kết luận phải kèm **trích dẫn nguyên văn** 5–25 từ từ hồ sơ.
- Không tự tính khoảng thời gian; chỉ dùng số đã có (percentile do code tính).
- `start`/`end` của episode phải **copy đúng** một timestamp có trong hồ sơ.
- Priority "Blocker" là mức nghiêm trọng, không phải bằng chứng nghẽn.
- Thiếu bằng chứng → `unsure`.

**Schema đầu ra:** `is_bottleneck ∈ {yes, no, unsure}`, `role`, `type`, `f_criteria ⊆ {F1..F4}`, `i_criteria ⊆ {I1..I3}`, `waiting_for`, `evidence[≤6]`, `episodes[≤4]`, `exclusion`, `confidence`, `rationale`.

**Self-consistency:**

```
label_issue(key, N=3):
  S ← các mẫu đã có trong llm_raw/{key}.jsonl cùng prompt_version và model     # chạy tiếp được
  calls ← 0
  while |{s ∈ S : s.answer hợp lệ}| < N và calls < 2N:
      r ← LLM(codebook, dossier_text); calls += 1
      ans ← parse JSON (None nếu hỏng hoặc bị cắt do max_tokens)
      s ← {r, ans, check ← verify(ans, dossier_text)}; ghi nối vào llm_raw; S += s
  return aggregate(S, dossier)
```

**Kiểm tra bằng chứng (`verify`):**

```
quote_found(q, T):                      # T = hồ sơ đã chuẩn hóa khoảng trắng, chữ thường
  q ← chuẩn hóa(q), bỏ dấu câu ở hai đầu
  if q ⊂ T: return True
  if q có dạng "<nhãn ≤25 ký tự>: <phần còn lại>" và phần còn lại ⊂ T: return True   # LLM thêm tiền tố
  return độ dài đoạn con chung liên tục dài nhất(q, T) ≥ 0,8·|q|                     # difflib
bad_timestamps ← {start, end của episode} \ {mọi chuỗi ISO-8601 trong hồ sơ}
```

### 5.7. A11 — Gộp mẫu và rule quyết định (`llm_label.py: aggregate`)

```
aggregate(S, dossier):
  V ← mẫu hợp lệ; if V = ∅: return review
  majority ← giá trị is_bottleneck có > 50% phiếu, ngược lại "unsure"
  A ← mẫu đồng thuận với majority
  role, type, exclusion ← mode trên A
  # episode đại diện = medoid theo IoU thời gian
  best ← argmax_{s ∈ A} Σ_{o ∈ A, o ≠ s} IoU(s.episodes, o.episodes)
  # xác nhận F và I bằng số liệu code
  f_ok ← candidate_reasons(dossier) ≠ ∅  ∨  (F2 ∈ LLM ∧ trích dẫn của best đều thật)
  i_code ← {I1 nếu có link Block/Depend; I2 nếu có fixVersion hoặc đổi fixVersion;
            I3 nếu priority tăng ∨ watchers ≥ 5 ∨ votes ≥ 3}
  i_ok ← i_code ≠ ∅  ∨  (I3 ∈ LLM ∧ trích dẫn thật)
  if majority = yes ∧ exclusion = null ∧ f_ok ∧ i_ok ∧ role ≠ none: final ← 1
  elif majority = no ∨ (majority = yes ∧ exclusion ≠ null):          final ← 0
  else:                                                              final ← review
  if final ≠ review ∧ có trích dẫn/timestamp bịa trong A:           final ← review
```

**IoU giữa hai tập episode** `A`, `B` (episode mở dùng `end = data_end`):

```
IoU(A, B) = Σ_{a∈A, b∈B} |a ∩ b|  /  ( Σ|a| + Σ|b| − Σ|a ∩ b| )      ; = 1 nếu cả hai rỗng, = 0 nếu một bên rỗng
```

Ba đầu ra: `1` (dương, có episode), `0` (âm), `review` (đưa người chấm: LLM không chắc, LLM mâu thuẫn rule, hoặc có bằng chứng bịa).

### 5.8. Kiểm định nhãn (cổng trước khi huấn luyện)

| Chỉ số | Công thức | Ngưỡng |
|---|---|---|
| κ người–người (100 issue chấm đôi) | Cohen's κ = `(p_o − p_e) / (1 − p_e)` | ≥ 0,6 — thấp hơn thì sửa codebook trước |
| κ LLM–gold (`is_bottleneck`) | như trên | ≥ 0,6 và ≥ 0,8 × κ người–người |
| Precision lớp dương | `TP / (TP + FP)` | ≥ 0,75 |
| Độ chính xác `role` trên ca dương | | ≥ 0,7 |
| Biên episode | IoU ≥ 0,5 hoặc lệch `start` ≤ 7 ngày | |
| Recall bộ lọc | tỉ lệ dương trong tầng random × kích thước tầng random | Báo cáo; nhiều → nới bộ lọc |

**Hiện trạng pilot (20/300 issue JFrog):** 15 issue đang mở → đều `0` (14 backlog). Trong các issue đã đóng có tín hiệu F rõ: 4 × `1`, 2 × `0` (`data_artifact`). Ví dụ dương: **BI-459** ứ ở *Pending QA* 177 ngày (p100), là điều kiện tiên quyết của 3 issue → root/review; **RTFACT-1131** ứ ở *Reopened* 92 ngày (p97) sau nhiều lỗi UI → root/technical. Chưa có trích dẫn bịa nào; LLM áp dụng đúng ngoại lệ E3 (RTFACT-26414: priority Blocker nhưng không ai chờ → âm). Tốc độ ~45 s/issue (3 mẫu) → 300 issue ≈ 3,75 giờ.

### 5.9. Mở rộng nhãn ra toàn instance

| Phương án | Phạm vi LLM | Chi phí (local, ~15 s/lần gọi) |
|---|---|---|
| A | 3.298 issue (candidate + v3) × 3 mẫu; còn lại gán 0 | ~41 giờ |
| **B (đề xuất)** | Như A nhưng 1 mẫu trước, chỉ lấy thêm 2 mẫu khi `confidence < 0,8` hoặc mâu thuẫn rule | **~20 giờ** |
| C | LLM gắn ~1.000 issue, distill sang bộ phân loại nhỏ trên hồ sơ | ~12 giờ + huấn luyện (dùng cho Spring) |

Gán 0 cho phần ngoài ứng viên chỉ hợp lệ nếu tầng random của pilot cho tỉ lệ dương rất thấp; tỉ lệ này được báo cáo như sai số nhãn đã biết.

---

## 6. Giải pháp mô hình

### 6.1. Vì sao chọn TGN

| Phương pháp | Điểm yếu với bài toán |
|---|---|
| Heuristic (tuổi, WIP, priority × tuổi) | Không phân biệt "lâu vì ít quan trọng" với "lâu và đang chặn người khác"; không học |
| Process mining | Phân tích hồi cứu, yếu ở dự đoán; không biểu diễn được issue mới |
| GNN tĩnh trên snapshot | Mất thứ tự thời gian; phải dựng lại đồ thị mỗi snapshot |
| RNN theo từng issue | Bỏ qua tương tác giữa các issue |
| **TGN** | Xử lý trực tiếp dòng sự kiện; memory giữ trạng thái từng issue; attention theo hàng xóm thời gian; suy diễn được cho issue mới; repo có sẵn hai chế độ (dự đoán liên kết, phân loại nút) và baseline JODIE/DyRep |

Cảnh báo từ EDA (§3.10): với 96–97% self-loop, lợi thế "đồ thị" của TGN bị thu hẹp. Vì vậy TGN phải được so với baseline không đồ thị mạnh (§6.6); nếu không vượt, kết luận đó vẫn là một kết quả hợp lệ.

### 6.2. Kiến trúc TGN (theo mã nguồn trong repo)

Ký hiệu: `s_i(t) ∈ ℝ^{d_m}` là memory của nút `i`; `t_i⁻` là lần cập nhật memory gần nhất; `d_m = 64`.

#### 6.2.1. Thông điệp (`modules/message_function.py`)

Với sự kiện `e = (u, v, t, x)`, thông điệp thô cho nguồn và đích:

```
raw_u = [ s_u(t⁻) ‖ s_v(t⁻) ‖ x ‖ φ(t − t_u⁻) ]
raw_v = [ s_v(t⁻) ‖ s_u(t⁻) ‖ x ‖ φ(t − t_v⁻) ]
```

với `φ` là time encoder (§6.2.4). Hàm thông điệp MLP:

```
m = W₂ · ReLU(W₁ · raw + b₁) + b₂ ,   W₁: d_raw → d_raw/2 ,   W₂: d_raw/2 → d_msg (= 64)
```

Kích thước `d_raw = 2·64 + 24 + 64 = 216`.

#### 6.2.2. Gộp thông điệp (`modules/message_aggregator.py`)

Một nút có thể nhận nhiều thông điệp trong cùng batch. Bộ gộp `last` (dùng trong cấu hình chính) giữ thông điệp có timestamp lớn nhất; `mean` lấy trung bình (ablation).

#### 6.2.3. Cập nhật memory (`modules/memory_updater.py`)

```
s_i(t) = GRUCell( m̄_i(t), s_i(t⁻) )
```

Trước khi cập nhật, code kiểm tra bất biến `last_update[i] ≤ t` (lý do phải kẹp timestamp âm, §4.4). Memory là tensor `n_nodes × 64` (không phải tham số học), được **reset** ở đầu mỗi epoch và **detach** khỏi đồ thị tính toán sau mỗi `backprop_every` batch.

**Thứ tự cập nhật chống nhìn tương lai** (`memory_update_at_start = True`, mặc định): ở batch `b`, memory được cập nhật bằng các thông điệp **của các batch trước**, rồi mới tính embedding và dự đoán cho batch `b`; thông điệp của chính batch `b` chỉ được lưu lại để dùng ở batch sau. Như vậy dự đoán cho sự kiện tại `t` không dùng thông tin của chính sự kiện đó.

#### 6.2.4. Mã hóa thời gian (`model/time_encoding.py`)

```
φ(Δt) = cos( ω · Δt + b ) ∈ ℝ^{d_t} ,   ω_j khởi tạo = 10^{−9·j/(d_t − 1)} , j = 0..d_t−1 ,  b = 0
```

Tần số trải từ `1` đến `10⁻⁹` (học được), phù hợp với dải khoảng cách sự kiện từ giây đến ~12 năm (§3.4). `Δt` tính bằng giây, không chuẩn hóa, trong thông điệp và attention; phiên bản chuẩn hóa theo trung bình/độ lệch chuẩn của train chỉ dùng cho module nhúng kiểu JODIE (`--embedding_module time`).

#### 6.2.5. Nhúng bằng temporal graph attention (`modules/embedding_module.py`, `model/temporal_attention.py`)

Đặc trưng lớp 0 của nút: `h_i⁽⁰⁾(t) = s_i(t) + f_i` (memory + đặc trưng nút — lý do `node_dim = memory_dim`).

Với lớp `l = 1..L` (`L = 2`), lấy `k = 10` hàng xóm thời gian gần nhất `N_i(t) = {(j, e_ij, t_j) : t_j < t}`:

```
q   = [ h_i⁽ˡ⁻¹⁾(t) ‖ φ(0) ]
K=V = [ h_j⁽ˡ⁻¹⁾(t_j) ‖ x_ij ‖ φ(t − t_j) ]   với (j, e_ij, t_j) ∈ N_i(t)
h̃   = MultiHeadAttention(q, K, V)            (4 head, dropout 0,1)
h_i⁽ˡ⁾(t) = MergeLayer(h̃, h_i⁽ˡ⁻¹⁾(t)) = W_b · ReLU(W_a · [h̃ ‖ h_i⁽ˡ⁻¹⁾] )
```

Embedding cuối `z_i(t) = h_i⁽ᴸ⁾(t) ∈ ℝ^64`. Việc tính đệ quy `h_j⁽ˡ⁻¹⁾` của hàng xóm làm chi phí tăng theo `k^L`.

#### 6.2.6. Bộ giải mã

| Bài toán | Decoder | Đầu ra |
|---|---|---|
| T2 (dự đoán sự kiện) | `MergeLayer(z_u, z_v)`: `64+64 → 64 → 1`, sigmoid | xác suất có sự kiện `(u, v, t)` |
| T1 (điểm nghẽn) | MLP `64 → 80 → 10 → 1`, ReLU, dropout 0,1 (`utils/utils.py: MLP`) | xác suất `y_i(t) = 1` |

### 6.3. Giai đoạn 1 — Tiền huấn luyện tự giám sát (T2, `train_self_supervised.py`)

```
for epoch in 1..E:
  memory.reset(); neighbor_finder ← chỉ dùng cạnh train
  for nhóm k batch liên tiếp (k = backprop_every = 4):
      loss ← 0
      for batch B = {(u, v, t, x)} (kích thước 128):
          v⁻ ← RandEdgeSampler: lấy ngẫu nhiên đích âm từ tập đích của train
          p⁺ ← σ(dec(z_u(t), z_v(t)));  p⁻ ← σ(dec(z_u(t), z_{v⁻}(t)))
          loss += BCE(p⁺, 1) + BCE(p⁻, 0)
      loss /= k; loss.backward(); Adam.step(lr = 1e-3)
      memory.detach()
  đánh giá val (AP, AUC) trên cạnh cũ và cạnh có nút mới; early stopping (patience 5) theo AP val
lưu saved_models/{prefix}-{data}.pth
```

Mục đích: học memory, message function và attention sao cho embedding phản ánh "issue này sắp có hoạt động gì", không cần nhãn. Trên dữ liệu Jira, bài toán này **dễ** (AUC ~0,99) vì phần lớn sự kiện là self-loop; giá trị chính của giai đoạn này là khởi tạo các module chứ không phải con số AUC.

### 6.4. Giai đoạn 2 — Phát hiện điểm nghẽn (T1-D)

#### 6.4.1. Cách repo đang làm và vấn đề

`train_supervised.py` nạp mô hình giai đoạn 1, **đóng băng toàn bộ TGN** (`tgn.eval()`, `torch.no_grad()`), duyệt lại dòng sự kiện để cập nhật memory, và huấn luyện decoder MLP trên `z_u(t)` của **nguồn mỗi sự kiện** với `BCELoss` không trọng số. Nhãn được đọc từ cột `label` của CSV.

Ba vấn đề với nhãn episode:
1. **Issue đang nghẽn thường không có sự kiện** trong episode (chính vì nó đang tắc) → nếu chỉ dự đoán tại sự kiện thì gần như không có điểm dương.
2. Lớp dương dự kiến < 1% (EDA §3.6) → BCE không trọng số khiến decoder luôn đoán âm.
3. Embedding của giai đoạn 1 được tối ưu cho dự đoán sự kiện, chưa chắc mang tín hiệu điểm nghẽn.

#### 6.4.2. Đánh giá tại mốc thời gian (query points)

Phương án chèn sự kiện "tick" hằng tuần cho mọi issue đang mở bị loại sau khi đo: JFrog có ~1,6 triệu issue-tuần đang mở (gấp ~29 lần số sự kiện thật), Spring ~4,8 triệu. Phương án chọn:

```
Q(t) = { i : i chưa done tại t  ∧  ( i đang ở trạng thái category "indeterminate" tại t
                                     ∨ i có sự kiện trong (t − 90 ngày, t] ) }

query_training(stream, labels_episode, tuần t_1 < t_2 < …):
  memory.reset()
  for mỗi mốc t_w:
      nạp mọi sự kiện có ts ≤ t_w vào TGN (cập nhật memory, neighbor finder)
      Q ← Q(t_w)                                   # không thêm sự kiện nào vào đồ thị
      Z ← compute_embedding(Q, t_w)                # memory hiện tại + attention trên hàng xóm trước t_w
      ŷ ← decoder(Z);  y ← [t_w ∈ episode root của i] với i ∈ Q
      loss ← BCEWithLogits(ŷ, y, pos_weight = n_neg / n_pos)
```

`Q(t)` loại backlog không hoạt động (trung vị 622–2.396 ngày im lặng, §3.4) đúng theo ngoại lệ E1, giữ lại issue đang thực sự trong quy trình. Kích thước `Q(t)` theo tuần là số cần đo khi cài đặt.

#### 6.4.3. Thay đổi huấn luyện

| # | Thay đổi | Lý do |
|---|---|---|
| 1 | `BCEWithLogitsLoss(pos_weight = n_neg / n_pos)` hoặc lấy mẫu cân bằng trong batch | Lớp dương hiếm |
| 2 | Tùy chọn mở khóa TGN và fine-tune end-to-end với `lr = 1e-4` cho encoder | Thích nghi embedding cho điểm nghẽn |
| 3 | Vòng huấn luyện/đánh giá theo `Q(t)` | Đánh giá đúng issue đang tắc |
| 4 | Seed cấu hình được, chạy ≥ 5 seed | P0 cho thấy dao động ±0,03 AUC giữa các lần chạy |
| 5 | Dữ liệu `--leak-safe`; sự kiện link dùng timestamp thật từ changelog `Link` (JFrog) | Không feature nào là hàm của nhãn hoặc của tương lai |

#### 6.4.4. Cảnh báo sớm (T1-E)

Cùng vòng lặp, nhãn đổi thành `y_i(t) = 1 ⟺ ∃ episode root: start ∈ (t, t + Δt]`, với `Δt ∈ {7, 14, 30}` ngày; loại khỏi `Q(t)` các issue đang ở trong episode để không lẫn "phát hiện" với "dự báo".

### 6.5. Cấu hình siêu tham số

| Nhóm | Tham số | Giá trị |
|---|---|---|
| Kích thước | `node_dim`, `memory_dim`, `message_dim`, `time_dim` | 64, 64, 64, 64 |
| Memory | `use_memory`, `memory_updater`, `aggregator`, `memory_update_at_start` | bật, GRU, last, bật |
| Embedding | `embedding_module`, `n_layer`, `n_head`, `n_degree` | graph_attention, 2, 4, 10 |
| Thông điệp | `message_function` | mlp |
| Tối ưu | `bs`, `lr`, `backprop_every`, `drop_out`, `patience` | 128, 1e-3, 4, 0,1, 5 |
| Epoch | T2 / T1 | 20 / 30 |
| Phần cứng | GPU | RTX 4060 Ti 16 GB (dùng chung với LLM local → chạy tuần tự) |
| Thời gian (JFrog) | T2 / T1 | ~17 s/epoch / ~11 s/epoch; 5 seed ≈ 40 phút |

### 6.6. Baseline

| Baseline | Mô tả | Câu hỏi trả lời |
|---|---|---|
| Heuristic rule | Tín hiệu F/I tính **tại t** (không LLM, không học) | TGN có thêm giá trị ngoài rule đã biết? (Nhãn dùng rule F/I nên baseline này có lợi thế tự nhiên — đó là chủ đích) |
| Logistic regression / Gradient boosting | Feature phẳng theo thời điểm: tuổi, dwell hiện tại và percentile, số handoff, reopen, priority, WIP assignee, số issue phụ thuộc đang mở | Có cần đồ thị và memory không? (đặc biệt quan trọng vì 96–97% self-loop) |
| TGN không memory | bỏ `--use_memory` (≈ TGAT) | Giá trị của memory |
| JODIE, DyRep | cờ có sẵn trong repo | So với mô hình cùng họ |
| TGN + v3 `--leak-safe` | tham chiếu P0 | Nhãn mới có học được hơn không |

### 6.7. Chỉ số đánh giá

| Chỉ số | Định nghĩa | Vai trò |
|---|---|---|
| **AUPRC** | diện tích dưới đường Precision–Recall | Chỉ số chính (lớp dương hiếm) |
| AUC-ROC | | So sánh với P0 |
| **Precision@k theo tuần** | `(1/W) Σ_w |top_k(ŷ(t_w)) ∩ positives(t_w)| / k`, `k ∈ {10, 20}` | Giá trị thực tế cho PM: danh sách cảnh báo mỗi tuần đúng bao nhiêu |
| **Lead time** (T1-E) | `start_episode − t_first` với `t_first` = thời điểm đầu tiên điểm dự đoán vượt ngưỡng | Cảnh báo được sớm bao lâu |
| Inductive | Các chỉ số trên tập con issue chưa xuất hiện trong train | Khả năng tổng quát cho issue mới |
| Độ ổn định | trung bình ± độ lệch chuẩn trên ≥ 5 seed | |

Chia dữ liệu: theo thời gian 70/15/15; báo cáo tỉ lệ dương từng split; nếu lệch quá 3 lần thì cân nhắc chia theo issue hoặc cắt đầu/cuối dòng thời gian. Giai đoạn sau: train Spring, test JFrog (cross-instance).

### 6.8. Ablation

1. Bỏ memory. 2. `graph_attention` → `graph_sum`. 3. Bỏ edge feature. 4. Có/không sự kiện comment. 5. Có/không sự kiện link với timestamp thật. 6. Nhãn `root` so với `root ∪ victim`. 7. `Δt` = 7 / 14 / 30 ngày. 8. Đồ thị hai phía issue–người (`assignee`/`comment` nối tới nút người thay vì self-loop) — trực tiếp nhắm vào vấn đề 96–97% self-loop và tải tập trung (Gini 0,82–0,84).

### 6.9. Danh sách kiểm tra rò rỉ (chạy trước mỗi thí nghiệm)

- [ ] Không feature nào tính từ trạng thái cuối document (`n_links`, `has_block`, trạng thái hiện tại…).
- [ ] Không feature nào là hàm của `t` theo cùng cách nhãn là hàm của `t` (bài học v1).
- [ ] Sự kiện link dùng timestamp thật hoặc xấp xỉ không sớm hơn thực tế.
- [ ] Tỉ lệ dương theo split đã kiểm.
- [ ] Ablation bỏ kênh nghi ngờ không làm AUC rơi đột ngột về ~0,5 (dấu hiệu nhãn chỉ đọc lại feature, như §5.1).

---

## 7. Kết quả hiện có

| Run | Dữ liệu | Bài toán | Kết quả test |
|---|---|---|---|
| TGN | JFrog | T2 | AUC 0,9986 (cạnh cũ) / 0,9823 (nút mới, 1.216 nút) |
| TGN | Spring | T2 | AUC 0,9997 / 0,9988 (6.769 nút mới) |
| TGN | Mojang (50k) | T2 | AUC 0,9989 / 0,9937 (4.951 nút mới) |
| DyRep | JFrog | T2 | AUC 0,9901 / 0,8893 — TGN hơn 9,3 điểm AUC trên nút mới |
| TGN | JFrog, v3 | T1 | AUC 0,835 (3 lần) — **rò rỉ** |
| TGN | JFrog_nl1, v3 | T1 | AUC 0,620 |
| TGN | JFrog_nl2, v3 | T1 | AUC 0,484 |
| TGN | Spring, v3 | T1 | AUC 0,768 — cùng cơ chế rò rỉ, chưa đo lại |
| TGN | JFrog, composite | T1 | AUC 0,578; có dwell < 0,5 |

**Diễn giải:** (1) pipeline dữ liệu và định dạng tương thích hoàn toàn với repo; (2) TGN học tốt bài toán dự đoán sự kiện và vượt DyRep rõ ở nút mới — memory có ích cho issue chưa thấy; (3) **chưa có** kết quả hợp lệ nào cho bài toán điểm nghẽn — sẽ có sau khi nhãn mới qua cổng kiểm định.

---

## 8. Rủi ro, giới hạn và lộ trình

### 8.1. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Khái niệm điểm nghẽn quá chủ quan (κ người–người thấp) | Cao | Sửa codebook trước khi chạy quy mô lớn |
| Quá ít ca dương (I1 hiện tại chỉ 0,1–0,3%; JFrog chủ yếu Open → Done) | Cao | AUPRC, `pos_weight`; cân nhắc gộp `victim`; Spring có quy trình đầy đủ hơn |
| Đồ thị gần suy biến (96–97% self-loop) → TGN không vượt baseline phẳng | Trung bình | Baseline GBDT bắt buộc; ablation đồ thị hai phía; kết quả âm vẫn được báo cáo |
| Đóng hàng loạt làm sai dwell (38–52% issue) | Trung bình | Cờ `bulk_close`, ngoại lệ E8 |
| Nhãn LLM sai hệ thống | Trung bình | Gold set; báo cáo sai số theo nhóm ngoại lệ; dùng `confidence` làm nhãn mềm |
| Dữ liệu công khai có trong pretraining của LLM | Thấp | Ghi nhận; so với model khác họ |

### 8.2. Giới hạn dữ liệu đã biết

1. Timestamp link là xấp xỉ (trừ changelog `Link` của JFrog).
2. Người phụ trách ẩn danh, không có vai trò/nhóm.
3. I1 trong hồ sơ dùng trạng thái **hiện tại** của issue bên kia, chưa phải trạng thái trong khoảng episode.
4. Mojang chỉ build 50.000/421.000 issue (giới hạn RAM; cần đọc theo luồng).
5. Lỗi D2 (`Done` của Spring) và D8 (mất mục link inward, chiều link luôn 0) chưa sửa.

### 8.3. Lộ trình

| Bước | Việc | Cổng đi tiếp |
|---|---|---|
| P0 ✅ | Đo rò rỉ v3, sửa bug | — |
| P1 ✅ | Hồ sơ, chọn mẫu, LLM labeler | — |
| P2 | Người chấm gold set (300 + 100 chấm đôi) | κ người–người ≥ 0,6 |
| P3 | LLM gắn 300 issue pilot | — |
| P4 | So LLM với gold, sửa codebook/prompt | κ LLM–gold ≥ 0,6, precision ≥ 0,75 |
| P5 | Sửa D2, D8; gắn nhãn toàn JFrog (phương án B) | Recall bộ lọc chấp nhận được |
| P6 | Build v4 (`--leak-safe`, `--label-mode llm`, link có timestamp); query points; huấn luyện + baseline, 5 seed | TGN vượt heuristic và GBDT về AUPRC |
| P7 | T1-E, ablation | — |
| P8 | Mở rộng Spring (distill) | — |

---

## 9. Tái lập

```bash
cd /mnt/Data/0.Workspace/0.SourceCode/tgn

# MongoDB (dump đã restore)
.tools/mongodb-linux-x86_64-enterprise-ubuntu2404-9.0.2/bin/mongod \
  --dbpath .tools/mongo-data --bind_ip 127.0.0.1 --port 27017 --fork --logpath .tools/mongod.log --logappend

# EDA cơ bản + build dữ liệu TGN
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --list
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog --out data --eda-out docs/eda
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog --out data --leak-safe --as-name JFrog_ls

# Hồ sơ + mẫu pilot + bảng chấm
PYTHONPATH=.pylibs python -m jira_adapter.sampling --instance JFrog --out data/llm_pilot

# Gắn nhãn LLM (LM Studio đã load model; cấu hình trong .env), chạy tiếp được
python -m jira_adapter.llm_label --pilot-dir data/llm_pilot/JFrog

# Huấn luyện
COMMON="--bs 128 --n_degree 10 --n_head 4 --n_layer 2 --lr 0.001 --patience 5 --node_dim 64 --time_dim 64 \
  --backprop_every 4 --use_memory --embedding_module graph_attention --message_function mlp \
  --memory_updater gru --message_dim 64 --memory_dim 64 --prefix tgn_jira"
python train_self_supervised.py -d JFrog_ls $COMMON --n_epoch 20
python train_supervised.py      -d JFrog_ls $COMMON --n_epoch 30 --use_validation --n_runs 3
```

**EDA mở rộng (§3):** các số liệu §3.2–3.10 được tính bằng một script dùng lại `normalize_doc`, `extract_events`, `build_project_context`, `build_dossier`, `candidate_reasons` trên toàn bộ document của JFrog và Spring, cộng với đọc `data/ml_{instance}.csv` cho số liệu đồ thị (thời gian chạy ~10 phút cho hai instance). Script hiện nằm ngoài repo; nên đưa vào `jira_adapter/eda.py` để `build_mongo --eda-out` sinh luôn các bảng này.

---

## 10. Phụ lục: bản đồ mã nguồn

| Thuật toán | Tệp / hàm |
|---|---|
| A1 Chuẩn hóa shape | `jira_adapter/normalize.py: normalize_doc` |
| A2 Chuẩn hóa giá trị | `jira_adapter/normalize.py: normalize_link_type, link_type_index, normalize_priority, normalize_issue_theme` |
| A3 Sinh sự kiện | `jira_adapter/events.py: extract_events, _to_epoch, _safe_ts` |
| A4 Đặc trưng | `jira_adapter/to_tgn.py: edge_feature, node_features` |
| A5 Xuất TGN | `jira_adapter/to_tgn.py: write_instance`; driver `jira_adapter/build_mongo.py` |
| A6 Chia dữ liệu | `utils/data_processing.py: get_data, get_data_node_classification` |
| Nhãn v1–v3 | `jira_adapter/labels.py: build_states, b1_score, assign_labels` |
| A7 Ngữ cảnh dự án | `jira_adapter/dossier.py: build_project_context, ProjectContext.pct_rank` |
| A8 Hồ sơ | `jira_adapter/dossier.py: build_dossier, render_text` |
| A9 Chọn mẫu | `jira_adapter/sampling.py: candidate_reasons, _stratified, sample_instance` |
| A10 LLM | `jira_adapter/llm_label.py: CODEBOOK, SCHEMA, Client, label_issue, verify` |
| A11 Gộp + rule | `jira_adapter/llm_label.py: aggregate, _iou` |
| TGN | `model/tgn.py`, `modules/{memory,memory_updater,message_function,message_aggregator,embedding_module}.py`, `model/{time_encoding,temporal_attention}.py` |
| Huấn luyện | `train_self_supervised.py`, `train_supervised.py`, `evaluation/evaluation.py` |

**Tài liệu tham khảo:**
1. Montgomery L., Lüders C., Maalej W. *An Alternative Issue Tracking Dataset of Public Jira Repositories.* MSR 2022. arXiv:2201.08368. Zenodo 15719919.
2. Rossi E. et al. *Temporal Graph Networks for Deep Learning on Dynamic Graphs.* ICML 2020 GRL Workshop. arXiv:2006.10637.
3. Xu D. et al. *Inductive Representation Learning on Temporal Graphs (TGAT).* ICLR 2020.
4. Kumar S. et al. *Predicting Dynamic Embedding Trajectory in Temporal Interaction Networks (JODIE).* KDD 2019.
5. Trivedi R. et al. *DyRep: Learning Representations over Dynamic Graphs.* ICLR 2019.
6. Wang X. et al. *Self-Consistency Improves Chain of Thought Reasoning in Language Models.* ICLR 2023.
7. Pangakis N., Wolken S., Fasching N. *Automated Annotation with Generative AI Requires Validation.* 2023.
