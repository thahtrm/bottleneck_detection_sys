# Đóng góp

1. Môi trường: `pip install -r requirements-lock.txt && pip install -e ".[train,dev]" --no-deps`
   (hoặc chỉ `pip install -e ".[dev]"` nếu không huấn luyện lại).
2. Trước khi gửi thay đổi: `ruff check src tests training` và `pytest` phải sạch.
3. Quy tắc kiến trúc:
   - Mọi đặc trưng dùng lúc suy luận chỉ có **một** cài đặt, nằm trong `src/early_risk_detection/`.
     Script huấn luyện import từ thư viện, không sao chép code đặc trưng.
   - Đặc trưng phải tính được tại thời điểm tạo issue (T0): chỉ dùng sự kiện có `ts < T0`,
     mọi encoder / scaler / SVD chỉ `fit` trên tập train và được lưu vào bundle.
   - Thay đổi làm đổi đặc trưng hoặc định dạng bundle phải tăng `FORMAT_VERSION`
     (`bundle.py`) hoặc phiên bản thư viện, và huấn luyện lại bundle.
4. `training/*/baselines/` và `experiments/archive/` là mã nghiên cứu, không có cam kết ổn định API.
