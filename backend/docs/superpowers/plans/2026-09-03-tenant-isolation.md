# P0-04 Tenant Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** Enforce tenant isolation for every tenant-scoped API, query, insert, background job, webhook, OAuth callback, and RAG retrieval path.

**Architecture:** Resolve a trusted `TenantContext` at the request boundary. Pass its `business_id` explicitly into repositories and jobs; every SQL predicate, foreign-key validation, list, count, and vector search uses that value. Webhooks resolve a channel account to `Channel.business_id`, while development headers are restricted to non-production.

**Tech Stack:** FastAPI dependencies, SQLAlchemy 2, PostgreSQL, Alembic, pgvector, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-tenant-isolation-design.md`

## Global Constraints

- No default tenant fallback.
- Production rejects `X-Business-Id`.
- Legacy rows with `business_id IS NULL` are invisible to tenant-scoped operations.
- Cross-tenant resources return 404; cross-tenant foreign keys are rejected.
- Webhook payload `business_id` is never trusted.
- OAuth callback state is signed or opaque single-use server-side state.

---

### Task 1: Tenant context dependency

**Files:**
- Create: `app/tenancy/context.py`
- Create: `app/tenancy/dependencies.py`
- Modify: `app/core/config.py`
- Test: `tests/test_tenant_context.py`

- [ ] Write tests for authenticated-user, channel-account, and development-header sources; missing context; and production header rejection.
- [ ] Run the tests and verify they fail because the tenant context API does not exist.
- [ ] Implement `TenantContext(business_id: int, source: str)` and a dependency that rejects missing/invalid tenants, allows `X-Business-Id` only outside production, and never falls back to `default-business`.
- [ ] Run the context tests and the existing identity tests.

### Task 2: Tenant-scoped repository primitives

**Files:**
- Create: `app/tenancy/scoped_queries.py`
- Modify: `app/db/message_repository.py`
- Test: `tests/test_tenant_scoped_queries.py`

- [ ] Write tests showing tenant A cannot fetch, list, count, update, or delete tenant B records and that NULL-business legacy rows are omitted.
- [ ] Run tests to verify failure.
- [ ] Implement reusable predicates and resource lookup helpers requiring `business_id`; return `None`/404 semantics for cross-tenant IDs.
- [ ] Update message repository read/write paths to require `business_id` and validate referenced customer/conversation tenant equality.
- [ ] Run repository and regression tests.

### Task 3: Conversation, customer, channel, and document APIs

**Files:**
- Modify: `app/api/conversations.py`
- Modify: `app/api/documents.py`
- Modify: `app/api/meta_oauth.py`
- Modify: relevant customer/channel routes
- Test: `tests/test_api_tenant_isolation.py`

- [ ] Add failing API tests for cross-tenant GET/PATCH/DELETE, list/search/count, invalid foreign keys, and NULL-business records.
- [ ] Add tenant dependency to each route and pass the context business ID through every query and insert.
- [ ] Replace unscoped `db.get(Model, id)` with tenant-scoped lookups.
- [ ] Validate customer, conversation, channel, and document foreign keys against the same business.
- [ ] Return 404 for resources owned by another tenant.
- [ ] Run API isolation and existing API tests.

### Task 4: Webhook authenticity and channel-to-tenant resolution

**Files:**
- Create: `app/tenancy/webhook_tenant.py`
- Modify: `app/api/facebook.py`
- Modify: `app/api/instagram.py`
- Modify: `app/api/shopee.py`
- Modify: `app/api/tiktok.py`
- Modify: `app/services/message_service.py`
- Test: `tests/test_webhook_tenant_resolution.py`

- [ ] Write failing tests for invalid signatures/tokens, unknown channel accounts, and payloads that attempt to override `business_id`.
- [ ] Verify the tests fail.
- [ ] Verify provider authenticity first, resolve `Channel` by provider and external account, and derive `business_id` only from that row.
- [ ] Pass the resolved business ID into message processing and background auto-reply work.
- [ ] Return a safe 401/404 response for invalid or unknown webhook tenants.
- [ ] Run webhook contract, identity, and isolation tests.

### Task 5: OAuth state, background jobs, and auto-reply

**Files:**
- Modify: `app/api/meta_oauth.py`
- Modify: `app/services/auto_reply_service.py`
- Modify: background task call sites
- Test: `tests/test_oauth_and_job_tenant.py`

- [ ] Write failing tests for forged OAuth state, replayed state, and jobs missing `business_id`.
- [ ] Implement signed/opaque single-use OAuth state containing the intended tenant; validate it on callback.
- [ ] Add required `business_id` parameters to auto-reply/background job entry points and reject absent values.
- [ ] Ensure outbound recipient lookup and settings lookup are tenant-scoped.
- [ ] Run OAuth and job tests.

### Task 6: RAG/vector tenant scope and final regression

**Files:**
- Modify: `app/api/chat.py`
- Modify: RAG retrieval/service modules
- Modify: document query paths
- Test: `tests/test_rag_tenant_isolation.py`

- [ ] Write failing tests showing vector/text retrieval from tenant A never returns tenant B documents/chunks.
- [ ] Add mandatory `business_id` filters through document joins for vector and lexical retrieval.
- [ ] Reject chat/RAG requests without tenant context.
- [ ] Run all tenant, identity, channel-contract, and available API tests; run compile and `git diff --check`.

