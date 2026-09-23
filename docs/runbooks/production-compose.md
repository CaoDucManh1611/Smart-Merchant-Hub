# Chạy Smart Merchant Hub bằng Docker Compose production

Tệp `docker-compose.production.yml` tạo môi trường chạy độc lập với mã nguồn:
PostgreSQL, Redis và thư mục upload dùng named volume; chỉ frontend được mở ở
`127.0.0.1:8080` mặc định. Đặt reverse proxy/TLS ở phía trước cổng này trước
khi công khai hệ thống. Reverse proxy phải chuyển `X-Forwarded-Proto: https`;
Nginx giữ header này khi proxy tiếp sang API để backend không redirect nhầm
giao thức nội bộ.

## Chuẩn bị bí mật

1. Tạo `.env.production` từ `.env.production.example` ở thư mục gốc. Thay
   `POSTGRES_PASSWORD` bằng mật khẩu dài, ngẫu nhiên.
2. Tạo `backend/.env` từ `backend/.env.example`. Trong file private này, đặt
   đầy đủ `AUTH_SECRET`, `CHANNEL_ENCRYPTION_KEY`, `CHANNEL_ROUTE_SECRET`, SMTP OTP, khóa LLM,
   `FRONTEND_BASE_URL`, `PUBLIC_BASE_URL`, `CORS_ORIGINS`, `ALLOWED_HOSTS`.
3. Với môi trường thật, các URL phải dùng HTTPS; đặt `ENVIRONMENT=production`,
   `FORCE_HTTPS=true`, `HSTS_ENABLED=true` và `RATE_LIMIT_BACKEND=redis`.
   Không đưa hai file `.env` vào Git.

## Khởi động database trống

Từ thư mục gốc, kiểm tra cấu hình trước:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml config
```

Sau đó tạo và chạy toàn bộ dịch vụ:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d
docker compose --env-file .env.production -f docker-compose.production.yml ps
```

Container backend tự nâng cấp hai control database (`crm_chatbot`,
`crm_platform`), rồi chạy `upgrade_active_tenants --apply` để nâng cấp độc lập
từng schema shop đang hoạt động trước khi mở API. Shop mới tiếp tục được tạo và
migrate tenant schema trong luồng provisioning. Chờ tất cả dịch vụ đạt
`healthy`, sau đó kiểm tra từ host:

```powershell
Invoke-WebRequest http://127.0.0.1:8080/ -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8080/api/health -Headers @{ Host = 'crm.example.com'; 'X-Forwarded-Proto' = 'https' } -UseBasicParsing
```

Thay `crm.example.com` bằng hostname đã khai báo trong `ALLOWED_HOSTS` và
`HEALTHCHECK_HOST`. Request health check dùng đúng Host/header HTTPS như reverse
proxy thật, nên không bị middleware production từ chối khi chạy qua `127.0.0.1`.

Frontend proxy cùng origin cho `/api` và `/ws`, nên browser không cần biết
cổng backend hay một `VITE_API_BASE_URL` riêng.

## Kiểm tra nghiệp vụ sau triển khai

Thực hiện một lần trên môi trường staging/database trống:

1. Đăng ký shop → nhận/nhập OTP → đăng nhập.
2. Chọn hoặc nâng cấp gói; kiểm tra hạn mức hiển thị đúng.
3. Kết nối một kênh; khi hết hạn mức, UI phải nêu lý do và đưa tới chọn gói.
4. Mời nhân viên, upload tài liệu, chờ tiến độ xử lý, thử chat và chuyển nhân viên.
5. Đăng nhập tài khoản platform admin, mở từng tenant và kiểm tra gói/thanh
   toán/hạn mức; thử khóa rồi mở lại một tenant thử nghiệm.

## Vận hành an toàn

Xem log theo dịch vụ bằng `docker compose ... logs -f backend` hoặc `worker`.
Không chạy `down -v` trên production: thao tác đó xóa các named volume chứa
database, Redis và upload. Hướng dẫn backup/restore đầy đủ nằm tại
`docs/production-security-runbook.md` và `docs/runbooks/tenant-backup-restore.md`.
