# 07 — RAG technique ablation and bounded query-expansion helper

**Date:** 2026-11-03  
**Branch:** `codex/rag-improvements-20261102`  
**Delivery:** local working tree only; no commit or push.

**Audit correction:** the first leakage oracle in this log treated a mixed chunk as
safe when *any* catalog mapping matched. An independent review found that this was
too permissive. The zero-leak statements below describe that flawed oracle and are
superseded by the all-mappings check and rerun in log 08. The first-pass retrieval
scores are retained only as historical measurements on the pre-isolation candidate
set; they are not the current strict-filter scores.

## MMR ablation

Added an offline BM25 + lexical MMR arm to `backend/scripts/audit_rag_retrieval.py` and reran it over the same 243 eligible positive cases and the same PostgreSQL/catalog snapshot as the final report in log 06.

| Method | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.995885 | 0.931893 | 0.948199 |
| BM25 + lexical MMR | 1.000000 | 0.931756 | 0.949011 |

Paired query-family cluster bootstrap (5,000 resamples, seed `20261103`) gives a mean NDCG@5 difference of **+0.000812** for MMR, with a 95% interval **[-0.002109, +0.005378]**; 60.44% of bootstrap samples are positive. This does not establish a reliable gain. Keep `enable_mmr` off in serving; retain the ablation for future evaluation on answer-level quality and source diversity.

The initial MMR hard-filter audit covered 118 filtered cases and 125 returned chunks, but its any-mapping oracle was later found to be incorrect. See log 08 for strict results and the effect of legacy mixed chunks. PPR conclusions remain unchanged: the current PPR path lowers hybrid NDCG@5 and remains disabled in serving.

## Existing `auto` router ablation

Extended the same audit to replay the exact production `_select_retrieval_mode("auto")` decision against the same-run BM25 candidates and hybrid RRF results without PPR. It kept exact-identifier/hard-filter cases on BM25, routed only weak lexical cases to hybrid, and did not call the embedding provider because all 154 query vectors came from the copied local cache.

| Method | Cases | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 243 | 0.995885 | 0.931893 | 0.948199 |
| `auto` (hybrid no-PPR on weak lexical) | 243 | 0.987654 | 0.932099 | 0.946354 |

The router chose BM25 for 109 lexical-sufficient cases, hybrid for 46 weak-lexical cases, and BM25 for 88 exact-filter/SKU cases. The initial auto leakage count used the flawed any-mapping oracle noted above. The strict rerun in log 08 is the valid result. Auto was below BM25 on Recall@5 and NDCG@5 in the first candidate set; no evidence supports making it the default. Latency and embedding cost were not benchmarked here.

## Query expansion from techniques 1–8

Added `backend/app/rag/query_expansion.py` as a bounded, caller-controlled planning helper. It preserves the original query and the same hard-filter mapping, caps expansion at two query variants and one generator callback, runs model mode only after a caller reports weak retrieval, rejects oversized/malformed output, and keeps synthetic HyDE text separate from citable evidence. It is intentionally **not wired into auto-reply or serving**. No model calls, customer-visible behavior, or new cost are introduced by this helper alone.

The helper covers a safe implementation seam for multi-query/HyDE. Query normalization, exact self-query hard filters, tenant scoping, parent/neighbor context, and consented recommendation personalization are already covered in the existing RAG flow. MMR has no established quality gain. Time-weighting, contextual compression, and Map-Reduce/Refine/Map-rerank remain unimplemented/unmeasured; they should be considered only against suitable time-sensitive or long-context answer cases, not enabled globally by default.

## Verification and service state

- `tests/test_rag_query_expansion.py` + `tests/test_rag_components.py`: **82 passed** in a one-off Docker run with mounted test sources.
- `git diff --check`: passed before the final README/log additions; rerun at closeout.
- Python `compileall` for the expansion helper and retrieval audit script: passed.
- Local API health and frontend root returned HTTP 200. This verifies local service availability only, not production or provider behavior.
- A first test command lacked the test mount and a second lacked `PYTHONPATH`; both collection-only attempts were corrected. The final mounted run above is authoritative.
- Fresh auto/MMR ablation report and per-case rows are under `backend/.local-evaluation/rag-quality-pass-20261103-auto-ablation/`; embedding cache hits 154, misses 0, API calls 0.

## Agent work and label provenance

- Franklin completed the standalone helper and focused tests above.
- Kepler's independent review found the any-mapping oracle flaw; the strict follow-up and code review are recorded in log 08.
- Parfit's service/rental source scan found no eligible structured catalog entries in the 14-shop registry. It created no answer labels; see the exploratory summary artifact and log 08. This does not prove the shops lack legacy service/rental data.

No answer-level quality gate was changed. The benchmark still lacks independently verified final-answer judgments for broad production claims, so no experimental retrieval setting was enabled for all shops.
