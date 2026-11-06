# LLM Pipeline Reliability & Answer Quality — 2026-11-06

## Scope and repository state

Repository: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`  
Branch: `codex/rag-rfm-all-updates-20261104`  
HEAD: `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

The working tree contains 172 changed/untracked Git status entries at final inspection, including extensive pre-existing work and report artifacts. It was preserved. No reset, clean, stash, commit, push, deploy, migration, production DB access, `backend/test.db` access, channel send, or provider request was made. `git diff --check` exited 0; Git printed only line-ending conversion warnings. `SALES_JOURNEY_ENGINE_ENABLED` remains default `False` (config line 145), and the evaluator rejects a run if it is enabled.

## Findings and status fields

HTTP_400_ROOT_CAUSE=UNKNOWN_FROM_AVAILABLE_EVIDENCE. The prior run records one Groq HTTP 400 but omits provider error `code`, `param`, schema name/fingerprint, and response-format details. It is not valid to conclude that Groq rejected a particular schema feature. The gateway now captures sanitized status/code/param and schema name/fingerprint for a future owner-approved run. No provider call was made to obtain that missing evidence.

HTTP_429_ROOT_CAUSE=Provider rate/quota response. The old run received one HTTP 429. A reproduced offline defect ignored the HTTP-date form of `Retry-After`, allowing the key cooldown to expire before the provider-specified time. Handling now accepts numeric and HTTP-date values, applies the larger of configured cooldown and provider delay, and caps the delay at one hour. A provider-wide 429 is not immediately replayed on a sibling key.

CIRCUIT_BREAKER_BEHAVIOR=Per model route, failure threshold 1 and recovery timeout 60 seconds in the LLM gateway. Open routes reject calls until cooldown; recovery admits only one half-open probe; a successful probe closes the circuit, a failed probe reopens it, and neutral outcomes release the probe. Offline state-machine and concurrency tests pass. No real-provider recovery was tested.

PROVIDER_ATTEMPT_ACCOUNTING=Prior synthetic run: 20 cases; 14 logical model calls; 5 physical Groq attempts; 3 provider successes, 1 HTTP 400 and 1 HTTP 429; no provider switch. The three successes were intermediate calls, not completed user-visible model answers: case 002 made two successful intermediate calls then failed with 400; case 006 made one successful intermediate call then failed with 429. Subsequent model-required turns were circuit-blocked. Reported successful-attempt usage totals 4,100 prompt and 852 completion tokens; monetary cost is unavailable because pricing is not configured. There were 9 nonempty outputs (7 deterministic fact/lookup/comparison responses and 2 clarifications) and 0 completed LLM-generated final answers. The old artifact did not capture final-answer schema provenance.

STRUCTURED_OUTPUT_COMPATIBILITY=Offline schema construction, strict local validation, parse-state recording, and telemetry are covered. The old 400 cannot identify the incompatible field. Actual Groq native structured-output compatibility is NOT_VERIFIED until an approved bounded provider run records the new sanitized fields. The benchmark had Gemini fallback disabled and routes restricted to the named Groq model; this is deliberate single-provider measurement, not proof fallback is misconfigured.

EVALUATION_HARNESS_STATUS=Updated classification distinguishes `DETERMINISTIC_ANSWER`, `LLM_GENERATED_ANSWER`, `VALIDATED_FALLBACK`, `CLARIFICATION`, `PROVIDER_HTTP_400`, `PROVIDER_RATE_LIMIT_429`, `CIRCUIT_OPEN`, and `INFRASTRUCTURE_ERROR`. A final answer is counted as LLM-generated only when the graph ends in `graph_answer` and a validated `shop_answer` invocation has nonempty model text, successful parse and validation, and no error. Planner/query-rewrite/arithmetic calls no longer count as final generation. The result artifact captures model invocations, response text separately from user-visible text, evidence IDs, schema metadata, usage, latency, tools, retries/circuit transitions, and attempted/flushed writes. This corrects provenance accounting; it does not establish answer quality.

DETERMINISTIC_ANSWER_CASES=7 of the 9 nonempty outputs in the prior run were deterministic catalog answers; 2 were clarifications. This is a retrospective classification from recorded statuses, not a new provider run.

ACTUAL_LLM_ANSWER_CASES=0 completed model-generated final answers in the prior 20-case run. Three successful physical calls were intermediate only.

GOLD_CASE_016_STATUS=PENDING_HUMAN_REVIEW for the claim that Beta is a suitable substitute. Evidence proves Alpha is out of stock and Beta is active/in stock; it does not prove interchangeability or suitability. Keep the independently supported Alpha stock claim. Original fixture remains unchanged.

GOLD_CASE_020_STATUS=PENDING_HUMAN_REVIEW for expected action. The prompt asks about a 10:00 consultation slot but does not identify the service. Asking which service is intended may be correct. No booking must be created. Original fixture remains unchanged.

SOURCE_FIXES=Provider Retry-After handling and 429 replay policy (`backend/app/services/api_key_pool.py`); single-flight half-open circuit probe and neutral release (`backend/app/services/provider_circuit_breaker.py`); sanitized structured-provider/schema telemetry (`backend/app/rag/llm_caller.py`, `backend/app/rag/turn_budget.py`); explicit final-answer provenance taxonomy (`backend/scripts/evaluate_rag_answer_generation.py`). Regression coverage was added/updated in `backend/tests/test_api_key_pool.py`, `backend/tests/test_provider_circuit_breaker.py`, `backend/tests/test_llm_turn_budget.py`, and `backend/tests/test_rag_answer_generation_eval.py`. Existing dirty work outside this task was left intact.

FOCUSED_REGRESSION=PASS: 89 passed in 3.09s, exit 0. Command: `RUN_POSTGRES_TESTS=0 python -m pytest tests/test_rag_answer_generation_eval.py tests/test_llm_turn_budget.py tests/test_api_key_pool.py tests/test_provider_circuit_breaker.py -q`. Log: `reports/rag-intelligence-final/llm-pipeline-final-focused-20261106.log`. Initial red evidence: `llm-pipeline-diagnostic-red-20261106.log` records the HTTP-date cooldown defect and missing HTTP 400 route status in structured trace; earlier harness collection also failed because the classifier did not exist yet (`llm-pipeline-red-20261106.log`).

BACKEND_REGRESSION=PASS: 2,257 passed, 3 skipped, 39 warnings, 37 subtests passed in 142.41s; exit 0. Command was the offline runner with outbound network blocked and `RUN_POSTGRES_TESTS=0`: `python .pytest_tmp/pytest_offline_runner.py -q`. Log: `reports/rag-intelligence-final/llm-pipeline-backend-full-20261106.log`. The skipped tests include PostgreSQL-only coverage; this is not PostgreSQL runtime verification.

RETRIEVAL_REGRESSION=PASS: 51 synthetic cases, 30 documents, 3 tenants, top-k 5. Relevant-case rate@5 1.0; evidence recall@5 1.0; MRR@5 1.0; empty-result accuracy 1.0; forbidden evidence 0; tenant-isolation violations 0; provider calls 0. Command: `python backend/scripts/evaluate_synthetic_rag_benchmark.py --results ../reports/rag-intelligence-final/retrieval-benchmark-post-llm-pipeline-20261106.json`. Logs/results: `reports/rag-intelligence-final/retrieval-benchmark-post-llm-pipeline-20261106.log` and `.json`. Answer correctness, grounding, unsupported claims, and live model calls per answer are NOT_MEASURED; this benchmark measures retrieval only.

POST_REPAIR_PROVIDER_RUN=NOT_RUN_UNTIL_APPROVED

REMAINING_BLOCKERS=1) Need a separately approved, bounded provider run to learn the actual HTTP 400 code/param/schema compatibility and to measure completed LLM-generated answers. 2) Gold cases 016 substitute suitability and 020 expected action need owner/human review. 3) Answer correctness, grounding, hallucinations, and cost remain NOT_MEASURED. 4) Consent race P2 remains OPEN; no PostgreSQL concurrency verification. 5) Recommendation impressions are not measured by the query-only answer evaluator: `recommendation_evidence` calls the ranker with `record_impressions=False`, while a later auto-reply path records impressions. Safe evaluation strategy: a separate per-case disposable SQLite `sqlite://` database seeded only with synthetic tenant data; keep production authorization/capability code active; use a fake outbound adapter and deny network; permit only the recommendation request and impression interaction writes in that disposable database; compare persisted product IDs with the exact candidate IDs in the simulated delivered answer; assert no order/payment/appointment writes, then dispose the database. This strategy is identified but not implemented or executed here. No impression counts are inferred from retrieved/ranked candidates.

## Evidence and limits

| Area | Result | Evidence boundary |
|---|---|---|
| Retry-After / 429 | Fixed and offline-regression tested | No live quota behavior checked |
| Structured error telemetry | Fixed and mock-tested | Root cause of historical HTTP 400 unknown |
| Circuit breaker | Offline state machine/concurrency tested | Provider recovery not runtime-tested |
| Evaluator provenance | Fixed and regression-tested | No model answer quality conclusion |
| Retrieval | Synthetic benchmark passed | Does not assess generated answers |
| Gold 016/020 | Pending human review | No machine-generated approval |
| PostgreSQL/consent race | Not verified; P2 remains open | SQLite suite is not evidence of PostgreSQL concurrency |
| Recommendation impression evaluation | Safe approach documented, not run | Existing answer evaluator remains query-only |

The final result is an offline reliability and accounting repair. It does not establish that the RAG answers are more correct or that provider generation now succeeds. The next answer-quality run requires fresh owner approval for bounded Groq requests and human review of the two disputed gold expectations.

