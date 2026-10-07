# Báo cáo kiểm thử Luồng 3

Ngày ghi nhận: 2026-10-07. Đây là trạng thái repo và môi trường tại thời điểm chạy, không phải cam kết cho provider hoặc deployment khác.

## Môi trường

- Windows PowerShell; repo branch `feat/luong-3-admin-integration-release` tạo từ `main` hiện tại.
- Python 3.11.9 system interpreter đã cấu hình; backend dependencies có sẵn.
- Frontend Node/npm trên máy; Docker Engine Linux 29.8.0, Docker Desktop 4.91.0, Compose v5.5.1.
- Compose development config yêu cầu `.env` và `backend/.env`; chúng không có trước lần chạy. Tạo file env cục bộ riêng với credentials ngẫu nhiên cho lần thử; không đưa chúng vào tài liệu/commit.

## Kết quả thực tế

| Test / kiểm tra | Kết quả | Trạng thái / giới hạn |
|---|---|---|
| Backend full suite: `python -m pytest -q` trong `backend` | 872 passed, 3 skipped, 43.11s (final run) | PASS với 3 skip |
| Backend ticket/auth focused sau sửa env test host | 16 passed, 6.94s | PASS |
| Backend focused ticket/auth lần kiểm tra tiếp nối trước full suite | 9 passed, 4.93s | PASS |
| Frontend `npm.cmd test` | 222 passed, 0 failed, 0 skipped | PASS |
| Frontend `npm.cmd run build` | vite build thành công trong 4.61s | PASS; cảnh báo một số chunk minified >500 kB |
| `git diff --check` cuối cùng | Không có lỗi whitespace | PASS |
| Docker `docker version` | Client và Server cùng phản hồi; Engine Linux | PASS |
| `docker compose version` | v5.5.1 | PASS |
| Compose config | Ban đầu không resolve vì thiếu `.env`, `backend/.env`; sau đó cấu hình cục bộ test được tạo | PASS sau cấu hình |
| Compose build/start clean (`docker compose --env-file .\.env -p smh-flow3-clean up -d --build`) | Backend dependency install dừng với `OSError: [Errno 30] Read-only file system: '/usr/local/bin/convert-caffe2-to-onnx'`, sau đó BuildKit worker báo `Bus error`/EOF | FAIL; container stack không được xác nhận healthy |
| Docker version recheck (timeout wrapper 15s) | `docker version` không trả output trong thời hạn; tiến trình CLI PID cụ thể bị dừng sau 15 giây | TIMEOUT; không retry |
| Compose status check sau lỗi build | `docker compose ... ps -a` và `docker ps` không trả lời; tiến trình CLI bị dừng theo timeout của người vận hành | TIMEOUT; trạng thái service/health chưa xác minh |
| PostgreSQL container / migration main, platform, tenant trên DB sạch | Không hoàn tất do backend image build/BuildKit lỗi trước khi database stack được xác nhận healthy | NOT RUN / chưa có bằng chứng |
| Healthcheck/backend startup qua Compose | Không hoàn tất | NOT RUN |
| PostgreSQL migration trên DB đã có dữ liệu | Không chạy | NOT RUN |
| Provider OAuth/webhook/LLM live | Credentials và kết nối thực không được chạy trong test suite | NOT RUN |

Lượt đầu full pytest trả 297 failed do `ALLOWED_HOSTS` cục bộ từ env mẫu từ chối HTTP test host `testserver` (ví dụ response 400 `Invalid host header`); đó là sai lệch môi trường test, không phải bằng chứng regression của từng API. Sau khi thêm `testserver` vào env test cục bộ, focused tests đạt 16/16 và full backend suite đạt 872 passed, 3 skipped. Không sửa test để làm PASS.

## Các bằng chứng tính năng

- [test_cskh_advanced_api.py](../../backend/tests/test_cskh_advanced_api.py): support shop, SLA admin-only, deny override cho tickets write, forged `X-Business-Id` khi gọi ticket.
- [test_api_tenant_isolation.py](../../backend/tests/test_api_tenant_isolation.py), [test_customer_360_api.py](../../backend/tests/test_customer_360_api.py), [test_crm_two_shop_e2e.py](../../backend/tests/test_crm_two_shop_e2e.py): các kiểm tra tenant/inbox/Customer 360/commerce.
- [test_unified_inbox_webhooks.py](../../backend/tests/test_unified_inbox_webhooks.py): webhook channel persistence và chữ ký trong test harness.
- [test_industry_modules.py](../../backend/tests/test_industry_modules.py): appointment và luồng quote → project → invoice/payment trong fixture.
- [test_rag_tenant_isolation.py](../../backend/tests/test_rag_tenant_isolation.py), [test_rag_components.py](../../backend/tests/test_rag_components.py): cách ly truy xuất RAG và thành phần RAG.
- [test_tenant_migration_runner.py](../../backend/tests/test_tenant_migration_runner.py), [test_alembic_chain.py](../../backend/tests/test_alembic_chain.py), [test_container_migrations.py](../../backend/tests/test_container_migrations.py): logic/schema contract migration; test contract không tương đương chạy migration trên PostgreSQL container.

Các test unit/integration trên SQLite/in-memory chỉ là test tương ứng; chúng không được dùng làm bằng chứng migration PostgreSQL hoặc provider live.

## Lỗi và thay đổi liên quan

| Phát hiện | Thay đổi | Kết quả |
|---|---|---|
| Shop user role `support` bị chặn nhầm như platform support | Sửa ranh giới auth để platform support không gắn shop mới chịu guard support-only | Regression support shop đạt |
| Permission override `tickets:read/write` không được ticket endpoint thực thi | Thêm resource permission dependency cho các endpoint ticket phù hợp; SLA write giữ admin guard | Regression deny write/read đạt |
| Forge tenant header không được dùng để đổi tenant phiên auth | Ticket query vẫn bound với tenant đã xác thực; test detail/update ticket shop khác bị 404 | Regression đạt |
| Compose clean build lỗi ở bước pip/BuildKit; các lệnh Docker kế tiếp treo | Đã dừng CLI khi hết timeout; không sửa Dockerfile/dependency vì chưa phân biệt được lỗi read-only filesystem, BuildKit worker hay Docker Desktop/WSL runtime | Deployment chưa PASS; cần kiểm tra Docker Desktop/WSL/BuildKit logs khi Engine phản hồi |

## Giới hạn còn lại

- Permission override mới được wire và xác minh tại ticket; UI có option resource customers/orders/documents/team/reports nhưng chưa có chứng cứ override có hiệu lực thống nhất ở mọi endpoint đó. Không dùng tài liệu này để tuyên bố ma trận permission/override CRM toàn diện đã PASS.
- Tenant tests bao phủ những API cụ thể của suite, không phải kiểm thử fuzz từng endpoint ID của toàn bộ nghiệp vụ.
- PostgreSQL thật, migration từ database trống/có dữ liệu, Compose healthcheck/startup chưa có bằng chứng chạy thành công.
- Sau lỗi build, một lần kiểm tra `docker version` có giới hạn 15 giây và `docker compose ... ps -a` đều timeout; không chạy tiếp troubleshooting vô hạn. Lần kiểm tra đầu tiên ở đầu phiên đã trả Client + Server và Compose version.
- Kết nối provider live, gửi nhận tin production và LLM/RAG với secret thật chưa được chạy.

## Lệnh tái chạy

```powershell
Set-Location backend
python -m pytest -q
Set-Location ..\frontend
npm.cmd test
npm.cmd run build
Set-Location ..
docker version
docker compose version
docker compose --env-file .\.env -p smh-l3-clean config --quiet
docker compose --env-file .\.env -p smh-l3-clean up -d --build
docker compose --env-file .\.env -p smh-l3-clean ps -a
```

Chỉ ghi migration/healthcheck là PASS sau khi container PostgreSQL và backend thực sự healthy, kiểm tra được Alembic revision của main/platform DB và upgrade tenant schema.
