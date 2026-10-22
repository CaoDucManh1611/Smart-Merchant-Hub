# Kho tư vấn dịch vụ và chatbot chọn gói

- Admin mở **Kho tư vấn dịch vụ**, chọn PDF có văn bản, DOCX, TXT hoặc Markdown (tối đa 10 MB; 200.000 ký tự).
- Tài liệu mới ở dạng nháp. Xem trước rồi bật **Dùng để tư vấn**. Tắt lại để ngừng dùng cho câu hỏi mới. Các câu trả lời đã hiển thị trong phiên chat không bị sửa lại.
- Chỉ công bố thông tin có thể chia sẻ với khách: chính sách triển khai, hướng dẫn đăng ký, giải thích tính năng, FAQ. Không nhập dữ liệu riêng của shop.
- Trợ lý **Tư vấn chọn gói** xuất hiện ở trang giới thiệu/bảng giá trước đăng nhập và trang chọn gói dành cho shop. Có nút mở bảng giá/đăng ký; chatbot không tự kích hoạt gói hoặc nhận thanh toán.
- Giá quản lý và giá thuê chatbot được đọc từ cùng danh mục đang dùng cho onboarding; không lấy bảng giá cũ từ tài liệu. Bảng gói trả về riêng hai khoản phí.
- Kho nằm trong `platform_knowledge_documents` ở database nền tảng, không dùng bảng tài liệu của tenant. Bản sao lưu admin bao gồm bảng này.
- Dùng lại loader/chunker, tìm kiếm từ khóa cục bộ trên tài liệu đã bật. Không gọi embedding AI khi tải lên. Câu hỏi chỉ đối chiếu giá/hạn mức được trả lời bằng danh mục mà không gọi AI. Khi có tài liệu liên quan, dùng luồng LLM trả lời hiện có (kèm model dự phòng của hệ thống), không thêm lượt AI chấm điểm.
- Lịch sử hội thoại chỉ giữ trong bộ nhớ của tab, gửi tối đa 6 lượt gần nhất. Không lưu hội thoại tư vấn vào hộp thư của shop.
- Có giới hạn 12 câu/phút theo IP ngang hàng và giới hạn chung `SERVICE_ADVISOR_DAILY_LIMIT=200` mỗi 24 giờ. Redis chia sẻ bộ đếm giữa các backend; lỗi Redis sẽ ngừng nhận yêu cầu mới. Không tin header IP do khách tự gửi. Sau reverse proxy, các khách có thể dùng chung hạn mức IP; cấu hình proxy/IP tin cậy cần đánh giá trước khi mở lớn.
- Lỗi model có phản hồi dự phòng dựa vào thông tin công khai và bảng gói. Không trả lỗi provider hay cấu hình nội bộ cho khách.

## Triển khai

Chạy migration nền tảng trước khi khởi động bản mới:

```powershell
docker compose exec backend python -m alembic -c alembic-platform.ini upgrade head
docker compose restart backend worker
```

Production phải dùng migration `20261020_0004_knowledge`. Backup cũ có migration khác bị từ chối theo chính sách khôi phục hiện có.

## API

- `GET /api/platform/knowledge`: danh sách và xem trước, chỉ admin nền tảng.
- `POST /api/platform/knowledge/upload`: tải tài liệu, tạo bản nháp.
- `PATCH /api/platform/knowledge/{id}` với `{ "published": true/false }`.
- `POST /api/services/advisor/chat` với `question`, `history`, `locale`: công khai, không nhận business/customer/tenant ID.
