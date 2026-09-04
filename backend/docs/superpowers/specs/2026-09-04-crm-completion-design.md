# CRM Completion Design

**Date:** 2026-09-04  
**Scope:** Complete the CRM capabilities requested for the Smart Merchant Hub without removing existing tenant data or changing the working Facebook, Instagram, Telegram, and Zalo Bot flows.

## Goal

Deliver a production-shaped CRM in five independently testable waves: a complete Customer 360 and order domain, real authentication and authorization, operational reports and workflows, reliable RAG operations, and finally recommendation/ML experimentation primitives.

## Current baseline

The repository already contains tenant-scoped conversations, customer identities, notes, customer facts, customer-level tag tables/API, products, customer sales orders, leads, tickets with comments/history/SLA fields, basic workflows, reports, document ingestion/RAG, and outbound messaging for the currently connected channels. Shopee and TikTok webhook modules are still ingestion stubs. The existing `User` table has a role label but no authentication or permission enforcement.

## Architecture

Keep the existing FastAPI + SQLAlchemy + PostgreSQL/pgvector + Vue architecture. Every new table and query remains tenant-scoped by `business_id`; referenced customers, conversations, products, users, and orders must be validated against the same tenant before writes. Additive Alembic migrations are used for all schema changes. API contracts are represented by Pydantic schemas, and the Vue app consumes those contracts through the existing tenant-aware fetch helper.

The implementation is split into independently deployable waves:

1. **CRM core:** customer deduplication/merge workflow, tag management and segment filters, a timeline that includes messages, notes, leads, orders, tickets, and assignments, Purchase Orders, and lifecycle/status transitions for both sales and purchase orders.
2. **Security and operations:** password/session authentication, role-based permissions enforced at API boundaries, audit log records for mutations, report filters/series/export, and workflow scheduling/retry/notification history.
3. **AI reliability and experimentation:** RAG provider/quota resilience and indexing observability, rule recommendations, supervised-training datasets, A/B experiments, and contextual-bandit event/reward storage.

## Customer 360

- Add an explicit customer merge preview and confirm endpoint. The survivor keeps its ID; identities, messages, notes, facts, tags, leads, tickets, and orders are reassigned inside one transaction. The merge is append-only audited and reversible through a recorded merge map until dependent references are changed again.
- Add customer tag create/list/remove operations to the Vue profile panel and a customer list filter by one or more tag IDs. Tags remain tenant-owned and customer-owned; conversation tags are retained only for backwards compatibility.
- Expand `/api/customers/{id}/timeline` to return one ordered event contract for messages, notes, leads, sales orders, purchase orders, tickets, comments, assignments, and merge events. Each event contains a stable `event_type`, source ID, timestamp, channel when applicable, and concise content/metadata.

## Orders

- Keep the current `orders` table as `SalesOrder` for end-customer purchases.
- Add tenant-scoped `purchase_orders`, `purchase_order_items`, and supplier fields. A purchase order records the shop's purchase of a service/chatbot plan or other supplier item; it is not mixed with an end-customer sale.
- Both order types expose explicit status transitions (`draft`, `confirmed`, `paid`, `processing`, `completed`, `cancelled`, `refunded` where applicable), immutable totals after confirmation, notes, and source attribution. Invalid transitions return 409 and do not partially write.
- Reports distinguish sales revenue from purchase spend and never count purchase orders as customer conversion revenue.

## Authentication, permissions, and audit

- Add a password-hash column/use the existing `password_hash`, session or short-lived bearer tokens, login/logout endpoints, and a current-user dependency. No password or token is returned by any response.
- Define `admin`, `agent`, and `viewer` permissions. Enforce read/write rules at API boundaries, with tenant resolution taking the authenticated user over the development header. Webhooks continue to authenticate with channel secrets.
- Add an append-only `audit_logs` table recording actor, tenant, action, resource, resource ID, request ID, timestamp, and redacted before/after metadata. Secrets and message content are excluded by default.

## Reports and workflows

- Reports accept validated date range, channel, status, and assignee filters; return summary cards plus time-series and channel/agent breakdowns. Add CSV export with the same filter contract.
- Workflows retain existing event/action contracts and add optional delay, retry count, scheduled execution, and run outcome/error details. Scheduled work is idempotent by workflow/event key. Notifications are persisted first and delivered through a pluggable notifier.

## RAG reliability

- Preserve lexical retrieval when embeddings fail. Make provider, model, vector dimension, quota state, retry-after, and last indexing error visible per document/run.
- Add an explicit reindex action, bounded backoff, and a no-context guard that prevents auto-reply. Store retrieval source IDs with generated replies for traceability.
- Keep 3,072-dimensional embeddings supported by exact scan; never create an incompatible HNSW index.

## Recommendation and ML primitives

- Rule recommendations start as explainable, human-confirmed suggestions based on event counts and outcomes; no automatic production action is taken without confirmation.
- Store versioned feature snapshots/labels for supervised training, experiment assignments and outcomes for A/B tests, and contextual-bandit decisions/rewards with tenant and policy version. These are data/measurement primitives first; model training and policy promotion are later controlled steps.

## Error handling and compatibility

- Return 401 for missing/invalid authentication, 403 for insufficient permission, 404 for cross-tenant or missing resources, 409 for invalid state transitions/merge conflicts, and 422 for malformed payloads.
- Preserve existing response fields and legacy `messages.media_*` mirrors while adding new fields. Existing channel credentials remain encrypted and are never sent to the browser.
- All background tasks carry `business_id`, are idempotent, and log failures without causing webhook retries for unrelated work.

## Testing and acceptance

- Every wave begins with failing unit/API tests, then implementation, then focused and full regression runs.
- Acceptance requires tenant-isolation tests for every new read/write, transition and merge tests, auth/permission/audit tests, filtered report/export tests, workflow idempotency tests, RAG quota/fallback tests, and data-contract tests for recommendation/experiment events.
- The existing frontend media regression tests and all current backend channel tests must remain green.
