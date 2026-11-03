# 09 — Fast RAG serving defaults and RFM training readiness

**Date:** 2026-11-03  
**Branch:** `codex/rag-improvements-20261102`  
**Delivery:** local working tree only; no commit or push.

## RAG serving

- Serving now resolves to BM25 with the corrective controller off unless the
  deployment explicitly sets `RAG_EXPERIMENTAL_SERVING_ENABLED=true`.
- With the gate off, the runtime options loader returns immediately and skips a
  `business_settings` query on every message. Legacy per-shop `hybrid`, `auto`,
  or controller settings no longer turn on slower experimental paths by accident.
- PPR was already disabled in the customer-serving call; MMR and query expansion
  remain offline-only. Exact shop/SKU/typed-attribute SQL filters, current catalog
  price/availability checks, source citations, and safe handoff behavior remain.
- The strict 243-case audit supports BM25 as the current default: BM25 NDCG@5
  `0.769579`, auto `0.767734`, hybrid without PPR `0.758394`, and hybrid with PPR
  `0.502747`. PPR has the clearest accuracy regression. MMR's +`0.000812` NDCG
  delta had a paired 95% interval crossing zero, so it is not enabled.
- No production latency number is claimed. Disabling vector/RRF/retry and skipping
  the per-message settings query should reduce work on the normal path; measure
  latency in the running service before claiming a quantified speedup.

## RFM/LightFM readiness

- A read-only audit of 14 local shops (180-day window) found 0 eligible exposure
  requests in 13 shops. Shop 4 has 11 exposure groups, 1 explicitly consented
  customer, and 0 positive holdout requests. It fails the existing per-shop
  consent/event/holdout gates; no live-shop LightFM fit or activation is justified.
- Existing offline, industry-specific training artifacts are present under
  `D:\CRM_Industry_Datasets\trained_models` for Dunnhumby, H&M, Olist, and
  Retailrocket. They are benchmark-only artifacts, not shop IDs or production
  personalization models. Re-running the same unchanged sources would create
  duplicate artifacts without adding evidence.
- Fixed the live trainer's temporal split to sort each recommendation slate by
  the latest impression/feedback `occurred_at`, rather than request creation time.
  This prevents delayed click/purchase labels from leaking into an earlier train
  window. Model activation remains subject to the current consent and quality gate.

## Verification

- Docker focused tests: **15 passed** (`test_agentic_rag_controller.py`,
  `test_live_reranker_blend.py`). Includes regression coverage for default
  experimental-path lockout and outcome-time ordering.
- Restarted the Docker backend after verifying the main migration head and all
  14 tenant schemas were already current. The backend returned to `healthy`; the
  migration runner reported no revision changes.
- Live-shop LightFM eligibility was evaluated read-only; no DB rows, artifacts,
  or model-serving state were changed by that audit.
- Existing offline artifacts and their reports were inspected; none were copied
  into tenant-serving storage.
- No commit or push.

## Current limits / next data needed

- Current old multi-product chunks are intentionally rejected by strict filters;
  reindex the source documents with `structure-semantic-context-v3` and rerun the
  strict audit to recover coverage without weakening SKU/attribute safety.
- For live LightFM, collect more per-shop consented exposures and click/cart/purchase
  outcomes. Do not lower thresholds or use the public datasets as live customer data.
