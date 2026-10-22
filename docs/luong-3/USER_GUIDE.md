# Hướng dẫn sử dụng Smart Merchant Hub

Tài liệu này mô tả các thao tác người dùng trong workspace shop và nêu rõ chỗ cần cấu hình nhà cung cấp bên ngoài. Tên mục có thể khác nhẹ theo ngôn ngữ/cấu hình module đang bật.

## 1. Đăng nhập và chọn shop

1. Mở frontend tại địa chỉ do người triển khai cung cấp.
2. Đăng nhập bằng tài khoản shop hoặc tài khoản quản trị nền tảng đã được cấp.
3. Tài khoản thành viên thuộc shop chỉ làm việc trong tenant của mình. Header `X-Business-Id` không thay đổi shop gắn với phiên đăng nhập.
4. Tài khoản platform admin quản lý shop ở khu vực nền tảng; không dùng tài khoản này thay cho tài khoản nhân viên shop trong workspace.

Tài khoản đầu tiên có thể được tạo bằng quy trình onboarding hoặc script `backend/scripts/create_admin.py`. Script không đặt mật khẩu mặc định công khai; người vận hành cần đặt mật khẩu riêng.

## 2. Quản lý shop và nhân sự

- Owner/admin quản lý thông tin shop, module, thành viên, vai trò và quyền chi tiết trong **Cài đặt**.
- Vai trò hỗ trợ trong shop gồm owner, admin, agent, support, sales và viewer.
- Mục quyền chi tiết hiện cho phép cấu hình `read`/`write` theo resource customers, orders, tickets, team, reports và documents; có thể áp dụng theo vai trò hoặc nhân viên. Quy tắc deny được ưu tiên khi permission service đánh giá quyền.
- Quản trị nền tảng thực hiện quản lý vòng đời shop/gói tại khu vực admin nền tảng.
- Nhân viên không có quyền quản trị sẽ nhận phản hồi từ chối ở backend; ẩn nút trên giao diện không thay thế kiểm tra backend.

Lưu ý: quyền hiệu lực theo role được kiểm tra ở nhiều API, nhưng việc áp dụng permission override ngoài ticket chưa được kiểm thử runtime đầy đủ trong đợt Luồng 3 này. Không coi một override là đã có hiệu lực cho mọi API chỉ vì nó xuất hiện trong màn hình quyền.

## 3. Kết nối kênh

1. Vào **Kênh / Kết nối mạng xã hội**.
2. Chọn connector cần dùng và hoàn thành cấu hình OAuth, webhook hoặc thông tin bot theo nhà cung cấp.
3. Kiểm tra trạng thái kết nối trong giao diện và gửi/nhận một sự kiện thử an toàn.
4. Kiểm tra conversation và message trong inbox trước khi bật tự động trả lời.

Meta yêu cầu ứng dụng, quyền, Page và webhook phù hợp. Telegram cần bot/webhook; Zalo cần cấu hình Bot Creator hoặc bridge tương ứng. Connector TikTok/Shopee phụ thuộc phiên đăng nhập trình duyệt và không tương đương tích hợp API chính thức. Logo kênh không chứng minh kết nối đã hoạt động. Không ghi token hoặc cookie vào ticket, log, repository hay ảnh demo.

## 4. Inbox, CRM và hồ sơ khách hàng

- Tin nhắn inbound được nhận qua webhook/connector, gắn vào tenant của channel, rồi cập nhật unified inbox.
- Từ inbox có thể mở Customer 360 để xem hồ sơ, các định danh/kênh, lịch sử tương tác và các dữ liệu CRM được phép.
- Gửi phản hồi, phân công hội thoại, gắn nhãn và ghi chú theo các thao tác được hiển thị cho vai trò hiện tại.
- Nếu provider chưa được cấu hình, dùng test harness/mô phỏng webhook trong kiểm thử; không trình bày kết quả đó như một kết nối provider live.

## 5. Phiếu hỗ trợ (ticket)

Mở **Phiếu hỗ trợ & thời hạn xử lý**:

1. Tạo phiếu với tiêu đề, customer, mô tả, độ ưu tiên; có thể liên kết conversation và chọn nhân viên phụ trách.
2. Danh sách hiển thị mô tả, customer, channel, ưu tiên, trạng thái, hạn SLA và người phụ trách.
3. Đổi người phụ trách hoặc trạng thái ngay trong hàng ticket.
4. Mở lịch sử để xem sự kiện xử lý; thêm ghi chú/phản hồi nội bộ từ vùng comment.
5. SLA rules chỉ cho owner/admin cập nhật. Staff có thể xem cấu hình SLA nếu được phép đọc ticket.

API tương ứng: `GET/POST /api/tickets`, `GET/PATCH /api/tickets/{id}`, `GET /api/tickets/{id}/history`, `POST /api/tickets/{id}/comments`, `GET/PUT /api/tickets/sla/rules`. Tenant scope được áp dụng ở backend; ticket của tenant khác trả về không tồn tại thay vì tiết lộ nội dung.

## 6. Checkout, đơn bán và thanh toán

- Quản lý sản phẩm trong khu vực bán hàng; tạo order từ customer, conversation (nếu có) và các sản phẩm thuộc shop.
- Đơn mới bắt đầu ở trạng thái draft. Chuyển trạng thái theo quy trình bán hàng/tồn kho đang cấu hình.
- Ghi nhận thanh toán/hoàn tiền ở các thao tác tương ứng; không coi việc tạo đơn hoặc duyệt gói là bằng chứng thu tiền.
- Kiểm tra customer, item, số lượng, giá và tổng tiền trước khi xác nhận.

## 7. Lịch hẹn

- Mở **Lịch hẹn** nếu module appointments được bật cho shop.
- Tạo/cập nhật lịch theo customer, dịch vụ, nhân viên và thời gian.
- Theo dõi trạng thái, lịch nhắc và xuất lịch nếu thao tác đó có sẵn trong phiên bản đang chạy.
- Không tạo lịch khi shop chưa bật module hoặc user không có quyền ghi.

## 8. Báo giá, dự án và hóa đơn

- Mở khu vực **Báo giá / Dự án / Hóa đơn**.
- Tạo báo giá theo customer và dòng hàng; trạng thái phải đi theo transition hợp lệ.
- Tạo dự án từ báo giá đã chấp thuận hoặc tạo theo luồng hiện có; customer và báo giá liên kết phải thuộc cùng shop.
- Tạo hóa đơn và ghi nhận thanh toán theo quyền hiện hành.
- Gửi email chỉ hoạt động nếu backend được cấu hình mail/provider phù hợp.

## 9. AI/RAG

- Tải tài liệu vào kho kiến thức của shop, chờ xử lý/chia đoạn và embedding hoàn tất.
- Kiểm tra câu trả lời và nguồn trích dẫn trong chatbot/RAG; yêu cầu bot bàn giao khi không có căn cứ phù hợp.
- LLM/embedding bên ngoài cần API key trong cấu hình riêng. Chế độ local hoặc test không chứng minh provider bên ngoài hoạt động.
- Không tải tài liệu chứa dữ liệu nhạy cảm nếu chưa được shop cho phép; dữ liệu RAG phải giữ tenant scope.

## 10. Khi bị từ chối quyền

HTTP 401 thường có nghĩa phiên chưa hợp lệ/hết hạn hoặc cần MFA; HTTP 403 nghĩa vai trò/quyền hiệu lực không cho phép thao tác; HTTP 404 trên ID tenant khác là hành vi che giấu tài nguyên. Báo owner/admin shop để kiểm tra role, trạng thái tài khoản, module và permission override. Không thử vượt quyền bằng cách thay `X-Business-Id`.
