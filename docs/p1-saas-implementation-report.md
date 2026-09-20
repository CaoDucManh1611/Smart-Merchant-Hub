# P1 SaaS implementation report

**Date:** 2026-09-13
**Branch:** `crm-completion`
**Scope:** self-service onboarding, tenant isolation, entitlement/quota
visibility, platform operations and deployment wiring

## Delivered

- Self-service shop onboarding creates a tenant owner, subscription and signed
  tenant/role token in one transaction. Starter, Growth and Pro plans are
  seeded idempotently.
- Channel connection and product import endpoints are tenant-scoped. Channel
  credentials are encrypted at rest and never returned by the API.
- Tenant JWT claims (`business_id`, `role`) are checked against the database on
  every authenticated request. PostgreSQL RLS adds a second isolation layer;
  platform-admin context is explicit and audited.
- Quota snapshots expose plan, usage, limits and near-limit warnings. The
  reservation path locks the usage row and remains idempotent under retries.
- Platform admin can page shops, inspect quota/provider-error metadata and
  request export, anonymization or deletion through the existing lifecycle
  workflow. Provider payloads and secrets are redacted.
- Frontend settings now include onboarding and a tenant quota card; the
  platform panel includes redacted provider-error status.

## API surface

| Area | Endpoints |
|---|---|
| Onboarding | `GET /api/onboarding/plans`, `POST /api/onboarding/shops` |
| Setup | `POST /api/onboarding/shops/{business_id}/channels`, `POST /api/onboarding/shops/{business_id}/products/import` |
| Tenant usage | `GET /api/usage`, `GET /api/usage/warnings` |
| Platform ops | paged shops/usage, provider-error metadata and privacy lifecycle endpoints under `/api/platform` |

## Database and deployment

- Migration `20260919_0043_signup_email_verification` is the current Alembic head.
- The migration enables repeatable tenant RLS policies on all applicable
  `business_id` tables. It is a no-op for SQLite test databases.
- Compose bind-mounts `backend/alembic` so a restart applies additive
  migrations from the checkout. The existing PostgreSQL volume and conversation
  data were preserved.

## Verification evidence

| Check | Result |
|---|---:|
| Backend regression + P1 tests | **450 passed** |
| Frontend regression | **100 passed** |
| Python compile check | **PASS** |
| SQLite Alembic upgrade | **PASS** |
| Docker services | **5 healthy** |
| Runtime Alembic head | `20260919_0043` |
| PostgreSQL RLS policies | **59** |
| Restored data retained | **8 conversations / 713 messages** |
| `/health`, `/health/details`, onboarding plans, frontend | **HTTP 200** |

The detailed functional and business matrix, defects found and release verdict
are recorded in [p1-qa-test-report.md](p1-qa-test-report.md).

## Release gates still requiring real operator credentials

P1 code and the local/staging deployment are complete. A production sign-off
still requires live provider webhook callbacks, a real SMTP OTP delivery,
secret-manager rotation and monitoring destinations. Those checks cannot be
truthfully simulated with the repository test fixtures.
