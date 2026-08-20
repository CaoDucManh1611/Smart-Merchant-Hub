# RAG Module

Retrieval-Augmented Generation cho CRM Chatbot.

## Components

| File | Chức năng |
|------|-----------|
| `loader.py` | Đọc nội dung từ PDF, DOCX, TXT, CSV, HTML |
| `chunker.py` | Chia text thành chunks (Recursive Character Splitter) |
| `embedder.py` | Chuyển text → vector embedding (Gemini / OpenAI) |
| `retriever.py` | Hybrid retrieval: pgvector + tìm kiếm từ khóa |
| `prompt_builder.py` | Xây dựng prompt cho LLM từ context + query |
| `llm_caller.py` | Gọi LLM API, hỗ trợ streaming (Groq / Gemini / OpenAI) |
| `run_logger.py` | Ghi một bản ghi JSON cho mỗi lần RAG xử lý |

## Pipeline

### Data Ingestion (upload thủ công)
```
File upload → loader.py → chunker.py → embedder.py → pgvector DB
```

RAG sử dụng file do người bán upload thủ công trong mục **Kho tri thức**.
Có thể upload PDF, DOCX, TXT, CSV, Markdown hoặc HTML. Với catalog sản phẩm,
khuyến nghị dùng CSV có các cột như SKU, tên sản phẩm, danh mục, mô tả, giá và
tồn kho. Sau khi tài liệu đạt trạng thái `ready`, câu hỏi từ giao diện hoặc
webhook Facebook/Instagram sẽ được truy xuất từ tài liệu đó.

### Query (user hỏi)
```
User query → embedder.py → retriever.py → prompt_builder.py → llm_caller.py → Response
```

Retriever luôn thử kết hợp tìm kiếm ngữ nghĩa với từ khóa. Vì vậy các mã SKU,
tên sản phẩm và tài liệu chưa có embedding vẫn có thể được tìm thấy bằng lexical
fallback. Khi xử lý lại một tài liệu, các chunks cũ được thay thế trong cùng
transaction để không tạo dữ liệu trùng.

## API Endpoints

- `POST /api/documents/upload` – Upload tài liệu
- `GET /api/documents` – Danh sách tài liệu
- `GET /api/documents/{id}/chunks` – Kiểm tra chunks và embedding
- `DELETE /api/documents/{id}` – Xóa tài liệu
- `POST /api/chat` – Chat (non-streaming)
- `POST /api/chat/stream` – Chat (SSE streaming)

## Cấu hình (.env)

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
LLM_API_KEY=
LLM_MODEL=openai/gpt-oss-20b
EMBEDDING_PROVIDER=gemini
EMBEDDING_API_KEY=your-gemini-api-key
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSION=3072
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=100
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.3
RAG_LOG_FILE=rag_runs.jsonl
RAG_AUTO_SEED_ENABLED=true
RAG_AUTO_SEED_DIR=sample_data/knowledge_base
RAG_AUTO_SEED_FAST_MODE=false
```

## RAG run log

Mỗi lần ingestion, chat, streaming chat hoặc auto-reply kết thúc sẽ ghi một dòng
JSON vào `backend/rag_runs.jsonl`. Log có `run_id`, thời gian bắt đầu/kết
thúc, trạng thái, số chunks tìm được/lưu, model, thời lượng và lỗi nếu có.
Query và câu trả lời chỉ được ghi ở dạng rút gọn hoặc số ký tự, không ghi toàn bộ
prompt/answer.

Lưu ý: pgvector HNSW chỉ hỗ trợ tối đa 2.000 chiều. Với Gemini embedding 3.072
chiều, hệ thống bỏ qua HNSW để backend vẫn khởi động và dùng exact vector scan.

Groq được dùng để sinh câu trả lời qua API tương thích OpenAI. Gemini vẫn được
dùng cho embedding vì Groq không cung cấp embedding trong pipeline hiện tại.
