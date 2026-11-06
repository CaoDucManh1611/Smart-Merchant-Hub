# 18 — Phản biện độc lập bản tích hợp RAG tám hạng mục

Ngày 2026-11-04. Review trên working tree chưa commit của nhánh `codex/rag-rfm-all-updates-20261104`; line numbers là ảnh chụp tại thời điểm review. Chỉ đọc source, tests và logs 08, 09, 11–14, 17, 20, 21. Không sửa code, không chạy lại full suite, không gọi provider, không gửi tin, không reindex dữ liệu thật và không commit/push. Các số test dưới đây **do log triển khai ghi nhận**, không phải lần test độc lập của reviewer.

## Kết luận và thước chấm

**Code đã có đủ tám điểm nối nhưng chưa đủ bằng chứng để khẳng định RAG trả lời thông minh hơn hoặc bật rộng nhiều shop.** Không xác nhận P0 đã tái hiện ở bản mới. Có bốn P1 cần khép trước production. Chế độ BM25/PPR off đang là baseline phù hợp để giữ trong lúc đo.

Điểm *mức bằng chứng triển khai*, không phải điểm thông minh: **0** chưa có; **1** có code/artifact nhưng chưa nối hết hành vi mục tiêu; **2** có đường thực thi và test hẹp/fixture; **3** có replay ghép cặp và số liệu live theo shop/kênh chứng minh gate. Điểm hiện tại **15/24** (7 mục đạt 2, feedback đạt 1). Các mục đạt 2 đều **chưa đạt mức 3**. Test pass chỉ xác minh hành vi được fixture mô tả; không đo trả lời đúng trên lưu lượng thật.

| # | Hạng mục | Điểm | Code và test evidence | Phần chưa chứng minh |
| --- | --- | ---: | --- | --- |
| 1 | Graph/RAG chung | 2 | `backend/app/rag/serving.py:14-68`; Graph `backend/app/services/conversation_graph.py:133`, auto-reply `backend/app/services/auto_reply_service.py:42`; log 21: serving/graph/routing/auto-reply trong lượt 423 pass | Shortcut, workflow, API và kênh có các nhánh nghiệp vụ khác nhau; chưa replay cùng context qua adapter thật hoặc đo end-to-end |
| 2 | Catalog có điều kiện | 2 | `backend/app/services/catalog_search.py:179-270` lọc tenant/status/SKU/attributes/budget trước LIMIT; exact ref `:60-82`; log 11: 51 catalog tests trên PostgreSQL disposable, gồm item ngoài 100 | Query plan/latency với catalog shop lớn, tồn theo kênh, câu yêu cầu toàn bộ danh mục và đủ kiểu thuộc tính ngành |
| 3 | Reindex an toàn | 2 | `backend/app/services/ingestion_service.py:78,110,354-389`; queue/worker `backend/app/api/documents.py`, `backend/app/services/rag_job_service.py`; dry-run `backend/scripts/audit_safe_reindex.py`; log 21: nhóm ingestion/quota 102 pass | Chưa audit/apply tài liệu thật; chưa có version để rollback *sau* publish hoặc recovery bền vững khi chết giữa hai DB |
| 4 | Memory cấu trúc | 2 | `backend/app/services/conversation_memory.py:174-290`; central outbound persistence `backend/app/services/auto_reply_service.py:868-918`; Graph load `backend/app/services/conversation_graph.py:994-998`; log 20: direct-RAG memory test trong 99 pass | Chưa replay follow-up trên kênh thật; chỉ nhớ product IDs, không phải mọi entity dịch vụ/thuê; đường calendar cũ vẫn có fallback lịch sử dài (P1) |
| 5 | Structured output | 2 | Pydantic planner/answer `backend/app/rag/output_contracts.py:6-48`, native transport và budget trong `backend/app/rag/llm_caller.py`, `backend/app/rag/turn_budget.py`; log 14: 75 pass fake SDK | Chưa gọi provider/model thật trong container/staging; injected test callable đi legacy JSON; JSON schema không chứng minh đúng nghĩa câu |
| 6 | Adaptive retrieval | 2 | `backend/app/rag/serving.py:39-99` giữ hard filters, PPR off, bounded retry và không so score khác mode; auto-reply có controller riêng; log 21: serving/auto-reply 82 pass sau sửa | Chưa chứng minh NDCG/độ hữu ích tăng; nhánh retry có thể tốn request/embedding mà không đổi kết quả; thiếu p95/cost ghép cặp |
| 7 | Claim verification | 2 | `backend/app/rag/claim_verification.py:8-60`, graph `backend/app/services/conversation_graph.py:943-985` kiểm source, giá và phép tính; tests serving có ca sai giá hai sản phẩm | Tên rút gọn/alias có thể không kích hoạt đối chiếu giá theo hàng (P1); chưa đo chính sách/fitment/nguồn hết hiệu lực trên nhãn người |
| 8 | Learning from feedback | 1 | Export handoff + staff, consent hiện hành `backend/scripts/export_rag_faq_candidates.py:228-307`; approve recheck `backend/scripts/review_rag_feedback.py:24-33,142-160`; log 20: 99 pass | Chỉ tạo seed JSONL, **chưa có đường import KB/train/withdrawal để học thực tế**; scope `personalization` chưa được xác nhận cho tái sử dụng hội thoại làm FAQ (P1) |

**Quy thuộc thay đổi:** log 11 là catalog của agent khác; log 12 là reindex; log 13/17 là memory/feedback artifact; log 14 là structured transport/budget. Log 20 ghi Zeno khép lỗ consent và memory direct-RAG; log 21 ghi Zeno tích hợp, sửa chọn retry/claim và test liên quan. Không coi toàn bộ tám module là do riêng Zeno viết, cũng không coi code có mặt là đã triển khai live.

## Findings ưu tiên

### P0

Không có P0 mới được **xác minh** từ review tĩnh này. P0 cũ về reindex ghi đè giá/kho đã có nhánh `reindex_only` và test bất biến (log 12, 21); chưa kiểm trên dữ liệu thật nên không tự hạ rủi ro vận hành thành production PASS.

### P1 — Consent hợp lệ về trạng thái nhưng chưa rõ **mục đích FAQ/training**

`backend/scripts/export_rag_faq_candidates.py:228-261`, `backend/scripts/review_rag_feedback.py:142-158`: export và approval hiện kiểm `Customer.fact_extraction_opt_out=False`, customer active và consent mới nhất `purpose="personalization"`, `status="granted"`. Điều này sửa lỗ export opt-out/never-consented đã phát hiện; test 99 pass là bằng chứng hẹp. Tuy nhiên `personalization` không tự chứng minh khách đã cho phép đưa nguyên văn hội thoại/câu trả lời nhân viên vào KB dùng cho khách khác hoặc training. Artifact được giữ sau approval; nếu consent bị rút *sau* khi xuất seed, không có bước import/eviction kiểm lại. **Khuyến nghị:** định nghĩa scope riêng hoặc quyết định sản phẩm được duyệt; chặn import khi scope thiếu, recheck consent ngay tại import, lưu lineage customer/candidate→KB để gỡ và retrain khi rút. Cho đến lúc đó không import seed thật.

### P1 — Claim giá có thể lọt khi bot dùng tên rút gọn

`backend/app/rag/claim_verification.py:29-57`: đối chiếu giá theo dòng chỉ chạy khi **nguyên tên catalog** xuất hiện trong claim; nếu bot viết tên rút gọn/alias thì `product_mentions` rỗng và vòng kiểm theo hàng không chạy. `has_valid_citations` tại `:24-26` vẫn kiểm nguồn tổng quát, nhưng khi một source chứa nhiều dòng sản phẩm, điều này chưa chứng minh số tiền gắn đúng mặt hàng. Test mới ở `backend/tests/test_rag_serving_contract.py:89-109` kiểm tên đầy đủ và hai dòng, chưa có ca tên rút gọn với giá tráo. Đây là suy luận từ code, chưa tái hiện qua provider. **Khuyến nghị:** trả claim theo `offering_ref`/product ID trong schema rồi đối chiếu giá/kho từng row server-side; thêm negative test alias, tên rút gọn và hai sản phẩm cùng source.

### P1 — Calendar follow-up vẫn có thể lấy ngữ cảnh rất cũ

`backend/app/services/conversation_graph.py:394-425` truy ngược tối đa 200 inbound trong cùng conversation để suy loại service/rental khi câu lịch thiếu danh từ; vòng này không kiểm TTL, sản phẩm/dịch vụ vừa được trả, hay đổi chủ đề. Memory mới `backend/app/services/conversation_memory.py:200-256` có TTL 30 phút và latest-reply barrier nhưng nhánh calendar này không dùng nó. Trong hội thoại dài, “ngày mai 9h còn lịch không?” có thể bị ghép với dịch vụ cũ dù khách vừa đổi nhu cầu. **Khuyến nghị:** chỉ dùng offering_ref trong state đã xác thực/TTL hoặc hỏi lại một câu khi không có active service/rental; test đổi chủ đề và hết hạn.

### P1 — Reindex an toàn khi lỗi thường, chưa an toàn sau crash/publish

`backend/app/services/ingestion_service.py:354-389,448-493` reserve delta và publish tenant theo transaction; quota control-plane là transaction khác. Log 12 tự nêu hard-kill giữa reserve và publish/compensation có thể giữ quota dư; không có active index version để rollback sau publish. Script audit chỉ dry-run, chưa chạy trên document thật. **Khuyến nghị:** có reconciliation/compensation ledger và snapshot version/rollback procedure; audit một tập nhỏ theo tenant trước khi reindex, kiểm recall/mapping và catalog invariants trước/sau.

### P2 — Quan sát latency/cost còn thiếu dữ liệu quyết định rollout

`backend/app/rag/run_logger.py:82-129` có tổng `duration_ms`; `backend/app/rag/turn_budget.py:91-115` có latency/model/usage từng attempt; `backend/app/rag/retriever.py:463,501,594,646` hiện chủ yếu ghi duration retrieval ở log text. Chưa có report ghép `queue→delivery`, p50/p95, embedding/BM25/vector/LLM tách bước, token thiếu giữ unknown, bảng giá có phiên bản, 429/fallback rate theo shop/kênh. `backend/app/rag/run_logger.py:98` mặc định `code_version=unversioned` nếu không inject commit/version; working tree dirty làm cùng HEAD chưa chắc cùng code. **Khuyến nghị:** log `config_version` và dirty-diff hash, timer từng bước, provider/model thực, actual usage; offline paired replay + staging trace, tính chi phí chỉ khi usage/pricing có nguồn, không thay missing bằng 0.

## Bảy tiêu chí nghiệm thu của log 08

Chấm **mức bằng chứng**, 0 = chưa đo, 1 = fixture/cơ chế hẹp, 2 = offline end-to-end ghép cặp, 3 = live đa shop/kênh qua gate. Tổng **5/21**, không phải quality score.

| Tiêu chí | Điểm | Evidence và tình trạng |
| --- | ---: | --- |
| Cùng câu hỏi nhất quán qua kênh | 1 | `backend/tests/test_auto_reply_channels.py:295-331` tham số hóa sáu kênh với mock context/send. Chưa replay adapter thật, cùng customer/consent/catalog snapshot; khác transport, image/voice và webhook chưa được chấm. |
| Mục đúng nằm ngoài 100 đầu | 1 | `backend/tests/test_catalog_search_contract.py:99,149` và log 11 kiểm SQL filter/pagination trên fixture >100. Chưa kiểm production scale hoặc câu “liệt kê toàn bộ” trong Graph (đưa tối đa 12 ở `conversation_graph.py:542-554`). |
| Không trộn shop/SKU/biến thể | 1 | Tenant, SKU, typed attribute fixture ở log 11/21; chưa có paired answer audit nhiều shop/ngành, tên rút gọn và danh mục trùng SKU/alias trên kênh thật. |
| Hiểu câu nối tiếp như “cái rẻ hơn” | 1 | `conversation_memory.py:174-290` và tests isolated cover scope/TTL/barrier; calendar branch cũ có P1 nêu trên. Chưa replay end-to-end đổi chủ đề. |
| Thiếu nguồn thì hỏi đúng phần thiếu | 1 | Graph citations/fallback tests theo log 21; chưa có nhãn người theo ngành đo useful clarification vs. từ chối quá mức. |
| Groq 429 vẫn fallback an toàn | 0 | Fake SDK budget/fallback 75 pass (log 14), nhưng chưa thử Groq 429 thật/staging + delivery idempotency + wall deadline; `turn_budget` không hard-cancel sync blocking I/O. |
| Đo trước/sau về quality, latency, token/cost/fallback | 0 | Không có paired benchmark cùng snapshot/model/prompt, p50/p95, tiền/câu theo shop/kênh; log 21 cũng ghi **CHƯA ĐẠT**. |

Điểm 0 của 429 nói về **nghiệm thu end-to-end**, không phủ định các unit tests fallback. Không tiêu chí nào đạt mức 3.

## Việc tiếp để chứng minh “thông minh hơn”

1. Khép bốn P1 bằng test hồi quy hẹp; riêng consent phải quyết định scope trước khi phát hành seed. Giữ BM25/PPR off và không bật feedback import tự động.
2. Đóng băng 3–5 shop khác ngành, catalog/document revision, consent scope, code/diff hash, model/prompt/config. Chọn câu đã người duyệt, gồm catalog có điều kiện, nhiều sản phẩm/giá, chính sách, service/rental, follow-up, thiếu nguồn, 429. So baseline hiện hành và bản mới **ghép từng câu**; giữ kết quả theo shop, không gộp shop ít mẫu.
3. Chấm hard errors sai shop/SKU/giá/tồn/tương thích/nguồn, độ hữu ích, hỏi lại đúng lúc; kèm retrieval Recall@K/NDCG@K khi có nhãn. Ghi số lượt fallback, actual calls/token (unknown nếu provider không trả), p50/p95 từ nhận webhook đến gửi thành công và từng bước. Chi phí = usage thực × bảng giá có ngày/phiên bản, cộng retry/fallback.
4. Replay cùng input/context qua các adapter trên staging rồi canary từng shop. Gate: không tăng hard errors, đạt ngưỡng tuyệt đối đã chốt, không giảm hữu ích, p95 và chi phí dưới ngưỡng chốt **trước** khi xem kết quả. Chưa đủ mẫu thì tiếp tục shadow/baseline.

**Giới hạn review:** Không tự chạy test/provider/live; các số 423, 102, 96, 82, 75, 99 pass là báo cáo từ logs 20–21 và worker logs, chưa có đối chứng độc lập hoặc phép đo quality production. Không phát hiện bằng chứng commit/push trong lượt review.
