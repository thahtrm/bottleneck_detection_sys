# Hướng dẫn Chat PM Early Risk

Tài liệu seed đã duyệt — chỉ prose hướng dẫn. **Không** chứa số liệu board / sprint / issue sống.

## Chat dùng để hỏi gì

- Tiến độ sprint đang chạy
- Issue bị block, nguy cơ trễ, sắp đến hạn, quá hạn
- Ai đang được giao nhiều việc chưa xong
- Issue được đánh dấu quan trọng
- Tra cứu một mã issue trong đúng project đang chat

Ngoài phạm vi (thời tiết, viết code, đổi lịch báo cáo qua chat, ghi Jira tự động): hệ thống trả lời cố định rằng chưa có trong hệ thống.

## Ý nghĩa mức rủi ro

- **LOW**: theo dõi thường, chưa cần ưu tiên ngay.
- **MED**: cần chú ý trong sprint; cân nhắc xử lý sớm.
- **HIGH / CRITICAL**: ưu tiên xem xét ngay; kiểm tra block, hạn và assignee.

Mức rủi ro trên board luôn lấy từ tool lookup / digest — không suy ra từ tài liệu này.

## Cách đọc câu trả lời

1. Khối sự thật: số đếm và danh sách issue do hệ thống lấy từ board.
2. Khối đề xuất: gợi ý hành động; mọi mã issue phải nằm trong danh sách được phép từ tool.
3. Báo cáo định kỳ và tin việc gấp đi vào cùng timeline chat; không phải câu trả lời Q&A.

## RAG

Tài liệu trong `var/rag/seed/` chỉ giải thích quy trình. Nếu xung đột với số liệu tool → tin tool.
