# 16 — Chấm sơ bộ chất lượng câu trả lời RAG bằng AI

**Trạng thái:** Đã chấm mù 25 cặp rồi mới mở khóa A/B. Đây là đánh giá sơ bộ của AI, chưa phải nhãn chuẩn độc lập hay quality gate để bật cấu hình.

## Kết quả theo luồng

| Luồng | Ưu tiên theo cặp | Đúng TB / 5 | Có nguồn hỗ trợ TB / 5 | Đầy đủ TB / 5 | Hữu ích ở câu khách nhận TB / 5 | Bản nháp có lỗi nghiêm trọng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 serving | 6 thắng, 14 hòa, 5 thua | 3,44 | 4,48 | 3,04 | 2,88 | 1 |
| Hybrid không PPR | 5 thắng, 14 hòa, 6 thua | 3,48 | 4,68 | 2,96 | 2,96 | 0 |

Không có phương pháp thắng rõ. Điểm trung bình chỉ chênh rất ít và do cùng một AI đọc/chấm bộ thử nghiệm tổng hợp 25 case, không phải đánh giá độc lập. Không dùng điểm này để đổi cấu hình serving.

## Đối chiếu cổng tự động

- BM25: 5/25 đáp án qua cổng trích dẫn; 5 câu được trả lời, 20 chuyển hỗ trợ.
- Hybrid: 6/25 qua cổng; 6 được trả lời, 18 chuyển hỗ trợ, 1 lỗi sinh.
- Có 3 lỗi giới hạn tốc độ Groq trong mỗi lượt; chuỗi fallback Gemini được phép chạy nhưng model thực tế chưa được ghi riêng theo đáp án. Kết quả là so sánh chuỗi định tuyến, không cô lập một model.

## Lỗi nổi bật cần sửa trước khi kết luận

1. **Truy xuất bỏ sót nguồn đúng ở cả hai nhánh.** Các case sản phẩm xe máy và lọc kích thước có gold chunk trong dữ liệu nhưng một số lượt trả về rỗng. Câu trả lời từ chối là an toàn, nhưng RAG không hoàn thành truy vấn.
2. **Thuộc tính catalog không tới được đáp án.** Case lốp màu đen của shop 7 có màu trong catalog chuẩn, nhưng kết quả chỉ có chunk kiến thức không chứa màu/tồn. Cần nối kết quả catalog chuẩn vào nhánh lọc/đáp ứng thuộc tính.
3. **Cổng trích dẫn làm mất câu đúng.** Có câu trả lời chính sách giao hàng đúng nội dung nhưng vẫn bị thay bằng thông báo chung; một số đáp án trỏ sai chỉ số nguồn (ví dụ nguồn 4 trong khi chỉ có 3 chunk). Cần kiểm tra mapping nguồn hiển thị với danh sách chunk thực sự đưa vào prompt.
4. **Một bản nháp BM25 bịa thông số nhớt** (chống oxy hóa, giảm ma sát, bảo vệ động cơ và cách bảo quản) khi không có chunk hỗ trợ. Cổng đã chặn bản nháp; khách chỉ nhận thông báo chuyển hỗ trợ. Guard đang bảo vệ khách, nhưng generator vẫn cần kiểm soát tốt hơn.
5. **Câu hỏi mơ hồ cần hỏi thêm.** Câu hỏi về da nên hỏi loại da/nhu cầu/ngân sách trước khi liệt kê sản phẩm. Câu hỏi phụ tùng cần hỏi hãng, dòng xe, đời/phiên bản và mã/ảnh phụ tùng cũ.
6. **Giá/tồn phải xác minh từ CRM hiện hành.** Một số đáp án đọc giá/tồn từ đoạn văn tĩnh. Không xác nhận được các giá trị này là trạng thái trực tiếp tại thời điểm trả lời.

## Tệp

- Bảng chấm mù gốc: `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/answer-review-blinded.csv`
- Bảng chấm sơ bộ đã điền và mở khóa: `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/answer-review-ai-unblinded.csv`
- Tóm tắt JSON: `backend/.local-evaluation/rag-audit-20261102-self-check/answer-pilot/answer-review-ai-unblinded-summary.json`
- Chi tiết từng cặp và lời giải thích: cùng thư mục `answer-pilot/answer-review-ai-preliminary.csv`.

## Kết luận hành động

Chưa chọn BM25 hay hybrid làm phương pháp thông minh hơn. Ưu tiên sửa truy xuất SKU/thuộc tính và nối catalog chuẩn; sửa ánh xạ citation; sau đó chạy lại với provider/model được khóa và ghi theo từng case, chia ngẫu nhiên/xen kẽ hai nhánh, rồi nhờ người duyệt một mẫu đại diện trước khi quyết định.

Không thay đổi serving, không chạy test suite, không commit/push.
