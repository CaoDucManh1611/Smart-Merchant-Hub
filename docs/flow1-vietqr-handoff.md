# Luồng 1 — VietQR và bàn giao

Checkout mới tạo VietQR tại backend, không gọi payOS hoặc dịch vụ tạo QR bên ngoài. Admin cấu hình tài khoản nhận phí nền tảng tại `#admin-payments`: chọn ngân hàng, số tài khoản, tên người nhận, bật và lưu. Chưa có tài khoản thật được cấu hình bởi tác vụ này.

QR chốt số tiền báo giá, ngân hàng, tài khoản và nội dung `SMH<subscription_id>`. Gửi lại không tạo đơn thứ hai; đổi cấu hình chỉ áp dụng đơn mới. QR hết hạn sau 24 giờ và bị ẩn. QR không ngăn ngân hàng nhận chuyển khoản muộn, nên cần đối soát thủ công. Đơn payOS cũ và khóa đã lưu được giữ để không mất lịch sử.

Admin kiểm tra giao dịch ngân hàng rồi vào Danh sách shop → Xem chi tiết → chọn yêu cầu gói → nhập mã giao dịch thật → Xác nhận đã thu tiền. API `/api/platform/shops/{id}/payments` chỉ cho admin, kiểm tra số tiền và mã giao dịch; không cộng trùng doanh thu. Shop làm mới trạng thái để thấy đã nhận tiền. Duyệt/kích hoạt gói là thao tác riêng. Khách không có API tự xác nhận tiền.

Hạ gói chỉ gửi yêu cầu; không tạo QR, khoản thu hoặc yêu cầu hoàn tiền. Các khoản hoàn tiền của nghiệp vụ đơn bán cũ không bị xóa.

Khi admin đổi giá: mở lịch sử vẫn thấy giá cũ. Shop chọn lại gói hoặc bấm “Tạo yêu cầu theo giá mới”, rồi gửi để tạo yêu cầu theo giá danh mục hiện tại. Yêu cầu chờ cũ được hủy, không sửa/xóa số tiền hoặc QR lịch sử. Nếu có khoản thu/hoàn tiền hoặc cần đối soát thì chặn thay thế để admin xử lý. Không đổi giá tự động chỉ vì admin cập nhật danh mục. QR VietQR cũ không thể bị vô hiệu hóa trong ứng dụng ngân hàng: tiền chuyển tới nội dung yêu cầu đã hủy phải được admin đối soát, không tự cộng vào yêu cầu mới.

Kiểm thử thực tế 2026-10-11: trên shop đang mở, chọn Gói Thường 2.000đ → gửi yêu cầu SMH-13 → tạo QR có số tiền 2.000đ, nội dung SMH13. Không chuyển tiền hoặc xác nhận thu tiền trong kiểm thử này. SMH-12 cũ giữ lịch sử 1.000đ.

Ticket lỗi kết nối: component `ConnectionSupport` đã gắn vào màn hình kết nối. Shop POST/GET `/api/support/requests`; trạng thái và phản hồi nằm trong ticket. Người 3 dùng GET `/api/platform/support-requests`, PATCH `/api/platform/support-requests/{id}` để nhận/xử lý/phản hồi. Xem `flow1-ticket-handoff.md` cho hợp đồng dữ liệu. Không gửi ticket tới người thật trong tác vụ kiểm thử.

Kiểm thử hiện tại: 44 backend tests + 16 subtests (VietQR, ticket, lịch hẹn, báo giá, dự án, đơn bán/tồn kho/thanh toán); 273 frontend tests; Vite production build thành công. Test SQLite cô lập, không dùng dữ liệu shop thật. Chưa kiểm thử chuyển khoản thật, PostgreSQL tranh chấp đồng thời hoặc mọi ngân hàng bằng app di động.

Kiểm tra bổ sung: 25 tests cho VietQR, API cấu hình và cấu hình payOS lịch sử; route checkout thực trả VietQR và chặn sai shop qua test riêng. Trình duyệt đăng nhập admin thành công, tải danh sách ngân hàng, báo lỗi đúng khi cấu hình chưa bật; viewport 390px không tràn ngang. Không lưu số tài khoản giả hoặc xác nhận thu tiền trên dữ liệu thật. Build có cảnh báo bundle lớn, không có lỗi build.

Định dạng VietQR tham khảo thư viện MIT https://github.com/openhoangnc/vietqr ; vector CRC kiểm tra bằng dữ liệu công khai của thư viện. Danh mục ngân hàng lấy từ https://api.vietqr.io/v2/banks ngày 2026-10-11, lưu cục bộ. Không tải/chạy cổng MB không chính thức và không cần mật khẩu ngân hàng.
