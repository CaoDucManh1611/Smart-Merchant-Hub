# Groq Recovery and RAG Answer Quality — 2026-11-06

## Scope and source protection

- Repository: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`
- Branch/HEAD remained `codex/rag-rfm-all-updates-20261104` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`.
- Approval: Groq `openai/gpt-oss-20b`; up to 3 synthetic cases, 6 physical attempts, 30,000 input and 5,000 output tokens. Used 3 cases and 3 attempts, with no provider switch.
- Each case used a fresh in-memory SQLite context. Graph execution was query-only; data was synthetic. No external customer channel, order, payment or appointment was invoked. `backend/test.db` was not directly opened or modified and its Git status is clean.
- Safe-source manifest `C:\Users\Administrator\AppData\Local\Temp\smh-primary-source-manifest-20261105-final.csv`: 158 entries, 146 exact hash matches, 12 changed-but-present, 0 missing. The changed files remain present in the dirty worktree; this task did not replace the worktree.
- The Nov 5 count of 273 used `--untracked-files=all`; the Nov 6 count of 172 used default `--untracked-files=normal`, which collapses untracked directories. Current counts: 172 normal and 367 expanded (92 tracked modifications + 275 individual untracked files; normal view shows 92 tracked entries + 80 untracked directory/file entries). There are 8,138 ignored entries, excluded from both ordinary counts. The older 273 path listing was not retained, so later additions cannot be reconciled path-by-path; the safe-source manifest confirms no source is missing. Later reports/evaluation artifacts account for some untracked files.
- `SALES_JOURNEY_ENGINE_ENABLED=False` remains the default.

## Groq run

| Case | Result | Objective observation |
| --- | --- | --- |
| `answer-010-no-evidence` | Groq success; structured parse and validation passed | Model inferred “no lifetime warranty” from evidence that only says the policy does not mention a warranty period; it omitted staff verification. |
| `answer-011-policy-grounded` | Groq success; structured parse and validation passed | Model gave the 7-day return window but dropped the source condition that the product must be eligible. |
| `answer-012-multi-source` | HTTP 400 `BadRequestError`, code `json_validate_failed`, param unavailable | No final answer. Captured retrieval contained `policy:return-v1` but not expected `catalog:alpha`; tool selection was not recorded for the failed run. |

The application requested strict `json_schema` output with schema `shop_answer`, fingerprint `16dcdc5b5ee100dffa8f69508f083912a54728e4c4f8bc2c64cb8d6d3e476b77`. Two requests with the same schema succeeded; the third failed before application parsing. The trace has no error parameter or detailed provider body, so the underlying HTTP 400 cause is **UNKNOWN**. The evidence does not establish schema incompatibility; no extra request was made to guess.

- Calls/attempts: 3/3; provider switches: 0; non-Groq attempts: 0.
- Provider-reported usage: 4,137 input / 363 output tokens. Conservative budget reservations: 23,941 input / 875 output, within the approved 30,000 / 5,000 limits.
- Structured output: 2/2 successful responses parsed and validated; the third failed at the provider before parse.
- Live HTTP 429 was not observed. `Retry-After` numeric/date handling, cooldown and circuit recovery were checked only by offline tests.

## Deterministic answer checks

The case-level checks are in `groq-recovery-objective-checks-20261106.json`. These are deterministic checks, not an LLM judge or human review. No aggregate hallucination rate is claimed.

All 3 cases fail at least one required check. Cases 010 and 011 were replayed against the fixed citation guard and are now rejected: one infers a definitive policy denial from unknown evidence; the other drops a policy qualifier. Case 012 has no answer and the captured retrieval artifact lacks the expected catalog evidence.

## Minimal source fix

- `backend/app/rag/answer_guard.py`: reject definitive policy denials inferred from unknown evidence and require explicit eligibility/conditional language in the related answer sentence.
- `backend/tests/test_rag_components.py`: regression for the two observed failures, safe uncertainty wording, English/Vietnamese variants, and a qualifier incorrectly placed in another sentence.

The fix uses the existing structured-claim guard and graph retry/fallback path. No new model, retrieval algorithm, route, or retry mechanism was added. It was verified offline; live answers were not regenerated because the 3-case execution cap had been reached.

## Verification

- Focused command (final source):
  `python -m pytest tests/test_rag_components.py tests/test_rag_smartness_primitives.py tests/test_conversation_graph.py tests/test_rag_answer_generation_eval.py tests/test_rag_serving_contract.py tests/test_chatbot_answer_routing.py tests/test_llm_turn_budget.py tests/test_api_key_pool.py tests/test_provider_circuit_breaker.py -q`
  **299 passed**, exit 0.
- Full backend command (final source, `RUN_POSTGRES_TESTS=0`): `python -m pytest -q`
  **2,259 passed, 3 skipped, 39 warnings, 37 subtests passed**, exit 0, 136.57 seconds. This does not verify PostgreSQL runtime.
- Retrieval command: `python scripts/evaluate_synthetic_rag_benchmark.py --results ..\reports\rag-intelligence-final\groq-recovery-retrieval-benchmark-20261106.json`
  **51 synthetic cases**, Recall@5=1.0, MRR@5=1.0, empty-result accuracy 12/12, 0 forbidden-evidence hits, 0 tenant-isolation violations, 0 provider calls. It does not measure answer quality.
- `git diff --check`: exit 0; Git emitted only LF-to-CRLF notices.
- The first focused run exposed a false negative in the new eligibility matcher. The phrase/topic match was corrected; the final focused and full runs above both pass.

## Final state

```text
SOURCE_INTEGRITY=PASS_WITH_PREEXISTING_DIRTY_WORKTREE; 158 checked, 146 exact, 12 changed-but-present, 0 missing
SOURCE_STATUS_DIFFERENCE=273 expanded on Nov 5; 172 collapsed on Nov 6; current 172 normal / 367 expanded; 8138 ignored entries excluded
PROVIDER_APPROVAL=APPROVED_BOUNDED_TEST
MODEL=openai/gpt-oss-20b
SYNTHETIC_CASES_EXECUTED=3/3
PHYSICAL_ATTEMPTS=3/6
INPUT_TOKENS=4137 reported; 23941 conservatively reserved / 30000
OUTPUT_TOKENS=363 reported; 875 conservatively reserved / 5000
HTTP_400_ROOT_CAUSE=UNKNOWN; json_validate_failed; param unavailable; same schema succeeded twice
HTTP_429_HANDLING=OFFLINE_REGRESSION_PASS; no live 429 observed
CIRCUIT_RECOVERY=OFFLINE_REGRESSION_PASS; no live rate-limit event
STRUCTURED_OUTPUT_VALID=2 successful responses parsed and validated; 1 provider error before parse
FINAL_LLM_GENERATED_ANSWERS=2
ANSWER_OBJECTIVE_CHECKS=0/3 fully passing; human review pending
GROUNDING_RESULTS=0/3 fully passing; two policy-scope violations; third no answer and captured catalog evidence missing
UNSUPPORTED_CLAIMS=1 explicit unsupported policy denial; 1 omitted eligibility qualifier; no aggregate rate claimed
PROVIDER_RELIABILITY=2 successful final generations / 3 attempts; sample too small for a reliability estimate
SIDE_EFFECT_SAFETY=PASS for recorded synthetic run; no external customer channel or transaction side effects
SOURCE_FIXES=answer_guard policy-scope checks plus regression tests
FOCUSED_REGRESSION=299 passed
BACKEND_REGRESSION=2259 passed, 3 skipped, 37 subtests passed
RETRIEVAL_REGRESSION=51 cases; Recall@5=1.0; MRR@5=1.0; empty accuracy=12/12; answer quality not measured by this benchmark
LLM_RECOVERY=PASS; two final answers generated through the application graph
ANSWER_QUALITY=NOT_PASS; 0/3 pass objective checks; no human review
CONSENT_RACE_P2=OPEN
REMAINING_BLOCKERS=HTTP 400 cause unresolved; case 012 catalog evidence/tool route unresolved; no post-fix live regeneration within case cap; human review pending
```

## Logs and traces

- `groq-recovery-3case-20261106.json` — sanitized graph results, evidence, model output, routes and attempts.
- `groq-recovery-3case-20261106.rag-runs.jsonl` — sanitized RAG run records.
- `groq-recovery-objective-checks-20261106.json` — deterministic per-case grading.
- `groq-recovery-budget-20261106.json` — attempt and token ledger.
- `groq-recovery-execution-20261106.log` — preflight stop and bounded provider run.
- `groq-recovery-focused-20261106.log` — first focused attempt and corrected rerun.
- `groq-recovery-focused-final-20261106.log` — final focused regression.
- `groq-recovery-backend-full-final-20261106.log` — final full backend regression.
- `groq-recovery-retrieval-20261106.log` and `groq-recovery-retrieval-benchmark-20261106.json` — provider-free retrieval benchmark.
