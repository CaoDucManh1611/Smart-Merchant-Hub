# Khớp tên rút gọn khi xem chi tiết
- Tên sản phẩm bỏ dung tích trước đây vẫn đòi toàn bộ phần tên (mặt nạ đất sét làm sạch). Từ mặt nạ đất sét bị đẩy về cả nhóm Mặt nạ hoặc gọiAI.
- So phần đầu tên từ danh mục, yêu cầu nhiều từ hơn tên nhóm; ưu tiên đoạn nhận diện dài nhất. Nếu nhiều SKU cùng đoạn nhận diện thì giữ tất cả, không chọn tùy ý.
- Câu muốn xem + tên phân biệt duy nhất cũng được xem chi tiết không cần từ chi tiết/thông tin. Các từ còn dư ngoài ngữ pháp an toàn vẫn trả lại nhánh nhận diện cũ, tránh nuốt nhu cầu/chính sách/câu mua hàng.
- Bốn test mới tái hiện lỗi trước sửa đều fail. Sau sửa tổng121 test PASS: chi tiết/tên thiếu dung tích/tên rút gọn/nhóm/giá/câu cơ bản/semantic dialogue.
- Read-only shop8 với AI mô phỏng unavailable: cả3 câu user gửi trả MND-030 giá79000 tồn18 cùng công dụng/cách dùng, không kèm MND-100. Không gửi tin qua nền tảng hoặc tạo đơn.
- Có backup source trước sửa; đã restart backend và worker.
