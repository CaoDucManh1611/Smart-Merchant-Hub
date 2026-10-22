# Sao lưu và khôi phục trong admin

Đăng nhập admin nền tảng, chọn **Sao lưu & khôi phục**. Có thể tạo bản sao,
tải ZIP xuống, nhập lại ZIP, kiểm tra trên database tạm và khôi phục.
Shop thường không có quyền gọi các API `/api/platform/backups`.

## Phạm vi bản sao

- Các database được cấu hình bởi `DATABASE_URL`, `TENANT_DATABASE_URL`,
  `PLATFORM_DATABASE_URL` (tự gộp nếu cùng một database), bao gồm các schema shop,
  dữ liệu CRM, kho tri thức và vector RAG.
- Tệp trong `backend/uploads`. Không có `.env`, API key từ biến môi trường,
  mã nguồn, Redis hay hồ sơ Edge/cấu hình connector trên máy shop.
- Không khôi phục phiên đăng nhập, mã xác minh và hàng đợi `crm_jobs` cũ.
  Sau khi khôi phục cần đăng nhập lại; các tác vụ nền cần xếp lịch lại khi cần.
- ZIP chứa dữ liệu nghiệp vụ và dữ liệu tài khoản, không phải bản đã ẩn danh.
  Chỉ giữ ở nơi riêng; thư mục sao lưu không được phục vụ như uploads công khai.

Chữ ký HMAC dùng khóa được dẫn xuất riêng từ `CHANNEL_ENCRYPTION_KEY`, hoặc
`AUTH_SECRET` nếu chưa có khóa kênh đủ mạnh. Manifest ghi loại khóa, không ghi
giá trị. Khi chuyển máy phải giữ nguyên khóa tương ứng và các khóa mã hóa khác
trong cấu hình riêng. ZIP không thể tự giải mã kết nối kênh khi mất khóa gốc.

## Cách vận hành

`pg_dump`/`pg_restore` 16 được cài trong image backend từ kho PostgreSQL chính
thức. Các script PowerShell trước đây vẫn độc lập; ZIP mới chỉ nhận bản do app
ký. Tệp dump/ZIP từ bên thứ ba không được thực thi.

Sao lưu/kiểm tra/khôi phục chạy nền. Trạng thái và lịch sử lưu ngoài database ở
`BACKUP_DIR` (mặc định `/app/backups` trong Docker). Compose local bind-mount
`./backups`, production dùng volume `production_backups`; backend và worker
phải dùng chung volume này. `BACKUP_MAX_BYTES` mặc định 2 GiB.

Một khóa hệ điều hành ngăn tác vụ trùng. Barrier bảo trì ngăn yêu cầu API mới
và vòng chạy worker mới, chờ công việc hiện tại hoàn tất (tối đa 120 giây).
Streaming và FastAPI background tasks giữ khóa đến khi hoàn tất. Webhook nhận
503 kèm Retry-After trong thời gian này; nhà cung cấp/connector cần gửi lại.

Khôi phục yêu cầu nhập **KHÔI PHỤC** và mật khẩu admin hiện tại. Trước khi ghi:

1. Kiểm tra chữ ký, checksum, giới hạn kích thước và đường dẫn ZIP.
2. Đối chiếu phiên bản PostgreSQL/migration; phục hồi thử từng dump vào database
   tạm, đối chiếu schema và số bản ghi. Tài khoản database cần quyền CREATEDB.
3. Tạo một bản **an toàn trước khôi phục**, hiển thị trong danh sách.
4. Khôi phục từng database bằng giao dịch có `--exit-on-error`, đồng bộ uploads
   và kiểm tra lại. Nếu lỗi, trả lại các database/uploads từ bản an toàn.

Mỗi database có một transaction riêng. Nếu tiến trình chết hoặc rollback thất
bại giữa các database, hệ thống giữ chế độ bảo trì, không tự mở lại ghi dữ liệu.
Admin xem lịch sử tác vụ để lấy `safety_backup_id`. Quản trị máy chủ có thể phục
hồi sau khi kiểm tra bản an toàn bằng lệnh sau (thao tác này ghi đè dữ liệu):

```powershell
docker compose exec backend python -m app.scripts.restore_backup <safety_backup_id> --confirm "KHÔI PHỤC"
```

Không xóa `maintenance.json` để bỏ qua một lần khôi phục chưa hoàn tất. Khôi
phục thành công sẽ tự mở lại hệ thống. Tác vụ sao lưu/kiểm tra bị gián đoạn do
khởi động lại được đánh dấu thất bại và giải phóng bảo trì khi khởi động.

## Kiểm chứng không đụng dữ liệu đang dùng

```powershell
docker compose exec backend python scripts/verify_admin_backups.py
```

Script chỉ tạo database `smh_backup_test_<uuid>` mới, tạo dữ liệu/vector mẫu,
sao lưu, sửa dữ liệu mẫu rồi khôi phục. Kiểm tra tệp, vector, schema và phiên
đăng nhập; xóa đúng database tạm đã tạo. Không khôi phục vào database đang dùng.

Tham khảo: [pg_restore 16](https://www.postgresql.org/docs/16/app-pgrestore.html),
[kho PostgreSQL cho Debian](https://www.postgresql.org/download/linux/debian/).

PostgreSQL trong Compose dùng `max_locks_per_transaction=1024` vì nhiều schema shop có hàng nghìn bảng/index. Giá trị mặc định 64 có thể gây `out of shared memory` khi `pg_restore --single-transaction`; thay đổi này cần khởi động lại dịch vụ database. Với PostgreSQL ngoài Compose, cấu hình tương ứng trước khi kiểm chứng/khôi phục.
