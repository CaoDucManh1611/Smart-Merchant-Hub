# Thiết kế SaaS hai database và schema riêng cho từng shop

**Ngày:** 2026-09-15
**Nhánh mục tiêu:** `crm-completion`
**Trạng thái:** Chờ duyệt trước khi viết implementation plan

## 1. Mục tiêu

Chuyển Smart Merchant Hub từ mô hình tenant dùng chung schema sang kiến trúc:

- `platform_db` chỉ chứa control plane của nhà cung cấp SaaS;
- `tenant_db` chứa dữ liệu nghiệp vụ, mỗi shop nằm trong một PostgreSQL schema riêng;
- một shop có một owner và nhiều tài khoản nhân viên;
- tài khoản shop A không thể đọc, suy đoán sự tồn tại hoặc thay đổi dữ liệu shop B;
- Platform Admin quản lý shop, gói, quota, thanh toán và sức khỏe hệ thống nhưng không mặc định đọc dữ liệu nghiệp vụ;
- quyền hỗ trợ dữ liệu chỉ tồn tại khi owner cấp tạm thời, có lý do, thời hạn và audit.

## 2. Phạm vi dữ liệu

### `platform_db`

Chỉ lưu control plane và dữ liệu tối thiểu cần để định tuyến:

- `businesses`;
- `users`, với email duy nhất trong phạm vi một shop;
- `service_plans`, `subscriptions`, `payments`;
- `platform_memberships` dành riêng cho nhân sự nhà cung cấp;
- `tenant_registry` ánh xạ `business_id -> schema_name`, trạng thái provision và phiên bản migration;
- `quota_usage` và entitlement;
- `channel_route_registry` gồm provider, external account ID, secret hash, `business_id` và schema đích;
- `support_grants` gồm shop cấp quyền, người được cấp, lý do, phạm vi, thời điểm bắt đầu/hết hạn/thu hồi;
- `platform_audit`, không chứa nội dung hội thoại, token hoặc dữ liệu định danh khách hàng.

### `tenant_db`

Mỗi shop có schema chuẩn hóa `shop_<business_id>`, ví dụ `shop_17`. Schema chứa toàn bộ dữ liệu nghiệp vụ:

- khách hàng, identity, liên hệ, địa chỉ và Customer 360;
- kênh, token đã mã hóa và cấu hình webhook;
- hội thoại, tin nhắn, tệp đính kèm và timeline;
- sản phẩm, kho, nhà cung cấp, mua hàng, đơn bán và thanh toán;
- lead, ticket, SLA, CSAT, workflow, follow-up và notification;
- tài liệu, chunk, embedding, RAG run, AI experiment và AI usage chi tiết;
- shop settings, role override và shop audit.

Schema `public` của `tenant_db` chỉ chứa extension dùng chung, metadata migration và thành phần kỹ thuật không mang dữ liệu shop. Không lưu token hoặc nội dung khách hàng trong `public`.

## 3. Danh tính, quyền và chọn tenant

- Tài khoản shop thuộc đúng một `business_id`; cùng email có thể được đăng ký độc lập ở shop khác.
- JWT chứa `user_id`, `business_id`, role và session ID; backend luôn đối chiếu lại với `platform_db`.
- Client không được tự chọn tenant bằng `X-Business-Id` trong production.
- `TenantRegistryService` nhận `business_id` đã xác thực và trả về schema đã allow-list; schema từ request không bao giờ được nối trực tiếp vào SQL.
- Khi bắt đầu transaction trên `tenant_db`, backend đặt `SET LOCAL search_path TO <allow-listed-schema>, public`.
- PostgreSQL role của ứng dụng không có quyền `USAGE` trên schema khác ngoài schema được cấp cho transaction; explicit tenant guards vẫn được giữ ở các quan hệ nhạy cảm như channel routing và support grant.
- Platform Admin chỉ kết nối `platform_db`; không được cấp database role đọc `tenant_db`.

## 4. Onboarding và vòng đời shop

Tạo shop là một saga vì PostgreSQL không hỗ trợ transaction nguyên tử xuyên hai database:

1. Tạo `business`, owner, subscription và bản ghi `tenant_registry(status=provisioning)` trong `platform_db`.
2. Tạo schema an toàn trong `tenant_db` bằng account provisioner riêng.
3. Chạy toàn bộ tenant migrations vào schema mới.
4. Seed cấu hình mặc định của shop.
5. Kiểm tra schema, phiên bản và quyền truy cập.
6. Chuyển registry sang `active`; lúc đó shop mới được đăng nhập vào CRM.

Nếu bước 2–5 lỗi, registry chuyển `provision_failed`, lưu lỗi đã redaction và cho phép retry idempotent. Không xóa tự động schema đã tạo một phần; cleanup phải là job có audit.

Tạm khóa shop chỉ chặn login mới, write và worker; dữ liệu vẫn được giữ. Xóa shop dùng lifecycle `active -> suspended -> deletion_scheduled -> deleted`, có thời gian chờ và backup theo chính sách.

## 5. Webhook và kết nối kênh

- `channel_route_registry` ở `platform_db` giải quyết bài toán webhook đến trước khi backend biết schema shop.
- Registry chỉ lưu định tuyến tối thiểu và hash của webhook secret; access token vẫn nằm trong schema shop dưới dạng mã hóa.
- Webhook xác minh chữ ký/secret trước, tra đúng `business_id`, mở transaction vào schema tương ứng rồi mới persist event.
- Một external account chỉ thuộc một shop tại một thời điểm bằng unique constraint toàn cục.
- Inbox/outbound luôn lấy channel trong schema hiện tại; không có fallback sang channel mặc định hoặc token `.env` trong production.

## 6. Platform Admin và hỗ trợ tạm thời

Platform Admin được phép:

- xem shop, plan, subscription, quota và trạng thái provision/migration;
- xem số liệu vận hành tổng hợp không chứa nội dung/PII;
- suspend/reactivate shop;
- retry provisioning/migration;
- quản lý billing và cảnh báo provider ở mức metadata.

Platform Admin không được phép đọc trực tiếp schema shop. Khi cần hỗ trợ, owner tạo `support_grant` với phạm vi cụ thể, ví dụ `settings.read` hoặc `channel.health`; mặc định không có `conversation.read`, `customer.read` hay `order.read`. Grant tối đa 60 phút, có thể thu hồi ngay, yêu cầu MFA và ghi audit ở cả control plane lẫn shop.

## 7. Migration dữ liệu hiện tại

Không chuyển toàn bộ dữ liệu trong một lần. Mỗi shop được chuyển theo quy trình:

1. Inventory toàn bộ bảng và foreign key hiện tại; chặn tạo row mới thiếu `business_id`.
2. Tạo `platform_db`, `tenant_db` và schema factory nhưng vẫn chạy đường dữ liệu cũ.
3. Chọn một shop thử nghiệm, tạo schema và chạy migration rỗng.
4. Đặt shop thử nghiệm vào maintenance write ngắn; copy dữ liệu theo thứ tự dependency.
5. So sánh row count, khóa ngoại, checksum dữ liệu quan trọng, số hội thoại/tin nhắn/đơn/tồn kho/chunk.
6. Đổi duy nhất con trỏ `tenant_registry` sang schema mới.
7. Chạy smoke test và theo dõi; rollback bằng cách trả con trỏ về nguồn cũ nếu chưa có write mới.
8. Chuyển từng shop còn lại theo batch nhỏ.
9. Sau thời gian ổn định mới xóa fallback `Default Business`, `X-Business-Id` production và các cột tenant nullable.

Không dùng dual-write lâu dài vì làm tăng nguy cơ lệch dữ liệu. Mỗi shop chấp nhận một cửa sổ maintenance ngắn để cutover có thể kiểm chứng và rollback.

## 8. Migration và phiên bản schema

- `platform_db` có Alembic chain riêng.
- Tenant schema dùng một bộ migration template chung, chạy lần lượt cho từng schema.
- `tenant_registry` lưu `current_revision`, `target_revision`, `migration_status`, `last_error_code` và thời điểm chạy.
- Worker migration có lock theo `business_id`, idempotency key và giới hạn concurrency.
- Request chỉ được phục vụ khi schema ở revision tương thích; nếu không trả lỗi bảo trì có mã ổn định.

## 9. Backup, restore và quan sát

- Backup `platform_db` và `tenant_db` tách biệt nhưng cùng recovery point label.
- Có thể restore một schema shop sang schema tạm để kiểm chứng mà không đè shop đang chạy.
- Log, trace và metric chứa `business_id`, schema alias, request ID và operation ID; không chứa raw token, OTP, nội dung tin nhắn hoặc PII.
- Dashboard Platform chỉ hiển thị trạng thái schema, revision, quota, lỗi provider đã redaction, queue lag và SLA tổng hợp.

## 10. Chiến lược kiểm thử

- Unit test schema-name allow-list, tenant resolver và support grant.
- API isolation test với ít nhất hai shop có ID bản ghi trùng nhau trong hai schema.
- Test rằng token Shop A không thể đổi header/schema để đọc Shop B.
- Test webhook route đúng schema, sai secret bị từ chối và retry không tạo trùng.
- Test RAG chỉ truy hồi document/chunk trong schema hiện tại.
- Test worker, follow-up, workflow và quota luôn giữ tenant context.
- Test provisioning retry, migration failure, cutover và rollback.
- Restore drill cho một schema riêng và full `tenant_db`.
- Release gate chạy toàn bộ backend, frontend, migration rỗng, migration dữ liệu cũ và smoke đa shop.

## 11. Bảng kế hoạch rollout

| Giai đoạn | Kết quả bàn giao | Phạm vi chính | Điều kiện hoàn thành |
|---|---|---|---|
| 0. Audit tenant | Danh sách mọi bảng/query/config đang dùng chung | Hard-code `BUSINESS_ID=1`, nullable `business_id`, global settings/token, API và worker | Có ma trận table/API/job và test tái hiện các điểm rò tenant |
| 1. Control plane DB | `platform_db` chạy độc lập | Business, user, plan, subscription, quota, registry, platform audit | Login và Platform Admin chỉ dùng `platform_db`; không đọc tenant data |
| 2. Tenant DB foundation | Engine/resolver/schema factory | `tenant_db`, schema allow-list, transaction search path, roles | Tạo được schema shop rỗng, migrate và kết nối đúng schema |
| 3. Shop provisioning | Onboarding saga có retry | Tạo shop, owner, schema, seed, status | Retry không tạo trùng; lỗi giữa chừng không kích hoạt shop |
| 4. Core CRM isolation | Customer/inbox/order/inventory tách schema | Customer, conversation, message, channel, product, inventory, order | Hai shop có dữ liệu trùng ID nhưng API không thể đọc chéo |
| 5. AI/RAG isolation | Kho tri thức và AI tách theo shop | Document, chunk, embedding, RAG run, rules, experiments | Query shop A không truy hồi chunk hoặc AI state của shop B |
| 6. Operations isolation | CRM automation tách schema | Lead, ticket, workflow, follow-up, notification, CSAT, audit | Worker chạy nhiều shop không đổi nhầm context và không tạo trùng |
| 7. Webhook routing | Registry định tuyến toàn cục tối thiểu | Telegram, Zalo, Meta, TikTok, Shopee; encrypted channel token | Provider event vào đúng schema; secret sai bị từ chối |
| 8. Pilot migration | Một shop thật được cutover có rollback | Copy theo dependency, checksum, maintenance window | Row count/checksum/smoke pass; rollback drill thành công |
| 9. Batch migration | Chuyển toàn bộ shop theo batch | Scheduler, progress, alert, backup label | Mọi shop ở revision mục tiêu; không còn row thiếu tenant |
| 10. Remove legacy fallback | Production fail-closed hoàn toàn | Bỏ `BUSINESS_ID=1`, default tenant, global token fallback, nullable tenant FK | Cross-tenant suite, restore drill và release smoke đều pass |

## 12. Ngoài phạm vi giai đoạn này

- Mỗi shop một database riêng;
- data warehouse/BI xuyên tenant chứa dữ liệu chi tiết;
- cho Platform Admin quyền đọc mặc định vào dữ liệu shop;
- dual-write lâu dài giữa schema cũ và mới;
- tự động xóa dữ liệu/schema ngay khi shop hủy gói.
