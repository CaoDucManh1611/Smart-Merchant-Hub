# P0-04 Tenant Isolation Design

## Goal

Ensure every tenant-scoped API and service operation can only read or mutate
records belonging to the resolved `business_id`.

## Current constraint

The backend does not yet have a complete authentication/authorization layer.
Webhook requests identify a tenant through the connected channel account;
development-only internal requests may use `X-Business-Id`. Production
requests without a trusted tenant context must be rejected rather than falling
back to `default-business`.

## Tenant context

Add a small `TenantContext` dependency/service that carries an integer
`business_id` and its source (`authenticated_user`, `channel_account`, or
`development_header`). It must reject missing or invalid tenant context. There
is no default-tenant fallback. The development header is disabled when
`ENVIRONMENT=production`.

Webhook resolution must verify the provider signature/token, then look up
`Channel.business_id` using the channel type and external account id. The
payload's arbitrary `business_id` is never trusted.

## Query boundary

Repositories and route handlers must scope all reads, updates, deletes, lists,
searches, and counts by `business_id`. Resource lookup must use a combined
predicate such as `WHERE id = :resource_id AND business_id = :business_id`; a
resource in another tenant is reported as not found. Inserts take
`business_id` only from `TenantContext`. Joins must include the tenant
predicate on the root resource, not only rely on a child foreign key.

Whenever an insert or update references another tenant-scoped record (for
example, a conversation's customer or a document's business), validate that
the referenced row has the same `business_id` before committing.

The initial implementation covers conversations/messages, documents/chunks,
customer and identity operations, channel/OAuth configuration, the message
repository, auto-reply paths, and RAG/vector retrieval. Vector searches must
join/filter through the owning document's `business_id`. Background and
auto-reply jobs explicitly carry `business_id`; they must not rediscover a
tenant from a global default.

OAuth tenant state must be signed (or stored server-side with an opaque,
single-use state) and validated on callback. Global platform health and
migration endpoints are not tenant-scoped.

## Compatibility

Existing nullable `business_id` rows are treated as legacy data and are
invisible to tenant-scoped endpoints until they are explicitly assigned to a
tenant. No destructive backfill or cross-tenant inference is performed in this
phase.

## Verification

Add route/service tests proving tenant A cannot read, update, delete, or attach
to tenant B's customer, conversation, document, message, or channel; that
lists/searches/counts and vector retrieval are scoped; that cross-tenant
foreign keys are rejected; and that background jobs retain their tenant.
Add tests for missing tenant context, webhook authenticity and channel
resolution, signed OAuth state, legacy `NULL business_id` invisibility, and
production rejection of `X-Business-Id`. Run the existing contract and
identity test suites as regression checks.
