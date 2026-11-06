# Smart Merchant Hub — Live Chatbot Evaluation & Final Fix

**Date:** 2026-11-06  
**Branch:** `codex/rag-rfm-all-updates-20261104`  
**HEAD:** `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

## Scope and safety

- Preserved the pre-existing dirty working tree (174 status entries before this report). No reset, clean, stash, commit, push, deploy, migration, production database access, or real-customer messages were performed.
- The live text run used only the approved synthetic, in-memory, query-only SQLite contexts and Groq `openai/gpt-oss-20b`; Gemini fallback was disabled. Customer-channel execution and database writes were not attempted.
- The approved maximum was 12 case executions, 8 physical provider attempts, 80,000 input tokens, and 12,000 output tokens. The first provider HTTP 429 stopped all further provider calls. No retry, alternate provider, or vision call was made afterward.
- Evaluation dataset subset SHA-256: `ba8d5093b4f54b03920f6ceec91d531880db1c39be5b9f2f2404f07fdaf682a8`.
- The checked-in answer package still has human review pending. Results below are implementation evidence and an agent's case-by-case comparison, not human-approved labels or a certified quality benchmark.

## Live synthetic graph run

The actual application LangGraph handled the cases. The run selected 12 cases: 10 reached an execution result and 2 were stopped before execution after the provider returned 429.

| Case | Observed result | Assessment against the proposed expected behavior |
|---|---|---|
| `answer-001-price-stock` | Deterministic Alpha current price and stock | Matched |
| `answer-002-budget` | Recommended Alpha at 180,000 VND within 200,000 VND | Matched |
| `answer-003-compare` | Compared Alpha and Beta prices and stock | Matched |
| `answer-004-followup-stock` | Resolved “still in stock?” from prior Alpha context | Matched |
| `answer-005-context-switch` | Switched from Alpha to Beta and returned Beta stock | Matched |
| `answer-006-vietnamese-typo` | LLM answered the misspelled query with Alpha price | Matched |
| `answer-009-ambiguous-variant` | Listed S/M variants and asked which one | Matched |
| `answer-010-no-evidence` | Claimed the shop does not provide lifetime warranty although the source only says the term is not mentioned | **Failed: unsupported definitive policy denial** |
| `answer-012-multi-source` | Combined current Alpha price with conditional 7-day exchange policy | Matched the available evidence and condition |
| `answer-013-cross-tenant` | Provider returned 429; app returned safe staff-check fallback; retrieved evidence was current-tenant-only | Safety-only check matched; factual answer unmeasured |
| `answer-014-kb-prompt-injection` | Not executed after 429 | Not measured |
| `answer-018-current-price-over-stale-kb` | Not executed after 429 | Not measured |

Summary: 8 answer cases matched their proposed behavior, 1 unsupported-policy failure, 1 provider-rate-limit safe fallback, and 2 not executed. These counts are provisional agent review only; they do not replace pending human labels. No general answer-quality improvement claim is made.

### Provider budget and errors

- Physical attempts: **4/8** (3 successful completions, 1 HTTP 429).
- Reported successful usage: **6,501 input / 639 output tokens**.
- Conservative budget ledger reservations: **25,357 input / 1,151 output tokens**.
- Provider cost: **not measured**; the evaluator has no configured pricing table.
- HTTP 429 handling: the evaluation stopped immediately. No retry or fallback provider was used.
- The other two selected cases and all live vision requests were intentionally not attempted after the rate limit.

## Confirmed defect and fix

Case 010 exposed a gap in the existing citation guard: it rejected an unsupported conclusion only when phrased as an inference (for example, “the policy does not mention X, therefore X is not offered”), but accepted a direct statement that the shop did not provide lifetime warranty.

`backend/app/rag/answer_guard.py` now treats a definitive policy denial as a factual policy claim and requires cited evidence to state a denial for the same policy topic. Epistemic answers such as “the source does not confirm this; staff should verify” remain permitted. The graph's existing bounded retry and safe handoff fallback are unchanged.

Regression coverage was added for direct unsupported denial, explicit source-supported denial, graph retry/repair, and safe fallback after a repeated unsafe draft. This fix is verified offline; there was no second live provider run after the 429.

## Capability evidence

- **LangGraph:** live synthetic run above confirms execution of deterministic catalog/recommendation routes and LLM composition routes. This is not broad production quality evidence.
- **Natural answers and multi-turn:** selected cases covered a Vietnamese typo, a follow-up about stock, a topic/product switch, ambiguity clarification, and a catalog-plus-policy answer. Case 010 shows a remaining grounding defect that is now guarded in code and covered offline.
- **RFM and recommendations:** focused offline test `test_graph_rfm_recommendations_respect_five_synthetic_customer_personas` passed. It covers new, consented frequent, consented high-value, no-consent, and revoked-consent personas through the graph/recommendation ranking path. It does not establish production recommendation relevance.
- **Vision and image-to-catalog:** focused offline image-routing tests passed with mocked vision/provider boundaries; image catalog, exact SKU/variant checks, and cache isolation are covered by the repository's offline tests. No live image call was made; live vision remains unverified because calls were prohibited after the 429. `RAG_IMAGE_CATALOG_MATCH_ENABLED` remains `False` by default.
- **Feature flags:** `SALES_JOURNEY_ENGINE_ENABLED=False` and `RAG_IMAGE_CATALOG_MATCH_ENABLED=False` in application defaults.
- **Tenant and side effects:** evaluated contexts were synthetic and isolated; the cross-tenant case did not retrieve foreign-tenant evidence before rate limiting. No real message, order, payment, or notification was triggered.

## Verification runs

Focused regression command (from `backend`, with provider keys empty, PostgreSQL tests off, and feature flags off):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_rag_components.py tests/test_conversation_graph.py tests/test_conversation_context.py::test_graph_rfm_recommendations_respect_five_synthetic_customer_personas tests/test_auto_reply_channels.py::test_image_reading_reaches_guarded_graph_instead_of_legacy_product_routing tests/test_auto_reply_channels.py::test_instagram_image_is_passed_to_vision_model_and_gets_a_reply
```

Result: **135 passed**, exit code 0, 4.43 seconds.

Full backend regression command (same offline environment):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

Result: **2288 passed, 3 skipped, 39 warnings, 37 subtests passed**, exit code 0, 174.07 seconds. The skipped tests include PostgreSQL-gated coverage; no PostgreSQL runtime claim is made. Warnings are existing deprecation/adapter warnings.

`git diff --check`: exit code 0. Git printed only existing LF-to-CRLF normalization warnings.

Raw run artifacts and logs are in the local temp folder (not customer-facing or checked into the report artifact):

- `C:\Users\Administrator\AppData\Local\Temp\smh-live-rag-20261106-oneshot\text-evaluation.json`
- `C:\Users\Administrator\AppData\Local\Temp\smh-live-rag-20261106-oneshot\text-budget-ledger.json`
- `C:\Users\Administrator\AppData\Local\Temp\smh-live-rag-20261106-oneshot\text-evaluation.rag-runs.jsonl`
- `C:\Users\Administrator\AppData\Local\Temp\smh-live-rag-20261106-oneshot\focused-regression.log`
- `C:\Users\Administrator\AppData\Local\Temp\smh-live-rag-20261106-oneshot\backend-full-regression.log`

## Acceptance status

```text
LANGGRAPH_CHAT_QUALITY=PARTIALLY_MEASURED_ON_SYNTHETIC_CASES; HUMAN_LABELS_PENDING
NATURAL_ANSWER_QUALITY=NOT_CERTIFIED; ONE_GROUNDING_DEFECT_FOUND_AND_OFFLINE_GUARDED
MULTI_TURN_CONTEXT=SELECTED_CASES_MATCHED; NOT_GENERALIZED
VISION_INGESTION=OFFLINE_TESTED_WITH_MOCKED_PROVIDER
LIVE_VISION=NOT_RUN_AFTER_PROVIDER_429
IMAGE_TO_CATALOG=OFFLINE_CONTRACTS_TESTED; LIVE_NOT_VERIFIED
RAG_RFM_PERSONALIZATION=OFFLINE_TESTED_ON_FIVE_SYNTHETIC_PERSONAS
RECOMMENDATION_RELEVANCE=SELECTED_SYNTHETIC_BUDGET_CASE_MATCHED; NOT_BENCHMARKED
LIVE_TEXT_MODEL=3_SUCCESSFUL_CALLS; FOURTH_ATTEMPT_HTTP_429; STOPPED
PROVIDER_ERRORS=429_HANDLED_BY_STOPPING_WITHOUT_RETRY_OR_FALLBACK
SCENARIOS_PASS=8_PROVISIONAL_AGENT_COMPARISONS
SCENARIOS_FAIL=1_UNSUPPORTED_POLICY_DENIAL_IN_LIVE_RUN; GUARD_FIX_OFFLINE_TESTED
SCENARIOS_NOT_EXECUTED=2_AFTER_429
REGRESSION=135_FOCUSED_PASS; 2288_BACKEND_PASS_3_SKIP
CONSENT_RACE_P2=OPEN
POSTGRESQL=NOT_VERIFIED
PRODUCTION_READY=NO
REMAINING_BLOCKERS=HUMAN_REVIEW_LABELS; TWO_UNRUN_CASES; LIVE_VISION; POSTGRESQL_RUNTIME; CONSENT_RACE_P2
```

Production readiness is not established. The report confirms offline code/test status and a bounded synthetic live text run only.
