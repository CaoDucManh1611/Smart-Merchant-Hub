# Bounded Agentic RAG pilot — 2026-11-02

> Initial pilot record. The retrieval table below is superseded by the refined rerun in
> `2026-11-02-20-shadow-modes-and-answer-review.md` after replacing the chunk-count score.

## Scope

Implemented a tenant-scoped, read-only controller around the existing RAG flow. The controller keeps BM25 as the default, supports per-shop hybrid retrieval without PPR, and allows one corrective retrieval when the first retrieval is empty or below its confidence threshold. It preserves the original hard filters and only replaces the original evidence when the corrective pass has a better deterministic evidence score.

This is a bounded corrective-retrieval controller, not an LLM planner. Product price, stock, and sale status continue to come from the structured shop catalog before an answer is generated; these facts do not rely on stale knowledge chunks. Catalog evidence includes `source`, `fetched_at`, product ID/SKU, and `availability_scope=shop_catalog`. Inventory is currently shop-wide, not channel-specific.

## Runtime controls

- `RAG_RETRIEVAL_MODE=bm25` is the application default. Per-shop `business_settings.rag_retrieval_mode` may select `bm25` or `hybrid` independently.
- `RAG_AGENTIC_ENABLED=false` is the application default. Per-shop `business_settings.rag_agentic_enabled` enables the corrective pass.
- `RAG_AGENTIC_MAX_TOOL_CALLS` is capped at 4; `RAG_AGENTIC_RETRY_THRESHOLD` selects the weak-evidence boundary; `RAG_AGENTIC_TIMEOUT_SECONDS` is capped at 30 seconds.
- Provider calls used for query embeddings and PostgreSQL statements receive bounded timeouts. A retry error keeps the initial evidence; an initial retrieval error takes the existing safe handoff path.
- Serving uses `enable_ppr=False`. PPR remains available for offline experiments. RFM/LightFM remain product-recommendation rankers and do not affect knowledge evidence.

No migration was needed. Settings reuse the existing per-shop settings table. No admin UI was added; the switch can be set through the existing shop settings storage.

## Verification

- Focused tests: **32 passed**. Coverage includes tenant settings isolation, preserved hard filters on retry, catalog source/status metadata, vector-query timeout behavior, PostgreSQL statement-timeout restoration, single provider-attempt limits, and pilot metric/label handling.
- `py_compile` passed for the changed RAG controller, embedder, retriever, provider key pool, auto-reply service, and evaluation runner.
- `git diff --check` passed. Git reports only existing LF/CRLF normalization warnings.
- No migration or database write was performed for the pilot. Evaluation read the existing local PostgreSQL catalog/knowledge data.

## Retrieval-only pilot

Input: 25 saved cases across shops 1, 4, and 7. The evaluator re-mapped 15 positive expected passages from their source text because the saved chunk IDs had become stale; seven explicit no-match probes were scored separately; three behavior-only cases had no retrieval gold and were not included in relevance metrics. Labels are not all human-approved.

| Retrieval arm | Positive cases | Recall@5 | MRR | NDCG@5 | p50 retrieval | p95 retrieval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 baseline | 15 | 1.000 | 0.922 | 0.942 | 5.66 ms | 33.47 ms |
| BM25 + corrective controller | 15 | 1.000 | 0.922 | 0.942 | 5.70 ms | 33.53 ms |
| Hybrid Gemini + BM25 + RRF, no PPR | 15 | 1.000 | 0.956 | 0.967 | 11.86 ms | 43.36 ms |
| Hybrid + corrective controller | 15 | 1.000 | 0.956 | 0.967 | 11.90 ms | 43.41 ms |

The corrective pass ran **0/15** positive cases because the first retrieval was already sufficient; paired NDCG was 15 ties, 0 wins, and 0 losses for both modes. Both retrieval modes returned no match for **7/7** explicit negative probes. This is retrieval behavior only, not proof that generated answers never hallucinate.

By shop, positive sample counts were 4 (shop 1), 5 (shop 4), and 6 (shop 7). BM25 NDCG@5 was 0.875, 1.000, and 0.938 respectively; hybrid was 0.875, 1.000, and 1.000. By positive query type, both modes scored NDCG@5 1.000 for product info (n=3), SKU lookup (n=3), size constraints (n=2), and color constraints (n=2). Product detail (n=3) scored 0.833 for both; policy FAQ (n=2) scored 0.815 with BM25 and 1.000 with hybrid.

These small, partly unreviewed samples do not justify enabling hybrid globally or claiming an Agentic RAG quality improvement. Hybrid is a per-shop pilot option; BM25 remains the default. The pilot measured retrieval latency only and excludes batch embedding latency. One Gemini embedding batch request covered the 18 pilot queries.

## Limits and next validation

- The pilot does not call an answer LLM. It does not measure answer correctness, whether citations support each answer claim, live-price/stock answer violations, clarification quality, answer token cost, or end-to-end customer latency.
- The pilot cases are not a time-split dataset; they are static retrieval checks. The three behavior-only cases need answer-level review before they can be scored.
- Add human-reviewed answer cases for missing price/stock, cross-source answers, ambiguity/clarification, and unsupported claims. Then compare baseline and controller on the exact same cases, report per-shop and per-type paired outcomes, and keep a hard gate that factual/citation violations do not rise.
- Keep current catalog scope explicit. If a channel has its own inventory, add the channel inventory source before claiming channel-accurate stock.

## Artifacts

- Runner: `backend/scripts/evaluate_agentic_rag_pilot.py`
- Case input: `backend/.local-evaluation/rag-audit-20261102-self-check/postfix-20261102/bm25_serving-input.json`
- Detailed machine report: `backend/.local-evaluation/rag-audit-20261102-self-check/postfix-20261102/agentic-control-pilot-20261102.json`
- Runtime overview: `backend/app/rag/README.md`

The detailed local report remains under `.local-evaluation`; it contains case-level retrieval details. No commit or push was made.
