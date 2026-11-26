# Kiểm tra và sửa đúng chuỗi câu hỏi giá — 25/11/2026

Đoạn hội thoại được gửi chưa đạt: hỏi kem trả sang sữa/gel rửa mặt; hỏi 100ml vẫn đưa bản 150ml; hỏi hai chai không được tính tổng giá.

Đã chạy nguyên văn 6 câu theo đúng thứ tự qua conversation graph, dùng bản sao 24 sản phẩm đang mở bán của shop và SQLite tách biệt. Hai lượt đầu gọi dịch vụ LLM thật; bốn lượt hỏi giá lấy dữ liệu trực tiếp từ danh mục. Lượt chạy sau sửa không gặp lỗi nhà cung cấp. Không tạo đơn hàng hoặc phiên thu thập thông tin ở cả sáu lượt.

## Kết quả sau sửa

| Lượt | Câu hỏi nguyên văn | Kết quả thực tế |
|---|---|---|
| 1 | Cho tôi thông tin các sản phẩm hiện c9s | Liệt kê đủ 24 sản phẩm đang mở bán. |
| 2 | Có | Lặp lại danh sách 24 sản phẩm. Nội dung đúng danh mục, nhưng phản hồi này vẫn còn lặp. |
| 3 | Kem giá bao nhiêu | Liệt kê đúng bốn bản kem dưỡng ẩm dạng cream/gel 30g và 50g; không đưa sữa hoặc gel rửa mặt. |
| 4 | Giá 2 chai 100ml là bao nhiêu | Hỏi rõ sản phẩm vì các loại kem vừa xem không có quy cách 100ml; không tự chuyển sang nhóm khác. |
| 5 | Giá 2 chai 100ml gel rửa mặt không hạt | Gel rửa mặt không hạt 100ml: 99.000 đồng/sản phẩm; 2 sản phẩm là 198.000 đồng. |
| 6 | Tôi đang muốn biết giá của 2 chai 100ml gel rửa mặt không hạt | Gel rửa mặt không hạt 100ml: 99.000 đồng/sản phẩm; 2 sản phẩm là 198.000 đồng. |

## Nguyên văn phản hồi sau sửa

### Lượt 1: Cho tôi thông tin các sản phẩm hiện c9s

Trạng thái: catalog_dialogue.

> Shop hiện có 24 sản phẩm đang mở bán:
> • Dầu gội làm sạch dịu nhẹ 250ml
> • Dầu gội làm sạch dịu nhẹ 500ml
> • Dầu tẩy trang 100ml
> • Dầu tẩy trang 200ml
> • Gel rửa mặt không hạt 100ml
> • Gel rửa mặt không hạt 200ml
> • Kem dưỡng ẩm dạng cream 30g
> • Kem dưỡng ẩm dạng cream 50g
> • Kem dưỡng ẩm dạng gel 30g
> • Kem dưỡng ẩm dạng gel 50g
> • Mặt nạ đất sét 100g
> • Mặt nạ đất sét 30g
> • Nước tẩy trang 200ml
> • Nước tẩy trang 400ml
> • Serum dưỡng ẩm 15ml
> • Serum dưỡng ẩm 30ml
> • Son dưỡng môi không màu 4g
> • Son dưỡng môi không màu 8g
> • Sữa rửa mặt tạo bọt dịu nhẹ 100ml
> • Sữa rửa mặt tạo bọt dịu nhẹ 150ml
> • Sữa tắm dưỡng ẩm 250ml
> • Sữa tắm dưỡng ẩm 500ml
> • Toner dưỡng ẩm 100ml
> • Toner dưỡng ẩm 200ml

### Lượt 2: Có

Trạng thái: catalog_dialogue.

> Shop hiện có 24 sản phẩm đang mở bán:
> • Dầu gội làm sạch dịu nhẹ 250ml
> • Dầu gội làm sạch dịu nhẹ 500ml
> • Dầu tẩy trang 100ml
> • Dầu tẩy trang 200ml
> • Gel rửa mặt không hạt 100ml
> • Gel rửa mặt không hạt 200ml
> • Kem dưỡng ẩm dạng cream 30g
> • Kem dưỡng ẩm dạng cream 50g
> • Kem dưỡng ẩm dạng gel 30g
> • Kem dưỡng ẩm dạng gel 50g
> • Mặt nạ đất sét 100g
> • Mặt nạ đất sét 30g
> • Nước tẩy trang 200ml
> • Nước tẩy trang 400ml
> • Serum dưỡng ẩm 15ml
> • Serum dưỡng ẩm 30ml
> • Son dưỡng môi không màu 4g
> • Son dưỡng môi không màu 8g
> • Sữa rửa mặt tạo bọt dịu nhẹ 100ml
> • Sữa rửa mặt tạo bọt dịu nhẹ 150ml
> • Sữa tắm dưỡng ẩm 250ml
> • Sữa tắm dưỡng ẩm 500ml
> • Toner dưỡng ẩm 100ml
> • Toner dưỡng ẩm 200ml

### Lượt 3: Kem giá bao nhiêu

Trạng thái: catalog_dialogue.

> Shop có các phiên bản sau; bạn muốn xem chi tiết bản nào ạ?
> • Kem dưỡng ẩm dạng gel 30g — 119.000 đồng
> • Kem dưỡng ẩm dạng gel 50g — 179.000 đồng
> • Kem dưỡng ẩm dạng cream 30g — 129.000 đồng
> • Kem dưỡng ẩm dạng cream 50g — 199.000 đồng

### Lượt 4: Giá 2 chai 100ml là bao nhiêu

Trạng thái: dialogue_clarify.

> Các sản phẩm vừa xem chưa có quy cách bạn nêu. Bạn đang hỏi sản phẩm nào ạ?

### Lượt 5: Giá 2 chai 100ml gel rửa mặt không hạt

Trạng thái: catalog_dialogue.

> Dạ, Gel rửa mặt không hạt 100ml giá 99.000 đồng/sản phẩm; 2 sản phẩm là 198.000 đồng.

### Lượt 6: Tôi đang muốn biết giá của 2 chai 100ml gel rửa mặt không hạt

Trạng thái: catalog_dialogue.

> Dạ, Gel rửa mặt không hạt 100ml giá 99.000 đồng/sản phẩm; 2 sản phẩm là 198.000 đồng.

## Chạy đối chiếu trước sửa

Lượt chạy trước sửa trả danh sách ở hai câu đầu; bốn câu hỏi giá rơi vào trạng thái không xử lý được. Hai phép kiểm tra nhà cung cấp riêng xác nhận RateLimitError, HTTP 429, mã rate_limit_exceeded. Đây là lỗi giới hạn gọi dịch vụ; không coi lượt chạy đó là bằng chứng LLM đã chọn nhầm nhóm kem. Các lỗi chọn nhóm, lọc dung tích và mất số lượng được tái hiện độc lập bằng kiểm thử hồi quy trước khi sửa.

| Lượt | Câu hỏi | Trạng thái trước sửa |
|---|---|---|
| 1 | Cho tôi thông tin các sản phẩm hiện c9s | catalog_dialogue |
| 2 | Có | catalog_dialogue |
| 3 | Kem giá bao nhiêu | dialogue_understanding_unavailable |
| 4 | Giá 2 chai 100ml là bao nhiêu | dialogue_understanding_unavailable |
| 5 | Giá 2 chai 100ml gel rửa mặt không hạt | dialogue_understanding_unavailable |
| 6 | Tôi đang muốn biết giá của 2 chai 100ml gel rửa mặt không hạt | dialogue_understanding_unavailable |

## Các thay đổi và kiểm tra

- Câu hỏi giá xác định được từ danh mục đi theo nhánh trực tiếp; câu mơ hồ giữ phạm vi sản phẩm vừa xem và hỏi lại.
- Lọc dung tích trước khi hiển thị các lựa chọn, kể cả khi có nhiều nhóm liên quan.
- Giữ câu hỏi và số lượng khi tạo câu trả lời chi tiết; giá hai sản phẩm dùng đơn giá nhân hai dù khách không dùng từ “tổng”.
- Không dùng số trong SKU, tên như SPF 50 hoặc dung tích làm số lượng; hỏi lại khi số lượng âm, lẻ hoặc có nhiều khả năng.
- Tên sản phẩm hiện tại quyết định nhóm hàng; “kem dạng gel” không trở thành gel rửa mặt. Chính sách, khuyến mãi và ngân sách tiếp tục dùng luồng của chúng.
- Bộ kiểm thử chọn theo phạm vi: 275 passed, 44,92 giây; gồm 214 kiểm thử liên quan đã có và 61 trường hợp giá mới. Replay LLM thật: 1 passed, 16,78 giây.
- Python compile và git diff --check đạt. Đây không phải kết quả của toàn bộ backend; bộ legacy rộng hơn còn có các lỗi đã được ghi nhận trước đợt sửa này.

## Runtime sau nạp bản sửa

Đã restart backend và worker trong project smart-merchant-hub-runtime. Cả hai running/healthy, failing streak 0. Endpoint /health trả status=ok, loaded_revision=source_revision=51205587fcdcb09d. Không khởi động connector.

## Bằng chứng

- Trước sửa: rag-gia-hoi-thoai-before-20261125.json.
- Sau sửa: rag-gia-hoi-thoai-after-20261125.json.
- JUnit: rag-gia-regressions-20261125.xml.
