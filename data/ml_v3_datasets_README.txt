MÔ TẢ CÁC TRƯỜNG DỮ LIỆU - DATASET TGN JIRA (NHÃN V3)
=====================================================

Áp dụng cho: ml_JFrog.*, ml_Mojang.*, ml_Spring.* (đóng gói trong ml_v3_datasets.zip)
Nguồn sinh: jira_adapter/to_tgn.py, jira_adapter/normalize.py, jira_adapter/labels.py
Ngày build dữ liệu: 2026-10-01

Mỗi dataset gồm 3 file, liên kết với nhau qua idx và id node:
  ml_{name}.csv        danh sách sự kiện
  ml_{name}.npy        đặc trưng cạnh (edge feature) của từng sự kiện
  ml_{name}_node.npy   đặc trưng của từng node (mỗi node là một issue)


1. ml_{name}.csv - DANH SÁCH SỰ KIỆN
------------------------------------
Mỗi dòng là một sự kiện; các dòng sắp xếp tăng dần theo thời gian.

  u      Id của issue nguồn, đánh số từ 1 (id 0 được chừa trống làm padding).
  i      Id của issue đích. Với sự kiện "link" thì đây là issue được nối tới;
         các loại sự kiện khác là self-loop (i == u), chiếm khoảng 96% số dòng.
  ts     Thời điểm xảy ra sự kiện, tính bằng giây Unix (UTC).
  label  Nhãn điểm nghẽn: 1 nếu issue u có ít nhất một link Block/Depend.
         Nhãn chỉ được gắn cho sự kiện status, assignee, priority;
         sự kiện link và comment luôn có nhãn 0.
  idx    Số thứ tự sự kiện, đánh từ 1, trùng với số dòng trong file .npy.


2. ml_{name}.npy - ĐẶC TRƯNG CẠNH, kích thước (số sự kiện + 1, 24)
------------------------------------------------------------------
Dòng 0 toàn số 0; dòng k ứng với sự kiện có idx = k.
Chỉ số cột dưới đây theo code thực tế.

  Cột 0-4    Loại sự kiện, mã hóa one-hot:
             status, assignee, priority, link, comment
  Cột 5-13   Loại link, mã hóa one-hot, chỉ có giá trị khi là sự kiện link:
             Block, Depend, Epic, Parent-Child, Subtask, Fix, Duplicate,
             Relate, Other
  Cột 14     Hướng link: 1 nếu issue này là bên chủ động
             (outward, ví dụ "A blocks B").
  Cột 15     Mức ưu tiên đã chuẩn hóa về khoảng 0-1:
               Blocker/Highest = 1.0   Critical = 0.8   High = 0.6
               Major = 0.5             Normal/Medium = 0.4
               Minor/Low = 0.3         Trivial/Lowest = 0.1
               Nếu thiếu thì mặc định 0.4
  Cột 16-20  Nhóm loại issue, mã hóa one-hot:
             Requirements, Development, Maintenance, User Support, Other
  Cột 21     sin(2*pi*giờ/24) - giờ trong ngày (UTC)
  Cột 22     cos(2*pi*giờ/24) - giờ trong ngày (UTC)
  Cột 23     Cột dự phòng, luôn bằng 0.


3. ml_{name}_node.npy - ĐẶC TRƯNG NODE, kích thước (số node + 1, 64)
--------------------------------------------------------------------
Mỗi node là một issue. Dòng 0 toàn số 0.
Chỉ 8 cột đầu có ý nghĩa; cột 8-63 luôn bằng 0, chỉ dùng để đệm cho khớp
với memory_dim = 64 mà TGN yêu cầu.

  Cột 0      Mức ưu tiên đã chuẩn hóa, cùng thang với cột 15 của file cạnh.
  Cột 1-5    Nhóm loại issue, mã hóa one-hot, cùng thứ tự với cột 16-20
             của file cạnh.
  Cột 6      has_block_link: 1 nếu issue có link Block hoặc Depend.
  Cột 7      log1p(số link) / log1p(số link lớn nhất trong instance).

Cột 6 và 7 lấy từ trạng thái cuối cùng của issue, nên chứa luôn thông tin
về nhãn v3 (rò rỉ nhãn). Khi build với --leak-safe thì hai cột này được
đặt về 0.


4. THỐNG KÊ
-----------
  Dataset  Sự kiện   Node     Khoảng thời gian      Sự kiện nhãn 1    Issue nhãn 1
  JFrog     55.666   12.165   2006-10 -> 2022-01    1.754 (3,2%)        432
  Mojang   210.411   49.516   2014-01 -> 2022-01      116 (0,06%)        28
  Spring   372.553   67.691   1970-01 -> 2021-10    9.598 (2,6%)      2.714

Spring có 26 sự kiện với ts = 0 (ngày 1970-01-01) do thiếu timestamp lúc
tiền xử lý. Khi chia train/test theo thời gian, các sự kiện này sẽ rơi hết
vào tập train.


5. ĐIỂM LỆCH GIỮA CODE, DOCSTRING VÀ DỮ LIỆU THẬT
--------------------------------------------------
(1) Docstring ở đầu to_tgn.py ghi sai chỉ số cột. Docstring ghi cột 22 là
    log1p(số ngày từ sự kiện trước), nhưng code dùng cột 22 cho cos của giờ
    trong ngày. Feature khoảng cách thời gian không được tính ở đâu cả,
    cột 23 luôn bằng 0. Các khoảng cột khác trong docstring cũng bị lệch so
    với bảng ở mục 2; bảng ở mục 2 là bảng đúng.

(2) Cột 14 (hướng link) bằng 0 ở cả 3 dataset, dù có hàng nghìn sự kiện
    link. Có thể điều kiện out_key == key ở events.py:146 không bao giờ đúng.

(3) Các file này được build ngày 2026-10-01, trước khi sửa 2 bug ngày
    2026-10-04:
    - JFrog có mức ưu tiên luôn bằng 0.4 cho mọi issue (cột 15 của file
      cạnh, cột 0 của file node). Đây là bug không nhận ra tên dạng
      "4 - Normal".
    - Cột 6 của file node (has_block_link) bằng 0 trên toàn bộ JFrog và
      Spring, dù hai dataset này có lần lượt 432 và 2.714 issue mang nhãn
      dương. Đây là bug so tên loại link chưa chuẩn hóa.
    Nếu muốn có feature đúng, cần chạy lại jira_adapter/build_mongo.py
    rồi nén lại.

(4) Nhãn v3 bị rò rỉ qua feature loại link (cột 5-13 của file cạnh, cột 6-7
    của file node). Trên JFrog, AUC của tác vụ T1 là 0,839 với đầy đủ
    feature; bỏ feature loại link thì còn 0,620; bỏ thêm sự kiện link thì còn
    0,484, tức ngang đoán ngẫu nhiên.
    Xem docs/phuong-an-gan-nhan-bottleneck-bang-llm.md.


6. CÁCH DÙNG
------------
  unzip ml_v3_datasets.zip -d data/
  python train_self_supervised.py -d JFrog ...

Loader (utils/data_processing.py) đọc ./data/ml_{name}.csv, .npy, _node.npy.
