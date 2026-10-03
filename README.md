# CRM Chatbot đa kênh

Kiến trúc ban đầu:

- Frontend: Vue.js
- Backend: FastAPI
- Database: PostgreSQL + pgvector
- Webhook: Facebook, Instagram, Shopee, TikTok
- RAG: PostgreSQL + pgvector, hỗ trợ upload tài liệu, hybrid retrieval và chatbot có nguồn

Tài liệu Kho kiến thức mới được chia theo cấu trúc/đoạn văn và giữ nguyên văn bản gốc. Nếu cấu hình `GEMINI_API_KEY` hoặc `GEMINI_API_KEYS` trong `backend/.env`, hệ thống gửi từng nhóm tối đa 16 đoạn/8.000 ký tự tới Google Gemini để chọn ranh giới ngữ nghĩa; không gửi file gốc hay thông tin shop kèm theo. Gemini lỗi, hết quota hoặc chưa cấu hình key thì dùng chia cục bộ; tối đa 32 lượt Gemini cho mỗi tài liệu. Tài liệu đã nạp trước đây chỉ đổi cách chia khi được reindex; không tự động reindex hay xóa dữ liệu cũ.
- Docker Compose
- GitHub Actions CI

## Chạy ứng dụng trên Windows PowerShell

Cần mở Docker Desktop trước. Các lệnh dưới đây chạy tại thư mục gốc dự án
(thư mục chứa `docker-compose.yml`), ví dụ trên máy hiện tại:

```powershell
Set-Location 'C:\Users\DUC_STRONG\Smart-Merchant-Hub-full-stack-ready'
docker info
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
if (-not (Test-Path 'backend\.env')) { Copy-Item 'backend\.env.example' 'backend\.env' }
```

Nếu vừa tạo `.env` ở thư mục gốc, mở file đó và điền các dòng sau. Dùng cùng
một mật khẩu cho PostgreSQL và URL; trong Docker, host là `db`, không phải
`localhost`. `backend\.env` chứa cấu hình riêng của backend, không dùng làm
`--env-file` cho Compose. Không ghi mật khẩu thật vào Git:

```dotenv
POSTGRES_DB=crm_chatbot
POSTGRES_USER=crm_app
POSTGRES_PASSWORD=YOUR_LOCAL_PASSWORD
DATABASE_URL=postgresql+psycopg://crm_app:YOUR_LOCAL_PASSWORD@db:5432/crm_chatbot
```

Compose tự tạo URL mặc định cho database platform/tenant và Redis từ các biến
trên. Nếu đã có dữ liệu Docker, giữ nguyên mật khẩu hiện tại trong `.env`.

Giữ nguyên tên project Compose đã dùng để tiếp tục dùng đúng volume dữ liệu.
Trong hướng dẫn này, tên project là `smart-merchant-hub-runtime`:

```powershell
docker compose --env-file .\.env -p smart-merchant-hub-runtime up -d --build
docker compose --env-file .\.env -p smart-merchant-hub-runtime ps -a
Start-Process 'http://127.0.0.1:5173/'
```

Giao diện ở <http://127.0.0.1:5173/>, tài liệu API ở
<http://127.0.0.1:8000/docs>. Lần chạy đầu, backend tự áp dụng Alembic
migration và có thể mất vài phút. Nếu container chưa lên, xem log:

```powershell
docker compose --env-file .\.env -p smart-merchant-hub-runtime logs --tail 100 db backend frontend worker
```

Không dùng `docker compose down -v` khi muốn giữ dữ liệu PostgreSQL. Nếu cần
tạo tài khoản chủ shop trên database mới, xem [hướng dẫn backend](backend/README.md#crm-operations).

## Chatbot runtime

Các tính năng chatbot nâng cao được quản lý theo từng `X-Business-Id`:

- `GET/PUT /api/chatbot/config`: bật/tắt bot, Top-K/ngưỡng RAG và giờ hoạt động.
- `GET/POST/PATCH/DELETE /api/chatbot/canned-responses`: mẫu trả lời nhanh như `/cod`.
- `POST /api/chatbot/conversations/{id}/pause|resume`: nhân viên tiếp quản hoặc trả hội thoại về bot.
- `GET /api/chatbot/conversations/{id}/memory` và `POST /api/chatbot/conversations/{id}/tools/execute`: memory và allow-list tool có kiểm tra tenant.
- `GET/POST /api/chatbot/followups`, `POST /api/chatbot/followups/dispatch`: nhắc lại đơn nháp/bỏ giỏ và chăm sóc chủ động. Báo giá bỏ dở được nhắc sau 2 giờ; đơn chuyển `delivered` được nhắc chăm sóc sau 24 giờ; khách xác nhận hoặc hủy thì nhắc bỏ giỏ được hủy.
- `GET /api/chatbot/csat`: danh sách phản hồi CSAT và điểm trung bình theo shop. Khi ticket chuyển sang `resolved` hoặc `closed`, hệ thống tự gửi khảo sát 1–5 sao sau follow-up.
- Provider LLM/embedding có thể nhận danh sách key phân tách bằng dấu phẩy qua `GROQ_API_KEYS`, `LLM_API_KEYS` và `EMBEDDING_API_KEYS`. Hệ thống xoay vòng theo lượt, tạm ngưng key khi gặp lỗi quota/rate-limit/auth và không ghi raw key vào log.

Worker CRM hiện có thể xử lý job `chatbot.followup`; môi trường development có thể gọi
endpoint dispatch theo lịch (ví dụ mỗi phút). Outbound webhook và setup wizard
không nằm trong phạm vi bản này.

Kiểm tra phiên bản schema:

```powershell
docker compose --env-file .\.env -p smart-merchant-hub-runtime exec backend python -m alembic current
```

Schema được quản lý bằng Alembic trong `backend/alembic/`; không cần xóa DB
hiện tại để cập nhật.

## Media đa kênh

Ảnh, âm thanh, sticker, video và file được chuẩn hóa qua cùng contract rồi lưu
tenant-scoped trong `message_attachments`. Backend tự chạy migration khi khởi động.

Inbox tải media qua `GET /api/media/{attachment_id}`; API tự kiểm tra tenant và
không đưa channel token ra trình duyệt. Nhân viên gửi media bằng
`POST /api/conversations/{conversation_id}/send-media`. Xem chi tiết endpoint,
giới hạn provider và lệnh kiểm thử trong [`backend/README.md`](backend/README.md).

## Bàn giao cho người khác chạy từ Git

Branch bàn giao gồm toàn bộ frontend, backend, Docker Compose, migration và seed
dữ liệu mặc định. Database không được commit kèm mật khẩu hoặc dữ liệu shop thật;
PostgreSQL sẽ tự tạo ba database (`crm_chatbot`, `crm_platform`, `crm_tenant`)
và backend tự chạy migration khi khởi động.

Sau khi clone, làm theo mục [Chạy ứng dụng trên Windows PowerShell](#chạy-ứng-dụng-trên-windows-powershell)
và thay đường dẫn thư mục trong ví dụ bằng nơi vừa clone. Mở frontend tại
<http://localhost:5173/>, API tại <http://localhost:8000/docs>.
Không copy các file `.env` thật, token kênh, cookie TikTok hoặc database dump lên
Git. Nếu cần chuyển dữ liệu thật, dùng file dump riêng và khôi phục vào PostgreSQL
sau khi các container đã khởi động.

## 4. Facebook Webhook

Callback URL:

```text
https://TEN-MIEN-PUBLIC/api/webhooks/facebook
```

Verify Token:

```text
Giá trị riêng do bạn tạo và cấu hình trong `backend/.env` (`FACEBOOK_VERIFY_TOKEN`).
Không còn giá trị mặc định dùng chung.
```

Có thể đổi trong:

```text
backend/.env
```

## 5. Meta OAuth (Facebook Page + Instagram)

OAuth được mở từ tab **Cài đặt** trên Web UI. Trước khi bấm **Kết nối với Facebook**, điền các biến sau vào `backend/.env`:

```env
META_APP_ID=ID_CUA_META_APP
META_APP_SECRET=SECRET_CUA_META_APP
META_GRAPH_VERSION=v26.0
META_OAUTH_REDIRECT_URI=https://TEN-MIEN-PUBLIC/api/oauth/meta/callback
FRONTEND_BASE_URL=http://localhost:5173
```

Trong Meta Developer, thêm Redirect URI đúng bằng:

```text
https://TEN-MIEN-PUBLIC/api/oauth/meta/callback
```

OAuth sẽ đổi authorization code thành Page Access Token, tự chọn Page, lấy Instagram Professional Account liên kết và tự đăng ký webhook `messages` cho Page. Token được lưu trong PostgreSQL `app_settings`, không cần dán token thủ công vào UI.

## 6. Lệnh chạy backend quan trọng

Đứng trong thư mục `backend` và chạy:

```bash
uvicorn app.main:app --reload
```

Không chạy `uvicorn main:app` vì file `main.py` nằm trong thư mục `app`.

## 7. Thiết kế CSDL và Use Case

Thiết kế dữ liệu nền, ma trận Use Case và các sơ đồ Mermaid nằm tại:

- `docs/database-use-cases.md`
- `docs/diagrams/erd.mmd`
- `docs/diagrams/system-use-case.mmd`
- `docs/diagrams/conversation-flow.mmd`
- `docs/diagrams/rag-flow.mmd`
