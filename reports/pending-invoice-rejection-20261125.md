# Pending-invoice rejection routing — 2026-11-25

- Root cause: catalogue dialogue only deferred to sessions marked pending/partial. Retail checkout marks contact collection completed before asking the customer to confirm its draft order, using awaiting_customer_confirmation. Short rejection was therefore consumed by semantic catalogue dialogue rather than the pending draft handler.
- Catalogue dialogue now also defers completed sessions with explicit awaiting_customer_confirmation or otp_pending flags. Terminal completed sessions without either flag remain normal catalogue conversations.
- Existing draft-decline handler retains the unconfirmed draft, records customer_declined_at/customer_confirmed=false, and closes the active collection session. No paid amount/inventory change and no automatic order creation.
- New full-graph tests disable remote interpretation and cover Không / Không nhé / Không mua nữa. They assert decline metadata, abandoned collection, unchanged draft status/paid amount/stock, and no second order.
- 12 focused rejection/form/split-contact tests passed. Broader checkout/catalogue/payment regression run follows.
- No real customer message or historical order changed during this implementation.

Broader verification: 128 checkout/catalogue/payment regression tests passed.
