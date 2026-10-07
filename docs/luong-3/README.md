# Luồng 3 – Evidence / Báo cáo nghiệm thu

Trang tổng hợp để nhóm xem nhanh implementation, test evidence, kết quả, giới hạn và tài liệu trình diễn. Trạng thái luôn phân biệt test tự động, tích hợp provider live và deployment runtime; không coi test harness là provider live.

## Tài liệu bàn giao

- [Acceptance checklist](./ACCEPTANCE_CHECKLIST.md) — từng requirement, implementation, file/module, test, result và evidence cần dùng khi demo.
- [Test report](./TEST_REPORT.md) — môi trường, lệnh đã chạy, kết quả và các giới hạn chưa xác minh.
- [User guide](./USER_GUIDE.md) — thao tác đăng nhập, shop, kênh, CRM/ticket và các module nghiệp vụ.
- [Deployment guide](./DEPLOYMENT_GUIDE.md) — Docker/Compose, PostgreSQL, env, migrations, healthcheck và troubleshooting.
- [Demo script](./DEMO_SCRIPT.md) — thứ tự trình bày cùng expected result và ảnh demo cần chụp.

## Evidence hiện có

| Requirement | Implementation | File/module liên quan | Test | Result | Evidence cần dùng khi demo |
|---|---|---|---|---|---|
| Admin xử lý ticket: phân công, status, comment/history | Ticket API/UI hiện hữu; quyền resource-aware cho read/write; SLA write admin-only | `backend/app/api/tickets.py`, `backend/app/auth/dependencies.py`, `frontend/src/App.vue` | `backend/tests/test_cskh_advanced_api.py` | API regression pass; browser demo chưa chạy | Ảnh list/detail, shop/channel, SLA, assignee, status, comment và history |
| Login → inbound CRM → hồ sơ khách | Auth, webhook/unified inbox và Customer 360 | `backend/app/api/auth.py`, webhook/inbox/customer APIs | `test_auth_api.py`, `test_unified_inbox_webhooks.py`, `test_customer_360_api.py` | PASS tự động trong test harness; provider live chưa chạy | Ảnh login, trạng thái kênh, conversation và Customer 360; ghi rõ live/simulation |
| Checkout/order | Sales order và payment API | `backend/app/api/sales.py`, `backend/app/api/payments.py` | `test_crm_two_shop_e2e.py`, sales tests trong full suite | PASS tự động; checkout live chưa xác minh | Ảnh order trạng thái draft/chuyển trạng thái |
| Appointment, quote, project | Industry/commercial modules | `backend/app/api/appointments.py`, `backend/app/api/commercial.py`, `frontend/src/IndustryModules.vue` | `test_industry_modules.py` | PASS test fixture; provider/calendar live chưa xác minh | Ảnh lịch, quote accepted, project liên kết |
| AI/RAG | Ingest/retrieval, citation, handoff và tenant scope | `backend/app/rag/`, chatbot APIs | `test_rag_components.py`, `test_rag_tenant_isolation.py`, auto-reply tests | PASS automated; LLM/embedding live chưa chạy | Ảnh câu trả lời và citation/handoff; không lộ tài liệu riêng |
| Authorization / multi-tenant | Role guard, permission service, tenant DB/context | `backend/app/auth/`, `backend/app/tenancy/`, CRM APIs | `test_cskh_advanced_api.py`, `test_api_tenant_isolation.py`, `test_crm_two_shop_e2e.py` | PASS cho các trường hợp được suite cover; override mọi resource chưa xác minh | Ảnh request shop A truy cập ID shop B bị từ chối; che user/dữ liệu |
| Regression | Backend và frontend suites | `backend/tests/`, `frontend/tests/` | pytest full; `npm.cmd test`; Vite build | Backend 872 passed/3 skipped; frontend 222 passed; build pass với chunk warning | Log đầu ra và commit hash |
| Migration/deployment PostgreSQL | Alembic main/platform/tenant, Docker Compose healthchecks | `backend/alembic*`, `docker-compose*.yml`, Dockerfiles | Migration contract tests; Docker build được thử | PostgreSQL migration/Compose healthcheck NOT VERIFIED: build pip lỗi read-only FS, BuildKit bus error/EOF, lệnh kế tiếp timeout | Cần ảnh/log healthy PostgreSQL, Alembic revisions main/platform/tenant, `/health`, `compose ps` từ lần chạy thật thành công |

## Nguyên tắc evidence

- Không thêm screenshot giả. Presenter lưu ảnh thật trong `docs/luong-3/evidence/` khi demo; che token, cookie, email cá nhân và dữ liệu khách.
- Không ghi PASS cho provider live, PostgreSQL migration, Compose startup/health nếu chưa lưu log/response thực tế.
- Kết quả đầy đủ và các lệnh chạy nằm trong [TEST_REPORT.md](./TEST_REPORT.md). Cách diễn giải nghiệm thu theo từng mục nằm trong [ACCEPTANCE_CHECKLIST.md](./ACCEPTANCE_CHECKLIST.md).

**Kết luận hiện tại:** Luồng 3 đã hoàn thiện trong phạm vi có thể kiểm chứng; Docker/PostgreSQL runtime chưa xác minh.
