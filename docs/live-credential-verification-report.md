# Live credential verification report

**Date:** 2026-09-13
**Scope:** Safe verification with the credentials mounted in the running CRM
containers. Secrets, account IDs, public URLs and provider response bodies were
not captured in this report.

## Safety boundary

- Provider checks used only read-only account/model endpoints, except for one
  SMTP OTP delivery to the configured sender mailbox itself.
- Webhook checks used an empty/synthetic probe with no customer content. CRM
  data remained at **8 conversations / 713 messages** after the probes.
- No customer-facing Telegram/Zalo/Facebook/Instagram message and no SMS was
  sent.

## Results

| Component | Result | Evidence / conclusion |
|---|---:|---|
| Facebook page token | FAIL | Meta OAuth error `190/463`: token has expired. |
| Instagram token | FAIL | Meta OAuth error `190/463`: token has expired. |
| Meta webhook verify/signature in backend | PASS | Real verify token and app-secret HMAC accepted for Facebook and Instagram. |
| Meta public webhook route | BLOCKED | All public URL routes returned `404`; the configured public endpoint does not currently reach this backend. |
| Telegram bot credential | PASS | `getMe` and `getWebhookInfo` returned HTTP 200. HTTPS webhook is configured with zero pending updates. |
| Telegram webhook signature in backend | PASS | Active channel's real webhook secret accepted a zero-message probe. |
| Zalo Bot credential | PASS | Read-only bot-info endpoint returned HTTP 200. |
| Zalo webhook signature in backend | PASS | Active channel's real webhook secret accepted a zero-message probe. |
| Zalo public webhook route | BLOCKED | Same public URL routing problem returns `404`. |
| Groq chat inference | PASS | One minimal non-customer prompt completed successfully. The provider's models-list endpoint returned 403, but the configured inference call works. |
| Gemini model catalog | PASS | Read-only model listing returned HTTP 200. |
| Gemini embedding / RAG | PASS | One minimal query embedding succeeded at 768 dimensions. |
| SMTP authentication | PASS | SMTP STARTTLS and login succeeded. |
| SMTP delivery | PASS | One OTP test was accepted for delivery to the configured sender mailbox. |
| Twilio credentials | PASS | Read-only account endpoint returned HTTP 200. No SMS was sent because no dedicated test number was supplied. |
| Redis shared rate limit | FIXED + PASS | Runtime had `memory/disabled`; it was changed to `redis/enabled`, restarted, and health reports Redis `ok`. |
| Database / queue / alerts | PASS | Database, worker queue and health checks are normal; no alerts are firing. |
| External payment gateway | NOT CONFIGURED | The repository has an internal idempotent payment-record state machine, but no Stripe/MoMo/VNPay/PayPal credential or live webhook integration exists to verify. |

## Required operator actions before public production

1. Refresh Facebook Page and Instagram access tokens, then reconnect/update the
   tenant channel credentials.
2. Point `PUBLIC_BASE_URL` at an active public HTTPS reverse proxy or tunnel
   that routes `/api/webhooks/*` to this backend. The currently configured
   public URL returns 404 for root, health, docs and every webhook path.
3. Re-register/verify each webhook in Meta, Telegram and Zalo after the route
   is repaired.
4. Move from `ENVIRONMENT=development` to a hardened production configuration:
   configure `AUTH_SECRET`, explicit CORS/allowed hosts, HTTPS/HSTS and a
   non-superuser application database role.
5. Choose and configure a real payment gateway before claiming live
   subscription-payment automation.

## Local change made during verification

`backend/.env` now enables shared Redis rate limiting:

```dotenv
RATE_LIMIT_ENABLED=true
RATE_LIMIT_BACKEND=redis
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

The file is intentionally local/ignored and contains no credentials in source
control.
