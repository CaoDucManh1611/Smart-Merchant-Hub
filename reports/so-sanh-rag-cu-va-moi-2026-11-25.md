# A/B tìm kiếm RAG: cách đang chạy và cách thử nghiệm

Ngày 25/11/2026. Không đổi RAG_RETRIEVAL_MODE và không thay chunk/vector đang phục vụ. Các bảng thử nghiệm được sao chép vào schema riêng trong transaction; mọi thay đổi schema đã rollback, đã xác nhận schema thử không còn. Tài liệu thật vẫn 7 + 42 chunks, embedding_status=ready.

## Thiết kế thử nghiệm
- 30 câu tự xây từ danh mục demo: 27 có nguồn dự kiến (10 tên nhóm, 10 diễn đạt khác, 3 SKU, 4 quy tắc); 3 câu ngoài phạm vi.
- Cùng truy vấn và nhãn kỳ vọng trên mọi nhánh; dùng retriever SQL hiện có, giữ bộ lọc shop/tài liệu đang bật và ánh xạ SKU.
- Cách A: 49 chunk cũ + BM25 hiện tại. Cách B: 95 chunk theo tokenizer + hybrid. Mọi đầu vào embedding mới <=124 token, dưới giới hạn128, có overlap và giữ nguồn/đoạn gốc.
- Hai nhánh chẩn đoán: hybrid trên chunk cũ và BM25 trên chunk mới để phân biệt ảnh hưởng của chunking với vector.
- Vector câu hỏi được tính trước và dùng chung. Thời gian retrieval dưới đây KHÔNG gồm tạo embedding câu hỏi, tải model hoặc sinh câu trả lời; không phải độ trễ chatbot đầu-cuối.

## Kết quả trên 27 câu có nguồn
| Nhánh | Đúng top1 | Có nguồn đúng trong top3 | MRR@3 | Trung vị retrieval |
|---|---:|---:|---:|---:|
| A — BM25 cũ | 24/27 (88.9%) | 24/27 (88.9%) | 0.8889 | 59.3 ms |
| B — Token-safe + hybrid | 23/27 (85.2%) | 25/27 (92.6%) | 0.8827 | 77.6 ms |
| Chẩn đoán — hybrid/chunk cũ | 24/27 (88.9%) | 24/27 (88.9%) | 0.8889 | 57.1 ms |
| Chẩn đoán — BM25/chunk mới | 25/27 (92.6%) | 25/27 (92.6%) | 0.9259 | 78.9 ms |

## Nhận xét
- B cải thiện top3 đúng thêm 1 câu so với A, nhưng top1 giảm 1 câu và MRR hơi thấp hơn. Chưa có cơ sở thay A bằng B.
- Cả A và B đều đạt 10/10 câu tên nhóm và 3/3 câu SKU trong top3; diễn đạt khác tăng từ 7/10 lên8/10. Các số này chỉ phản ánh tập thử nhỏ.
- BM25 trên chunk mới đạt25/27 cả top1 và top3, tốt nhất trong lần thử này. Điều đó gợi ý chia đúng token có thể hữu ích hơn việc bật hybrid ngay; cần tập kiểm tra độc lập lớn hơn để xác nhận.
- Ví dụ B tốt hơn: “Có món nào dưỡng ẩm cho làn da không?” từ không có nhóm kỳ vọng trong top3 sang có. B kém hơn: “Dầu tẩy trang dùng để làm gì?” từ đúng top1 sang chỉ đúng ở hạng3; câu tẩy trang buổi tối từ top1 sang hạng2.
- Câu “Tôi muốn làm sạch làn da trên mặt sau một ngày đi đường” chưa tìm đúng nhóm sữa rửa mặt ở cả hai. Cần bổ sung/đánh giá từ đồng nghĩa và điều kiện nhu cầu, không chỉ đổi mode.
- Cả4 nhánh đều trả ít nhất một đoạn cho cả3 câu ngoài phạm vi. Đây là vấn đề phân biệt nguồn liên quan/từ chối, không phải bằng chứng LLM đã trả sai: benchmark không sinh câu trả lời.

## Giới hạn phép đo
- Nhãn chấm theo đúng nhóm sản phẩm hoặc tài liệu quy tắc. Có cùng nhóm/tài liệu không bảo đảm đoạn chứa đầy đủ câu trả lời; không chấm độ đúng toàn bộ câu tư vấn.
- Phần nhãn candidate quy về đoạn gốc để so sánh công bằng khi một đoạn được tách nhiều mảnh. Điều này không chứng minh mảnh được trả đã chứa đủ mọi điều kiện.
- Bộ câu hỏi tự xây, dữ liệu demo nhỏ và lặp nhiều biến thể cùng nhóm; không phải benchmark độc lập hay kết quả người mua thực tế. Chênh lệch1/27 không đủ chứng minh ưu thế tổng quát.
- Các câu giá/tồn/đặt hàng thường đi thẳng CRM nên kết quả RAG này không thay cho kiểm tra các luồng đó; chưa đo connector giao tin hay trả lời đa lượt.
- Chạy một lượt/nhánh, có hiệu ứng cache và thứ tự; độ trễ chỉ mang tính tham khảo, không kết luận hiệu năng tổng thể.

## Giữ lại hai phương án
1. A đang chạy nguyên trạng: BM25, 49 chunks, không thay cấu hình phục vụ.
2. B lưu trong token_chunker.py và benchmark_rag_old_vs_new.py để chạy lại; chưa tích hợp bật tự động vào ingestion hoặc UI. Chỉ là phương án thử nghiệm.
Khuyến nghị hiện tại: giữ A để demo. Ưu tiên thử thêm token-safe + BM25, cải thiện xếp hạng và từ chối câu ngoài nguồn trước khi cân nhắc hybrid.

## Tệp và cách chạy lại
- scripts/benchmark_rag_old_vs_new.py: tự tạo schema transaction riêng và rollback, xuất JSON vào backups/rag-ab-old-vs-new-20261125.json.
- backend/app/rag/token_chunker.py: helper thử nghiệm chưa được ingestion thật gọi.
- backend/tests/test_token_chunker.py:2 test đạt về giới hạn, bảo toàn nội dung/nguồn và context dài.
- reports/rag-ab-old-vs-new-20261125.json:120 kết quả chi tiết tương ứng 30 câu x4 nhánh.
Chạy từ repo: docker exec -e PYTHONPATH=/app -e HF_HUB_OFFLINE=1 smart-merchant-hub-runtime-backend-1 python /app/root-scripts/benchmark_rag_old_vs_new.py
Không chạy script nhiều bản đồng thời: tên schema thử cố định và lần chạy mới ghi lại JSON kết quả.
