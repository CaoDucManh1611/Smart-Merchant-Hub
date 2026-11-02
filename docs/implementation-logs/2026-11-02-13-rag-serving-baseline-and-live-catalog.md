# 13 — BM25 serving baseline, hybrid/PPR ablation, và dữ liệu catalog hiện hành

**Trạng thái:** Đã cập nhật mã nguồn trong working tree; chưa commit, chưa push. Chưa khởi động lại server.

## Thay đổi

- Đặt `RAG_RETRIEVAL_MODE=bm25` làm mặc định. Serving chỉ chạy BM25, không gọi embedding, RRF hay PPR ở chế độ này.
- Giữ nhánh Gemini vector + BM25 + RRF để đánh giá bằng `retrieval_mode="hybrid"`. PPR chỉ chạy khi caller thí nghiệm truyền `enable_ppr=True`; các script đánh giá đã chọn chế độ rõ ràng để benchmark không phụ thuộc cấu hình serving.
- Giữ helper PPR cho ablation offline. Không có đường gọi serving nào bật PPR.
- Giữ lọc `business_id`/shop, SKU và thuộc tính kiểu chính xác ngay trong truy vấn lexical/vector, trước `LIMIT`; mở rộng chunk cũng giữ bộ lọc. Bổ sung kiểm tra hồi quy cho SQL lexical và vector.
- Loại trọng số RFM khỏi retrieval/chat RAG, gồm cả graph hội thoại. Pipeline gợi ý sản phẩm vẫn nhận tín hiệu cá nhân hóa ở bước rerank sản phẩm.
- Nguồn CRM hiện hành cho sản phẩm được nhận diện nay ghi rõ trạng thái bán, giá và tồn khả dụng, kể cả mặt hàng ngừng bán; prompt yêu cầu trạng thái CRM thắng tài liệu cũ và không khẳng định mua được khi không còn bán/hết hàng. Nguồn được gắn nhãn để trích dẫn.
- Giữ nguyên cơ chế trích nguồn, từ chối khi thiếu bằng chứng và chuyển nhân viên.

## Kiểm tra

- `test_rag_components.py`, `test_rag_tenant_isolation.py`, `test_chatbot_answer_routing.py`: **101 passed**.
- `test_rag_crm_model_integration.py`: lần chạy đầu **45 passed, 1 failed** vì test fallback không chọn hybrid tường minh sau khi đổi mặc định; đã sửa test để chọn hybrid, rồi chạy lại case đó: **1 passed**. Chưa chạy lại toàn bộ file sau sửa.
- Trong container backend với test DB cô lập, `test_conversation_context.py`, `test_auto_reply_channels.py`, `test_chatbot_bandit_runtime.py`, `test_personalized_rag_pipeline.py`: **78 passed, 1 failed**. Case lỗi là `test_feedback_becomes_one_traced_reward_and_is_tenant_safe` (feedback endpoint trả 400, test đòi 200); các luồng RAG/context/recommendation còn lại trong lần chạy đều qua.
- `py_compile` các file Python đã sửa: **thành công**.
- Cấu hình `RAG_RETRIEVAL_MODE` trong môi trường backend và worker đọc thành `bm25`.
- Không chạy migration hay benchmark dữ liệu thật ở lượt này.

## Giới hạn và ghi chú

- Số đo benchmark tham chiếu log #12, không được tính lại: BM25 NDCG@5 **0.945888**; hybrid không PPR **0.852113**; hybrid có PPR **0.620618** trên 243 case đủ nhãn.
- Chưa bật hybrid mặc định vì điểm trước đó thấp hơn BM25; chưa chạy đánh giá câu trả lời cuối bởi người duyệt trong lượt này.
- Mã hiện hành đã đổi, nhưng tiến trình backend/worker đang chạy chưa được restart; cần restart để nạp cấu hình và code mới. Không restart lượt này để tránh chạy lại các lệnh migration trong startup backend.
