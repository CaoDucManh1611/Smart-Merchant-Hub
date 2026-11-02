# Answer-evaluation readiness and retrieval rerun — 2026-11-02

## Scope and safety

The requested answer-level A/B/C evaluation was not run because the 100-case review file is still an unassigned template. No review labels were fabricated, and no customer messages were sent. The rerun below uses read-only retrieval against the local tenant database; it does not run migrations or write tenant data.

## Review-file audit

Audited `docs/agentic-rag-answer-review-v1.jsonl`:

- Rows: 100.
- Rows with a shop/business assignment: 0.
- Rows with a stable source reference: 0.
- Rows with a catalog snapshot: 0.
- Rows reviewed by a human: 0.
- Rows with an expected clarification response: 0.

The queries and answer contracts are present, but they cannot establish source support or factual correctness until each case is tied to a shop and its approved knowledge/catalog snapshot. Product questions also require the exact live catalog snapshot so price and stock are not judged against stale values.

## Fresh retrieval-only rerun

Reran the saved 25-case serving input against local PostgreSQL with current code. The controller arm models one corrective retrieval at most; it does not invoke the answer LLM or live catalog tool. Hybrid used Gemini query embeddings (18 unique query/rewrite strings in one batch). PPR remained disabled.

| Retrieval arm | Cases / positive labels | Recall@5 | MRR | NDCG@5 | p50 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 baseline | 25 / 15 | 1.000 | 0.922222 | 0.942062 | 4.66 ms | 28.41 ms |
| BM25 + corrective controller | 25 / 15 | 1.000 | 0.922222 | 0.942062 | 4.71 ms | 28.45 ms |
| Hybrid (Gemini + BM25 + RRF, no PPR) | 25 / 15 | 1.000 | 0.955556 | 0.966667 | 9.41 ms | 31.53 ms |
| Hybrid + corrective controller | 25 / 15 | 1.000 | 0.955556 | 0.966667 | 9.45 ms | 31.57 ms |

There were 7 reviewed negative probes and 3 unscored cases. Negative-probe false retrievals: 0/7 in every arm. The controller retried 0/15 positive cases; paired results were 15 ties, 0 wins, 0 losses for BM25 and hybrid. Shop-level scored positive counts were 4 for shop 1, 5 for shop 4, and 6 for shop 7; those small per-shop samples are descriptive only.

This is a fresh retrieval ranking result, not an answer-quality result. It does not establish correctness, citation support, wrong-price/stock rate, clarification quality, or end-to-end latency. No Groq/LLM completion tokens were used; one Gemini embedding batch was used. A dollar cost was not inferred from provider billing.

## A/B/C status

| Requested arm | Status | Reason |
| --- | --- | --- |
| A — legacy RAG without catalog | Not run | The current pilot runner has no isolated legacy answer path; its retrieval-only baseline is not equivalent to a legacy answer run. |
| B — RAG with live catalog | Not run | The 100 cases have no shop mapping or versioned catalog snapshots, so live price/stock results cannot be compared reproducibly. |
| C — catalog + controller | Not run | Same missing case/source/snapshot assignments; the current controller pilot only compares retrieval evidence and does not generate answers. |

The current available runner supports BM25 and hybrid-no-PPR retrieval plus a corrective-retrieval simulation. It does not execute the three requested end-to-end answer arms. Therefore the hard-error gate (wrong shop, price/stock, unsupported attributes), answer/citation grading, end-to-end p50/p95, and per-case token cost remain unmeasured. The controller remains out of active answer mode.

## Artifact

Fresh run report: `backend/.local-evaluation/rag-audit-20261102-self-check/postfix-20261102/agentic-control-user-rerun-20261102.json`.
Runner: `backend/scripts/evaluate_agentic_rag_pilot.py`.
Review template audited: `docs/agentic-rag-answer-review-v1.jsonl`.
