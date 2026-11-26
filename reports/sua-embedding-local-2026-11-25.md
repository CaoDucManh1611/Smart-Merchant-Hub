# Sửa embedding local — 25/11/2026

Nguyên nhân: image dùng torch 2.2.2+cpu cùng sentence-transformers 6.2.0 / transformers 5.22.2. Transformers vô hiệu hóa torch vì yêu cầu >=2.6, dẫn tới lỗi tải encoder và ingestion lexical_only.

Sửa: cố định sentence-transformers==6.2.0, transformers==5.22.2, torch==2.6.0+cpu trong backend/requirements.txt. Dựng lại backend/worker. Thêm volume embedding_cache dùng chung tại /root/.cache/huggingface trong docker-compose.yml để giữ trọng số khi tạo mới container. Model giữ nguyên sentence-transformers/paraphrase-multilingual-mpnet-base-v2; vector 768 chiều, không đổi DB vector column hay provider.

Kiểm tra: model thực tạo batch và query 768 chiều, hữu hạn; câu rửa mặt có cosine gần tài liệu rửa mặt hơn dầu gội/xe máy. 10 test embedder dimensions và ingestion fallback đạt. Reindex_only hai tài liệu đang bật của shop_7: doc3=7/7 vectors, doc5=42/42 vectors; cả hai embedding_status=ready. SQL pgvector cosine trả nội dung sữa rửa mặt trong top3. Không nhập lại sản phẩm hoặc thay giá/tồn/đơn khi reindex. Tài liệu ngừng sử dụng vẫn giữ nguyên trạng thái.

Các script tái kiểm tra: scripts/verify_local_embeddings.py; scripts/reindex_active_knowledge_embeddings.py. Script reindex thay index tài liệu đang bật, không chạy lặp nếu không cần.

Mô hình public đã tải vào cache; không cần key Groq/Gemini để tạo embedding local. Độ trễ lần tải model đầu tiên khác với thời gian tạo embedding khi model đã ở RAM. Sửa embedding không đồng nghĩa mọi connector đã được kiểm tra giao tin đầu-cuối.

Sau khi tạo lại container bằng image mới: backend và worker đều pip check không lỗi; cả hai chạy smoke test với model lấy từ volume cache, không tải mạng. Hybrid retriever thực tế ghi nhận bm25=9, vector=9, trả 3 chunks. Chế độ mặc định của ứng dụng vẫn là RAG_RETRIEVAL_MODE=bm25 như trước; kiểm tra hybrid được bật riêng trong script xác minh, không tự thay chính sách tìm kiếm đang dùng.
