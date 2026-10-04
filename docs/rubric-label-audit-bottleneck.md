# Rubric Label-Audit: "Điểm nghẽn" trong quản lý dự án phần mềm

**Mục đích:** Kiểm tra *face validity* của danh sách issue do heuristic/mô hình chấm điểm bottleneck — issue top-scored có thực sự "trông như" điểm nghẽn trong mắt người có kinh nghiệm quản lý dự án không? Đây là bước **audit mẫu** (200–500 issue), không phải gắn nhãn cho toàn bộ dữ liệu.

**Thời gian dự kiến cho người chấm:** 200 issue × 1–2 phút ≈ 3–6 giờ (tách được thành 2–3 buổi).

---

## Cách chấm

Với **mỗi issue** trong danh sách, nhìn vào 5 thông tin được cung cấp (tên, mô tả, trạng thái hiện tại, thời gian không hoạt động gần nhất, số issue đang phụ thuộc nó / nó đang chặn, người phụ trách, độ ưu tiên) rồi chấm 3 trục **B1, B2, B3** theo thang 0–2 bên dưới, sau đó trả lời 1 câu tổng kết.

| Trục | Câu hỏi nền | 0 | 1 | 2 |
|---|---|---|---|---|
| **B1 — Issue nghẽn / nghẽn phụ thuộc** | Issue này (và các issue phụ thuộc nó) có đang bị chôn? | Không chặn gì, không thấy gây trễ | Chậm/chặn 1–2 issue, vẫn có tiến triển | Tồn đọng **và** chặn nhiều issue quan trọng / chuỗi phụ thuộc dài, ưu tiên cao |
| **B2 — Người phụ trách nghẽn** | Người phụ trách có dấu hiệu quá tải không? | Tải bình thường, phản hồi đúng lúc | Nhiều issue mở ưu tiên cao, phản hồi chậm dần | Rõ quá tải: nhiều việc ưu tiên cao ứ cùng lúc, im lặng dài |
| **B3 — Quy trình nghẽn** | Issue có bị ứ ở một trạng thái so với "thói quen" của dự án không? | Di chuyển trạng thái bình thường | ứ ở 1 trạng thái lâu hơn thường | Ứ rất lâu / cùng trạng thái với nhiều issue khác (dấu hiệu nghẽn hệ thống: chờ review, chờ phê duyệt, chờ bên ngoài) |
| **TỔNG KẾT** | Nếu là PM, hôm nay bạn có muốn được cảnh báo về issue này không? | **Không** | **Có thể** (ghi lý do) | **Có — đây là bottleneck** (ghi 1 dòng lý do) |

**Hướng dẫn bổ sung:**
- Chấm theo **bằng chứng được hiển thị**, không cần mở Jira. Nếu thiếu thông tin để chấm một trục → để trống (không đoán).
- "Tồn đọng" = thời gian không có hoạt động (chuyển trạng thái/comment/assignee) dài so với tuổi issue và thông lệ dự án.
- Không trừ điểm vì issue đã closed — danh sách chỉ gồm issue **đang mở**.
- Nếu issue chỉ "lớn/đắt" nhưng đang tiến hành bình thường → B1 = 0–1, không phải bottleneck.

## Bảng chấm (mẫu)

| # | Issue key | Dự án | Trạng thái | Tuổi | Không hoạt động (d) | Đang chặn / bị chặn | Ưu tiên | Assignee | **B1** | **B2** | **B3** | **Tổng kết** | Lý do (tự do) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | / | | | 0-1-2 | 0-1-2 | 0-1-2 | K/CK/C | |
| 2 | | | | | | / | | | | | | | |
| … | | | | | | / | | | | | | | |

## Thống kê rút ra sau audit (tính tự động từ bảng)

| Chỉ số | Công thức | Ý nghĩa | Ngưỡng tham khảo |
|---|---|---|---|
| **Agreement (top-k)** | % issue được chấm "Có" trong top-k của mô hình/heuristic | Mô hình có chỉ đúng thứ PM quan tâm không? | ≥ 40% ở top-50 là khả quan |
| **Precision theo trục** | % "Có/Tổng" trong đó trục đó ≥ 1 | Trục nào đáng tin, trục nào nhiễu | So sánh 3 trục để cân trọng số `w1..w4` |
| **Trọng số đề xuất** | Từ tần suất các trục ≥ 2 khi Tổng kết = "Có" | Hiệu chỉnh `w1..w4` trong công thức nhãn §6.1 | — |
| **Lý do định tính** | Phân loại tự do-text (chờ review / chờ bên ngoài / thiếu người / scope lớn / …) | Phát hiện tín hiệu chưa có trong feature (vd "chờ phê duyệt") → đề xuất feature mới | — |

## Quy tắc vàng

1. **Audit không thay thế nhãn** — nó hiệu chỉnh trọng số và phát hiện "blind spot" của công thức nhãn.
2. Nếu agreement top-k < 25% → **dừng lại**, xem lại định nghĩa bottleneck với người chấm trước khi huấn luyện (rẻ hơn 5 ngày GPU).
3. Nếu có thể, mời **2 người chấm độc lập** trên cùng 100 issue → tính inter-rater agreement (Fleiss' kappa / percent agreement) để biết bản thân khái niệm "bottleneck" còn bao nhiêu nhiễu chủ quan.
