# Smart Merchant Hub SaaS Security Design

**Date:** 2026-09-11  
**Scope:** `feat/saas-security` for the existing `crm-completion` branch

## Goal

Add a safe SaaS control plane around the existing tenant-scoped CRM without
migrating the demo's business data to separate databases. Shops keep using the
current `business_id` boundary, while platform administrators gain lifecycle,
quota, usage, audit, and data-lifecycle controls.

## Constraints and non-goals

- Keep the current PostgreSQL database for the demo. Control-plane tables are
  additive and live beside CRM tables until a production split is justified.
- Preserve the existing `ServicePlan`, `Subscription`, `Payment`, `Business`,
  `User`, `AuthSession`, `Channel`, and `AuditLog` contracts where possible.
- Every shop-owned read and write remains tenant-scoped by `business_id`.
- Do not move existing CRM rows or change the default `search_path` in this
  workstream.
- Do not implement outbound webhooks or a setup wizard here.
- Do not store raw MFA secrets, channel tokens, passwords, OTP values, or raw
  customer exports in audit logs.

## Architecture

### Control plane in the current database

Reuse the existing service-plan and subscription tables. Extend the plan
limits with RAG chunks and AI budgets, and add small additive tables for
period-based usage, platform membership, data-lifecycle requests, and the
schema-per-tenant migration registry.

The control plane is accessed only through platform-admin endpoints. A
platform admin is represented by an explicit platform membership/role and is
never inferred from the `X-Business-Id` header. Shop users remain limited to
their own business.

### Quota service

Create one service that reads the active subscription, calculates the limit
for a resource, and atomically reserves usage in the current UTC period. The
resource keys are:

- `staff_users`
- `connected_channels`
- `documents`
- `rag_chunks`
- `ai_calls`
- `ai_cost`

The service returns a structured result (`allowed`, `resource`, `used`,
`limit`, `requested`, `period_start`) and raises a stable `quota_exceeded`
error for API adapters. Reservations must be idempotent when an operation has
an existing idempotency key. Read-only usage endpoints never increment usage.

The checks are placed immediately before the existing mutations:

- team member creation;
- channel connection/upsert;
- document upload and chunk-ingestion completion;
- AI runtime/tool execution and recorded AI cost.

When a subscription is missing or inactive, the default policy is deny for
new billable writes and allow read-only CRM access. Existing records are not
deleted when a shop is suspended.

### Platform administration

Add tenant-independent endpoints under `/api/platform`:

- `GET /shops` — paginated shop list with status, plan, and usage summary;
- `PATCH /shops/{business_id}/status` — suspend/reactivate with audit;
- `GET /shops/{business_id}/usage` — quota limits and current-period usage;
- `GET /audit-logs` — filtered sensitive-operation audit entries.

All endpoints require the platform-admin dependency and reject a shop bearer
session, even if the request supplies another `X-Business-Id`.

The frontend adds a small Platform Admin section only for platform admins. It
shows shop status, plan, quota bars, and suspend/reactivate actions; secrets
and customer content are never rendered.

### Authentication and security controls

- Extend auth-session records with device label, user-agent hash, IP hash,
  last-seen timestamp, and revocation metadata. Add tenant-scoped session list
  and revoke-current/other-device actions.
- Add MFA preparation fields and endpoints: generate an encrypted enrollment
  secret, expose only a one-time provisioning URI/QR payload, and confirm an
  enrollment code through a provider abstraction. Until enforcement is enabled,
  the UI clearly labels MFA as prepared/disabled.
- Keep channel credentials encrypted through the existing credential service;
  all new connection paths must write only `access_token_encrypted` and leave
  the legacy plaintext field null.
- Add a reusable rate-limit dependency with an in-memory backend for the demo
  and a replaceable Redis/backend interface for production. Apply it to login,
  OAuth starts/callbacks, webhook ingress, and AI endpoints.
- Reuse the redacting audit service for shop suspension, quota changes,
  credential connection/disconnection, MFA changes, session revocation, and
  data-lifecycle actions.

### Customer data lifecycle

Add tenant-scoped requests for export, anonymization, and deletion. Export is
generated from an allow-listed set of customer profile, identity, contact,
address, conversation metadata, order, ticket, tag, and fact fields. The
request record stores status, requester, timestamps, and a short-lived local
file reference; it never stores the export body in an audit row.

Anonymization removes direct identifiers while preserving aggregate/reporting
references. Deletion is a guarded operation that requires an explicit
confirmation token, runs tenant-scoped, records counts only, and refuses to
delete shared catalog or audit infrastructure. Both operations are idempotent
per request key.

### Schema-per-tenant experiment

Add a registry table mapping `business_id` to a proposed schema name and
migration state. The migration creates the registry and validates safe schema
names; it does not create tenant schemas or move CRM rows automatically. A
small helper can validate and return a future `search_path` value behind an
off-by-default feature flag, allowing a later pilot on a new shop.

### Operations policy

Document backup frequency, retention, restore drills, health checks, secret
rotation, and production rate-limit storage in the existing runbook. The demo
will expose health/usage information and safe configuration validation, but it
will not pretend that a local Docker database is a production backup system.

## API and error contracts

- Tenant quota rejection: HTTP `429`, detail code `quota_exceeded`, and
  `{resource, used, limit, requested, period_start}` metadata.
- Suspended shop writes: HTTP `423`, detail code `business_suspended`.
- Platform access failure: HTTP `403`, detail code `platform_admin_required`.
- Invalid or cross-tenant data request: HTTP `404` or `422` without revealing
  whether another tenant's record exists.
- Session revoke and data-lifecycle mutations are audited after a successful
  transaction and contain no secrets or customer message bodies.

## Migration safety

Every migration is repeatable with inspector guards and keeps existing rows
valid. New nullable security columns receive safe defaults. Quota counters are
created lazily for the current period, so existing shops continue to work
before a plan is attached. The schema registry is additive and has no effect
unless its feature flag is enabled.

## Test strategy

Backend tests will cover:

- plan/subscription limits and period rollovers;
- atomic quota rejection and idempotent reservation;
- staff/channel/document/RAG/AI enforcement;
- platform-admin isolation and suspend/reactivate audit;
- session metadata and revocation;
- MFA preparation without secret leakage;
- encrypted channel credentials;
- rate-limit behavior and stable errors;
- export/anonymize/delete tenant isolation and idempotency;
- schema registry validation and migration chain.

Frontend tests will cover platform visibility, quota rendering, status actions,
session controls, and redacted customer-data actions. Existing backend and
frontend suites must remain green, with Docker/live-provider checks documented
separately when those services are available.
