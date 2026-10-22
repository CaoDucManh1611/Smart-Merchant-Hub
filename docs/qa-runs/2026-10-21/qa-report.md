# Báo cáo kiểm thử Smart Merchant Hub

- Thời điểm: 21/10/2026 (UTC+7)
- Môi trường: Docker Compose local, PostgreSQL + pgvector, Redis, FastAPI, worker, Vue/Vite
- Giao diện: Codex in-app browser tại `http://127.0.0.1:5173/`
- Danh mục gốc: `docs/qa-test-case-catalog.md` (286 test case)
- Phương pháp: kiểm thử smoke bằng Computer Use kết hợp bộ test tự động backend/frontend

## Tình trạng môi trường

| Thành phần | Kết quả | Bằng chứng |
|---|---|---|
| PostgreSQL | PASS | Container `crm_chatbot_db` healthy, cổng 5432 |
| Redis | PASS | Container `crm_chatbot_redis` healthy |
| Backend | PASS | Container healthy, `GET /health` trả `{"status":"ok"}` |
| Worker | PASS | Container healthy |
| Frontend | PASS | Container healthy, `http://127.0.0.1:5173/` trả HTTP 200 |

## Kết quả theo 16 nhóm

| # | Nhóm | Kết quả | Bằng chứng / giới hạn |
|---:|---|---|---|
| 1 | Xác thực, tài khoản và phiên đăng nhập | PASS có cảnh báo | Phiên đăng nhập được khôi phục sau khi Docker khởi động lại; trang Cài đặt hiển thị “Tài khoản & phiên đăng nhập”. Bộ frontend có test đăng nhập/quên mật khẩu nhưng còn lỗi ở luồng admin OTP. |
| 2 | Đa shop, phân quyền và quản trị nội bộ | PASS một phần | Tài khoản shop không mở được `#admin-backups`; giao diện vẫn ở workspace shop. Các màn admin cần phiên platform-admin riêng nên chưa kiểm thử thao tác ghi bằng UI. |
| 3 | Hộp thư đa kênh và realtime | PASS có lỗi tự động | Inbox tải 29/29 hội thoại, có trạng thái chưa đọc/ưu tiên, mở được hội thoại Facebook. Test tự động Meta live refresh đang fail. |
| 4 | Facebook và Instagram | PASS hiển thị, BLOCKED tích hợp thật | Inbox hiển thị hội thoại Facebook/Instagram và trạng thái chat. Không gửi tin thật ra Meta vì không thực hiện giao tiếp đại diện và không có sandbox xác nhận trong lượt chạy này. |
| 5 | Telegram, Zalo, TikTok và Shopee | PASS hiển thị, có lỗi nhãn | Inbox có đủ Telegram, Zalo, TikTok, Shopee; Telegram hiển thị preview ảnh. Test tự động còn lệch nhãn `Zalo`/`ZALO` và `Whatsapp`/`WHATSAPP`. |
| 6 | Media và tệp đính kèm | PASS smoke | Hội thoại Telegram hiển thị `📷 Hình ảnh`; test frontend cho picker theo capability, URL media, audio, sticker và Meta echo đạt. Chưa gửi media ra provider thật. |
| 7 | Customer 360, danh tính và gộp khách | PASS smoke | Mở được Hồ sơ khách hàng 360, danh tính đa kênh, lịch sử tương tác và khu vực gộp hồ sơ trùng. Không thực hiện gộp/xóa dữ liệu thật. |
| 8 | Sản phẩm, tồn kho, đơn hàng và thanh toán khách | PASS smoke | Trang Sản phẩm tải danh mục/import/export; trang Đơn bán tải doanh thu, đơn đa kênh, trạng thái và thanh toán. Không bấm ghi nhận tiền/hoàn tiền. |
| 9 | RFM, sở thích và gợi ý sản phẩm | PASS smoke | Customer 360 hiển thị “Gợi ý sản phẩm cho khách”; trang Khách quan tâm tải thành công. Bộ backend đang kiểm tra thuật toán và tenant scope. |
| 10 | Kho tri thức, hybrid RAG và chatbot | PASS smoke | Kho kiến thức tải danh sách tài liệu, hạn mức Gói Premium; hội thoại có trạng thái bot và nút nhân viên tiếp quản. Không gọi provider AI trả phí trong kiểm thử UI. |
| 11 | Ticket, SLA, workflow và thông báo | PASS smoke | Phiếu hỗ trợ, việc cần xử lý, lịch hẹn, báo giá, giờ làm việc, quy tắc thời hạn và quy trình tự động đều tải được. |
| 12 | Gói dịch vụ, quota và thanh toán nền tảng | PASS smoke | Trang Chọn gói tải Gói Demo/Thường/VIP và thông tin giá. Không đăng ký gói hoặc xác nhận giao dịch thật. |
| 13 | Backup, restore, migration và PostgreSQL | PASS hạ tầng, BLOCKED UI admin | PostgreSQL và migration khởi động thành công. Tài khoản shop bị chặn khỏi `#admin-backups` đúng phân quyền. Không chạy restore phá huỷ trên dữ liệu hiện tại. |
| 14 | API, webhook và bảo mật | PASS hạ tầng, đang chạy suite | `/health` đạt; backend test suite PostgreSQL đang chạy. Các webhook bên ngoài cần sandbox/provider thật để xác nhận end-to-end. |
| 15 | UI/UX, accessibility và responsive | PASS smoke | Điều hướng bàn phím/AX đọc được; chuyển dark → light → dark thành công; bố cục Customer 360 co về viewport hẹp và vẫn cuộn được. |
| 16 | Hiệu năng, độ bền và quan sát hệ thống | PASS smoke | Stack phục hồi sau khi Docker Desktop khởi động, health checks đạt; frontend và backend giữ trạng thái healthy trong lúc kiểm thử. Chưa chạy load/stress kéo dài. |

## Test tự động

### Frontend

- Lệnh: `npm test`
- Tổng: **316**
- Pass: **316**
- Fail: **0**
- Skip: **0**
- Raw log: `frontend-full-tests.log`
- Đã sửa và xác nhận lại cả 9 kiểm thử hồi quy được báo lỗi trước đó; giữ riêng kiểm thử Zalo và khôi phục kiểm thử unknown-channel để bao phủ cả hai hành vi.

### Backend

- Lệnh: `python -m pytest -q` trong `backend`, chạy cùng lúc với frontend test và build.
- Kết quả: **PASS — 1.439 test và 30 subtest đạt**, thời gian 1.133,52 giây (18 phút 53 giây).
- PostgreSQL test isolation: sau khi chạy, xác nhận 0 schema `pytest_*` trong cả ba database kiểm thử. Đã xóa 119 schema mồ côi của một lượt test bị ngắt trước đó, chỉ trong các database `*_test`.
- Raw log: `backend-full-tests.log`; log kiểm tra dọn schema: `postgres-cleanup-check.log` và `postgres-test-cleanup.log`.

### Build frontend

- Lệnh: `npm run build`
- Trạng thái: **PASS** — 131 module được build trong 11,34 giây.
- Cảnh báo: bundle JavaScript 1.088,33 kB trước gzip vượt ngưỡng khuyến nghị 500 kB; nên tách chunk ở một đợt tối ưu hiệu năng riêng.
- Raw log: `frontend-full-build.log`.

## Kết luận tạm thời

Đã kiểm tra smoke đủ 16 nhóm trên server local và ghi rõ phần nào chỉ xác minh giao diện/hạ tầng. Toàn bộ backend suite đạt 1.439 test + 30 subtest, frontend đạt 316/316 test, và production build thành công. Các database kiểm thử đã được dọn sạch schema tạm. Bundle JavaScript còn vượt ngưỡng khuyến nghị; các connector bên ngoài chưa được xem là end-to-end pass nếu chưa gửi/nhận thật bằng sandbox.
