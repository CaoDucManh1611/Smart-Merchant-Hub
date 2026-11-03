# RAG controller trigger boundary fix — 2026-11-02

## Change

- Changed corrective-query trigger matching to require whole normalized phrases, preventing `gia` (price) from matching inside `giao` (delivery).
- Added explicit Vietnamese delivery-time phrases and a regression test for “Giao mấy ngày thì nhận được?”.
- The existing price, stock, policy, and booking expansions now also match phrase boundaries.

## Validation

- `python -m pytest tests/test_agentic_rag_controller.py -q`: passed, 4 tests in 5.18s.
- PostgreSQL was unavailable during the initial probe. It was later started with the correct split-database URLs; see [the evaluation run log](2026-11-02-29-rag-evaluation-groq-quota.md).

## Scope

- Retrieval, auto-reply policy, production flags, database schema, and customer-facing behavior were not otherwise changed.
- No commit or push.
