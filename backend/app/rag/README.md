# RAG Module

Retrieval-Augmented Generation cho CRM Chatbot.

## Components

| File | Chức năng |
|------|-----------|
| `loader.py` | Đọc nội dung từ PDF, DOCX, TXT, CSV, HTML |
| `semantic_chunker.py` | Chia theo cấu trúc, câu hoàn chỉnh và ranh giới Gemini; thêm ngữ cảnh cho embedding |
| `chunker.py` | Chunker cũ, giữ cho tương thích và kiểm thử |
| `embedder.py` | Chuyển text → vector embedding (local Sentence-Transformers / Gemini / OpenAI) |
| `retriever.py` | Gemini vector + BM25 → RRF → Personalized PageRank |
| `prompt_builder.py` | Xây dựng prompt cho LLM từ context + query |
| `llm_caller.py` | Gọi LLM API, hỗ trợ streaming (Groq / Gemini / OpenAI) |
| `run_logger.py` | Ghi một bản ghi JSON cho mỗi lần RAG xử lý |

## Pipeline

### Data Ingestion (upload thủ công)
```
File upload → Structure-aware → Semantic Chunking → Contextual Embedding → pgvector DB
```

RAG sử dụng file do người bán upload thủ công trong mục **Kho tri thức**.
Có thể upload PDF, DOCX, TXT, CSV, Markdown hoặc HTML. Với catalog sản phẩm,
khuyến nghị dùng CSV có các cột như SKU, tên sản phẩm, danh mục, mô tả, giá và
tồn kho. Sau khi tài liệu đạt trạng thái `ready`, câu hỏi từ giao diện hoặc
webhook Facebook/Instagram sẽ được truy xuất từ tài liệu đó.

### Query (user hỏi)
```
User query → Gemini embedding + BM25 → RRF → PPR → prompt_builder.py → LLM → Response
```

Khi `LLM_PROVIDER=groq`, lỗi quota, xác thực, mất kết nối, timeout hoặc circuit
breaker mở sẽ chuyển sang `GEMINI_FALLBACK_MODEL` (mặc định
`gemini-3.5-flash-lite`). Để trống biến này để tắt dự phòng. Ưu tiên
`GEMINI_API_KEYS`; nếu không có, dùng các key embedding được khai báo riêng khi
`EMBEDDING_PROVIDER=gemini`. Không dùng key Groq để gọi Gemini.
Áp dụng cho trả lời thường, streaming và ảnh; streaming chỉ chuyển khi chưa phát
nội dung. Lỗi payload không chuyển provider; lỗi Gemini được trả về, không lặp
về Groq. Model embedding giữ nguyên để tương thích với chỉ mục hiện có.

`GEMINI_FALLBACK_MODELS` thêm model sau model dự phòng đầu tiên, mặc định
`gemini-3.1-flash-lite,gemini-3.6-flash`. Mỗi yêu cầu thử tối đa một model Groq
và ba model Gemini, theo thứ tự, không gọi song song. Model vừa lỗi được bỏ qua
60 giây trong mỗi tiến trình; khi hết thời gian này, Groq được thử lại trước.
Cooldown key và circuit Gemini tách theo model; giới hạn gọi đồng thời vẫn theo
provider. Streaming dừng chuyển model sau khi bất kỳ model nào đã phát nội dung.
Quota Gemini được tính theo project/model, không phải mỗi API key; nhiều key
trong cùng project không làm tăng quota. Không tự đổi model embedding.

### Ranh giới và ngữ cảnh

- Markdown, tiêu đề DOCX/HTML được giữ thành đường dẫn mục; bảng Markdown giữ tiêu đề cột trong mỗi dòng, CSV và sản phẩm có SKU không trộn sản phẩm.
- Đoạn văn dài tách tại câu hoàn chỉnh; số thập phân và một số viết tắt thông dụng được giữ. Câu không có ranh giới rõ được giữ nguyên, nên 800 ký tự là mục tiêu mềm, không phải giới hạn cắt cứng.
- Gemini chỉ trả chỉ số ranh giới cho các đơn vị nguồn. Tối đa 16 đơn vị/8.000 ký tự mỗi lượt và 32 lượt/tài liệu; lỗi, quota hoặc JSON sai dùng fallback cục bộ. Các giới hạn này giữ chi phí và độ trễ có trần.
- Embedding nhận tên tài liệu, đường dẫn mục, SKU và văn bản chunk. Ngữ cảnh được lấy từ nguồn, không tạo tóm tắt mới bằng LLM; `DocumentChunk.content` giữ nguyên nội dung để trích dẫn.
- Metadata `parent_start`, `parent_end`, `parent_id` cho phép dựng lại đoạn cha từ các chunk cùng tài liệu/shop mà không lưu bản sao đoạn cha.
- Retrieval mở rộng cả đoạn cha khi tối đa 16 chunk và 6.000 ký tự; nếu lớn hơn, lấy hàng xóm gần nhất. Tổng nội dung bổ sung tối đa 12.000 ký tự/lượt truy xuất; giữ các kết quả độc lập và thứ tự nguồn trong đoạn cha.
- Tài liệu cũ tiếp tục được đọc theo metadata cũ. Reindex từ bản gốc để áp dụng đầy đủ `structure-semantic-context-v2`; không trộn vector từ model khác trong một chỉ mục.

Retriever giữ nguyên Gemini embedding và chỉ mục vector hiện có. Mỗi truy vấn lấy
ứng viên vector theo độ gần cosine, đồng thời lấy ứng viên từ khóa có phạm vi
`business_id`, chuẩn hóa dấu tiếng Việt và ưu tiên SKU chính xác. BM25 chấm thứ
hạng từ khóa trên tối đa `max(200, top_k × 40)` ứng viên khớp; RRF hợp nhất thứ
hạng BM25 và vector mà không cộng trực tiếp hai thang điểm khác nhau; Personalized
PageRank dùng liên kết sản phẩm, chunk cha và chunk liền kề để xếp hạng lại tập
đã hợp nhất. Không đổi model embedding hoặc schema nên không cần re-embed kho tài
liệu. Nếu Gemini embedding hoặc truy vấn vector lỗi, BM25 vẫn chạy và tiếp tục
qua PPR. Candidate BM25 hiện được chấm trong Python trên tập giới hạn; theo dõi
Recall@K để quyết định khi nào cần chuyển thống kê/chấm điểm sang chỉ mục tìm kiếm
PostgreSQL khi kho tri thức lớn lên.

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

## RFM và gợi ý theo khách hàng

- Hồ sơ 360 và bộ gợi ý dùng chung `customer_rfm_profiles`: chỉ tính đơn
  `completed` hoặc `delivered` đã trả tiền, loại đơn hoàn toàn bộ/thất bại và
  đơn tương lai; tổng chi tiêu trừ phần hoàn tiền. Một đơn nhiều dòng vẫn chỉ
  tính một lần mua. Percentile lấy toàn bộ khách đã mua còn hiệu lực trong shop,
  không thay đổi theo tập khách đồng ý cá nhân hóa.
- Hồ sơ và tín hiệu sản phẩm được lưu trong `recommendation_customer_profiles.features`.
  Job phân nhóm sẵn có nạp trước cache; lượt gợi ý đầu tiên cũng tự tạo hồ sơ.
  Mỗi lượt chỉ kiểm tra các aggregate SQL để phát hiện đơn/tín hiệu thay đổi.
  Cache đổi khi trạng thái, tiền hoàn, tương tác hoặc catalog thay đổi; bucket
  một giờ cập nhật tuổi lần mua và độ suy giảm sở thích. Cache không thay thế
  kiểm tra đồng ý cá nhân hóa, giá hoặc tồn kho trực tiếp từ CRM.
- RFM điều chỉnh trọng số sở thích/mức phổ biến/RAG, không phải xác suất mua.
  Mức quan tâm nhập tay lấy bản ghi mới nhất, kể cả 0%; SKU được hỏi cụ thể,
  ngân sách, màu và tồn khả dụng là điều kiện bắt buộc trước xếp hạng.
- `RecommendationRequest.context` lưu `profile_cache_hit`, `profile_as_of`,
  trọng số và `ranking_elapsed_ms`; phần tính RFM/sở thích không gọi LLM.

Đo chất lượng với bộ câu hỏi/khách được gán nhãn độc lập. Trong JSONL cases,
thêm `expected_product_ids`, `forbidden_product_ids`, `expected_rfm_segment`;
predictions tương ứng có `recommended_product_ids`, `rfm_segment` cùng các
trường câu trả lời/nguồn hiện có. `evaluate_rag.py` xuất thêm Precision@K,
Recall@K, NDCG@K, MRR, tỷ lệ gợi ý sản phẩm cấm và độ đúng nhóm RFM.
Các ID được đối chiếu trong cùng shop; không gom ID giữa các tenant vào một case.

```powershell
python backend/scripts/evaluate_rag.py predictions.jsonl --cases cases.jsonl --min-product-ndcg 0.8 --max-forbidden-product-rate 0
```

Với bộ case chỉ đo gợi ý, thêm `--min-action-accuracy 0 --min-recall 0`.
Điểm xếp hạng và kiểm tra nội dung tự động không thay thế đánh giá ngữ nghĩa
câu trả lời của người thật. Kiểm thử hồi quy không chứng minh tăng chuyển đổi.
