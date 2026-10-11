# Flow 1 — Checkout and sales workflow

> Update: new checkout requests use local VietQR, not payOS. Follow [VietQR setup and handoff](flow1-vietqr-handoff.md); retained payOS behavior below concerns historical orders only.

## Scope delivered

- Checkout selects a plan, confirms changes, freezes the server-side price, and exposes the latest request and separate payment/approval statuses.
- A downgrade, including a paid tier to Demo, stays pending until admin approval. Existing access remains active. No payment attempt or refund is created.
- payOS QR payments use the merchant's configured bank account. Only a verified webhook or an admin-confirmed receipt updates the existing payment ledger; neither automatically approves a subscription.
- Signed webhook replay is idempotent. Manual receipt/webhook overlaps are marked for reconciliation rather than automatically counted twice.
- Shops submit social-connection support tickets and read their own statuses/history. Person 3 can integrate the admin list/update API described in [ticket handoff](flow1-ticket-handoff.md).
- Quote item edits persist correctly. Project edits no longer silently offer a customer change the API cannot save. Appointment, order, inventory, quote and project regression checks passed; see [business verification](flow1-business-verification.md).

## Starting real QR payments

1. Register at [my.payos.vn](https://my.payos.vn), complete the provider's identity verification, link your own supported bank account, then create a payment channel. Follow [the official integration guide](https://payos.vn/tich-hop-thanh-toan-truc-tuyen-vao-website/).
2. Put the channel's `PAYOS_CLIENT_ID`, `PAYOS_API_KEY`, and `PAYOS_CHECKSUM_KEY` only in the untracked `backend/.env`. Do not paste keys into chat, commit them, or put them in frontend `VITE_*` settings.
3. Set `PAYOS_EXPECTED_ACCOUNT_NUMBER` and `PAYOS_EXPECTED_BANK_BIN` to that same recipient; set `PAYOS_RETURN_URL` and `PAYOS_CANCEL_URL` to your application's public HTTPS URL. A browser redirect never proves receipt of money.
4. Expose the backend through a trusted HTTPS deployment/tunnel and register `https://YOUR_HOST/api/webhooks/payos` on the payment channel. `localhost` is not reachable by payOS. Configure the exact public host in `ALLOWED_HOSTS`; retain normal authentication on all other routes.
5. Recreate the backend after changing environment settings; restart alone does not reload Compose `env_file`. Build backend/worker images with the updated requirements for durable deployments. Compose already reads `backend/.env`; no secret needs to be forwarded to the frontend.
6. With explicit owner approval, perform one low-value real transfer and verify the receipt appears once in admin billing, while plan approval remains separate. No real transfer was performed in this implementation.

Until these settings exist, payment creation deliberately returns `payment_not_configured`, not a fake QR or success. See [payment configuration and recovery](flow1-payments.md).

## Verification and local integration

- Integrated backend batch: 70 tests plus 16 support subtests passed; an additional checkout/admin batch passed 21 tests after the manual-receipt and request-lock changes.
- Final payment-specific suite: 70 tests passed after manual-overlap, refund/replay and signed registration-probe fixes.
- Full frontend suite: 254 tests passed. Production build passed (existing large-bundle warning remains).
- Playwright CLI/Edge component checks: checkout submit/pay actions, local QR rendering, untrusted checkout URL rejection, 375px layout, light/dark modes, and no payment control on downgrades. Provider/API responses were mocked, not live bank transactions.
- An isolated PostgreSQL scratch-schema check passed: two concurrent checkout calls created one provider order, and two identical callbacks created one receipt without activating the subscription. The scratch tables/schema were removed after the check; customer tables were not modified. This is a focused lock check, not a production load test.
- Local legacy and platform databases were backed up before additive migrations. Revisions advanced to `20261011_0058` and `20261011_0002_support_requests`. No customer rows or database volumes were deleted.
- No commit or push was made.

Reference patterns were reviewed in [Stripe Python](https://github.com/stripe/stripe-python) and [Medusa](https://github.com/medusajs/medusa). The implementation uses [the official payOS Python SDK](https://github.com/payOSHQ/payos-lib-python), not an unrelated checkout application's database or payment recipient.

## Remaining deployment checks

Live payOS credentials, public webhook registration, actual bank receipt and production contention/load tests require deployment verification. Full backend-suite coverage is not claimed. Person 3 still owns integrating the admin support-ticket UI; the shop UI and authenticated handoff APIs are ready.
