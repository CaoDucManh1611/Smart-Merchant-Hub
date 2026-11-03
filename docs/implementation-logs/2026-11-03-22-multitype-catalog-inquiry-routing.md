# Multi-type catalog inquiry routing

## Reproduced behavior

- The approved Telegram inquiry for a shop service reached the bot, but the graph selected `catalog + knowledge` and the answer fell through to a generic staff-review response.
- RAG run `business_id=7`, `conversation_id=7`, incoming message `5046` recorded six evidence entries and `needs_staff_decision=true`; the worker spent about 3.55 seconds processing the turn.
- The inspected shop had only the `retail` workspace module enabled and no active `appointment_services`. Its live catalog contained goods, not a configured service listing. The bot therefore had no verified service price or appointment to quote.

## Changes

- Explicit service and rental inquiries now take a deterministic, read-only, tenant-scoped catalog path before the LLM planner. Explicit booking actions remain on the existing workflow path.
- The path ranks current service/rental entries by meaningful name/description terms, respects an explicit price ceiling, and returns at most three matches. It uses the current catalog price and billing unit; missing or zero prices are marked unconfirmed and sent for staff review.
- Appointment availability is never inferred from inventory: the customer is asked for a date/time. Rental availability is never inferred from stock count: the customer is asked for a rental date range.
- If the shop has no configured offerings of the requested type, or no match in the active catalog, the bot says that the data is not configured/matched, does not invent a service or price, and invokes the existing staff notification path.
- The informational route explicitly states that no appointment or rental request was created. Broad service inquiries can show a short menu. RAG logs now include the typed catalog reply mode and candidate count without logging customer text.
- Catalog evidence labels for service and rental availability were corrected so neither is described as ordinary product stock.

## Verification

- `python -m py_compile backend/app/services/conversation_graph.py` passed.
- `git diff --check -- backend/app/services/conversation_graph.py` passed.
- Restarted the mounted worker. `crm_chatbot_worker` became healthy, and importing `app.services.conversation_graph` inside the container succeeded. Backend remained healthy.
- No tests were added or run. No second Telegram message was sent; the user's action-time authorization covered only the one service inquiry already used to reproduce the issue.

## Limits

- Shop 7 has no configured appointment service, so a successful service-price/appointment example cannot be demonstrated against that shop's current data. The new configured-service match path is source-validated but not live-verified with an actual configured service or rental listing.
- This implementation is shared across businesses and relies on each shop's typed catalog entries (`offering_type`) or active appointment-service records. It does not create missing catalog data for a shop.
