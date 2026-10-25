# CRM 360 and recommendation verification — 2026-10-25

## Implemented

- The conversation graph now calls the existing, tenant-scoped recommendation service for product advice and uses the current CRM catalog as the authority for price and availability. The recommendation request ID and ranked product IDs travel with the outbound message for feedback attribution.
- Customer facts enter the graph only after the shop enables extraction, the customer grants personalization, and the customer has not opted out. Facts outside their validity window, low-confidence facts and facts from another shop are excluded.
- Approved response-style experiments can serve the graph without changing transaction rules. No experiment or personalization grant was enabled for a live shop during this rollout.
- The existing goods, service and rental collection flow keeps the sequence of customer details, payment choice, review, draft request, eligible payment instructions and reconciliation. PostgreSQL remains the system of record.
- Segmentation reports a cold start and uses deterministic RFM when fewer than 20 eligible purchasing customers are available. The general knowledge template now describes suitability, alternatives and staff decisions without freezing mutable catalog values.
- Graph logs record source types, source hashes and document IDs, without copying customer facts into the diagnostic record. Backend and worker report matching runtime revision `b1395ba4a117d5e6`.

## Verification

| Check | Result |
| --- | --- |
| Focused PostgreSQL integration and regression checks | 36 passed, 38 deselected |
| Isolated SQLite graph, collection, booking and payment checks | 97 passed |
| Real LLM with synthetic products, rental and service, same-chat price/stock changes, consent/revocation, conflicting document, tenant privacy | 9 of 9 assertions passed; results in `artifacts/context-rollout-results.json` |
| Knowledge template download test | 1 passed |
| Python compile, `git diff --check`, backend/worker revision check and container health | Passed |

The revocation scenario withheld the old preference, but its reply still suggested asking staff where a simple clarification to the customer would be better. This is a response-quality issue to address before broad enterprise rollout.

## Scope and remaining risks

- The existing recommendation ranker covers `Product` rows. Appointment services are offered through the current catalog and scheduling flow; they do not yet receive the same personalized ranking. A product marked as rental uses its configured billing unit.
- The graph's catalog read is bounded to the first 100 active products and 100 services. Large tenants need paginated or query-targeted retrieval before this can be considered complete coverage.
- The customer-facing browser was unavailable because local browser control is disabled in Work settings. Facebook to CRM to Facebook delivery was therefore not rechecked after this rollout. The nine LLM checks used synthetic data and made no customer-facing sends.
- No real payment, bank transfer, full-load test or model weight training was performed. Learning policies remain opt-in and need outcome volume and offline validation before broad activation.
