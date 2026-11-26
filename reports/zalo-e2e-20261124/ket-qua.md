# Kiểm thử mua hàng qua Zalo — 24/11/2026

## Kết quả thực tế

Thao tác trên Zalo Web trong trình duyệt Codex, đúng hội thoại Bot Smart-Merchant-bot; đối chiếu giao diện SMH và dữ liệu của shop 7, hội thoại 24. Không tạo đơn bằng SQL/API để thay cho thao tác của khách. Không thực hiện chuyển tiền.

| Đơn | Sản phẩm | Số lượng | Tổng | Cách nhập thông tin |
|---|---|---:|---:|---|
| CHAT-12 | Toner cấp ẩm – Tiêu chuẩn | 2 | 284.000 đồng | Một mẫu có nhãn |
| CHAT-13 | Son dưỡng môi – Tiêu chuẩn | 1 | 280.000 đồng | Gửi riêng tên, điện thoại, email, địa chỉ, chuyển khoản |
| CHAT-14 | Sữa rửa mặt dịu nhẹ – Tiêu chuẩn | 1 | 119.000 đồng | Một khối 5 dòng không có nhãn |

Cả ba đơn có đúng số điện thoại và địa chỉ được chỉ định. Địa chỉ được lưu là E13/15/1N. Mỗi đơn có một dòng sản phẩm, không tạo trùng đơn khi gửi lại thông tin/QR. Ba tin QR lưu trạng thái sent, media_type=image và có mã tin nhắn từ Zalo. Ảnh QR đã quan sát trực tiếp trong hội thoại phía khách.

CHAT-12 và CHAT-13 gặp lỗi trong quá trình chạy, được sửa và gửi lại tin thất bại với khóa chống trùng cũ. CHAT-14 chạy toàn bộ tự động qua worker sau khi sửa volume, kể cả khi Zalo tự đính kèm danh thiếp.

Khách xác nhận CHAT-13 và CHAT-14 bằng tin “Xác nhận”, bot trả thông báo chờ nhân viên phụ trách. Không coi lời xác nhận đó là chứng cứ chuyển tiền. Giao diện đồng thời ghi nhận CHAT-12 đang đóng gói, CHAT-13 đang giao, CHAT-14 chờ nhân viên xác nhận; các thao tác quản trị ghi nhận thanh toán/đổi trạng thái không do phiên mua thử này thực hiện.

## Kịch bản và kiểm tra

- Hỏi “Shop kinh doanh những mặt hàng gì vậy?” và yêu cầu tất cả sản phẩm: nhận danh sách 39 mục đang bán.
- Hỏi chi tiết, giá và tồn kho. Với mô tả giả lập không có công dụng/cách dùng được xác nhận, bot nói rõ giới hạn thay vì bịa nội dung.
- Dùng các câu mua khác nhau: “Mình lấy 2 chai…”, “Mình mua 1… tạo đơn mới riêng…”, “Chốt cho mình 1… làm đơn mới…”.
- Nhập thông tin bằng ba cách trong bảng; kiểm tra số lượng, thành tiền, phương thức chuyển khoản và mã tham chiếu QR từng đơn.
- Quan sát thông báo xác nhận, đóng gói, đang giao của CHAT-13 xuất hiện trên Zalo.
- Kiểm tra riêng CHAT-14: 0/119.000 đồng trước đối soát; gửi QR không tự ghi nhận đã thanh toán.

## Lỗi phát hiện và sửa

1. Danh thiếp Zalo không có nội dung làm mất lượt trả lời của tin văn bản trước: điều kiện chọn tin mới nhất giờ chỉ xét tin có nội dung hoặc ảnh mà chatbot xử lý được.
2. Worker lưu ảnh QR vào filesystem riêng, URL lại do backend phục vụ: thêm bind mount `./backend/uploads:/app/uploads` cho worker, tạo lại worker và kiểm tra mount thực tế. QR được xuất RGB JPEG chuẩn; thử nghiệm cho thấy riêng đổi định dạng chưa giải quyết được lỗi, volume dùng chung là sửa chữa quyết định.
3. Trạng thái chờ xác nhận cũ giữ khách trong CHAT-12 dù khách muốn đơn mới: giải phóng bước xác nhận khi đơn đã rời nháp hoặc khách yêu cầu rõ một đơn riêng; giữ nguyên đơn cũ.
4. Các dòng email/địa chỉ/thanh toán trong một lượt gom tin bị bỏ sót sau giá trị đầu tiên: lần lượt phân tích các trường còn thiếu.
5. Địa chỉ diễn đạt “Địa chỉ của mình là … nhé”: chuẩn hóa bỏ phần dẫn câu. Sửa chính xác địa chỉ của CHAT-13 đã tạo trong lượt lỗi, không sửa các đơn khác.
6. “Loại này giá thế nào” bị nhận nhầm là hỏi danh mục dù đã nêu tên sản phẩm: thu hẹp điều kiện hỏi chưa rõ sản phẩm; kiểm tra lại cùng câu trên Zalo thành công.
7. Câu hỏi nhiều ý bị trả riêng giá/tồn mà bỏ qua công dụng: trả lời rõ phần mô tả chưa được xác nhận trong danh mục.

## Kiểm chứng

- 118 kiểm thử đạt trong ba bộ: test_checkout_new_order.py, test_conversation_turn_service.py, test_auto_reply_channels.py.
- Các hồi quy bao gồm tin phụ danh thiếp, đơn cũ không giữ checkout mới, nhập nhiều trường không nhãn, địa chỉ hội thoại, câu hỏi sản phẩm có “loại này”, ảnh QR RGB JPEG, các đường gửi kênh hiện có.
- `git diff --check` đạt trên các tệp thay đổi trong lượt kiểm thử.
- Backend/worker đã nạp bản sửa; worker có volume uploads dùng chung.
- Phạm vi kết luận: ba kịch bản Zalo nêu trên và các kiểm thử liên quan. Không coi đây là chứng nhận mọi câu diễn đạt hoặc mọi kênh đều không thể lỗi.

## Ảnh

- `three-orders-smh.jpg`: trang Đơn bán trên SMH (khung hình hẹp chỉ thấy khu vực tổng quan; ba dòng đơn đã đối chiếu qua trạng thái giao diện và dữ liệu, không nằm trong khung ảnh này).
- `CHAT-14-confirmed-by-customer.jpg`: đúng hội thoại bot, có thông báo nhận xác nhận hóa đơn từ khách và các trạng thái đơn hàng. Ảnh QR đã được kiểm tra qua trạng thái giao diện; không có ảnh chụp QR riêng trong báo cáo này.

## Kiểm thử bổ sung: tiếp nhận hoàn đơn

- Gửi yêu cầu hoàn hàng không có mã qua Zalo: bot hỏi mã đơn.
- Gửi `CHAT-14`: bot xác nhận đã nhận thông tin hoàn đơn và yêu cầu đợi nhân viên hỗ trợ, không hỏi thêm trường bắt buộc.
- Phiếu #3 “Yêu cầu hoàn/đổi trả đơn CHAT-14” được tạo, trạng thái mở; có thông báo trong ứng dụng cho nhân viên.
- Ngay sau khi tiếp nhận, đơn vẫn delivered, paid_amount=119000 và refunded_amount=0, giống trước lượt thử.
- Sau đó lịch sử quản trị có chuyển delivered → completed → refunded với actor_id=18; thao tác quản trị này không do bộ tiếp nhận hoàn đơn thực hiện.
- 49 bài kiểm thử và 3 subtest đạt, gồm 7 kiểm thử mới cho luồng hoàn đơn và hồi quy tác vụ đơn/ghép tin. Fixture kiểm thử đơn cũ được bổ sung tạo TenantBase để chạy với kiến trúc tách schema hiện tại.
- Bằng chứng: `return-CHAT-14.jpg`.

## Kiểm tra sau thao tác hoàn tiền của nhân viên

- CHAT-14 hoàn 119.000 đồng: lịch sử kho cho product_id=331 có sales_shipment -1 (8 → 7) và sales_refund +1 (7 → 8), đúng một lần. Không thực hiện lại giao dịch hoàn tiền khi kiểm tra.
- Bổ sung job thông báo dựa trên sự kiện refund_created đã lưu. Thông báo CHAT-14 gửi qua Zalo thành công; lần hoàn tiền sau sẽ tự tạo job trong cùng giao dịch với bút toán hoàn. Khóa thông báo gắn với từng payment để chống gửi trùng và hỗ trợ hoàn từng phần.
- Doanh thu cũ loại trạng thái refunded nên loại CHAT-14, nhưng chưa trừ tiền hoàn trên đơn vẫn ở trạng thái khác. CHAT-5 đã hoàn 257.000 đồng mà còn processing, làm báo cáo dư 257.000 đồng.
- Sửa tổng, phân kênh và chuỗi thời gian để dùng total_amount − refunded_amount trong phạm vi trạng thái được ghi nhận. Tổng thực tế đã đối chiếu trên SMH: 1.540.000 → 1.283.000 đồng; Telegram 257.000 → 0 đồng.
- Khi ghi nhận hoàn/thu tiền, giao diện tải lại cả đơn và danh mục sản phẩm để số tồn không bị giữ ở dữ liệu cũ.
- 22 bài kiểm thử đạt, gồm hoàn một phần rồi hoàn hết, trừ doanh thu, chỉ nhập lại kho đúng một lần, chống lặp idempotency key và nội dung thông báo theo từng bút toán. Frontend build thành công.
- Hoàn một phần tiền không tự cộng lại toàn bộ hàng. Luồng hiện hành chỉ nhập lại số lượng đã bán khi hoàn toàn bộ cho đơn delivered/completed; đây là hành vi hiện tại được kiểm chứng, chưa có bước kiểm định tình trạng hàng trả về.
- Ảnh: `refund-CHAT-14-notified.jpg`, `net-revenue-after-refund.jpg`.
