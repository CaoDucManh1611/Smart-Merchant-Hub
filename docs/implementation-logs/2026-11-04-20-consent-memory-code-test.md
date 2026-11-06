# 20 - Consent của FAQ feedback và memory của RAG trực tiếp

Ngày 2026-11-04. Không commit/push, không gọi provider hay xuất hội thoại thật.

## Thay đổi

- Export FAQ chỉ xét hội thoại thuộc đúng tenant, customer đang active, không `fact_extraction_opt_out`, và bản ghi consent mới nhất của scope `personalization` là `granted`. Thiếu consent hoặc mới nhất là `revoked` thì bỏ qua trước khi đọc nội dung tin nhắn. Ghi `consent_provenance` (shop, hội thoại, customer, consent ID, purpose, status) vào CSV và hash; schema mới là 2. CSV cũ schema 1 không được duyệt.
- Approval kiểm tra lại tenant registry và consent trực tiếp từ tenant DB. Consent thiếu, bị rút, đổi sang bản ghi khác hoặc khác shop đều từ chối trước khi tạo seed. Provenance trong CSV chỉ để đối chiếu, không là nguồn quyền. Script vẫn chỉ tạo artifact, không tự nhập KB hoặc train.
- Test metadata memory giả mạo trước đây không ghi `True` thay cho `1` xuống PostgreSQL vì Python coi `True == 1`; fixture nay buộc SQLAlchemy ghi JSON đã thay đổi rồi mới đọc kiểm tra. Cổng đọc hiện tại trả state rỗng đúng.
- Luồng `_save_auto_reply_outbound` đã dùng chung cho direct RAG; thêm test lưu reply có `route=direct_rag`, xác nhận metadata memory có product ID đúng và câu hỏi nối tiếp đọc được. Không cần đổi service vì đường lưu hiện có đã nối đúng.

## Kiểm chứng

`python -m pytest -q backend/tests/test_rag_feedback_consent.py backend/tests/test_rag_feedback_artifacts_isolated.py backend/tests/test_rag_faq_candidate_export.py backend/tests/test_conversation_memory_isolated.py` → **99 passed in 29.33s**. Harness dùng cơ sở dữ liệu PostgreSQL test tách biệt theo `conftest.py`; không chạm DB sản xuất.

`git diff --check` → exit 0; chỉ có cảnh báo chuyển LF/CRLF của working copy.

Giới hạn: chỉ dùng consent scope `personalization` đang có trong hệ thống; chưa có mục đồng ý riêng cho tái sử dụng hội thoại vào FAQ. Cần xác nhận phạm vi chính sách sản phẩm trước khi phát hành seed ra KB. Test không thay thế kiểm chứng hành vi chatbot thực tế qua kênh.
