# RAG Module

Retrieval-Augmented Generation cho CRM Chatbot.

## Components

| File | Chức năng |
|------|-----------|
| `loader.py` | Đọc nội dung từ PDF, DOCX, TXT, CSV, HTML |
| `chunker.py` | Chia text thành chunks (Recursive Character Splitter) |
| `embedder.py` | Chuyển text → vector embedding (local Sentence-Transformers / Gemini / OpenAI) |
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

### Tải liệu: giới hạn, trạng thái và xử lý lỗi

- Giới hạn upload là **20 MiB**. Chỉ nhận PDF, DOCX, TXT, CSV, Markdown và HTML;
  chữ ký PDF, cấu trúc ZIP/DOCX, văn bản rỗng và payload nhị phân được kiểm tra
  trước khi tạo bản ghi hoặc tiêu quota.
- Cùng một nội dung SHA-256 chỉ được nạp một lần trong **mỗi shop**. Tải trùng trả
  `409` với header `X-Error-Code: duplicate_document`; shop khác vẫn có thể nạp
  cùng tệp.
- `DocumentOut.status`: `pending` → `processing` → `ready` hoặc `error`.
  `error_code` là mã ổn định cho giao diện; `error_message` là thông báo có thể
  hiển thị. `RagRunOut.status`: `queued`, `processing`, `completed`, `failed`;
  run lỗi có thể retry bằng `POST /api/documents/runs/{run_id}/retry`.
- Các mã thường gặp: `unsupported_file_type`, `empty_file`,
  `invalid_file_content`, `empty_extracted_text`, `empty_document`,
  `document_processing_failed`, `chunk_quota_exceeded`, `ai_quota_exceeded`.
  Lỗi từ upload cũng có `X-Error-Code`; upload lỗi định dạng trả `400`, tệp trùng
  trả `409`, quá quota trả `429`; tệp quá 20 MiB trả `400` với
  `X-Error-Code: file_too_large`.
- Reindex thay chunks cũ trong cùng transaction; xóa tài liệu xóa chunks liên
  quan nên truy xuất không thể tiếp tục trả nội dung đã xóa.

### Hợp đồng trích dẫn và handoff

`POST /api/chat` trả `answer_status` (`answered`, `no_context`, `service_error`)
và `handoff_required`. Mỗi nguồn trong `sources` có `citation_id`, `document_id`,
`chunk_id`, `filename`, `chunk_index`, `content`, `similarity` và `metadata`.
Nhãn `[Nguồn N]` trong câu trả lời khớp `citation_id`.

Nếu truy xuất không có đoạn vượt ngưỡng liên quan, hệ thống không gọi LLM và trả
thông báo chưa đủ thông tin với `answer_status=no_context`. Nếu LLM lỗi, chỉ trả
thông báo an toàn với `answer_status=service_error`; không trả một phần câu trả
lời chưa hoàn tất.

Câu trả lời sinh ra phải có ít nhất một `[Nguồn N]`/`[Source N]` hợp lệ. Hệ thống
từ chối giá tiền không có trong các đoạn được trích dẫn, kể cả nhầm VND/USD.
Đây là kiểm tra nguồn và số tiền, **không phải** chứng minh mọi mệnh đề đều đúng;
nhân viên vẫn cần duyệt câu trả lời có tác động đến giá/chính sách. Nếu kiểm tra
không đạt, API trả `no_context` và cờ bàn giao thay vì hiển thị câu chưa xác minh.

`POST /api/chat/stream` giữ các event `sources`, `chunk`, `done`. Event `done`
thêm `answer_status` và `handoff_required`; khi LLM hỏng giữa stream, event
`error` mang mã `service_unavailable`, `replace=true` và nội dung thay thế an toàn
để giao diện loại bỏ phần trả lời dở dang.

Trong auto-reply theo kênh, thiếu nguồn hoặc dịch vụ LLM lỗi sẽ gửi thông báo
phù hợp, tạo notification `rag_handoff_required`, chuyển `bot_mode=human`, và
ghi `resolution_outcome=needs_human`. Notification chỉ lưu mã lý do và ID hội
thoại/khách hàng để nhân viên mở đúng hồ sơ, không lưu câu hỏi. Endpoint chat nội bộ
chỉ trả cờ `handoff_required`; UI không được hiểu cờ này là hội thoại đã tự động
được chuyển cho một nhân viên cụ thể.

## Cấu hình (.env)

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
LLM_API_KEY=
LLM_MODEL=openai/gpt-oss-20b
# Có thể chọn: local | gemini | openai
EMBEDDING_PROVIDER=local
EMBEDDING_API_KEY=
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
EMBEDDING_DIMENSION=768
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=100
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.3
RAG_LOG_FILE=rag_runs.jsonl
RAG_AUTO_SEED_ENABLED=true
RAG_AUTO_SEED_DIR=sample_data/knowledge_base
RAG_AUTO_SEED_FAST_MODE=false
RAG_AUTO_REPLY_ENABLED=true
```

## RAG run log

Mỗi lần ingestion, chat, streaming chat hoặc auto-reply kết thúc sẽ ghi một dòng
JSON vào `backend/rag_runs.jsonl`. Log có `run_id`, thời gian bắt đầu/kết
thúc, trạng thái, số chunks tìm được/lưu, model, thời lượng và lỗi nếu có.
Log mới chỉ giữ độ dài/hash rút gọn của câu hỏi, số liệu xử lý và loại lỗi;
không lưu nội dung câu hỏi, câu trả lời, prompt, tên tệp hay chuỗi lỗi thô.
Các log cũ có thể cần được rà soát theo chính sách lưu giữ dữ liệu trước khi
đưa hệ thống vào môi trường thật.

Lưu ý: pgvector HNSW chỉ hỗ trợ tối đa 2.000 chiều. Với Gemini embedding 3.072
chiều, hệ thống bỏ qua HNSW để backend vẫn khởi động và dùng exact vector scan.

Groq được dùng để sinh câu trả lời qua API tương thích OpenAI. Gemini vẫn được
dùng cho embedding vì Groq không cung cấp embedding trong pipeline hiện tại.
