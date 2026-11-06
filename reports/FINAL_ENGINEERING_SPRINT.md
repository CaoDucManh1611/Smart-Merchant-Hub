# Smart Merchant Hub — Final Engineering Sprint

**Date:** 2026-11-06 (local workspace date)  
**Repository:** `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`  
**Branch / HEAD:** `codex/rag-rfm-all-updates-20261104` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61` (unchanged)

## Summary

Three read-only agents were launched. Agent A reviewed RAG/sales intelligence and initially flagged a budget-ranking issue; its final review noted the graph receives at most three `served_items`, so the graph-only five-candidate regression did not represent the production path. Reviewing the complete path showed `serve_recommendations()` applies `_filter_query_candidates()` (including the stated budget) before building its top-three `served_items`. The artificial graph test and corresponding application edit were removed; no budget defect was established. Agent B reviewed provider reliability and confirmed that recorded HTTP 429 attempts must stop the synthetic batch even when the graph emits a safe fallback. Agent C reviewed security/release risks and left the consent-versus-memory race as an open P2. No agent edited source or called a provider.

The only code change retained in this sprint is an offline regression for the already implemented 429 batch-stop contract. No serving behavior changed.

## Changes made in this sprint

| File | Change |
| --- | --- |
| `backend/tests/test_rag_answer_generation_eval.py` | Add an offline regression proving a graph safe fallback does not hide a recorded 429 and the evaluator stops before executing later cases. |

No application source, user-facing model calls, retrieval algorithms, prompt policy, consent policy, or feature flags were changed. Case 002's end-to-end root cause remains unproven.

## Regression evidence

All tests used the isolated backend interpreter at `C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated\backend\.venv\Scripts\python.exe`, with `RUN_POSTGRES_TESTS=0`, `PYTHONDONTWRITEBYTECODE=1`, provider-key environment variables cleared, and pytest cache disabled. This avoided global dependency changes, PostgreSQL bootstrap, and provider access.

| Run | Result |
| --- | --- |
| Focused budget/service + 429 evaluator checks | `pytest -p no:cacheprovider tests/test_personalized_rag_pipeline.py tests/test_rag_answer_generation_eval.py -q -k "preferences_cannot_override_budget_sku_stock_or_live_price or graph_safe_fallback_with_recorded_429_stops_batch_without_provider_calls" --tb=short` — **2 passed, 49 deselected**, exit 0. This confirms the real recommendation service's budget guard and the evaluator stop condition. |
| Full backend offline regression | `pytest -p no:cacheprovider -q --tb=short` — **2,278 passed, 6 skipped, 37 subtests passed**, exit 0, 138.92 seconds. The run emitted 40 deprecation warnings (SQLite datetime adapter, `datetime.utcnow()`, and SciPy L-BFGS options); no test failures. |
| Whitespace check | `git diff --check` — no whitespace errors; Git emitted existing LF/CRLF conversion warnings. |

The evaluator regression verifies control flow only. The prior 20-case Groq run is not repeated and is not evidence of answer-quality improvement: its report records 7/20 automated objective passes, 20/20 human labels pending, and answer correctness/grounding/hallucination as `NOT_MEASURED`.

## Agent findings and remaining issues

- **Agent A — RAG/sales:** its follow-up review correctly noted the five-candidate graph regression bypassed the real service contract. Source inspection confirmed the actual service applies the budget filter before selecting the top three. The synthetic regression and no-op graph edit were removed. Case 002's reported mismatch is not fully explained by available traces; no speculative patch was made. Cases 010–014 include provider/error fallback behavior, so no claim about normal provider answer quality is made.
- **Agent B — provider reliability:** the offline batch-stop regression passes. This sprint did not call Groq/Gemini or modify provider retry/circuit behavior.
- **Agent C — security/consent:** no P0/P1 was reported in its scoped read-only review. **Consent race P2 remains open**: stale conversation memory can survive a concurrent consent revocation; no safe closure was established here.
- **Final review:** Agent A completed a read-only review of the budget experiment; its objection led to re-checking the service path and removing the unsupported fix/test. Agent B and C findings are included above. No final application patch remains from those findings; the retained change is a test-only evaluator regression.

## Safety and verification boundaries

- Working tree was already dirty with **174 Git status entries** before this report. The existing changes were preserved; no reset, clean, stash, commit, push, merge, or deployment was performed.
- Branch and HEAD did not change. The retained test regression was added to an already-dirty test file; this report is the only new deliverable created by this sprint.
- `SALES_JOURNEY_ENGINE_ENABLED` remains `False` by the application setting default (`backend/app/core/config.py:145`). No feature flag was enabled.
- No provider calls, production/customer data access, external messages, orders, payments, bookings, or migration/reindex operations were performed. `backend/test.db` was not accessed.
- PostgreSQL runtime/concurrency is **not verified by this sprint**; the full test run explicitly disabled PostgreSQL tests and used the test suite's isolated SQLite fixtures.
- No browser/UI runtime acceptance was performed.

## Acceptance status

```text
ENGINEERING_SPRINT=PARTIAL
QUALITY_EVALUATION_READY=NO
CONSENT_RACE_P2=OPEN
PRODUCTION_READY=NO
```

The offline backend suite passes. This sprint did not establish that RAG answer quality improved. Final quality acceptance remains blocked on human review and valid answer-quality measurement; consent race, PostgreSQL runtime, and browser runtime remain unverified/open.
