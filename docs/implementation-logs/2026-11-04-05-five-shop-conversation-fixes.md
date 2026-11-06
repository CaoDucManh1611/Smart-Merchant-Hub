# Rà câu linh kiện xe và hội thoại 5 shop

Ngày: 2026-11-04  
Branch: `codex/rag-rfm-all-updates-20261104`

## Linh kiện xe: hoàn tất lượt sửa trước

- Câu 44: thêm tra cứu mã phụ tùng trong đúng shop để xác nhận mã có khớp tên Wave Alpha 110 hay chỉ sang sản phẩm/đời xe khác; phản hồi không lộ SKU nội bộ.
- Câu 49: chuẩn hóa lỗi gõ phổ biến `Wave Anfa`/`Wave Anpha` thành `Wave Alpha` trước tra cứu chính xác, lọc tương thích và xếp hạng.
- Rà lại các ca 21–50 đang có trong working tree: so sánh giá lốp, ngân sách, tổng tiền gương, gộp món, mã dở, hỏi giá công, tồn kho theo kênh, câu nối tiếp và yêu cầu nhiều món. Không thêm bản xử lý trùng cho các nhánh đã có; chi tiết liên quan nằm ở log 2026-11-04-01 đến -04.

## Rà báo cáo 5 shop

Đọc `C:\Users\Administrator\Downloads\SMH-bao-cao-hoi-thoai-5-shop.docx` và đối chiếu câu hỏi, phản hồi bot, đáp án kỳ vọng cùng nhận xét trong báo cáo. Thay đổi dùng chung:

- Câu giải thích khái niệm được tách khỏi tìm sản phẩm và trả lời trực tiếp, ngắn gọn; thêm glossary chung cho thuật ngữ thời trang, điện tử, nhà cửa và thực phẩm.
- Câu hỏi niacinamide/loại da và thành phần cho da nhạy cảm không bị đẩy sang liệt kê sản phẩm vì trùng từ `mặt`; câu tư vấn da không khẳng định thành phần hoặc mức phù hợp của sản phẩm shop khi catalog chưa ghi.
- Từ vựng lexical bổ sung cách gọi tương đương trong 5 ngành; tách `fit` khỏi `collar` để tránh kéo nhầm kết quả.
- Prompt trả lời yêu cầu giải thích tối đa hai câu ngắn, chỉ liệt kê nội dung được hỏi, và không tự suy ra cam kết của shop.

## Giới hạn nguồn

Glossary chỉ giải thích thuật ngữ phổ thông; không chứa giá, tồn kho, chính sách, hiệu quả sản phẩm, thông số thiết bị hay xác nhận an toàn/tương thích của shop. Các thông tin đó vẫn cần catalog hoặc tài liệu được shop duyệt. Không nạp bộ dữ liệu mẫu vào shop và không sửa nội dung DOCX.

## Phạm vi xác minh

- `git diff --check` được dùng để rà whitespace.
- Không chạy test theo yêu cầu hiện tại; không gửi câu hỏi Telegram, không khởi động lại server/worker, không chạy migration.
- Hành vi trực tiếp chỉ được xác nhận sau khi backend đang chạy nạp branch này và có lượt hỏi thật.
- Không commit hoặc push.
