# Checklist nghiệm thu Luồng 3

Trạng thái chỉ phản ánh evidence ghi nhận trong [TEST_REPORT.md](./TEST_REPORT.md). **PASS** là đã chạy/kiểm tra; **PARTIAL** là có evidence một phần hoặc thiếu live/deployment; **NOT RUN** là chưa chạy.

| Requirement | Implementation | File/module liên quan | Test | Result | Evidence cần dùng khi demo |
|---|---|---|---|---|---|
| Admin xem ticket/shop/kênh/customer/lỗi/priority/status/SLA | Ticket workspace hiện có list/detail và thông tin liên quan | `backend/app/api/tickets.py`, `frontend/src/App.vue` | `test_cskh_advanced_api.py`, full backend suite; UI source inspection | PARTIAL: chưa demo runtime browser | Chụp danh sách và chi tiết ticket với shop/kênh/SLA, dùng dữ liệu demo |
| Phân công người xử lý | Assignee chỉ user active cùng tenant | `backend/app/api/tickets.py`, `frontend/src/App.vue` | Ticket/API regression trong full suite | PARTIAL: chưa kiểm thử trình duyệt live | Chụp assignee trước/sau cập nhật |
| Cập nhật trạng thái và phản hồi | Patch ticket, comment, history | `backend/app/api/tickets.py`, `backend/tests/test_cskh_advanced_api.py` | `test_cskh_advanced_api.py`; 16 focused tests đạt | PASS (API regression) | Chụp status, comment và history |
| Owner/admin quyền shop | Role policy owner/admin; SLA update admin-only | `backend/app/auth/dependencies.py`, `backend/app/services/permission_service.py` | `test_auth_api.py`, `test_permissions_api.py`, focused ticket tests | PARTIAL: chưa test toàn bộ endpoints từng role | Chụp kết quả allow/deny cho thao tác đã kiểm chứng |
| Agent/support/sales/viewer | Role defaults và route guards; support shop xử lý ticket | `backend/app/services/permission_service.py`, API dependencies | Full backend suite; support ticket regression | PARTIAL: sales/viewer ma trận từng resource chưa chạy | Chụp response 403 cho hành động bị từ chối và role đã đăng nhập |
| Permission override allow/deny trên ticket | Resource-aware dependency cho ticket read/write | `backend/app/auth/dependencies.py`, `backend/app/api/tickets.py` | Deny read/write regression trong `test_cskh_advanced_api.py` | PASS cho ticket đã wire | Chụp override và request tương ứng trả 403 |
| Permission override customers/orders/documents/mọi CRM resource | Permission UI có cấu hình; nhiều route còn generic guard | `frontend/src/App.vue`, `backend/app/api/*` | Chưa có test end-to-end runtime bao phủ | NOT VERIFIED | Chỉ demo sau khi có test/runtime evidence riêng |
| Tenant A không đọc/sửa ticket B / giả mạo header | Auth tenant ưu tiên; truy vấn ticket theo tenant | `backend/app/tenancy/context.py`, `backend/app/api/tickets.py`, `backend/tests/test_cskh_advanced_api.py` | `test_authenticated_ticket_scope_ignores_foreign_business_header` | PASS cho ticket | Chụp A gọi ID B trả 404; dùng fixture an toàn |
| Tenant isolation customer/conversation/order/RAG | Tenant DB binding và truy vấn scoped | `backend/app/tenancy/*`, CRM APIs | `test_api_tenant_isolation.py`, `test_customer_360_api.py`, `test_crm_two_shop_e2e.py`, `test_rag_tenant_isolation.py` | PASS cho case trong suite, không bao quát mọi endpoint | Chụp account A/B và dữ liệu riêng biệt, che định danh |
| Login | Auth/session API | `backend/app/api/auth.py`, `backend/tests/test_auth_api.py` | Backend full suite | PASS automated; browser demo chưa chạy | Chụp đăng nhập thành công, che email/session |
| Kết nối channel live | OAuth/webhook/connector | `backend/app/api/*webhook*`, channel services | Test webhook/contract, không có provider credentials | PARTIAL; live NOT RUN | Chụp trạng thái provider verified khi demo live; nếu simulation phải ghi rõ |
| Inbound message → CRM conversation | Unified inbox webhook pipeline | `backend/tests/test_unified_inbox_webhooks.py`, inbox APIs | Webhook test harness trong full suite | PASS trong harness; provider live NOT RUN | Chụp tin nhắn và conversation; nêu rõ live hay fixture |
| Customer profile | Customer 360 API/UI | `backend/app/api/customers.py`, `frontend/src/App.vue` | `test_customer_360_api.py`, full suite | PASS automated | Chụp hồ sơ khách demo |
| Checkout/order | Sales order APIs | `backend/app/api/sales.py`, `backend/app/api/payments.py` | `test_crm_two_shop_e2e.py`, sales tests trong full suite | PASS automated; live checkout chưa xác minh | Chụp order draft và trạng thái thanh toán riêng |
| Appointment | Appointment API/module | `backend/app/api/appointments.py`, `frontend/src/IndustryModules.vue` | `test_industry_modules.py` | PASS fixture; live calendar chưa xác minh | Chụp lịch hẹn thử và trạng thái |
| Quote/project | Commercial APIs | `backend/app/api/commercial.py` | `test_industry_modules.py` | PASS automated fixture | Chụp quote accepted và project liên kết |
| AI/RAG | Retrieval, citation/handoff, tenant scope | `backend/app/rag/*`, chatbot API | RAG components, tenant-isolation/auto-reply trong full suite | PASS automated; provider live NOT RUN | Chụp câu trả lời, citation/handoff; không để lộ nội dung riêng |
| Backend regression | Existing tests giữ nguyên | `backend/tests/` | Full pytest | 872 passed, 3 skipped — PASS với skip | Lưu output lệnh và commit |
| Frontend regression | Node test suite | `frontend/tests/` | `npm.cmd test` | 222 passed, 0 failed — PASS | Lưu output test |
| Frontend production build | Vite | `frontend/package.json`, `frontend/vite.config.*` | `npm.cmd run build` | PASS; chunk >500 kB warning | Lưu output build |
| Migration chain/schema tests | Alembic và tenant migration contracts | `backend/alembic*`, `backend/tests/test_*migration*.py` | Migration tests trong full suite | PARTIAL; PostgreSQL runtime chưa có evidence | Chụp revisions/logs chỉ sau khi chạy PostgreSQL thật |
| Clean PostgreSQL migration | Compose PostgreSQL + main/platform/tenant migration | `docker-compose.yml`, `backend/Dockerfile` | Build lỗi trước healthy DB; migration NOT RUN | NOT VERIFIED | Cần log, healthy service, `alembic current` và tenant revision từ lần chạy thành công |
| Compose startup/healthcheck | Dev/production Compose | `docker-compose.yml`, `docker-compose.production.yml` | Docker CLI lần đầu phản hồi; build lỗi; lần sau timeout | NOT VERIFIED | Chụp `ps -a`, health status, `/health`, logs sau khi chạy được |
| Install/deployment docs | README, Compose/runbooks, guide | `README.md`, `docker-compose*.yml`, `docs/luong-3/DEPLOYMENT_GUIDE.md` | Đọc config; Compose runtime không đạt | PARTIAL | Chụp các service healthy và kiểm tra sau deploy |
| User guide | Quy trình thao tác nghiệp vụ | `docs/luong-3/USER_GUIDE.md` | Source/API cross-check | DOCUMENTED; chưa usability-test | Dùng guide trong demo và ghi nhận feedback |
| Deployment guide | Docker, PostgreSQL, migration, health, troubleshooting | `docs/luong-3/DEPLOYMENT_GUIDE.md`, `docs/runbooks/` | Runtime clean install chưa xác minh | DOCUMENTED; runtime partial | Lưu log deploy/revision khi chạy thành công |
| Demo script/evidence | Kịch bản theo thứ tự Luồng 3 | `docs/luong-3/DEMO_SCRIPT.md`, `docs/luong-3/evidence/` | Screenshot tự động chưa tạo | DOCUMENTED; evidence capture pending | Presenter chụp ảnh thật, che dữ liệu nhạy cảm |
| Commit/push branch | Feature branch hiện hành | `feat/luong-3-admin-integration-release` | Chỉ chạy sau final regression | Pending đến khi final tests đạt | Ghi commit hash và URL branch sau push |

## Yêu cầu file bằng chứng

- Automated: lưu test command/result/commit cùng report.
- Deployment: ghi Docker/Compose versions, `ps -a`, logs, migration revisions và health response.
- Demo: ảnh do người trình bày chụp trong `docs/luong-3/evidence/`; không dùng ảnh giả.
