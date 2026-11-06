# RAG 8 hạng mục: đối chiếu tích hợp và nghiệm thu offline

Ngày 2026-11-04. Nhánh `codex/rag-rfm-all-updates-20261104`. Đây là tổng hợp trên working tree dùng chung; không commit, push, gọi embedding, reindex dữ liệu thật, gửi tin kênh hay chạy migration. Reviewer Gauss tạm dừng cho đến khi lượt code này kết thúc.

## Phạm vi và sửa lỗi trong lượt tích hợp

- Đối chiếu các thay đổi Graph/RAG, catalog, reindex, memory, structured output, retrieval, verifier và feedback từ các worker trước. Giữ đường trả lời SQL hiện hành cho giá/kho, shortcut catalog và workflow giao dịch.
- `backend/app/rag/serving.py`: nếu retry hết turn budget, trả lại ứng viên retrieval ban đầu; không thay ứng viên bằng điểm ở retrieval mode khác; entry trace giữ `business_id` cả khi caller truyền positional arguments. `backend/app/services/auto_reply_service.py`: áp cùng quy tắc không so BM25/hybrid lệch thang điểm ở đường auto-reply; guard kết quả SKU query khi test DB mock không trả list.
- `backend/app/rag/claim_verification.py`: gắn từng giá trong claim so sánh nhiều sản phẩm với dòng catalog của đúng sản phẩm, thay vì gộp toàn bộ giá của nguồn rồi chấp nhận tráo giá.
- `backend/tests/test_auto_reply_channels.py`: fixture DB giả trả workspace config rõ ràng, một ca ép vào nhánh RAG khi đang đo prompt; đọc đúng log `auto_reply` thay vì log `auto_reply_entry` bao ngoài. `backend/tests/test_rag_tenant_isolation.py`: fixture mô phỏng mapping đã migrate cho ca kiểm SQL và thêm ca mapping thiếu phải fail closed. `backend/tests/test_rag_serving_contract.py`: test retry hết budget, điểm khác mode và giá từng sản phẩm.
- P1 feedback consent và direct-RAG memory đã sửa trong lượt liền trước; chứng cứ chi tiết: `2026-11-04-20-consent-memory-code-test.md`.

## Ma trận 8 hạng mục

| # | Kết quả đối chiếu code | Kiểm chứng offline và giới hạn |
| --- | --- | --- |
| 1. Graph/RAG chung | `backend/app/rag/serving.py:13,36` là wrapper budget, shop/filter/mode/PPR; `backend/app/services/conversation_graph.py:133` và `backend/app/services/auto_reply_service.py:42` dùng wrapper. Shortcut và workflow vẫn ở auto-reply/Graph. | Test serving, graph, routing, auto-reply qua. Chưa replay live các adapter; wrapper không chứng minh mọi nhánh giao dịch có cùng behavior. |
| 2. Catalog có điều kiện | `backend/app/services/catalog_search.py:60,179-270` lọc business/status/SKU/attribute/budget trong SQL trước `LIMIT`, phân trang, hydrate giá/kho hiện hành; `backend/app/services/conversation_graph.py` dùng công cụ catalog. | `test_catalog_search_contract.py` gồm mục ngoài 100, multi-shop, exact ref, hàng/dịch vụ/thuê. Chưa đo hiệu năng catalog production lớn hoặc stock theo kênh. |
| 3. Reindex an toàn | `backend/app/services/ingestion_service.py:78,110,389` phân biệt reindex, không sync giá/kho từ tài liệu cũ; `backend/app/services/rag_job_service.py`, `backend/app/api/documents.py` giữ index ready; `backend/scripts/audit_safe_reindex.py` dry-run một shop/tài liệu. | Test lỗi/quota/tenant/publish. **Chưa reindex live**. Rollback transaction trước publish có; chưa lưu snapshot phiên bản để rollback sau publish hoặc khôi phục cứng khi process chết giữa control-plane quota và tenant commit. |
| 4. Memory có cấu trúc | `backend/app/services/conversation_memory.py:174-284` lưu ID, constraints, pending slot/intent, TTL; `backend/app/services/auto_reply_service.py:868-905` ghi metadata cả direct RAG; Graph nạp tại `backend/app/services/conversation_graph.py:994`. Không lưu giá/kho lâu dài. | Test forged metadata, tenant, reset, latest-reply barrier, direct RAG persistence. Chưa xác minh follow-up trên kênh live. |
| 5. Structured output | `backend/app/rag/output_contracts.py:6-48` schema Pydantic; `backend/app/rag/llm_caller.py` native `call_structured`, budget attempts/provider; Graph planner/composer gọi schema. | Test provider SDK fake và validation. Runtime cài local `google-genai 2.19.0` khác constraint repo `<2`; chưa xác minh container/provider thực. Prompt/test injected callable vẫn là legacy JSON path. |
| 6. Adaptive retrieval | `backend/app/rag/serving.py:36-96`, `backend/app/services/auto_reply_service.py:4407-4528`: mặc định BM25/PPR off, retry có mode/shadow, giữ hard filters, budget và trace; không dùng điểm khác mode để chọn. | Test mode, retry filter, timeout. Chưa chứng minh NDCG/độ trễ tốt hơn trên nhãn đã duyệt hoặc lưu lượng thật. Không bật hybrid/PPR mặc định. |
| 7. Claim verification | `backend/app/rag/claim_verification.py:8-60`, `backend/app/services/conversation_graph.py:943-977`: source ID, phép tính, giá từng sản phẩm, citation, retry có giới hạn; auto-reply legacy dùng `answer_guard.has_valid_citations`. | Test không mượn giá từ sản phẩm khác, nguồn sai và phép tính. Verifier chưa chứng minh tất cả claim về tương thích/chính sách hiệu lực trên dữ liệu production; không tuyên bố 0 hallucination. |
| 8. Feedback learning | `backend/scripts/export_rag_faq_candidates.py` tạo candidate theo handoff + staff reply, current consent/opt-out/scope/tenant và provenance; `backend/scripts/review_rag_feedback.py:24-162` recheck consent DB khi duyệt, fail closed, chỉ human-approved seed. | Test never-consent, revoked, opt-out, khác shop, synthetic, hash và approval. Seed **chưa tự import KB/train**; cần quy trình xác thực reviewer và đưa seed đã duyệt vào nguồn đúng shop. Không dùng chat test làm hành vi mua thật. |

## Bảy tiêu chí nghiệm thu

| Tiêu chí | Bằng chứng đạt đến đâu | Trạng thái |
| --- | --- | --- |
| Kết quả nhất quán qua kênh | `backend/tests/test_auto_reply_channels.py:295` kiểm chung context qua 6 kênh, nhiều test đường trả lời từng kênh. | PASS offline trên fixture; live chưa kiểm. |
| Tìm item ngoài 100 đầu | `backend/tests/test_catalog_search_contract.py:99,149` kiểm candidate cuối, filter trước LIMIT, pagination. | PASS offline; production scale chưa đo. |
| Không trộn shop/SKU/biến thể | `backend/tests/test_catalog_search_contract.py:104,135,164,182`; `backend/tests/test_rag_tenant_isolation.py:107-158`; `backend/tests/test_safe_reindex.py:272`. | PASS offline; live chưa kiểm. |
| Hiểu câu nối tiếp | `backend/tests/test_conversation_memory_isolated.py:69-175` kiểm ID đã hiển thị, TTL, chuyển chủ đề, sửa constraint, forged metadata. | PASS offline; live chưa kiểm. |
| Thiếu bằng chứng thì hỏi/chuyển đúng | Graph/auto-reply citation và handoff tests trong `backend/tests/test_conversation_graph.py`, `test_chatbot_answer_routing.py`, `test_auto_reply_channels.py`. | Một số case PASS offline; chưa có bộ nhãn người theo ngành để đo tỷ lệ hỏi lại đúng. |
| 429/fallback an toàn | `backend/tests/test_llm_turn_budget.py` và `test_llm_provider_fallback.py` giả lập key rotation/provider/attempt cap/timeout. | PASS offline SDK fake; chưa đo provider live hoặc hard wall deadline. |
| Đo trước/sau cùng dữ liệu | Run log ghi route/retrieval/latency, budget có attempt/model/usage; log12 và log14 nêu smoke/dry-run. | **CHƯA ĐẠT**: không có paired snapshot benchmark 8 hạng mục, không có p50/p95 và chi phí live per-shop. Không được suy từ số pytest. |

## Kiểm thử và ranh giới số liệu

- Lượt tích hợp chính (12 tệp test: serving/catalog/reindex/memory/budget/feedback/graph/routing/auto-reply): **423 passed, 0 failed, 144.88 giây**, harness mặc định dùng PostgreSQL test schemas. Trước sửa fixture có 399 pass/22 lỗi auto-reply; sau sửa auto-reply + serving riêng 80 pass.
- Lượt ingestion/quota mở rộng (10 tệp): lần đầu **99 pass, 2 lỗi fixture** vì recording session thiếu metadata mapping; fixture đã cập nhật và thêm case fail-closed. Chạy lại trọn nhóm: **102 passed, 0 failed, 185.20 giây** trên harness PostgreSQL test schemas.
- Lượt xác nhận riêng tenant isolation + serving + auto-reply sau sửa fixture và cross-mode: **96 passed, 0 failed, 38.61 giây**. Nhóm LLM native schema/key rotation/provider fallback/vision/api pool: **75 passed, 0 failed, 6.20 giây**.
- Sau bổ sung entry trace cho positional call, chạy lại serving + auto-reply: **82 passed, 0 failed, 30.08 giây**.
- `python -m compileall -q` trên source/test sửa trong lượt này và `git diff --check` đều exit 0. `git diff --check` có cảnh báo chuyển LF/CRLF cho hai file sẵn có; không có whitespace error.
- Không gọi provider, embedding, kênh khách, reindex hoặc training. Các con số này là kết quả test code, không phải chất lượng câu trả lời. Không có phép đo chứng minh RAG “thông minh hơn” ở production. Muốn bật theo shop cần snapshot, bộ câu có nhãn người, so paired baseline/đề xuất về lỗi cứng, hữu ích, p95 và chi phí; với dữ liệu chưa đủ thì giữ baseline.

## Việc còn chặn production gate

1. Dry-run audit tài liệu được chọn và xác nhận catalog/KB snapshot, quota, source mapping; sau đó reindex từng shop qua API có giám sát và rollback vận hành rõ ràng. Không chạy hàng loạt khi chưa có evidence.
2. Xác minh dependency/version provider trong container và phép thử 429/deadline trên môi trường staging; khóa ngưỡng p95/cost trước khi so sánh.
3. Duyệt nhãn và replay cùng dữ liệu theo shop/ngành/kênh; so lỗi cứng và hữu ích, không gộp shop ít mẫu. Live canary chỉ sau gate.
4. Xây/kiểm tra đường nhập seed đã human-approved với quyền và consent hiện hành; rút consent cần loại khỏi train/KB tiếp theo theo chính sách đã chốt.

Gauss được mời phản biện độc lập sau khi bàn giao code/log; trạng thái trên không thay kết luận của reviewer.
