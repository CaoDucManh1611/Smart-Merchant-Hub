# Kiểm tra chuỗi chunk → embedding → pgvector

Ngày 25/11/2026. Kiểm tra chỉ đọc source và dữ liệu đang chạy của shop_7; không thay cấu hình/index trong lần rà soát này.

## Kết luận
Hệ thống chia đoạn, tạo embedding và lưu vector hoạt động về kỹ thuật. Chưa thể coi pipeline đã tối ưu đầy đủ: đầu vào embedding thường vượt giới hạn token của model; chế độ truy xuất mặc định vẫn BM25.

## Kết quả đo
| Hạng mục | Tài liệu 3: quy tắc chat | Tài liệu 5: hồ sơ demo |
|---|---|---|
| Chunk khai báo/thực tế | 7/7 | 42/42 |
| Vector không NULL | 7 | 42 |
| Embedding status | ready | ready |
| Số chiều | 768 | 768 |
| Độ dài nội dung theo ký tự | 17–783 | 230–423 |
| Token đầu vào gồm context | 44–236 | 81–166 |
| Chunk vượt max_seq_length=128 | 4/7 | 40/42 |

Không có chunk rỗng, chỉ số chunk liên tiếp. Vector đều hữu hạn, chuẩn L2 gần 1 (khoảng 0.99999989–1.00000008). Cột DB vector(768), có HNSW index dùng vector_cosine_ops, index theo document_id. Metadata có source, source_content_hash, source_revision, section, parent_start/end, context, chunking_version.

## Phát hiện P1: chunk theo ký tự không bảo đảm vừa giới hạn model
RAG_CHUNK_SIZE=800, overlap=100 là cấu hình chia đoạn theo ký tự; encoder sentence-transformers/paraphrase-multilingual-mpnet-base-v2 có max_seq_length=128 token. Đo bằng tokenizer thật với contextual_embedding_text tương đương lúc ingestion cho thấy 44/49 đầu vào vượt mức đó. SentenceTransformer encode giới hạn theo max_seq_length, nên vector không đại diện đầy đủ phần cuối chunk. Không mất văn bản nguồn: content gốc vẫn lưu đầy đủ, và sau retrieve vẫn có thể được đưa vào trả lời. Tác động chính là giảm khả năng tìm đúng bằng ý nghĩa, nhất là chi tiết cuối đoạn.

Đề xuất: chia embedding theo token và tính cả context, giữ điều kiện/cảnh báo cùng nội dung; kiểm tra tự động không chunk nào vượt giới hạn. Nếu đổi model hoặc thay max length thì phải xác nhận model hỗ trợ, đánh giá lại và reindex đồng bộ; không tự tăng max length hay đổi model rồi dùng lẫn vector cũ.

## Phát hiện P1: vector sẵn sàng nhưng chatbot chưa mặc định dùng
Cấu hình thực tế RAG_RETRIEVAL_MODE=bm25; đường retrieve chọn mode theo cấu hình. Vì vậy vector có trong DB không có nghĩa mỗi câu hỏi chatbot dùng cosine search. Hybrid đã được thử riêng thành công trên backend và worker: BM25=9, vector=9, trả 3 chunks. SQL cosine tìm sữa rửa mặt cũng trả bằng chứng phù hợp trong top3. Đây là bằng chứng chức năng, chưa phải đánh giá chất lượng trên bộ câu hỏi lớn.

Đề xuất sau khi xử lý giới hạn token: đánh giá BM25/hybrid/auto cùng tập câu hỏi (tên/SKU, từ đồng nghĩa, công dụng, điều kiện cuối đoạn, câu không có đáp án), đo hit@k và độ trễ rồi mới chọn mode chạy thật. Không coi sửa thư viện là đã tự bật hybrid.

## Các phần đã đúng trong source
- Ingestion dùng context cho embedding nhưng giữ source text cho trích dẫn.
- Batch vectors được kiểm tra số lượng/số chiều/giá trị hữu hạn trước khi lưu.
- Pipeline có lexical fallback khi embedding lỗi, trạng thái embedding riêng để không đánh đồng lexical-only với ready vectors.
- Retrieval lọc document.status=ready và business_id. Tài liệu 2 disabled nên không thuộc nguồn đang phục vụ; từng tenant dùng schema riêng.
- Có snapshot index trước khi reindex, tạo lại mappings theo SKU; hai tài liệu đang bật đã có đủ vector.

## Kiểm tra tự động
28 test semantic chunking, retrieval audit, embedder dimensions đạt trong container backend hiện tại. Các test này không bắt được vấn đề thực tế về tokenizer length nêu trên; cần thêm ca giới hạn token khi triển khai sửa chunking.

## Ưu tiên
1. Token-aware embedding chunks + kiểm tra giới hạn + reindex.
2. Đánh giá và chọn BM25/hybrid/auto với tiêu chí rõ.
3. Kiểm tra đầu-cuối qua chatbot và connector; không suy từ kết quả lưu vector rằng mọi kênh trả lời đúng.
