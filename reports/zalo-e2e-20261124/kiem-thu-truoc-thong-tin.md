# Kiểm thử Zalo: mở đầu đến biểu mẫu thông tin

Ngày 24/11/2026, kiểm tra trực tiếp trong trình duyệt Codex, cuộc trò chuyện Bot Smart-Merchant-bot, shop 7, conversation 24.

## Phạm vi

Chỉ kiểm tra mở lời, danh mục, thông tin sản phẩm, báo giá, chọn/đổi mẫu, số lượng và lời đồng ý. Mỗi luồng dừng khi bot hỏi tên, điện thoại, email, địa chỉ và thanh toán. Không nhập thông tin cá nhân, không thanh toán trong lượt kiểm tra này.

## Các luồng đã quan sát thành công sau sửa

| Luồng | Các bước thực tế trên Zalo | Kết quả cuối |
|---|---|---|
| 1. Chọn bằng ngữ cảnh | “Chào shop, bên mình có gì vậy?” → hỏi giá/tồn Toner Nhỏ gọn → “Vậy cho em 2 chai loại này nhé” → “Ừ, làm đơn cho em đi shop” | 2 chai × 284.000 = 568.000 đồng; đến biểu mẫu, phiên 21 |
| 2. Hỏi thêm rồi đổi mẫu | Danh mục → “đặt giúp mình 1 Sữa rửa mặt dịu nhẹ – Tiêu chuẩn” → hỏi tác dụng → đổi số lượng thành 2 chai → “Không lấy sữa rửa mặt nữa, đổi sang 1 Toner cấp ẩm – Bộ đôi nhé” → “Vâng, đặt giúp mình nhé” | Giỏ thay bằng đúng 1 Toner Bộ đôi, 284.000 đồng; đến biểu mẫu, phiên 22 |
| 3. Làm rõ phiên bản và thiếu hàng | Danh mục → “Mình muốn mua toner” → bot đưa 4 mẫu → “Mình lấy bản tiêu chuẩn” → yêu cầu 100 chai → bot báo chỉ còn 9 → “Vậy mình lấy 2 chai thôi nha” → “Được, mình đồng ý mua” | 2 × 142.000 = 284.000 đồng; đến biểu mẫu, phiên 24 |
| 4. Không dấu và giỏ nhiều món | “shop ban nhung gi vay” → đặt không dấu 1 Sữa rửa mặt Tiêu chuẩn + 1 Toner Tiêu chuẩn → “Mua thêm 1 Toner cấp ẩm – Tiêu chuẩn nữa nha” → “Vâng nhé” | 261.000 đồng ban đầu; thêm 1 Toner thành 403.000 đồng; đến biểu mẫu, phiên 25 |
| 5. Chỉ hỏi giá, đổi ý và bắt đầu lại | “Hello shop của bạn có j” → hỏi tổng 2 Sữa rửa mặt Nhỏ gọn, nói rõ chưa đặt → bot trả 476.000 đồng và chưa tạo đơn → đặt 1 → từ chối trong câu dài → đặt 1 Sữa rửa mặt Nâng cao → “Ừ” | Yêu cầu cũ được bỏ, mẫu mới 357.000 đồng; đến biểu mẫu, phiên 27 |

## Lỗi tìm thấy và sửa

- Không nhận câu từ chối dài, cứ lặp báo giá: nhận ý chưa mua thay vì chỉ so khớp nguyên câu ngắn.
- Không nhận “làm đơn cho em”, “đặt giúp mình”, “Vâng nhé”, “Ừ”: mở rộng cách nhận yêu cầu và lời đồng ý tại bước đang chờ xác nhận.
- Không hiểu đơn vị “chai”, thêm/bớt hoặc thay số lượng: cập nhật số lượng và tính lại bằng giá trong danh mục; phân biệt mua thêm với thay số lượng.
- Câu hỏi tác dụng trong khi xem báo giá làm mất hoặc lặp giỏ: giữ giỏ, trả thông tin hiện có. Dữ liệu mô tả giả lập được nói rõ là chưa đủ xác nhận công dụng/cách dùng.
- “Mình muốn mua toner” đi thẳng tới thu thập thông tin: yêu cầu chọn phiên bản trước; danh sách lựa chọn lấy từ dữ liệu đang hoạt động của shop.
- Câu “lấy bản tiêu chuẩn” thiếu tên họ sản phẩm: chỉ chọn khi câu trả lời xác định duy nhất một mẫu trong danh sách vừa giới thiệu.
- Quay lại hỏi danh mục khi vừa đến biểu mẫu bị đọc thành tên người nhận và không phản hồi: nhận diện câu hỏi danh mục trước khi đọc các trường thông tin.
- Hỏi tổng tiền có kèm “chưa đặt hàng” rơi vào trả lời thiếu căn cứ: đưa về phép tính theo danh mục, không mở phiên mua hàng cho câu chỉ hỏi giá.

## Xác minh

- 196 kiểm thử liên quan qua: bộ hồi quy hội thoại mới, nhận diện sản phẩm, trả lời qua kênh, mở đơn mới và phần thu thập dữ liệu cũ. 3 ca OTP/corpus cũ không thuộc lượt chạy chọn lọc này; không tuyên bố toàn bộ test dự án đã chạy.
- Python compile và git diff --check cho các tệp liên quan qua.
- Backend và worker đã khởi động lại và ở trạng thái healthy.
- Đối chiếu CSDL: các phiên 21, 22, 24, 25, 27 có đúng tổng tiền nêu trên. Phiên cuối ở trường name, chưa nhập thông tin.
- Không phát sinh đơn bán mới kể từ 18:10 trong lượt kiểm tra này (đếm orders.created_at từ 11:10 UTC).
- Ảnh bằng chứng: precheckout-natural-final.jpg, quan sát trực tiếp đúng cuộc trò chuyện bot.

Các kết quả trên chứng minh những luồng đã thử; không phải cam kết hiểu mọi cách diễn đạt có thể có. Những thông tin chưa có trong danh mục vẫn cần shop bổ sung hoặc nhân viên kiểm tra.
