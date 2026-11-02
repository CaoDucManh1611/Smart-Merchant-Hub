# RFM/RAG ranking work log — 2026-11-01

Timezone: Asia/Bangkok (UTC+07:00)

## Scope

Implement the agreed first slice before adding LightFM:

1. Preserve the current shop ranking/retrieval score when applying the live learned reranker; use a weighted blend on a bounded candidate pool.
2. Restrict reranker training data to customers whose current shop setting, current personalization consent, and opt-out state permit personalization, before loading interactions or building feature groups.

No commit or push was requested. The user's server is being started independently; this work does not start or restart it.

## Activity

- 15:40 +07 — Inspected the current branch and working tree. Existing unrelated modified and untracked files were preserved.
- 15:40 +07 — Confirmed `serve_recommendations` previously replaced every candidate score with the live model score, and `_load_groups` loaded requests/events without checking current consent.
- 15:40 +07 — Confirmed serving already gates customer personalization on the shop setting, a non-opted-out customer record, and the latest `personalization` consent. Consent revocation also clears the customer's stored recommendation requests and interaction rows.
- 15:40 +07 — Added a bounded top-50 blend: normalized current baseline score and live model score, using 0.85 baseline weight for specific queries and 0.65 for broad discovery requests. If fewer than two valid model scores exist, the baseline ranking is retained.
- 15:40 +07 — Added the same current setting/consent/opt-out gate to training before request-linked events and candidate features are built. Requests without a currently eligible customer are excluded.
- 15:41 +07 — Saved the pre-rerank score and position in each candidate snapshot and taught training to reuse them, so the next training run does not learn from the prior model's blended order.
- 15:41 +07 — Sorted candidates by the current baseline even when no live reranker is active; guarded model-version trace access against caller-provided context values.
- 15:51–15:53 +07 — Added `normalized_baseline_blend_v1` as a shared serving/evaluation contract. The blend preserves the baseline signal and uses query-specific weights: 0.85 for specific queries and 0.65 for discovery queries.
- 15:51–15:53 +07 — Added the blend version and server-generated blend trace to each displayed impression event, including retrieval/model weights and candidate counts; added a test that inspects the persisted event metadata.
- 15:51–15:53 +07 — Added six offline tests for query weights, baseline/model blending, consent and opt-out filtering, impression metadata, baseline-versus-blend ranking, and chronological holdout reporting.
- 15:51–15:53 +07 — Fixed holdout metrics to look up relevance from the exposed set while ranking the full candidate pool. Strengthened the temporal test to prove the trained blend improves its deterministic fixture from NDCG@3 0.63093 to 1.0.
- 15:51–15:53 +07 — Attempted an actual 180-day shop evaluation in read-only transactions. PostgreSQL was reachable, but the configured platform/tenant URLs fall back to the legacy `DATABASE_URL`; the database has `public.tenant_schema_registry` instead of the expected `tenant_registry`, and lacks the recommendation request/feedback/interaction tables needed for evaluation. Saved the exact blocker and synthetic-only metric separately in `2026-11-01-rfm-temporal-evaluation.json`.

## Validation and limits

- `RUN_POSTGRES_TESTS=0 python -m pytest tests/test_live_reranker_blend.py -q --tb=short` — **6 passed** in 3.47 seconds; no app server or PostgreSQL fixture was needed. The run emitted 8 `datetime.utcnow()` deprecation warnings from the test/script paths.
- AST syntax parsing passed for all five touched Python files; `git diff --check` passed.
- The synthetic temporal test confirms the evaluator's arithmetic only. A real shop baseline-versus-blend score is **not available yet** because the reachable database schema and required event tables do not match the trainer's expected layout. No model was activated, trained artifact persisted, or database row changed.
- No server was started or restarted; no commit or push was made. Pre-existing unrelated worktree changes and uploaded media were preserved.

## Runtime DB correction and system inventory

- The earlier schema blocker conclusion applied only to the Windows .env fallback database `crm_chatbot`. Inspecting Docker backend environment confirms explicit `crm_platform` and `crm_tenant` URLs. The runtime registry and recommendation tables exist.
- Read-only runtime inventory found 14 active tenants, 46 recommendation requests, and 134 interaction rows, all impressions. No click/cart/purchase/skip labels were observed; feedback tables are empty. This is the actual behavioral-training blocker in the inspected snapshot.
- Runtime Gemini embedding dimension is 768; shop_1 still has a vector(3072) column and no populated vectors. Other tenant vector columns are 768.
- User confirmed the target is official multi-shop production operation. Full source map, psql dt/d outputs, all table row counts, and relevant source snapshots are in `2026-11-01-system-inventory/REPORT.md`.
- This pass collected evidence only; no application code, DB rows, model activation, server lifecycle, commit, or push was changed.
