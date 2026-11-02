# 10 — Kiểm tra nhãn, chẩn đoán PPR và mở rộng đánh giá RAG

**Trạng thái:** Đã kiểm tra hỗ trợ chủ đề của nhãn nguồn, chạy lại BM25 và hai biến thể PPR trên PostgreSQL local. Quality gate vẫn chặn thay đổi serving.

## Kiểm tra 53 nhãn nguồn

- Đối chiếu đủ 53 `expected_chunk_ids` với chunk ready được map trong đúng tenant. Cả 53 chunk đều có tên sản phẩm hoặc SKU chuẩn; không có nhãn sai về danh tính sản phẩm.
- Đây chỉ xác nhận chunk nói về sản phẩm được hỏi. CSV gốc có 53 dòng nhưng `answer_text`, điểm hỗ trợ nguồn và điểm chính xác đều trống, nên chưa có duyệt thủ công chất lượng câu trả lời hay xác nhận giá/tồn hiện thời.
- Sửa nhãn ngành trong CSV duyệt: shop 1 = mỹ phẩm/chăm sóc cá nhân; shop 4 và 7 = phụ tùng/phụ kiện xe máy. 11 shop còn lại không có đủ tài liệu hoặc catalog để suy ra ngành; không gán ngành đoán.

## Lỗi lọc thuộc tính tìm thấy và sửa

- 1/24 câu lọc kích thước ban đầu hụt sản phẩm bugi `CPR8EA-9`: bộ trích xuất xem mã kích thước là SKU chính xác, rồi loại chunk có SKU nội bộ đã chuẩn hóa khác.
- `_query_sku_identifiers` nay bỏ token trùng với giá trị thuộc tính cứng đã trích, nhưng vẫn giữ SKU khác nếu câu hỏi chứa cả SKU lẫn thuộc tính.
- Chạy lại: SKU 53/53, size 24/24, màu 10/10 gold hit; cả ba nhóm không có chunk rò qua bộ lọc.
- Kiểm tra focused: 2 test pass. `py_compile` và `git diff --check` pass.

## So sánh retrieval, K=5

### Cùng 53 câu `product_info`

| Phương pháp | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 mới chạy | 0.9623 | 0.9245 | 0.9344 |
| BM25 + PPR hiện tại | 0.9528 | 0.8648 | 0.8724 |
| BM25 + PPR chỉ nối cùng sản phẩm/SKU, blend 85/15 (offline) | 0.9623 | 0.9245 | 0.9344 |
| Gemini + BM25 + RRF, không PPR (kết quả đã lưu trước đó) | 0.7925 | 0.7453 | 0.7576 |
| Gemini + BM25 + RRF + PPR hiện tại (kết quả đã lưu trước đó) | 0.5660 | 0.4324 | 0.4640 |
| Hybrid đã lưu + PPR 85/15 chỉ trên top-5 đã lưu | 0.7925 | 0.7453 | 0.7576 |

So sánh hybrid là kết quả đã lưu trên cùng câu và nhãn, không phải lần chạy Gemini mới. Biến thể PPR giới hạn chỉ được chạy trên top-5 hybrid đã lưu; nó không thể khôi phục ứng viên đã bị mất trước đó.

### Bộ câu mở rộng

149 câu có nhãn retrieval (53 thông tin sản phẩm, 53 tra SKU, 24 thuộc tính kích thước, 10 màu, 9 chính sách):

| Phương pháp | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.9866 | 0.9597 | 0.9668 |
| BM25 + PPR hiện tại | 0.9832 | 0.9340 | 0.9403 |
| BM25 + PPR chỉ có cạnh sản phẩm/SKU, blend 85/15 (offline) | 0.9866 | 0.9597 | 0.9668 |

Phần không có đáp án được tách khỏi metric retrieval: 10 câu mơ hồ/thiếu ngữ cảnh, 3 SKU không tồn tại, 14 probe dịch vụ và 14 probe cho thuê. Không có false positive ở 31 probe SKU/dịch vụ/cho thuê. Bộ mở rộng gồm 190 case; không tạo nhãn dương giả cho shop trống.

### Theo shop, 53 câu sản phẩm gốc

| Shop | Ngành suy từ dữ liệu local | Mẫu | BM25 NDCG@5 | PPR hiện tại NDCG@5 | PPR chỉ cùng sản phẩm NDCG@5 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | Mỹ phẩm và chăm sóc cá nhân | 4 | 0.8155 | 0.6250 | 0.8155 |
| 4 | Phụ tùng xe máy | 25 | 1.0000 | 0.9705 | 1.0000 |
| 7 | Phụ tùng xe máy | 24 | 0.8859 | 0.8115 | 0.8859 |

## PPR đang làm rơi kết quả chính xác

- Đồ thị serving hiện kết nối cùng sản phẩm/SKU trọng số 3, cùng tài liệu/parent trọng số 2 và chunk liền kề trọng số 0.35.
- Trên 23/53 câu hybrid lịch sử bị giảm, cạnh lân cận và parent thường đẩy chunk gần nhau về chủ đề tổng quát lên trước chunk khớp sản phẩm.
- Ví dụ shop 4, câu hỏi bugi `CR7HSA`: chunk đúng 47626 từ hạng 1 xuống hạng 2; chunk 47644/47645 (gương trái/phải) được đẩy vào top-5 qua cạnh liền kề với 47643 (còi) và 47646 (nước làm mát). Cạnh phản ánh vị trí trong tài liệu, không phải quan hệ mua hàng hay độ khớp SKU.
- Ví dụ shop 7, câu hỏi lọc gió Vision 110: chunk đúng 33 từ BM25 hạng 1 xuống PPR hạng 10. PPR đẩy chunk 23, 21, 25, 26 lên top-5 qua `same_document_parent`/`adjacent_chunk`; nội dung là hướng dẫn tương thích xe và nhóm hàng khác, không phải chunk sản phẩm Vision cần trả lời.
- Biến thể chỉ dùng cạnh sản phẩm/SKU không làm giảm điểm ở tập hiện tại. Đây là phép thử offline trên tập ứng viên hiện có, chưa thay đổi PPR serving.

## Giới hạn và quyết định

- Không có `GEMINI_API_KEY` hoặc cache embedding trong runtime hiện tại; không chạy lại nhánh Gemini/vector/RRF. Báo cáo mới dùng BM25 chạy trực tiếp trên PostgreSQL và đối chiếu hybrid từ snapshot trước.
- Nguồn hỗ trợ mới xác nhận danh tính sản phẩm; nội dung trả lời vẫn chờ người duyệt. Giá/tồn/khả dụng ở thời điểm trả lời và chất lượng trả lời cuối chưa được đo.
- Không có dữ liệu dương cho dịch vụ/cho thuê. 11/14 shop chưa phân loại ngành; suy luận ngành trong đánh giá không được ghi vào cấu hình shop.
- Quality gate giữ trạng thái chặn. Không đổi cấu hình PPR/serving, không migration, không commit và không push.

## Tệp kết quả

- Báo cáo máy: `2026-11-01-10-rag-label-ppr-expansion.json`.
- Script tái tạo: `backend/scripts/audit_rag_retrieval.py`.
- CSV nguồn đã đối chiếu và CSV mở rộng để người duyệt xem nằm trong `backend/.local-evaluation/rag-audit-20261101-final/`; thư mục bị Git ignore vì chứa nội dung catalog riêng của shop.
