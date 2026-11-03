# RFM cold-start prior in chatbot RAG product ranking

Date: 2026-11-03

## Scope

Connect the industry RFM prior to both chatbot product-recommendation paths,
while keeping knowledge-chunk retrieval based on the query and preserving exact
product-match constraints.

## Changes

- The standard chatbot RAG path continues to retrieve shop-local chunks, map
  chunks to shop-owned products, and pass those candidates to
  `serve_recommendations`. The existing RFM segment weights now record an
  explicit blend version for industry-prior, shop-trained, and rule fallback
  ranking.
- The specific-product catalog matcher now computes a consent-gated RFM
  secondary score from shop-local purchase facets, product interactions,
  popularity/co-purchase signals, RAG relevance, and the selected RFM segment.
  Exact catalog match score stays the primary sort key; RFM can only reorder
  products with the same match score.
- Recommendation request and item snapshots record whether the RFM ranker
  actually changed a tied candidate order, plus model version/source/industry,
  confidence, and consented-peer count. Chatbot and conversation-graph metadata
  carry a compact RFM ranking trace.
- Updated `backend/app/rag/README.md` to document where RFM runs and where it
  does not: after product retrieval/mapping, not in knowledge-chunk retrieval.

## Safety boundaries

- Tenant scoping, active/available-catalog filtering, query match score, and
  personalization consent remain prerequisites. No product enters the result
  because of RFM alone.
- Customers with no purchase history do not use the industry buyer prior.
- RFM remains deterministic SQL/Python scoring and does not add an LLM call.

## Verification and limits

- Python syntax compilation passed for the edited backend modules and
  `git diff --check` found no whitespace errors.
- Recreated only the Compose `backend` and `worker` services so the updated
  code and read-only `industry_rfm` artifact mount are active. Both services
  report healthy; the artifact directory is visible in both containers.
- The backend artifact loader reports `industry_rfm_cold_start_v1` available
  with five supported model keys.
- No test suite or live customer recommendation was run, so ranking against
  customer/catalog rows remains unverified.
