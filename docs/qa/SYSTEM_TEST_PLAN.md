# Kế hoạch kiểm thử hệ thống

Ngày 07/11/2026. HEAD `c6895046f69773ed40db83ecc053faabce911e18`. Một agent QA, chỉ tạo tài liệu và bộ chạy kiểm thử trong docs/qa. Quyền ưu tiên của chủ sở hữu là không sửa source ứng dụng.

## Hệ thống và nguồn yêu cầu

Vue 3/Vite 7 gọi FastAPI. SQLAlchemy kết nối PostgreSQL/pgvector theo ba ngữ cảnh legacy/platform/tenant. Redis hỗ trợ tác vụ nền và rate limiting. Worker xử lý chatbot, tài liệu và công việc CRM. LangGraph điều phối công cụ, BM25 mặc định và nhánh embedding/hybrid tùy cấu hình. Catalog cung cấp giá/tồn; RFM/recommendation phụ thuộc consent. Các adapter gồm Meta, Telegram, Zalo, TikTok, Shopee; thu phí có payOS/MONA và xử lý thủ công. Tài liệu và media lưu theo backend storage. Router tại backend/app/api/router.py và OpenAPI hiện hành là nguồn kiểm kê.

Nguồn yêu cầu gồm prompt chủ sở hữu, UI đã quan sát, OpenAPI và hợp đồng test hiện có. Các kỳ vọng suy ra từ source được coi là hợp đồng cần xác nhận nếu liên quan chính sách nghiệp vụ. Không tự đặt SLA, policy consent hoặc mức tải production.

## Danh mục và thứ tự theo rủi ro

| Nhóm | Chức năng | Ưu tiên | Luồng chính |
|---|---|---|---|
|AUTH|Đăng nhập, OTP, phiên|P0|Đăng nhập → me → logout → thử token cũ|
|RBAC|Vai trò và tenant|P0|Dùng từng vai trò đọc/ghi ID shop khác qua API|
|CRM|Khách, danh tính, gộp|P1|Tìm kiếm → xem 360 → merge preview → merge → undo|
|INBOX|Hội thoại, realtime, media|P1|Nhận sự kiện → mở chat → gửi phản hồi → refresh|
|CHANNEL|Meta, Telegram, Zalo, TikTok, Shopee|P0|Verify chữ ký → nhận sự kiện → phát lại → sai chữ ký|
|CATALOG|Sản phẩm, ảnh, nhập CSV|P1|Nhập → đọc giá/tồn → thay ảnh → chỉnh tồn|
|ORDER|Đơn bán, tồn, thanh toán đơn|P0|Tạo nháp → xác nhận → giao → hoàn tất → gửi lại thao tác|
|PROCURE|Nhà cung cấp, mua hàng, kho|P0|Tạo đơn → nhận một phần → nhận còn lại → gửi lặp|
|SERVICE|Dịch vụ, lịch hẹn, giờ làm|P1|Tra lịch → đặt thử → đổi trạng thái → sửa ghi chú khi capability tắt|
|KB|Tài liệu, parsing, version, index|P0|Upload → chờ ready → retrieve → replace → rollback trong DB thử|
|RAG|Graph, nguồn, tư vấn, multi-turn|P0|Hỏi giá → nối tiếp → đổi mẫu → thiếu nguồn → injection|
|RFM|RFM, recommendation, consent|P0|Gợi ý cùng nhu cầu/ngân sách với từng persona|
|WORK|Tickets, SLA, tasks, workflow|P1|Tạo → phân công → quá hạn → đóng → dispatch bị chặn|
|SAAS|Shop, team, gói, thu phí|P0|Đăng ký gói → xác nhận tiền → approve → retry callback|
|PRIVACY|Consent, purge, nhật ký|P0|Revoke → đọc/ghi memory → purge scoped → kiểm audit|
|OPS|Báo cáo, backup, vận hành|P0|Build → health → backup → verify → restore → so hash|

Toàn bộ 405 operations và phương thức đã xuất tại evidence-20261107/api-inventory.json. Danh mục này là phạm vi cần kiểm, chưa có nghĩa đã thực thi 405 operations. Các module còn có commercial quotes/projects, leads, notifications, experimentation và hỗ trợ platform; xem FEATURE_INVENTORY.md để đối chiếu mọi router.

## Môi trường và thực thi

1. Snapshot hash source trước/sau, giữ 5 lock files tồn tại trước lượt chạy.
2. Backend dùng fixture SQLite riêng qua conftest; chặn socket ra ngoài, chỉ cho loopback ephemeral phục vụ Windows asyncio. Không dùng DB đang phục vụ, test.db hoặc credential thật.
3. Frontend chạy test và build ra thư mục evidence, tránh thay dist ứng dụng.
4. Probe chỉ đọc localhost ở mức 22 request tuần tự, lưu status/header, không lưu body khách.
5. PostgreSQL disposable qua container tmpfs loopback 55439, dùng dữ liệu và tài khoản QA. Kết quả ghi riêng khi hoàn tất.
6. UI mới cần browser kết nối, hai tenant và vai trò thử. Không gửi tin kênh khách hoặc thanh toán thật.

## Tiến độ các phase

| Phase | Trạng thái |
|---|---|
|1 Discovery|Đã kiểm kê router và 405 operations|
|2 Environment|Backend/frontend test runtime hoạt động; PostgreSQL disposable; UI bị chặn kết nối|
|3 Functional|Đã chạy suite hiện có; chi tiết JUnit và execution report|
|4 API/DB|Có probe trực tiếp và fixture integration; PG có kết quả riêng|
|5 UI/E2E|BLOCKED trong lượt hiện tại; minh chứng lượt trước ghi riêng|
|6 Security|Kiểm tra tự động, probe auth và review cấu hình chọn lọc|
|7 Performance|Baseline health tuần tự; load/recovery/leak NOT RUN|
|8 AI/RAG|Hợp đồng offline có test; lượt provider mới NOT RUN|
|9 Defects|Ghi findings, không sửa source hoặc tự retest như đã có bản vá|
|10 Release|NO-GO cho production do acceptance còn thiếu|

## Quy tắc nghiệm thu

PASSED cần output thực chạy. FAILED cần assertion hoặc hành vi sai có căn cứ. BLOCKED ghi công cụ/quyền/môi trường thiếu. NOT RUN là chưa thực thi. Phân biệt unit, fixture integration, PostgreSQL, browser E2E và real-channel E2E. Chỉ tính quality trên ca đã chạy; tách nhãn AI/nhận xét QA khỏi nhãn người độc lập.
