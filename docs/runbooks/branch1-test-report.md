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

## Lệnh xác minh

```text
backend: 470 passed, 5 skipped
frontend unit: 108 passed
frontend build: passed
focused Branch 1: 17 passed
```

Các test PostgreSQL cần môi trường DB thật được đánh dấu skip khi dịch vụ không có sẵn; smoke test Docker đã xác nhận provisioning shop 1 thành công và revision tenant `20260915_0001`.
