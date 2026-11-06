# Execution log — answer-quality diagnostics and targeted fixes

Date: 2026-11-06 (Asia/Bangkok)  
Repository: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`  
Branch: `codex/rag-rfm-all-updates-20261104`  
HEAD: `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

## Scope and preservation

The workspace already contained extensive uncommitted changes from prior work. Those changes were retained; there was no reset, clean, stash, checkout, commit, push, merge, or deploy. This pass added focused changes to two service files and two regression files, plus this report and the final quality report. Existing unrelated diffs in those same files were not reverted.

No customer channel, real customer data, production database, order, payment, appointment, migration, or reindex was used. No provider calls were made after the two previously authorized evaluation runs. The Sales Journey flag remains default OFF; consent race P2 remains OPEN.

## Recorded synthetic provider runs

Dataset: `smh-rag-answer-quality-synthetic-v1`, 20 cases, invocation path `app.services.conversation_graph.graph_reply`.

1. `execution-real-answer-quality-20261105-234218.log` and `real-answer-quality-20261105-run2.json`:
   - 20 cases; 11 nonempty generated answers; 9 case failures, all `BadRequestError` from strict structured output.
   - 14 logical model calls / 14 physical attempts; Groq `openai/gpt-oss-20b` only; 17.953 s.
   - Provider-reported usage: 8,621 prompt and 1,162 completion tokens. Cost was not measured.
2. `execution-real-answer-quality-after-schema-fix-20261105-234651.log` and `real-answer-quality-20261105-after-schema-fix.json`:
   - Same 20 cases; 18 nonempty generated answers; case errors: `answer-002-budget` (`OperationalError`) and `answer-013-cross-tenant` (`ClientError`). Root causes were not established in this pass.
   - 19 logical calls / 24 physical attempts; Groq `openai/gpt-oss-20b` 7 attempts and Gemini `gemini-3.5-flash-lite` 17 attempts; 2 provider switches; 77.578 s.
   - Attempt log reports 4 `ServerError`, 1 `RateLimitError`, and 1 `ClientError`. Provider-reported usage: 29,456 prompt and 2,490 completion tokens. Cost was not measured.

The JSON results mark answer correctness, groundedness, and hallucination rate `NOT_MEASURED`: there are no human-approved labels or calibrated judge results. The two runs differ in schema and provider mix and are diagnostics, not a valid quality A/B. They predate the source fixes below. No provider rerun was made after those fixes.

## Reproduced answer-path failures and changes

Five regressions were first run red and are recorded in `test-answer-quality-fixes-red-20261106.log` (**5 failed**, exit 1; 107 deselected). The failures represented:

- Explicit catalog comparison blocked by a generic needs-discovery prompt.
- Same-chat stock follow-up losing the prior product when persistent profile memory is empty.
- Unknown explicit SKU being treated as a fuzzy prefix match.
- Ambiguous identical product names lacking variant details.
- Price plus return-window question being shortened to price-only.

Minimal fixes were added:

- `backend/app/services/conversation_graph.py`: route explicit product comparisons through the existing deterministic catalog path before a generic follow-up question can stop them.
- `backend/app/services/auto_reply_service.py`: bounded prior-product resolution from the same conversation when persistent reply memory is empty; exact lookup for explicitly labeled codes; structured variant detail in clarification without exposing SKU; recognition of “đổi trong … ngày” as a return-policy request.
- Regression coverage added to `backend/tests/test_chatbot_answer_routing.py` and `backend/tests/test_conversation_graph.py`.

The conversation fallback is read-only and bounded to the current conversation; it does not persist extra memory. Tenant-scoped product resolution remains in the existing resolver. The explicit-code branch avoids fuzzy matching; exact catalog lookup still determines whether the code exists.

## Test commands and outcomes

### Targeted red reproduction

Command:
`python -m pytest --noconftest tests\test_chatbot_answer_routing.py tests\test_conversation_graph.py -k "explicit_unknown_sku or ambiguous_same_name_variants or stock_followup_uses_unambiguous or price_and_return_window or explicit_catalog_comparison_bypasses" -q`

Exit code: 1; **5 failed, 107 deselected**, 3.29 s. Raw output: `test-answer-quality-fixes-red-20261106.log`.

### Targeted post-fix regression

Command:
`python -m pytest --noconftest tests\test_chatbot_answer_routing.py tests\test_conversation_graph.py -k "explicit_unknown_sku or ambiguous_same_name_variants or stock_followup_uses_unambiguous or price_and_return_window or explicit_catalog_comparison_bypasses" -q`

Exit code: 0; **5 passed, 107 deselected, 2 warnings**, 2.88 s. Raw output: `test-answer-quality-fixes-focused-20261106.log`.

### Broader focused regression

Command:
`python -m pytest --noconftest tests\test_chatbot_answer_routing.py tests\test_conversation_graph.py tests\test_conversation_memory_isolated.py tests\test_llm_turn_budget.py tests\test_rag_answer_generation_eval.py tests\test_rag_serving_contract.py -q`

Exit code: 0; **233 passed, 2 warnings**, 7.44 s. Raw output: `test-answer-quality-regression-20261106.log`.

Warnings: `PLATFORM_DATABASE_URL` and `TENANT_DATABASE_URL` fell back to legacy `DATABASE_URL`. `--noconftest` avoided the repository test bootstrap attempting PostgreSQL. PostgreSQL runtime and concurrency were not tested.

### Whitespace check

Command: `git diff --check`  
Exit code: 0. No whitespace errors. Git emitted line-ending conversion warnings for modified files; these did not indicate a diff-check failure.

## Final verification state

- `IMPLEMENTED`: five targeted routing/formatting behaviors above.
- `TESTED`: 5/5 targeted regressions and 233 focused regression tests pass offline.
- `ANSWER_QUALITY_VERIFIED`: no. Post-fix correctness, groundedness, hallucination, multi-turn answer quality, product advice accuracy, and unauthorized-action answer rate remain `NOT_MEASURED` pending valid reviewed labels and an approved evaluation run.
- `PROVIDER_ERRORS_OPEN`: the second synthetic evaluation had two case errors and recorded retry/fallback errors; they were not modified or re-run in this pass.
- `POSTGRESQL_RUNTIME`: not verified.
- `CONSENT_RACE_P2`: OPEN.
- `SALES_JOURNEY_ENGINE_ENABLED`: default remains `False`.
- `GIT_DELIVERY`: no commit, push, merge, or deploy.
