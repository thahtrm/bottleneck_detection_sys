# Thiết kế đồ thị node cho PM: loại node, liên kết và phương án hiển thị

> Mục tiêu: PM nhìn vào là biết ngay **task nào sắp trễ hạn**, **vì sao** (bị chặn bởi ai, người phụ trách có quá tải không), và **trễ sẽ lan sang đâu**.

## 1. Các loại node trong mô hình TGN

Nguồn: `src/early_risk_detection/criticality/stream.py` (view `v_tgn_events_all`). Mỗi sự kiện là bộ ba `(u, v, p)`. Tổng cộng khoảng 3,45 triệu node.

| Loại node | Khoá trong stream | Vai trò trong mô hình | Có ý nghĩa với PM? |
|---|---|---|---|
| **Issue** | `issue:<KEY>` (`u`, hoặc `v` của sự kiện `link`) | Đối tượng cần dự đoán trễ hạn. Memory 128 chiều tích luỹ lịch sử của issue | **Có**: node trung tâm |
| **User** | `user:<id>` (assignee, reporter, người comment) | Mang trạng thái "tải" của con người. Memory của user truyền tín hiệu quá tải sang issue qua message | **Có**: người phụ trách |
| **Project** | `<instance>\|project:<P>` (`p`, có mặt trong mọi sự kiện) | Bối cảnh chung của dự án (nhịp release, áp lực chung) | Có, nhưng làm **nhóm/nền**, không vẽ thành node |
| **Status value** | `status:<giá trị>` | Node "giá trị" giúp mô hình phân biệt các lần chuyển trạng thái | **Không**: là chi tiết kỹ thuật, hiển thị thành thuộc tính |
| **Priority value** | `priority:<giá trị>` | Như trên, cho thay đổi độ ưu tiên | **Không**: là thuộc tính |

Webapp có thêm hai thực thể ngoài TGN nhưng quan trọng với hạn chót: **Sprint** (`sprints.end_at`) và **Version** (`versions.release_date`).

## 2. Các loại liên kết (cạnh)

### 2.1 Trong TGN (6 loại sự kiện)

| `kind` | `u → v` | `ltype` (chỉ với link) |
|---|---|---|
| `create` | issue → user (reporter) | |
| `assignee` | issue → user (người nhận) | |
| `comment` | issue → user (người bình luận) | |
| `status` | issue → status value | |
| `priority` | issue → priority value | |
| `link` | issue → issue | 0 = Block/Depend, 1 = Relate, 2 = Duplicate, 3 = Other |

Mọi sự kiện còn nối `u` với project `p`.

### 2.2 Cạnh nên hiển thị cho PM

| Cạnh hiển thị | Nguồn dữ liệu | Có hướng | Truyền rủi ro trễ? |
|---|---|---|---|
| **Chặn** (Blocks/Depends) | `links` có type Block/Depend, chuẩn hoá chiều *tiền đề → phụ thuộc* (API đã làm) | Có | **Có**: đây là đường lan truyền domino |
| **Phụ trách** | `issues.assignee_id` | issue → người | **Có**: người quá tải kéo trễ mọi task của họ |
| **Thuộc sprint / version** | `issue_sprints`, `issue_versions` | issue → sprint/version | Không, nhưng cho biết hạn chót thật |
| Liên quan / Trùng lặp | `links` Relate, Duplicate | Không | Không: mặc định ẩn để giảm nhiễu |
| Comment / reporter | TGN `comment`, `create` | | Không: chỉ hiện trong panel chi tiết |

Lưu ý: Relate chiếm phần lớn link, còn Block/Depend chỉ chiếm 3–4% nhưng tỷ lệ trễ là 51,5% so với 39,4%. Vì vậy mặc định **chỉ vẽ cạnh Chặn**.

## 3. Ánh xạ 4 điểm nghẽn trong nghiên cứu sang hình ảnh

| Điểm nghẽn (Bảng 3.4) | Thể hiện trên đồ thị |
|---|---|
| 1. Hàng đợi tiếp nhận (task chưa gán) | Node ảo **"Chưa phân công"** gom mọi issue chưa có assignee. Node càng lớn thì hàng đợi triage càng dài |
| 2. Quá tải nguồn lực (Gini 0,82) | Node **Người**: kích thước tỷ lệ số task đang mở, viền đỏ khi quá tải |
| 3. Reopen / ping-pong | Huy hiệu ↻ trên node issue (đếm từ bảng `changes`) |
| 4. Lan truyền phụ thuộc | Cạnh **Chặn**, đường găng được tô đậm, node điểm nghẽn có quầng sáng |

## 4. Các phương án đã cân nhắc

**A. Đồ thị dị thể toàn phần.** Vẽ tất cả issue, người, sprint trong một đồ thị force.
Loại vì: node người thành hub khổng lồ (vài người giữ 46–60% việc) nên layout biến thành "cục len". Đồ thị không còn cho thấy chuỗi chặn, và PM không biết nên nhìn vào đâu.

**B. Đồ thị tâm điểm (ego graph) theo rủi ro.** Danh sách issue xếp theo rủi ro ở bên trái. Chọn một issue thì hiện vùng lân cận k bước: blocker phía thượng nguồn ở bên trái, task bị ảnh hưởng ở bên phải, người phụ trách bên dưới, sprint/version bên trên.
Ưu điểm: trả lời trực tiếp câu "vì sao task này trễ, sẽ kéo theo gì". Nhược điểm: mất cái nhìn toàn cục.

**C. Tổng quan theo làn người phụ trách.** Chỉ vẽ DAG issue–issue (cạnh Chặn). Issue được gom thành cụm hoặc làn theo assignee, nên người là *nhóm* chứ không phải node.
Ưu điểm: thấy ngay ai đang ôm cụm task đỏ. Nhược điểm: cạnh chặn liên làn cắt nhau nhiều.

### Tổng hợp (khuyến nghị): hai chế độ trên cùng một API

1. **Chế độ Tổng quan** (mặc định, lấy từ C và phần đang có của `NetworkGraph.jsx`):
   - Chỉ vẽ node issue và cạnh Chặn. Issue đã xong và không chặn ai thì ẩn.
   - **Mặc định bật "Gom theo người phụ trách"** (dạng làn, mỗi người một làn, làn có nhiều task rủi ro cao xếp trên). Có thể tắt để xem DAG thuần. Ở chế độ gom, có thể dùng vis-network `cluster` theo assignee. Mỗi cụm thu gọn thành một node Người kèm số liệu (số task mở, số task đỏ). Bấm vào cụm thì mở ra.
   - Có node "Chưa phân công" (điểm nghẽn 1).
2. **Chế độ Tâm điểm** (lấy từ B): bấm một issue hoặc một người để vào.
   - Bố cục phân tầng trái → phải: `blockers ← [ISSUE] → dependents`, độ sâu mặc định là 2.
   - Hiện node Người cho mọi issue trong vùng. Vì chỉ có vài chục node nên không bị rối.
   - Hiện node Sprint/Version kèm hạn chót, để thấy hạn thật đang bị đe doạ.
   - Panel phải: `factors` (lý do mô hình đánh giá rủi ro), số ngày trễ dự kiến, gợi ý hành động.

Cách tổng hợp này loại phương án A. Nó giữ được câu hỏi toàn cục ("ở đâu đang đỏ") lẫn câu hỏi cục bộ ("vì sao, kéo theo gì") mà không bao giờ vẽ cả nghìn node người cùng lúc.

## 5. Mã hoá trực quan

| Kênh | Node Issue | Node Người | Sprint/Version |
|---|---|---|---|
| Hình dạng | Hộp bo góc | Tròn (avatar hoặc chữ viết tắt) | Lục giác / cờ |
| Màu nền | Theo `level` rủi ro: HIGH đỏ, MEDIUM cam, LOW xanh, đã xong xám | Theo mức tải: bình thường xám, quá tải đỏ | Đỏ khi còn ≤ 3 ngày và có issue HIGH |
| Kích thước | Tỷ lệ `bottleneck_score` (hoặc số task bị chặn) | Tỷ lệ số task đang mở | Cố định |
| Viền | Nét đứt khi đã quá hạn, kèm nhãn "+N ngày" | | |
| Huy hiệu | ⛔ bị chặn · ↻ reopen · ★ đường găng | Số task đỏ | Ngày còn lại |

Cạnh **Chặn**: nét liền, có mũi tên. Màu đỏ khi blocker đang trễ hoặc HIGH (rủi ro đang lan). Đậm hơn khi nằm trên đường găng. Cạnh **Phụ trách**: nét mảnh xám, không mũi tên. Cạnh **Sprint/Version**: nét chấm.

Nguyên tắc màu: chỉ dùng màu cho **rủi ro**, không dùng màu để phân biệt loại node (loại node phân biệt bằng hình dạng). Nhờ vậy PM chỉ cần tìm màu đỏ.

## 6. Hợp đồng API (bản phác thảo)

Mở rộng `GET /api/dashboard/graph` theo hướng tương thích ngược: `id` của issue vẫn là key Jira, các loại node khác có tiền tố.

```python
# webapp/backend/erw/api/dashboard.py

NodeKind = Literal["issue", "person", "unassigned", "sprint", "version"]
EdgeKind = Literal["blocks", "relates", "duplicates", "assigned", "in_sprint", "in_version"]

@dashboard_router.get("/graph")
def get_dashboard_graph(
    project: str | None = None,
    focus: str | None = None,          # issue key hoặc "person:<id>"; None = chế độ tổng quan
    depth: int = 2,                    # số bước lân cận theo cạnh blocks, chỉ dùng với focus
    include: str = "",                 # "person,sprint,version,relates"; tổng quan mặc định ""
    ...
) -> GraphResponse: ...

class GraphNode(TypedDict):
    id: str                            # "SPR-12" | "person:abc" | "person:__unassigned__" | "sprint:7"
    kind: NodeKind
    label: str
    # issue: giữ nguyên các trường hiện có (level, delay_value, is_overdue, is_bottleneck, ...)
    #        thêm reopen_count
    # person: open_count, high_risk_count, overdue_count, is_overloaded
    # sprint/version: end_at, days_left, high_risk_count

class GraphEdge(TypedDict):
    id: str
    from_: str                         # serialise thành "from"
    to: str
    kind: EdgeKind
    propagates_risk: bool              # blocks với blocker trễ hoặc HIGH, hoặc assigned tới người quá tải
    is_critical_path: bool

def _ego_subgraph(blocking_map, blocked_by_map, focus: str, depth: int) -> set[str]:
    """BFS hai chiều theo cạnh blocks, giới hạn depth. Trả về tập issue key."""
    raise NotImplementedError

def _person_load(issues: Iterable[Issue], risk: Mapping[str, RiskState]) -> dict[str, PersonLoad]:
    """Đếm task mở, HIGH, quá hạn theo assignee.
    is_overloaded = open_count > p90 của dự án hoặc high_risk_count >= 2."""
    raise NotImplementedError
```

Định nghĩa "quá tải" dùng percentile **trong dự án** thay vì ngưỡng cứng, vì Gini rất cao và quy mô từng dự án khác nhau.

## 7. Lộ trình triển khai

1. **Backend**: thêm `kind` cho node và cạnh, thêm node person/unassigned (tính từ `issues.assignee_*`), thêm `reopen_count` từ `changes`, thêm tham số `focus`/`depth`/`include`. Sửa `test_api_dashboard.py`.
2. **Frontend, chế độ Tổng quan**: thêm công tắc "Gom theo người phụ trách" (vis-network `network.cluster`) và node "Chưa phân công".
3. **Frontend, chế độ Tâm điểm**: double-click node để vào, dùng layout `hierarchical` hướng LR, có breadcrumb để quay lại.
4. (Tuỳ chọn) Lấy thẳng embedding hoặc điểm tải của **node user từ memory TGN** thay cho heuristic đếm task. Cách này khớp với lập luận trong khoá luận rằng memory của user truyền tín hiệu quá tải.

## 8. Wireframe

### 8.1 Chế độ Tổng quan (mặc định)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Đồ thị phụ thuộc · Dự án [SPR ▾]   🔍 Tìm issue/người...    [Tổng quan] [Tâm điểm]   │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐                      │
│ │ 🔴 12   │ │ ⏰ 7    │ │ ⛔ 5     │ │ 👤 2     │ │ 📥 9      │                      │
│ │Rủi ro   │ │Quá hạn  │ │Điểm nghẽn│ │Người quá │ │Chưa phân  │                      │
│ │cao      │ │         │ │          │ │tải       │ │công       │                      │
│ └─────────┘ └─────────┘ └──────────┘ └──────────┘ └───────────┘                      │
│ Lọc: (●Tất cả) (○Điểm nghẽn) (○Quá hạn) (○Bị chặn)   ☑ Gom theo người phụ trách      │
│      ☐ Hiện Relate/Duplicate   ☐ Hiện task đã xong                                   │
├────────────────────────┬─────────────────────────────────────────────────────────────┤
│ TOP RỦI RO             │                                                             │
│ ────────────────────── │   ╭──────────╮          ╭──────────╮                        │
│ 1 🔴 SPR-12  +5d  ★⛔  │   │ SPR-3    │━━━━━━━━━▶│▓SPR-12▓▓ │━━━━━━━━▶╭──────────╮   │
│   Auth API · An        │   │ 🟢 LOW   │          │🔴HIGH +5d│  (đỏ)   │ SPR-20   │   │
│ 2 🔴 SPR-20  ★         │   ╰──────────╯          │ ★ ⛔→3   │         │🔴 HIGH ★ │   │
│   Payment · Bình       │                         ╰────┬─────╯         ╰────┬─────╯   │
│ 3 🟠 SPR-31  ↻2        │                              │ (đỏ)               │         │
│   Báo cáo · An         │                              ▼                    ▼         │
│ 4 🟠 SPR-44            │                         ╭──────────╮         ╭──────────╮   │
│   UI login · (trống)   │                         │ SPR-31   │         │ SPR-25   │   │
│ ...                    │                         │🟠 MED ↻2 │         │🟢 LOW    │   │
│                        │                         ╰──────────╯         ╰──────────╯   │
│ NGƯỜI PHỤ TRÁCH        │                                                             │
│ ────────────────────── │      ( An )◉  9 mở · 3🔴     ( Bình )○ 4 mở · 1🔴           │
│ 🔴 An     9 mở  3🔴    │      viền đỏ = quá tải        (cụm thu gọn, bấm để mở)      │
│ ⚪ Bình   4 mở  1🔴    │                                                             │
│ ⚪ Chi    2 mở  0      │      [ 📥 Chưa phân công · 9 ]  ← node ảo (điểm nghẽn 1)    │
│ 📥 Chưa gán 9          │                                                             │
├────────────────────────┴─────────────────────────────────────────────────────────────┤
│ Chú giải: 🔴HIGH 🟠MED 🟢LOW ⬜Xong │ ━▶ Chặn  ━▶(đỏ) đang lan trễ  ═▶ đường găng ★ │
│           ⛔ bị chặn  ↻ reopen  +Nd quá hạn  ◯ người  ⬡ sprint/version               │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

- Danh sách bên trái và đồ thị đồng bộ: hover một dòng thì node tương ứng nhấp nháy, bấm thì vào **Tâm điểm**.
- Khi bật "Gom theo người phụ trách", task của mỗi người thu thành một node tròn. Mở cụm ra thì thấy các task bên trong, các task khác mờ đi.

### 8.2 Chế độ Tâm điểm (bấm vào SPR-12)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ← Tổng quan / SPR-12            Độ sâu: [1] [●2] [3]   ☑ Người ☑ Sprint ☐ Relate     │
├─────────────────────────────────────────────────────────────┬────────────────────────┤
│        THƯỢNG NGUỒN            TÂM ĐIỂM          HẠ NGUỒN    │ SPR-12 · Auth API      │
│        (chặn nó)                             (bị nó chặn)    │ 🔴 HIGH · trễ dự kiến  │
│                         ⬡ Sprint 14                          │    ~5 ngày             │
│                         còn 3 ngày 🔴                         │ Hạn: 12/11 (Sprint 14) │
│                              ┊                               │ Trạng thái: In Progress│
│  ╭─────────╮           ╭═══════════╮          ╭─────────╮    │ Phụ trách: An (quá tải)│
│  │ SPR-3   │━━━━━━━━━━▶║ ▓SPR-12▓▓ ║━━━━━━━━━▶│ SPR-20  │━━▶ │                        │
│  │ 🟢 Done?│           ║ 🔴 +5d ★  ║  (đỏ)    │ 🔴 ★    │ …  │ VÌ SAO RỦI RO          │
│  ╰─────────╯           ╚═════╤═════╝          ╰────┬────╯    │ • Chặn 3 task, 1 trên  │
│  ╭─────────╮                 │                ╭────┴────╮    │   đường găng           │
│  │ SPR-7   │━━━━━━━━━━━━━━━━━┘                │ SPR-31  │    │ • Assignee có 9 task   │
│  │ 🟠 MED  │ (đỏ: blocker                     │ 🟠 ↻2   │    │   mở (p90 dự án = 6)   │
│  ╰────┬────╯  cũng đang rủi ro)               ╰─────────╯    │ • Ở Open 6 ngày trước  │
│       ┊                      ┊                     ┊         │   khi nhận             │
│    ( Chi )              ◉( An )◉ quá tải       ( Bình )      │                        │
│    2 mở                 9 mở · 3🔴             4 mở          │ ẢNH HƯỞNG              │
│                                                              │ Kéo theo 3 task, 2 HIGH│
│                                                              │ Sprint 14 bị đe doạ    │
│                                                              │                        │
│                                                              │ GỢI Ý                  │
│                                                              │ [Chuyển bớt việc của An]│
│                                                              │ [Ưu tiên gỡ SPR-7]     │
│                                                              │ [Mở trên Jira ↗]       │
└─────────────────────────────────────────────────────────────┴────────────────────────┘
```

- Bố cục phân tầng trái → phải cố định nên PM đọc như một chuỗi: **nguyên nhân → task này → hậu quả**.
- Node người nằm dưới mỗi issue (nét mảnh), sprint/version nằm trên (nét chấm).
- Bấm vào một node người thì chuyển tâm điểm sang người đó (xem 8.3).

### 8.3 Chế độ Tâm điểm theo người (bấm vào An)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ← Tổng quan / SPR-12 / An                                                            │
├─────────────────────────────────────────────────────────────┬────────────────────────┤
│                                                              │ An · 🔴 Quá tải        │
│     ╭────────╮  ╭────────╮  ╭────────╮  ╭────────╮           │ 9 task mở (p90 = 6)    │
│     │SPR-12  │  │SPR-31  │  │SPR-40  │  │SPR-41  │  …        │ 3 HIGH · 2 quá hạn     │
│     │🔴 +5d ★│  │🟠 ↻2   │  │🔴 +2d  │  │🟢      │           │                        │
│     ╰───┬────╯  ╰───┬────╯  ╰───┬────╯  ╰───┬────╯           │ Task đang chặn người   │
│         └───────────┴─────┬─────┴───────────┘               │ khác: SPR-12 → Bình    │
│                       ◉( An )◉                               │                        │
│                                                              │ Ứng viên nhận bớt việc:│
│   Task xếp từ trái sang phải theo mức rủi ro giảm dần        │ Chi (2 mở · 0🔴)       │
│                                                              │ [Gợi ý chuyển SPR-40]  │
└─────────────────────────────────────────────────────────────┴────────────────────────┘
```
