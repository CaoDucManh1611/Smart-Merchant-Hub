# Final RAG recovery acceptance — 2026-11-06

## Scope

Branch: `codex/rag-rfm-all-updates-20261104`. This closes the synthetic answer-evaluator recovery and guarded-fallback work only. Existing unrelated working-tree changes were preserved. No provider request, production database access, migration, reindex, customer message, commit, push, or deployment was performed. `backend/test.db` was not opened or modified. `SALES_JOURNEY_ENGINE_ENABLED` was not enabled; `CONSENT_RACE_P2` remains open.

## Results

- `CASE_010_COMPLETENESS=SAFE_BUT_INCOMPLETE`: the recorded answer (“Chúng tôi không có thông tin về bảo hành trọn đời.”) does not invent a warranty denial, but does not explicitly offer verification by staff. No exact-phrase rule or answer-specific hardcoding was added. Answer quality remains unaccepted for this case.
- `CASE_011_GUARD_BEHAVIOR=PASS`: the unsafe drafts missing the policy eligibility condition are rejected; the bounded retry remains limited and does not turn an unsupported claim into an accepted answer.
- `CASE_011_FINAL_FALLBACK=PASS_OFFLINE`: graph returns its guarded fallback even when handoff persistence fails. Response metadata reports that staff handoff was requested and whether persistence succeeded.
- `CASE_012_MULTISOURCE_REGRESSION=PASS_OFFLINE`: the regression verifies that current catalog price and policy evidence are both selected and cited for a mixed question.
- `SYNTHETIC_NOTIFICATION_ISOLATION=PASS`: evaluator uses a synthetic-only notification spy; it captures intent/reason and asserts no database write or external message. It fails closed for a non-synthetic or wrong-tenant context.
- `DATABASE_QUERY_ONLY=PASS_IN_SYNTHETIC_EVALUATOR`: the synthetic graph scenario uses in-memory SQLite with `query_only=1`; no production database is involved. This is not PostgreSQL runtime evidence.
- `STAFF_HANDOFF_CAPTURE=PASS_OFFLINE`: intent, tenant/conversation identifiers, reason and idempotency context are captured by the test adapter; the evaluator reports persistence separately from the requested handoff.
- `GRAPH_END_TO_END_COMPLETION=PASS_OFFLINE_FOR_CASE_011`: actual graph path with fake model responses returns the safe final fallback and recorded metadata. This does not establish live-provider answer quality.
- `OFFLINE_SCENARIOS=PASS_FOR_COVERED_REGRESSIONS`: focused tests cover current-catalog-vs-stale-KB pricing, accepted catalog citations, image observation evidence, bounded guard retry, safe fallback, mixed catalog+policy retrieval, tenant isolation/capability denial, structured-output/provider failure, and synthetic side-effect isolation. Evidence is the focused test run below; these are code regressions, not an answer-quality score for a full A–H benchmark.
- `SOURCE_FIXES=conversation_graph.py routes guarded handoff persistence through the failure-contained recorder and returns handoff persistence metadata; evaluator adds a read-only synthetic notification adapter and visible error outcomes; graph/evaluator regression tests added.`
- `TENANT_CAPABILITY=FOCUSED_OFFLINE_REGRESSION_PASS`: the focused run includes RAG tenant isolation, capability registry and workspace-module tests. PostgreSQL-specific isolation is not claimed.
- `POST_FIX_LIVE_PROVIDER_TEST=NOT_RUN`: provider budget for the prior three-case Groq verification had already been used. No further Groq/Gemini request was sent.
- `CONSENT_RACE_P2=OPEN`.

## Test evidence

### Focused regression

Command and raw output: [`recovery-focused-20261106-123500.log`](recovery-focused-20261106-123500.log)

Result: **208 passed in 6.13s; exit code 0**. This included `tests/test_conversation_graph.py`, `tests/test_rag_answer_generation_eval.py`, RAG components/tenant-isolation, capability-registry and workspace-module tests. PostgreSQL tests were disabled (`RUN_POSTGRES_TESTS=0`).

### Full backend run

Command/output and tracebacks: [`recovery-full-backend-20261106-123532.log`](recovery-full-backend-20261106-123532.log)

Result: **2265 passed, 6 skipped, 2 failed, 37 subtests passed; exit code 1; 134.82s**. The two failures were working-directory-sensitive RFM artifact expectations: `test_training_precomputes_cache_using_same_tenant_population` received `rules_artifact_unavailable` instead of `industry_prior`, and `test_rfm_excludes_pending_cancelled_refunded_and_future_orders` received `rfm_percentile_v1` instead of `industry_rfm_cold_start_v1` when the suite ran from a temporary current directory.

Both failures were rerun from `backend` with in-memory fixtures and passed: [`recovery-rfm-failures-rerun-20261106.log`](recovery-rfm-failures-rerun-20261106.log), **2 passed in 1.94s; exit code 0**. The complete suite was not rerun from the repository root because relative SQLite paths could touch the protected `backend/test.db`. Therefore the full backend result is **PARTIAL**, not a clean full-suite pass.

`git diff --check`: exit code 0. Git emitted only existing LF/CRLF conversion warnings. No frontend source was changed for this recovery; frontend tests/build were not rerun.

## Implementation vs acceptance

- **IMPLEMENTED:** failure-contained guarded fallback, handoff persistence metadata, synthetic-only read-only notification capture.
- **TESTED:** focused offline regressions pass; two full-suite RFM failures were independently rerun and pass from the expected backend working directory.
- **ANSWER QUALITY:** case 010 remains incomplete; no new live answer evaluation was performed. No aggregate RAG-quality improvement is claimed.
- **RUNTIME / PRODUCTION ACCEPTANCE:** not verified. No PostgreSQL runtime or production service was used.

## Required status fields

```text
CASE_010_COMPLETENESS=SAFE_BUT_INCOMPLETE
CASE_011_GUARD_BEHAVIOR=PASS_OFFLINE
CASE_011_FINAL_FALLBACK=PASS_OFFLINE
CASE_012_MULTISOURCE_REGRESSION=PASS_OFFLINE
SYNTHETIC_NOTIFICATION_ISOLATION=PASS
DATABASE_QUERY_ONLY=PASS_IN_SYNTHETIC_EVALUATOR
STAFF_HANDOFF_CAPTURE=PASS_OFFLINE
GRAPH_END_TO_END_COMPLETION=PASS_OFFLINE_FOR_CASE_011
OFFLINE_SCENARIOS=PASS_FOR_COVERED_REGRESSIONS; NOT_A_FULL_A-H_ANSWER_BENCHMARK
SOURCE_FIXES=GUARDED_FALLBACK_DELIVERY_AND_SYNTHETIC_NOTIFICATION_EVALUATOR
FOCUSED_TESTS=208_PASSED_EXIT_0
FULL_BACKEND_TESTS=PARTIAL_2265_PASSED_6_SKIPPED_2_CWD_SENSITIVE_FAILURES_37_SUBTESTS; BOTH_FAILURES_RERUN_PASS
TENANT_CAPABILITY=FOCUSED_OFFLINE_PASS; POSTGRESQL_NOT_VERIFIED
POST_FIX_LIVE_PROVIDER_TEST=NOT_RUN
CONSENT_RACE_P2=OPEN
REMAINING_BLOCKERS=CASE_010_COMPLETENESS; NO_LIVE_PROVIDER_ANSWER_QUALITY; FULL_SUITE_NOT_CLEAN_IN_ONE_RUN; POSTGRESQL_RUNTIME_NOT_VERIFIED; CONSENT_RACE_P2_OPEN
```

