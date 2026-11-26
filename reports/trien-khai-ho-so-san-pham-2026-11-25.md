# Nhóm sữa rửa mặt demo

Mốc source trước thay đổi: 6276e40.
Database trước chỉnh: backups/before-product-profile-20261125.dump (PostgreSQL custom dump crm_tenant).
Bản gốc metadata/mô tả 4 SKU: backups/product-profiles-before-20261125.json.

Không đổi schema database. Dùng metadata.product_profile với benefits, suitable_needs, usage, warnings, demo. Đã bổ sung 4 SKU DEMO-BEA-01-1 đến 01-4 trong shop_7. Không đổi giá/tồn hay luồng đặt đơn. Công dụng chỉ là làm sạch da mặt, ghi rõ demo; không khẳng định thành phần, loại da hay hiệu quả điều trị.

Chi tiết sản phẩm đọc các trường có thật. Gợi ý nhu cầu có cấu hình dùng danh mục active/còn hàng, kiểm tra ngân sách và trả tối đa 3 lựa chọn theo giá. Nhánh này là lọc nhu cầu trực tiếp; phần cá nhân hóa/xếp hạng cũ vẫn còn. Bổ sung trường công dụng vào tín hiệu khớp câu hỏi của bộ xếp hạng cũ.

Đã kiểm tra 2 test về lọc đúng nhu cầu/ngân sách/tồn và hiển thị demo. Gọi graph trực tiếp với câu “nhu cầu rửa mặt và dưới 200000” trả đúng Sữa rửa mặt dịu nhẹ – Tiêu chuẩn 119.000 đồng. Không gửi tin Zalo và không tạo đơn trong lần kiểm tra này.

knowledge_base/sua-rua-mat-demo-ho-so-san-pham.md là bản nội dung mới đã soạn trên đĩa; chưa nạp vào RAG hoặc thay tài liệu đang bật. Hiện thông tin demo được trả qua hồ sơ CRM, không phụ thuộc tài liệu kiểm thử. Cần shop cung cấp nội dung thật trước khi hoàn thiện và thay tài liệu RAG đang chạy. Không được tự suy công dụng khác nhau giữa các biến thể chỉ từ tên.

Khôi phục source theo mốc 6276e40 không tự khôi phục database. Việc phục hồi dump cần dừng dịch vụ và chọn phạm vi khôi phục, vì ghi đè có thể mất đơn phát sinh sau thời điểm sao lưu. Không tự chạy phục hồi toàn bộ khi hệ thống còn dùng.
