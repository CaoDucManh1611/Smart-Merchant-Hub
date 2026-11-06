# Final post-fix Groq verification — 2026-11-06

## Scope and method

- Branch: `codex/rag-rfm-all-updates-20261104`.
- Entry point: `app.services.conversation_graph.graph_reply` through the synthetic answer evaluator.
- Provider/model: Groq `openai/gpt-oss-20b`; no generation fallback provider or model switch. Retrieval ran in BM25 mode. No customer channel was invoked.
- Three unique synthetic cases were executed. Case 012 had one bounded revalidation after its first provider call returned HTTP 429. Total: 5 physical attempts; 29,407 input-token and 1,658 output-token reservations, versus 8,637 input and 1,146 output tokens reported by successful provider responses. Cost is not measured because the evaluator has no price configuration.
- No API key or credential is included in these artifacts.

## Case results

| Case | Outcome | Evidence and answer | Assessment |
|---|---|---|---|
| 010 — unknown lifetime warranty | One valid structured Groq answer. | Knowledge evidence said the policy does not state the warranty duration. Answer: “Chúng tôi không có thông tin về bảo hành trọn đời.” | Safe: it did not claim the product lacks a lifetime warranty. Content incomplete against the stricter expected wording: it did not explicitly say it cannot confirm or offer staff verification. Not a strict objective pass. |
| 011 — conditional 7-day exchange | Two structured responses omitted “if eligible”; the bounded retry repeated the omission. The guard selected the safe fallback and staff-decision path. | Both drafts said the item could be exchanged within seven days without the eligibility condition. The evaluator then failed while persisting a synthetic `Notification` into query-only SQLite; no model was flushed and no external channel was attempted. The final customer-visible fallback text was therefore not captured in this live run. | Guard rejection and bounded retry are evidenced; final graph delivery is not verified for this case. Classified `SAFETY_PASS_CONTENT_INCOMPLETE`, not a full answer pass. Existing offline graph regression for this path passed. |
| 012 — price plus exchange policy | First call returned HTTP 429. The single allowed revalidation generated a valid structured answer. | Planner selected `catalog` and `knowledge`; the evidence manifest records both `CURRENT_CRM_CATALOG` and `KNOWLEDGE`, with one catalog evidence item. Answer: “Alpha có giá 180.000 đồng và có thể đổi trong 7 ngày nếu đủ điều kiện.” | Strict objective pass on revalidation: both requested facts and the eligibility condition are present and supported by the synthetic catalog and policy evidence. |

## Objective and safety summary

- Strict answer-objective pass: **1/3 cases** (case 012). Case 010 is safe but incomplete; case 011 has no captured final output and cannot pass.
- Four successful provider responses (case 010: 1, case 011: 2, case 012 revalidation: 1) all parsed and passed structured schema validation. The other physical attempt returned 429 and had no response to validate.
- No accepted model output contained an observed unsupported price, policy denial, or cross-tenant fact. Case 011's two unsafe drafts were rejected before becoming a graph answer. However, its final delivery was not captured, so end-to-end safety for that output remains unverified.
- Safe fallback was selected twice (case 011 guard rejection and case 012's initial 429). The initial synthetic notification write failed before a customer-visible final response was captured in those two paths. Case 012 was then revalidated successfully with a no-op notification boundary scoped to the synthetic runner; this did not change application source.
- HTTP 400 was **not observed** in this run. The historical `json_validate_failed` HTTP 400 cause remains unknown.
- Five provider attempts yielded four successful responses and one rate limit. This three-case sample is not a provider-reliability estimate.
- No overall RAG accuracy or hallucination rate is claimed. There was no human/approved judge, no claim-level annotation, and no configured provider pricing.

## Safety, regression, and source changes

- The runner set database URLs to `sqlite://`; the synthetic context factory creates an in-memory SQLite database and seeds only the current synthetic case. No `backend/test.db`, production database, or customer data was read.
- In the initial run, `PRAGMA query_only` prevented the staff-notification insert; no notification was flushed and no channel send occurred. In case 012 revalidation the runner replaced `_notify_rag_handoff_required` with a no-op only for that synthetic run. Its result artifact reports `database_query_only=false`; therefore this report does not claim query-only was active during revalidation. The result also records no attempted/flushed database models and no external channel execution.
- No serving source was changed in this verification. The observed case 011 issue is model non-adherence to a policy qualifier; the existing guard rejected it. No prompt/guard change was made because case 011 exhausted its per-case provider-attempt limit and could not be safely revalidated under this approval.
- Focused offline regression: **6 passed**, exit code 0, 8.36 seconds. It covered one bounded policy retry, safe fallback/handoff, preserving policy eligibility conditions, and rejection of unsupported policy denial. See the captured command and output in the regression log.
- `git diff --check`: exit code 0. Git emitted only line-ending conversion warnings for existing dirty files.
- `SALES_JOURNEY_ENGINE_ENABLED` remains `False` in configuration. `CONSENT_RACE_P2` remains `OPEN`.

## Required results

PROVIDER_APPROVAL=APPROVED_LIMITED
MODEL=openai/gpt-oss-20b via Groq only
CASES_EXECUTED=3 unique synthetic cases (case 012 revalidated once)
PHYSICAL_ATTEMPTS=5/6; per-case 010=1, 011=2, 012=2
MODEL_GENERATED_ANSWERS=2 accepted final model answers (010 and 012); case 011 produced 2 rejected drafts
REPAIRED_ANSWERS=0 successful repairs; case 011's single retry repeated the missing qualifier
SAFE_FALLBACKS=2 selected; customer-visible fallback output not captured on the two initial failure paths
CASE_010_RESULT=SAFETY_PASS_CONTENT_INCOMPLETE
CASE_011_RESULT=SAFETY_PASS_CONTENT_INCOMPLETE; final graph output not captured after synthetic notification persistence error
CASE_012_RESULT=PASS_ANSWER_OBJECTIVE on bounded revalidation after initial HTTP 429
CASE_012_CATALOG_EVIDENCE=VERIFIED with catalog and knowledge selected; one catalog evidence item and both evidence sources in manifest
HTTP_400_RESULT=NOT_OBSERVED; historical root cause remains UNKNOWN
STRUCTURED_OUTPUT_VALIDITY=4/4 successful provider responses parsed and schema-validated; one 429 had no response
ANSWER_OBJECTIVE_PASS=1/3 under strict required-claim grading; no aggregate quality claim
SAFETY_PASS=PARTIAL; unsafe case 011 drafts were blocked, but its final delivery was not captured
CONTENT_COMPLETENESS=1/3 strict pass; case 010 partial, case 011 unverified/incomplete, case 012 complete
GUARD_EFFECTIVENESS=VERIFIED for case 011 rejection and one bounded retry; offline regression 6 passed
PROVIDER_RELIABILITY=4 successful responses/5 attempts, 1 HTTP 429; sample too small for a reliability estimate
SOURCE_FIXES=NONE; no serving source changed; case 012 notifier was suppressed only in its synthetic revalidation runner
REGRESSION=6 passed, 0 failed; focused offline suite only
CONSENT_RACE_P2=OPEN
REMAINING_BLOCKERS=Case 011 final answer not captured and cannot be called again under its 2-attempt cap; historical HTTP 400 cause unknown; no human answer judge or claim annotation; provider cost not configured; no production/runtime quality acceptance
