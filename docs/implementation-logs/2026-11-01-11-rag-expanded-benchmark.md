# 11 — Mở rộng bộ case và chạy lại benchmark RAG

**Trạng thái:** Benchmark mở rộng chạy xong trên PostgreSQL local. Quality gate vẫn chặn thay đổi serving vì PPR làm giảm NDCG tổng thể và phần chấm câu trả lời bởi người duyệt còn thiếu.

## Bộ case

- Tăng từ **190 lên 255 case** (+65): thêm 53 câu hỏi chi tiết sản phẩm dựa trên chunk có mô tả và 12 FAQ có câu nguồn khớp.
- Có **214 case retrieval có nhãn nguồn**, gom thành **74 query family**; các câu cùng sản phẩm là biến thể liên quan, không phải 214 mẫu độc lập.
- 41 probe không có nhãn retrieval dương: 10 câu mơ hồ, 3 SKU không tồn tại, 14 truy vấn dịch vụ và 14 truy vấn cho thuê.
- Dữ liệu có bằng chứng ở shop 1 (mỹ phẩm, 19 case), shop 4 (phụ tùng xe máy, 92), shop 7 (phụ tùng xe máy, 103). 11 tenant còn lại chưa đủ dữ liệu để gán ngành.

## Kết quả mới, K=5

| Phương pháp | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.985981 | 0.935514 | 0.948402 |
| BM25 + PPR hiện tại trên nhánh lexical | 0.962617 | 0.912773 | 0.917557 |
| BM25 + PPR chỉ cạnh sản phẩm/SKU, blend 85/15 (offline) | 0.985981 | 0.935514 | 0.948402 |
| Gemini vector-only | 0.785047 | 0.757009 | 0.763226 |
| Gemini + BM25 + RRF, không PPR (fresh) | 0.873832 | 0.833723 | 0.843967 |
| Gemini + BM25 + RRF + PPR hiện tại (fresh) | 0.705607 | 0.631620 | 0.649147 |

Trên cùng 214 case, PPR làm hybrid giảm **0.168225 Recall**, **0.202103 MRR** và **0.194820 NDCG** so với hybrid không PPR. PPR làm giảm NDCG ở **62/214** case dense. Bộ cạnh hiện tại vẫn nối cùng sản phẩm/SKU, parent/tài liệu và chunk liền kề; log có chi tiết chunk được đẩy lên và cạnh nhìn thấy được.

### NDCG@5 theo nhóm

| Nhóm | Mẫu | BM25 | Hybrid không PPR | Hybrid + PPR |
| --- | ---: | ---: | ---: | ---: |
| Thông tin sản phẩm | 53 | 0.934410 | 0.757635 | 0.463986 |
| Chi tiết sản phẩm | 53 | 0.901502 | 0.785489 | 0.432258 |
| Tra SKU | 53 | 1.000000 | 1.000000 | 1.000000 |
| Thuộc tính kích thước | 24 | 0.984622 | 0.734622 | 0.734622 |
| Thuộc tính màu | 10 | 1.000000 | 1.000000 | 0.926186 |
| FAQ chính sách | 21 | 0.905891 | 0.866311 | 0.548749 |

### NDCG@5 theo shop

| Shop | Mẫu | BM25 | Hybrid không PPR | Hybrid + PPR |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 19 | 0.836463 | 0.836463 | 0.941726 |
| 4 | 92 | 1.000000 | 0.880435 | 0.677191 |
| 7 | 103 | 0.922963 | 0.812779 | 0.570127 |

Shop 1 có ít mẫu và PPR giúp trong mẫu hiện tại; shop 4 và shop 7 giảm rõ. Không dùng điểm gộp để bật PPR cho mọi shop.

## Đối chiếu bộ 53 câu cũ

Chạy lại đúng nhóm `product_info` cho kết quả hybrid không PPR **0.792453 / 0.745283 / 0.757635** và hybrid + PPR **0.566038 / 0.432390 / 0.463986** (Recall@5 / MRR / NDCG@5). Kết quả fresh trùng số đã lưu trước đó; vì vậy điểm thấp trước đây không phải chỉ do số mẫu ít.

## Kiểm tra và giới hạn

- 214/214 lượt dense ở chế độ `hybrid`; không có `retrieval_fallback_stage`.
- Lọc cứng trong audit: SKU 53/53, size 24/24, màu 10/10 gold hit; 0 chunk rò qua bộ lọc lexical. 31 probe SKU/dịch vụ/cho thuê không có kết quả BM25; các probe phủ định không được nhúng trong lần dense để tiết kiệm quota.
- Gemini embedding: `gemini-embedding-001`, 768 chiều; 125 chuỗi query duy nhất được nhúng cho 214 case ở 2 batch trong lượt thành công. Hai lượt thử ban đầu gặp quota miễn phí 429; lượt hoàn tất được giãn batch. Lần tái tạo báo cáo cuối đọc cache cục bộ, không gọi API thêm.
- Nhãn xác nhận chunk có liên quan chủ đề/sản phẩm, chưa chứng minh câu trả lời hoàn chỉnh đúng. CSV người duyệt còn cần xác nhận phạm vi đáp án; chưa đánh giá giá/tồn kho trực tiếp từ live catalog, cũng chưa có positive set dịch vụ/cho thuê.
- Không đổi cấu hình serving/PPR, không chạy migration, không commit và không push. Kết luận: **giữ quality gate ở trạng thái blocked**.

## Tệp kết quả

- Báo cáo máy: `2026-11-01-11-rag-expanded-benchmark.json`.
- Bộ case, kết quả từng câu, CSV người duyệt, nguồn nhãn và chẩn đoán PPR nằm trong `backend/.local-evaluation/rag-audit-20261101-dense-expanded-final/` (thư mục local bị Git ignore).
- Script tái tạo: `backend/scripts/audit_rag_retrieval.py`.
