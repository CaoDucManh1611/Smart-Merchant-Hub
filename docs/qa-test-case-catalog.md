# Bộ test case tổng hợp — Smart Merchant Hub

- Phiên bản: 2026-10-21
- Phạm vi: CRM đa shop, hộp thư đa kênh, Customer 360, bán hàng, RAG/RFM, quản trị nền tảng, thanh toán, backup và tích hợp mạng xã hội.

## 1. Cách sử dụng

- `P0`: lỗi làm mất dữ liệu, lộ dữ liệu shop khác, sai tiền, không nhận/gửi được tin hoặc không khôi phục được hệ thống.
- `P1`: chức năng chính sai nhưng có thể xử lý thủ công.
- `P2`: giao diện, tiện dụng hoặc trường hợp biên ít gặp.
- Loại `A`: nên tự động hóa; `M`: kiểm thử thủ công; `I`: cần tài khoản/sandbox thật của nền tảng.
- Mỗi lần chạy ghi: môi trường, build/commit, người chạy, thời gian, dữ liệu test, kết quả thực tế, ảnh/log và mã lỗi.

Mẫu ghi kết quả:

| Trường | Nội dung |
|---|---|
| Mã test | Ví dụ `INB-001` |
| Build | Commit hoặc image tag |
| Dữ liệu | Shop, tài khoản, kênh, conversation ID |
| Kết quả | Pass / Fail / Blocked |
| Bằng chứng | Ảnh, request/response, log, DB query |
| Lỗi liên quan | Issue ID và mức nghiêm trọng |

## 2. Ma trận nguồn tham khảo

Các nguồn dưới đây được dùng để rút ra hành vi cần kiểm thử, sau đó điều chỉnh theo chức năng thật của Smart Merchant Hub.

| Nguồn | Hành vi tham khảo |
|---|---|
| [HubSpot Conversations Inbox](https://knowledge.hubspot.com/inbox/use-the-conversations-inbox) | Lọc theo trạng thái/kênh/người phụ trách, hộp thư chưa phân công, đóng/mở lại, spam/thùng rác |
| [HubSpot Help Desk](https://knowledge.hubspot.com/help-desk/overview-of-the-help-desk-workspace) | Omnichannel, ticket pipeline, SLA, routing, lịch sử, chuyển người xử lý |
| [Intercom permissions](https://www.intercom.com/help/en/articles/176-teammate-permissions-how-to-control-workspace-access) | Quyền xem hội thoại, tự nhận, chuyển giao, quản lý đội nhóm, export/import |
| [Intercom assignment](https://www.intercom.com/help/en/articles/6561699-assign-conversations-to-teammates-and-teams) | Gán người/nhóm, unassigned, tự động định tuyến, giới hạn quyền chuyển giao |
| [Zendesk Agent Workspace](https://support.zendesk.com/hc/en-us/articles/4408843683226-Receiving-and-sending-messages-in-the-Zendesk-Agent-Workspace) | Nhận/gửi social message, timeout kênh, transfer, online capacity |
| [Meta Messenger API](https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api) | Gửi text/media, PSID, quyền, cửa sổ nhắn tin, lỗi token |
| [Meta Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api) | Instagram Professional, DM, attachment, webhook và quyền truy cập |
| [Telegram Bot API](https://core.telegram.org/bots/api) | Webhook secret, text/photo/audio/sticker, file ID/URL/upload, giới hạn file |
| [TikTok Webhooks](https://developers.tiktok.com/doc/webhooks-overview) | HTTPS callback, phản hồi 200, retry tối đa 72 giờ, at-least-once và idempotency |
| [OWASP API Security Top 10](https://api-security.owasp.org/editions/2023/en/0x03-introduction/) | BOLA/BFLA, auth, resource consumption, SSRF, unsafe third-party APIs |
| [OWASP LLM risks](https://genai.owasp.org/llm-top-10/) | Prompt injection, rò rỉ dữ liệu, poisoning, unsafe output, excessive agency |
| [WCAG 2.2 Quick Reference](https://www.w3.org/WAI/WCAG22/quickref/) | Keyboard, focus, contrast, lỗi biểu mẫu, status message |
| [Gemini Embeddings](https://ai.google.dev/api/embeddings) | Retrieval query/document, kích thước vector, title và task type |
| [PostgreSQL backup/restore](https://www.postgresql.org/docs/17/backup.html) | Dump, restore, quyền sở hữu, backup định kỳ và kiểm chứng khôi phục |

## 3. Xác thực, tài khoản và phiên đăng nhập

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| AUTH-001 | P0 | A | Đăng nhập bằng email/mật khẩu hợp lệ | Tạo phiên đúng shop, chuyển vào CRM |
| AUTH-002 | P0 | A | Sai mật khẩu | 401, thông báo chung, không lộ email tồn tại |
| AUTH-003 | P0 | A | Email không tồn tại | Không tạo phiên hoặc gửi reset |
| AUTH-004 | P1 | A | Email khác hoa/thường và có khoảng trắng | Chuẩn hóa nhất quán |
| AUTH-005 | P0 | A | Brute force vượt ngưỡng | Rate limit/khóa tạm đúng cấu hình |
| AUTH-006 | P0 | A | Token hết hạn | 401 và chuyển về đăng nhập |
| AUTH-007 | P0 | A | Token bị sửa chữ ký | Bị từ chối, không đọc dữ liệu |
| AUTH-008 | P0 | A | Đăng xuất | Token/phiên không dùng lại được |
| AUTH-009 | P1 | A | Đổi mật khẩu | Mật khẩu cũ mất hiệu lực; mật khẩu mới hoạt động |
| AUTH-010 | P1 | A | Mật khẩu dưới 12 ký tự/yếu | Hiển thị yêu cầu cụ thể và không lưu |
| AUTH-011 | P0 | A | Quên mật khẩu với email đúng hệ thống | Chỉ gửi OTP/link cho đúng email |
| AUTH-012 | P0 | A | Quên mật khẩu với email không tồn tại | Không gửi email; phản hồi không dò được tài khoản |
| AUTH-013 | P0 | A | OTP đúng, sai, hết hạn, dùng lại | Chỉ OTP đúng và chưa dùng được chấp nhận |
| AUTH-014 | P0 | A | OTP bị thử nhiều lần | Rate limit và ghi audit |
| AUTH-015 | P1 | A | Thay đổi email người dùng | Xác minh email mới trước khi cập nhật |
| AUTH-016 | P0 | A | Tài khoản bị vô hiệu hóa đang có phiên | Phiên bị chặn ở request kế tiếp |
| AUTH-017 | P0 | M | Hai tab cùng đăng nhập, một tab logout | Hành vi phiên nhất quán theo chính sách |
| AUTH-018 | P1 | A | Redirect URL độc hại sau login | Chỉ cho URL nội bộ/allowlist |

## 4. Đa shop, phân quyền và quản trị nội bộ

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| RBAC-001 | P0 | A | Nhân viên shop A gọi API khách shop B bằng ID | 403/404, không lộ dữ liệu |
| RBAC-002 | P0 | A | Đổi `business_id` trong body/query/header | Tenant lấy từ phiên tin cậy, không từ input |
| RBAC-003 | P0 | A | Admin nền tảng truy cập màn quản trị | Được phép theo đúng role |
| RBAC-004 | P0 | A | Nhân viên shop truy cập API admin nền tảng | 403 |
| RBAC-005 | P0 | A | Nhân viên thiếu quyền trả lời hội thoại | UI ẩn/vô hiệu và API từ chối |
| RBAC-006 | P0 | A | Nhân viên chỉ xem hội thoại được giao | Hội thoại ngoài phạm vi bị ẩn/redact |
| RBAC-007 | P1 | A | Quyền tự nhận hội thoại bị tắt | Không thể tự gán bằng UI lẫn API |
| RBAC-008 | P1 | A | Quyền chuyển hội thoại bị tắt | Không thể chuyển người/nhóm khác |
| RBAC-009 | P0 | A | Quyền backup/restore | Chỉ role được cấp mới xem/tạo/restore |
| RBAC-010 | P0 | A | Quyền quản lý đội ngũ | Chỉ role quản trị được thêm/sửa/khóa tài khoản |
| RBAC-011 | P1 | A | Thay role khi người dùng đang đăng nhập | Quyền mới có hiệu lực ngay hoặc theo chính sách rõ ràng |
| RBAC-012 | P0 | A | Tự xóa/khóa admin cuối cùng | Bị chặn để tránh mất quyền quản trị |
| RBAC-013 | P0 | A | Admin tự khóa chính mình | Bị chặn hoặc yêu cầu admin khác |
| RBAC-014 | P1 | A | Nhân viên bị xóa đang phụ trách hội thoại | Hội thoại chuyển unassigned/nhóm mặc định |
| RBAC-015 | P0 | A | API export khách hàng | Chỉ role có quyền; dữ liệu đúng tenant |
| RBAC-016 | P0 | A | Audit log thao tác nhạy cảm | Ghi actor, thời gian, shop, action và target |
| RBAC-017 | P0 | A | Giả mạo `X-Tenant-ID` legacy | Không override tenant đã xác thực |
| RBAC-018 | P0 | A | Worker xử lý job của nhiều shop | Mỗi job mở đúng schema tenant |

## 5. Hộp thư đa kênh và realtime

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| INB-001 | P0 | A | Tin mới đến khi đang mở inbox | Hiện realtime, không cần F5 |
| INB-002 | P0 | A | Tin mới đến đúng hội thoại đang mở | Append cuối, không nhân đôi |
| INB-003 | P1 | M | Poll/reconnect làm mới dữ liệu | Không cuộn lên đầu; giữ vị trí hợp lý |
| INB-004 | P1 | M | Mở hội thoại lần đầu | Focus vào tin mới nhất/chưa đọc gần nhất |
| INB-005 | P0 | A | Lịch sử và realtime chạy đồng thời | Không mất, đảo hoặc trùng tin |
| INB-006 | P0 | A | Cùng khách bị detect thành hai hội thoại | Gộp theo external identity/channel account đúng |
| INB-007 | P0 | A | Hai người trùng tên/avatar | Không gộp nếu external ID khác |
| INB-008 | P0 | A | Một webhook gửi lại hai lần | Idempotent theo external message/event ID |
| INB-009 | P0 | A | Event đến sai thứ tự | Timeline sắp theo provider timestamp và tie-break ổn định |
| INB-010 | P1 | A | Tin không có timestamp | Dùng received_at, không lặp vô hạn |
| INB-011 | P1 | A | Đánh dấu đã đọc | Badge và số chưa đọc cập nhật nhất quán |
| INB-012 | P1 | A | Tin mới đến hội thoại khác | Preview, thời gian và thứ tự danh sách cập nhật |
| INB-013 | P1 | A | Lọc theo kênh/trạng thái/người phụ trách | Chỉ đúng hội thoại thỏa điều kiện |
| INB-014 | P1 | A | Tìm theo tên, nội dung, SĐT, email | Kết quả đúng tenant và có phân trang |
| INB-015 | P1 | A | Đóng hội thoại rồi khách nhắn lại | Mở lại theo quy tắc và giữ lịch sử |
| INB-016 | P1 | A | Gán/chuyển nhân viên | Cập nhật realtime và ghi timeline |
| INB-017 | P1 | A | Ghi chú nội bộ | Không gửi ra kênh khách hàng |
| INB-018 | P1 | A | Trả lời mẫu | Nội dung đúng, placeholder được thay, không gửi rỗng |
| INB-019 | P0 | A | Nhấn gửi liên tục/double click | Chỉ một outbound message |
| INB-020 | P0 | A | Provider timeout sau khi nhận request | Trạng thái `unknown/pending`, không tự gửi trùng |
| INB-021 | P1 | A | Provider trả lỗi | Hiện trạng thái failed và cho retry an toàn |
| INB-022 | P1 | M | Danh sách 10.000 hội thoại | Cuộn/lọc ổn định, không freeze UI |
| INB-023 | P1 | A | Pagination có tin mới chen vào | Không bỏ sót hoặc trả trùng page |
| INB-024 | P2 | M | Dark/light mode inbox | Màu, badge, icon và trạng thái dễ đọc |

## 6. Tích hợp Facebook và Instagram

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| META-001 | P0 | I | Kết nối Facebook Page hợp lệ | Lưu route/token mã hóa, trạng thái connected |
| META-002 | P0 | I | Kết nối Instagram Professional hợp lệ | Nhận đúng account/page mapping |
| META-003 | P0 | A | Verify token webhook đúng/sai | Đúng trả challenge; sai bị từ chối |
| META-004 | P0 | A | Chữ ký webhook hợp lệ/không hợp lệ | Chỉ payload hợp lệ được xử lý |
| META-005 | P0 | A | Webhook text Messenger | Tạo đúng customer/conversation/message |
| META-006 | P0 | A | Webhook text Instagram | Tạo đúng identity Instagram, không thành Facebook |
| META-007 | P0 | I | Gửi text từ CRM ra Messenger | Provider message ID được lưu |
| META-008 | P0 | I | Gửi text từ CRM ra Instagram | Đúng recipient scoped ID và account |
| META-009 | P0 | I | Gửi ảnh bằng upload/public media URL | Ảnh đến khách và CRM lưu attachment |
| META-010 | P1 | I | Nhận ảnh/GIF/video/audio/sticker | Render đúng loại hoặc fallback có nghĩa |
| META-011 | P1 | A | Tin hệ thống “dùng ứng dụng mới nhất” | Không coi là nội dung khách cần bot trả lời |
| META-012 | P0 | A | Token hết hạn/bị thu hồi | Chuyển trạng thái disconnected và cảnh báo rõ |
| META-013 | P0 | A | Page/account không khớp shop | Bị từ chối, không route sang tenant khác |
| META-014 | P0 | A | Hai shop kết nối cùng external account | Chặn trùng toàn cục |
| META-015 | P1 | I | Vượt cửa sổ nhắn tin/policy | Không gửi sai chính sách; báo lý do hành động được |
| META-016 | P1 | A | History import song song realtime | Không kích hoạt bot/workflow cho lịch sử |
| META-017 | P0 | A | Bridge restart giữa lúc import | Resume checkpoint, không nhập lại hàng loạt |
| META-018 | P0 | A | Browser/CDP disconnect | Tự reconnect có backoff, không mở tab vô hạn |
| META-019 | P1 | A | Không lấy được conversation ID | Log đủ context, retry có giới hạn |
| META-020 | P0 | I | Reply từ CRM | Tin xuất hiện ở Meta và trạng thái delivery cập nhật |

## 7. Telegram, Zalo, TikTok và Shopee

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| CHN-001 | P0 | A | Telegram webhook secret đúng/sai | Chỉ secret đúng được nhận |
| CHN-002 | P0 | I | Telegram text hai chiều | External IDs và delivery status đúng |
| CHN-003 | P1 | I | Telegram photo bằng file ID, URL, upload | Cả ba cách được xử lý đúng giới hạn |
| CHN-004 | P1 | I | Telegram audio/voice/sticker/document | Đúng endpoint/MIME và render |
| CHN-005 | P0 | A | Telegram update bị gửi lại | Không tạo tin trùng |
| CHN-006 | P0 | A | Zalo webhook secret/chữ ký OA | Sai bị 401; đúng được xử lý |
| CHN-007 | P0 | I | Zalo text hai chiều | Đúng OA/channel/customer |
| CHN-008 | P1 | I | Zalo ảnh/audio/sticker | Lưu attachment và gửi/nhận theo capability |
| CHN-009 | P1 | A | Zalo thiếu avatar/tên | Enrich profile hoặc fallback ổn định |
| CHN-010 | P0 | A | TikTok webhook trả lại event | Deduplicate theo at-least-once delivery |
| CHN-011 | P0 | A | TikTok endpoint không trả 200 | Job retry/backoff không tạo side effect trùng |
| CHN-012 | P0 | I | TikTok text hai chiều | Có bằng chứng message ID từ kênh |
| CHN-013 | P1 | I | TikTok media capability thật | UI chỉ bật loại provider hỗ trợ thực tế |
| CHN-014 | P0 | A | Shopee session/profile hết hạn | Trạng thái disconnected, không báo connected giả |
| CHN-015 | P0 | I | Shopee text hai chiều | Route đúng shop/conversation |
| CHN-016 | P1 | I | Shopee image/audio/sticker | Capability được kiểm chứng; lỗi có fallback rõ |
| CHN-017 | P0 | A | Connector restart | Không mất checkpoint hoặc chạy hai instance cùng account |
| CHN-018 | P1 | A | Rate limit provider | Queue lại theo Retry-After/backoff |
| CHN-019 | P1 | A | Provider payload thiếu trường tùy chọn | Không 500; lưu phần dữ liệu hợp lệ |
| CHN-020 | P0 | A | Provider payload chứa URL nội bộ | Chặn SSRF khi tải media |

## 8. Media và tệp đính kèm

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| MED-001 | P0 | A | Upload JPG/PNG hợp lệ | Lưu đúng MIME, size, checksum và tenant |
| MED-002 | P1 | A | Upload audio/video/document hợp lệ | Capability kiểm tra theo kênh |
| MED-003 | P0 | A | File giả phần mở rộng | Kiểm tra magic bytes/MIME; từ chối nếu nguy hiểm |
| MED-004 | P0 | A | File vượt giới hạn | 413/validation rõ, không lưu file dở |
| MED-005 | P0 | A | Tên file path traversal | Không thoát thư mục upload |
| MED-006 | P0 | A | SVG/HTML/script độc hại | Không thực thi inline; sanitize hoặc download an toàn |
| MED-007 | P0 | A | URL media localhost/private IP | Chặn SSRF và redirect nội bộ |
| MED-008 | P1 | A | URL media hết hạn | Hiện placeholder và có cơ chế refresh/proxy phù hợp |
| MED-009 | P0 | A | Shop A truy cập file shop B | 403/404 |
| MED-010 | P1 | A | Một message có nhiều attachment | Giữ đủ loại và thứ tự |
| MED-011 | P1 | M | Ảnh rất rộng/cao/EXIF rotation | Preview đúng, không vỡ layout |
| MED-012 | P1 | A | Upload bị ngắt giữa chừng | Không còn bản ghi/file mồ côi |
| MED-013 | P1 | A | Retry gửi cùng file | Không nhân đôi attachment local |
| MED-014 | P1 | A | Media provider trả 404/403 | Message vẫn tồn tại và báo media unavailable |

## 9. Customer 360, danh tính và gộp khách

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| CUS-001 | P0 | A | Tạo khách từ tin đầu tiên | Customer và identity được tạo một lần |
| CUS-002 | P0 | A | Tin tiếp theo cùng external ID | Dùng lại đúng customer |
| CUS-003 | P1 | A | Cập nhật tên/avatar | Không ghi đè dữ liệu tốt bằng placeholder rỗng |
| CUS-004 | P0 | A | Một khách có Facebook và Instagram | Link có bằng chứng, không tự gộp chỉ vì tên |
| CUS-005 | P0 | A | Hai khách cùng SĐT/email | Quy tắc duplicate có confidence và review |
| CUS-006 | P0 | A | Gộp hai khách | Chuyển đủ conversation/order/tag/fact/history |
| CUS-007 | P0 | A | Hoàn tác gộp | Phục hồi đúng ownership và không mất dữ liệu sau gộp |
| CUS-008 | P0 | A | Gộp chéo shop | Bị chặn |
| CUS-009 | P1 | A | Gộp đã có xung đột tên/SĐT | Giữ nguồn và lịch sử lựa chọn |
| CUS-010 | P1 | A | Tag thêm/xóa/lọc | Không trùng tag; filter đúng |
| CUS-011 | P1 | A | Fact extraction từ hội thoại | Có nguồn message và confidence |
| CUS-012 | P0 | A | Prompt độc hại yêu cầu sửa hồ sơ | Không tự ghi dữ liệu nhạy cảm trái phép |
| CUS-013 | P1 | A | Timeline đa kênh | Sắp đúng thời gian và loại sự kiện |
| CUS-014 | P1 | A | Import CSV khách hàng | Validate từng dòng; báo lỗi không làm mất dòng đúng |
| CUS-015 | P0 | A | Export/delete dữ liệu cá nhân | Đúng tenant, audit và chính sách retention |
| CUS-016 | P1 | M | Customer 360 không có dữ liệu | Empty state có hướng dẫn, không hiển thị logo thừa |

## 10. Sản phẩm, tồn kho, đơn hàng và thanh toán khách

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| COM-001 | P0 | A | Tạo/sửa/xóa mềm sản phẩm | Validation giá/tồn kho; lịch sử đúng |
| COM-002 | P0 | A | SKU trùng trong cùng shop | Bị chặn theo quy tắc |
| COM-003 | P0 | A | SKU giống nhau ở hai shop | Được phép và không lẫn dữ liệu |
| COM-004 | P1 | A | Nhập hàng | Tồn kho và ledger tăng đúng |
| COM-005 | P0 | A | Hai đơn mua sản phẩm cuối cùng đồng thời | Không âm kho/double sell |
| COM-006 | P0 | A | Tạo đơn từ hội thoại | Liên kết đúng customer/conversation/items |
| COM-007 | P0 | A | Giá thay đổi sau khi tạo đơn | Đơn giữ snapshot giá |
| COM-008 | P0 | A | Giảm giá/phí ship/thuế | Tổng tiền và làm tròn chính xác |
| COM-009 | P0 | A | Chuyển trạng thái đơn hợp lệ | Chỉ transition được cho phép |
| COM-010 | P0 | A | Hủy đơn | Hoàn kho/ledger đúng và idempotent |
| COM-011 | P1 | A | Ghép đơn với khách/hội thoại | Không ghép theo tên mơ hồ |
| COM-012 | P0 | A | VietQR tạo amount/addInfo/account | Dữ liệu khớp đơn và được encode đúng |
| COM-013 | P0 | A | Webhook thanh toán gửi lặp | Chỉ ghi nhận tiền một lần |
| COM-014 | P0 | A | Số tiền nhận thiếu/thừa | Không tự xác nhận sai; tạo cảnh báo |
| COM-015 | P0 | A | Mã giao dịch trùng | Không cộng tiền hai lần |
| COM-016 | P1 | A | Xác nhận thủ công ở yêu cầu chờ duyệt | Đúng đơn, actor, thời gian và mã giao dịch |
| COM-017 | P1 | A | Lịch sử thanh toán trong shop | Chỉ đọc, sắp mới nhất, không chứa form duyệt |
| COM-018 | P1 | I | Gửi hóa đơn/QR ra từng kênh | Dùng media nếu hỗ trợ, fallback text đúng |

## 11. RFM, sở thích và gợi ý sản phẩm

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| REC-001 | P0 | A | RFM với khách chưa mua | Segment mặc định hợp lý, không chia cho 0 |
| REC-002 | P0 | A | Recency theo timezone | Số ngày đúng mốc UTC+7 |
| REC-003 | P0 | A | Frequency loại đơn hủy/hoàn | Chỉ tính trạng thái theo quy tắc |
| REC-004 | P0 | A | Monetary với hoàn tiền/giảm giá | Giá trị ròng chính xác |
| REC-005 | P1 | A | Hai khách bằng điểm | Tie-break ổn định |
| REC-006 | P1 | A | Recompute hàng loạt | Idempotent, không tạo snapshot trùng |
| REC-007 | P0 | A | Sở thích theo sản phẩm nhập tay | Tăng đúng trọng số sản phẩm/nhóm |
| REC-008 | P1 | A | Tương tác cũ giảm trọng số | Decay đúng cấu hình |
| REC-009 | P0 | A | Sản phẩm hết hàng/ngừng bán | Không được đề xuất để mua |
| REC-010 | P1 | A | Khách mới cold start | Dùng popular/context, không trả rỗng vô lý |
| REC-011 | P1 | A | Diversity | Không chỉ trả biến thể cùng một sản phẩm |
| REC-012 | P0 | A | Tenant isolation recommendation | Không dùng hành vi/sản phẩm shop khác |
| REC-013 | P1 | A | Giải thích đề xuất | Lý do dựa trên tín hiệu thật, không bịa |
| REC-014 | P1 | A | Đo hit-rate/MRR/NDCG offline | Metric tái lập được trên cùng dataset |
| REC-015 | P1 | A | A/B ranking | Assignment ổn định và outcome attribution đúng |
| REC-016 | P1 | A | Dữ liệu cực trị | Không overflow, NaN hoặc bias do một đơn rất lớn |

## 12. Kho tri thức, hybrid RAG và chatbot

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| RAG-001 | P0 | A | Upload PDF/DOCX/TXT/MD hợp lệ | Parse, chunk, index và trạng thái rõ |
| RAG-002 | P0 | A | File vượt 10 MB/không hỗ trợ | Từ chối trước khi index |
| RAG-003 | P0 | A | Tài liệu shop A truy vấn từ shop B | Không có kết quả |
| RAG-004 | P1 | A | Chunk giữ tiêu đề/ngữ cảnh | Citation trỏ đúng đoạn nguồn |
| RAG-005 | P0 | A | Gemini embedding document/query task | Dùng cấu hình đúng vai trò retrieval |
| RAG-006 | P1 | A | Embedding API lỗi/tạm nghẽn | Retry/fallback; không đánh dấu indexed giả |
| RAG-007 | P1 | A | BM25 bắt mã SKU/tên riêng | Kết quả lexical được giữ trong candidate set |
| RAG-008 | P1 | A | Vector bắt câu đồng nghĩa | Semantic candidate phù hợp |
| RAG-009 | P1 | A | RRF hợp nhất BM25/vector | Không phụ thuộc thang điểm riêng của retriever |
| RAG-010 | P1 | A | PPR cá nhân hóa theo khách | Boost đúng sở thích nhưng không loại bằng chứng mạnh |
| RAG-011 | P0 | A | Câu hỏi không đủ bằng chứng | Trả no-context/handoff, không bịa |
| RAG-012 | P0 | A | Citation sai tài liệu/đoạn | Answer guard loại hoặc yêu cầu tạo lại |
| RAG-013 | P0 | A | Prompt injection trực tiếp | Không tiết lộ system prompt/secrets hoặc đổi quyền |
| RAG-014 | P0 | A | Prompt injection nằm trong tài liệu | Xem là dữ liệu, không làm theo chỉ dẫn độc hại |
| RAG-015 | P0 | A | Tài liệu chứa dữ liệu nhạy cảm | Không trả cho role/tenant không có quyền |
| RAG-016 | P1 | A | Groq lỗi | Chuyển Gemini fallback đúng model pool |
| RAG-017 | P1 | A | Một model Gemini nghẽn/quota | Xoay key/model có giới hạn và quan sát được |
| RAG-018 | P0 | A | Tất cả provider lỗi | Handoff an toàn, không ghi câu trả lời rỗng là thành công |
| RAG-019 | P1 | A | Cache cùng câu hỏi/cùng knowledge version | Hit cache; citation vẫn hợp lệ |
| RAG-020 | P0 | A | Tài liệu được sửa/xóa | Cache/index cũ bị vô hiệu hóa |
| RAG-021 | P1 | A | Câu hỏi tiếng Việt không dấu/sai chính tả | Retrieval vẫn tìm được tài liệu phù hợp |
| RAG-022 | P1 | A | Câu hỏi nhiều ý | Trả đủ phần có bằng chứng, nêu phần thiếu |
| RAG-023 | P1 | A | Đo Recall@K, MRR, groundedness, citation precision | Metric được lưu theo run/model/config |
| RAG-024 | P1 | A | So sánh baseline với BM25→RRF→PPR | Có dataset cố định và báo cáo regression |

## 13. Ticket, SLA, workflow và thông báo

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| OPS-001 | P1 | A | Tạo ticket từ hội thoại | Liên kết đúng khách/kênh/người phụ trách |
| OPS-002 | P1 | A | Cập nhật priority/status | Chỉ transition hợp lệ và ghi lịch sử |
| OPS-003 | P1 | A | First response SLA | Bắt đầu/dừng đúng sự kiện |
| OPS-004 | P1 | A | Resolution SLA | Pause/resume theo trạng thái đúng |
| OPS-005 | P1 | A | Ngoài giờ làm việc/ngày nghỉ | Thời gian SLA loại trừ đúng |
| OPS-006 | P1 | A | Ticket reopen | Mốc reopen và SLA theo chính sách |
| OPS-007 | P1 | A | Giao cho nhân viên offline | Route unassigned/nhóm fallback |
| OPS-008 | P1 | A | Capacity đạt giới hạn | Không giao thêm; tránh starvation |
| OPS-009 | P1 | A | Workflow điều kiện nhiều nhánh | Chỉ nhánh đúng chạy một lần |
| OPS-010 | P0 | A | Workflow retry sau lỗi | Side effect idempotent |
| OPS-011 | P1 | A | Nhắc việc/notification | Đúng người, tenant, deep link và trạng thái đọc |
| OPS-012 | P1 | A | Đóng ticket khi còn job pending | Xử lý theo rule; không mất job |
| OPS-013 | P1 | A | Yêu cầu hỗ trợ shop gửi admin | Admin thấy đúng trạng thái và nội dung |
| OPS-014 | P1 | A | Admin phản hồi/đóng yêu cầu | Shop nhận realtime và xem lịch sử |

## 14. Gói dịch vụ, quota và thanh toán nền tảng

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| SUB-001 | P0 | A | Đăng ký gói mới | Tạo pending request, chưa cấp quyền trước duyệt |
| SUB-002 | P0 | A | Admin xác nhận đúng mã giao dịch | Kích hoạt đúng shop/gói/chu kỳ |
| SUB-003 | P0 | A | Dùng lại mã giao dịch | Không cộng tiền/kích hoạt lần hai |
| SUB-004 | P0 | A | Upgrade/downgrade | Proration/quyền/quota theo chính sách |
| SUB-005 | P0 | A | Gói hết hạn | Chặn tính năng vượt gói nhưng giữ dữ liệu |
| SUB-006 | P1 | A | Gia hạn | Ngày hết hạn tăng từ mốc đúng |
| SUB-007 | P0 | A | Quota kênh 6/6 | Kết nối thứ 7 bị chặn nhất quán UI/API |
| SUB-008 | P1 | A | Kênh đã dùng vs đang hoạt động | Đếm đúng định nghĩa và trạng thái thực |
| SUB-009 | P0 | A | Ngắt một kênh | Giải phóng quota theo chính sách |
| SUB-010 | P0 | A | Hai request đồng thời dùng slot cuối | Chỉ một request thành công |
| SUB-011 | P1 | A | Quota tài liệu/tra cứu | Ledger chính xác, reset đúng chu kỳ |
| SUB-012 | P0 | A | Giá gói sửa sau hóa đơn | Hóa đơn giữ snapshot giá |
| SUB-013 | P1 | A | Chatbot tư vấn gói | Chỉ dựa catalog/tài liệu admin đã bật |
| SUB-014 | P0 | A | Nhân viên admin thiếu quyền sửa gói | 403 và audit |

## 15. Backup, restore, migration và PostgreSQL

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| DB-001 | P0 | A | Tạo backup đầy đủ | Archive có DB, uploads, manifest, checksum |
| DB-002 | P0 | A | Backup không chứa `.env`/secret thô | Secret không nằm trong archive |
| DB-003 | P0 | A | Verify checksum đúng/sai | Nhận diện archive hỏng trước restore |
| DB-004 | P0 | A | Dry-run restore vào DB tạm | Migrations/schema/data kiểm chứng được |
| DB-005 | P0 | M | Restore thật từ backup đã verify | Dữ liệu và file trở về đúng snapshot |
| DB-006 | P0 | A | Archive do hệ thống khác tạo | Bị từ chối theo manifest/signature |
| DB-007 | P0 | A | Restore path traversal archive | Không ghi file ngoài workspace |
| DB-008 | P0 | A | Restore thiếu role/owner | Báo lỗi hành động được hoặc remap an toàn |
| DB-009 | P0 | A | Restore thất bại giữa chừng | Không để hệ thống nửa cũ nửa mới |
| DB-010 | P1 | A | Retention backup | Chỉ xóa bản quá hạn; giữ tối thiểu theo policy |
| DB-011 | P0 | A | Alembic upgrade từ baseline | Tạo schema đầy đủ không lỗi |
| DB-012 | P0 | A | Upgrade từ bản production gần nhất | Không mất dữ liệu và backfill đúng |
| DB-013 | P0 | A | Migration chạy lại | Idempotent hoặc fail rõ, không nhân dữ liệu |
| DB-014 | P0 | A | Tenant provision mới | Platform registry và tenant schema nhất quán |
| DB-015 | P0 | A | Provision lỗi sau bước giữa | Rollback/state `failed`, retry được |
| DB-016 | P0 | A | Pool connection cạn | Backpressure, đóng connection, không treo app |
| DB-017 | P0 | A | Transaction deadlock | Retry có giới hạn và không double side effect |
| DB-018 | P1 | A | Test suite PostgreSQL | Chạy trên `*_test`, schema tạm được dọn sạch |

## 16. API, webhook và bảo mật ứng dụng

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| SEC-001 | P0 | A | BOLA đổi customer/order/message ID | Không đọc/sửa object shop khác |
| SEC-002 | P0 | A | BFLA gọi endpoint admin bằng user thường | 403 |
| SEC-003 | P0 | A | Mass assignment role/business/status | Field nhạy cảm bị bỏ hoặc từ chối |
| SEC-004 | P0 | A | SQL injection ở search/filter/sort | Parameterized; không lỗi/lộ DB |
| SEC-005 | P0 | A | Stored/reflected XSS trong tên/tin nhắn | Render text an toàn |
| SEC-006 | P0 | A | CSRF với action dùng cookie | Token/SameSite/origin protection |
| SEC-007 | P0 | A | CORS từ origin lạ | Không cấp credential/access |
| SEC-008 | P0 | A | Webhook body quá lớn | 413 trước parse sâu |
| SEC-009 | P0 | A | JSON lồng sâu/zip bomb | Giới hạn tài nguyên |
| SEC-010 | P0 | A | SSRF media/webhook callback | Chặn localhost, metadata IP, private ranges và redirect |
| SEC-011 | P0 | A | Secret xuất hiện trong API/log | Redact token, password, encryption key |
| SEC-012 | P0 | A | Token/channel credential trong DB | Được mã hóa và rotate được |
| SEC-013 | P0 | A | Replay webhook cũ | Timestamp/ID/idempotency ngăn side effect trùng |
| SEC-014 | P1 | A | Rate limit theo user/IP/shop | Không để một shop làm nghẽn toàn hệ thống |
| SEC-015 | P0 | A | Header spoofing proxy | Chỉ tin trusted proxy headers |
| SEC-016 | P0 | A | Error 500 | Không trả stack trace/path/SQL/secrets |
| SEC-017 | P0 | A | Dependency/provider response độc hại | Validate schema trước khi dùng |
| SEC-018 | P0 | A | Export formula injection CSV | Escape ô bắt đầu `=`, `+`, `-`, `@` |

## 17. UI/UX, accessibility và responsive

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| UI-001 | P1 | M | Dark/light trước và sau login | Cùng design tokens, không nháy sai theme |
| UI-002 | P1 | M | Refresh trang sâu | Giữ route/theme/auth state |
| UI-003 | P1 | M | Sidebar dài màn hình thấp | Scroll được, mục cuối truy cập được |
| UI-004 | P1 | M | Modal/dropdown mở gần mép | Không bị cắt hoặc khóa scroll toàn trang |
| UI-005 | P1 | M | 1366×768, 1920×1080, mobile/tablet | Không tràn ngang ngoài vùng có chủ đích |
| UI-006 | P1 | M | Zoom 200% | Nội dung reflow, thao tác vẫn dùng được |
| UI-007 | P1 | M | Chỉ dùng bàn phím | Tất cả control thao tác được, không keyboard trap |
| UI-008 | P1 | M | Focus indicator | Luôn thấy rõ và có tương phản |
| UI-009 | P1 | M | Contrast text/icon/control | Đạt WCAG AA mục tiêu |
| UI-010 | P1 | M | Lỗi form | Có text chỉ rõ field/lý do/cách sửa, không chỉ đổi màu |
| UI-011 | P1 | M | Loading/success/error realtime | Có `status/alert`, screen reader nhận biết |
| UI-012 | P1 | M | Checkbox nền tảng | Click cả hàng/nhãn đều toggle đúng |
| UI-013 | P1 | M | Tên nền tảng | Viết hoa chuẩn: Facebook, Instagram, Telegram, Zalo, TikTok, Shopee |
| UI-014 | P1 | M | Icon kênh trên dark/light | Đúng brand, nền/viền rõ, không fallback nhầm |
| UI-015 | P2 | M | Typography toàn hệ thống | Cỡ/chữ/line-height nhất quán, không font giả italic |
| UI-016 | P1 | M | Empty state và unavailable state | Phân biệt chưa có dữ liệu, chưa kết nối và tải lỗi |
| UI-017 | P1 | M | Nút destructive | Có xác nhận và mô tả ảnh hưởng |
| UI-018 | P1 | M | Vietnamese/English | Không vỡ layout, không còn key i18n thô |

## 18. Hiệu năng, độ bền và quan sát hệ thống

| ID | P | Loại | Test case | Kết quả mong đợi |
|---|---:|---|---|---|
| NFR-001 | P1 | A | 100 user đồng thời đọc inbox | p95 và error rate trong SLO |
| NFR-002 | P0 | A | Burst 1.000 webhook/phút | Không mất event; queue/backpressure hoạt động |
| NFR-003 | P0 | A | Provider chậm 30 giây | Request worker không bị chiếm vô hạn |
| NFR-004 | P0 | A | Worker chết giữa job | Job được lease lại, side effect không trùng |
| NFR-005 | P0 | A | PostgreSQL restart ngắn | App phục hồi pool và báo degraded đúng |
| NFR-006 | P1 | A | Redis unavailable | Fallback hoặc fail rõ theo chức năng |
| NFR-007 | P1 | A | LLM provider nghẽn | Circuit breaker/model rotation và timeout |
| NFR-008 | P1 | A | 10.000 sản phẩm search | p95 mục tiêu, không full-table scan ngoài ý muốn |
| NFR-009 | P1 | A | 100.000 message một tenant | Pagination/index ổn định |
| NFR-010 | P1 | A | RAG corpus lớn | Retrieval latency và Recall@K đạt ngưỡng |
| NFR-011 | P0 | A | Log correlation | Request/event/job có correlation ID xuyên suốt |
| NFR-012 | P0 | A | Health/readiness khi DB/provider lỗi | Phản ánh đúng dependency bắt buộc/tùy chọn |
| NFR-013 | P1 | A | Alert webhook failure rate | Cảnh báo có shop/provider/context, không chứa secret |
| NFR-014 | P1 | A | Metrics tenant cardinality | Không tạo label cardinality vô hạn |
| NFR-015 | P1 | A | Restart connector nhiều lần | Chỉ một consumer active cho account |
| NFR-016 | P0 | A | Disk đầy khi upload/backup | Fail an toàn và cleanup file tạm |

## 19. Smoke suite bắt buộc trước khi demo/deploy

Chạy tối thiểu các case sau trên môi trường gần production:

1. `AUTH-001`, `AUTH-002`, `AUTH-011`, `AUTH-012`.
2. `RBAC-001`, `RBAC-004`, `RBAC-009`.
3. `INB-001`, `INB-005`, `INB-008`, `INB-019`.
4. `META-005`, `META-006`, `META-007`, `META-009` với sandbox/account thật nếu có.
5. `CHN-001`, `CHN-002` và ít nhất một test thật cho mỗi connector đang bật.
6. `CUS-006`, `CUS-007`, `COM-005`, `COM-013`.
7. `RAG-003`, `RAG-011`, `RAG-012`, `RAG-013`, `RAG-018`.
8. `DB-001`, `DB-003`, `DB-004`, `DB-011`.
9. `SEC-001`, `SEC-010`, `SEC-011`, `SEC-016`.
10. `UI-003`, `UI-007`, `UI-009`, `UI-016`.

## 20. Điều kiện hoàn thành kiểm thử

- 100% `P0` đã chạy và pass; không còn lỗi Critical/High chưa có chấp thuận rủi ro.
- Ít nhất 95% `P1` pass; case blocked phải ghi rõ dependency/tài khoản sandbox còn thiếu.
- Full backend suite PostgreSQL pass; frontend tests và production build pass.
- Có một lần backup, verify và dry-run restore thành công trên dữ liệu gần production.
- Các kênh được công bố “đã hỗ trợ” phải có bằng chứng inbound và outbound thật cho từng loại media công bố.
- RAG có regression report trên bộ câu hỏi cố định; không đánh giá chỉ bằng vài câu hỏi demo.
- Báo cáo cuối cùng tách rõ: tự động hóa đã pass, manual đã pass, integration chưa thể chạy và baseline lỗi có sẵn.
