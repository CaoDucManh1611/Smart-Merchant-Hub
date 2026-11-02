# 15 — Pilot chấm chất lượng câu trả lời RAG

**Trạng thái:** Chạy xong 25 cặp; chưa có kết luận chất lượng cuối cùng vì cần người duyệt nội dung.

## Phạm vi

- Cùng 25 truy vấn trên ba shop dữ liệu thử nghiệm, gồm 10 nhóm: SKU, thông tin/chi tiết sản phẩm, FAQ chính sách, thuộc tính size/màu, câu mơ hồ/thiếu ngữ cảnh, SKU không tồn tại, và truy vấn thuộc dịch vụ/cho thuê chưa có dữ liệu.
- So sánh thứ tự nguồn của **BM25 qua `retrieve()` hiện tại** với **Gemini vector + BM25 + RRF, không PPR**. Cả hai dùng cùng nguồn dữ liệu, câu hỏi và chuỗi sinh đáp án.
- Bộ sinh đáp án cấu hình Groq `openai/gpt-oss-20b` làm route chính và Gemini làm fallback (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.6-flash`). Không gửi tin nhắn ra connector.
- Khi dựng pilot, đã tạo embedding Gemini cho 7 câu còn thiếu trong một batch; retrieval không báo fallback.

## Kết quả máy kiểm tra

| Luồng | Câu có đáp án sinh | Qua cổng trích dẫn | Được trả lời cho khách | Chuyển hỗ trợ | Lỗi sinh |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 serving | 25/25 | 5/25 (20%) | 5/25 | 20/25 | 0 |
| Hybrid không PPR | 24/25 | 6/25 (24%) | 6/25 | 18/25 | 1 |

Cổng trích dẫn chỉ kiểm tra dạng trích nguồn/hỗ trợ nguồn theo luật hiện tại; **không xác nhận ngữ nghĩa của mọi khẳng định**. Bộ câu hỏi không có `must_include`/`must_not_include` nên kiểm tra thuật ngữ bắt buộc không chạy (0 điều khoản); không được diễn giải chỉ số literal evidence là điểm độ đúng.

## Giới hạn và kết luận

Groq ghi nhận 3 lỗi giới hạn tốc độ ở mỗi lượt; cấu hình cho phép rơi sang Gemini. Hệ thống không lưu provider/model đã trả lời theo từng câu, vì vậy đây là so sánh trên **chuỗi định tuyến LLM**, không phải so sánh cô lập một model cố định. Hai nhánh cũng chạy tuần tự, không xen kẽ từng cặp. Chênh lệch 5 so với 6 lượt qua cổng trích dẫn quá nhỏ để chọn luồng. Một lỗi sinh ở hybrid và tỷ lệ chuyển hỗ trợ cao đều cần người duyệt các câu A/B.

**Kết luận hiện tại:** chưa thể nói RAG nào thông minh hơn. Cần chấm mù tính đúng, bằng chứng nguồn, độ đầy đủ, quyết định hỏi thêm/chuyển nhân viên và lỗi nghiêm trọng; sau đó mới mở khóa A/B và tổng hợp theo nhóm câu/shop. Giữ baseline hiện tại cho tới khi có kết quả duyệt và đánh giá mở rộng.

## Tệp kết quả

- Bảng chấm mù 25 cặp: `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/answer-review-blinded.csv`
- Hướng dẫn chấm: `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/README-review.md`
- Bản đồ A/B (chỉ mở sau khi chấm): `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/answer-review-key.json`
- Số liệu máy: `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/answer-pilot-summary.json`
- JSON từng câu, log gọi model và đầu vào retrieval nằm cùng thư mục `answer-pilot/` (local, Git ignored).
- Đánh giá retrieval trên 243 case đủ nhãn: [log 14](2026-11-02-14-rag-self-check.md).

## Bước tiếp theo

1. Chấm mù A/B trong CSV, ưu tiên các case có `citation_gate=FAIL`, lỗi sinh, hoặc lựa chọn chuyển hỗ trợ.
2. Sau khi chấm mới mở khóa A/B, tổng hợp tỷ lệ thắng/hòa, điểm paired theo nhóm câu và shop, cùng lỗi nghiêm trọng.
3. Bổ sung gold checks có điều khoản bắt buộc/không được nói; ghi provider/model thực tế cho từng đáp án; xen kẽ ngẫu nhiên BM25/hybrid khi chạy lại.
4. Mở rộng bộ câu hỏi đa ngành rồi chạy lại trước khi thay mặc định serving.
