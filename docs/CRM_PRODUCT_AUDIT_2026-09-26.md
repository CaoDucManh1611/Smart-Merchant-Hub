# Rà soát CRM — 26/09/2026

Phạm vi rà soát: frontend, router/API/backend, test tự động và tài liệu trong repo. TikTok bridge được để ngoài phạm vi theo yêu cầu; không thay đổi cấu hình hay luồng bridge.

## Tình trạng hiện tại

CRM đã có các nhóm chức năng sau:

- **Hộp thư & khách hàng 360:** hợp nhất hội thoại, phân công/tiếp quản (gồm giao việc hàng loạt có xác nhận), hồ sơ khách đa kênh, timeline, nhãn/nhóm, ghi chú và nội dung media.
- **Bán hàng & vận hành:** danh mục sản phẩm, tồn kho, lead pipeline, đơn bán/đơn nhập, nhà cung cấp, thanh toán, vận chuyển và lịch sử trạng thái.
- **Chăm sóc khách hàng:** ticket, phân công, SLA, giờ làm việc, CSAT, thông báo và lịch chăm sóc lại.
- **AI & tự động hóa:** kho tri thức/RAG, chatbot, mẫu trả lời, công cụ có allow-list, workflow/retry, đánh giá AI, thử nghiệm/rule suggestions và kết quả hội thoại do nhân viên xác nhận.
- **SaaS/quản trị:** tenant isolation, nhân viên/vai trò/quyền, gói và quota, onboarding OTP, phê duyệt shop, usage, nhật ký audit, báo cáo và các luồng quyền riêng tư.
- **Dịch vụ theo lịch:** danh mục dịch vụ, lịch đặt/sửa/đổi trạng thái, lọc lịch sắp tới/hôm nay/7 ngày, phân công nhân viên, ngăn lịch trùng cho cùng nhân viên và nhắc trong CRM.
- **Dịch vụ dự án/B2B:** báo giá nhiều hạng mục có tính thuế; trạng thái báo giá; chuyển báo giá được duyệt thành dự án; theo dõi phụ trách/tiến độ; phát hành hóa đơn, hạn thanh toán, quá hạn và sổ từng khoản thu.

Hai bộ nghiệp vụ mới được bật/tắt độc lập trong Cài đặt theo từng shop. Tắt bộ chỉ khóa/ẩn thao tác, không xóa lịch hay chứng từ. Hóa đơn có lịch sử thanh toán; không thể hủy hóa đơn đã thu tiền hoặc ghi nhận vượt số dư. CRM có nhắc nội bộ và tùy chọn gửi nhắc lịch qua email; báo giá/hóa đơn có nút gửi email và ghi nhận thời điểm gửi, yêu cầu SMTP hoạt động và email khách hợp lệ. Lịch hiện xuất `.ics` để nhập vào Google Calendar/Outlook, chưa đồng bộ hai chiều.

Dashboard chất lượng trợ lý tách riêng hai loại số liệu: kết quả do nhân viên xác nhận cho hội thoại có bot trả lời/bàn giao, và ước tính từ trạng thái CRM (đã đóng, đang bàn giao, khách chưa phản hồi sau 24 giờ hoặc đang tiếp tục). Hội thoại chưa được gắn kết quả không bị suy đoán thành đã giải quyết. Nhãn xác nhận được lưu theo shop và ghi audit khi thay đổi.

Hộp thư hỗ trợ chế độ xem đã lưu theo shop và tài khoản đăng nhập trên trình duyệt hiện tại. Đây là tùy chọn giao diện cục bộ, chưa đồng bộ qua thiết bị khác.

Các module/API và nhiều luồng nghiệp vụ có regression test. Điều này xác nhận logic được kiểm tra trong môi trường tự động; không thay thế kiểm thử staging với tài khoản/kênh thật.

## Đa ngôn ngữ

Đã thêm lựa chọn **Tiếng Việt / English**, lưu lựa chọn trên trình duyệt, đặt `lang` cho tài liệu, định dạng ngày/tiền theo locale và phủ các chuỗi tĩnh của ứng dụng. Regression test kiểm tra chuỗi tĩnh không còn bị trộn ngôn ngữ. Thông báo/lỗi do API và nhãn dữ liệu nghiệp vụ vẫn cần tiếp tục rà soát để chắc chắn bản dịch tự nhiên.

Phần còn lại cần làm: dịch từng workspace (Inbox, đơn hàng, ticket, báo cáo, cài đặt, admin), thông báo/lỗi từ API và nội dung trợ lý; chuyển định dạng ngày/tiền khỏi `vi-VN` cố định; quyết định lưu ngôn ngữ theo tài khoản hay theo trình duyệt. Hiện dữ liệu/nhãn nghiệp vụ và phần chưa có bản dịch vẫn hiển thị tiếng Việt. Vì vậy **chưa thể coi giao diện English đã hoàn tất**.

## Phần chưa hoàn thiện hoặc chưa được xác nhận

1. **Shopee — chưa sẵn sàng dùng thật.** Frontend chủ động hiện “ĐANG HOÀN THIỆN”. Backend hiện mới nhận JSON, chuẩn hóa và trả `received`; chưa thấy xác thực chữ ký, định tuyến tenant, lưu/dispatch hội thoại hay luồng gửi trả lời trong handler Shopee. Cần hoàn tất webhook Open Platform, idempotency, map sự kiện, gửi chat và test với shop/app thật trước khi bật nút kết nối.
2. **Các kết nối provider cần staging thật.** Callback public Facebook/Instagram đã kiểm tra qua ngrok: challenge hợp lệ trả 200 chính xác, token sai trả 403; POST không ký của Facebook/Instagram/Telegram/Zalo/TikTok bị 401 ở local. Token/API đã lưu trước đó phản hồi tốt cho Facebook, Instagram, Telegram và Zalo Bot Creator; Zalo OA chưa xác minh độc lập bằng profile ID đã lưu. Đây là kiểm tra token đang cấu hình, không phải đăng nhập lại OAuth bằng tài khoản thật. TikTok bridge để ngoài phạm vi theo yêu cầu.
3. **Release gates còn thủ công.** Backup/restore đã diễn tập trên ba database (`crm_chatbot`, `crm_platform`, `crm_tenant`) và so sánh số dòng; sửa cấu hình shared memory cho PostgreSQL để restore index pgvector thành công. Backup drill nằm tại `backups/restore-drill-20260926-172324`. Migration tenant 0007 đã chạy trên cả 4 shop đang hoạt động; đây là migration bổ sung cột nullable, không xóa dữ liệu. Lệnh khởi động Docker dev tự nâng cấp schema khi restart. Rate limit production, secret manager, OTP provider thật và ma trận smoke test P0 vẫn cần xác nhận trước production.
4. **i18n mới phủ shell/auth.** Các màn nghiệp vụ còn nhiều chuỗi hardcode và định dạng tiền/ngày tiếng Việt; cần triển khai lần lượt theo module, ưu tiên Inbox → đơn hàng → ticket → báo cáo → cài đặt/admin.
5. **Các cải tiến sản phẩm tiếp theo:** saved views và gắn nhãn hàng loạt trong Inbox; bảng điều hành backlog/SLA/lead nóng; correlation/audit xuyên inbound → bot → đơn. Giao việc hàng loạt đã có, giới hạn 100 hội thoại mỗi lượt, kiểm tra tenant và audit từng thay đổi.

### Ý tưởng tạo khác biệt (chưa triển khai)

**“Việc nên làm tiếp theo” trong Customer 360:** gợi ý nhân viên ưu tiên trả lời hội thoại quá hạn, gọi lại lead nóng, kiểm tra đơn giao chậm hoặc chăm sóc khách cũ. Mỗi gợi ý phải nêu dữ kiện dẫn đến nó, cho phép bỏ qua/ghi nhận kết quả, và yêu cầu nhân viên xác nhận trước khi gửi tin hay đổi trạng thái. Tận dụng timeline, lead, đơn hàng và SLA sẵn có; không tự động nhắn khách.

## Thứ tự đề xuất

| Ưu tiên | Việc | Điều kiện xong |
|---|---|---|
| P0 | Rà soát bản dịch API và nhãn dữ liệu nghiệp vụ | Chuyển Việt/Anh tự nhiên, không còn thông báo nghiệp vụ bị trộn ngôn ngữ |
| P0 | Hoàn thiện Shopee trước khi quảng bá kết nối | Chữ ký + tenant routing + idempotency + lưu/hiển thị tin + gửi trả lời + kiểm thử tài khoản thật |
| P0 | Chạy staging/release checklist | Có bằng chứng migration/restore, secret/rate-limit, OTP và smoke test đa kênh |
| P1 | Bulk tag và bảng điều hành chăm sóc | Có quyền hạn, xác nhận thao tác, audit và test tenant isolation; saved views và bulk assignment đã hoàn thành |
| P1 | Theo dõi hành trình sự kiện đầu-cuối | Tra được một inbound đến reply/ticket/order bằng correlation id mà không lộ dữ liệu nhạy cảm |

## Kiểm tra đã chạy

- Frontend hiện tại: `npm test` — **172 passed**; `npm run build` — **thành công** (còn cảnh báo bundle JavaScript lớn hơn 500 kB).
- Backend regression liên quan kết quả hội thoại: **25 passed, 1 skipped**; lần chạy toàn bộ trước đó đạt **637 passed, 2 skipped**.
- Callback Facebook/Instagram đã test qua Internet. Không gửi thử email ra khách thật; chưa chạy lại OAuth tương tác.
