# Shadow modes and answer review preparation — 2026-11-02

## Changes

- Replaced the evidence comparator that favored larger chunk lists. It now compares the best retrieval signal and mean of the top three signals within the same retrieval mode. BM25/vector/RRF values are logged as ranking signals, not probabilities.
- Added per-shop `rag_agentic_mode`: `off`, `decision_shadow`, `execute_shadow`, or `active`. Decision shadow records whether a retry would run. Execute shadow runs it but retains the original evidence for the answer. Active mode may select the retry candidate. The legacy `rag_agentic_enabled` setting remains supported.
- RAG run records now include mode, trigger reason, initial/candidate chunk IDs, comparison signals, and whether the candidate would be selected. Chunk text is not added to the run log.
- Generated a 100-row answer-review file from the existing question and answer-contract sets. Each row has explicit fields for shop assignment, stable source references, catalog snapshot, human review, A/B/C outputs, hard failures, clarification, and helpful resolution. All 100 cases are marked pending review; no labels were invented.

## Refined retrieval pilot

The same 25 saved cases were rerun against local PostgreSQL with the updated comparator. Hybrid used one Gemini embedding batch from the running backend container. The host process did not have Gemini credentials available; no credential was printed or changed.

| Mode | Positive labels | Recall@5 | MRR | NDCG@5 | p50 retrieval | p95 retrieval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 baseline | 15 | 1.000 | 0.922 | 0.942 | 5.60 ms | 28.41 ms |
| BM25 controller simulation | 15 | 1.000 | 0.922 | 0.942 | 5.64 ms | 28.45 ms |
| Hybrid no PPR | 15 | 1.000 | 0.956 | 0.967 | 7.95 ms | 32.60 ms |
| Hybrid no PPR controller simulation | 15 | 1.000 | 0.956 | 0.967 | 8.00 ms | 32.65 ms |

The controller retried **0/15** positive cases. Paired outcomes were 15 ties, zero wins, and zero losses. False matches were **0/7** explicit no-match probes for each arm. These are retrieval-only observations; the saved labels are not all human-reviewed and do not score generated answers.

This runner simulates retrieval selection and does not execute an LLM answer. The table therefore does not establish end-to-end A/B/C effects. It also cannot compare pre-catalog behavior because the saved cases lack a catalog snapshot and assigned shop for every row.

## Checks

- Focused controller, shadow-mode, key-pool, pilot-label, PostgreSQL timeout, Gemini timeout, and live-catalog tests: **18 passed**.
- Python compilation and `git diff --check` passed.
- No migration, customer message, or database write was performed.

## Next gates

1. Review the 100 cases, assign the shop, approve expected action/source/facts, and attach stable source hashes plus catalog snapshot IDs.
2. Build the three answer runs from the same prompt/model/input snapshot: legacy without catalog (offline only), current catalog route, and catalog plus controller.
3. Record answer correctness, supported citations, wrong shop/price/stock/attribute, clarification, helpful resolution, end-to-end p50/p95, and token cost. Require zero absolute hard errors on the approved critical cases before enabling active mode.
4. Start with `decision_shadow`; use sampled `execute_shadow` only where retrieval triggers, and keep the stock scope explicitly shop-wide until channel inventory is sourced.

## Artifacts

- Human-review template: `docs/agentic-rag-answer-review-v1.jsonl`
- Refined retrieval report: `backend/.local-evaluation/rag-audit-20261102-self-check/postfix-20261102/agentic-control-pilot-refined-hybrid-20261102.json`
- Runtime guide: `backend/app/rag/README.md`
