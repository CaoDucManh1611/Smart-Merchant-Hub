# RAG live-case precision fixes — 2026-11-03

## Scope

Applied local code changes based on the Telegram answers the user supplied for cases 21–50. No Telegram messages were sent during this code pass. No commit or push was made.

## Changes

- Kept requested product identity separate from vehicle compatibility when building product candidates. A shared vehicle fitment can no longer make an unrelated accessory satisfy the requested product category.
- Added a read-only catalog-selection route for “I need/find …” requests when the requested product identity exists in the current shop catalog. This keeps product discovery out of pending order or booking collection flows.
- Preserved the customer's preceding explicit product query when resolving a short follow-up such as “the cheaper one”; the prior customer query takes precedence over a possibly incomplete assistant answer.
- Narrowed multi-product price/stock calculations to resolved catalog items. The bot only calculates a two-item total when exactly two current products match. Ambiguous variant sets now ask for SKU or vehicle/version details instead of summing unrelated variants.
- Tightened fitment handling: an explicit vehicle/model with no verified matching product now prompts for make/model/year or the old part SKU rather than returning a merely related item.
- Routed warranty/return/delivery policy questions to knowledge evidence first, and product-use/comparison questions to catalog plus knowledge evidence, avoiding unrelated request-collection routes.
- Generic “any type is fine” requests for fitment-sensitive motorcycle parts now trigger a vehicle clarification.

## Validation and limits

- Python `compileall` for the two edited service modules completed successfully.
- `git diff --check` for the edited modules completed successfully.
- Pytest was not run in this pass.
- Budget notation such as `200.000đ` is already parsed as VND 200,000 by the local code. The earlier Telegram output of 200 indicates the running service may be stale or use another checkout/configuration; restart the backend that serves the bot before judging that fix.
- These edits are local. They do not affect the currently running Telegram bot until the correct backend process is restarted/redeployed. Actual outputs still need a live recheck, especially for product variants whose metadata or fitment is incomplete.

## Files

- `backend/app/services/auto_reply_service.py`
- `backend/app/services/conversation_graph.py`
