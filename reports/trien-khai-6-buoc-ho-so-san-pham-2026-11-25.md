# Triển khai hồ sơ sản phẩm và tư vấn demo — 25/11/2026

## Phạm vi
Repo Smart-Merchant-Hub; shop_7/business_id=7; 40 SKU DEMO-BEA thuộc 10 nhóm. Không thay sản phẩm shop khác, cấu trúc database, số lượng tồn, giá, trạng thái bán, đơn hay connector. Hồ sơ mới là nội dung minh họa demo, không phải xác nhận từ nhà sản xuất.

## 1. Trường dữ liệu
Tận dụng Product.description và Product.metadata. Hồ sơ nằm tại metadata.product_profile: category, benefits, suitable_needs, usage, warnings, demo. Không thêm cột hoặc bảng trùng. API sản phẩm hiện đã nhận metadata; có thể cập nhật các trường qua API sẵn có. Chưa thêm form nhập riêng trên frontend.

## 2. Chuẩn hóa
40 SKU đã có nhóm, công dụng minh họa, nhãn nhu cầu, lưu ý. usage để trống vì chưa có hướng dẫn đã xác nhận. Không gán loại da, thành phần, SPF, nồng độ hay dung tích theo suy đoán. Không suy luận công dụng khác nhau từ tên Tiêu chuẩn/Nhỏ gọn/Nâng cao/Bộ đôi.

## 3. Kho tri thức
- Tài liệu 2 (70 câu kiểm thử) chuyển disabled, giữ nguyên source/chunks; đã xuất reports/beauty-70-test-cases.md.
- Tài liệu 3 (quy tắc luồng chat) vẫn ready.
- Tài liệu mới 5 beauty-product-profiles-demo.md đã ready, 42 chunks, 40 ánh xạ SKU.
- Nội dung không đóng băng giá/tồn. Dùng pipeline ingestion sẵn có với reindex_only=True, không nhập sản phẩm từ Markdown.
- Embedding local gặp lỗi thư viện PyTorch/Transformers; pipeline đã dùng lexical_only. Đang có tìm kiếm từ khóa, chưa thể xác nhận tìm kiếm ngữ nghĩa/vector hoạt động. Đây là lỗi môi trường cần xử lý riêng, không tự nâng thư viện hàng loạt trong lần này.

## 4. Chi tiết
_format_product_fact_reply hiển thị công dụng, nhu cầu phù hợp và lưu ý từ hồ sơ cùng giá/tồn hiện tại. Không có hồ sơ thì giữ nhánh trả lời cũ; trường trống không được tự bịa. Mỗi câu trả lời của hồ sơ demo có nhãn minh họa.

## 5. Gợi ý
Nhánh nhu cầu rõ dùng dữ liệu shop hiện tại: active, tồn khả dụng >0, ngân sách và nhãn nhu cầu. Ưu tiên nhóm khách nêu rõ và nhu cầu cụ thể nhất, tránh dưỡng ẩm môi chuyển sang toner dưỡng ẩm. Không đủ ngân sách thì không tự nới nhu cầu để lấy món không liên quan. Tối đa 3 lựa chọn theo giá tăng dần, kèm công dụng; đây là lọc theo nhu cầu trực tiếp, không phải thay toàn bộ xếp hạng cá nhân hóa. Công dụng cũng được thêm vào tín hiệu khớp câu hỏi của bộ xếp hạng cũ. Câu quá chung tiếp tục hỏi nhu cầu/ngân sách.

Phạm vi hiểu nhu cầu dựa trên các nhãn shop cấu hình, không đảm bảo hiểu mọi từ đồng nghĩa tự do. Các thuộc tính chưa xác nhận không được coi là điều kiện đã đáp ứng.

## 6. Kiểm tra
- Test hồ sơ: 9 ca, gồm đúng nhu cầu, ngân sách, tồn sau giữ chỗ, inactive, không có hồ sơ, không có nhu cầu, nhu cầu cụ thể, đúng nhóm và giá thay đổi.
- Kiểm tra đọc trực tiếp graph: 50 ca trên nhãn Zalo/Telegram/Facebook/Instagram/TikTok, có lịch sử conversation 24 và ID không có lịch sử; cùng customer để giữ nguyên điều kiện khác. Đây không phải thử tài khoản khách mới thật.
- 40 hồ sơ được kiểm tra có nội dung; ngân sách 200k đọc là 200000.
- Kiểm tra trực tiếp câu nhu cầu rửa mặt dưới 200000 trả Sữa rửa mặt Tiêu chuẩn 119000; chi tiết có công dụng.
- Đã xác nhận doc 2 disabled, doc 5 ready/42 chunks. Không gửi tin ra nền tảng, không tạo đơn/ghi thanh toán trong ca kiểm tra này.
- Giao nhận đầu-cuối qua connector và tài khoản khách mới thật CHƯA xác nhận. Không được coi 50 ca lõi là 50 tin đã giao qua nền tảng.

## Sao lưu / khôi phục
Source trước thay đổi: commit 6276e40. Database trước mở rộng: backups/before-full-profiles-20261125.dump. Bản gốc metadata 40 SKU: backups/all-demo-profiles-before-20261125.json. Bản trước pilot vẫn có backups/before-product-profile-20261125.dump.
Để hoàn tác riêng tri thức: bật lại doc 2, tắt doc 5; không xóa tài liệu. Khôi phục source không hoàn tác dữ liệu. Nên phục hồi riêng metadata theo ID/SKU để giữ đơn phát sinh sau sao lưu; phục hồi dump toàn bộ cần dừng dịch vụ và đánh giá dữ liệu mới trước.

## Các file vận hành
scripts/prepare_demo_product_profiles.py: tạo hồ sơ demo và xuất tài liệu; có thay dữ liệu, không chạy lại tùy tiện nếu shop đã chỉnh hồ sơ.
scripts/publish_demo_product_knowledge.py: nạp tài liệu và chuyển hiệu lực sau ingest thành công.
scripts/verify_demo_profiles.py: kiểm tra graph chỉ đọc, không giao tin ra provider.
