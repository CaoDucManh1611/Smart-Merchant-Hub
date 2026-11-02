# 18 — Fresh RAG pilot after SKU/volume fixes

**Status:** Code and local evaluation artifacts updated in the working tree. No commit or push.

## Fixes made

- `backend/app/rag/retriever.py`: product specifications such as `10W-40` were being inferred as exact SKUs. That added a hard SKU filter and hid the matching product when a customer asked by name. Exact SKU inference now accepts a code explicitly labelled `SKU`/`mã` or a multi-segment code; it leaves short two-part specs to lexical retrieval. Global identifier parsing remains unchanged for citations and answer validation.
- `scripts/evaluate_cached_rag_answers.py`: original case contracts may identify rows with `id` or `case_id`; both now work.
- The old pilot fixture called a one-liter volume a `size`. For this run, volume-valued hard filters were normalized to `volume`, and targeted question wording uses “dung tích”. This corrected the evaluation contract; it did not change the production query wording.

## Current tenant snapshot after reindex

| Shop | Ready documents | Ready chunks | Catalog entries | Typed volume attributes | Chunk mappings |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 1 | 25 | 1,525 | 6 | 25 |
| 7 | 1 | 18 | 25 | 2 | 29 |

## Fresh retrieval results

The 13 product questions cover shops 1, 4, and 7. Expected chunk IDs were resolved from current tenant-local catalog-to-chunk mappings, rather than stale IDs from before reindex.

| Method | N | Hit@5 | Recall@5 | MRR | NDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 serving | 13 | 1.0000 | 1.0000 | 0.9487 | 0.9615 |
| Gemini + BM25 + RRF, no PPR | 13 | 1.0000 | 1.0000 | 0.9487 | 0.9615 |

Per-shop NDCG@5 was 0.8333 for shop 1 (3 cases), 1.0000 for shop 4 (5 cases), and 1.0000 for shop 7 (5 cases). In the seven no-answer cases (unknown SKU, empty service catalog, empty rental catalog), both methods returned zero chunks in all seven.

These are small, pilot-sized, mapping-derived labels—not human-reviewed relevance judgments. Do not compare them directly with the older 243-case report. PPR was disabled in both arms and was not re-evaluated here.

## Targeted answer pilot

Four cases per arm tested product details and one-liter volume questions across shops 4 and 7. Both answer arms used the same retrieved data for each question.

| Method | Citation gate | Required fact terms | Fully literal-checked cases | Safe handoffs |
| --- | ---: | ---: | ---: | ---: |
| BM25 serving | 3/4 (75%) | 6/10 (60%) | 2/4 | 1/4 |
| Hybrid no PPR | 2/4 (50%) | 5/10 (50%) | 2/4 | 2/4 |

This does not show that BM25 is better: the sample is four answers per arm, generated calls were not deterministic, and the configured Groq model returned rate limits during the run. Fallback routing was attempted, but the evaluator does not save the actual provider/model per answer. Several handoffs mentioned unavailable price/stock fields that were absent from the retrieved TXT evidence; because this evaluator does not fetch live CRM price/stock, those answers cannot pass the evidence gate. Keep this as a safety handoff, not a measured answer-quality win.

## Checks

- `python -m pytest backend/tests/test_rag_components.py -k "product_specification_is_not_mistaken_for_sku or hard_filter_size_code_is_not_also_treated_as_an_exact_sku" -q`: **2 passed**.
- Earlier focused idempotent catalog upsert test: **1 passed**.
- `py_compile` for the retriever, its focused test, and the answer-evaluation script: passed.
- `git diff --check`: passed; Git reported only existing LF/CRLF conversion warnings.
- Docker DB, Redis, backend, and worker returned healthy after Docker Desktop restarted. `db-init` exited successfully. The existing frontend container remains stopped.
- Pilot inputs and answer outputs are saved under `backend/.local-evaluation/rag-audit-20261102-self-check/postfix-20261102/` (ignored local evaluation artifacts).

## Agentic RAG recommendation

This pipeline can add a **bounded corrective controller** without replacing the existing retrieval stack:

1. Keep tenant scope and supported hard filters (SKU, typed attributes, object type) inside retrieval SQL before `LIMIT`; verify live price, stock, and selling status from the catalog before answering.
2. Retrieve with BM25 or hybrid-without-PPR. Use cheap evidence signals first: exact SKU/attribute match, candidate count, and source coverage.
3. If evidence is weak, permit one targeted query rewrite/retrieval retry while preserving every hard filter. Do not broaden to other tenants or public web sources.
4. Generate with citations, validate citations and claims, then read current price/stock from CRM. If evidence is still weak, ask a clarifying question or hand off.
5. Keep RFM/LightFM in product recommendation ranking, after relevant products are retrieved; do not use them to answer knowledge questions.

This resembles CRAG's retrieval-quality evaluator and conditional correction, and Self-RAG's on-demand retrieval/critique ([CRAG](https://arxiv.org/abs/2401.15884), [Self-RAG](https://arxiv.org/abs/2310.11511)). It is a design recommendation only; no agentic loop was implemented in this change. Limit the loop to one retry and invoke an LLM grader only for ambiguous low-confidence cases so simple SKU/FAQ turns do not incur extra model calls.
