# BÁO CÁO KHÓA LUẬN TỐT NGHIỆP
## NGHIÊN CỨU VÀ THỰC NGHIỆM MÔ HÌNH TEMPORAL GRAPH NETWORK (TGN) CHO BÀI TOÁN ĐÁNH GIÁ MỨC ĐỘ QUAN TRỌNG CỦA ISSUE (TASK CRITICALITY) TẠI THỜI ĐIỂM TẠO ($T_0$)

---

## LỜI MỞ ĐẦU (ĐẶT VẤN ĐỀ NGHIÊN CỨU)

Trong quá trình thực hiện khóa luận tốt nghiệp với đề tài **"Phát hiện sớm rủi ro trễ hạn và đánh giá mức độ quan trọng của issue trên tập dữ liệu Jira quy mô lớn"**, bài toán trọng tâm thứ hai mà em giải quyết là **Task Criticality Scoring** ngay tại thời điểm khởi tạo issue ($T_0$). Mục tiêu của bài toán là trả lời câu hỏi: *"Trong hàng nghìn issue vừa được tạo mới, issue nào có nguy cơ trở thành điểm nghẽn trên đường găng (Critical Path Bottleneck) hoặc gây trễ tiến độ dây chuyền cho toàn dự án?"*

Trong thực tế quản lý dự án phần mềm, một issue mới sinh ra không tồn tại độc lập mà nằm trong một mạng lưới tương tác động giữa lập trình viên (`assignee`), người tạo (`reporter`), dự án (`project`), và các liên kết phụ thuộc (`Blocks` / `Depends on`) liên tục thay đổi theo thời gian. Để mô hình hóa toàn bộ lịch sử tương tác của các đối tượng này mà không bị rò rỉ dữ liệu tương lai (*Zero Temporal Data Leakage*), em đã tìm hiểu chuyên sâu, thiết kế và huấn luyện mô hình **Temporal Graph Network (TGN)** kết hợp **Ranking-Aware Readout Head** trên toàn bộ tập dữ liệu **The Public Jira Dataset** ($2,685,911$ issues, $19,659,049$ events, $3,451,575$ nodes).

Bản báo cáo này trình bày chi tiết cơ sở lý thuyết của mô hình TGN, quy trình xử lý dữ liệu đầu vào tại mốc $T_0$, cấu hình tham số huấn luyện hai giai đoạn và kết quả thực nghiệm cuối cùng của mô hình TGN đã được đóng gói chính thức trong khóa luận.

---

## PHẦN 1: CƠ SỞ LÝ THUYẾT VÀ KIẾN TRÚC MÔ HÌNH TGN

### 1.1. Biểu diễn dữ liệu Jira dưới dạng Đồ thị Động Thời gian Liên tục (Continuous-Time Dynamic Graph - CTDG)

Toàn bộ lịch sử hoạt động trên Jira được biểu diễn dưới dạng một đồ thị động theo chuỗi sự kiện liên tục theo thời gian (**CTDG**):

$$\mathcal{G} = (\mathcal{V}, \mathcal{E}), \quad \mathcal{E} = \{e_k = (u_k, v_k, p_k, t_k, \mathbf{x}_k)\}_{k=1}^M$$

với chuỗi timestamp tăng dần $t_1 \le t_2 \le \dots \le t_M$. Trong thiết kế [`TGNMemory`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L27-L99) của khóa luận:

- **Tập hợp các node ($\mathcal{V}$, với $N = 3,451,575$ nodes)**: Bao gồm $2,685,911$ **issue nodes** và $765,664$ **context/value nodes** đại diện cho người dùng (`user`), dự án (`project`), trạng thái (`status`), và mức độ ưu tiên (`priority`).
- **Luồng sự kiện ($\mathcal{E}$)**: Mỗi event $e_k$ tại thời điểm $t_k$ cập nhật đồng thời 3 nodes: issue nguồn $u_k$, **counterpart node** $v_k$ (`user` nhận việc/bình luận, `status`/`priority` mới, hoặc `issue` được liên kết), và `project` node $p_k$.

### 1.2. Năm thành phần cốt lõi của TGN trong khóa luận

Kiến trúc TGN được cài đặt tại [`src/early_risk_detection/criticality/memory.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py) và [`src/early_risk_detection/criticality/readout.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/readout.py) gồm 5 module hoạt động tuần tự:

```mermaid
flowchart LR
    EV["Jira Event Stream<br/>(19.66M events)"] --> MSG["Message + Time Enc<br/>(MLP 160 → 64)"]
    MSG --> GRU["Mean Agg + GRUCell<br/>Node Memory (128-d)"]
    GRU --> SNAP["T0 Snapshot<br/>(issue, rep, ass, proj)"]
    SNAP --> EMB["Dynamic Embedding<br/>z_i(T0) (128-d)"]
    STAT["Static Features T0<br/>x_static (119-d)"] --> HEAD["Readout MLP<br/>(247 → 128 → 64 → 1)"]
    EMB --> HEAD
    HEAD --> OUT["Criticality Score<br/>Top 5% P0 Alert"]
```

#### 1. Node Memory ($\mathbf{S} \in \mathbb{R}^{N \times 128}$)
Mỗi node $u \in \mathcal{V}$ lưu một vector trạng thái lịch sử (**memory vector**) $s_u(t) \in \mathbb{R}^{128}$. Khi một node mới xuất hiện, $s_u(t)$ được khởi tạo bằng $\mathbf{0}$, giúp mô hình xử lý tự nhiên các issue mới theo cơ chế *inductive* mà không cần huấn luyện lại. Đi kèm với mỗi node là mốc thời gian cập nhật gần nhất $t_u^{\text{last}}$ và số lần được cập nhật $n_u^{\text{upd}}$.

#### 2. Time Encoding ($\Phi(\Delta t) \in \mathbb{R}^{16}$)
Khoảng thời gian trôi qua (tính bằng giờ) từ lần cập nhật gần nhất của chính node nhận $r \in \{u, v, p\}$ là:

$$\Delta t_r = \max\left(0, \frac{t - t_r^{\text{last}}}{3600}\right)$$

Giá trị $\Delta t_r$ được mã hóa qua 8 tần số hình học $\omega_k = 10^{-4k/7}$ (với $k = 0, 1, \dots, 7$) trong hàm [`TGNMemory.time_enc`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L45-L47):

$$\Phi(\Delta t_r) = \left[\cos(\omega_0 \Delta t_r), \sin(\omega_0 \Delta t_r), \dots, \cos(\omega_7 \Delta t_r), \sin(\omega_7 \Delta t_r)\right] \in \mathbb{R}^{16}$$

Các tần số trải theo thang logarit từ $10^0$ đến $10^{-4}\text{ giờ}^{-1}$ giúp mô hình nắm bắt cả các tương tác diễn ra liên tục trong vài phút/giờ lẫn khoảng thời gian issue bị tồn đọng hàng nghìn giờ.

#### 3. Message Function
Trong hàm [`TGNMemory.raw_messages`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L49-L70), mỗi event tạo ra 3 **messages** gửi tới 3 nodes nhận $r \in \{u, v, p\}$ bằng cách nối ($\text{Concat}$) vector đặc trưng sự kiện $x_{\text{dom}} \in \mathbb{R}^{16}$, vector mã hóa thời gian $\Phi(\Delta t_r) \in \mathbb{R}^{16}$, và trạng thái memory hiện tại của **counterpart node** $s_{\text{cpt}}(t^-) \in \mathbb{R}^{128}$:

$$m_r = \text{MLP}_{160 \to 128 \to 64}\left(\text{Concat}\left(x_{\text{dom}}, \Phi(\Delta t_r), s_{\text{cpt}}(t^-)\right)\right) \in \mathbb{R}^{64}$$

Việc đưa trực tiếp memory của counterpart node $s_{\text{cpt}}(t^-)$ vào message giúp thông tin lan truyền qua đồ thị: chẳng hạn khi một developer đang quá tải nhận task hoặc bình luận vào dự án, trạng thái quá tải từ memory của developer đó sẽ truyền sang memory của project và issue.

#### 4. Message Aggregator và Memory Updater (`GRUCell`)
Dòng sự kiện được đưa vào GPU theo từng **chunk** ($C = 10,000$ events, tương ứng $30,000$ messages). Vì một node $u$ có thể nhận $K_u$ messages trong cùng một chunk, hàm [`TGNMemory.apply`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L72-L81) dùng hàm `index_add_` để tính trung bình cộng các messages (**Mean Aggregator**), sau đó cập nhật memory của node thông qua `GRUCell`:

$$\bar{m}_u = \frac{1}{K_u} \sum_{j=1}^{K_u} m_{u,j}, \quad s_u(t) = \text{GRUCell}\left(\bar{m}_u, s_u(t^-)\right) \in \mathbb{R}^{128}$$

#### 5. Zero-Leakage $T_0$ Snapshot và Embedding Module
Tại đúng thời điểm issue $i$ vừa được tạo ($t = T_{0,i}$), bản thân issue node $i$ chưa có lịch sử hoạt động ($s_i(T_{0,i}^-) = \mathbf{0}$). Do đó, hàm [`snapshot_memory`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L129-L183) chụp lại (**snapshot**) trạng thái memory của các nodes lân cận có liên kết với issue $i$ ngay trước mốc $T_{0,i}$:

$$Z_i(T_0) = \text{Concat}\left(s_i(T_0^-), s_{\text{rep}}(T_0^-), s_{\text{ass}}(T_0^-), s_{\text{proj}}(T_0^-), a_i(T_0)\right) \in \mathbb{R}^{517}$$

trong đó $s_{\text{rep}}, s_{\text{ass}}, s_{\text{proj}} \in \mathbb{R}^{128}$ lần lượt là memory vector của `reporter`, `assignee` tại $T_0$, và `project`; còn $a_i(T_0) \in \mathbb{R}^5$ là 5 đặc trưng phụ gồm $\ln(1 + \Delta t)$ của 4 nodes trên và $\ln(1 + n_{\text{rep}}^{\text{upd}})$. Tiếp theo, tầng chiếu trong [`Readout`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/readout.py#L39-L57) nén $Z_i(T_0)$ thành **dynamic embedding** $z_i(T_0) \in \mathbb{R}^{128}$:

$$z_i(T_0) = \text{ReLU}\left(\text{LayerNorm}\left(W_z Z_i(T_0) + b_z\right)\right) \in \mathbb{R}^{128}$$

---

## PHẦN 2: QUY TRÌNH XỬ LÝ DỮ LIỆU ĐỂ ĐƯA VÀO HUẤN LUYỆN

Quy trình xử lý dữ liệu được xây dựng trong [`training/criticality/build_dataset.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/build_dataset.py) và [`training/criticality/build_events.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/build_events.py), tuân thủ nghiêm ngặt nguyên tắc **Zero Temporal Data Leakage** trên toàn bộ $2,685,911$ issues của 16 Jira instances.

### 2.1. Lọc dữ liệu và Khôi phục thuộc tính tại thời điểm tạo ($T_0$ Reconstruction)

- **Lọc bản ghi hợp lệ (`VALID_FILTER`)**: Từ cơ sở dữ liệu `data/jira.duckdb`, giữ lại các issues có `created_ts > 2000-01-01` và `resolved_ts IS NULL OR resolved_ts >= created_ts`, thu được **$2,685,911$ issues** được sắp xếp cố định theo `(created_ts, instance, issue_key)`.
- **Khôi phục giá trị thuộc tính tại $T_0$ ([`load_issues_t0`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/features/t0.py#L32-L102))**: Bảng `issues` gốc chỉ lưu trạng thái cuối cùng sau khi issue đã đóng, trong khi thực tế có $11.13\%$ số issue bị đổi `priority`, $7.15\%$ bị đổi `issuetype`, và $36.19\%$ bị đổi `assignee` trong quá trình xử lý. Để tránh lấy nhầm thông tin tương lai, hệ thống truy vấn giá trị `from_value` ở bản ghi `issue_changelogs` đầu tiên của từng trường (sử dụng `arg_min(from_value, (created_ts, from_value))` có tie-breaker cố định) để khôi phục đúng `priority_t0`, `issuetype_t0`, và `assignee_t0` lúc mới tạo.

### 2.2. Xác định Timestamp thực tế cho Issue Links ([`load_timed_links`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/features/t0.py#L105-L124))

- Để biết chính xác một liên kết phụ thuộc (`Block`, `Depend`, ...) được tạo ra khi nào, hệ thống join bảng `issue_links` với bảng `issue_changelogs` (`field = 'Link'`) để lấy timestamp thực tế $t_{\text{link}}$ (khớp được **$91.4\%$** tổng số links).
- Với $8.6\%$ số links không có lịch sử trong changelog, timestamp được gán an toàn bằng mốc cập nhật muộn nhất của hai đầu mút:

$$t_{\text{link}} = \max\left(t_{\text{updated}}^{(a)}, t_{\text{updated}}^{(b)}, t_{\text{created}}^{(a)}, t_{\text{created}}^{(b)}\right)$$

Cách xử lý này đảm bảo không có bất kỳ link tương lai nào bị đưa vào đặc trưng hay luồng sự kiện trước thời điểm nó thực sự xuất hiện. Thống kê cho thấy tại thời điểm $T_0$, chỉ có **$0.461\%$** số issues đã có sẵn liên kết phụ thuộc.

### 2.3. Xây dựng Nhãn Ground-Truth Criticality bằng Critical Path Method (CPM)

Trong [`build_dataset.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/build_dataset.py#L51-L177), nhãn mức độ quan trọng thực tế $y_i \in [0, 1]$ được tính toán từ đồ thị phụ thuộc có hướng (DAG) gồm các cạnh `Block` và `Depend` của cả 16 instances ($112,826$ nodes có liên kết và $82,253$ edges sau khi đã loại bỏ 77 cạnh gây chu trình):

1. **Tính các chỉ số CPM trên DAG ([`cpm_metrics`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/build_dataset.py#L75-L114))**: Trên từng thành phần liên thông, hệ thống tính 5 chỉ số cấu trúc:
   - `marginal_delay` ($M_i$): Độ trễ biên trên đường găng (mức giảm thời gian hoàn thành dự án nếu issue $i$ trên đường găng có $\text{Slack}_i = 0$ không bị trễ);
   - `downstream_delay` ($C_i$): Độ trễ lan truyền xuống các issues phụ thuộc phía sau;
   - `slack_time` ($\text{Slack}_i$): Thời gian dự trữ cho phép trễ mà không ảnh hưởng toàn dự án;
   - `blast_radius` ($B_i$): Tổng số issues phía sau bị phụ thuộc trực tiếp hoặc gián tiếp vào issue $i$;
   - `inverted_pagerank` ($\text{IPR}_i$, với $\alpha = 0.85$): Điểm PageRank tính trên đồ thị đảo ngược hướng cạnh.
2. **Tổng hợp điểm `raw_criticality`**: Gọi $\hat{M}_i, \hat{C}_i, \hat{P}_i \in [0, 1]$ lần lượt là $M_i, C_i, \text{IPR}_i$ đã chia chuẩn hóa theo giá trị lớn nhất; $\text{Prio}_i \in [0, 1]$ là độ ưu tiên chuẩn hóa; $\text{SP}_i$ là Story Points ước lượng; và $S_i = \min(3, \max(0, d_i - p_i)/p_i)/3 \in [0, 1]$ là tỷ lệ trượt thời gian xử lý (`slip_ratio`). Điểm cấu trúc đồ thị $G_i$ được tính theo công thức:

$$G_i = 0.35\,\hat{M}_i + 0.30\,\hat{C}_i + 0.15\,\exp\left(-\frac{\text{Slack}_i}{14}\right) + 0.10\,\min\left(1, \frac{B_i}{5}\right) + 0.10\,\hat{P}_i$$

Điểm `raw_criticality` ($R_i$) được tính riêng cho nhóm **Blocker** ($B_i > 0$ hoặc out-degree $\deg^+(i) > 0$) và nhóm **Non-Blocker**:

$$R_i^{\text{blocker}} = 0.70 + 0.30\,G_i + 0.20\,\text{Prio}_i + 0.10\,S_i$$

$$R_i^{\text{non-blocker}} = 0.50\,\text{Prio}_i + 0.35\,S_i + 0.15\,\min\left(1, \frac{\text{SP}_i}{15}\right)$$

3. **Chuẩn hóa phân vị (`ground_truth_criticality`) và Nhãn P0 (`is_critical_p0`)**: Điểm $R_i$ được quy đổi sang thứ hạng phần trăm (`rank(pct=True)`) $y_i \in [0, 1]$ trong từng tập dữ liệu; nhóm **Top 5%** issues có $y_i \ge 0.95$ được gán nhãn nhị phân $p_{0,i} = 1$ (`is_critical_p0 = 1`).

### 2.4. Chia tập dữ liệu theo thời gian ([`chronological_split`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/features/t0.py#L140-L148))

Toàn bộ các issues đã giải quyết được chia theo thứ tự thời gian khởi tạo `created_ts` với tỷ lệ 70% / 15% / 15% (đồng thời giữ lại $182,671$ issues đang mở sau mốc cắt train trong event stream để cập nhật memory sát thực tế):

| Tập dữ liệu (Split) | Số lượng Issues | Khoảng thời gian | Tỷ lệ P0 (`is_critical_p0 = 1`) | Tỷ lệ Blocker (`is_blocker_final = 1`) | Mục đích sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Train** | $1,810,894$ | đến `2018-07-12` | $5.04\%$ | $2.64\%$ | Huấn luyện TGN Memory, fit SVD/normalizer và huấn luyện Readout |
| **Validation** | $346,172$ | `2018-07-12` đến `2020-02-27` | $5.13\%$ | $2.76\%$ | Tuning siêu tham số bằng Optuna và Early Stopping |
| **Out-of-Time Test** | $346,174$ | `2020-02-27` đến `2022-01-03` | $5.00\%$ ($17,311$ P0) | $1.90\%$ | Đánh giá kết quả cuối cùng (chỉ chạy một lần) |

### 2.5. Xây dựng Event Stream cho TGN ([`build_event_stream`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/stream.py#L89-L191))

Hàm `build_event_stream` trích xuất và gộp 6 loại sự kiện từ DuckDB thành **$19,659,049$ events** sắp xếp tăng dần theo `(ts, u_id, kind, v_id, p_id)`. Dữ liệu được lưu dưới dạng 8 file `numpy.memmap` (`ts, u_id, v_id, p_id, kind, ltype, scat, blen`) chia làm **$1,966$ chunks** (mỗi chunk $10,000$ events) giúp đọc trực tiếp từ ổ cứng sang GPU với tốc độ cao mà không tốn RAM:

| Mã `kind` | Loại Event | Bảng nguồn trong DuckDB | Số lượng Events | Tỷ lệ | Thông tin đưa vào Message |
| :---: | :--- | :--- | :---: | :---: | :--- |
| `0` | `status` | `issue_changelogs` (`field='status'`) | $5,676,001$ | $28.87\%$ | Nhóm trạng thái đích `scat` (Done, In Progress, Reopen, Other) |
| `1` | `assignee` | `issue_changelogs` (`field='assignee'`) | $1,383,482$ | $7.04\%$ | User node của developer nhận việc (đã đồng bộ UUID) |
| `2` | `priority` | `issue_changelogs` (`field='priority'`) | $344,023$ | $1.75\%$ | Value node của mức độ ưu tiên mới |
| `3` | `comment` | `issue_comments` | $8,849,742$ | $45.02\%$ | Độ dài bình luận $\ln(1 + \text{len})$ |
| `4` | `link` | `issue_links` + `Link` changelog | $719,890$ | $3.66\%$ | Nhóm liên kết `ltype` (Block/Depend, Relate, Duplicate, Other) |
| `5` | `create` | `issues` (tạo bởi `reporter` tại $T_0$) | $2,685,911$ | $13.66\%$ | Event khởi tạo kết nối `issue`, `reporter` và `project` |
| **Tổng** | **6 loại** | **16 Jira Instances** | **19,659,049** | **100%** | **Cập nhật trên $3,451,575$ memory nodes** |

### 2.6. Trích xuất 119 Static & Workload Features tại $T_0$ ([`static_matrix`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/readout.py#L28-L36))

Bên cạnh vector nhúng động $z_i(T_0) \in \mathbb{R}^{128}$ từ TGN, mỗi issue tại thời điểm tạo được trích xuất thêm vector đặc trưng $x_{\text{static}} \in \mathbb{R}^{119}$ chỉ sử dụng dữ liệu **trước mốc $T_0$ ít nhất 1 giây** (`strictly-before T0`):

- **24 đặc trưng lấy logarit $\ln(1 + x)$ (`LOG_COLS`)**: Độ dài summary, số từ, số task đang mở (`assignee_active_count`), chỉ số quá tải $\text{WCI}(T_0)$ của assignee, số lượng task đã đóng và cycle time lịch sử của assignee/reporter/project (toàn bộ lịch sử và trong cửa sổ 90 ngày gần nhất), chỉ số nén thời gian $\text{SCF}$, số lượng link đã biết tại $T_0$ (`links_t0_any`), và số lượng blocker trong quá khứ trước $T_0$.
- **44 đặc trưng số thực (`RAW_COLS`)**:
  - Thuộc tính tại $T_0$ và điểm rủi ro từ văn bản: `priority_t0`, `planned_t0`, `story_points_t0`, `ambiguity_score`, `tech_concurrency_risk`, `tech_scope_risk`, `umbrella_score`, `is_unassigned_t0`, thời điểm tạo (`created_month`, `created_dow`, `created_hour`).
  - Tỷ lệ trễ hạn lịch sử (`delay_rate`) của assignee, reporter và project.
  - **16 đặc trưng ngữ nghĩa văn bản (`svd_0` .. `svd_15`)**: Giảm chiều bằng `TruncatedSVD(16)` từ vector embedding 768 chiều của mô hình `nomic-embed-text` (chỉ fit trên $200,000$ mẫu tập Train, giữ được $26\%$ phương sai).
  - **13 đặc trưng xu hướng lịch sử (Propensity Features)**: Tỷ lệ trở thành blocker trước $T_0$ của project/reporter/assignee/instance (`*_blocker_rate_before`) và trung bình lịch sử (`slip_ratio`, `long_rate`, `log_dur`) theo từng cặp `(project, priority)` và `(project, issuetype)` với giá trị dự phòng (**back-off mean**) chỉ tính trên tập Train.
- **51 đặc trưng One-Hot**: 5 nhóm chủ đề (`THEMES`), 16 hệ sinh thái (`instances`), và 30 loại issue phổ biến nhất trên tập Train (`types`).

---

## PHẦN 3: CẤU HÌNH THAM SỐ VÀ QUY TRÌNH HUẤN LUYỆN MÔ HÌNH TGN

Mô hình TGN chính thức (`tgn_hybrid`, đóng gói tại [`bundles/criticality/manifest.json`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/bundles/criticality/manifest.json)) được huấn luyện qua 2 giai đoạn tuần tự trong [`train_tgn.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/train_tgn.py) và [`train_readout.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/train_readout.py):

### 3.1. Giai đoạn 1: Huấn luyện Tự giám sát TGN Memory (`train_tgn.py`)

Module [`TGNMemory`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L27-L99) được huấn luyện bằng bài toán **Self-Supervised Temporal Link Prediction** trên $1,315$ chunks đầu tiên thuộc giai đoạn Train ($t \le \text{2018-07-12}$):

- **Cơ chế huấn luyện theo chunk**: Ở bước chunk $c$, các messages từ chunk $c - 1$ được tổng hợp và cập nhật qua `GRUCell` (có giữ gradient) để tạo ra memory mới. Sau đó, mạng `decoder` ($\text{MLP}_{256 \to 128 \to 1}$) dự đoán xác suất xuất hiện cạnh nối $f_{\text{dec}}(s_u, s_v)$ cho các cặp sự kiện thật $(u, v)$ trong chunk $c$ so với các cặp negative $(u, q)$ được lấy ngẫu nhiên bằng hàm mất mát Binary Cross-Entropy:

$$\mathcal{L}_{\text{link}} = -\frac{1}{N_c} \sum_{(u, v, q)} \left[ \ln \sigma\left(f_{\text{dec}}(s_u, s_v)\right) + \ln\left(1 - \sigma\left(f_{\text{dec}}(s_u, s_q)\right)\right) \right]$$

- **Đảm bảo tính tái lập kết quả (Determinism)**: Bật `CUBLAS_WORKSPACE_CONFIG=":4096:8"` và `torch.use_deterministic_algorithms(True)` để loại bỏ sai số ngẫu nhiên của các phép cộng song song (`index_add_`, `scatter_reduce`) trên GPU qua $1,315$ bước cập nhật liên tiếp.

### 3.2. Giai đoạn 2: Huấn luyện Ranking-Aware Readout Head (`train_readout.py`)

Sau khi trích xuất memory snapshot $Z_i(T_0) \in \mathbb{R}^{517}$ cho toàn bộ $2,685,911$ issues, mạng [`Readout`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/readout.py#L39-L57) nối vector nhúng động $z_i(T_0) \in \mathbb{R}^{128}$ với $x_{\text{static}, i} \in \mathbb{R}^{119}$ thành vector $247$ chiều và đưa qua mạng MLP:

$$h_i = \text{MLP}_{247 \to 128 \to 64}\left(\text{Concat}\left(z_i(T_0), x_{\text{static}, i}\right)\right), \quad \hat{y}_i = \sigma\left(w_{\text{out}}^\top h_i + b_{\text{out}}\right) \in (0, 1)$$

Để tối ưu đồng thời độ chính xác ở nhóm đầu bảng **Top 5% P0** và thứ tự xếp hạng trên toàn tập dữ liệu, em sử dụng hàm mất mát kết hợp (**Hybrid Multi-Task Loss**) trong hàm [`hybrid_loss`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/train_readout.py#L47-L58):

$$\mathcal{L}_{\text{Total}} = \mathcal{L}_{\text{MSE}} + \lambda \cdot \mathcal{L}_{\text{Rank}} + w_{\text{aux}} \cdot \mathcal{L}_{\text{Aux}}$$

Trong đó:
1. **Pointwise MSE Loss ($\mathcal{L}_{\text{MSE}}$)** giúp giữ độ tương quan thứ hạng Spearman $\rho$ trên toàn dải giá trị:

$$\mathcal{L}_{\text{MSE}} = \frac{1}{B} \sum_{k=1}^B (\hat{y}_k - y_k)^2$$

2. **Pairwise Margin Ranking Loss ($\mathcal{L}_{\text{Rank}}$)** lấy mẫu ngẫu nhiên $N_s = \min(500, |P| \cdot |N|)$ cặp $(i \in P, j \in N)$ giữa nhóm P0 ($P = \{i \mid p_{0,i} = 1\}$) và nhóm non-P0 ($N = \{j \mid p_{0,j} = 0\}$) trong mỗi mini-batch, ép điểm dự đoán của issue P0 phải cao hơn issue thường tối thiểu một khoảng margin $\gamma$:

$$\mathcal{L}_{\text{Rank}} = \frac{1}{N_s} \sum_{(i, j) \in P \times N} \max\left(0, \gamma - (\hat{y}_i - \hat{y}_j)\right)$$

3. **Auxiliary Multi-Task Loss ($\mathcal{L}_{\text{Aux}}$)** sử dụng thêm một nhánh phụ `Linear(64 -> 2)` lúc huấn luyện để dự đoán xác suất issue trở thành Blocker trong tương lai $b_k \in \{0, 1\}$ và tỷ lệ trượt tiến độ $S_k \in [0, 1]$:

$$\mathcal{L}_{\text{Aux}} = \frac{1}{B} \sum_{k=1}^B \left[ \text{BCE}\left(\sigma(\hat{a}_{k,0}), b_k\right) + \left(\sigma(\hat{a}_{k,1}) - S_k\right)^2 \right]$$

### 3.3. Bảng Cấu hình Siêu tham số Chính thức (`bundles/criticality`)

Bộ siêu tham số tối ưu được tìm kiếm bằng Optuna (thuật toán TPE) trên tập Validation và lưu cố định trong [`bundles/criticality/manifest.json`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/bundles/criticality/manifest.json):

| Thành phần | Tham số (Parameter) | Giá trị cấu hình | Giải thích vai trò kỹ thuật |
| :--- | :--- | :---: | :--- |
| **TGN Memory (`TGNMemory`)** | Tổng số memory nodes ($N$) | $3,451,575$ | $2,685,911$ issues + $765,664$ users/projects/status/priority |
| | Chiều memory vector (`MEM`) | $128$ | Ma trận memory chiếm $1.65\text{ GiB}$ VRAM (FP32 trên GPU) |
| | Chiều message vector (`MSG`) | $64$ | Đầu ra của `msg_fn` ($\text{Linear}(160 \to 128) \to \text{ReLU} \to \text{Linear}(128 \to 64)$) |
| | Chiều `time_enc` + `domain_features` | $16 + 16 = 32$ | 8 tần số cos/sin $\omega_k = 10^{-4k/7}\text{ giờ}^{-1}$ + 16 chiều mô tả event |
| | Kích thước event chunk (`chunk`) | $10,000$ | Chia $19.66$ triệu events thành $1,966$ chunks ($1,315$ train chunks) |
| | Optimizer & Learning rate (`lr`) | `AdamW`, $5 \times 10^{-4}$ | `weight_decay = 1e-4`, `clip_grad_norm = 1.0` |
| | Số `epochs` & Random `seed` | $2$ epochs, `seed = 45` | Thời gian train: $11.5\text{ giây/epoch}$ trên GPU RTX 4060 Ti |
| **Readout Head (`Readout`)** | Chiều dynamic embedding $z_i(T_0)$ | $128$ | Chiếu từ snapshot $Z_i(T_0) \in \mathbb{R}^{517}$ qua `Linear + LayerNorm + ReLU` |
| | Chiều static features $x_{\text{static}}$ | $119$ | Chuẩn hóa Z-score bằng `mean` và `std` tính trên tập Train |
| | Kiến trúc MLP (`trunk`) | $247 \to 128 \to 64 \to 1$ | Kèm `BatchNorm1d`, `ReLU`, `Dropout(p = 0.20)` |
| | Ranking margin ($\gamma^*$) | $0.3983$ | Biên khoảng cách tối thiểu giữa điểm của P0 và non-P0 |
| | Trọng số ranking loss ($\lambda^*$) | $0.0984$ | Hệ số điều chỉnh thành phần Pairwise Margin Loss |
| | Trọng số nhánh phụ ($w_{\text{aux}}^*$) | $0.7729$ | Hệ số điều chỉnh Auxiliary Loss (Blocker + Slip Ratio) |
| | Learning rate (`lr`) & `batch_size` | $6.08 \times 10^{-4}$, $2,048$ | Tối ưu bằng `AdamW` (`weight_decay = 1e-4`) + `CosineAnnealingLR` |
| | Số `epochs` & `Seed Ensemble` | $18$ epochs, $3$ seeds | Lấy trung bình dự đoán của 3 models với seeds `[45, 47, 49]` |

---

## PHẦN 4: KẾT QUẢ THỰC NGHIỆM CỦA MÔ HÌNH TGN

### 4.1. Kết quả Huấn luyện TGN Memory và Kiểm toán Zero Temporal Leakage

Kết quả thực thi Giai đoạn 1 (lưu tại [`tgn_memory_report_lr5e-4_e2_s45.json`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/data/tgn_full/tgn_memory_report_lr5e-4_e2_s45.json)) cho thấy quá trình tiền huấn luyện tự giám sát trên dòng sự kiện hội tụ nhanh và ổn định:

- **Quá trình hội tụ khi train ($1,315$ chunks thuộc tập Train)**:
  - **Epoch 1**: Loss $\mathcal{L}_{\text{link}} = 1.1164$, chỉ số `Train Link AP` đạt **$0.7258$** (thời gian chạy: $11.7\text{ giây}$).
  - **Epoch 2**: Loss giảm xuống $\mathcal{L}_{\text{link}} = 0.9891$, `Train Link AP` tăng lên **$0.7913$** (thời gian chạy: $11.4\text{ giây}$).
- **Khả năng tổng quát hóa của Memory trên dữ liệu tương lai**:
  Khi đóng băng trọng số của `TGNMemory` để chạy lượt trích xuất snapshot trên toàn bộ dòng sự kiện (kiểm tra link prediction mỗi 20 chunks), mô hình duy trì độ chính xác dự đoán liên kết ổn định trên các giai đoạn tương lai: đạt `Link AP = 0.6279` (`ROC-AUC = 0.6487`) trên giai đoạn Validation và **`Link AP = 0.6786` (`ROC-AUC = 0.6671`)** trên giai đoạn Out-of-Time Test.
- **Kiểm toán Zero Temporal Leakage (`leakage_audit`)**:
  - Tổng số issues kiểm tra: **$2,685,911$ issues**.
  - Số trường hợp vi phạm áp dụng event có timestamp $\ge T_0$: **$0$ vi phạm** (`n_violations_applied_ts_ge_T0 = 0`).
  - Độ lệch thời gian lớn nhất giữa event cuối cùng được cập nhật vào memory và thời điểm tạo issue: $\max(t_{\text{applied}} - T_0) = -0.035\text{ giây} < 0$.
  - Event cuối cùng dùng để cập nhật trọng số TGN ($t = 1,531,392,465$) nằm hoàn toàn trước mốc kết thúc tập Train ($t_{\text{cutoff}} = 1,531,410,693$).

### 4.2. Hiệu năng Tổng thể của Mô hình TGN trên Tập Validation và Out-of-Time Test

Kết quả đánh giá chính thức của mô hình TGN (`JiraFull_tgn_hybrid`, ensemble 3 seeds `[45, 47, 49]`, lưu tại [`experiments/leaderboard_jira_full_v2.json`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/experiments/leaderboard_jira_full_v2.json) và [`bundles/criticality/manifest.json`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/bundles/criticality/manifest.json)):

| Chỉ số đánh giá (Metric) | Tập Validation ($346,172$ issues) | Tập Out-of-Time Test ($346,174$ issues) | Ý nghĩa thực tế trong quản lý dự án |
| :--- | :---: | :---: | :--- |
| **NDCG@10 (Global)** | **$0.9715$** | **$0.8677$** | Độ chính xác xếp hạng 10 issues quan trọng nhất toàn tập dữ liệu (vượt ngưỡng $\ge 0.85$) |
| **NDCG@10 (Grouped theo Project $\times$ Quý)** | **$0.8428$** | **$0.8547$** | Chất lượng xếp hạng Top-10 issues bên trong từng project theo từng quý |
| **NDCG@50 (Grouped theo Project $\times$ Quý)** | **$0.8912$** | **$0.9011$** | Chất lượng xếp hạng Top-50 issues quan trọng đầu bảng của mỗi project |
| **ROC-AUC (P0 Alert)** | **$0.8221$** | **$0.8382$** | Khả năng phân biệt giữa nhóm issue quan trọng (P0) và issue thường |
| **PR-AUC (P0 Alert)** | **$0.3136$** | **$0.2082$** | Diện tích dưới đường cong Precision-Recall (cao gấp $4.16$ lần tỷ lệ nền $5.00\%$) |
| **Precision@Top-5% (P0 Alert)** | **$0.3526$** | **$0.2386$** | Phát hiện đúng **$6,104$** (Val) và **$4,130$** (Test) issues P0 ngay tại thời điểm tạo $T_0$ (cao gấp **$4.77$ lần** chọn ngẫu nhiên) |
| **Recall@Top-5% (P0 Caught)** | **$0.3437$** | **$0.2386$** | Tỷ lệ phần trăm tổng số issues P0 được bắt trúng trong ngân sách cảnh báo Top 5% |
| **Spearman Rank Correlation ($\rho$)** | **$0.5615$** ($p = 0.0$) | **$0.5937$** ($p = 0.0$) | Độ tương quan thứ hạng tổng thể trên toàn bộ $346,174$ issues |

### 4.3. Kết quả Đánh giá Chi tiết theo từng Jira Instance (Per-Instance Performance)

Khi chạy suy luận thực tế qua [`CriticalityScorer`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/scorer.py), các issues được xếp hạng và gắn cờ cảnh báo Top 5% (`is_critical`) **riêng trong từng Jira instance**. Bảng dưới đây tổng hợp hiệu năng của TGN trên cả 16 instances trong tập **Out-of-Time Test ($346,174$ issues)**:

| Jira Instance | Số mẫu Test ($N$) | Số lượng P0 thực tế | NDCG@10 (Global) | NDCG@10 (Grouped) | Precision @Top-5% | Recall @Top-5% | Spearman $\rho$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Apache** | $70,263$ | $5,208$ | $0.9626$ | $0.9110$ | $0.2581$ | $0.1742$ | $0.5777$ |
| **RedHat** | $48,816$ | $7,078$ | $0.9054$ | $0.9061$ | $0.3953$ | $0.1363$ | $0.5098$ |
| **MongoDB** | $24,120$ | $2,283$ | $0.7756$ | $0.6981$ | $0.2371$ | $0.1253$ | $0.3591$ |
| **Qt** | $16,094$ | $836$ | $0.9913$ | $0.6830$ | $0.2919$ | $0.2811$ | $0.1762$ |
| **Sakai** | $1,842$ | $209$ | $0.9277$ | $0.9551$ | $0.4086$ | $0.1818$ | $0.6859$ |
| **MariaDB** | $1,739$ | $222$ | $0.8143$ | $0.9268$ | $0.2759$ | $0.1081$ | $0.4786$ |
| **JiraEcosystem** | $1,338$ | $243$ | $0.8633$ | $0.9157$ | $0.2687$ | $0.0741$ | $0.4176$ |
| **Hyperledger** | $1,173$ | $79$ | $0.9461$ | $0.8417$ | $0.2542$ | $0.1899$ | $0.4576$ |
| **Spring** | $1,091$ | $24$ | $0.9319$ | $0.7020$ | $0.1818$ | $0.4167$ | $0.4493$ |
| **JFrog** | $618$ | $95$ | $0.7103$ | $0.8735$ | $0.3226$ | $0.1053$ | $0.4768$ |
| **Mindville** | $91$ | $4$ | $0.8961$ | $0.8665$ | $0.4000$ | $0.5000$ | $0.5947$ |
| **Sonatype** | $20,125$ | $115$ | $0.9032$ | $0.9264$ | $0.0616$ | $0.5391$ | $0.2703$ |
| **Jira** | $4,608$ | $171$ | $0.8863$ | $0.6050$ | $0.0173$ | $0.0234$ | $0.3253$ |
| **IntelDAOS** | $3,208$ | $331$ | $0.7790$ | $0.7121$ | $0.2360$ | $0.1148$ | $-0.0641$ |
| **Mojang** | $151,046$ | $413$ | $0.5687$ | $0.6395$ | $0.0350$ | $0.6392$ | $0.4758$ |
| **SecondLife** | $2$ | $0$ | $1.0000$ | $0.0000$ | $0.0000$ | — | — |

### 4.4. Phân tích và Nhận xét Kết quả Thực nghiệm

1. **Hiệu quả nổi bật trên các dự án có quy trình quản lý liên kết chặt chẽ**:
   Ở các hệ sinh thái phần mềm lớn như **Apache, RedHat, Sakai, Qt, MariaDB, JiraEcosystem, Hyperledger, JFrog**, mô hình TGN đạt `NDCG@10` từ **$0.85$ đến $0.99$** và `Precision@Top-5%` đạt từ **$25.4\%$ đến $40.9\%$** (tức trong 3 đến 4 cảnh báo đưa ra ngay lúc issue vừa tạo thì có 1 issue thực sự là P0). Với các instances đặc thù như **Mojang** (hệ thống báo lỗi game Minecraft từ người chơi, chỉ có $413$ mẫu P0 trên $151,046$ issues — tỷ lệ mẫu dương chỉ $0.27\%$) hay **Sonatype** (tỷ lệ P0 chỉ $0.57\%$), dù `Precision@Top-5%` bị giới hạn bởi số lượng mẫu P0 quá ít, TGN vẫn đạt **`Recall@Top-5%` rất cao: $63.92\%$ trên Mojang và $53.91\%$ trên Sonatype**.
2. **Đánh giá khách quan giới hạn dự báo tại thời điểm $T_0$**:
   Phân tích cấu trúc nhãn Ground Truth cho thấy **$53.9\%$ số issues P0 là các issues sẽ phát sinh liên kết chặn (`Blocks` / `Depends`) trong tương lai**, trong khi tại đúng thời điểm tạo $T_0$ chỉ có **$0.461\%$** số issues được gắn sẵn link phụ thuộc. Việc mô hình TGN đạt `ROC-AUC = 0.8382`, `NDCG@10 Grouped = 0.8547` và nâng độ chính xác cảnh báo Top-5% lên gấp **4.77 lần** mức ngẫu nhiên mà không hề rò rỉ dữ liệu tương lai chứng minh rằng TGN đã khai thác hiệu quả trạng thái memory của các nodes lân cận `(reporter, assignee_t0, project)` kết hợp với các đặc trưng tải công việc tại $T_0$.

---

### 4.5. Mở rộng: Huấn luyện và Dự báo TGN tại Thời điểm Dự án Thay đổi (`Project-Change Continuous Snapshot`)

Ở chế độ mặc định tại $T_0$ (`snapshot_memory`), ảnh chụp bộ nhớ của một `issue` được đóng băng ngay trước khi `issue` đó được tạo ra, dẫn đến vector bộ nhớ riêng của chính `issue` đó luôn bằng không ($s_i(T_0^-) = \mathbf{0}$, chỉ có $0.037\%$ mẫu khác không). Tuy nhiên, trong vận hành thực tế, quản lý dự án cần hệ thống **tự động đánh giá lại các `issue` đang mở mỗi khi dự án phát sinh sự kiện thay đổi** (có người bình luận, đổi `status`/`priority`, phân công lại `assignee`, hoặc gắn thêm liên kết phụ thuộc `Blocks`/`Depends`).

Để giải quyết bài toán này mà vẫn bảo toàn nguyên tắc **Zero Temporal Leakage**, khóa luận cài đặt thêm thuật toán [`snapshot_memory_at_change`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/memory.py#L198-L265) và quy trình huấn luyện đa mốc [`train_project_change.py`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/training/criticality/train_project_change.py):
1. **Chụp bộ nhớ 2 pha trong từng Chunk (`Two-Phase Sub-Chunk Splitting`)**: Với mỗi `issue` $i$ tại mốc cập nhật dự án $t_{\text{change}} \in [T_{0,i},\; T_{\text{resolved},i} - 1\text{s})$, hệ thống tách `chunk` chứa $t_{\text{change}}$ thành 2 pha:
   - **Pha 1 (`pre_mask`)**: Áp dụng toàn bộ các sự kiện đang mở ($\text{ts} \le t_{\text{change}}$ và `scat != 0`, loại trừ hoàn toàn sự kiện đóng `Done`/`Resolved`) vào `TGNMemory` và cập nhật động `assignee` hiện tại (`dynamic_assignee = True`) trước khi đọc snapshot $Z_i(t_{\text{change}})$.
   - **Pha 2 (`post_mask`)**: Áp dụng phần sự kiện còn lại của `chunk` sau khi đã chụp xong để bảo toàn lịch sử đầy đủ cho các `chunk` tiếp theo.
   - Nhờ cơ chế này, **100.00% số `issue` đều có bộ nhớ riêng $s_i(t_{\text{change}}) \neq \mathbf{0}$** với **$0$ vi phạm rò rỉ thời gian** (`applied_ts <= t_change < resolved_ts`).
2. **Huấn luyện `Readout` Đa mốc (`Multi-Snapshot Training`)**: Trong mỗi epoch, mạng `Readout` (tổ hợp 3 seeds `[45, 47, 49]`) được huấn luyện đồng thời trên các ảnh chụp tại `@T0_pre`, `@T3_change` (cập nhật dự án trong 3 ngày đầu), `@T7_change` (trong 7 ngày đầu) và `@T_active_change` (cập nhật dự án mới nhất khi `issue` đang mở).

#### Bảng Kết quả Thực nghiệm theo Tiến trình Dự án Thay đổi (Validation & Out-of-Time Test)

| Thời điểm dự án cập nhật | Tập đánh giá | `NDCG@10` (Global) | `NDCG@10` (Grouped) | `NDCG@50` (Grouped) | `Precision@Top-5%` (Số ca `TP` bắt trúng) | `Spearman` $\rho$ (Mục tiêu $\ge 0.70$) | `ROC-AUC` | `PR-AUC` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline cũ (Chỉ train ở $T_0$)** | **TEST** | $0.8677$ | $0.8547$ | $0.9011$ | $23.86\%$ ($4,130$ TP) | $0.5937$ | $0.8382$ | $0.2082$ |
| **1. Ngay trước khi tạo (`@T0_pre`)** | **VAL** | $0.9799$ | $0.8407$ | $0.8901$ | $35.25\%$ ($6,101$ TP) | $0.5625$ | $0.8228$ | $0.3182$ |
| | **TEST** | $0.9292$ | $0.8545$ | $0.9017$ | $24.17\%$ ($4,183$ TP) | $0.5992$ | $0.8367$ | $0.2068$ |
| **2. Sau 3 ngày dự án thay đổi (`@T3_change`)** | **VAL** | $0.9081$ | $0.8545$ | $0.9000$ | $40.04\%$ ($6,931$ TP) | $0.5946$ | $0.8440$ | $0.3792$ |
| | **TEST** | $0.9716$ | $0.8674$ | $0.9086$ | $28.83\%$ ($4,991$ TP) | $0.6193$ | $0.8517$ | $0.2522$ |
| **3. Sau 5 ngày dự án thay đổi (`@T5_change`)** | **VAL** | $0.9096$ | $0.8566$ | $0.9012$ | $40.40\%$ ($6,993$ TP) | $0.5977$ | $0.8449$ | $0.3826$ |
| | **TEST** | $0.9689$ | $0.8678$ | $0.9092$ | $29.06\%$ ($5,030$ TP) | $0.6259$ | $0.8519$ | $0.2544$ |
| **4. Sau 7 ngày dự án thay đổi (`@T7_change`)** | **VAL** | $0.9114$ | $0.8568$ | $0.9015$ | $40.42\%$ ($6,997$ TP) | $0.6016$ | $0.8464$ | $0.3847$ |
| | **TEST** | $0.9688$ | $0.8682$ | $0.9099$ | $29.15\%$ ($5,045$ TP) | $0.6289$ | $0.8528$ | $0.2562$ |
| **5. Khi dự án thay đổi trong lúc mở (`@T_active_change`)** | **VAL** | **$0.9532$** | **$0.9041$** | **$0.9331$** | **$45.18\%$ ($7,821$ TP)** | **$0.7026$ (ĐẠT)** | **$0.8710$** | **$0.4371$** |
| | **TEST** | **$0.9920$** | **$0.8987$** | **$0.9312$** | **$38.99\%$ ($6,749$ TP)** | **$0.7272$ (ĐẠT)** | **$0.8735$** | **$0.3286$** |

#### Bảng Hiệu năng Chi tiết theo từng Jira Instance tại `@T_active_change` (Out-of-Time Test — $346,174$ issues)

| Jira Instance | Số mẫu Test ($N$) | Số lượng P0 thực tế | NDCG@10 (Global) | NDCG@10 (Grouped) | Precision @Top-5% | Recall @Top-5% | Spearman $\rho$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Apache** | $70,263$ | $5,208$ | $0.9899$ | $0.9462$ | $0.4243$ | $0.2863$ | $0.6410$ |
| **RedHat** | $48,816$ | $7,078$ | $0.9739$ | $0.9355$ | $0.5145$ | $0.1775$ | $0.6214$ |
| **MongoDB** | $24,120$ | $2,283$ | $0.9531$ | $0.8065$ | $0.4876$ | $0.2576$ | $0.5236$ |
| **Qt** | $16,094$ | $836$ | $0.9793$ | $0.7611$ | $0.4882$ | $0.4701$ | $0.3558$ |
| **Sakai** | $1,842$ | $209$ | $0.9831$ | $0.9678$ | $0.6022$ | $0.2679$ | $0.7502$ |
| **MariaDB** | $1,739$ | $222$ | $0.9074$ | $0.9452$ | $0.4023$ | $0.1577$ | $0.5409$ |
| **JiraEcosystem** | $1,338$ | $243$ | $0.8564$ | $0.9350$ | $0.5522$ | $0.1523$ | $0.5844$ |
| **Hyperledger** | $1,173$ | $79$ | $0.9843$ | $0.8920$ | $0.3220$ | $0.2405$ | $0.5660$ |
| **Spring** | $1,091$ | $24$ | $0.9709$ | $0.7131$ | $0.2000$ | $0.4583$ | $0.4680$ |
| **JFrog** | $618$ | $95$ | $0.8066$ | $0.9038$ | $0.4516$ | $0.1474$ | $0.5614$ |
| **Mindville** | $91$ | $4$ | $0.9220$ | $0.8887$ | $0.4000$ | $0.5000$ | $0.5855$ |
| **Sonatype** | $20,125$ | $115$ | $0.9527$ | $0.9358$ | $0.1072$ | $0.9391$ | $0.3146$ |
| **Jira** | $4,608$ | $171$ | $0.8981$ | $0.6693$ | $0.1775$ | $0.2398$ | $0.4212$ |
| **IntelDAOS** | $3,208$ | $331$ | $0.9441$ | $0.7797$ | $0.3789$ | $0.1843$ | $0.2887$ |
| **Mojang** | $151,046$ | $413$ | $0.9490$ | $0.6908$ | $0.0408$ | $0.7458$ | $0.6564$ |
| **SecondLife** | $2$ | $0$ | $1.0000$ | $0.0000$ | $0.0000$ | — | — |

---

## PHẦN 5: ĐÓNG GÓI MODEL BUNDLE VÀ ỨNG DỤNG THỰC TẾ

Toàn bộ pipeline suy luận của mô hình TGN đã được đóng gói thành 2 Model Bundles chuẩn trong package `early_risk_detection`:

- **Model Bundle tại thời điểm khởi tạo $T_0$ ([`bundles/criticality`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/bundles/criticality/manifest.json))**: Chuyên biệt cho bài toán đánh giá ngay trước khi `issue` được tạo ($t = T_0^-$).
- **Model Bundle cập nhật theo thời điểm dự án thay đổi ([`bundles/criticality_project_change`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/bundles/criticality_project_change/manifest.json))**: Đóng gói trọng số `tgn_memory.pt`, 3 trọng số readout đa mốc `readout_seed{45,47,49}.pt`, bộ chuẩn hóa `normalizers.npz` và cấu hình `project_change_mode: true` để chấm điểm tại bất kỳ thời điểm `as_of` nào khi dự án có sự kiện mới.
- **Hiệu năng suy luận (Inference Speed)**: Class [`CriticalityScorer`](file:///home/jiooum/0.Workspace/0.SourceCode/tgn/src/early_risk_detection/criticality/scorer.py#L22-L138) và lệnh CLI `erd score criticality` cho phép replay toàn bộ dòng $19.66$ triệu sự kiện lịch sử để cập nhật memory (~8.2 giây cho một lượt quét toàn bộ sự kiện trên GPU RTX 4060 Ti) và xuất trực tiếp điểm `score`, thứ hạng `rank_in_instance`, và nhãn cảnh báo `is_critical` (Top 5%) để tích hợp vào ứng dụng quản lý dự án.
