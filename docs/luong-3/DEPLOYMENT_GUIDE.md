# Hướng dẫn triển khai

## 1. Yêu cầu

- Git và Docker Desktop chạy Linux containers / Docker Engine Linux.
- Docker Compose plugin.
- Cổng local 5173, 8000, 5432 chưa bị chiếm với Compose development.
- Kết nối mạng để tải image và cài package khi build lần đầu.
- Với production: domain/HTTPS ở reverse proxy, secret ngẫu nhiên, PostgreSQL/Redis persistent storage, backup và provider credentials phù hợp.

Chạy `docker version` (phải thấy cả Client và Server) và `docker compose version` trước khi triển khai.

## 2. Chuẩn bị cấu hình local

Từ thư mục gốc repo:

```powershell
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
if (-not (Test-Path 'backend\.env')) { Copy-Item 'backend\.env.example' 'backend\.env' }
```

Đặt `POSTGRES_USER`, `POSTGRES_PASSWORD` ngẫu nhiên, `POSTGRES_DB` **và `DATABASE_URL`** trong `.env` ở thư mục gốc. Compose nội suy `${DATABASE_URL}` từ shell/Compose env file; `env_file: backend/.env` không cung cấp giá trị cho phép nội suy Compose. Đồng thời cấu hình `DATABASE_URL`, `PLATFORM_DATABASE_URL`, `TENANT_DATABASE_URL` trong `backend/.env` để ứng dụng có đủ cấu hình runtime. Tất cả URL dùng hostname `db` trong container và đúng credentials. Chọn `ALLOWED_HOSTS` phù hợp request host development. Các file env không được commit.

Ví dụ URL (thay bằng giá trị local riêng):

```dotenv
DATABASE_URL=postgresql+psycopg://crm_app:LOCAL_PASSWORD@db:5432/crm_chatbot
PLATFORM_DATABASE_URL=postgresql+psycopg://crm_app:LOCAL_PASSWORD@db:5432/crm_platform
TENANT_DATABASE_URL=postgresql+psycopg://crm_app:LOCAL_PASSWORD@db:5432/crm_tenant
```

Nếu password chứa ký tự đặc biệt, URL-encode password trong connection URL. Không paste secret thật vào terminal transcript, issue hoặc Git.

## 3. PostgreSQL và migration từ database sạch

Compose development dùng `pgvector/pgvector:pg16`, init script tạo thêm database platform/tenant; `db-init` là prerequisite của backend. Startup command trong backend chạy theo thứ tự:

1. Alembic main CRM database (`alembic.ini`).
2. Alembic platform database (`alembic-platform.ini`).
3. `app.scripts.upgrade_active_tenants --apply` cho tenant schema active.
4. Khởi động FastAPI.

Các service development khai báo `container_name` cố định. Do đó đổi Compose project name trên cùng Docker Engine không đủ để chạy song song với một stack đang có cùng tên container. Chỉ thực hiện clean-install test trên Docker Engine/VM riêng không có container ứng dụng trùng tên và với volume test riêng; tuyệt đối không xóa volume của môi trường đang có dữ liệu.

```powershell
docker compose --env-file .\.env -p smh-l3-clean config --quiet
docker compose --env-file .\.env -p smh-l3-clean up -d --build
docker compose --env-file .\.env -p smh-l3-clean ps -a
```

Tên project tạo volume riêng, nhưng không thay đổi các `container_name` cố định. Không dùng `docker compose down -v` trên môi trường có dữ liệu. Xem log và revision:

```powershell
docker compose --env-file .\.env -p smh-l3-clean logs --tail 150 db db-init backend
docker compose --env-file .\.env -p smh-l3-clean exec backend python -m alembic -c alembic.ini current
docker compose --env-file .\.env -p smh-l3-clean exec backend python -m alembic -c alembic-platform.ini current
```

Production sử dụng [docker-compose.production.yml](../../docker-compose.production.yml) và `.env.production` riêng. File này phải có tối thiểu `POSTGRES_USER`, `POSTGRES_PASSWORD`, `HEALTHCHECK_HOST`; có thể đặt `POSTGRES_DB`, `FRONTEND_PORT`, `BACKEND_ENV_FILE` theo cấu hình. `backend/.env` (hoặc file được chọn qua `BACKEND_ENV_FILE`) chứa `AUTH_SECRET`, cấu hình production/HTTPS/CORS/hosts, provider và các secret runtime; không đưa secret vào `.env.production` nếu không cần thiết.

```powershell
docker compose --env-file .\.env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .\.env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .\.env.production -f docker-compose.production.yml ps -a
docker compose --env-file .\.env.production -f docker-compose.production.yml logs --tail 150 db backend worker frontend
```

Đọc [production compose runbook](../runbooks/production-compose.md), tenant migration và backup/restore runbook trước khi nâng cấp. Backup trước migration production.

## 4. Khởi động và health check

Compose development:

```powershell
docker compose --env-file .\.env -p smart-merchant-hub-runtime up -d --build
docker compose --env-file .\.env -p smart-merchant-hub-runtime ps -a
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:5173/
```

Backend healthcheck kiểm tra `/health` cùng kết nối platform/tenant DB; frontend healthcheck kiểm tra HTTP 200. Redis có `redis-cli ping`; PostgreSQL dùng `pg_isready`. Có thể kiểm tra riêng:

```powershell
docker compose --env-file .\.env -p smart-merchant-hub-runtime exec db pg_isready -U $env:POSTGRES_USER -d crm_chatbot
docker compose --env-file .\.env -p smart-merchant-hub-runtime exec redis redis-cli ping
```

Mở frontend `http://localhost:5173/`, API docs `http://localhost:8000/docs`, health `http://localhost:8000/health`. Tạo owner riêng theo hướng dẫn README, không dùng credential demo cố định.

## 5. Khởi chạy ngoài Docker

- Backend: tạo virtual environment, cài `backend/requirements.txt`, cấu hình env cho PostgreSQL/Redis. Từ `backend`, chạy `python -m alembic -c alembic.ini upgrade head`, `python -m alembic -c alembic-platform.ini upgrade head`, sau đó `python -m app.scripts.upgrade_active_tenants --apply` rồi `uvicorn app.main:app --reload`.
- Frontend: `npm ci`, rồi `npm run dev` hoặc `npm run build`.
- Cách chạy host và Docker khác nhau ở hostname DB/Redis; host thường dùng `localhost`, container dùng tên service `db`/`redis`.

## 6. Kiểm tra sau triển khai

- Tất cả service cần thiết ở trạng thái healthy; backend log thể hiện migration hoàn tất trước startup.
- `/health` trả 200; kiểm tra revision của main/platform DB; worker kết nối được hai DB.
- Đăng nhập owner, xác nhận tenant, tạo dữ liệu thử được phép, rồi đăng nhập user thứ hai để kiểm tra cách ly.
- Kiểm tra frontend, kết nối provider thực với tài khoản thử, inbound webhook, Customer 360 và gửi/nhận an toàn.
- Xác minh backup/restore và giám sát trước khi chuyển dữ liệu thật.

## 7. Sự cố thường gặp

| Triệu chứng | Kiểm tra |
|---|---|
| `docker version` chỉ hiện Client | Khởi động Docker Desktop, chọn Linux containers/WSL 2 và chạy lại lệnh. |
| Compose thiếu `POSTGRES_USER/PASSWORD` hoặc `DATABASE_URL` | Tạo `.env` và `backend/.env` từ mẫu; xác nhận tên biến và Compose `config --quiet`. |
| Backend không kết nối DB | Trong container dùng hostname `db`, kiểm tra credentials/database và `db`/`db-init` health/log. |
| Backend không healthy | Đọc log backend; phân biệt migration thất bại, DB chưa healthy, sai allowed host hoặc env thiếu. |
| Migration fail | Giữ log đầy đủ, xác nhận database PostgreSQL/version, backup trước khi sửa dữ liệu; không sửa schema thủ công. |
| Frontend không truy cập được | Kiểm tra cổng 5173/8080, health của backend và cấu hình API base URL. |
| Channel không nhận tin | Kiểm tra credentials, callback public HTTPS, signature/webhook subscription và trạng thái channel; test local không thay provider live. |
| RAG không trả lời | Kiểm tra ingest job/chunks, trạng thái tài liệu, cấu hình embedding/LLM, quota và tenant của tài liệu. |
| Thấy dữ liệu trống sau khi đổi Compose project name | Xác minh volume/project name; không xóa volume cũ. |

## 8. Trạng thái xác minh đợt Luồng 3

Docker Engine và Compose ban đầu đã phản hồi phiên bản trong phiên kiểm tra, nhưng cấu hình cá nhân ban đầu không tồn tại. Khi dựng cấu hình test riêng, build backend image thất bại trong bước cài dependency Torch (`OSError: Read-only file system` và sau đó worker Docker báo bus error). Các lệnh Docker tiếp theo treo và đã được dừng theo timeout; theo yêu cầu, không tiếp tục troubleshooting. Vì vậy chưa có bằng chứng PostgreSQL container, migration DB sạch, Compose healthcheck hay production startup thành công trên máy hiện tại. Hướng dẫn trên mô tả quy trình dự kiến từ source/config; không phải kết quả triển khai đã PASS. Xem [TEST_REPORT.md](./TEST_REPORT.md).
