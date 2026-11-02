# 09 — Retrieval benchmark và hàng chờ duyệt câu trả lời

**Trạng thái:** Đánh giá kỹ thuật đã chạy; nhãn và đáp án người duyệt còn chờ.

## Nguồn và phạm vi

- Dùng local Docker PostgreSQL, 14 tenant schema.
- Sinh 53 câu hỏi tên sản phẩm từ 53 sản phẩm có mapping tới chunk tri thức đã sẵn sàng, ở shop 1 (4), shop 4 (25), shop 7 (24).
- 53/53 shop case hiện được xếp `unclassified`: chưa tìm được cấu hình ngành trong các khóa industry đã đăng ký. Vì vậy đây chưa phải tập kiểm thử đa ngành.
- Nhãn chunk được suy ra từ mapping SKU đã xác thực tenant; cần người hiểu nghiệp vụ xác nhận nguồn đó thật sự trả lời câu hỏi trước khi dùng làm quality gate.
- 53 embedding câu hỏi được gửi một lần theo lô Gemini `gemini-embedding-001`, dimension 768. Không gọi LLM để sinh câu trả lời.

## Kết quả tổng hợp (K=5)

| Phương pháp | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.9623 | 0.9245 | 0.9344 |
| BM25 + PPR trên nhánh lexical fallback | 0.9528 | 0.8648 | 0.8724 |
| Gemini vector-only | 0.7358 | 0.6698 | 0.6841 |
| Gemini + BM25 + RRF, bỏ PPR | 0.7925 | 0.7453 | 0.7576 |
| Gemini + BM25 + RRF + PPR (serving hiện tại) | 0.5660 | 0.4324 | 0.4640 |

Không có truy vấn nào bị vector-dimension fallback trong 53 case. Theo tập nhãn hiện tại, BM25 vượt luồng hybrid khoảng 0.4704 NDCG@5; PPR sau RRF làm NDCG thấp thêm khoảng 0.2936. Đây là dấu hiệu cần điều tra fusion/PPR, chưa đủ để đổi serving vì nhãn còn provisional và chỉ có ba shop.

## Quyết định

- Không bật thêm reranker/cross-encoder và không train/bật LightFM.
- Chưa thay đổi thứ tự serving chỉ dựa trên tập provisional này.
- Trước khi dùng làm quality gate: duyệt nhãn; bổ sung câu hỏi thuộc chính sách, SKU/thuộc tính bắt buộc, thiếu dữ liệu, dịch vụ và cho thuê; lưu cấu hình ngành đúng cho shop; chạy lại ablation theo từng shop.
- Đánh giá câu trả lời chưa chạy: file review có 53 dòng, trường đáp án và chấm điểm còn trống. Đây là hàng chờ cho người duyệt, không phải kết quả human eval.

## Tệp và dữ liệu

- Báo cáo máy, chỉ chứa metric và số lượng: `2026-11-01-09-rag-retrieval-evaluation.json`.
- Script tái tạo: `backend/scripts/evaluate_rag_retrieval.py`.
- Câu hỏi và CSV review chứa tên/SKU catalog shop, nằm trong `backend/.local-evaluation/` và được Git ignore để tránh đưa dữ liệu catalog riêng vào commit.
- Không commit hoặc push.
