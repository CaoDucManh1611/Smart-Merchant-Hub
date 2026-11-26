# Sửa hỏi chi tiết theo tên không có dung tích
Nguyên nhân: scope detail chỉ nhận tên đầy đủ gồm dung tích hoặc nhóm hàng. Câu gọi đúng tên riêng nhưng bỏ250ml bị mở rộng cả nhóm; từ đấy chưa được nhận là phần câu hỏi. Fallback AI gặp429/ApiKeyPoolUnavailable trong log worker.
Thay đổi: detail scope đối chiếu tên sau khi bỏ đơn vị đo; ưu tiên tên riêng dài nhất, giữ tất cả SKU nếu thực sự cùng tên. Thêm đấy vào ngữ pháp tham chiếu. Lời chào đơn thuần có tiểu từ nhá/nhé xử lý local, sau kiểm tra phiên thu thập đang hoạt động.
Kiểm chứng:5 test mới tái hiện lỗi trước sửa đều fail; sau sửa tổng111 test pass, gồm detail-variant, price-scope, overview-scope và catalog dialogue. Mô phỏng AI unavailable trên danh mục shop8 với ngữ cảnh thử không ghiDB: hai câu thực tế đều trảST-250 99000 tồn34, công dụng/cách dùng; không cóST-500. Không gửi tin quaTikTok, không tạo đơn.
Giới hạn: API AI vẫn có thể429 ở những ý định khác cầnAI; bản sửa này không tăng hạn mức nhà cung cấp. Không sửa connector hoặc dữ liệu shop.
Đã restart backend/worker để nạp code mới.
