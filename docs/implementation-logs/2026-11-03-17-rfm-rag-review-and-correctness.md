# RFM-to-RAG review and correctness fixes

Date: 2026-11-03

## Scope

Independent Sol review of the industry RFM prior integration into chatbot
product ranking, followed by fixes for consent, hard-filter, cache, and exposure
logging correctness. No ranking algorithm was added.

## Review findings and changes

- A withdrawn personalization consent now invalidates successful shop-trained
  RFM segmenter artifacts as well as LightFM/live reranker artifacts. The next
  eligible profile rebuild can use the industry prior or rules fallback.
- The catalog-matcher fallback now applies the same validated hard-filter
  predicate as the regular recommendation path before it scores candidates.
- Catalog ranking now records `rfm_score_computed` separately from
  `rfm_display_order_changed`. `rfm_ranker_applied` means the customer-visible
  top three actually changed; a one-candidate match no longer claims a rerank.
- Training finalizes and flushes the current model-run identity before creating
  profile cache signatures. This keeps signatures fresh with runtime
  `autoflush=False` sessions.
- Chatbot trace extraction now tolerates older recommendation response objects
  that do not expose a `context` field.

## Verification

- Sol independently reviewed the initial integration, then reviewed the fixes
  in two subsequent passes. The final pass found no further concrete issue.
- Targeted regression tests:
  `python -m pytest backend/tests/test_personalized_rag_pipeline.py backend/tests/test_chatbot_answer_routing.py -q`
  — 64 passed.
- Python syntax compilation and `git diff --check` are recorded after the final
  code edits.
- This verifies correctness paths, not a general relevance lift. No per-shop
  offline A/B or live conversion-quality evaluation was run.

## Runtime follow-up

- Docker Compose reports the backend and worker healthy after restart; database,
  Redis, and frontend are also healthy.
- The packaged industry cold-start prior loads successfully as
  `industry_rfm_cold_start_v1` for cross-industry, ecommerce, fashion,
  general retail, and grocery.
- Aggregate tenant schemas contain 53 recommendation request records, 0
  recommendation feedback records, and 134 customer-product interactions.
  These totals are not enough to claim a measured ranking improvement; in
  particular, there are no explicit recommendation feedback labels yet.
