# Branch 1 (SaaS platform control) – test report

Phạm vi: `feat/saas-platform-control`, chỉ các năng lực control-plane/provisioning/support/backup của Branch 1. Không đưa dữ liệu hội thoại, khách hàng hay payload webhook vào platform database.

## Ma trận kiểm thử

| ID | Nhóm | Kịch bản và kỳ vọng | Kết quả |
|---|---|---|---|
| B1-T05-01 | Provisioning | Tạo shop với idempotency key mới tạo đúng `shop_<business_id>`, chạy tenant migration và bật feature sau khi migrate thành công. | PASS |
| B1-T05-02 | Provisioning | Gửi lại cùng key không chạy migration lần hai và trả lại trạng thái cũ. | PASS |
| B1-T05-03 | Provisioning | Migration lỗi chuyển registry sang `provision_failed`, không xóa schema, lỗi chỉ là mã đã sanitize; retry dùng key mới và có thể thành công. | PASS |
| B1-T06-01 | Auth/tenant | Request có user nhưng registry chưa `active` bị chặn `423 tenant_unprovisioned`. | PASS |
| B1-T06-02 | Auth/tenant | Tenant context lấy từ user/session và registry; header `X-Business-Id` giả mạo bị bỏ qua. | PASS |
| B1-T07-01 | Platform boundary | Provider errors/audit/events đọc bảng metadata của platform khi bảng tồn tại, không truy cập bảng tenant. | PASS |
| B1-T07-02 | Privacy | Export/anonymize/delete chỉ ghi yêu cầu dispatch sang tenant worker, không trả counts lấy từ tenant. | PASS |
| B1-T13-01 | Support access | Owner cấp grant có reason, scope hợp lệ, thời hạn; support session bị giới hạn bởi grant và TTL. | PASS |
| B1-T13-02 | Support access | Token support bị chặn khỏi API khách hàng; revoke làm token mất hiệu lực ngay. | PASS |
| B1-T15-01 | Backup/restore | Backup suy ra schema theo business id, archive rỗng/version mismatch/pg_restore lỗi đều fail rõ ràng. | PASS |
| B1-T15-02 | Backup/restore | Restore mặc định không destructive; chỉ `-Overwrite` mới thêm `--clean --if-exists`; manifest kiểm checksum. | PASS |
| B1-T17-01 | Lifecycle | Suspend shop revoke toàn bộ auth session của shop; request ghi dữ liệu bị chặn. | PASS |
| B1-T18-01 | Billing/quota | Payment chỉ chuyển trạng thái theo thứ tự hợp lệ và số tiền paid phải khớp giá plan. | PASS |
| B1-T18-02 | Quota | Usage/near-limit lấy aggregate platform, không đếm users/channels/documents từ tenant. | PASS |
| B1-T19-01 | Observability | Snapshot có trạng thái reachability của platform DB và tenant DB; lỗi chỉ phát cảnh báo khi thật sự có lỗi. | PASS |
| B1-INT-01 | PostgreSQL boundary | Pool tenant đặt đúng `search_path`; trả connection về pool rồi mượn lại không rò schema của shop trước. | PASS |
| B1-INT-02 | Tenant migration | Hai schema tenant độc lập migrate đúng revision; chạy lại migration có tính idempotent. | PASS |
| B1-UI-01 | Anonymous boundary | Chưa đăng nhập không tải/hiện hội thoại hoặc card cài đặt tenant; chỉ hiện login/onboarding. | PASS |
| B1-UI-02 | UI feedback | Mở/đóng form tạo shop có phản hồi; đăng nhập sai hiện thông báo rõ ràng, không tạo chức năng “ma”. | PASS |
| B1-UI-03 | Browser runtime | Reload ở trạng thái anonymous không phát sinh lỗi/warning console từ API tenant. | PASS |
| B1-AUTH-UTC | Token expiry | Token 15 phút vẫn còn hiệu lực đúng TTL trên máy UTC+7; `exp` dùng UTC instant, không phụ thuộc timezone host. | PASS |
| B1-LIFE-02 | Suspension | Shop bị khóa không thể tạo session mới; Platform Admin vẫn đăng nhập được để thực hiện phục hồi nhưng không được dùng tenant API của shop bị khóa. | PASS |
| B1-BILL-03 | Subscription period | Từ chối kỳ dịch vụ có `ends_at <= starts_at`. | PASS |
| B1-SUP-03 | Least privilege | Từ chối TTL support quá 24 giờ, scope lặp và thao tác ngoài scope đã cấp. | PASS |
| B1-PROV-04 | Idempotency isolation | Một idempotency key không thể tái sử dụng cho shop khác; business id không hợp lệ bị từ chối trước migration. | PASS |
| B1-QUOTA-03 | Production fail-closed | Shop production không có subscription bị giới hạn quota về 0 thay vì được dùng không giới hạn. | PASS |

## Lệnh xác minh

```text
backend: 478 passed, 2 skipped
focused Branch 1 edge/security: 23 passed
PowerShell/backup focused: 5 passed
PostgreSQL integration (isolated database): 4 passed
frontend unit: 108 passed
frontend build: passed
```

Hai case bị skip trong bộ regression mặc định là PostgreSQL-only và đã được chạy opt-in cùng nhóm database-boundary trên database cô lập `crm_branch1_validation_20260916_001` (4/4 pass). Database tạm đã được xóa sau test; database CRM và dữ liệu hội thoại không bị thay đổi. Smoke test Docker cũng xác nhận provisioning shop 1 thành công và revision tenant `20260915_0001`.

## Lỗi phát hiện và đã sửa trong vòng retest

1. Test harness trước đây luôn ép URL database về SQLite nên các test PostgreSQL vẫn skip dù đã cấp database thật. Đã thêm chế độ `RUN_POSTGRES_TESTS=1` và cô lập fixture để chạy integration thật an toàn.
2. Trang Cài đặt khi chưa đăng nhập vẫn render các card tenant và âm thầm gọi API, gây lỗi `403`/`Tenant context is required`. Đã gate cả UI lẫn request theo authenticated session; reload thực tế xác nhận console sạch.
3. Vite dev server từng giữ transform cũ sau khi source thay đổi. Đã restart frontend container và xác minh bundle đang phục vụ đúng logic mới.
4. Token expiry được tính từ UTC datetime đã bỏ timezone, khiến Python hiểu là giờ local và token support 15 phút hết hạn ngay trên máy UTC+7. Đã giữ datetime timezone-aware đến lúc đổi sang Unix timestamp và thêm regression theo thời gian thực.
5. Shop đã bị suspend vẫn có thể đăng nhập lại để nhận token mới. Đã chặn session mới và chặn tenant API theo trạng thái shop; chỉ Platform Admin được dùng đường auth/platform để phục hồi.
6. Subscription trước đây nhận kỳ thời gian đảo ngược. Đã thêm validation `ends_at > starts_at` ở contract API.
7. Test backup cục bộ chọn nhầm `backend/scripts` chỉ vì thư mục tồn tại. Đã định vị script theo đúng file `tenant-backup.ps1`, giúp Windows và Docker chạy nhất quán.
