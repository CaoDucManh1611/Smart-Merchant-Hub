# Smart Merchant Hub — Final RAG Quality Consolidation

**Ngày:** 2026-11-06 13:07 ICT  
**Branch:** `codex/rag-rfm-all-updates-20261104`

## Trạng thái nghiệm thu

```text
CASE_010_COMPLETENESS=IMPLEMENTED_AND_UNIT_TESTED; LIVE_ANSWER_QUALITY_NOT_MEASURED
UNCERTAINTY_HANDLING=IMPLEMENTED_FOR_POLICY_SHIPPING_RETURN_COMPATIBILITY_AND_WARRANTY_MISSING_EVIDENCE
STAFF_HANDOFF_BEHAVIOR=SAFE_REPLY_NAMES_UNRESOLVED_DETAIL_AND_REQUESTS_STAFF_CHECK; HANDOFF_PATH COVERED BY EXISTING GRAPH TESTS; NO LIVE CHANNEL TEST
RFM_CWD_ROOT_CAUSE=RELATIVE_RECOMMENDATION_ARTIFACT_DIR WAS RESOLVED AGAINST PROCESS CWD
RFM_CWD_FIX=IMPLEMENTED; RELATIVE ARTIFACT PATH NOW ROOTED AT BACKEND MODULE LOCATION
FOCUSED_REGRESSION=PASS; FINAL 93 PASSED IN 4.04S; EXIT 0
FULL_BACKEND_REGRESSION=PASS; 2275 PASSED, 6 SKIPPED, 40 WARNINGS, 37 SUBTESTS; EXIT 0
RETRIEVAL_REGRESSION=NOT_RERUN; RETRIEVAL/SERVING CODE UNCHANGED IN THIS CONSOLIDATION
TENANT_CAPABILITY=OFFLINE TESTS INCLUDED IN FULL SUITE; RUNTIME/POSTGRESQL NOT VERIFIED
20_CASE_EVALUATION_READY=PREPARED; 20 SYNTHETIC CASES, HASHED SNAPSHOTS, PAIRED-RUN CONTRACT AND PROVIDER CAPS; NO QUALITY RESULT
HUMAN_REVIEW_RUBRIC=PREPARED; 20 LABELS PENDING; CASES 016 AND 020 DISPUTED
SOURCE_FILES_CHANGED=9 CODE/TEST FILES LISTED BELOW; PRE-EXISTING DIRTY WORKING TREE PRESERVED
PROVIDER_CALLS=0
CONSENT_RACE_P2=OPEN
REMAINING_BLOCKERS=HUMAN REVIEW; SEPARATE PROVIDER-RUN APPROVAL; CASE 016/020 GOLD DISPUTE; COST RATE NOT CONFIGURED; CONSENT RACE P2; POSTGRESQL RUNTIME NOT VERIFIED
```

## Đã thực hiện

### 1. Case 010 và câu trả lời khi thiếu bằng chứng

Thêm `_missing_evidence_subject()` và `_missing_evidence_reply()` trong `backend/app/services/conversation_graph.py`. Fallback nêu cụ thể điều chưa được nguồn xác nhận (ví dụ thời hạn bảo hành, phí/thời gian giao, điều kiện đổi trả, tương thích), không biến thiếu thông tin thành câu khẳng định và hướng khách nhờ nhân viên kiểm tra. Không hardcode cụm “bảo hành trọn đời”. Luồng quyết định nhân viên hiện có được giữ nguyên.

Prompt cũng được bổ sung hướng dẫn trả lời phần có căn cứ, nêu phần chưa rõ, không suy diễn chính sách và tách thông số khỏi khẳng định tương thích. Test hồi quy bao gồm giao hàng, đổi trả, tương thích, bảo hành và fallback chính sách không có nguồn.

**Giới hạn:** đây là kiểm tra code và test offline. Chưa chạy provider để xác nhận câu trả lời do LLM tạo có tự nhiên, đủ ý hoặc tốt hơn.

### 2. Sửa lỗi RFM phụ thuộc thư mục chạy

Nguyên nhân là `RECOMMENDATION_ARTIFACT_DIR` tương đối được diễn giải theo process CWD, dẫn tới CLI/worker/test có thể đọc các artifact khác nhau hoặc rơi về hành vi mặc định. `_artifact_path()` hiện neo đường dẫn tương đối vào vị trí package backend. Hai test RFM được parameterize với hai working directory và giữ nguyên assertion nghiệp vụ.

Log tái hiện trước sửa ghi hai test lỗi; sau sửa cả hai pass. Không mở hoặc sửa `backend/test.db`; test chạy với CWD tạm và PostgreSQL tests bị tắt.

### 3. Chuẩn bị đánh giá câu trả lời 20 case

- Dataset synthetic được giữ nguyên: SHA-256 `340e70c14bcd7f954650570a6ada9b7c9539d37cb149467017577ea5e97bb386`.
- Snapshot evidence: `smh-rag-answer-quality-synthetic-v1-evidence:a2667f4debf8e5ca`; SHA-256 đầy đủ nằm trong evaluation package.
- Implementation snapshot SHA-256: `58290155d110f8261ea864d59b75b9409c90645e599e639570f2b1b45bbbde7a`.
- Hai nhánh được định nghĩa là `baseline` và `post-fix`, cùng dataset/evidence snapshot và cấu hình.
- Cấu hình khi được phê duyệt: Groq `openai/gpt-oss-20b`, BM25, temperature 0.3, không fallback provider, max retries 0, tối đa 512 completion tokens/request, tối đa 20 case/run.
- Hard cap ghép cặp: 40 case executions, 80 physical provider attempts, 200.000 input tokens, 30.000 output tokens, 1.800 giây/run. Chạm cap phải báo incomplete, không suy ra kết quả chất lượng.
- USD cost estimate chưa thể tính vì evaluator chưa cấu hình bảng giá. Không bịa mức chi phí.
- Evaluator ghi rõ các outcome deterministic, LLM, validated fallback, clarification, provider HTTP 400/429, circuit open và infrastructure error. Objective grader không được coi fallback an toàn là câu trả lời đầy đủ.
- Context factory yêu cầu dữ liệu synthetic, read-only, in-memory SQLite; cấu hình cấm side effect và chặn provider khác Groq. Sanitized trace chỉ được tạo khi có lần chạy; lần này không có trace provider mới.
- Toàn bộ nhãn vẫn `pending human review`. Không dùng nhãn AI làm nhãn người. `answer-016-out-of-stock` và `answer-020-service-read-only-availability` được giữ ở trạng thái tranh luận.

CLI preflight xác nhận 20 case, không import context factory và không gọi ứng dụng, database hay provider. Answer quality vẫn `NOT_MEASURED`.

## Test và kiểm tra thực chạy

Python dùng virtual environment cô lập: `C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated\backend\.venv\Scripts\python.exe`. Provider keys được làm trống; `RUN_POSTGRES_TESTS=0`; test chạy từ thư mục tạm.

| Kiểm tra | Lệnh/kết quả | Exit |
|---|---|---:|
| Focused cuối | Lệnh đầy đủ, Python executable, test paths, CWD và exit code được ghi trong `consolidation-focused-final-20261106.log` — **93 passed, 4.04s** | 0 |
| Full backend | `python -m pytest -q "<repo>\backend\tests"` — **2.275 passed, 6 skipped, 40 warnings, 37 subtests passed, 131.53s**. Warnings là deprecation, không phải test failures. | 0 |
| Provider preflight | 20 cases; `provider_calls=0`; no context factory/app/provider/database call. | 0 |
| `git diff --check` | Exit 0; chỉ có cảnh báo Git về LF/CRLF trên các file working tree. | 0 |

Lệnh focused cuối được chạy từ CWD tạm, với các đường dẫn test tuyệt đối:

```powershell
C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated\backend\.venv\Scripts\python.exe -m pytest -q C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub\backend\tests\test_conversation_graph.py C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub\backend\tests\test_personalized_rag_pipeline.py::test_training_precomputes_cache_using_same_tenant_population C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub\backend\tests\test_rag_crm_model_integration.py::test_rfm_excludes_pending_cancelled_refunded_and_future_orders C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub\backend\tests\test_rag_answer_generation_eval.py C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub\backend\tests\test_compare_rag_runs.py C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub\backend\tests\test_prepare_rag_human_review.py
```

Lượt focused đầu tiên có 6 lỗi test: bốn assertion phân biệt chữ hoa/thường ở câu fallback và hai test gọi helper evaluator thiếu keyword metadata. Đã chỉnh assertion/default test-invoker metadata, không thay expected nghiệp vụ. Focused rerun sau đó đạt 86 test; focused cuối với danh sách lệnh ghi đầy đủ đạt 93 test. Raw logs giữ cả lần lỗi ban đầu và các lần pass.

Không chạy retrieval benchmark lại vì không sửa serving/retrieval. PostgreSQL runtime, UI và live/provider answer quality không được kiểm chứng trong nhiệm vụ này.

## File source/test được chạm trong consolidation

- `backend/app/services/conversation_graph.py`
- `backend/app/services/industry_rfm_prior.py`
- `backend/scripts/evaluate_rag_answer_generation.py`
- `backend/scripts/compare_rag_runs.py`
- `backend/tests/test_conversation_graph.py`
- `backend/tests/test_personalized_rag_pipeline.py`
- `backend/tests/test_rag_crm_model_integration.py`
- `backend/tests/test_rag_answer_generation_eval.py`
- `backend/tests/test_prepare_rag_human_review.py`

Các thay đổi trước đó trong working tree không bị reset, clean, stash hoặc ghi đè. Không commit, push, deploy, migration, reindex, truy cập production DB, gửi tin thật hay gọi LLM/provider. `SALES_JOURNEY_ENGINE_ENABLED` vẫn mặc định `False`; `CONSENT_RACE_P2` vẫn `OPEN`.

## Artifact và log

- Rubric: `reports/rag-intelligence-final/human-review-rubric-20case-v1.md`
- Gói case + evidence/source hashes: `reports/rag-intelligence-final/20-case-evaluation-package-v1.json`
- Giới hạn provider/token và chi phí: `reports/rag-intelligence-final/provider-budget-estimate-20case-v1.json`
- Focused lần đầu (có lỗi): `reports/rag-intelligence-final/consolidation-focused-tests-20261106.log`
- Focused rerun: `reports/rag-intelligence-final/consolidation-focused-tests-rerun1-20261106.log`
- Focused cuối, kèm lệnh và exit code: `reports/rag-intelligence-final/consolidation-focused-final-20261106.log`
- Full backend: `reports/rag-intelligence-final/consolidation-full-backend-20261106.log`
- RFM reproduction trước sửa: `reports/rag-intelligence-final/rfm-cwd-repro-before-fix-20261106.log`
- RFM hai test sau sửa: `reports/rag-intelligence-final/recovery-rfm-failures-rerun-20261106.log`
- Provider preflight: `reports/rag-intelligence-final/consolidation-provider-preflight-20case-20261106.log`
- Diff check: `reports/rag-intelligence-final/consolidation-diff-check-20261106.log`

## Kết luận

**Code/offline regression: đạt cho phạm vi sửa Case 010, CWD RFM và harness. Chất lượng câu trả lời RAG: chưa được đo, không phải PASS.** Bước đánh giá 20 case chỉ còn cần phê duyệt riêng cho provider run, người duyệt xử lý nhãn (đặc biệt ca 016/020), và xác định bảng giá nếu cần báo chi phí USD. Consent race P2 cùng PostgreSQL runtime vẫn là blocker ngoài phạm vi sửa hiện tại.
