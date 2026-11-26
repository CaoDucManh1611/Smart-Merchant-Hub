# Cancellation and refund customer notifications — 2026-11-25

- Added cancelled to the shared committed order-status notification map. Retail and service cancellations now enqueue durable notifications to the order's own customer conversation/channel.
- Service-order cancellation is no longer excluded by the service notification filter. Existing service completion acknowledgement remains owned by its previous handler.
- Cancellation text explicitly distinguishes cancellation from a completed refund when paid funds remain.
- Refund-created events now capture cumulative refunded amount and paid amount. Notifications retain the specific refund amount and display the cumulative total/remaining received amount as of that event, including partial refunds processed before the final refund.
- Existing per-order cancellation notification key and per-refund event keys preserve retry idempotency. No task is sent for a rolled-back transaction or an order with no associated customer conversation.
- Initial 14 cancellation/status/refund tests passed. Added assertions that delayed partial-refund messages retain their own event totals after a later full refund, then ran broader payment checks.
- No real cancellation, refund, payment, stock change or manual customer message performed. Historical cancellations are not bulk-notified.
- Previously authorized complete-form-before-quote-confirmation change is also regression-checked before restarting these services.

Broader validation: 20 cancellation/status/refund/payment API/form tests passed in the isolated SQLite test setup. API test process explicitly used ENVIRONMENT=test and an allowlist including testserver; live runtime security/environment configuration was not changed. Updated the old over-refund fixture to use 1 VND rather than 0.01 VND so it actually tests exceeding the refunded balance, instead of being rejected earlier by the existing whole-VND schema validation.
