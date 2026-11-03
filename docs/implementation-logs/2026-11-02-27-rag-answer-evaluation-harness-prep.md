# RAG answer evaluation preparation — 2026-11-02

## Scope and direction

Prepare a reviewed-pending 25-case set and a fair offline A/B/C answer-evaluation harness. A is the current retrieval/prompt without live catalog context; B adds the production live catalog resolver; C adds bounded corrective retrieval. Keep production behavior unchanged until human labels and the hard quality gate are approved.

## Completed

- Created `C:/Users/Administrator/Downloads/rag-controller-testset-v1-enriched-pending.csv`; preserved the original draft file.
- Added frozen catalog snapshot IDs, fetched timestamps, stable source references, and gold product references for shops 1, 4, and 7. Gold product IDs/SKUs are validation labels only and are not inserted into the answer prompt.
- Split answer-action and response-mode labels from the unverified controller hypothesis. Corrected the shipping-fee wording to say the source gives no amount; changed the authorized-dealer label to `unknown_unverified`; made the coolant query identify its product; added reviewer notes for damaged goods, medical-safety, and absent gold-price evidence.
- Kept all 25 answer labels and all original review statuses `pending`.
- Updated `backend/scripts/prepare_rag_snapshot_eval.py` to read the review CSV, validate tenant/snapshot/source/product references, capture catalog evidence with the production `_live_product_context_chunk` helper, and fail closed when the retrieval cache lacks a matching tenant-scoped catalog capture.
- Disabled answer reuse by default so A/B/C are generated independently. Legacy prompt-pair reuse remains opt-in.
- Extended automatic numeric checks to multiple SKU prices, list/combo prices, savings, subtotals, and totals. The report now separates contradictions, missing expected prices, and cases that are not numerically checkable. Added an explicit tenant-scope check.
- The independent reviewer available in this run was GPT-6 Astra. GPT-6 Luna Max was not available in the model/tool list; Astra was used only for offline review, never for customer messages.

## Validation and findings

- `python -m py_compile backend/scripts/prepare_rag_snapshot_eval.py`: passed.
- `validate-cases`: passed — 25 cases, 36 source references, 23 gold catalog product references, all labels pending.
- Snapshot IDs: shop 1 `0f83176e…faf0`, shop 4 `23aabe3b…a124`, shop 7 `a67753db…3d4b`. They are existing frozen local snapshots; current DB contents could not be reverified.
- The current controller's `corrective_query()` rewrites 9/25 queries in the offline rule probe. It misclassifies “giao mấy ngày” as a price intent because `gia` matches inside `giao`; `ship` is not a configured trigger. This is a controller rule finding, not a human-approved answer label.
- `prepare-retrieval` was attempted and stopped before retrieval/embedding: PostgreSQL host `db` failed DNS resolution (`getaddrinfo failed`). Docker Engine is unavailable in this environment. The configured platform/tenant database URLs also warn that they fall back to legacy `DATABASE_URL`.

## Not completed / interpretation limits

- No fresh retrieval cache and no A/B/C generated answers or scores were produced. Do not interpret the prior 34-case pre-review as the result of this 25-case run.
- No Groq/Gemini answer calls, migrations, test-suite runs, training, serving changes, deployment, commit, or push were performed.
- Labels remain pending and cannot be used as ground truth until a human reviews them. The snapshot still needs verification against a reachable DB before an evaluation run.
- The production live catalog resolver currently returns one exact product context at a time; multi-product cases also depend on retrieved knowledge evidence. The harness does not use gold IDs to fill this gap.
- Controller retry replay records offline corrective retrieval and is not a full reproduction of every production eligibility gate.

## Next step

Make the configured PostgreSQL endpoint reachable (start the intended local Compose database or provide the correct database URL), then recapture/verify the shop snapshots, prepare retrieval, and independently generate A/B/C. Review the answer labels before making any quality-gate or production decision.
