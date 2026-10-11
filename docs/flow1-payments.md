# Flow 1 subscription payments

> Current checkout uses local VietQR with manual administrator reconciliation. See [VietQR setup and handoff](flow1-vietqr-handoff.md). The payOS instructions below apply only to historical integrations and existing orders.

## Integration

Install `backend/requirements.txt` (`payos==1.1.0`) before importing the API.
Include `app.api.subscription_payments.router` in the existing `/api` router and
import `SubscriptionPaymentAttempt` from `app.models.subscription_payment_attempt`
in the model registry. These exports are integrated by the main implementation.

Migration `backend/alembic/versions/20261011_0058_subscription_payment_attempts.py`
follows `20261011_0057`. It creates a durable attempt table with unique subscription,
order code and provider link identities. Apply migrations through the normal deployment
process; this implementation did not migrate any live database.

Implementation paths:

- `backend/app/services/subscription_payment_service.py`
- `backend/app/api/subscription_payments.py`
- `backend/app/models/subscription_payment_attempt.py`
- `backend/app/schemas/subscription_payment.py`
- `backend/tests/test_subscription_payments.py`
- `backend/app/core/config.py`
- `backend/requirements.txt`
- `.env.example`, `.env.production.example`, `backend/.env.example`

## API contract

Authenticated same-shop members use:

- `POST /api/onboarding/shops/{business_id}/subscription/{subscription_id}/payment`
- `GET /api/onboarding/shops/{business_id}/subscription/{subscription_id}/payment`

POST takes no amount or provider identity from the client. It uses the server's
`Subscription.quoted_amount` and `quoted_currency`, with legacy plan price fallback
(chatbot requests use the existing rental-price helper). Amounts must be positive whole
VND and fit the existing receipt ledger. An attempt permanently freezes that amount.
Pending and active requests can pay; downgrades cannot create attempts. A paid manual
receipt is visible through GET and suppresses a new provider checkout through POST.

The response contains `status`, `amount`, `currency`, `qr_code`, `checkout_url`,
`bank_name`, `bin`, `account_name`, `account_number`, `reference`, `expires_at`,
`approval_status`, and `reconciliation_required`. `reference` is immutable transfer
content (`SUB {subscription_id}`), not the bank transaction ID. The latter is stored
separately as `provider_transaction_reference` and on the Payment receipt.
The official create response supplies bank BIN but no bank name, so `bank_name` is
nullable. Render QR from the returned provider QR payload.

Statuses: `not_created`, `creating`, `pending`, `paid`, `refunded`, `expired`, `cancelled`,
`reconciliation_required`. QR and checkout URL appear only for `pending` checkout.
`paid` means a ledger receipt exists; `approval_status` independently represents
subscription approval. Browser return/cancel URL parameters never establish payment
or activate a subscription.

Only positive VND paid receipts establish paid status, suppress checkout, or trigger
manual-overlap reconciliation. Legacy zero-value Demo or foreign-currency receipts
are retained but ignored for those decisions. When no positive VND paid receipt remains
and a positive VND refunded receipt exists, GET reports terminal `refunded`, even if
the attempt still says paid; QR and checkout URL remain hidden. POST does not create
another checkout for that refunded request. A remaining positive VND paid receipt
takes precedence over a refunded receipt from another transfer.

## Configuration and recipient validation

Required: `PAYOS_CLIENT_ID`, `PAYOS_API_KEY`, `PAYOS_CHECKSUM_KEY`,
`PAYOS_RETURN_URL`, `PAYOS_CANCEL_URL`, `PAYOS_EXPECTED_ACCOUNT_NUMBER`,
`PAYOS_EXPECTED_BANK_BIN`. Empty configuration disables creation with an actionable
503 (`payment_not_configured`, listing missing settings). Return/cancel URLs must
use HTTPS. `PAYOS_PAYMENT_TTL_SECONDS` defaults to 900 and must be positive.
Set these values in the backend runtime; root Compose interpolation alone may not
forward every variable. Keep real credentials out of example files and tests.

The SDK signs creation and verifies provider response signatures. Before exposing QR,
the service checks amount/currency/order identity, account number and BIN against the
configured own-bank recipient, and snapshots the recipient from that verified response.
Checkout must use HTTPS at `pay.payos.vn` with no user information or nonstandard port.

## Webhook and accounting

`POST /api/webhooks/payos` accepts the original payOS JSON envelope and returns
`{"accepted": true}` only after verified receipt recording, a saved manual-review
observation, or an exact replay.
The exact documented, signature-verified registration sample is acknowledged without
ledger writes; changed sample transaction fields are rejected as unknown real orders.
This permits webhook setup without ever counting the provider's fictitious test transfer.
The official SDK verifies the signature; the service additionally requires successful
envelope/data codes and matches signed order, amount, currency, payment link, and
recipient account against the saved attempt. Unknown orders, missing snapshots,
invalid signatures and mismatches are rejected. The BIN is checked on create and
against the saved recipient; webhook counter-account fields identify the payer,
so they must not be treated as the recipient bank.

Subscription then attempt row locks serialize checkout and callbacks on PostgreSQL.
Database unique constraints protect attempt identity and transaction receipts.
Each verified bank transaction writes the existing `Payment` ledger with provider
`payos`, status `paid`, transaction identity `payos:{bank_reference}`, and metadata
for order/link/reconciliation. Exact callback replay records nothing twice. A different
valid transaction for the same order is recorded as additional received money and
flagged for reconciliation. Existing manual receipts remain supported.

When any paid non-payOS receipt already exists for this subscription, the callback
does not automatically add revenue. It uses the matching raw/prefixed bank-reference
receipt when available, otherwise the first paid manual receipt. It preserves that
receipt and its metadata, marks the attempt paid with reconciliation required, and
stores each distinct verified transfer in receipt metadata under
`payos_verified_payments_pending_review`. Each observation includes bank reference,
order/link identity, amount, currency, recipient and verification time. Exact replay
does not append evidence twice. GET reports paid with the reconciliation flag.
Identity-matching replay of a refunded payOS receipt is also acknowledged, preserving
the refunded ledger and the attempt without any changes; mismatches remain rejected.
An administrator must compare bank statements and the manual receipt: confirm a
duplicate without adding revenue, or book an actually distinct transfer once through
the existing manual workflow. This evidence is not an additional paid ledger entry;
potentially separate received money remains awaiting administrative review.

Payments received after expiration, cancellation/rejection, or another paid receipt
remain accounted as paid receipts with `reconciliation_required=true`. Neither
subscription activation nor refunds happen automatically. Review the receipt metadata
and provider transaction before resolving reconciliation or recording a manual refund.

## Recovery limits

The order identity and amount are committed before any provider request. After a timeout,
POST looks up that same order. Only an SDK NotFoundError permits another create with
the saved identity; ambiguous lookup failures return 503 and never mint another order.
An existing QR snapshot is reused. GET reads durable status, including manual receipts.

If payOS accepted creation but the response was lost, lookup lacks QR and recipient
details. Creation durably snapshots the configured own-bank recipient before the
network call. POST retry validates the signed lookup's order and amount, saves its
nonempty provider link ID, returns `reconciliation_required`, and exposes no QR or
checkout URL. Older attempts missing the recipient use the mandatory configured
account/BIN during recovery. A subsequent signed webhook must match the saved
order/link, amount, currency and configured recipient; it can record payment while
retaining the reconciliation flag. This does not prove the omitted QR/recipient
response, so an administrator must review the recovered payment. A webhook arriving
before link recovery is rejected and should be retried after checkout recovery.
No provider lookup status alone creates a paid receipt.

## Verification

Tests use mocked SDK methods and isolated SQLite databases. They cover frozen pricing,
durable retry, configuration, own-bank mismatch, malicious checkout host, callback
signature/mismatch/replay, concurrent uniqueness and callbacks, manual status recovery,
late payment, extra transfers, authorization, and no activation. SQLite exercises unique
constraints but does not implement PostgreSQL row locks; production lock contention
still requires a PostgreSQL integration check.

The main integration's platform manual-payment writer now acquires the same subscription
row lock and rejects additional paid receipts (including pending-to-paid transitions)
when another positive VND paid receipt exists. Both paths ignore legacy zero-value or
foreign-currency receipts for that guard. The service also locks the selected manual
receipt when appending reconciliation evidence. These follow-ups need no migrations.

Official SDK documentation: https://payos.vn/docs/sdks/back-end/python
Official API schemas: https://payos.vn/docs/api/
