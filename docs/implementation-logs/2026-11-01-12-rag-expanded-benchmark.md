# 12 — Mở rộng bộ case RAG và đánh giá lại

**Trạng thái:** Chạy xong trên PostgreSQL local. Bộ test tăng thêm 29 câu hỏi có nhãn nguồn. Quality gate vẫn chặn PPR hiện tại vì điểm giảm rõ trên cùng tập đánh giá.

## Bộ case

- Tăng từ **255 lên 284 case** (+29), trong đó câu có nhãn retrieval tăng từ **214 lên 243**. Số `query_family` tăng từ **74 lên 103**.
- FAQ có nhãn nguồn tăng từ **21 lên 50**: thêm 7 câu cho shop 1 (mỹ phẩm) và 22 câu cho shop 7 (phụ tùng xe máy).
- Các ý mới gồm: thời gian giao nội thành; thứ tự/thời điểm sử dụng và thoa lại mỹ phẩm; độ phù hợp da; lựa chọn theo ngân sách/combo; cung cấp mã đơn khi cần hỗ trợ; phạm vi sửa chữa/lắp đặt và tuyên bố đại lý; xử lý ảnh mã mờ; chọn nhớt/phân biệt SKU; điều kiện mua kèm; chi phí chưa gồm; hết hàng và tiền cọc; giảm giá; bằng chứng đổi trả/bảo hành; dữ liệu thanh toán nhạy cảm; và cộng giá nhiều món.
- 41 probe không có nhãn retrieval dương được giữ nguyên: 10 câu thiếu/mơ hồ, 3 SKU không có, 14 truy vấn dịch vụ và 14 cho thuê.
- Bộ có 284 `case_id` duy nhất; cả 243 nhãn retrieval đều có chunk đích và cả 29 câu mới đều có nguồn tài liệu. Nhãn câu mới được đối chiếu tự động bằng cụm từ trong chunk, chưa phải chấm đáp án bởi chuyên gia.

## Kết quả mới, K=5

| Phương pháp | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.987654 | 0.931550 | 0.945888 |
| BM25 + PPR hiện tại | 0.934156 | 0.876543 | 0.884186 |
| BM25 + PPR cạnh thực thể chính xác, blend 85/15 (offline) | 0.987654 | 0.931550 | 0.945888 |
| Gemini vector-only | 0.777778 | 0.740878 | 0.749424 |
| Gemini + BM25 + RRF, không PPR (fresh) | 0.888889 | 0.839506 | 0.852113 |
| Gemini + BM25 + RRF + PPR hiện tại (fresh) | 0.679012 | 0.602195 | 0.620618 |

Trên cùng 243 câu, PPR hiện tại làm hybrid giảm **0.209877 Recall**, **0.237311 MRR** và **0.231495 NDCG** so với hybrid không PPR; NDCG giảm ở **81/243** case. BM25 vẫn cao hơn hybrid không PPR **0.093775 NDCG** trên bộ này.

Riêng 29 case mới: BM25 đạt **0.927338 NDCG**, hybrid không PPR **0.912221**, còn hybrid + PPR **0.410096**. Các case mới vì vậy làm lộ rõ việc PPR kéo các chunk chính sách đúng xuống thấp.

## NDCG@5 theo shop

| Shop | Mẫu retrieval | BM25 | Hybrid không PPR | Hybrid + PPR |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 26 | 0.866297 | 0.866297 | 0.943220 |
| 4 | 92 | 1.000000 | 0.880435 | 0.677191 |
| 7 | 125 | 0.922617 | 0.828318 | 0.511880 |

Shop 1 vẫn ít mẫu và là shop mỹ phẩm duy nhất có nguồn ngành; kết quả tốt hơn tại shop này chưa đủ căn cứ bật PPR riêng. Shop 4 và 7 giảm khi dùng PPR. Không gộp các shop để quyết định bật cấu hình chung.

## So với bộ 255 case trước

Trên 255 case cũ được đối chiếu theo `case_id` và giữ nguyên nhãn, metric tính lại trùng log #11: BM25 **0.948402**, hybrid không PPR **0.843967**, hybrid + PPR **0.649147 NDCG@5** trên 214 case đủ nhãn. Thay đổi điểm ở bảng 284 case đến từ 29 câu mới, không phải thay nhãn cũ.

## Kiểm tra và giới hạn

- 243/243 lượt dense chạy ở chế độ `hybrid`, không có `retrieval_fallback_stage`.
- Kiểm tra hard filter: SKU 53/53, size 24/24, màu 10/10 tìm thấy gold; **0 chunk lọt bộ lọc**.
- 31 probe phủ định (SKU không tồn tại, dịch vụ và cho thuê chưa có dữ liệu) có **0 false positive** trên nhánh lexical.
- Dùng `gemini-embedding-001`, vector 768 chiều. Có 154 query duy nhất: tái dùng 125 vector cache và nhúng 29 câu mới trong 1 batch Gemini.
- PostgreSQL local có 14 tenant schema; chỉ shop 1, 4, 7 có đủ dấu hiệu ngành/dữ liệu cho bộ hiện tại. 11 shop còn lại không được gán nhãn ngành.
- Tập này đo xếp hạng chunk theo nhãn nguồn, không xác nhận câu trả lời cuối của bot, tồn kho/giá trực tiếp, hay chất lượng tư vấn dịch vụ/cho thuê. Các policy FAQ mới cần người có chuyên môn duyệt phạm vi đáp án trước khi xem là gold chuẩn.
- **Quality gate: blocked.** Không đổi cấu hình serving. Chưa chạy migration, không commit và không push.

## Tệp kết quả

- Báo cáo máy: `2026-11-01-12-rag-expanded-benchmark.json`.
- Bộ case, từng kết quả, CSV người duyệt và chẩn đoán PPR nằm trong `backend/.local-evaluation/rag-audit-20261101-expanded-v2/` (thư mục bị Git ignore).
- Script tái tạo: `backend/scripts/audit_rag_retrieval.py`.
