# Kiểm tra hội thoại danh mục, giá toner và tiếng Anh — 25/11/2026

Đã phát lại đúng 11 câu hỏi theo thứ tự người dùng cung cấp, qua graph hiện tại, trên bản chụp 24 sản phẩm của shop 8 trong SQLite riêng. Hai câu hỏi giá toner và câu tìm sản phẩm bằng tiếng Anh đã được sửa. Các câu chào, hỏi danh mục và yêu cầu viết code đã có phản hồi phù hợp trong lần kiểm tra trước sửa của đợt này.

Kết quả phát lại sau sửa dưới đây tóm tắt phần danh mục; các câu trả lời còn lại được chép từ kết quả thực tế. Transcript JSON lưu đầy đủ từng phản hồi và trạng thái.

| Lượt | Câu hỏi nguyên văn | Phản hồi sau sửa | Đánh giá |
| --- | --- | --- | --- |
| 1 | xin chào | Chào bạn! Mình có thể giúp bạn tìm sản phẩm hoặc tư vấn đơn hàng hôm nay nhé. | Đạt |
| 2 | bạn đang có sản phẩm gì | Liệt kê 12 nhóm hàng đang bán, rồi hỏi nhóm khách quan tâm để giới thiệu sản phẩm cụ thể. | Đạt |
| 3 | bạn đang có nhóm sản phẩm nào | Liệt kê các danh mục thực tế của shop. | Đạt |
| 4 | bạn đang có nhóm sản phẩm nào | Tiếp tục liệt kê danh mục; không hỏi ngược lại khách muốn xem nhóm nào khi chưa đưa danh sách. | Đạt |
| 5 | bạn đang có sản phẩm nào | Liệt kê 12 nhóm hàng đang bán và mời chọn nhóm. | Đạt |
| 6 | shop đang có sản phẩm nào | Liệt kê 12 nhóm hàng đang bán và mời chọn nhóm. | Đạt |
| 7 | tôi muốn mua 2 toner dưỡng ẩm 200ml giá | Dạ, Toner dưỡng ẩm 200ml giá 159.000 đồng/sản phẩm; 2 sản phẩm là 318.000 đồng. Tồn hiện tại là 25 sản phẩm. | Đạt |
| 8 | tôi muốn mua 2 toner dưỡng ẩm 200ml giá sẽ trả bao nhiêu | Dạ, Toner dưỡng ẩm 200ml giá 159.000 đồng/sản phẩm; tiền hàng cho 2 sản phẩm là 318.000 đồng. Tồn hiện tại là 25 sản phẩm. | Đạt |
| 9 | code python cho tôi bài code thiếu nhi đi | Mình là trợ lý của shop, hỗ trợ thông tin sản phẩm, giá, dịch vụ và đơn hàng. Bạn cần tìm hiểu điều gì về shop ạ? | Đạt: chuyển về phạm vi shop |
| 10 | hello | Hi! I can help you find a product or answer questions about an order today. | Đạt |
| 11 | please help me find a product | What type of product are you looking for, what do you need it for, and what's your budget? | Đạt |

Ở lượt 2–6, phản hồi tổng quan nhóm hàng đã hoạt động trên bản đang có trước đợt sửa này. Danh sách có 12 nhóm, tương ứng 24 sản phẩm/phiên bản trong dữ liệu kiểm tra; không nhầm 12 nhóm với 24 sản phẩm.

Trước sửa, lượt 7 đi qua nhánh mô hình và gặp HTTP 429 từ Groq; metadata phản hồi có yêu cầu chuyển nhân viên. Harness dừng gọi provider sau lỗi 429, vì vậy lượt 8 và 11 trước sửa bị chặn bởi circuit của harness, không phải hai lần HTTP 429 riêng biệt. Bản ghi trước sửa là kiểm tra chẩn đoán, không phải kết quả chấp nhận hành vi.

Đã sửa nhận diện câu hỏi báo giá có từ “mua”, hỗ trợ số lượng đứng sát tên sản phẩm/SKU như “2 toner dưỡng ẩm 200ml”, và bỏ phần ngữ pháp “sẽ/phải trả bao nhiêu” khi xác định sản phẩm. Giá lấy từ TON-200: 159.000 × 2 = 318.000 đồng tiền hàng; không tự thêm phí giao hàng. Các câu xác nhận chốt đơn vẫn đi theo luồng mua hàng hiện có. Kiểm tra hồi quy cũng bảo đảm mặt hàng lạ như “trà” không kế thừa toner từ lịch sử.

Yêu cầu tìm sản phẩm chung bằng tiếng Anh được hỏi thêm loại hàng, nhu cầu và ngân sách bằng tiếng Anh. Các câu có tên sản phẩm, ngân sách, nhu cầu cụ thể hoặc tham chiếu lịch sử tiếp tục dùng bộ xử lý hiện có.

Trong lần phát lại sau sửa, cả 11 lượt dùng tổng cộng 0 lần gọi provider. Mỗi lượt có 0 ticket, 0 phiên thu thập thông tin đặt hàng và 0 đơn; bot giữ chế độ auto, tồn kho và lượng giữ chỗ không đổi. Đây là kiểm tra trên dữ liệu cô lập, không gửi tin nhắn hay tạo giao dịch cho khách thật.

Nhãn dán sau lời chào chỉ được chèn thành message metadata `[sticker]`, `media_type=sticker`, không có URL và không chạy graph riêng cho media. Chưa kiểm tra connector, tải ảnh hay pipeline xử lý nhãn dán.

Đã thêm 37 ca hồi quy. Trước sửa, 4 trong 36 ca ban đầu tái hiện lỗi; sau sửa, nhóm tập trung đạt 103/103. Bộ kiểm tra kết hợp với các bản sửa trước đạt **357/357 trong 53,28 giây**. Phạm vi gồm danh mục, phạm vi shop, giá/số lượng, SKU/dung tích, ngữ cảnh, pending checkout và API đơn hàng; không phải toàn bộ backend hay bộ PostgreSQL. Hai file ứng dụng và file test mới biên dịch Python thành công; `git diff --check` đạt. Review độc lập không còn lỗi chặn.

Đã restart backend và worker. Cả hai container ở trạng thái healthy, failing streak 0. Endpoint `/health` trả `status=ok`, `loaded_revision=source_revision=19069fb698fd9a8a`.

Các file ứng dụng sửa trong đợt này: `backend/app/services/catalog_dialogue.py`, `backend/app/services/auto_reply_service.py`. File kiểm tra mới: `backend/tests/test_catalog_natural_requests_regression.py`.

Chứng cứ:

- [Transcript trước sửa](/C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub/reports/rag-danh-muc-toner-before-20261125.json)
- [Transcript sau sửa](/C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub/reports/rag-danh-muc-toner-after-20261125.json) — SHA-256 `6acd0b58bb999b2e9d68c0df22eaee817653efe683af3ab078e5387118fa161d`
- [Kết quả 357 ca kiểm tra](/C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub/reports/rag-danh-muc-toner-regressions-20261125.xml)
