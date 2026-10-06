# jira_adapter — The Public Jira Dataset → TGN event stream

Package chuyển dữ liệu **The Public Jira Dataset** (Montgomery–Lüders–Maalej, MSR 2022;
Zenodo record 15719919, CC-BY-4.0) thành đúng format mà repo TGN này tiêu thụ,
kèm gắn nhãn bottleneck theo §6.1 của báo cáo
(`docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md`).

## Cấu trúc

| File | Vai trò |
|---|---|
| `normalize.py` | Bảng chuẩn hóa link type / priority / issue-theme + **`normalize_doc()`** (đưa shape dump về shape chuẩn; idempotent) |
| `events.py` | Issue document → list `Event(u, v, ts, kind, detail)` (chấp nhận cả shape dump) |
| `labels.py` | Gắn nhãn bottleneck v1: `B1_score` composite + top-q% theo dự án (point-in-time) |
| `to_tgn.py` | Xuất `data/ml_{name}.csv` + `.npy` + `_node.npy` đúng format `utils/preprocess_data.py` của repo (node features THỰC, padding zero lên 64 chiều) |
| `eda.py` | EDA per-instance → markdown (số liệu quyết định P1) |
| `build_mongo.py` | **Driver chính**: đọc instance từ MongoDB (đã restore dump) → EDA + events + labels + files |
| `build.py` | Driver dùng file JSON (nếu xuất issue ra file) |
| `download_dataset.sh` | Tải dataset từ Zenodo + công cụ MongoDB (không cần root) → restore vào mongod local |
| `dossier.py` | Hồ sơ issue hồi cứu (dòng thời gian trạng thái + percentile dwell, link, comment, tín hiệu F/I) cho gắn nhãn bằng LLM |
| `sampling.py` | Chọn mẫu pilot 3 tầng (v3 / ứng viên heuristic / ngẫu nhiên) → hồ sơ + bảng chấm gold — xem `docs/phuong-an-gan-nhan-bottleneck-bang-llm.md` |

## Loại sự kiện (kind)

- `status` — chuyển trạng thái (changelog field=status)
- `assignee` — thay đổi người phụ trách (v1: self-loop, v2: bipartite)
- `priority` — thay đổi ưu tiên
- `link` — issue link (Block/Depend/Epic/... đã chuẩn hóa)
- `comment` — comment (tùy chọn)

## Feature dimensions (cứng, đã test)

- Edge: **24** = kind(5) + link_type(9) + direction(1) + priority(1) + theme(5) + time-of-day(2) + đệm(1)
- Node: **8 chiều ngữ nghĩa** = priority(1) + theme(5) + has_block(1) + log1p(n_links) normalized(1),
  **padding zero lên 64** (mặc định `node_out_dim=64`) — vì repo TGN yêu cầu
  `memory_dim == node feature dim` (`embedding_module.py: memory + node_features`).
  Chạy training với `--memory_dim 64 --node_dim 64`.

## Shape document trong dump (KHÁC Jira API v2 "gốc" — đã xác minh trực tiếp)

- `changelog` = dict `{startAt, maxResults, total, histories:[{id, author, created, items}]}`
  (không phải list). `normalize_doc()` rút `histories` ra list.
- **Issue links nằm trong `fields.issuelinks`** (lowercase), comments trong
  `fields.comments` — không có top-level `issueLinks`/`comments`.
- Assignee anonymized: `<<|author_name|<uuid>|>>` (uuid ổn định → vẫn dùng làm node).
- Changelog KHÔNG truncate (`total == len(histories)` — đã verify 5 instance lớn).
- JFrog có changelog `field: "Link"` (sự kiện link CÓ timestamp) — chưa dùng ở v1.

## Tải dataset gốc & restore vào MongoDB (một lần)

Nguồn: Zenodo record **15719919**, file `2025-06-23 ThePublicJiraDataset.zip`
(5.81GB, md5 `02f85309d966092ea130ca0797aea795`). Bên trong có
`3. DataDump/mongodump-JiraReposAnon.archive` (mongodump `--gzip`, ~60GB khi restore,
2,686,282 docs / 16 instance). Cần ~75GB đĩa trống, `curl`, `unzip`; **không cần root**.

```bash
# Tất cả trong một lệnh: tải zip (resume được) + kiểm md5 + giải nén -> data/raw/,
# tải mongod + mongodb-database-tools (tarball) -> .tools/, khởi động mongod
# @127.0.0.1:27017 (dbpath .tools/mongo-data), mongorestore vào db JiraReposAnon
bash jira_adapter/download_dataset.sh

# Hoặc từng bước
bash jira_adapter/download_dataset.sh download   # chỉ tải + giải nén dataset
bash jira_adapter/download_dataset.sh tools      # tải mongod / mongorestore
bash jira_adapter/download_dataset.sh start      # khởi động mongod (cần sau mỗi lần reboot)
bash jira_adapter/download_dataset.sh restore    # mongorestore (~15-30 phút)
bash jira_adapter/download_dataset.sh stop       # tắt mongod
```

Tùy chỉnh bằng biến môi trường: `RAW_DIR` (mặc định `data/raw`), `TOOLS_DIR` (`.tools`),
`MONGO_PORT` (27017), `MONGO_VER` (9.0.2), `TOOLS_VER` (100.19.1), `MONGO_OS`
(`ubuntu2404`; distro khác: `ubuntu2204`, `rhel93`, ... — xem mongodb.com/try/download).
Nếu đổi port, truyền `--host 127.0.0.1:<port>` cho `build_mongo` / `sampling`.

Tải thủ công (nếu không dùng script):

```bash
curl -fL -C - -o data/raw/ThePublicJiraDataset.zip \
  "https://zenodo.org/api/records/15719919/files/2025-06-23%20ThePublicJiraDataset.zip/content"
mongorestore --gzip --archive="data/raw/ThePublicJiraDataset/3. DataDump/mongodump-JiraReposAnon.archive" \
  --nsFrom "JiraReposAnon.*" --nsTo "JiraReposAnon.*"
```

## Chạy (dataset đã restore vào MongoDB local)

```bash
# 0) (một lần) tải + restore dump -> xem mục "Tải dataset gốc" ở trên

# 1) Liệt kê instance + số issue
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --list

# 2) EDA + build 1 instance -> data/ml_{instance}.* + docs/eda/eda_{instance}.md
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog --out data --eda-out docs/eda
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance Mojang --out data --limit 50000

# 2b) Build không rò rỉ nhãn (bỏ feature suy ra từ loại link) — bắt buộc khi dùng nhãn v3
PYTHONPATH=.pylibs python -m jira_adapter.build_mongo --instance JFrog --out data --leak-safe --as-name JFrog_ls

# 2c) Mẫu pilot gắn nhãn bằng LLM: hồ sơ issue + bảng chấm gold -> data/llm_pilot/JFrog/
PYTHONPATH=.pylibs python -m jira_adapter.sampling --instance JFrog --out data/llm_pilot

# 3) Huấn luyện (GPU: chạy với sandbox mở rộng vì /dev/nvidia* bị ẩn ở chế độ mặc định)
python train_self_supervised.py -d JFrog --bs 128 --n_degree 10 --n_head 4 --n_epoch 20 \
  --n_layer 2 --lr 0.001 --patience 5 --node_dim 64 --time_dim 64 --backprop_every 4 \
  --use_memory --embedding_module graph_attention --message_function mlp --memory_updater gru \
  --message_dim 64 --memory_dim 64 --prefix tgn_jira
python train_supervised.py -d JFrog ... --prefix tgn_jira   # load saved_models/tgn_jira-JFrog.pth
```

## Giới hạn dữ liệu đã biết (ghi nhận để đánh giá sensitivity ở P2)

1. **issueLinks không có timestamp** (Jira API v2) → thời điểm sự kiện link xấp xỉ
   `created` của issue nguồn. An toàn về phía "không nhìn tương lai" nhưng có thể trễ.
2. Link xuất hiện trong document của **cả 2** issue → trong event stream mỗi link tạo
   2 sự kiện (mỗi hướng 1) — đây là chủ đích (cập nhật memory cho cả 2 nút); trong
   EDA số đếm link cần chia đôi để ra số link độc lập.
3. Nhãn v1 gắn trên sự kiện `status/assignee/priority` của issue (không gắn trên
   `link/comment`) để tránh noise.
4. `labels.py` dùng trạng thái **cuối document** làm context (p90 dwell, max links)
   cho mọi thời điểm t — xấp xỉ chấp nhận được ở v1; P2 cải thiện bằng
   snapshot theo thời gian.

## Nhãn (label) — thiết kế cuối cùng P0

- **v3 (mặc định, `--label-mode dependency`)**: `LABEL(i,t)=1` iff issue có ≥1 link
  **Block/Depend** (quan hệ chặn/chờ). Phân bố cân bằng theo split thời gian
  (JFrog 3.7/3.1/1.2%, Spring 2.8/3.0/1.1%).
- **Ablation (`--label-mode composite [--use-dwell]`)**: top-5%/dự án theo B1_score
  (ranking + tie-break). Đã đo: composite static → AUC 0.578; composite+dwell →
  AUC < 0.5 (leakage temporal) — so với v3: **AUC 0.839** (JFrog). Chi tiết:
  báo cáo `docs/bao-cao-tgn-jira-phat-hien-diem-nghen.md` Phụ lục D §6.
- Build dataset ablation:
  `python -m jira_adapter.build_mongo --instance JFrog --label-mode composite --as-name JFrog_comp`

## Kết quả training (P0, RTX 4060 Ti, torch 2.14)

| Run | Instance | Task | Kết quả |
|---|---|---|---|
| T2 TGN | JFrog | link-pred (self-sup) | test AUC 0.9986 (old) / 0.9823 (new) |
| T2 TGN | Spring | link-pred | test AUC 0.9997 / 0.9988 (6,769 inductive nodes) |
| T2 TGN | Mojang (50k) | link-pred | đang chạy |
| T1 TGN | JFrog (label v3) | bottleneck | **test AUC 0.839** |
| T1 TGN | JFrog (composite ablation) | bottleneck | test AUC 0.578 |
| T1 TGN | Spring (label v3) | bottleneck | đang chạy (val ~0.82) |
| T2 DyRep | JFrog | link-pred (baseline) | test AUC 0.9901 / 0.8893 — TGN +9.3 AUC trên new nodes |

- Smoke test adapter: document tổng hợp → events (đã sửa bug `outwardIssue==key`,
  shape `set` vs `to`, priority/status dict, timestamp âm clamp về 0).
- End-to-end trên dữ liệu thật: JFrog 55,666 events · Spring 372,553 events ·
  Mojang 210,411 events (pilot 50k). File `data/ml_*.{csv,npy,_node.npy}` hợp lệ.
- File toy: `data/ml_synth.*` — smoke-test training loop.
- Dev tool: `debug_spring_order.py` (instrumentation "Trying to update memory
  to time in the past").
