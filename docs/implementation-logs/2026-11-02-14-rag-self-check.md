# 14 — Kiểm tra retrieval hiện hành trên bộ case đã lưu

**Trạng thái:** Hoàn tất trên PostgreSQL local; chỉ sinh báo cáo, không sửa serving code, migration, commit hay push.

## Phạm vi chạy

- Chạy lại đúng bộ 284 case đã lưu trước đó, gồm 243 case có nhãn retrieval, trên tenant DB local hiện tại.
- So sánh BM25 thô, đường BM25 đầy đủ của `retrieve()`, hybrid Gemini + BM25 + RRF không PPR và hybrid có PPR.
- Tái sử dụng 154 query embedding đã lưu. Không gọi LLM hoặc API embedding.
- Kiểm tra kết quả lọc cứng và các probe cần từ chối.

## Kết quả tổng hợp tại K=5

| Luồng | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 thô trước đa dạng hóa/mở rộng chunk | 0.987654 | 0.931550 | 0.945888 |
| BM25 qua `retrieve()` hiện tại | 0.876543 | 0.835391 | 0.845972 |
| Gemini + BM25 + RRF, không PPR | 0.888889 | 0.839506 | 0.852113 |
| Gemini + BM25 + RRF + PPR (ablation offline) | 0.679012 | 0.602195 | 0.620618 |

Hybrid không PPR chỉ nhỉnh hơn BM25 serving **0.006141 NDCG** (0.61 điểm phần trăm), nhưng thấp hơn BM25 thô **0.093775 NDCG**. PPR tiếp tục giảm mạnh so với hybrid không PPR. Chưa có căn cứ để nói một luồng tốt hơn trên mọi loại câu.

## Chẩn đoán cần xử lý tiếp

- Benchmark BM25 cũ đo thứ hạng lexical thô. Đường serving BM25 còn áp dụng đa dạng hóa và mở rộng chunk; kết quả cuối hiện thấp hơn **0.099916 NDCG**. Lượt này đo chênh lệch tổng, chưa tách riêng ảnh hưởng của hai bước.
- Theo nhóm câu: hybrid tăng nhẹ ở FAQ chính sách (0.892939 so với BM25 serving 0.885712) và chi tiết sản phẩm (0.785489 so với 0.762128), nhưng giảm ở thông tin sản phẩm (0.757635 so với 0.790430).
- SKU đạt 1.0 ở cả ba luồng. Với thuộc tính size, BM25 serving 0.666667, hybrid không PPR 0.734622, còn BM25 thô 0.984622; cần truy vết bước sắp thứ tự/mở rộng làm rơi kết quả đúng.
- 118 case có hard filter: **0 kết quả lọt bộ lọc**. 31 probe âm: **0 kết quả dương giả**.

## Giới hạn

- 243 nhãn dựa trên nguồn/tài liệu được kiểm tra bằng quy tắc; một số FAQ vẫn cần chuyên gia duyệt phạm vi đáp án.
- Đây là đo xếp hạng nguồn, không sinh hoặc chấm câu trả lời cuối, không xác nhận tính đúng của giá/tồn kho trực tiếp và không chứng minh chatbot thông minh hơn trong mọi hội thoại.
- PPR chỉ được chạy để đối chiếu offline, không thay đổi cấu hình serving.

## Tệp kết quả

- JSON từng case và tổng hợp: `backend/.local-evaluation/rag-audit-20261102-self-check/rag-self-check.json` (local, Git ignored).
- Script chạy một lần: `backend/.local-evaluation/rag-audit-20261102-self-check/run_saved_case_eval.py` (local, Git ignored).
