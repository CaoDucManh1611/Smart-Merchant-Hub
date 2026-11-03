# RAG controller decision reasons — 2026-11-03

## Change

- Extracted the existing corrective-retrieval gate into a pure decision helper that returns a reason for retry or skip.
- Run logs now receive explicit reason codes for agentic mode off, image/casual exclusions, sufficient retrieval score, exhausted tool/time budget, no applicable query expansion, and an eligible retry.
- Kept the existing gate order, threshold, timeout, tool budget, retrieval mode, and customer-facing behavior unchanged.
- Added unit coverage for the decision reasons and retained the delivery-time phrase-boundary regression.

## Validation

- `git diff --check`: passed.
- `RUN_POSTGRES_TESTS=0 python -m pytest tests/test_agentic_rag_controller.py -q`: 6 passed. The test file only needs isolated SQLite for its settings test; disabling the PostgreSQL bootstrap avoids waiting for unavailable local PostgreSQL during collection.
- The prior frozen 25-query retrieval audit found one query eligible for an actual corrective retry at threshold `0.3` (`shop7_rl_para_warranty_duration`). The CSV's 22 expected-controller values remain unreviewed hypotheses, not ground truth.

## Limits

- This improves observability and does not itself improve answer accuracy. No threshold or serving mode was changed.
- The answer A/B/C run remains incomplete because the previous Groq call hit its daily quota; no alternate provider was configured. Human answer labels remain pending.
- No migration, production database, or external model call was used. No commit or push.
