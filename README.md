# CRM Chatbot đa kênh

Kiến trúc ban đầu:

- Frontend: Vue.js
- Backend: FastAPI
- Database: PostgreSQL + pgvector
- Webhook: Facebook, Instagram, Shopee, TikTok
- RAG: PostgreSQL + pgvector, hỗ trợ upload tài liệu, hybrid retrieval và chatbot có nguồn
- Docker Compose
- GitHub Actions CI

## 1. Chạy backend không dùng Docker

Nếu muốn chạy FastAPI bằng Python nhưng vẫn tự bật PostgreSQL/pgvector, dùng script ở thư mục gốc:

```powershell
.\start_dev.ps1
```

Script sẽ tự gọi Docker cho service `db`, chờ database sẵn sàng, sau đó backend tự tạo/cập nhật schema. Không cần mở DBeaver để chạy SQL.

Nếu database đang có các bảng cũ và cần đưa về đúng 20 bảng để vẽ ERD, chạy một lần:

```powershell
.\reset_database.ps1
```

Script sẽ hỏi nhập `RESET`, xóa toàn bộ bảng trong schema `public`, rồi tạo lại đúng 20 bảng hiện tại. Lệnh này xóa dữ liệu cũ.

```bash
cd backend
copy .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Mở:

- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs

## 2. Chạy frontend không dùng Docker

```bash
cd frontend
npm install
npm run dev
```

Mở:

- http://127.0.0.1:5173

## 3. Chạy toàn bộ bằng Docker

Tạo file môi trường trước:

```bash
copy .env.example .env
cd backend
copy .env.example .env
cd ..
docker compose up --build
```

Trước khi chạy, thay các giá trị `CHANGE_ME` trong `.env` bằng thông tin
riêng. Compose dùng `DATABASE_URL` ở file `.env` gốc để kết nối tới service
`db`; tuyệt đối không commit file `.env`.

Backend sẽ tự khởi tạo pgvector và các bảng dữ liệu khi bắt đầu. Sau mỗi lần
cập nhật tính năng, áp dụng migration mới bằng:

```powershell
docker compose exec backend python -m alembic upgrade head
```

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
docker compose exec backend python -m alembic current
```

Schema được quản lý bằng Alembic trong `backend/alembic/`; không cần xóa DB
hiện tại để cập nhật.

## 3.1 Media đa kênh

Ảnh, âm thanh, sticker, video và file được chuẩn hóa qua cùng contract rồi lưu
tenant-scoped trong `message_attachments`. Sau khi cập nhật code, chạy:

```powershell
docker compose exec backend python -m alembic upgrade head
```

Inbox tải media qua `GET /api/media/{attachment_id}`; API tự kiểm tra tenant và
không đưa channel token ra trình duyệt. Nhân viên gửi media bằng
`POST /api/conversations/{conversation_id}/send-media`. Xem chi tiết endpoint,
giới hạn provider và lệnh kiểm thử trong [`backend/README.md`](backend/README.md).

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
