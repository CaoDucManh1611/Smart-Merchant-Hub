# Smart Merchant Hub — Final Handover

**Ngày:** 2026-11-06 (Asia/Bangkok)  
**Branch / HEAD:** `codex/rag-rfm-all-updates-20261104` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`  
**Phạm vi:** tổng hợp trạng thái RAG, RFM và xác minh offline/provider được cho phép. Không commit, push, deploy, migration, reindex hay truy cập database production.

## Kết luận nhanh

Code RAG và recommendation/RFM có các đường xử lý đã được tích hợp và có regression offline. Benchmark retrieval synthetic cho kết quả tốt trên 51 tình huống, nhưng đây không phải đánh giá câu trả lời đầu cuối. Batch Groq cuối bị rate limit sau 8/20 hội thoại; 12 hội thoại chưa chạy. Độ đúng tổng thể, grounding và hallucination vẫn **chưa được đo hợp lệ**, do đó chưa thể kết luận chatbot thông minh hơn hoặc sẵn sàng production.

## Trạng thái nghiệm thu

```text
RAG_RETRIEVAL=OFFLINE_SYNTHETIC_EVIDENCE: 51 cases; 39/39 evidence-bearing cases relevant at top-5; evidence Recall@5=1.0; MRR@5=1.0; empty-result accuracy=12/12; forbidden evidence=0; tenant violations=0. Not live or production evidence.
RAG_ANSWER_QUALITY=NOT_MEASURED overall; latest Groq run stopped on HTTP 429 after 8/20 case executions. Automated claim checks are not human answer-quality labels.
RAG_RFM_INTEGRATION=CODE_INTEGRATED; OFFLINE_TESTED across recommendation and conversation-graph paths; no single live/provider end-to-end personalized rank-swap verified.
RFM_PERSONALIZATION=OFFLINE_VERIFIED for consent-gated purchase-history/category signals and ranking traces; not production/runtime verified.
RECOMMENDATION_RELEVANCE=OFFLINE_RANKING_TESTS_PASS; human relevance and online conversion impact NOT_MEASURED.
SALES_ADVICE=PARTIALLY_VERIFIED on synthetic catalog facts; budget case 002 failed to return the in-budget item in the latest run.
PROVIDER_RELIABILITY=429 STOP GUARD VERIFIED; run stopped safely without provider switching or fallback. One HTTP 400 structured-output failure and one HTTP 429 occurred in 4 physical attempts.
TENANT_ISOLATION=OFFLINE_SYNTHETIC_TESTED; production/runtime verification NOT_VERIFIED.
CONSENT_RACE_P2=OPEN.
POSTGRESQL_RUNTIME=NOT_VERIFIED.
BACKEND_REGRESSION=FOCUSED: 148 passed, 6 subtests passed; separate focused invocation: 13 passed. Prior full suite: 2,278 passed, 6 skipped, 37 subtests, exit 0; not rerun in this continuation.
HUMAN_REVIEW=20/20 labels pending; no AI-generated label was promoted as human-approved.
PRODUCTION_READY=NO.
REMAINING_BLOCKERS=Groq quota/rate limit; 12 unevaluated cases; unresolved answer case 002; human review/grounding; consent race P2; PostgreSQL runtime/concurrency; browser and production runtime not verified; no end-to-end live RFM ranking proof.
```

## Retrieval benchmark

The latest recorded synthetic retrieval result in `reports/rag-intelligence-final/execution-post-fix-validation-20261106.md` covers 51 scenarios, 30 synthetic documents and 3 synthetic tenants using BM25 with `top_k=5`:

- 39/39 supported questions returned relevant evidence in the top five.
- Mean evidence Recall@5 was 1.0; MRR@5 was 1.0.
- Empty-result accuracy was 12/12.
- No forbidden-evidence hits or tenant-isolation violations were recorded.
- The run made no provider calls.

The before/after artifact attributes a narrow improvement to exact-SKU companion evidence retrieval: three comparison cases went from 1/2 to 2/2 required evidence items, while the exact SKU remained first. This demonstrates a synthetic retrieval improvement for that case family only; it does not establish answer correctness, hallucination reduction, latency or production performance.

## Real-answer evaluation run

One authorized synthetic run used Groq `openai/gpt-oss-20b`, BM25, temperature 0.3, no provider fallback, zero retries and a 512-token completion cap. Sales Journey remained OFF. The run used the frozen 20-case dataset and evidence snapshot:

- Dataset SHA-256: `340e70c14bcd7f954650570a6ada9b7c9539d37cb149467017577ea5e97bb386`.
- Evidence snapshot: `smh-rag-answer-quality-synthetic-v1-evidence:a2667f4debf8e5ca`; SHA-256 `a2667f4debf8e5cafa56cc4d41b38e28771744c5685df33eb962175f31beb0c2`.
- Source snapshot digest for this run: `43db1973746f812d66a22c7496d9a79ff8856d26674e8054a806582d9dfe10e9`.
- The evaluator stopped on `PROVIDER_RATE_LIMIT_429` after 8 of 20 graph executions. The remaining 12 cases are explicitly `NOT_EXECUTED`.
- Four physical provider attempts were recorded: two failures (one HTTP 400 `json_validate_failed`, one HTTP 429 `rate_limit_exceeded`) and two successful attempts. There was no provider switch and no Gemini fallback.
- The offline objective grader reports 6 automated passes, 13 automated failures and 1 provider error across the 20-case package. Among the 8 executed cases: 6 passed objective claim checks, 1 failed, and 1 ended in provider error. The 12 unexecuted cases do not count as answer passes.
- Case `answer-002-budget` failed: it returned a generic compatibility fallback instead of identifying the synthetic item within the stated 200,000 VND budget.
- Correctness, groundedness and hallucination rate remain `NOT_MEASURED`: there are no human-approved labels or validated judge results. The objective grader checks claims and does not replace answer review.
- Provider-reported usage was 3,693 input and 450 output tokens; conservative reservations were 41,747 input and 1,474 output tokens. USD cost is not measured because no price table was configured.

No further provider calls were made after the 429. The run and sanitized grading artifacts are retained; the raw run contains synthetic content only.

## RFM and recommendation behavior

Offline tests establish that recommendation ranking can use completed-order/category-affinity signals when customer consent permits it, persist ranking/retrieval trace metadata, and avoid claiming personalization where there is no usable signal or only one candidate. Separate graph tests cover the recommendation tool path and trace persistence. Consent gating and tenant-scoped behavior are covered by offline tests.

The current evidence is a set of linked service/API/graph tests, not one production-like end-to-end conversation showing that an opted-in customer's purchase history visibly changes the final product order. No conversion or recommendation relevance study was run. RFM and LightFM-style product personalization affect product recommendations; they do not train or replace factual RAG retrieval.

## Tests executed in this continuation

Tests used the isolated interpreter at:
`C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated\backend\.venv\Scripts\python.exe`.

1. Focused regression command:

   ```powershell
   pytest -p no:cacheprovider tests/test_personalized_rag_pipeline.py tests/test_recommendations_api.py tests/test_conversation_graph.py tests/test_rag_tenant_isolation.py tests/test_rag_feedback_consent.py tests/test_rag_answer_generation_eval.py -q --tb=short
   ```

   Result: **148 passed, 1 warning, 6 subtests passed in 9.39s**. `RUN_POSTGRES_TESTS=0`; provider environment variables were blank.

2. Additional context/RFM trace command:

   ```powershell
   pytest -p no:cacheprovider tests/test_conversation_context.py tests/test_personalized_rag_pipeline.py::test_catalog_match_logs_rfm_only_when_top_three_order_changes tests/test_personalized_rag_pipeline.py::test_catalog_match_does_not_claim_rfm_rerank_for_single_candidate tests/test_recommendations_api.py::RecommendationApiTests::test_completed_order_facets_change_personalized_rank_and_explain_the_signal tests/test_recommendations_api.py::RecommendationApiTests::test_consent_does_not_claim_personalization_without_customer_signals -q --tb=short
   ```

   Result: **13 passed in 5.15s**. Three selected tests overlap with the first invocation, so do not add these counts as unique tests.

3. The prior full backend result retained in `reports/rag-intelligence-final/RAG_FINAL_CONSOLIDATION.md` is **2,278 passed, 6 skipped, 37 subtests, exit 0**. No full suite was rerun in this continuation because application source was not changed.
4. `git diff --check` exited 0. Git emitted only existing LF/CRLF conversion warnings.

## Security, runtime and release boundary

- `CONSENT_RACE_P2` remains open; no concurrency claim is made.
- PostgreSQL runtime, pooling/search-path concurrency, row locking and role permissions were not verified. SQLite tests are not evidence of PostgreSQL correctness.
- Tenant isolation was exercised with synthetic offline tests only. No production tenant or database was accessed.
- No browser/UI runtime smoke or real-channel check was performed in this continuation.
- No source code was edited during the handover continuation. Existing worktree changes were preserved. There were 174 Git status entries before creating this report; `git diff --check` showed no whitespace errors.
- No order, payment, appointment, external customer message or provider fallback was triggered. The run used synthetic, query-only in-memory SQLite contexts and left the Sales Journey feature disabled.

## Evidence files

- Retrieval result: `reports/rag-intelligence-final/execution-post-fix-validation-20261106.md`
- Retrieval before/after: `reports/rag-intelligence-final/05_BEFORE_AFTER_BENCHMARK.md`
- Prior RAG consolidation and regression record: `reports/rag-intelligence-final/RAG_FINAL_CONSOLIDATION.md`
- Prior 20-case run limitations: `reports/rag-intelligence-final/FINAL_20CASE_RAG_QUALITY_RESULTS.md`
- Latest raw synthetic run: `reports/rag-intelligence-final/final-handover-20case-20261106-run1.json`
- Latest provider attempt trace: `reports/rag-intelligence-final/final-handover-20case-20261106-run1.rag-runs.jsonl`
- Latest budget ledger: `reports/rag-intelligence-final/final-handover-budget-20261106-run1.json`
- Latest offline case grading: `reports/rag-intelligence-final/final-handover-grading-run1/recorded-answer-case-review.csv`
- Latest sanitized answer traces: `reports/rag-intelligence-final/final-handover-grading-run1/recorded-answer-review-traces-sanitized.jsonl`
- Latest grading summary: `reports/rag-intelligence-final/final-handover-grading-run1/recorded-answer-review-summary.json`

**Handover decision:** offline code and synthetic retrieval evidence are available for review. Overall answer quality is inconclusive, provider evaluation is incomplete, human review is pending, and production acceptance is not met.
