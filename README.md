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
cd backend
copy .env.example .env
cd ..
docker compose up --build
```

Backend sẽ tự khởi tạo pgvector, các bảng dữ liệu và vector index khi bắt đầu.

## 4. Facebook Webhook

Callback URL:

```text
https://TEN-MIEN-PUBLIC/api/webhooks/facebook
```

Verify Token mặc định:

```text
crm_chatbot_2026
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
