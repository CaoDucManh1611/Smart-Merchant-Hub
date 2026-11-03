# Recommendation outcome attribution integrity

Date: 2026-11-03

## Why this pass

The live-data audit found that the current reranker cannot be trained or
evaluated honestly yet: 53 recommendation requests, 134 linked impressions,
and no recorded recommendation feedback or real positive outcomes. A chat
action that starts an order-confirmation quote had been recorded as a cart,
and a general rejection of a displayed list had been attributed to its first
product. Those labels would mislead learning.

## Changes

- The generic interaction API now accepts only low-risk `view`, `search`, and
  `ask` events. Recommendation exposures and conversion outcomes remain
  created by server-owned flows.
- The generic recommendation feedback API accepts `click` only. Purchases,
  refunds, quote/order intent, and impressions continue to be written from
  verified server paths.
- A chat-triggered order-confirmation quote is now `checkout_intent`, not
  `cart`; it receives click-level relevance/reward so an uncompleted quote is
  not treated as a completed cart or purchase. Legacy `cart` labels are also
  downgraded to click-level relevance in the trainer.
- A customer declining a displayed recommendation list is recorded as a
  slate-level `slate_skip` with no product ID. It no longer marks the first
  item as an explicit negative.
- Reranker training excludes explicit offline/synthetic traffic and legacy
  chatbot snapshot rows with the `conversation_id=0` sentinel.
- Signed-link GETs still redirect normally, but click telemetry is suppressed
  for known link-preview crawlers and prefetch/prerender requests. Modern
  browsers' `Sec-Fetch-User: ?1` is retained as a positive activation signal;
  clients that omit that header remain eligible unless they look automated.
- Updated focused tests cover blocked client-submitted outcomes, click
  idempotency, preview GETs without click labels, consent revoke/regrant timing,
  slate-level declines, and offline/synthetic training exclusion.
- Updated the no-retrieval-chunk RAG test to reflect current behavior: live
  catalog evidence can still reach the LLM, but an uncited answer is discarded
  and the safe fallback is returned.

## Verification

- `python -m pytest backend/tests/test_recommendations_api.py backend/tests/test_live_reranker_blend.py -q`:
  40 passed, 19 warnings, 6 subtests passed. Warnings are existing
  `datetime.utcnow()` deprecations in tests/training code.
- `python -m py_compile` passed for the changed services, schema, API, trainer,
  and focused tests.
- `git diff --check` passed; Git emitted only its normal LF/CRLF conversion
  notices.
- Restarted backend and worker. Docker reports backend, worker, PostgreSQL,
  Redis, and frontend healthy.
- No migration or model training was run; this change adds no database schema.

## Independent review and remaining limits

- The first independent review found that current-consent-only filtering could
  include pre-consent requests/events and that the generic feedback endpoint
  still accepted unsigned clicks. It also flagged broad list-decline matching.
- Follow-up fixes: training now checks both request creation and each tracked
  event against the latest effective grant timestamp; generic POST feedback
  returns HTTP 410 and `record_feedback` requires an explicitly verified click;
  only the HMAC-signed redirect path can record clicks. Decline tracking skips
  questions and messages that pivot to a different variant.
- Review also identified the risk of missing taps in browsers without Fetch
  Metadata. The final handler instead suppresses known preview crawler user
  agents and prefetch/prerender purpose headers, while accepting ordinary
  clients that omit `Sec-Fetch-User`; the API integration test covers an
  Android webview user agent without that header.
- Added an integration test that drives a chatbot recommendation impression
  through the order-confirmation quote path and verifies it records
  `checkout_intent` with click-level reward, never `cart`.
- This filters common unfurl/prefetch traffic but cannot identify every
  nonstandard link scanner. A scanner using an ordinary browser user agent may
  still create a click label; validate against actual shop browsers/channels.
- The independent second-agent review found no blocker. It noted that the
  Android webview test needed to assert the click before a later `?1` request;
  the test now asserts zero after crawler/prefetch/`?0`, then exactly one
  immediately after the Android webview navigation.
- External clients that POST to `/api/recommendations/{request_id}/feedback`
  must move to the signed product links. No such frontend caller was found in
  this repository.
- `slate_skip` remains an analytics-only signal and is not used as a training
  label, because a list-level refusal cannot safely identify which product was
  rejected.
- The live audit still has no consented recommendation outcome labels, so no
  ranking lift or production model-training result can be claimed. Next
  verification should trace one real recommendation impression to a signed
  click and a completed order for the same consenting customer, shop, request,
  and product before fitting/evaluating the reranker.
- Existing old `cart` rows cannot be reliably distinguished as true carts or
  quote intents, so the trainer treats them conservatively as click-level
  positives.
