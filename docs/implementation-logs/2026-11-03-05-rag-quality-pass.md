# RAG quality pass — 2026-11-03

## What changed

- New knowledge chunks retain a source-content hash, reindex revision, chunker version, and PDF page range. Parent/neighbor expansion continues to use bounded context and preserves the combined page span.
- Retrieval accepts `auto`: it starts with BM25 and only uses hybrid RRF when lexical candidates are weak and no exact SKU or hard filter is present. The default remains BM25. Diagnostics record requested/selected mode and routing reason.
- Hard filters are validated and applied in SQL before the vector, lexical, and parent-expansion limits. Caller-supplied exact SKU/attributes take priority over query inference. Conflicts are logged by field only. Mixed product/policy questions keep unmapped policy evidence eligible under attribute-only filters.
- A corrective retry is bounded to one query rewrite, retains the full original query and hard filters, and uses the same selected BM25/hybrid route as the first retrieval. Unknown retrieval mode falls back to BM25.
- Optional lexical MMR is an offline/ablation switch only (`enable_mmr=false` by default). It uses token Jaccard as a cheap redundancy signal; it is not a semantic reranker and has not passed an online quality gate.
- If the answer would claim warranty coverage without a matching policy source, the service now records an idempotent staff handoff before returning the safe fallback.
- Exact SKU matches from catalog-to-chunk mappings now survive lexical ranking even when the SKU is absent from chunk text. English delivery/return/payment/shop terms take the same policy-evidence path as Vietnamese queries.
- Mixed product/policy retrieval reserves a policy source in the final top-K when top-K is at least two; parent-neighbor expansion preserves that source too.
- A `needs_human` conversation pauses auto-replies without changing the shop's `bot_mode`. Handoff notifications deduplicate per inbound turn and accumulate reason codes on the same row.
- If a channel provider accepts a reply but CRM persistence fails, the outbox is marked `delivery_unknown` when possible, staff are notified, and no retry sends a duplicate. User-facing verification guidance is channel-neutral.

## Deliberate boundaries

- HyDE, multi-query generation, time-weighted retrieval, and LLM-based contextual compression were not enabled. There is no paired evaluation showing that their added calls, latency, or cost improve this system.
- RFM/LightFM remains a product-recommendation ranking signal; it does not rank factual RAG evidence. No consented customer-history signal was added to knowledge retrieval.
- `auto`, MMR, and active agentic retry remain opt-in/configurable; this change does not switch shops to a new production default.
- These changes improve guardrails and offer controlled experiments, but do not by themselves prove higher answer quality. A reviewed, paired answer-level evaluation is still required before enabling a new route per shop.

## Review and verification

- Independent reviews surfaced risks around ambiguous color extraction, PDF page spans, long-query truncation, missing warranty handoff, reranker diagnostics, caller/query SKU conflicts, retry score-scale mismatch, mixed product/policy queries, and idempotent staff handoff. Applicable findings were fixed and covered by focused tests.
- Follow-up review findings were addressed for catalog-mapped SKU post-filtering, English policy terms, policy survival through top-K and parent expansion, pausing bot replies during unresolved handoff, per-turn notification idempotency, and provider-accepted/CRM-save-failed delivery state.
- Offline tests with `RUN_POSTGRES_TESTS=0`: 144 passed across retrieval components/tenant isolation, controller, and answer routing; 66 passed in `test_auto_reply_channels.py` with six optional graph/image cases deselected because the host lacks `langgraph`.
- `compileall` passed for RAG and auto-reply code. `git diff --check` passed with only Git line-ending normalization warnings.
- The application and tenant migrations add nullable notification idempotency keys with unique constraints. A static revision-graph parse reports heads `20261103_0062` (application), `20261020_0004_knowledge` (platform), and `20261103_0016` (tenant). Migration execution is pending: Docker reports the local PostgreSQL container stopped; Alembic CLI is unavailable on the host.
- PostgreSQL-backed tests, training, and live shop evaluation were not completed; no production traffic was used. No quality uplift is claimed. Keep `auto`, MMR, and agentic retry opt-in until paired held-out evaluation is available.
- The independent review found four additional retrieval issues: mapped catalog SKU candidates needed priority before the lexical candidate limit; bare `vat` confused Vietnamese “vật liệu”; and substring matching confused `cashmere` and `supportive` with policy terms. They are fixed and covered by regression tests; single-word topic aliases now use token boundaries and multiword aliases remain phrase matched. Final review found no remaining actionable issue (static review only).

## Delivery state

Changes are local and uncommitted. No branch was pushed.
