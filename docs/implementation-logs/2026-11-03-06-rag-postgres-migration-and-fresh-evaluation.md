# 06 — PostgreSQL migrations, focused tests, and fresh RAG retrieval audit

**Date:** 2026-11-03  
**Branch:** `codex/rag-improvements-20261102`  
**Delivery:** local working tree only; no commit or push.

## Runtime and migrations

- Restarted the local Compose PostgreSQL and Redis services. PostgreSQL recovered its WAL after the earlier unclean stop and passed its health check; no volume was removed or recreated.
- `db-init` completed successfully. Application migration advanced `20261020_0061` to `20261103_0062`; platform DB was already at `20261020_0004_knowledge`.
- Applied tenant migration `20261101_0015` to `20261103_0016` for all 14 active shop schemas: `shop_1`–`shop_7`, `shop_9`–`shop_12`, and `shop_14`–`shop_16`.
- Read-only verification confirmed the application and platform heads and all 14 tenant revisions. Backend, worker, frontend, PostgreSQL, and Redis are healthy. `http://127.0.0.1:8000/health` and `http://127.0.0.1:5173/` returned HTTP 200.

## PostgreSQL-backed tests

- RAG components, tenant isolation, agentic controller, and answer routing: **144 passed**.
- Auto-reply channel suite: **72 passed**.
- Tests ran in Docker using isolated `*_test` databases and temporary schemas; runtime shop data was not used as a test fixture.

## Fresh retrieval evaluation

The audit found three evaluation defects and corrected them:

- Saved rows use `case_id`, not always `id`; prior rows now accept either identifier.
- Duplicate rows are deduplicated by `(business_id, case_id)`. Identical duplicates collapse; conflicting duplicates fail the run. The shop totals are recomputed after deduplication.
- The previous size-case generator discarded measured capacities because the query parser correctly classified `120 ml` and `1 lít` as `volume`. It now generates typed size and volume cases separately. Legacy `size`/`sizes` keys are treated as volume aliases only when the requested value includes an explicit capacity unit; a bare `L` does not make `volume=L` match clothing size `L`. Exact values are still required. Regression coverage checks both `250 ml` and the bare-`L` boundary.
- The hard-filter audit uses a separate benchmark oracle and now checks BM25 candidate output and each returned/reranked method, not just lexical candidates.

The authoritative fresh output is under `backend/.local-evaluation/rag-quality-pass-20261103-final/`. It ran against the local PostgreSQL catalog and chunks. The final rerun consumed **154 cached query embeddings** (0 misses, 0 API calls). One discarded preliminary run happened before the cache was available inside the container and made 2 embedding API calls; its evaluation output was superseded by the guarded cached rerun.

The current DB generated 289 rows before deduplication. After removing **5** identical duplicates, the set has **284 unique cases**: **243** positive retrieval cases and **41** abstention/coverage probes across **103** query families. The earlier 243-case report is not a paired historical comparison: only four saved dense-result rows match both current case IDs and gold chunk IDs. Treat the same-run results below as the valid method comparison.

| Retrieval method | Cases | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 243 | 0.995885 | 0.931893 | 0.948199 |
| Gemini vector only | 243 | 0.868313 | 0.831413 | 0.839959 |
| Gemini + BM25 + RRF, no PPR | 243 | 0.979424 | 0.927984 | 0.941129 |
| Gemini + BM25 + RRF + current PPR | 243 | 0.748971 | 0.665295 | 0.685482 |
| BM25 + current PPR | 243 | 0.942387 | 0.871536 | 0.882455 |

| Shop | Cases | BM25 NDCG@5 | Hybrid, no PPR NDCG@5 | Hybrid + PPR NDCG@5 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 26 | 0.866297 | 0.866297 | 0.943220 |
| 4 | 92 | 0.995988 | 0.995988 | 0.772429 |
| 7 | 125 | 0.930062 | 0.916318 | 0.567880 |

Hard-filter audit found **0 leaking chunks** across these outputs: BM25 candidates (118 filtered cases, 125 chunks), BM25 PPR top 5 (118, 125), exact-entity PPR top 5 (118, 125), Gemini hybrid + PPR (87, 121), hybrid without PPR (87, 121), and vector-only (87, 117). The smaller dense count excludes non-positive abstention probes, which are not sent through dense evaluation. Exact-match gold-hit counts were SKU 53/53, size 12/12, volume 12/12, and color 10/10. The typed alias fix restored all four previously missed volume cases in shop 7 without treating a bare `L` as capacity. Current PPR still reduces aggregate hybrid NDCG@5 from 0.941129 to 0.685482; the offline exact-entity PPR variant matches BM25 on this set and has not demonstrated an improvement. Keep PPR out of serving pending reviewed answer-level evidence. No serving configuration changed.

After the final alias and audit-oracle changes, the RAG component suite passed **73/73**. The broader PostgreSQL-backed suites listed above were run earlier in this work; they were not rerun after this small alias-only correction.

## Quality limits and next step

- Only shops 1, 4, and 7 have identifiable industry evidence; the other 11 active tenants remain unclassified.
- 128 labels have machine-verified source support. Another 53 product-detail labels and 50 policy phrase labels still need a human to confirm answer scope. This set does not measure final answer correctness, live stock/price claims, or positive service/rental retrieval.
- The quality gate remains **blocked**. Keep the serving default unchanged; retrieval scores alone do not establish better customer answers.
- Agent 2's first review identified three issues: broad volume aliases, leakage counted only for lexical output, and a duplicated nested artifact path. The first two are fixed and rerun; the duplicate is renamed `preliminary-superseded-before-final-hard-filter-audit` so the report at the directory root is authoritative. A second review of the corrected state is pending.

## Artifacts

- Script: `backend/scripts/audit_rag_retrieval.py`
- Filter and regression test: `backend/app/rag/catalog_filters.py`, `backend/tests/test_rag_components.py`
- Fresh report: `backend/.local-evaluation/rag-quality-pass-20261103-final/industry-rag-ppr-expansion-report.json`
- Per-case results: `backend/.local-evaluation/rag-quality-pass-20261103-final/industry-rag-expanded-results.jsonl`
- Unique case set: `backend/.local-evaluation/rag-quality-pass-20261103-final/industry-rag-expanded-evaluation-set.jsonl`
