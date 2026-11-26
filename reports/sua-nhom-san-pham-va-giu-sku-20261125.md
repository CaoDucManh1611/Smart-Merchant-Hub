# Sửa phân nhóm và giữ SKU khi đặt hàng
- Phân nhóm ưu tiên product_profile.category, attributes.category, metadata.category; fallback bỏ quy cách cuối tên. Không sửa dữ liệu sản phẩm.
- Khi duyệt nhóm, liệt kê mọi SKU trong nhóm, không lọc theo shortlist cũ hoặc tự chọn một dung tích do LLM gợi ra. Nhóm rõ từ danh mục được xử lý trực tiếp.
- Câu tham chiếu như đặt nó ưu tiên sản phẩm vừa xác định, đọc provenance catalog_dialogue.shortlist; không dùng từ đặt để chọn nhóm đất sét/tẩy trang.
- Tên rút gọn khớp nhiều phiên bản cùng nhóm: giữ lựa chọn trước đó nếu rõ; chưa rõ thì hỏi phiên bản, không tự chọn hoặc gom hết thành giỏ.
- Hỏi số lượng kèm tên/đơn giá; nhận một sau động từ đặt/mua/chốt là số lượng rõ.
- Kiểm thử: 140 passed (RUN_POSTGRES_TESTS=0, CATALOG_DIALOGUE_ENABLED=false cho suite legacy; test graph mới bật semantic riêng và mock bộ nhận diện). Có 7 test tái hiện nhóm mặt nạ/giữ100g và toàn luồng hỏi số lượng→báo189000.
- Read-only shop8:24 SKU/12 nhóm; MND-030 79000, MND-100 189000; render đúng 12 nhóm.
- Đã restart backend/worker. Chưa gửi tin qua TikTok hoặc tạo đơn thật; chưa chứng minh end-to-end giao tin.
- Files: catalog_dialogue.py, catalog_overview.py, product_resolver.py, customer_collection_flow.py; test_catalog_mask_regression.py, test_natural_checkout_regressions.py.
