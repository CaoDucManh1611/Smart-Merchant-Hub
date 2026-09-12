# CRM platform quality runbook

## Quality signals

`GET /api/experiments/evaluation/dashboard?days=30` returns tenant-scoped
model evaluation averages, experiment exposure/outcome conversion, and RAG
run status counts. It also reports handoff rate, duplicate outbound attempts
tool errors, and chatbot draft-to-confirmed conversion so a high conversion
rate cannot hide an unreliable bot. The AI Rule Lab renders the same contract;
no customer message content is sent to the dashboard.

`GET /api/reports/quality?days=30` is the operations snapshot used by the CRM
Reports page. It combines current-period tenant quota usage/limits, failed and
retrying provider events, circuit state, AI calls/cost/tool errors, and open or
overdue SLA counters. The endpoint is tenant-scoped and returns counters only;
it never includes message bodies, contact data, channel tokens, or model
prompts. AI cost is a conservative, configurable estimate (roughly four
characters per token plus the configured output allowance) because provider
usage payloads are not uniform; each RAG run is charged once by its idempotency
key. The standalone `/api/chat` endpoints and background Customer Facts
extraction use the same preflight ledger, so an alternate AI entry point
cannot bypass the tenant budget. Clients may send `X-Idempotency-Key` when
retrying `/api/chat` or `/api/chat/stream`.

## Unified events

Every new audit entry receives a stable `event_id`, `actor_type` (`staff`,
`bot`, `customer`, or `system`) and optional `correlation_id`. Platform admins
can read the canonical stream at `/api/platform/events`; tenant audit views
continue to use `/api/auth/audit-logs`. Tool execution accepts an optional
correlation id outside its arguments, so an inbound-triggered tool call can be
traced without allowing the model to write arbitrary audit fields.

## MFA and sessions

An owner/admin prepares TOTP at `/api/auth/mfa/prepare`, scans the URI once,
then verifies a six-digit code at `/api/auth/mfa/verify`. Sessions created for
an enabled user remain blocked until that session is verified. Device labels,
hashed network metadata, last-seen time and individual revocation remain
available under `/api/auth/sessions`.

## OTP delivery

External checkout OTPs are persisted only as hashes. Set
`OTP_DELIVERY_MODE=disabled` when no delivery is needed, or `in_chat` for a
free development demo: the raw code is intentionally shown in the immediate
Telegram/Zalo bot prompt (and therefore the demo chat history) and is never
allowed in production. The current checkout rollout uses `smtp` with
`OTP_SMTP_HOST`, `OTP_SMTP_USERNAME`, `OTP_SMTP_PASSWORD`, `OTP_SMTP_PORT` and
`OTP_FROM_EMAIL`; for Gmail, create an App Password and use that value instead
of the normal account password. In SMTP mode only the email challenge is
created, so an undelivered SMS challenge cannot block email verification.
`twilio` with `OTP_TWILIO_*` remains available for a later SMS rollout.
Production startup rejects a missing provider configuration and rejects the
in-chat fallback; credentials must be injected by the secret manager. A
provider outage leaves the challenge queued and is recorded as a redacted
audit event, without blocking creation of the draft order or exposing the OTP
in logs/responses.

## Data lifecycle

Admins can export, anonymize, or delete customer data. `/api/privacy/requests`
shows the idempotent lifecycle queue without returning customer payloads, and
`/api/privacy/retention` exposes the configured `DATA_RETENTION_DAYS` policy.
Accounting order/audit records stay retained while direct identifiers and
message content are redacted on delete.

## Draft inventory holds

Chatbot-created draft orders hold the requested quantity in
`products.reserved_quantity` for two hours without decrementing on-hand stock.
The hold is idempotent and is released on cancellation or automatically by the
CRM worker after expiry. `OrderOut.reservation_expires_at` lets the inbox and
operations screens explain why a draft is no longer available for confirmation.
When a held draft is confirmed, the existing hold is converted into the normal
confirmed-order reservation exactly once.

## Transactional routing and correlation

Order-list, draft-list, status, cancellation and refund intents are resolved
from the tenant/customer relationship before RAG. Natural phrases such as
“tôi có đơn hàng nào” and “tôi có đơn hàng nháp nào” return database-backed
results; policy questions still use RAG. Each inbound auto-reply key is copied
to outbound metadata and audit entries, providing a redacted
`inbound_message_id → route → outbound_message_id` trace for duplicate or
provider-retry investigations.

## Provider resilience and rate limiting

Channel provider retries now share a process circuit breaker with closed,
open and half-open states. Configure `RATE_LIMIT_ENABLED=true` in production;
when the app is behind a trusted reverse proxy, set
`RATE_LIMIT_TRUSTED_PROXY=true` so the limiter uses the proxy-supplied client
address. Keep proxy rate limiting enabled as the shared multi-replica layer.

`GET /health` remains the lightweight load-balancer probe. `GET
/health/details` is the operator probe: it checks database connectivity,
reports pending/running durable CRM jobs, and shows redacted provider circuit
states. A degraded response is actionable but still contains no credentials or
customer payloads.

## Backup and restore

The daily backup runner can execute `scripts/backup-verify.ps1 -BackupFile
<path>` using a secret-manager-provided `DATABASE_URL`. A restore rehearsal
must first run the script with `-VerifyOnly`, then restore to an isolated
database with `-RestoreDatabaseUrl <url>` (add `-Overwrite` only during an
approved replacement window), apply Alembic migrations, run backend/frontend
tests and the tenant-isolation smoke suite, then record checksum, duration and
revision in the operations log. The script never prints database URLs.
