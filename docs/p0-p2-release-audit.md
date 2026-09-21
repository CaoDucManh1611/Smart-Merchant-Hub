# Tổng kiểm thử phát hành P0 → P2

**Ngày:** 2026-09-13
**Branch:** `codex/p0-p2-release-audit`
**Baseline:** `crm-completion` tại `8fbb3f2` cộng toàn bộ thay đổi P0–P2 đã kiểm thử
**Môi trường:** Windows, Docker Compose, PostgreSQL/pgvector 16, Redis 7.4,
FastAPI, worker và Vue/Vite

## Kết luận quản lý chất lượng

**PASS cho code review, local integration và staging/UAT. Chưa được gọi là public
production certified.**

Toàn bộ regression hiện xanh, stack chạy đúng từ branch này và dữ liệu restore không
bị thay đổi. Các cổng còn chặn production đều cần quyền hoặc hạ tầng bên ngoài:
token Meta mới, public HTTPS route, đăng ký webhook tại dashboard provider, cấu hình
production bằng secret manager/non-superuser database role và lựa chọn payment gateway.

P0 và P1 đã có implementation cùng test nội bộ đầy đủ cho phạm vi mã nguồn. P2 mới
đạt các phần đã hiện thực; các tích hợp logistics/payment/invoice thật, saved views và
bulk actions tổng quát, agency white-label và schema-per-tenant vật lý vẫn là GAP, không
được báo cáo sai thành hoàn tất.

## Bằng chứng cuối

| Cổng kiểm tra | Kết quả |
|---|---:|
| Backend unit/API/integration/business regression | **455 passed, 0 failed, 0 warnings** |
| Frontend behavior/contract regression | **106 passed, 0 failed** |
| Frontend production build | **PASS — 20 modules transformed** |
| Python compile check | **PASS** |
| Git whitespace/error check | **PASS** |
| Docker runtime | **5/5 running và healthy** |
| Backend `/health` | **HTTP 200 / `ok`** |
| OpenAPI | **190 paths / 241 operations / 241 operation IDs duy nhất** |
| Alembic | **`20260919_0043`** |
| PostgreSQL tenant RLS | **59 policies / 59 tables** |
| RLS probe với tenant không tồn tại | **0 customer rows visible** |
| Dữ liệu runtime | **8 conversations / 713 messages** trong `crm16_restore` |
| Google GenAI trong image | **`google-genai 1.75.0`** |

## Kiểm thử UI thật

- 12/12 mục điều hướng có phản hồi và đổi đúng workspace: Inbox, Knowledge Base,
  Sản phẩm, Đơn bán, Đơn nhập, Sales Pipeline, Ticket & SLA, Workflow, AI Rule Lab,
  AI Assistant, Báo cáo và Settings.
- Thao tác nhanh mở dialog; thông báo mở popover; thu gọn sidebar thay đổi trạng thái;
  trợ giúp đưa người dùng tới Settings.
- Tìm `Phulee` trả đúng 2 hội thoại; lọc Instagram sau khi xóa tìm kiếm trả đúng 2;
  inbox runtime tải đủ 8 hội thoại và không hiện lỗi API.
- Ảnh có dữ liệu tải được và có kích thước thật. Avatar không lấy được từ provider rơi
  về initials/channel fallback, không còn hiển thị ảnh vỡ hoặc nút giả.
- Mọi button render trực tiếp đều có handler hoặc hành vi form; mọi handler tham chiếu
  trong template đều tồn tại; các thao tác mạng quan trọng có busy/success/error state.

## Lỗi tìm thấy và đã sửa trong vòng tổng kiểm thử

1. Test runner thừa kế `.env` local (`Redis`, SMTP/Twilio), gây gọi mạng thật và fail
   không ổn định. Test bootstrap nay ép SQLite, memory limiter, OTP disabled và không
   đọc secret manager runtime.
2. Tải CSV dùng thẻ link nên không gửi JWT và tenant header, có thể mở tab 401/403.
   Export nay dùng `apiFetch`, Blob download và phản hồi thành công/thất bại rõ ràng.
3. Nhiều nút mạng im lặng khi API lỗi: auto reply, notification, Meta, documents,
   follow-up và CSAT. Đã thêm kiểm tra HTTP status, khóa double click và thông báo UI.
4. Hủy follow-up thiếu xác nhận. Đã thêm confirm và báo lỗi có thể phục hồi.
5. Dispatch workflow lấy danh sách sau khi worker đã đổi trạng thái nên trả mảng rỗng.
   Đã chụp run IDs trước dispatch và trả đúng kết quả.
6. Dispatch workflow dùng `GET` cho side effect. Đã đổi sang `POST` và bắt buộc quyền
   ghi để tránh prefetch/replay ngoài ý muốn.
7. Shopee webhook bị nhân đôi prefix. OpenAPI hiện chỉ còn
   `/api/webhooks/shopee`; contract test ngăn route lỗi quay lại.
8. SDK `google.generativeai` đã hết vòng đời hỗ trợ. Sinh nội dung và embedding đã
   chuyển sang `google.genai`, có test request/response và image Docker mới.
9. Một test dùng `datetime.utcnow()` deprecated. Đã chuyển sang thời gian UTC rõ ràng.
10. Stack trước kiểm tra đang bind backend/frontend từ thư mục `p1`; Compose đã được
    recreate từ chính workspace branch hiện tại và vẫn giữ database restore.
11. Script tổng từng dùng lại một pytest temp directory trong OneDrive nên có thể bị
    Windows/antivirus khóa. Mỗi lần chạy nay dùng một OS temp directory duy nhất và
    đã qua lại toàn bộ 455 backend cases.

## P0 — trạng thái

- Restore/migration, chữ ký và replay webhook giả lập, Redis shared limiter, secret
  loading/rotation, SMTP/Twilio adapter, backup failure detection, metrics và alerts:
  **PASS**.
- Live credential read-only: Telegram, Zalo, Groq, Gemini, SMTP, Twilio: **PASS**.
- Facebook/Instagram token: **FAIL bên ngoài — token hết hạn**.
- Public webhook HTTPS: **BLOCKED bên ngoài — URL hiện trả 404**.
- Runtime local vẫn là `ENVIRONMENT=development` và database user `postgres`; đây
  không phải cấu hình được phép dùng cho production.

## P1 — trạng thái

- Onboarding, plan/subscription/payment ledger, entitlement/quota, tenant context,
  JWT/session/API isolation, 59 RLS policies, Platform Admin và data lifecycle:
  **PASS local/staging**.
- Conversation → Revenue, grounded AI, combo quote, proactive CRM, explainability và
  customer identity đa kênh: **PASS**.
- Payment automation với gateway thật và production secret/monitor destination:
  **chưa cấu hình bên ngoài**.

## P2 — trạng thái

- Workflow builder/worker/idempotency/retry/tenant isolation, logistics metadata,
  payment/refund ledger, purchase receipt, saved customer segment và schema registry
  rehearsal: **PASS**.
- Saved views đa module và bulk actions: **GAP**.
- Adapter hãng vận chuyển, payment gateway và hóa đơn điện tử thật: **GAP**.
- Agency multi-shop, white-label và schema/database vật lý riêng: **GAP**.

## Cổng bắt buộc trước production

1. Refresh token Facebook Page/Instagram và cập nhật channel credentials đã mã hóa.
2. Cấp domain HTTPS thật, route `/api/webhooks/*` vào backend và đăng ký lại Meta,
   Telegram, Zalo webhook.
3. Đặt `ENVIRONMENT=production`, `AUTH_SECRET`/encryption key đủ mạnh, CORS/hosts
   allowlist, HTTPS/HSTS và database role không phải superuser.
4. Chọn gateway thanh toán và kiểm thử chữ ký webhook, settlement, refund/chargeback.
5. Chạy callback thật có kiểm soát cho bốn kênh và xác nhận đúng một event/message,
   không duplicate và không cross-tenant.

Không có `.env`, dump database, token hoặc dữ liệu hội thoại được đưa vào Git.
Script `scripts/release-audit.ps1` cho phép lặp lại các gate tự động trên máy phát hành.
