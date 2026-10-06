# Báo cáo: Tập dữ liệu & Tiền xử lý — Dự án TGN phát hiện điểm nghẽn trên dữ liệu Jira

**Phạm vi:** Mô tả đầy đủ (a) tập dữ liệu The Public Jira Dataset được sử dụng, (b) pipeline tiền xử lý từ document MongoDB → dòng sự kiện → nhãn bottleneck → định dạng `ml_{instance}.*` mà repo TGN tiêu thụ, kèm số liệu EDA đã đo, vấn đề chất lượng dữ liệu đã phát hiện/sửa, và bằng chứng xác minh end-to-end.
**Tài liệu liên quan:** `docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md` (báo cáo chính, §4 dữ liệu, §6 pipeline, Phụ lục D tiến độ), `jira_adapter/README.md` (tài liệu gói adapter), `docs/eda/eda_*.md` (EDA từng instance).
**Ngày:** 2026-10-01 (sau khi hoàn thành P0)
**Trạng thái:** Pipeline đã chạy end-to-end trên dữ liệu thật, 3 instance được build + xác minh bằng training.

> **⚠️ Đính chính 2026-10-04 (P0 đo rò rỉ nhãn, chi tiết: `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` §1).** Kết quả T1 của nhãn v3 trong báo cáo này **không còn hiệu lực**:
> - Nhãn v3 ("có ≥1 link Block/Depend") rò rỉ qua **edge feature one-hot loại link**: 432/432 issue dương JFrog (2.711/2.714 Spring) có sự kiện link Block/Depend, luôn đến trước sự kiện có nhãn. Node `[7] log1p(n_links)` rò rỉ một phần.
> - Bỏ các feature này, JFrog T1 test AUC (3 lần chạy) giảm từ **0,835 → 0,620**; bỏ thêm sự kiện link → **0,484** (ngẫu nhiên). Nghĩa là TGN **không học được** tín hiệu bottleneck từ diễn biến quy trình với nhãn v3.
> - Node `[6] has_block_link` luôn bằng 0 do bug (chỉ so tên link kiểu Block) — đã sửa trong `to_tgn.py`; build mới có cờ `--leak-safe`.
> - "Priority 100% normal trên JFrog" là **bug chuẩn hóa** (tên dạng `"4 - Normal"` không khớp bảng) — thực tế: Normal 72%, High 16%, Critical 7%, Blocker 3%. Đã sửa `normalize_priority`; dữ liệu `ml_*` hiện có vẫn mang giá trị cũ cho đến khi build lại.
> - Hướng thay thế: nhãn theo episode do LLM trích tín hiệu + rule, kiểm định bằng gold set — xem tài liệu nói trên.

---

## Mục lục

1. [Tóm tắt](#1-tóm-tắt)
2. [Tập dữ liệu](#2-tập-dữ-liệu)
3. [Tiền xử lý](#3-tiền-xử-lý)
4. [Sản phẩm dữ liệu (artifacts)](#4-sản-phẩm-dữ-liệu-artifacts)
5. [Xác minh end-to-end](#5-xác-minh-end-to-end)
6. [Phát hiện & sửa lỗi chất lượng dữ liệu](#6-phát-hiện--sửa-lỗi-chất-lượng-dữ-liệu)
7. [Giới hạn đã biết](#7-giới-hạn-đã-biết)
8. [Tái lập](#8-tái-lập)
9. [Tham chiếu mã nguồn & nguồn dữ liệu](#9-tham-chiếu-mã-nguồn--nguồn-dữ-liệu)

---

## 1. Tóm tắt

| Hạng mục | Giá trị (đã xác minh) |
|---|---|
| Nguồn dữ liệu | The Public Jira Dataset — Montgomery, Lüders & Maalej, **MSR 2022**; Zenodo record **15719919** (5,81 GB, CC-BY-4.0) |
| Quy mô tổng (công bố) | 16 instance · 1.822 dự án · 2,7M issue · 32M bản ghi thay đổi · 9M comment · 1M issue link |
| Instance đã build (pilot) | **Spring** (69.156 issue · 372.553 sự kiện), **JFrog** (15.535 · 55.666), **Mojang** (pilot 50.000 · 210.411) |
| Pipeline | MongoDB `JiraReposAnon` → `jira_adapter` (normalize → events → labels → to_tgn) → `data/ml_{instance}.{csv,npy,_node.npy}` |
| Định dạng ra | CSV `u,i,ts,label,idx` (id 1-based) + edge features **(n+1, 24)** + node features **(n_nodes+1, 64)**, dòng 0 = vector 0 |
| Nhãn bottleneck (mặc định) | **v3 dependency:** issue có ≥1 link Block/Depend — JFrog AUC 0,839 · Spring AUC 0,768 (mục tiêu ≥0,75). **⚠️ Rò rỉ nhãn: bỏ feature loại link → JFrog 0,620; bỏ thêm sự kiện link → 0,484** |
| Xác minh | Smoke test `ml_synth.*` + 6 run training (T2/T1 × 3 instance + DyRep + ablation) đọc đúng file, chạy hết epoch |

---

## 2. Tập dữ liệu

### 2.1. Nguồn gốc, giấy phép, quy mô công bố

**Công bố chính thức:** Montgomery L, Lüders C, Maalej W. *"An Alternative Issue Tracking Dataset of Public Jira Repositories."* IEEE/ACM MSR 2022, pp. 73–77 (University of Hamburg). arXiv: [2201.08368](https://arxiv.org/abs/2201.08368).

**Nơi lưu trữ chính thức (đã dùng):** Zenodo record **15719919** — file `ThePublicJiraDataset.zip` (5,81 GB), phát hành 2025-06-23, giấy phép **CC-BY-4.0**. DOI gốc trên paper `10.5281/zenodo.5882881` redirect về record này. Artefact GitHub `IoanaCovataru/ThePublicJiraDataset` chỉ chứa code + định nghĩa + README (không có archive 60 GB) — **nguồn tải thực tế là Zenodo** (bản zip đã nằm trong `data/raw/ThePublicJiraDataset.zip`).

**Quy mô tổng (README chính thức của artefact — `data/raw/ThePublicJiraDataset/README.md`):**

| Hạng mục | Số lượng |
|---|---|
| Instance Jira công khai | **16** |
| Dự án (projects) | **1.822** |
| Issue | **2.700.000** |
| Bản ghi thay đổi (changelog) | **32.000.000** |
| Comment | **9.000.000** |
| Issue links | **1.000.000** |

**16 instance kèm số issue xấp xỉ** (từ `0. DataDefinition/jira_data_sources.json`):

| Instance | URL | Issue (xấp xỉ) |
|---|---|---|
| Apache | issues.apache.org | 1.015.000 |
| Mojang | bugs.mojang.com | 421.000 |
| RedHat | issues.redhat.com | 353.000 |
| Jira (Atlassian) | jira.atlassian.com | 275.000 |
| Qt | bugreports.qt.io | 147.000 |
| MongoDB | jira.mongodb.org | 137.000 |
| Sonatype | issues.sonatype.org | 87.000 |
| **Spring** | jira.spring.io | 69.000 |
| Sakai | jira.sakaiproject.org | 51.000 |
| JiraEcosystem | ecosystem.atlassian.net | 42.000 |
| MariaDB ⚠️ | jira.mariadb.org | 30.000 |
| Hyperledger | jira.hyperledger.org | 28.000 |
| **JFrog** | jfrog.com/jira | 16.000 |
| IntelDAOS | jira.hpdd.intel.com | 9.000 |
| Mindville ⚠️ | jira.mindville.com | 2.000 |
| SecondLife | jira.secondlife.com | 2.000 |

⚠️ **MariaDB và Mindville hiện không còn truy cập được** (ghi rõ trong README artefact); meta-information thời điểm May/2021 của chúng được lưu riêng ở `0. DataDefinition/May2021/`.

**Tính danh (anonymization):** README DataDump ghi rõ dữ liệu đã được ẩn danh — tên assignee, creator, reporter, author comment/evolution được thay bằng **mặt nạ UUID4** (định dạng quan sát thực tế: `<<|author_name|<uuid>|>>`), duy nhất theo người nhưng **không mapping được về vai trò/nhóm người** — giới hạn đối với lớp B2 (assignee-level) được ghi nhận tại §7.

### 2.2. Mô hình dữ liệu (cấu trúc document)

Đơn vị cơ bản là **issue** — 1 document MongoDB, mỗi instance là 1 collection trong DB `JiraRepos` (sau khi restore: `JiraReposAnon`). Theo Jira API v2 `expand=changelog` (shape "gốc"):

```
{
  key: "SPR-12345",
  fields: {
    summary, description, status, issuetype, priority,
    assignee {name, displayName}, reporter, created, updated,
    resolution, components[], labels[], fixVersions[], project, ...
  },
  changelog:   [ { id, created, user {name}, items: [{field, from, to|set}] }, ... ],
  comments:    [ { id, author, created, body, updateAuthor, updated }, ... ],
  issueLinks:  [ { type {id, name, inward, outward}, inwardIssue, outwardIssue }, ... ]
}
```

**Tài nguyên định nghĩa đi kèm artefact (dùng làm nguồn sự thật cho lớp chuẩn hóa §3.2):**

- `jira_issue_linktype_mapping.json` — kết quả gắn nhãn thủ công của các tác giả: ~75 loại link tùy biến → 20+ hạng mục chuẩn (Block, Depend, Parent-Child, Epic, Fix, Duplicate, Cause, …).
- `jira_issuetype_thematic_analysis.json` — issue type → theme chuẩn (`Requirements`, `Development`, `Maintenance`, `User Support`, `Other`) cho từng instance.
- `jira_field_information.json`, `jira_issuetype_information.json` — meta-schema từng instance.

### 2.3. Shape document thực tế trong dump (đã xác minh trực tiếp)

Shape dump **khác** shape API v2 "gốc" — các biến thể đã xác minh và được `normalize_doc()` (idempotent) xử lý:

| Hạng mục | Trong dump (thực tế) | Xử lý |
|---|---|---|
| `changelog` | **dict** `{startAt, maxResults, total, histories:[{id, author, created, items}]}` — không phải list | rút `histories` ra list; `createdAt`→`created`, `author`→`user` |
| `issueLinks` | nằm trong **`fields.issuelinks`** (lowercase), không có top-level | đưa lên top-level |
| `comments` | nằm trong **`fields.comments`** | đưa lên top-level |
| `fields.status`, `fields.priority` | **dict** `{"name": "Done", ...}` không phải string | đọc `.name` |
| changelog item | giá trị mới ở trường **`set`** (không phải `to`) | đọc `to` → fallback `set` |
| Assignee | anonymized `<<|author_name|<uuid>|>>` | giữ UUID làm id ổn định |
| Timestamp | Spring có **placeholder âm** `1969-12-31T16:00:00.000+0000` (epoch −28.800s, 58 trường, issue `IDE-*` — Jira IDE cũ merge vào Spring) | clamp `ts = max(ts, 0)` — xem §6.1 |

**Đã kiểm tra thêm:** changelog **KHÔNG bị truncate** — `total == len(histories)` đúng trên Apache/Spring/Mojang/JFrog/Jira (0 vi phạm). **JFrog có changelog `field: "Link"`** (sự kiện tạo link *có* timestamp) — chưa dùng ở v1, giữ làm tín hiệu bổ sung cho giai đoạn sau.

### 2.4. Lựa chọn instance pilot

| Instance | Vai trò | Số issue | Lý do |
|---|---|---|---|
| **Spring** | **Main** | 69.156 | Quy trình chuẩn, 81 dự án, 89,8% issue có assignee — instance huấn luyện chính |
| **JFrog** | Sanity / label-audit | 15.535 | Nhỏ, chạy nhanh; **3,01% issue có Block/Depend** — tín hiệu bottleneck rõ nhất |
| **Mojang** | Scale | 50.000 (pilot, giới hạn RAM) | Lớn nhất trong 3; **bug-centric** (46.762/50k Resolved); link chủ yếu Duplicate |

Cơ sở lựa chọn (báo cáo chính §6.2 + số liệu EDA): tương phản về quy mô, văn hóa quản lý và mật độ link; Mojang gần như không có link Block/Depend (0,03% issue, 14 link Block) → vai trò "scale/EDA" chứ không phải instance huấn luyện chính cho nhãn v3. 2 instance offline (MariaDB, Mindville) loại khỏi pilot.

### 2.5. EDA 3 instance pilot (đã đo trên dump)

Số liệu từ `docs/eda/eda_*.md` + `data/build_mongo_summary.json` (EDA tự động của `jira_adapter/eda.py`, chạy trong cùng một build):

| Chỉ số | **Spring** | **JFrog** | **Mojang** (pilot 50k) |
|---|---|---|---|
| Issues (mở) | 69.156 (7.594) | 15.535 (5.191) | 50.000 (3.238) |
| Khoảng thời gian | 2003-11-26 → 2021-12-22 | 2006-10-04 → 2022-01-04 | 2014-01-25 → 2022-01-05 |
| Tổng sự kiện (trung vị/issue) | **372.553** (4,0) | **55.666** (3,0) | **210.411** (3,0) |
| Phân bố sự kiện | comment 186.077 · status 128.673 · assignee 41.288 · link 11.053 · priority 5.462 | status 31.703 · comment 13.152 · assignee 6.771 · link 2.125 · priority 1.915 | status 97.550 · comment 87.054 · link 24.492 · assignee 1.015 · priority 300 |
| Link endpoint-occurrences (≈ link độc lập) | 22.092 (≈11.046) | 4.250 (≈2.125) | 40.227 (≈20.113) |
| % issue có Block/Depend | **4,04%** | **3,01%** | **0,03%** |
| % issue có ≥1 link bất kỳ | 20,51% | 21,04% | 50,55% |
| Top loại link (chuẩn) | Relate 13.966 · Duplicate 3.580 · Depend 3.565 · Supercede 981 | Relate 1.822 · Duplicate 1.380 · Depend 538 · Trigger 410 | Duplicate 38.740 · Relate 1.450 · Block 14 |
| Assignee (unique · % issue được gán) | 260 · 89,8% | 184 · 60,9% | 20 · 1,4% |
| Comment (trung vị/issue) | 186.077 (2,0) | 13.152 (0,0) | 87.054 (1,0) |
| Status top | Closed 37.200 · Resolved 21.217 · Open 6.225 | Done 6.344 · Open 4.997 · Closed 2.455 | Resolved 46.762 · Open 2.496 · Reopened 742 |
| Dự án | 81 | 10 (RTFACT 12.158 · HAP 1.274 · TCAP 1.063 · …) | 3 (MCPE 37,4k · REALMS 9,1k · WEB 3,5k) |

**Đọc số liệu:**
- Cả 3 instance đều "nhẹ" (dưới 400k sự kiện) — chạy được trên GPU RTX 4060 Ti 16 GB, đủ cả CPU.
- Mật độ sự kiện/issue ~3–4 → trung vị thấp do nhiều issue chỉ có vài chuyển trạng thái; phần đuôi (issue "sống") tạo đa số sự kiện.
- **Block/Depend là tín hiệu hiếm nhưng nhất quán** (3–4% trên Spring/JFrog) — khớp quyết định chọn nhãn v3 (issue có ≥1 link Block/Depend); Mojang là ngoại lệ (bug tracker, link chủ yếu Duplicate) → không phù hợp làm instance chính cho nhãn v3.
- ~~Priority gần như hằng số trên JFrog (100% "normal" trong dữ liệu)~~ **(sai — bug chuẩn hóa tên `"4 - Normal"`; thực tế Normal 72% / High 16% / Critical 7% / Blocker 3%, đã sửa 2026-10-04)** → thành phần priority của score composite bị vô hiệu ở instance này (một trong các lý do composite chỉ đạt AUC 0,578 — §3.4).

### 2.6. Đánh giá chất lượng dữ liệu cho bài toán bottleneck

| Tiêu chí | Đánh giá | Bằng chứng |
|---|---|---|
| Đủ sự kiện thời gian | ✅ Rất tốt | 32M changelog (tổng) · 55k–372k sự kiện/instance pilot |
| Đủ quan hệ phụ thuộc | ✅ (Spring, JFrog) / ❌ (Mojang) | % issue Block/Depend: 4,04 / 3,01 / 0,03 |
| Không bị truncate | ✅ | `total == len(histories)` — 0 vi phạm trên 5 instance lớn |
| Nhãn bottleneck | ⚠️ Không có sẵn — tự xây (v3 dependency) | §3.4 |
| Tính danh | ⚠️ UUID ổn định, không có vai trò/nhóm | §7.6 |
| Timestamp link | ⚠️ Không có — xấp xỉ bằng `created` | §7.1 |
| 2/16 instance offline | ⚠️ MariaDB, Mindville | Loại khỏi pilot |

**Kết luận:** Dataset phù hợp nhất hiện có cho bài toán (lớn nhất, có changelog + links + comments, giấy phép mở, kèm định nghĩa chuẩn hóa do tác giả làm sẵn). Rào cản chính — gắn nhãn bottleneck và quy mô — đã có phương án và được xử lý trong pipeline (§3).

---

## 3. Tiền xử lý

### 3.1. Kiến trúc tổng thể

```
 Zenodo 15719919 (CC-BY-4.0)
        │  ThePublicJiraDataset.zip (5,81 GB)
        ▼
 data/raw/ThePublicJiraDataset/   ← artefact: README + DataDefinition + DataDump
        │  mongorestore (mongod 9.0.2 local @127.0.0.1:27017)
        ▼
 MongoDB  DB: JiraReposAnon — 16 collections (=16 instance), 2.686.282 docs, 0 failures
        │
        │  python -m jira_adapter.build_mongo --instance <X> --out data
        ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ jira_adapter (pipeline 4 bước, mã nguồn trong workspace)                │
 │                                                                         │
 │  1. normalize.py   normalize_doc() — shape dump → shape chuẩn (idempotent)│
 │                     bảng chuẩn link type / priority / issue theme        │
 │  2. events.py      extract_events() — document → list Event(u, v, ts,    │
 │                     kind, detail); ISO→epoch; clamp ts âm; sort (ts,kind)│
 │  3. labels.py      assign_labels() — gắn LABEL bottleneck cho từng event │
 │                     (mặc định mode=dependency / v3)                      │
 │  4. to_tgn.py      write_instance() — xuất ml_{name}.{csv,npy,_node.npy} │
 │                     đúng contract của utils/data_processing.py           │
 └─────────────────────────────────────────────────────────────────────────┘
        │  data/ml_{instance}.csv/.npy/_node.npy  +  docs/eda/eda_{instance}.md
        ▼
 Loader repo TGN (utils/data_processing.py)
   • split theo THỜI GIAN: quantile(ts, [0.70, 0.85]) → train/val/test
   • chế độ inductive: giữ 10% nút mới (chỉ xuất hiện sau val_time),
     xoá mọi cạnh chứa chúng khỏi train
        ▼
 train_self_supervised.py (T2 link prediction)
 train_supervised.py      (T1 node classification — bottleneck)
```

**Vai trò từng module** (chi tiết §3.2–3.5):

| Module | Hàm chính | Trách nhiệm |
|---|---|---|
| `jira_adapter/normalize.py` | `normalize_doc`, `normalize_link_type`, `normalize_priority`, `normalize_issue_theme` | Chuẩn hóa shape + giá trị dị dạng giữa 16 instance |
| `jira_adapter/events.py` | `extract_events`, `_to_epoch`, `_safe_ts` | Phát sinh dòng sự kiện có mốc thời gian |
| `jira_adapter/labels.py` | `assign_labels`, `build_states`, `b1_score` | Gắn nhãn bottleneck (v3 mặc định + composite ablation) |
| `jira_adapter/to_tgn.py` | `write_instance`, `edge_feature`, `node_features` | Xuất đúng định dạng repo TGN |
| `jira_adapter/eda.py` | `eda_instance`, `render_markdown` | Số liệu EDA per-instance (quyết định scope) |
| `jira_adapter/build_mongo.py` | `build_instance_mongo` | **Driver chính**: đọc MongoDB → 4 bước trên → file |
| `utils/preprocess_data.py` (repo gốc) | `preprocess`, `reindex` | Tham chiếu định dạng đầu vào (adapter mô phỏng chính xác output này) |
| `utils/data_processing.py` (repo gốc) | `get_data`, `get_data_node_classification` | Tiêu thụ `ml_*.*` + split thời gian + đánh giá inductive |

### 3.2. Bước 1 — Chuẩn hóa shape & giá trị (`normalize.py`)

Ba lớp chuẩn hóa, tất cả **idempotent / không bỏ sót** (giá trị lạ → "Other"/default, không drop):

**(a) Shape document — `normalize_doc(doc)`:**

- `changelog`: dict `{startAt, maxResults, total, histories:[...]}` → list; mỗi history: `createdAt`→`created`, `author`→`user`.
- `fields.issuelinks`/`fields.issueLinks` → top-level `issueLinks`; `fields.comments` → top-level `comments`.
- Document đã đúng shape được trả về nguyên vẹn (không copy) — an toàn khi gọi lặp.

**(b) Link type — `normalize_link_type` / `link_type_index`:**

Ánh xạ ~75 tên link thô (từ `jira_issue_linktype_mapping.json` của tác giả dataset, được embed trong code để adapter chạy độc lập) → các hạng mục chuẩn. Nhóm quan trọng nhất cho bottleneck:

| Nhóm | Tên thô (ví dụ) → Chuẩn |
|---|---|
| **Phụ thuộc/chặn (tín hiệu bottleneck)** | Blocked/Blocks/Blocker → **Block**; Depend/Depends/Dependency/Gantt Dependency/Required → **Depend** |
| Cấu trúc | Child-Issue/Parent Feature/Parent-Relation → **Parent-Child**; Subtask → **Subtask**; Epic/Epic-Relation → **Epic** |
| Kết cục/chất lượng | Completes/Fixes/Resolve → **Fix**; Duplicate/Cloners → **Duplicate** |
| Nhân quả/thứ tự | Causality/Cause/Regression → **Cause**; Follows/Sequence → **Follow** |
| Quan hệ chung | Reference/Relate/Related → **Relate**; Split/Work Breakdown → **Split**; … |
| Gantt (ít gặp) | finish-finish, start-finish… → gom về **Depend** |

One-hot dùng **9 ô**: `Block, Depend, Epic, Parent-Child, Subtask, Fix, Duplicate, Relate, Other` — hạng mục ngoài 8 hạng mục chính (Trigger, Incorporate, Supercede, …) rơi vào **Other** (không mất dữ kiện).

**(c) Priority — `normalize_priority`:** Jira priority (dict `{"name": …}`) → trọng số 0..1: `blocker/highest=1.0 · critical=0.8 · high=0.6 · major=0.5 · medium/normal=0.4 (default) · minor/low=0.3 · trivial/lowest=0.1`.

**(d) Issue theme — `normalize_issue_theme`:** issue type → 1 trong 5 theme chuẩn (theo `jira_issuetype_thematic_analysis.json`): `Requirements` (epic, story, new feature, improvement…), `Development` (task, technical task, umbrella, subtask…), `Maintenance` (bug, outage, defect, technical debt…), `User Support` (incident, question, support…), `Other`.

### 3.3. Bước 2 — Phát sinh dòng sự kiện (`events.py`)

**Đơn vị sự kiện:** `Event(u, v, ts, kind, detail)` — `u`/`v` là issue key (hoặc tên người cho assignee/comment), `ts` = epoch giây.

**5 loại sự kiện (kind):**

| Kind | Nguồn trong document | u → v | Ghi chú |
|---|---|---|---|
| `status` | changelog `field == "status"` | issue → issue (self-loop) | detail: `from`/`to` |
| `assignee` | changelog `field == "assignee"` | issue → username | rỗng → `(unassigned)`; **v1 xuất ra self-loop** (bipartite để P2) |
| `priority` | changelog `field == "priority"` | issue → issue | |
| `link` | `issueLinks` | issue → issue liên kết | **ts xấp xỉ = `created` của issue này** (§7.1); detail: link_type_idx, direction (1 = outward) |
| `comment` | `comments` | issue → author | v1 xuất ra self-loop |

**Quy tắc phát sinh:**

- **Bỏ qua noise:** changelog field `description, summary, comment, attachment, worklog` và `updated` không tạo sự kiện (sửa mô tả/title là noise cho bài toán).
- **Thời gian:** ISO 8601 (cả `+0000` và `Z`) → epoch giây; **timestamp âm được clamp về 0** (`_safe_ts`) — Spring có 58 placeholder `1969-12-31T16:00:00.000+0000` (epoch −28.800s) từ Jira IDE cũ; không clamp sẽ vi phạm invariant `last_update(0) ≤ ts` của TGN memory và crash ngay batch 0 (xác minh: 26 sự kiện Spring được kẹp về `t=0` — CSV `ml_Spring.csv` bắt đầu từ `ts=0`).
- **Link tự tham chiếu bị loại** (sự kiện `outwardIssue == inwardIssue == key`).
- **Thứ tự:** sort `(ts, kind)` trong mỗi issue; toàn bộ stream sort `(ts, u)` trước khi viết file — **dòng sự kiện toàn cục đúng thứ tự thời gian**, điều kiện cần để TGN memory không nhìn vào tương lai.
- Mỗi link xuất hiện trong document của **cả hai issue** → mỗi link tạo **2 sự kiện** (một cho mỗi hướng) — chủ đích: cập nhật memory cho cả hai nút; hệ quả là số đếm link trong EDA là *endpoint-occurrences* (phải chia đôi để ra link độc lập).

### 3.4. Bước 3 — Gắn nhãn bottleneck (`labels.py`)

**Lịch sử thiết kế (3 phiên bản, kết quả đo quyết định — chi tiết ở báo cáo chính, Phụ lục D §6):**

| Phiên bản | Định nghĩa | Kết quả đo (JFrog) | Kết luận |
|---|---|---|---|
| v1 (composite + dwell) | top-5%/dự án theo `B1_score(t)` với `dwell(t) = t − created` | T1 AUC **0,19–0,44** (<chance); split positive rate lệch 1,1%/36%/55% | **BỎ** — dwell làm nhãn tương quan với thời điểm → **leakage** qua split thời gian |
| v2 (composite static) | top-5%/dự án theo score không-dwell (ranking + tie-break) | T1 test AUC **0,578** | **Bỏ làm nhãn chính** — 96–97% issue không có link + priority hằng số → top-5% pha loãng issue không tín hiệu; **giữ làm ablation** |
| **v3 (dependency) — MẶC ĐINH** | `LABEL(i,t)=1` ⟺ issue có ≥1 link **Block/Depend** | T1 test AUC **0,839**; Spring **0,768** — **⚠️ rò rỉ: 0,620 khi bỏ feature loại link, 0,484 khi bỏ thêm sự kiện link** | **CHỌN** (⚠️ cần thay, xem đính chính đầu báo cáo) — tín hiệu mạnh, face-valid ("điểm nghẽn = issue bị chặn/chặn người"), sạch cho đánh giá temporal |

**Cơ chế gán (v3):**

1. `build_states()` — trạng thái cuối document của mỗi issue: project, priority, created, last_event, số link Block/Depend in/out (theo hướng `outwardIssue`), resolved.
2. Nhãn theo **issue**: `label = 1 ⟺ links_in_block + links_out_block ≥ 1`.
3. Nhãn được **truyền xuống sự kiện**: chỉ các sự kiện `status/assignee/priority` của issue nhận nhãn (1.0/0.0) — không gắn lên sự kiện `link/comment` (tránh noise); mọi sự kiện khác trong CSV giữ `label=0`.
4. **Tính point-in-time:** vì v3 là thuộc tính cấu trúc (có/không có link Block/Depend) nên `LABEL(i,t) = LABEL(i,t')` với mọi t — không chứa hàm của thời điểm → **không leakage** khi split theo thời gian (bài học từ v1).

**Số liệu nhãn đã đo:**

| Instance | Issue dương | % issue | Positive events (trong CSV) |
|---|---|---|---|
| JFrog | 450 | 2,9% | 1.754 (3,15% × 55.666) |
| Spring | 2.794 | 4,0% | 9.598 (2,58% × 372.553) |
| Mojang (pilot) | ~10 | 0,02% | 116 (0,06% × 210.411) |

Phân bố positive theo split thời gian (70/15/15): JFrog 3,7/3,1/1,2% · Spring 2,8/3,0/1,1% — **cân bằng**, không prior-shift (đối lập v1).

**Biến thể ablation (vẫn build được):** `--label-mode composite [--use-dwell]` (top-5%/dự án theo `B1_score` với trọng số mặc định `w = (0.35, 0.35, 0.15, 0.15)`, ranking + tie-break theo key để tránh "khối điểm đồng nhất") → dataset `ml_JFrog_comp.*` đã build (781 issue dương, 40.389 sự kiện được gắn, pos_rate 6,68% — `data/build_mongo_summary.json`).

### 3.5. Bước 4 — Xuất định dạng repo TGN (`to_tgn.py`)

**Contract đầu vào của repo TGN** (tham chiếu `utils/preprocess_data.py` + `utils/data_processing.py`): mỗi dataset = 3 file trong `data/`:

| File | Nội dung |
|---|---|
| `ml_{name}.csv` | cột `u, i, ts, label, idx` — **id 1-based**, `idx` 1-based, dòng đã sort theo thời gian |
| `ml_{name}.npy` | edge features, shape **(n_events + 1, D_edge)**, **dòng 0 = vector 0** (vị trí "padding" cho idx=1-based) |
| `ml_{name}_node.npy` | node features, shape **(n_nodes + 1, D_node)**, dòng 0 = vector 0 |

Adapter sinh đúng contract này nhưng **cải tiến node features từ zero/random (repo gốc) sang đặc trưng issue thực** (§3.5.3).

**3.5.1. Gán id node:** thứ tự xuất hiện đầu tiên trong event stream → id 0-based ổn định → +1 khi viết CSV (JFrog: 12.165 nodes · Spring: 67.691 · Mojang pilot: 49.516).

**3.5.2. Edge features — 24 chiều (`EDGE_DIM = 24`), layout chính xác theo code:**

| Ô | Nội dung | Chi tiết |
|---|---|---|
| [0..4] | **kind one-hot** (5) | `status, assignee, priority, link, comment` |
| [5..13] | **link_type one-hot** (9) | `Block, Depend, Epic, Parent-Child, Subtask, Fix, Duplicate, Relate, Other` (chỉ có ý nghĩa với sự kiện `link`) |
| [14] | **direction** | 1 = issue này là outward (nguồn quan hệ, "A blocks B"), 0 = inward; 0 với các kind khác |
| [15] | **priority_norm** | 0.1–1.0 của issue nguồn (§3.2c) |
| [16..20] | **issue_theme one-hot** (5) | Requirements, Development, Maintenance, User Support, Other |
| [21] | **time-of-day sin** | `sin(2π·hour/24)`, hour = `(ts/3600) % 24` (UTC) |
| [22] | **time-of-day cos** | `cos(2π·hour/24)` |
| [23] | **đệm 0** | giữ chỗ mở rộng; delta-time giữa 2 sự kiện của cùng issue do **time encoder của repo** (`model/time_encoding.py`) đảm nhận — không nhân đôi |

**3.5.3. Node features — 8 chiều ngữ nghĩa, padding zero lên 64:**

| Ô | Nội dung |
|---|---|
| [0] | priority_norm |
| [1..5] | issue_theme one-hot (5) |
| [6] | has_block_link (có ≥1 link Block) — ⚠️ luôn 0 do bug cho đến 2026-10-04; nay = Block hoặc Depend; bị bỏ khi `--leak-safe` |
| [7] | log1p(n_links) / log1p(max_links trong instance) — ⚠️ đếm từ trạng thái cuối document, rò rỉ nhãn v3 một phần; bị bỏ khi `--leak-safe` |

**Vì sao 64 chiều:** repo TGN cộng `memory + node_features` trong embedding module → **`memory_dim` phải bằng chiều node feature**. Adapter padding zero 8 chiều ngữ nghĩa lên **64** (mặc định `node_out_dim=64`) và training chạy với `--memory_dim 64 --node_dim 64 --message_dim 64` (so với repo gốc: node features zero, 172 chiều).

**3.5.4. Chi tiết viết file (đã xác minh bằng đọc array):**

- CSV: header `u,i,ts,label,idx`; `ts` format 6 chữ số thập phân; sort `(ts, u)`.
- Edge npy: `float32`, dòng 0 toàn 0, dòng 1..n_events = feature 24 chiều.
- Node npy: `float32`, shape `(n_nodes+1, 64)`, dòng 0 toàn 0, 8 chiều đầu chứa feature ngữ nghĩa.
- Sự kiện `assignee`/`comment` (v = username/author ∉ node_id) → **self-loop** `v = u` (chế độ đồ thị đơn v1).
- Mỗi build in ra stats (n_nodes, n_events, n_labeled_events, edge_dim, node_dim, danh sách file) và ghi vào `data/build_mongo_summary.json`.

### 3.6. Tương thích với loader repo TGN (`utils/data_processing.py`)

Hai hàm loader — adapter không sửa loader, chỉ cần thỏa contract:

| Hàm | Nhiệm vụ | Chi tiết đã đọc code |
|---|---|---|
| `get_data` (self-supervised, T2) | split thời gian + **đánh giá inductive** | `val_time, test_time = np.quantile(ts, [0.70, 0.85])`; giữ **10% số nút chỉ xuất hiện sau val_time** làm "new test nodes", **xoá mọi cạnh chứa chúng khỏi train**; val/test dùng mọi cạnh trong khoảng thời gian tương ứng. (Đã vá 1 lỗi Python 3.13: `random.sample` cần sequence — dùng `sorted(test_node_set)`.) |
| `get_data_node_classification` (supervised, T1) | split thời gian đơn giản | train: `ts ≤ val_time` · val: `(val_time, test_time]` · test: `ts > test_time` |

**Hậu quả cho đánh giá (đã dùng trong P0):** AUC "old nodes" (toàn bộ test) + AUC "new nodes" (chỉ cạnh có ≥1 nút inductive — đo khả năng memory khởi tạo cho issue chưa từng thấy): JFrog 1.216 · Spring 6.769 · Mojang 4.951 nút inductive.

**Lưu ý về `label` trong loader:** `get_data_node_classification` đọc cột `label` của CSV làm nhãn node-classification — chính là nhãn bottleneck v3; sự kiện `link/comment` (label=0) là mẫu âm hợp lệ.

### 3.7. Tổng hợp: 1 sự kiện Jira → 1 dòng model

```
 issue SPR-1234 (changelog: status Open→In Progress @2021-05-04T10:20Z)
   │
   ├─ normalize_doc()          (shape dump → shape chuẩn)
   ├─ extract_events()         → Event(u="SPR-1234", v="SPR-1234", ts=1620123600,
   │                              kind="status", detail={from:"Open", to:"In Progress"})
   ├─ assign_labels()          → label=1 nếu SPR-1234 có link Block/Depend (v3)
   └─ write_instance()         → CSV:  (u=48148, i=48148, ts=1620123600.000000, label=1.0, idx=2)
                                  npy:  edge[2] = [1,0,0,0,0, 0,0,0,0,0,0,0,0,0, 0, 0.4,
                                            0,0,0,1,0, 0.4226,-0.9063, 0]
                                            (status, priority=normal, theme=Development,
                                            sin/cos của 10h20 UTC, padding)
```

---

## 4. Sản phẩm dữ liệu (artifacts)

Tất cả đã tồn tại trong `data/` và **đã xác minh shape/dtype bằng numpy**:

| Dataset | CSV (dòng sự kiện) | Edge npy (rows × 24) | Node npy (rows × 64) | Nodes |
|---|---|---|---|---|
| **Spring** (main) | `ml_Spring.csv` — 372.553 dòng · 15,4 MB | `(372.554, 24)` float32 · 35,8 MB | `(67.692, 64)` float32 · 17,3 MB | 67.691 |
| **JFrog** (sanity, nhãn v3) | `ml_JFrog.csv` — 55.666 dòng · 2,2 MB | `(55.667, 24)` · 5,3 MB | `(12.166, 64)` · 3,1 MB | 12.165 |
| **JFrog_comp** (ablation composite) | `ml_JFrog_comp.csv` — 55.666 dòng | `(55.667, 24)` | `(12.166, 64)` | 12.165 |
| **Mojang** (scale, pilot 50k) | `ml_Mojang.csv` — 210.411 dòng · 8,6 MB | `(210.412, 24)` · 20,2 MB | `(49.517, 64)` · 12,7 MB | 49.516 |
| **synth** (smoke test) | `ml_synth.csv` — 24 dòng | `(25, 24)` | `(8, 8)` | 7 |

Bảng kiểm tra chất lượng đã chạy (tất cả ✅):

- Dòng 0 của cả 2 array npy = vector 0 (đúng contract 1-based).
- `ts` trong CSV **đơn điệu tăng** (đã kiểm tra `is_monotonic_increasing` trên 3 dataset).
- `label=1`: JFrog 1.754 (3,15%) · Spring 9.598 (2,58%) · Mojang 116 (0,06%).
- `ts.min()` của Spring = **0** — xác nhận clamp timestamp âm đã hoạt động.
- `unique(u) = n_nodes` (12.165 / 67.691 / 49.516) — khớp node npy − 1.

Kèm theo: `data/build_mongo_summary.json` (stats từng build), `docs/eda/eda_{Spring,JFrog,Mojang}.md` (EDA markdown), `data/raw/ThePublicJiraDataset/` (artefact gốc + README + DataDefinition).

---

## 5. Xác minh end-to-end

Pipeline được xác minh bằng 2 lớp:

**(a) Smoke test định dạng** — dataset tổng hợp `ml_synth.*` (7 nodes, 24 sự kiện) chạy hết 3 epoch trong `train_self_supervised.py -d synth`, lưu model (`saved_models/synth_smoke-synth.pth`) → chứng minh format `csv+npy+_node.npy` hợp lệ với loader repo trên Python 3.13 + torch 2.14.

**(b) Training trên dữ liệu thật** (RTX 4060 Ti 16 GB, torch 2.14.0+cu130) — đọc chính xác các file §4, kết quả (chi tiết: báo cáo chính §1 + Phụ lục D):

| Run | Task | Kết quả test |
|---|---|---|
| TGN JFrog | T2 link prediction | AUC **0.9986** (old) / **0.9823** (new, 1.216 nút inductive) |
| TGN Spring | T2 | AUC **0.9997** / **0.9988** (6.769 nút inductive) |
| TGN Mojang | T2 | AUC **0.9989** / **0.9937** (4.951 nút inductive) |
| **TGN JFrog (label v3)** | **T1 bottleneck** | **AUC 0.839** (best epoch 15/30, early-stop đúng) |
| **TGN Spring (label v3)** | **T1 bottleneck** | **AUC 0.768** (best epoch 17/30) — cả 2 instance **vượt mục tiêu ≥0,75** |
| TGN JFrog, v3, bỏ feature loại link (`nl1`, 2026-10-04) | T1 | AUC **0,620** (trung bình 3 lần: 0,630 / 0,631 / 0,598) |
| TGN JFrog, v3, `nl1` + bỏ sự kiện link (`nl2`) | T1 | AUC **0,484** (0,523 / 0,459 / 0,469) — ngang ngẫu nhiên |
| DyRep JFrog (baseline) | T2 | AUC 0.9901 / 0.8893 — TGN **+9.3 AUC** trên new nodes |
| Ablation composite (cùng model/data) | T1 | AUC 0.578; composite+dwell < 0.5 (leakage) — **chứng minh thiết kế nhãn quyết định** |

**Kết luận xác minh:** (1) định dạng xuất ra tương thích hoàn toàn với loader repo; (2) dữ kiện thời gian đúng thứ tự (không crash invariant memory — sau khi fix timestamp âm); (3) ~~nhãn v3 **học được** (AUC 0.77–0.84 > mục tiêu) — tín hiệu bottleneck tồn tại trong dòng sự kiện Jira~~ **đính chính 2026-10-04: AUC đến từ rò rỉ nhãn qua feature loại link (0,835 → 0,620 → 0,484), chưa có bằng chứng tín hiệu bottleneck học được**; (4) chế độ inductive hoạt động (nút mới được đánh giá đúng, TGN vượt DyRep nhiều nhất ở đây — memory cho issue chưa thấy).

---

## 6. Phát hiện & sửa lỗi chất lượng dữ liệu

Các vấn đề **phát hiện trực tiếp trên dump** trong P0 và cách xử lý (bằng chứng: mã nguồn `jira_adapter/` + số liệu §2.3/§4):

| # | Vấn đề | Tác động nếu bỏ qua | Xử lý |
|---|---|---|---|
| 1 | **Spring: 58 timestamp âm** — placeholder `1969-12-31T16:00:00.000+0000` (epoch −28.800s) từ Jira IDE cũ (issue `IDE-*`) | Vi phạm invariant TGN `last_update(0) ≤ ts` → crash *"Trying to update memory to time in the past"* ngay batch 0 epoch 0 (JFrog/Mojang không có) | `_safe_ts()` clamp `ts = max(ts, 0)` — giữ thứ tự thời gian; 26 sự kiện kẹp về t=0 (đã xác minh `ts.min()=0` trong CSV) |
| 2 | **Changelog item: giá trị mới ở trường `set`**, không phải `to` như API v2 tài liệu | Mọi sự kiện `status` mất `to` → feature/ranking hỏng | Đọc `to` → fallback `set` (`events.py:110`) |
| 3 | **`fields.status`/`priority` là dict** `{"name": …}` không phải string | `startswith`/normalize crash hoặc sai | Lấy `.name` trước khi normalize (`labels.py:70-71`, `normalize_priority`) |
| 4 | **Link tự tham chiếu** (`outwardIssue == inwardIssue == key`) | Sự kiện rác u==v trùng lặp | Loại khi phát sinh (smoke test đã bắt bug này) |
| 5 | **Shape dump ≠ API v2** (changelog dict, `fields.issuelinks`, `fields.comments`) | Adapter đọc API "sách giáo khoa" sẽ rỗng 100% | `normalize_doc()` idempotent xử lý cả 2 shape (§3.2a) |
| 6 | **`random.sample(set)`** — Python 3.13 không cho phép (repo gốc viết cho 3.7) | Crash khi split inductive | `sorted(test_node_set)` trước khi sample (`data_processing.py:83`) |
| 7 | **Early-stop + save checkpoint bị dedent ra ngoài vòng epoch** (`train_supervised.py`) | Chạy hết 30 epoch, best model không được lưu → `FileNotFoundError` khi load | Sửa indent (phải nằm trong loop) — đã xác minh early-stop hoạt động (best epoch 15/17/22 như bảng §5) |

---

## 7. Giới hạn đã biết

Ghi nhận để đánh giá sensitivity ở giai đoạn sau (không ảnh hưởng đến tính hợp lệ của kết quả P0):

1. **Issue links không có timestamp** (giới hạn của Jira API v2) → thời điểm sự kiện link xấp xỉ bằng `created` của issue nguồn. *An toàn về phía "không nhìn tương lai"* (cả 2 issue đều tồn tại trước thời điểm đó) nhưng có thể trễ so với thời điểm thật. JFrog có sẵn trường `field:"Link"` trong changelog (link CÓ timestamp) — chưa dùng, là cải tiến hàng đầu cho v2.
2. **Mỗi link = 2 sự kiện** (xuất hiện trong document cả 2 issue) — chủ đích (cập nhật memory 2 nút) nhưng làm số đếm link trong EDA phải chia đôi.
3. **Nhãn gắn trên sự kiện `status/assignee/priority`** (không gắn `link/comment`) để tránh noise — sự kiện link/comment trong CSV là mẫu âm (label=0).
4. **Context dự án (p90-dwell, max-links) dùng trạng thái cuối document** — xấp xỉ chấp nhận được cho v1 (chỉ còn ý nghĩa với biến thể composite); v3 không phụ thuộc context này.
5. **Đồ thị đơn v1:** sự kiện assignee/comment là self-loop (v = issue) — lớp B2 (assignee-level) chưa tách nút developer; chế độ bipartite (`--bipartite` của repo) đã sẵn sàng, để P2.
6. **Assignee anonymized (UUID)** — không mapping được về vai trò/nhóm người → phân tích B2 theo nhóm không khả thi.
7. **Mojang pilot 50k/421k issue** (giới hạn RAM 30 GB khi nạp toàn bộ vào list) — build đầy đủ cần streaming theo batch (P2).
8. ~~**Priority gần như hằng số** trên JFrog (100% "normal")~~ **(sai — bug chuẩn hóa, đã sửa 2026-10-04; xem đính chính đầu báo cáo)** → feature priority ít giá trị ở instance này (đã thể hiện ở kết quả composite 0.578).
9. **2/16 instance offline** (MariaDB, Mindville) — ngoài phạm vi pilot.
10. **Thời gian trong ngày (sin/cos)** tính theo epoch (UTC) — hợp lý cho dữ liệu công khai, nhưng không phân biệt múi giờ tổ chức.

---

## 8. Tái lập

Môi trường: Python 3.13.9 · torch 2.14.0+cu130 (GPU RTX 4060 Ti 16 GB) · pymongo · mongod 9.0.2 local (`127.0.0.1:27017`, DB `JiraReposAnon` — 2.686.282 docs, 16/16 collection, restore 0 failures; công cụ ở `.tools/`).

```bash
cd /mnt/Data/0.Workspace/0.SourceCode/tgn

# 0) (một lần) restore dump từ Zenodo vào MongoDB local
#    mongorestore --archive data/raw/ThePublicJiraDataset/3.\ DataDump/mongodump-JiraReposAnon.archive \
#                 --db JiraReposAnon --host 127.0.0.1:27017

# 1) Liệt kê 16 instance + số issue
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --list

# 2) EDA + build 1 instance → data/ml_{instance}.* + docs/eda/eda_{instance}.md
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance Spring --out data --eda-out docs/eda
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog  --out data --eda-out docs/eda
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance Mojang --out data --limit 50000

#    (biến thể ablation composite)
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog --label-mode composite --as-name JFrog_comp

# 3) Training — lưu ý 3 cờ chiều: --node_dim 64 --memory_dim 64 --message_dim 64
python train_self_supervised.py -d JFrog --bs 128 --n_degree 10 --n_head 4 --n_epoch 20 \
  --n_layer 2 --lr 0.001 --patience 5 --node_dim 64 --time_dim 64 --backprop_every 4 \
  --use_memory --embedding_module graph_attention --message_function mlp --memory_updater gru \
  --message_dim 64 --memory_dim 64 --prefix tgn_jira
python train_supervised.py -d JFrog --node_dim 64 --time_dim 64 --bs 128 --n_degree 10 \
  --n_head 4 --n_epoch 30 --n_layer 2 --lr 0.001 --patience 5 \
  --use_memory --embedding_module graph_attention --message_function mlp --memory_updater gru \
  --message_dim 64 --memory_dim 64 --prefix tgn_jira
```

---

## 9. Tham chiếu mã nguồn & nguồn dữ liệu

**Mã nguồn pipeline (workspace này):**

| File | Vai trò |
|---|---|
| `jira_adapter/normalize.py` | `normalize_doc` (L83–133), `LINK_TYPE_MAP` (L13–50), `PRIORITY_NORM` (L138–142), `ISSUE_THEME_MAP` (L155–172) |
| `jira_adapter/events.py` | `extract_events` (L84–161), `_safe_ts` clamp ts âm (L70–81), `_to_epoch` (L42–63) |
| `jira_adapter/labels.py` | `assign_labels` (L160–238), `build_states` (L51–95), `b1_score` (L125–149), `label_topq` (L152–157) |
| `jira_adapter/to_tgn.py` | `write_instance` (L87–176), `edge_feature` (L53–74), `node_features` (L77–84), `EDGE_DIM=24` (L43) |
| `jira_adapter/eda.py` | `eda_instance` (L96–175), `render_markdown` (L180–218) |
| `jira_adapter/build_mongo.py` | driver MongoDB (L72–105, CLI L108–157) |
| `utils/preprocess_data.py` | định dạng tham chiếu của repo (L8–36, L60–78) |
| `utils/data_processing.py` | loader + split thời gian (L52–159), node-classification (L18–49) |
| `data/build_mongo_summary.json` | stats build (JFrog_comp mẫu) |
| `docs/eda/eda_{Spring,JFrog,Mojang}.md` | EDA per-instance |
| `jira_adapter/README.md` | tài liệu gói adapter (feature dims, shape dump, giới hạn) |

**Báo cáo liên quan:** `docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md` — §2 phát biểu bài toán, §4 khảo sát dataset, §6.1 thiết kế nhãn, §6.3 pipeline đề xuất, Phụ lục D (tiến độ P0 + lịch sử thiết kế nhãn v1/v2/v3), `docs/rubric-label-audit-bottleneck.md` (rubric label audit).

**Nguồn dữ liệu & trích dẫn:**

1. Montgomery L, Lüders C, Maalej W. *An Alternative Issue Tracking Dataset of Public Jira Repositories.* MSR 2022 — [arXiv:2201.08368](https://arxiv.org/abs/2201.08368); Zenodo record **15719919** (CC-BY-4.0); artefact: <https://github.com/IoanaCovataru/ThePublicJiraDataset>.
2. Rossi E, et al. *Temporal Graph Networks for Deep Learning on Dynamic Graphs.* ICML 2020 GRL — [arXiv:2006.10637](https://arxiv.org/abs/2006.10637) (repo mã nguồn trong workspace).
