# CRM Chatbot đa kênh

Kiến trúc ban đầu:

- Frontend: Vue.js
- Backend: FastAPI
- Database: PostgreSQL + pgvector
- Webhook: Facebook, Instagram, Shopee, TikTok
- RAG: để sẵn module phát triển sau
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

## 5. Lệnh chạy backend quan trọng

Đứng trong thư mục `backend` và chạy:

```bash
uvicorn app.main:app --reload
```

Không chạy `uvicorn main:app` vì file `main.py` nằm trong thư mục `app`.
