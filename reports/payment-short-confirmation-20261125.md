# Post-transfer customer confirmation — 2026-11-25

- Added an early deterministic graph route for a short customer confirmation after a delivered bank-transfer request. It binds the reply to that conversation/customer/shop and exact order number, and defers when a collection session is pending.
- Uses the existing customer-reported-payment operation: records customer_payment_reported_at, notifies staff once, and changes derived payment state to awaiting_reconciliation. Does not record revenue, paid_amount, or confirm fulfillment.
- Payment instructions now ask customers to reply Xác nhận / Tôi đã chuyển khoản after transferring.
- Sales order payment panel displays a pending reconciliation message when the customer reports payment and an amount remains.
- Validation: 20 customer-order/confirmation tests passed plus 3 subtests; 3 confirmation tests passed again after supporting image captions and repeated confirmation context. Frontend build passed in the existing frontend container (host Vite dependencies unavailable). Backend and worker restarted.
- No historical confirmation was retroactively treated as proof of transfer. No customer messages were sent or order/payment/inventory records modified during this implementation.
- Inline Zalo QR image remains unresolved; this change does not claim to fix the public image-fetch rejection.
