# Tài liệu thiết kế — Cửa sổ chat PM: hỏi đáp, báo cáo theo giờ, tin việc gấp

| | |
|---|---|
| Ngày | 2026-11-21 |
| Trạng thái | Đã duyệt (2026-11-21) |
| Liên quan | `webapp/backend/erw/pipeline/digest.py`, `webapp/backend/erw/pipeline/alerts.py`, `webapp/backend/erw/integrations/llm.py`, `webapp/backend/erw/jobs.py`, `webapp/frontend/src/App.jsx` |

Quy ước:

- **[Chốt]**: đã quyết trong buổi phân tích.
- **[Đề xuất]**: người viết tài liệu tự quyết. Đổi được nếu không lệch mục tiêu.

## Mục đích

PM theo dõi dự án trên web Early Risk. Họ cần hỏi dữ liệu dự án, nhận một báo cáo ngắn vào các giờ tự chọn, và thấy tin khi có việc gấp, tất cả trong một cửa sổ chat trên web. Câu trả lời gồm sự thật khớp bảng rủi ro và đề xuất việc nên làm. PM đọc đề xuất trên chat, rồi áp dụng trên panel issue đang có.

Demo này cho người xem thấy PM làm việc trên web app, không phải trên Slack.

## Mục tiêu

- Cửa sổ chat trên web, cạnh bảng rủi ro, cho PM đã đăng nhập.
- Hỏi đáp: đoạn sự thật do code tra từ dữ liệu app; đoạn đề xuất do Ollama viết từ đúng dữ liệu đó.
- Báo cáo ngắn theo giờ PM tự đặt, lưu theo tài khoản PM.
- Tin việc gấp trong cùng cửa sổ chat.
- Issue trong tin nhắn mở panel issue ở tab đề xuất. Xác nhận ghi Jira vẫn ở panel và modal hiện có.
- Tin nhắn được lưu. Mở app sau giờ gửi vẫn thấy báo cáo.

## Ngoài phạm vi

- Sửa, tắt, hoặc đổi nội dung job Slack hiện có (`daily_digest`, cảnh báo `notify`).
- Ghi Jira, xác nhận action, hoặc nút áp dụng ngay trong chat.
- Chat cho role `viewer`.
- WebSocket hoặc kênh đẩy riêng.
- Hỏi đáp tự do ngoài bốn kiểu tra cứu ở dưới.
- Cuối tuần, quá 3 mốc giờ, hoặc PM đặt khác ngày thường.
- Admin đặt giờ hộ PM.
- RAG, embedding, hoặc để mô hình tự viết câu SQL.

## Anti-goals

- Câu trả lời có số hoặc issue lệch dữ liệu vừa tra.
- Chat tạo một đường ghi Jira thứ hai.
- Đề xuất trích issue, factor, hoặc `action_type` không có trong dữ liệu vừa đưa cho mô hình.

## Ràng buộc

- App đã có FastAPI, SQLAlchemy `create_all`, APScheduler (`morning_batch`, `daily_digest`), Ollama (`call_ollama_chat`, JSON, `ALLOWED_ACTION_TYPES`), bảng `users` / `project_members.role` (`pm` | `viewer`), và URL dashboard với tham số `issue` mở `IssuePanel`.
- Không có WebSocket. Chat hỏi máy chủ định kỳ.
- Múi giờ hệ thống là `settings.tz`, mặc định `Asia/Ho_Chi_Minh`.
- LLM hiện chạy một worker (`erw-llm`). Câu trả lời chat không được giữ request HTTP suốt thời gian Ollama.

## Cách làm đã xét

**Cách 1 — Code trả số liệu, Ollama chỉ viết đoạn đề xuất. [Chốt]** Python tra dữ liệu và in đoạn sự thật. Ollama chỉ viết 1–3 việc nên làm, và bị loại nếu trích thứ không có trong kết quả tra. Số trên chat khớp bảng. Thêm một lớp nhận diện câu hỏi.

**Cách 2 — Ollama viết cả câu trả lời.** Nhét bản dữ liệu vào prompt, mô hình viết cả hai đoạn. Ít code hơn. Số trong câu trả lời có thể lệch bảng.

**Cách 3 — Chat không gọi Ollama.** Đề xuất chỉ trích gợi ý từng issue mà job sáng đã sinh. Câu hỏi về cả dự án phụ thuộc gợi ý đã có sẵn hay chưa.

Cách 1 được chọn vì demo cần số khớp bảng, và Ollama hiện đã bị khóa bằng JSON cùng danh sách hành động cho phép.

## PM nhìn thấy gì

### Cửa sổ chat [Chốt]

Một cửa sổ trên view bảng và danh sách, cạnh vùng bảng. Panel issue bên phải giữ nguyên (aside 440px). Chat nằm trong cột chính, thu được, để không chiếm aside.

Đổi project trên header thì chat chuyển sang hội thoại của project đó. Câu hỏi và báo cáo chỉ nói về project đang chọn.

Trên cửa sổ có ô sửa giờ:

```
Giờ báo cáo của bạn
08:00  ×
16:30 ×
[ Thêm giờ ]
```

PM thêm giờ `HH:MM`, xóa được. Tối đa 3 mốc. Chỉ ngày thường. [Chốt: PM tự chọn giờ của mình; các mặc định 3 mốc / ngày thường / múi giờ hệ thống là đề xuất đã được gật]

Tin gồm bốn loại: câu của PM, câu trả lời, báo cáo, việc gấp. Cuộn lên để xem tin cũ.

### Câu trả lời [Chốt]

Hai đoạn.

1. Sự thật, do code viết, từ kết quả tra.
2. Đề xuất, 1–3 việc. Mỗi việc thuộc `adjust_deadline`, `change_assignee`, `change_status`, `add_comment`, `escalate_blocker`, và chỉ vào issue nằm trong đoạn sự thật.

Hỏi một issue thì vẫn đủ hai đoạn, ngắn hơn. Hỏi ngoài bốn kiểu tra cứu thì một dòng: chưa có trong hệ thống. Không gọi Ollama cho câu đó.

Ví dụ đã duyệt:

```
PM
Sáng nay mình nên xử lý gì trước?

Hệ thống
Đang có 6 issue nguy cơ trễ, 2 tăng bậc trong 24 giờ.
DEMO-41 bị block và đang chặn DEMO-18, assignee Lan.

Nên xử lý DEMO-41 trước: escalate blocker, vì nó đang giữ DEMO-18.
DEMO-22 mức cao, hạn mai, assignee Minh — nên đổi hạn hoặc đổi người phụ trách.
```

### Áp dụng đề xuất [Chốt]

Chat không ghi Jira. Bấm mã issue trong tin gọi cùng cách mở panel như bảng (`issue` trên URL) và đưa panel tới tab `suggestion`. Bấm issue từ bảng vẫn mở tab mà panel đang dùng mặc định.

### Báo cáo [Chốt]

Đến mỗi giờ PM đã chọn, vào ngày thường, theo `settings.tz`: một tin báo cáo cho mỗi project mà user đó có role `pm`.

Nội dung mỗi lần cùng một dạng: số liệu tại thời điểm đó (cùng các ý `build_digest` đang có: ngày, tiến độ sprint, đếm nguy cơ / tăng bậc 24 giờ / block / mới 24 giờ, vài issue rủi ro nhất), rồi 1–3 việc nên làm. Issue bấm được.

Lịch gắn với user, dùng chung cho mọi project họ là PM. Không có mốc nào thì không gửi báo cáo. Hỏi đáp và tin gấp vẫn chạy.

### Việc gấp [Chốt]

Cùng cửa sổ, khi `alerts_for` tạo spec thuộc `risk_new`, `risk_up`, `blocked`, `critical`. Nội dung là mẫu chữ hiện có của `format_alert` (không gọi Ollama). Mỗi PM của project đó nhận một tin. Issue bấm được.

Đường Slack trong `dispatch` / `notify` giữ nguyên.

## Hành vi máy chủ

### Ai được dùng

Mọi API chat đòi session đăng nhập. Đọc và ghi chat của một project chỉ khi `get_user_project_role` là `pm`, hoặc user `is_admin`. Viewer nhận 403. Lịch giờ là của chính user đang đăng nhập; admin không sửa giờ của user khác.

### Bốn kiểu tra cứu

Nhận diện bằng luật, không bằng LLM. Nếu câu có mã issue của project đang chọn (dạng khóa Jira), chọn kiểu issue, kể cả khi câu còn chữ khác. Không thì lần lượt:

| Kiểu | Khi câu nói về | Sự thật lấy từ |
|---|---|---|
| `sprint` | tiến độ sprint | cùng cách tính `_sprint_line` |
| `blocked` | bị block, đang chặn | issue mở có `RiskState.blocked` |
| `risky` | nguy cơ trễ, nên xử lý gì, ưu tiên | issue mở mức từ MED, xếp như danh sách trong `build_digest` |
| `issue` | có mã issue của project | issue, risk, assignee, deadline, blocker, factor của mã đó |

Không khớp: trả lời chưa có trong hệ thống.

Danh sách cụm từ và thứ tự so khớp ngoài quy tắc “có mã issue thì chọn `issue`” là của builder. “Sáng nay nên xử lý gì” phải rơi vào `risky`.

Đoạn sự thật do Python render tiếng Việt từ kết quả tra. Tối đa 5 issue trong đoạn liệt kê, cùng trần `MAX_ITEMS` của digest. Đếm vẫn là đếm đầy đủ.

### Đề xuất

Chạy nền trên executor LLM hiện có, không chặn request.

Với kiểu `issue`, nếu đã có suggestion `ready` của issue đó thì dùng `summary` / `actions` đã lưu, không gọi Ollama thêm. Chưa có thì gọi Ollama với cùng dữ liệu issue mà pipeline gợi ý đang dùng.

Với `sprint`, `blocked`, `risky`, và với phần đề xuất của báo cáo: gọi Ollama một lần, prompt chỉ chứa JSON kết quả tra (không bảo mô hình bịa thêm issue). Schema trả về chỉ gồm đoạn chữ đề xuất và mảng action cùng dạng `ActionItem`.

Chấp nhận khi mọi `action_type` thuộc `ALLOWED_ACTION_TYPES`, mọi issue được nhắc nằm trong tập vừa tra, và không quá 3 action. Sai thì giữ đoạn sự thật và một dòng cố định rằng chưa tạo được đề xuất bám dữ liệu.

Ollama lỗi hoặc tắt: đoạn sự thật vẫn trả. Dòng đề xuất nói chưa tạo được.

Báo cáo và câu trả lời dùng chung hàm viết đề xuất này. Tin gấp không dùng.

Request hỏi đáp lưu ngay tin của PM và tin trả lời với đoạn sự thật, đề xuất ở trạng thái đang viết. Khi nền xong, cập nhật cùng tin đó.

### Lưu trữ

Bảng mới, tạo qua `Base.metadata.create_all` như các bảng hiện có.

`chat_messages`: id, user_id, project_key, kind (`user` | `assistant` | `report` | `urgent`), body, recommendation_status (`pending` | `ready` | `failed` | `skipped`), created_at, dedup_key (nullable). Index `(user_id, project_key, created_at)`.

`report_slots`: user_id, time_hhmm (`HH:MM`). Khóa duy nhất `(user_id, time_hhmm)`. API từ chối mốc thứ tư, giờ sai, hoặc trùng.

`dedup_key` của báo cáo: `report:{user_id}:{project}:{HH:MM}:{ngày local}`. Của việc gấp: `urgent:{user_id}:{dedup_key của AlertSpec}`. Gửi lại cùng khóa thì bỏ qua.

API đọc trả tối đa 50 tin mới nhất của user + project, cũ đến mới.

### Lịch

Thêm một job APScheduler, mỗi phút, `day_of_week=mon-fri`, timezone `settings.tz`, `coalesce`, `max_instances=1`. Job tìm slot có `time_hhmm` bằng giờ local hiện tại, rồi với mỗi project user là PM thì ghi tin báo cáo nếu chưa có `dedup_key` ngày đó.

Không sửa `digest_job` Slack.

### Việc gấp

Trong `dispatch`, sau khi xử lý Slack cho một spec, ghi thêm tin `urgent` cho mỗi `project_members` role `pm` của project. Cùng quy tắc dedup. Spec không thuộc bốn kind trên không sinh tin chat.

## API

Prefix gợi ý `/api/chat`. Builder đặt tên cuối, miễn là nằm cùng kiểu router trong `erw/api` và được gắn trong `erw/main.py`.

- `GET /api/chat/messages?project=` — 50 tin.
- `POST /api/chat/messages` — body `{ "project", "text" }`. Trả tin user và tin assistant (sự thật đã có, đề xuất có thể `pending`).
- `GET /api/chat/schedule` — các mốc của user hiện tại.
- `PUT /api/chat/schedule` — thay cả danh sách mốc bằng mảng `HH:MM`.

Client đang mở chat gọi `GET` messages khoảng 5 giây một lần khi tab được xem, và dừng khi tab ẩn. Khoảng này là của builder nếu muốn 3–10 giây.

## Giao diện

- Ô nhập và danh sách tin trên view `board` và `list`.
- Mã issue trong body là nút: `patch({ issue: key })` và panel mở tab `suggestion`. Cách truyền “mở tab suggestion” (state cục bộ hay query) là của builder.
- Ô giờ nằm trên cùng cửa sổ chat.
- Đề xuất `pending` hiện một dòng đang viết. `failed` hiện dòng chưa tạo được. Sự thật không bị xóa.
- Viewer không thấy cửa sổ chat.

## Kiểm tra

- Luật tra cứu: có mã issue thì ra `issue`; câu ưu tiên trong ngày ra `risky`; câu không khớp không gọi Ollama.
- Validator đề xuất loại action lạ và issue không nằm trong tập tra.
- Hai lần chạy job cùng phút không tạo hai báo cáo cùng `dedup_key`.
- `dispatch` với một `risk_up` tạo đúng một tin urgent cho mỗi PM, và vẫn gọi Slack như cũ khi có webhook.
- Viewer bị 403. PM project khác bị 403 trên project không thuộc về mình.
- PUT schedule từ chối mốc thứ tư và chuỗi không phải `HH:MM`.
