# 08 — Strict catalog hard filters, audit correction, and reindex gate

**Date:** 2026-11-03  
**Branch:** `codex/rag-improvements-20261102`  
**Delivery:** local working tree only; no commit or push.

## What changed

- Catalog hard-filter SQL now requires at least one matching catalog mapping and
  rejects a mapped chunk if **any** other mapping violates the same shop, object
  type, SKU, or required-attribute constraints. The shared predicate is reused by
  the SKU-only optimized path, so the vector and lexical limits see the same guard.
- Removed the unmapped text-only exact-SKU fallback. A SKU/attribute hard filter now
  requires catalog mappings that prove the same-shop entry matches; unindexed legacy
  text fails closed. Unmapped policy chunks remain a separate, topic-limited branch
  for mixed product/policy questions.
- Added executable SQLite regressions for mixed SERUM SKU mappings, a mixed L/M size
  mapping, multiple explicitly allowed SKUs, rejection of unmapped legacy SKU text,
  and the mapped/unmapped policy exception on a mixed SKU-policy query.
- Updated one stale ingestion test fixture: the catalog sync stub now returns a list,
  and the expected chunker metadata version is `structure-semantic-context-v3`.

## Why the earlier zero-leak result was wrong

The first independent oracle counted a chunk as safe when **any one** mapping matched.
On the current database, that made a chunk listing SERUM-01, SERUM-02, cleanser and
sunscreen appear safe for a query pinned to one SKU. Kepler's independent review
found this flaw. The audit was corrected to require every catalog mapping on the
returned chunk to satisfy the filter. A second review also showed that checking only
legacy `unit_type=product` metadata cannot prove atomic content, so that fallback was
removed rather than trusted.

## Strict audit rerun

Ran the same 243 eligible retrieval cases and same tenant/catalog snapshot with the
strict filter. Gemini query embeddings came from the existing cache (154 hits, 0
misses, 0 API calls). Results:

| Method | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.814815 | 0.756996 | 0.769579 |
| BM25 + MMR (offline) | 0.818930 | 0.756859 | 0.770391 |
| Auto router, no PPR | 0.806584 | 0.757202 | 0.767734 |
| Gemini + BM25 + RRF, no PPR | 0.794239 | 0.748971 | 0.758394 |
| Gemini + BM25 + RRF + current PPR | 0.563786 | 0.486283 | 0.502747 |

Strict hard-filter audit: **0 leaking returned chunks** across 118 filtered BM25
cases and 68 returned chunks. MMR's paired query-family bootstrap remains
inconclusive: mean NDCG@5 delta +0.000812, 95% CI [-0.002065, +0.005417]; MMR stays
off in serving. Current PPR remains off because it substantially lowers NDCG.

The strict scores are materially lower than the first-pass scores because this DB
contains old chunks that combine multiple products. For example, the SERUM-01 source
chunk maps four products; strict SKU filtering correctly excludes it. The source
document itself can be split by the existing `structure-semantic-context-v3`
chunker, but persisted legacy documents need reindexing for the new item boundaries
and mappings to take effect. Therefore, the strict safety gate currently trades
recall for lower cross-product contamination. Do not interpret the old scores or the
initial zero-leak count as current production quality.

The rerun is saved under
`backend/.local-evaluation/rag-quality-pass-20261103-final-audited-v2/`, including
case rows, the report JSON, and the copied query-embedding cache. `configuration_changed`
is false; this audit does not enable MMR, PPR, or auto retrieval globally.

## Service/rental data check

An agent ran the read-only source-grounded builder across 14 tenant registry shops.
It found zero eligible service/rental entries in the structured recommendation
catalog (28 shop × object-type rows) and produced zero exploratory cases. This only
describes that catalog source; it does not establish that no older service/rental
data exists elsewhere. No answer labels were invented or marked human-reviewed.

- `backend/.local-evaluation/service-rental-identity-retrieval-exploratory-20261103-01.jsonl`
- `backend/.local-evaluation/service-rental-identity-retrieval-exploratory-20261103-01-summary.csv`

## Verification and limits

- Focused RAG test set: **128 passed** across catalog/retriever components, query
  expansion, retrieval audit, service/rental case builder, tenant isolation, and
  semantic chunking.
- Retrieval audit used 154 cached query embeddings; **no Gemini embedding API calls**.
- No application migration, document reindex, or tenant data mutation was run. The
  compose one-off test job did invoke the project's `db-init` dependency; it exited
  successfully. No production channel was contacted.
- Reindexing can invoke the configured remote embedding provider and consume quota;
  it remains a separate operator action. Re-run the strict audit after reindex before
  widening the serving configuration.
- HyDE/Multi-Query is still a bounded helper only, not wired into customer serving.
  Time-weighted retrieval, contextual compression, and Map-Reduce/Refine/Map-rerank
  remain unmeasured and are not enabled. No answer-level human review or production
  quality gate was claimed.
