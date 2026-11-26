# Yêu cầu danh mục cơ bản không phụ thuộc API AI
- Sửa từ đệm với/giúp/nhé trong nhận diện nhóm: toàn bộ/tất cả sản phẩm của bạn không còn bị coi là tên nhóm không tồn tại.
- Hỏi gợi ý chung tiếng Việt: hỏi nhóm hàng/nhu cầu/ngân sách thay vì gọi AI hoặc chọn đại sản phẩm.
- Ngân sách đơn giản không kèm yêu cầu chuyên biệt: dùng parser VND sẵn có, lọc giá và tồn khả dụng theo shop. Dưới là <, tối đa/không quá là <=; không dùng nhánh này để nuốt yêu cầu có thêm tên/chính sách ngoài phạm vi.
- Không sửa API key hoặc quota nhà cung cấp. Các câu cần suy luận khác vẫn có thể phụ thuộc AI.
- 6 trường hợp mới tái hiện thất bại khi mô phỏng AI unavailable trước sửa, sau sửa tổng117 test PASS (basic, named detail, variant, price, scope, dialogue).
- Kiểm tra trực tiếp dữ liệu shop8 trong ngữ cảnh giả lập không ghi DB: danh sách đủ24, xin gợi ý hỏi tiêu chí, dưới200k trả son59000/mặt nạ79000/sữa rửa mặt89000.
- Chưa gửi tin qua kênh khách, không tạo đơn. Đã restart backend/worker.
