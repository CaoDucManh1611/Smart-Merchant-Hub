# Sửa các câu trả lời RAG lệch trong hội thoại shop

Ngày: 2026-11-03

## Phạm vi

Đối chiếu các câu 21–50 người dùng đã gửi từ hội thoại với bot. Chỉ chỉnh các nhánh trả lời có thể xác định bằng catalog và dữ liệu hội thoại hiện có; không tự thêm giá, chính sách hay cam kết tương thích.

## Đã cập nhật

- Câu hỏi so sánh giá theo hai kích cỡ/SKU nhận danh sách đúng hai sản phẩm, giá, tồn khả dụng và chênh lệch khi khách hỏi. Nếu không xác định được đúng hai món thì hỏi rõ tên/SKU, không thay bằng sản phẩm rẻ nhất ở nhóm khác.
- Yêu cầu ngân sách, món rẻ nhất, ba món rẻ nhất và tồn kho cao nhất đi theo truy vấn catalog có cấu trúc; câu “có thể mua” chỉ liệt kê món còn hàng.
- Yêu cầu nhiều món giữ lại các danh tính sản phẩm được nêu cùng nhau; khi có nhiều biến thể, liệt kê lựa chọn và hỏi làm rõ thay vì cộng tổng các phương án thay thế.
- Câu tiếp nối chỉ dùng sản phẩm ở lượt trao đổi gần nhất. Tên/giá/tồn được tra lại từ catalog hiện hành; nếu lượt trước có nhiều món thì không tự chọn một món.
- Câu hỏi xác nhận lắp vừa xe phải có dữ liệu xe. Với SKU rõ nhưng thiếu đời xe, trả thông tin catalog đã biết rồi nói rõ chưa thể bảo đảm tương thích.
- Câu hỏi gợi ý được đưa qua nhánh trả lời xác định trước để yêu cầu fitment không bị thay bằng một món phổ biến không liên quan.
- Bộ phân giải không chọn phương án chỉ vì SKU có ID nhỏ hơn khi các sản phẩm cùng điểm khớp; trường hợp hòa được coi là mơ hồ.

## Giới hạn

- Tồn kho trong catalog là cấp shop. Số lượng riêng TikTok/Shopee vẫn cần Seller Center nếu chưa đồng bộ feed tồn theo kênh.
- Giá công sửa/thay chỉ trả lời được nếu shop đã khai báo dịch vụ tương ứng; nếu chưa có thì phải báo chưa cấu hình/chuyển shop xác nhận.
- Chưa chạy test hoặc gửi câu mới qua Telegram trong lượt này. Cần kiểm tra bằng các câu mẫu trên môi trường local trước khi coi là đã xác nhận hành vi runtime.
- Không commit hoặc push.
