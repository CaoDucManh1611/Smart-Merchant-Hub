# Phản biện độc lập kế hoạch RAG

Ngày: 2026-11-04. Nhánh `codex/rag-rfm-all-updates-20261104`, HEAD `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`; số dòng thuộc working tree có thay đổi chưa commit lúc review.

Đã đọc tài liệu đính kèm như dữ liệu đánh giá và kế hoạch log 08. Không tìm thấy `AGENTS.md` khi kiểm kê repo và các thư mục cha. Chỉ ghi log 09; không sửa source/file 08, chạy server/test/benchmark, reindex, gửi Telegram hoặc commit/push. Đây là review tĩnh, không phải lỗi đã tái hiện runtime.

**Kết luận:** giữ thứ tự tám bước của log 08: giao diện chung tận dụng module cũ → catalog search có điều kiện → reindex kiểm soát → memory cấu trúc → structured outputs → adaptive retrieval với BM25 baseline/PPR off → claim verification → feedback có duyệt. Chưa đủ bằng chứng bật rộng.

## Năm findings quan trọng nhất

### P0 — Reindex có thể ghi lại giá/kho cũ vào dữ liệu đang bán

**Nguồn:** `backend/app/services/ingestion_service.py:351-357`; `backend/app/services/product_catalog_service.py:319-326`.
Reindex gọi đồng bộ catalog; sản phẩm còn nhãn `catalog_source=knowledge_document` và thuộc cùng tài liệu sẽ bị ghi lại price/stock/status từ bản gốc. Nếu kho đã giảm sau giao dịch nhưng nhãn nguồn vẫn giữ nguyên, thao tác xây lại chỉ mục có thể phục hồi kho cũ. Không áp kết luận này cho mọi sản phẩm: nhánh quản lý thủ công được bảo vệ riêng tại `backend/app/services/product_catalog_service.py:338-346`.
**Sửa nhỏ nhất:** reindex chỉ thay chunks/mappings; tách cập nhật catalog thành hành động có duyệt diff. Gate phải kiểm tra giá/kho/status không đổi khi chỉ reindex.

### P1 — Kiểm tra quota sau commit làm mất chỉ mục thay vì rollback

**Nguồn:** `backend/app/services/ingestion_service.py:327-339,391`; `backend/app/services/rag_job_service.py:117-152`.
Ingestion thay chunks rồi commit; worker mới reserve quota tăng thêm. Nếu vượt quota, worker xóa chunks và chuyển tài liệu sang error, không phục hồi bản cũ. API còn đổi status sang pending trước xử lý (`backend/app/api/documents.py:301-306`), trong khi retrieval chỉ đọc tài liệu ready (`backend/app/rag/retriever.py:1303-1309`), nên giữ rows cũ chưa bảo đảm liên tục phục vụ.
**Sửa nhỏ nhất:** reserve quota delta trước publish, giữ bản ready khi xây bản thay thế, chỉ đổi active sau kiểm tra và rollback cả status/mappings. Dùng job/API có tenant/write guard hiện có, không tạo đường reindex bỏ qua chúng.

### P1 — Thay catalog prompt chưa giải quyết đặt mục ngoài 100

**Nguồn:** `backend/app/services/business_request.py:24,33,63,91-98`; `backend/app/services/conversation_graph.py:519-534`.
Tập 100 sản phẩm/100 dịch vụ vừa vào evidence, vừa dùng xác thực offering_ref trong workflow, kể cả sau khóa row. Shortcut có thể tư vấn đúng SKU ngoài 100 nhưng workflow vẫn không nhận ref đó.
**Sửa nhỏ nhất:** lọc tenant/status/thuộc tính cứng trước LIMIT; ưu tiên SKU chính xác và tra lại exact ref độc lập danh sách tìm kiếm. Dùng cho cả tư vấn lẫn lựa chọn giao dịch, giữ khóa/khả dụng/xác nhận. Không chỉ tăng LIMIT hoặc coi 12 ứng viên là toàn catalog; phân trang khi khách hỏi toàn bộ.

### P1 — Budget tổng và hợp đồng retrieval chưa xuyên các đường gọi

**Nguồn:** Graph không truyền runtime options/timeout tại `backend/app/services/conversation_graph.py:796-799`, khác auto-reply tại `backend/app/services/auto_reply_service.py:4025,4454-4466`; API thường/stream có đường riêng tại `backend/app/api/chat.py:152-159,360-367`. Graph đã dùng lại shortcut cũ tại `backend/app/services/conversation_graph.py:250-268,292-309`.
Planner retry (`backend/app/services/conversation_graph.py:102-106`), composer retry/tính toán (`backend/app/services/conversation_graph.py:925-948`) và workflow recheck (`backend/app/services/business_request.py:72-76`) cùng đi qua fallback tối đa bốn model routes (`backend/app/rag/llm_caller.py:64-73,143-162`), mỗi route tối đa ba key attempts (`backend/app/services/api_key_pool.py:195-222`). Trần lý thuyết riêng một call non-stream là 12 attempts nếu đủ key và circuit chưa chặn; chưa phải số đo thực. Giới hạn từng tầng không phải trần cho cả turn.
**Sửa nhỏ nhất:** dùng hàm dịch vụ chung trên retriever/controller/prompt/guard cũ, giữ workflow/shortcut; truyền context quyền đã xác thực, hard filters và thời gian còn lại. Chốt trần pilot, ví dụ text read-only ≤3 call logic, ≤4 physical generation attempts tổng, chuyển provider ≤1 lần, retrieval ≤2 lượt; schema repair/verifier cùng chia budget. Đây là đề xuất chưa triển khai/đo; embedding/vision cần budget riêng nhưng chung deadline. Structured outputs phải kiểm tra khả năng cả adapter chính/fallback; JSON hợp lệ không thay xác thực quyền/nguồn. Giữ quyền CRM nhân viên (`backend/app/services/crm_knowledge.py:195-200,654-670`) tách phạm vi đơn của khách social (`backend/app/services/conversation_graph.py:774-780`); không nhận tenant/customer từ model.

### P1 — “Rẻ hơn” có thể chọn SKU cùng kích thước chưa được khách chọn

**Nguồn:** `backend/app/services/auto_reply_service.py:1964-1977,3086-3095`.
Khôi phục tập sản phẩm bằng alias hoặc chỉ kích thước lốp trên toàn bộ hàng active của shop rồi chọn min giá. Nhiều nhãn/SKU cùng size có thể mở tập sang mặt hàng chưa được bot nêu hoặc khách chọn; nhận diện đúng cụm “rẻ hơn” chưa đạt gate không trộn biến thể.
**Sửa nhỏ nhất:** lưu đúng IDs đã hiển thị/tập so sánh, scope tenant/customer/conversation, reset khi đổi chủ đề/ràng buộc và có TTL; đọc lại giá/kho, không cache chúng như sự thật. Tái dùng consent/validity hiện có (`backend/app/services/conversation_context.py:103-119`). Không rõ tập thì hỏi lại. Claim tương thích phải có bằng chứng gắn đúng SKU/thuộc tính; guard hiện có yêu cầu chứng cứ cùng dòng (`backend/app/rag/answer_guard.py:75-112`) nhưng tự ghi rõ không chứng minh mọi claim (`backend/app/rag/answer_guard.py:262-265`), nên formatter SQL/shortcut cũng cần kiểm tra, không chỉ composer.

## Bảng bảy gate

PASS bằng source chỉ xác nhận cơ chế hẹp, không phải PASS toàn gate. Không dùng pytest/benchmark cũ làm bằng chứng runtime cho nâng cấp này.

| Gate | Bằng chứng source / khoảng trống | Runtime đợt nâng cấp |
| --- | --- | --- |
| Nhất quán các kênh | Chưa PASS toàn gate: ba đường retrieval khác hợp đồng, finding budget; giữ workflow/shortcut và quyền riêng từng người gọi | Chưa xác minh |
| Tìm >100 | Chưa PASS toàn gate: evidence và xác thực workflow còn LIMIT 100, finding catalog | Chưa xác minh |
| Không trộn shop/SKU/biến thể | PASS hẹp: tenant/status trước LIMIT (`backend/app/rag/retriever.py:1297-1309`); còn tập so sánh mở theo size | Chưa xác minh |
| Hiểu “rẻ hơn” | PASS hẹp: chọn min giá hiện hành (`backend/app/services/auto_reply_service.py:3086-3095`); chưa bảo đảm đúng tập/TTL | Chưa xác minh |
| Thiếu nguồn hỏi lại | PASS hẹp: kiểm tương thích và composer hỏi lại sau retry (`backend/app/services/conversation_graph.py:945-953`); cần phủ cả formatter/câu nhiều ý | Chưa xác minh |
| Fallback 429 | PASS hẹp: nhận diện 429/cooldown/attempt cap (`backend/app/services/api_key_pool.py:26-44,101-108,195-222`); thiếu budget/deadline toàn turn | Chưa xác minh |
| Quality/latency/token/fallback trước–sau | Có logger/evaluator, chưa có baseline ghép cặp; evaluator tự ghi điểm là proxy và không xét turn trước (`backend/app/rag/evaluation.py:229-253`) | Chưa xác minh |

## Chặn bật rộng và phép đo còn thiếu

- Chặn reindex tới khi giữ được giá/kho/status và chỉ mục ready khi quota/error; chặn rollout khi chưa enforce trần call/token/deadline. 429/timeout/fallback cùng lỗi phải kết thúc hữu hạn; retry delivery không tạo lại giao dịch.
- Chặn mọi rò tenant/quyền, sai SKU/biến thể/giá/kho/tổng tiền, khẳng định tương thích hay giao dịch thiếu chứng cứ. Thiếu nguồn chỉ hỏi phần thiếu, vẫn trả phần đã xác minh. BM25 giữ baseline, PPR off; expansion giữ hard filters và trần retrieval, không nhân thêm lượt gọi.
- Còn thiếu replay ghép cặp cùng snapshot/code+dirty-diff/prompt/model/config: >100 goods/service/rental, hai shop có mã tương tự, nhiều nhãn cùng size, so sánh→rẻ hơn→đổi chủ đề→TTL/reset, thiếu nguồn/nguồn hết hiệu lực, workflow/shortcut/human mode, 429/timeout/fallback lỗi và delivery retry.
- Cần quality đúng/hữu ích/claim có nguồn/hỏi lại theo shop/nhóm câu; Recall@5/NDCG@5 sau reindex; p50/p95 queue→delivery và từng bước; tokens/cost/attempts/model thực/fallback kể cả lỗi. Scope log Graph bắt đầu sau các early return (`backend/app/services/conversation_graph.py:983-987`); logger ghi model cấu hình (`backend/app/rag/run_logger.py:84-96`), chưa thay thế trace model thực. Token thiếu ghi unknown, không ghi 0; cost estimate không phải hóa đơn. Chốt ngưỡng từ baseline, shadow/canary rồi mới bật rộng, giữ rollback.
- Feedback rating/reward tại `backend/app/api/chatbot.py:508-530` không phải duyệt kiến thức; giữ FAQ chưa duyệt như `backend/scripts/export_rag_faq_candidates.py:1-4`, bổ sung trace/bản sửa/người duyệt trước KB/training. Không dùng hội thoại synthetic/test làm hành vi mua thật hoặc gold đã duyệt.

Giới hạn: chỉ đối chiếu source và log 08; chưa xác minh DB, deploy config, provider/schema support hay bất kỳ runtime gate nào. Các hậu quả nêu trên là suy luận có điều kiện từ source. Không mở rộng audit thêm.
