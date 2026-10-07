# Kịch bản demo Luồng 3

## Chuẩn bị

- Dùng môi trường test/demo riêng, hai shop A/B và dữ liệu giả do nhóm tạo; không dùng thông tin khách hàng thật.
- Chuẩn bị owner A, agent/support A, viewer A và owner B. Chỉ demo platform admin nếu đã tạo tài khoản riêng.
- Cấu hình trước provider/kênh nếu muốn trình diễn OAuth/webhook thật; credentials phải ở env/secret store, không xuất hiện trên màn hình.
- Nếu provider live không sẵn sàng, gọi rõ đây là webhook simulation/test fixture, không trình bày như tin nhắn live.
- Thư mục gợi ý chụp ảnh thật: `docs/luong-3/evidence/`. Không có screenshot được tạo tự động bởi kiểm thử hiện tại. Che email/token/định danh nhạy cảm trước khi lưu.

| # | Thao tác | Màn hình/API cần mở | Kết quả mong đợi | Điểm cần nói / ảnh cần chụp |
|---:|---|---|---|---|
| 1 | Đăng nhập owner shop A | Frontend login, sau đó workspace | Vào workspace A, thông tin shop đúng | Nêu đây là phiên shop-scoped; chụp dashboard đã ẩn email nếu cần. |
| 2 | Tạo hoặc chọn shop | Onboarding hoặc admin nền tảng → shops | Shop A có trạng thái hoạt động và module cần demo | Chỉ platform admin quản lý vòng đời shop. Chụp trang shop không lộ bí mật. |
| 3 | Kết nối kênh | Cài đặt → Kênh; OAuth/webhook/provider console nếu dùng live | Trạng thái connected/verified và cấu hình webhook hợp lệ | Logo chưa đủ chứng minh kết nối. Chụp trạng thái đã xác minh và che token. |
| 4 | Nhận tin nhắn | Gửi tin từ account thử hoặc test webhook; mở Inbox | Message được lưu thành conversation dưới tenant A | Phân biệt live provider với fixture. Chụp inbox và channel. |
| 5 | Xem Customer 360 | Click customer từ inbox; API `GET /api/customers/{id}` | Hồ sơ, định danh và lịch sử thuộc đúng customer/shop | Chụp màn hồ sơ, tránh dữ liệu thật. |
| 6 | Tạo ticket | Mục **Phiếu hỗ trợ & thời hạn xử lý**; API `POST /api/tickets` | Phiếu hiện title, mô tả, customer, channel, priority, SLA | Nêu ticket gắn tenant và customer/conversation. Chụp form/danh sách. |
| 7 | Admin xem ticket | Admin A trong màn ticket | Xem chi tiết, mô tả, customer, channel, trạng thái, SLA, assignee | Dùng giao diện hiện hữu, không tạo trang admin riêng. |
| 8 | Phân công nhân viên | Chọn assignee trong ticket | Assignee đổi sang agent/support của cùng shop | Chứng minh nhân viên khác shop không thể được gán. Chụp assignee. |
| 9 | Cập nhật và phản hồi | Đổi trạng thái, thêm comment/ghi chú, mở History | Trạng thái, comment và history có dữ liệu mới | Chụp history và phản hồi; xác định rõ comment là nội bộ hay gửi khách theo UI. |
| 10 | Kiểm tra quyền | Đăng nhập agent/support/viewer; thử ticket và SLA PUT | Agent/support thao tác theo quyền; viewer bị chặn ghi; staff không sửa SLA rules | API test đã xác minh support shop thao tác ticket và agent bị chặn khi override deny; lặp lại trong môi trường demo trước khi trình bày. |
| 11 | Chứng minh tenant isolation | Đăng nhập A, request ID ticket/customer/order thuộc B và gửi `X-Business-Id` giả | Không đọc/sửa dữ liệu B; ID trực tiếp bị từ chối/404 | Dùng record thử. Chụp status code, không đưa response body nhạy cảm. |
| 12 | Checkout / order | Bán hàng → sản phẩm và đơn; API `/api/orders` | Tạo order draft với customer/item cùng tenant, chuyển trạng thái hợp lệ | Nêu xác nhận order/payment là thao tác khác nhau. |
| 13 | Quote | Commercial → báo giá | Báo giá thuộc customer A; transition hợp lệ | Chụp báo giá và trạng thái. |
| 14 | Project | Commercial → dự án; có thể tạo từ quote accepted | Project gắn quote/customer hợp lệ cùng shop | Chụp quan hệ quote → project. |
| 15 | Appointment | Lịch hẹn | Lịch gắn customer/service/staff và status đúng | Chụp lịch thử; nêu module phải bật. |
| 16 | AI/RAG | Kho kiến thức, sau đó chatbot/RAG | Tài liệu xử lý xong; câu trả lời hiển thị nguồn phù hợp hoặc handoff | Chỉ gọi API live là live khi có key/provider thật; chụp nguồn citation và che nội dung riêng tư. |
| 17 | Kết luận | Quay lại checklist / TEST_REPORT | Phân biệt PASS automated, skipped và chưa xác minh live | Nêu Docker migration chỉ được xác nhận sau khi hoàn thành thực tế; không nhận các phần chưa chạy là PASS. |

## Evidence cần nhóm chụp tại buổi demo

Lưu ảnh chụp màn hình thật dưới `docs/luong-3/evidence/` nếu nhóm có thể tạo; đặt tên theo thứ tự, ví dụ `01-login.png`, `06-ticket-list.png`, `11-tenant-denied.png`. Không thêm ảnh minh họa giả hoặc ảnh chứa token, cookie, email cá nhân, dữ liệu khách thật. Ghi ngày, commit và môi trường trong chú thích đi kèm khi tạo evidence.
