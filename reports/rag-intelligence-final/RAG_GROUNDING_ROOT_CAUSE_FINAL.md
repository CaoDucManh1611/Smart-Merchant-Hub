# RAG grounding and multi-source root-cause fix — final report

Date: 2026-11-06  
Repository: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`  
Branch / HEAD: `codex/rag-rfm-all-updates-20261104` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

## Scope and source protection

This work continued from the existing dirty worktree. It did not reset, clean, stash, commit, push, deploy, run a migration/reindex, open `backend/test.db`, call Groq/Gemini, or send customer messages. Tests used synthetic fixtures or in-memory SQLite. The final backend run explicitly set `RUN_POSTGRES_TESTS=0`; it does not verify PostgreSQL runtime. Existing unrelated modifications and untracked artifacts remain in the worktree.

## Case 010 — unknown warranty policy

**Reproduction:** A policy-grounded draft that treated “the source does not mention a warranty period” as a definitive denial can be rejected by the existing claim guard.  
**Root cause:** The model may turn absent policy evidence into a yes/no claim; a standalone guard rejection was not enough to establish the graph’s recovery behavior.  
**Fix:** The graph allows one bounded answer-generation retry and supplies grounding feedback that preserves unknowns and policy qualifiers. A second invalid draft produces a safe uncertainty response, sets `needs_staff_decision`, and reaches the existing staff-notification boundary. The policy guard repair from the preceding recovery work is reused.  
**Evidence:** Graph-level regression covers rejection → corrected answer and rejection → safe fallback.  
**Limit:** Offline synthetic responses only; no post-fix live Groq answer was generated.

`CASE_010_GUARD_RECOVERY=PASS_OFFLINE`

## Case 011 — conditional seven-day return

**Reproduction:** A draft that omitted “eligible products only” can be rejected by the claim guard.  
**Root cause:** Dropping an eligibility qualifier changes a conditional policy into an unconditional promise.  
**Fix:** The bounded retry prompt explicitly requires policy conditions, exclusions, and uncertainty to remain in the answer; a repeated failure uses the safe fallback and staff-decision path.  
**Evidence:** The same graph-level tests exercise the eligible-only return case and assert the qualifier survives repair; repeated rejection is also covered.  
**Limit:** No live provider retest; offline regression does not prove model behavior for all phrasings.

`CASE_011_GUARD_RECOVERY=PASS_OFFLINE`

## Case 012 — mixed catalog fact and policy

**Reproduction and trace diagnosis:** The saved failed-run trace contains `policy:return-v1` and lacks `catalog:alpha`. It does not contain a tool-selection record for the failed run, so the historical trace alone cannot prove whether catalog lookup was attempted and filtered, or omitted before execution. In the current planner, the `_policy_kind(query)` branch returned only `knowledge`, even when the same question explicitly requested product facts. That is a reproducible routing defect consistent with the missing catalog evidence.

**Fix:** For policy questions that also express product/catalog intent, the planner now adds `catalog` alongside `knowledge`, but only when the existing product-catalog capability check allows it. Catalog authorization remains in the execution path. The graph keeps the current catalog price as authoritative and the return term grounded in policy evidence.

**Regression evidence:** `test_mixed_product_price_and_policy_question_retrieves_both_authoritative_sources` supplies a synthetic catalog and synthetic policy for the same tenant. It checks both tool/source paths, current catalog price, policy eligibility/window, merged evidence and the structured answer request. The targeted and full offline suites pass.

**Limit:** This reproduces and fixes the planner bypass in code. The historical trace’s missing planned-tool field prevents a stronger claim about the precise runtime stage of that earlier failed execution. No live question was rerun.

`CASE_012_CATALOG_EVIDENCE_ROOT_CAUSE=POLICY_PLANNER_OMITTED_CATALOG_FOR_MIXED_INTENT; HISTORICAL_STAGE_NOT_FULLY_OBSERVABLE`  
`CASE_012_MULTISOURCE_FIX=IMPLEMENTED_AND_OFFLINE_REGRESSION_PASS`

## Groq HTTP 400 and structured output

**Reproduction/evidence:** The prior bounded Groq run recorded `BadRequestError`, `json_validate_failed`, with no provider parameter or detailed error body. The same strict `shop_answer` schema succeeded for two other cases. The historical trace therefore does not establish a provider/schema incompatibility or an exact request-specific cause.

**Application request defect found:** The final user prompt asked for `{answer, sources}`, while the strict `shop_answer` contract requires `claims`, `calculation`, and `needs_staff_decision` (with claim-level source/offering references). This was contradictory request construction and has been corrected to request exactly the strict schema. It is a real defect, but the available evidence does **not** prove it caused Groq’s HTTP 400.

**Safe recovery:** The graph now catches recognized structured-generation/provider failures at the answer-generation boundary and returns a localized, non-factual safe response. It records only an integer HTTP status and a bounded generation status, not exception text/provider payload. It does not silently switch providers, disable schema validation, or retry the provider call. Answer validation and claim/citation guards remain active. Invalid generated claims may receive the existing single bounded graph retry; repeated invalidity ends in a safe fallback.

**Regression evidence:** A controlled fake provider error with status 400 verifies safe response, no provider-detail leakage, no second provider call, and sanitized run-log status. Prompt/schema contract is covered by the mixed-source graph regression.  
**Limit:** Exact remote HTTP 400 cause remains unknown until an owner-approved, bounded live Groq reproduction can capture sufficient sanitized provider diagnostics.

`HTTP_400_ROOT_CAUSE=UNKNOWN; CONTRADICTORY_APP_PROMPT_SCHEMA_INSTRUCTION_FIXED_BUT_NOT_PROVEN_CAUSAL`  
`STRUCTURED_OUTPUT_SAFETY=STRICT_SCHEMA_AND_GUARDS_RETAINED; OFFLINE_FAILURE_FALLBACK_TESTED`  
`LLM_REPAIR_OR_FALLBACK=ONE_BOUNDED_GRAPH_REPAIR; PROVIDER_ERROR_NO_RETRY; SAFE_FALLBACK_AND_STAFF_SIGNAL_ON_FAILURE`

## Test evidence

Final focused command, run from `backend` with `RUN_POSTGRES_TESTS=0`:

```text
python -m pytest tests/test_conversation_graph.py tests/test_rag_components.py tests/test_rag_smartness_primitives.py tests/test_rag_answer_generation_eval.py tests/test_rag_serving_contract.py tests/test_chatbot_answer_routing.py tests/test_llm_turn_budget.py tests/test_api_key_pool.py tests/test_provider_circuit_breaker.py tests/test_rag_tenant_isolation.py -q
320 passed in 7.08s; exit 0
```

Full backend command, run from `backend` with `RUN_POSTGRES_TESTS=0`:

```text
python -m pytest -q
2265 passed, 3 skipped, 39 warnings, 37 subtests passed in 142.15s; exit 0
```

Synthetic retrieval benchmark:

```text
python scripts/evaluate_synthetic_rag_benchmark.py --results ..\reports\rag-intelligence-final\grounding-retrieval-benchmark-postfix-20261106.json
51 cases; relevant case rate@5=1.0; evidence recall@5=1.0; MRR@5=1.0;
empty-result accuracy=1.0; forbidden-evidence hits=0; tenant-isolation violations=0;
provider calls=0
```

This benchmark exercises BM25 retrieval using synthetic in-memory SQLite data. It does not execute answer generation. Answer grounding, answer correctness, unsupported generated claims, and model calls per answer are all `NOT_MEASURED` by this benchmark.

Additional checks: `python -m py_compile app\services\conversation_graph.py tests\test_conversation_graph.py` passed; `git diff --check` exited 0 (only line-ending notices).

An earlier focused run without `RUN_POSTGRES_TESTS=0` ended `312 passed, 8 failed`. Five answer-evaluation tests were affected by the repository test harness remapping SQLite contexts to its disposable PostgreSQL test path, contrary to those tests’ explicit in-memory SQLite contract. Three graph tests used a minimal fake DB without `.add()` when the safe staff-notification path ran. The runner was then configured explicitly for offline SQLite, and the fake-DB tests were updated to mock that boundary. The final focused and full offline runs above pass. The initial run did not access production, but it did exercise the configured disposable PostgreSQL test harness; PostgreSQL acceptance is not inferred from it.

`FOCUSED_TESTS=320_PASSED_EXIT_0; GRAPH_POLICY/MULTISOURCE/PROVIDER_FAILURE_AND_TENANT_ISOLATION_INCLUDED`  
`BACKEND_TESTS=2265_PASSED_3_SKIPPED_39_WARNINGS_37_SUBTESTS_EXIT_0`  
`RETRIEVAL_TESTS=51_SYNTHETIC_CASES_ALL_RETRIEVAL_METRICS_1.0; ANSWER_QUALITY_NOT_MEASURED`  
`TENANT_ISOLATION=OFFLINE_TESTS_PASS; SYNTHETIC_BENCHMARK_ZERO_CROSS_TENANT_HITS; POSTGRESQL_RUNTIME_NOT_VERIFIED`

## Changed files and remaining blockers

Source/test files changed for this targeted work:

- `backend/app/services/conversation_graph.py`
- `backend/tests/test_conversation_graph.py`

The report and test/benchmark artifacts are under `reports/rag-intelligence-final/`. The worktree contains substantial pre-existing dirty changes, so this list identifies the source/test scope of this task, not every modified or untracked repository path. No commit or push was made.

`SOURCE_FILES_CHANGED=backend/app/services/conversation_graph.py; backend/tests/test_conversation_graph.py`  
`POST_FIX_LIVE_GROQ_RUN=NOT_RUN`  
`REMAINING_BLOCKERS=Exact Groq HTTP 400 cause unverified; post-fix live answer quality not measured; PostgreSQL runtime not verified; CONSENT_RACE_P2 remains OPEN; production behavior and acceptance not verified`

## Artifact paths

- Focused log: `reports/rag-intelligence-final/grounding-focused-final-20261106.log`
- Full backend log: `reports/rag-intelligence-final/grounding-backend-full-20261106.log`
- Initial focused triage log: `reports/rag-intelligence-final/grounding-focused-20261106-01.log`
- Retrieval log: `reports/rag-intelligence-final/grounding-retrieval-postfix-20261106.log`
- Retrieval result: `reports/rag-intelligence-final/grounding-retrieval-benchmark-postfix-20261106.json`
- Historical bounded Groq evidence: `reports/rag-intelligence-final/GROQ_RECOVERY_RESULT.md`
