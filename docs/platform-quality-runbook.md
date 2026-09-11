# CRM platform quality runbook

## Quality signals

`GET /api/experiments/evaluation/dashboard?days=30` returns tenant-scoped
model evaluation averages, experiment exposure/outcome conversion, and RAG
run status counts. The AI Rule Lab renders the same contract; no customer
message content is sent to the dashboard.

## Unified events

Every new audit entry receives a stable `event_id`, `actor_type` (`staff`,
`bot`, `customer`, or `system`) and optional `correlation_id`. Platform admins
can read the canonical stream at `/api/platform/events`; tenant audit views
continue to use `/api/auth/audit-logs`.

## MFA and sessions

An owner/admin prepares TOTP at `/api/auth/mfa/prepare`, scans the URI once,
then verifies a six-digit code at `/api/auth/mfa/verify`. Sessions created for
an enabled user remain blocked until that session is verified. Device labels,
hashed network metadata, last-seen time and individual revocation remain
available under `/api/auth/sessions`.

## Data lifecycle

Admins can export, anonymize, or delete customer data. `/api/privacy/requests`
shows the idempotent lifecycle queue without returning customer payloads, and
`/api/privacy/retention` exposes the configured `DATA_RETENTION_DAYS` policy.
Accounting order/audit records stay retained while direct identifiers and
message content are redacted on delete.

## Provider resilience and rate limiting

Channel provider retries now share a process circuit breaker with closed,
open and half-open states. Configure `RATE_LIMIT_ENABLED=true` in production;
when the app is behind a trusted reverse proxy, set
`RATE_LIMIT_TRUSTED_PROXY=true` so the limiter uses the proxy-supplied client
address. Keep proxy rate limiting enabled as the shared multi-replica layer.

## Backup and restore

The daily backup runner can execute `scripts/backup-verify.ps1 -BackupFile
<path>` using a secret-manager-provided `DATABASE_URL`. A restore rehearsal
must run the script with `-VerifyOnly`, apply Alembic migrations on an isolated
database, run backend/frontend tests and the tenant-isolation smoke suite,
then record checksum, duration and revision in the operations log.
