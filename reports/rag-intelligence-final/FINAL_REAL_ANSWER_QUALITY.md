# Final real-answer quality report

Updated: 2026-11-06 (Asia/Bangkok)  
Repository: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`  
Branch: `codex/rag-rfm-all-updates-20261104`  
HEAD: `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

## Required results

```text
PROVIDER_EVALUATION=COMPLETED; two authorized synthetic runs of the same 20-case dataset; no provider call was made after those runs
MODEL_USED=Groq openai/gpt-oss-20b; run 2 also used Gemini gemini-3.5-flash-lite fallback
ANSWER_CASES_EXECUTED=40 executions total (20 cases repeated in two runs; not 40 independent cases)
ANSWER_CORRECTNESS_BEFORE=NOT_MEASURED; no human-approved answer labels or calibrated judge
ANSWER_CORRECTNESS_AFTER=NOT_MEASURED; no post-code-fix provider run and no human-approved labels
GROUNDEDNESS_BEFORE=NOT_MEASURED
GROUNDEDNESS_AFTER=NOT_MEASURED
HALLUCINATION_BEFORE=NOT_MEASURED
HALLUCINATION_AFTER=NOT_MEASURED
MULTI_TURN_ACCURACY=NOT_MEASURED for generated answers; focused deterministic follow-up regression passes
PRODUCT_ADVICE_ACCURACY=NOT_MEASURED for generated answers
UNAUTHORIZED_ACTIONS=NOT_MEASURED as an answer-quality metric; evaluation used synthetic contexts and did not send customer messages or create real transactions
LATENCY_BEFORE_AFTER=NOT_COMPARABLE; run 1 took 17.953 s (14 logical calls / 14 attempts, Groq only); run 2 took 77.578 s (19 logical calls / 24 attempts, Groq and Gemini fallback). Provider mix and failures differ, and neither run followed the source fixes in this report.
REGRESSION_RESULTS=PASS; 5 targeted regressions passed; broader focused suite 233 passed, 2 warnings
IMPROVEMENTS_IMPLEMENTED=5 reproduced routing/answer issues fixed with focused regression coverage
OPEN_LIMITATIONS=Answer quality and groundedness still need human review; provider reliability errors remain; no post-fix provider evaluation; cost not measured; consent race P2 remains OPEN; Sales Journey flag remains OFF
```

## Provider evaluation evidence

The evaluator called `app.services.conversation_graph.graph_reply` using the synthetic dataset `smh-rag-answer-quality-synthetic-v1`. The same 20 cases were executed twice, so the 40 executions are paired repeats, not an expanded independent sample.

| Run | Responses generated | Case errors | Model calls / physical attempts | Provider mix | Elapsed | Provider-reported tokens |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Before structured-output schema correction | 11/20 | 9 `BadRequestError` | 14 / 14 | Groq 14 | 17.953 s | 8,621 prompt / 1,162 completion |
| After schema correction | 18/20 | 2 (`OperationalError`, `ClientError`) | 19 / 24 | Groq 7, Gemini 17; 2 provider switches | 77.578 s | 29,456 prompt / 2,490 completion |

These runs diagnose execution and routing, but **do not establish answer correctness**. The report JSON explicitly leaves correctness, groundedness, and hallucination rate unmeasured. The cases have no approved human labels or calibrated judge. Run 2 also has infrastructure/provider errors and a different model mix, so its response count or latency must not be interpreted as a quality comparison. Provider pricing was not configured; cost is not measured. The schema correction removed the nine Groq structured-output `BadRequestError` case failures seen in run 1, but that is an execution improvement, not evidence that answers became more accurate.

## Reproduced issues fixed

1. **Explicit comparison blocked by generic discovery question.** A general `next_best_question` could prevent a deterministic comparison even when the query explicitly named products and requested comparison. The graph now lets explicit catalog comparisons proceed through the existing deterministic catalog path. Regression verifies it does not call the LLM for this case.
2. **Recent product follow-up lost without persisted profile memory.** For a short same-conversation follow-up such as asking whether the discussed item is in stock, resolution now falls back to a bounded prior explicit product mention when persistent reply memory returns empty. This reads the current conversation only and does not persist memory or bypass tenant-scoped product lookup.
3. **Unknown explicit SKU fuzzy-matched a shared prefix.** An explicitly labeled code now skips fuzzy ambiguity detection and proceeds to exact catalog lookup, avoiding a false match from a common prefix.
4. **Same-name variants were indistinguishable.** Ambiguity choices now include safe structured variant details such as size/color when available, without exposing internal SKU codes.
5. **Return-policy phrase took price-only shortcut.** The explicit phrase “đổi trong … ngày” is recognized as a return-policy request so the deterministic price-only path does not drop the policy portion.

The source edits are limited to `backend/app/services/auto_reply_service.py` and `backend/app/services/conversation_graph.py`; regression additions are in `backend/tests/test_chatbot_answer_routing.py` and `backend/tests/test_conversation_graph.py`. These files already contained unrelated working-tree changes before this work; only the scoped hunks above were added in this task.

## Tests

- Red reproduction before fixes: 5 targeted regressions failed; raw output is in `test-answer-quality-fixes-red-20261106.log`.
- Focused post-fix run: **5 passed, 107 deselected, 2 warnings, 2.88 s**, exit code 0; `test-answer-quality-fixes-focused-20261106.log`.
- Broader focused backend regression:
  `python -m pytest --noconftest tests\test_chatbot_answer_routing.py tests\test_conversation_graph.py tests\test_conversation_memory_isolated.py tests\test_llm_turn_budget.py tests\test_rag_answer_generation_eval.py tests\test_rag_serving_contract.py -q`
  **233 passed, 2 warnings, 7.44 s**, exit code 0; `test-answer-quality-regression-20261106.log`.
- `git diff --check`: passed. Git printed line-ending conversion warnings for pre-existing modified files; no whitespace error was reported.

The two warnings in pytest concern `PLATFORM_DATABASE_URL` and `TENANT_DATABASE_URL` falling back to legacy `DATABASE_URL`. Tests used `--noconftest` to avoid the repository collection hook attempting a PostgreSQL connection. This is not PostgreSQL runtime verification.

## Scope and remaining verification

- Synthetic-only evaluation; no customer channel messages, real customer data, production database, order, payment, appointment, migration, reindex, deployment, or feature-flag change was performed in this completion.
- No additional provider request was made after the two recorded runs. The five answer-path fixes have offline regression coverage only; answer quality after those fixes remains unmeasured.
- `CONSENT_RACE_P2=OPEN`; `SALES_JOURNEY_ENGINE_ENABLED=False` remains the default. No RFM/LightFM behavior was changed.
- Working-tree changes were preserved. No commit, push, merge, or deploy was performed.

## Evidence files

- `real-answer-quality-20261105-run2.json` and `.rag-runs.jsonl`
- `real-answer-quality-20261105-after-schema-fix.json` and `.rag-runs.jsonl`
- `execution-real-answer-quality-20261105-234218.log`
- `execution-real-answer-quality-after-schema-fix-20261105-234651.log`
- `test-answer-quality-fixes-red-20261106.log`
- `test-answer-quality-fixes-focused-20261106.log`
- `test-answer-quality-regression-20261106.log`
- `execution-answer-quality-fixes-20261106.md`
