# Customer transfer report moves order to staff confirmation — 2026-11-25

- Sending payment/QR instructions still leaves the order draft (Mới tạo).
- Customer reports transfer, including short confirmation bound to a delivered transfer request: existing scoped customer payment-report operation now transitions only draft prepay_then_confirm bank-transfer orders to pending_confirmation via transition_sales_order.
- Payment remains awaiting_reconciliation; paid_amount, revenue and inventory are not altered. Staff still cannot mark the order confirmed without required payment reconciliation.
- Notification, payment-report metadata, and status event commit together. Repeat reports are idempotent and do not downgrade orders that staff already advanced.
- Customer response explicitly states the order is unpaid and waiting for staff confirmation.
- 21 tests plus 3 subtests passed, including event uniqueness on repeat confirmation and unchanged product stock/reservations and paid amount.
- Read-only live check: shop 8 / conversation 28 / CHAT-15 is already delivered and had customer_payment_reported_at. Therefore no historical order was changed or downgraded, and no snapshot file was created. No customer message was sent.
- Backend/worker restarted. Other historical orders were not bulk-migrated.
