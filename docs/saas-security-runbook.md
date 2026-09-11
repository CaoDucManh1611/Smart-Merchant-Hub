# SaaS security and operations runbook

## Current rollout boundary

The demo continues to use one PostgreSQL database with a `business_id` tenant
boundary. `tenant_schema_registry` is only a pilot registry: it records the
deterministic target schema (`tenant_<business_id>`) and a rollout state. It
does not create schemas or move CRM rows. A migration rehearsal must first run
against a restored copy of one shop and pass the tenant-isolation suite.

## Shop lifecycle and quotas

- Platform members use **Settings → Quản trị Smart Merchant Hub** to review
  shop status, current-period usage, and the schema pilot registry.
- A suspended shop remains readable for support but all write endpoints are
  blocked with `business_suspended` until the platform member reactivates it.
- Quotas are checked before staff creation, channel activation, document
  upload, RAG chunk ingestion, and each runtime AI call. A rejected mutation
  returns `429` with `quota_exceeded` and the resource name.
- Usage periods are UTC calendar months. Idempotency keys prevent retries from
  consuming quota twice.

## Backup and restore policy

1. Take an encrypted PostgreSQL full backup daily and retain seven daily,
   four weekly, and twelve monthly copies.
2. Record backup success, duration, size, and checksum in the operations log;
   never place database credentials in that log.
3. Test a restore to an isolated database at least monthly. Run migrations,
   the backend test suite, and a tenant-isolation smoke test against it.
4. For a single-shop recovery, restore to a temporary database first, export
   only that shop's rows, review the export, and then import through an
   approved change window. Do not restore a whole production volume over a
   running instance.

## Production controls

- Set `ENVIRONMENT=production`, random `AUTH_SECRET` and
  `CHANNEL_ENCRYPTION_KEY` (32+ characters), explicit HTTPS/CORS/host
  allowlists, and `RATE_LIMIT_ENABLED=true`.
- Keep channel tokens encrypted at rest. Secrets belong in a secret manager
  or protected environment file, never in source control or audit metadata.
- Monitor `/health`, database connectivity, worker lag, webhook failures,
  quota rejections, 5xx rate, and latency. Alert on repeated failures rather
  than on a single transient webhook retry.
- Before a release, run backend tests, frontend tests, `vite build`,
  `alembic heads`, and `git diff --check`. Record the commit and migration
  revision in the change log.

## Privacy requests

Admins can call the tenant-scoped privacy endpoints to export, anonymize, or
delete customer data. Requests are idempotent by `request_key`; delete needs
the explicit `confirmation_token=DELETE`. Orders and audit records are retained
when required for accounting, while direct customer identifiers and message
content are redacted. Audit entries contain counts and request IDs only.

## MFA and sessions

Current rollout: after preparing TOTP, verify the six-digit code at
`/api/auth/mfa/verify`. When `mfa_status=enabled`, every new session remains
blocked until its own MFA verification succeeds.

MFA is prepared per user through the auth API: the secret is encrypted before
storage and the provisioning URI is returned only during setup. Session lists
expose device metadata and can be revoked individually. Enabling TOTP
verification is a follow-up rollout once the authenticator verification flow is
enabled; until then, keep `mfa_status=prepared` clearly visible to operators.
