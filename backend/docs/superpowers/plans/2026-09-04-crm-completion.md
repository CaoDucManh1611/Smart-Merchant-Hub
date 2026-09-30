# CRM Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Smart Merchant Hub CRM in tenant-safe waves covering Customer 360, sales and purchase orders, security, operations, RAG reliability, and measurable AI experimentation.

**Architecture:** Extend the existing FastAPI/SQLAlchemy/Vue application with additive Alembic migrations. Keep every resource tenant-scoped by `business_id`, validate all cross-resource references before writes, and preserve existing channel/media contracts. Each task has a focused API/UI test cycle before the next task begins.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL + pgvector, Pydantic, Vue 3, Node test runner, Docker Compose.

**Spec:** `backend/docs/superpowers/specs/2026-09-04-crm-completion-design.md`

## Global Constraints

- Never reset or delete the existing database as part of these changes.
- Every new table, query, background job, and event must carry `business_id` and reject cross-tenant references.
- Preserve legacy `messages.media_type`/`messages.media_url` fields and current Facebook, Instagram, Telegram, and Zalo Bot webhook contracts.
- Return 401 for missing authentication, 403 for forbidden role, 404 for missing/cross-tenant resources, 409 for invalid state transitions, and 422 for malformed payloads.
- Write the failing test before production code for every behavior change.

### Task 1: Customer merge model and tenant-safe merge API

**Files:**
- Create: `backend/app/models/customer_merge.py`
- Create: `backend/app/schemas/customer_merge.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/customers.py`
- Create: `backend/alembic/versions/20260904_0017_customer_merges.py`
- Test: `backend/tests/test_customer_merge_api.py`

**Interfaces:**
- `POST /api/customers/{customer_id}/merge-preview` accepts `{ "source_customer_id": int }` and returns survivor/source counts for identities, messages, notes, facts, tags, leads, tickets, sales orders, and purchase orders.
- `POST /api/customers/{customer_id}/merge` accepts `{ "source_customer_id": int, "reason": str | null }` and returns `{ "merge_id": int, "survivor_customer_id": int, "source_customer_id": int, "status": "completed" }`.
- `CustomerMerge` records tenant, survivor, source, actor, reason, and before/after counts; source records become inactive and all dependent rows point to survivor in one transaction.

- [ ] **Step 1: Write the failing tests** for preview counts, successful reassignment, idempotent duplicate merge rejection, and cross-tenant 404.
- [ ] **Step 2: Run `pytest tests/test_customer_merge_api.py -q`** and confirm the endpoint/model is missing.
- [ ] **Step 3: Add the merge table/model, request/response schemas, and transactional service that locks both customers, moves dependent rows, and records counts.**
- [ ] **Step 4: Wire the two customer routes and run the focused tests until all pass.**
- [ ] **Step 5: Run tenant-isolation tests and commit with `git add backend/app backend/alembic backend/tests/test_customer_merge_api.py && git commit -m "feat: add tenant-safe customer merge"`.**

### Task 2: Customer tags and segments in the UI

**Files:**
- Modify: `backend/app/api/customers.py`
- Modify: `backend/app/schemas/customer.py`
- Test: `backend/tests/test_customer_tags_api.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/customer-utils.js`
- Create: `frontend/tests/customer-segments.test.mjs`

**Interfaces:**
- `GET /api/customers?tag_ids=1,2` returns only customers carrying every requested tag.
- Existing `POST/DELETE /api/customers/{id}/tags` remain the mutation contract; the Vue profile panel adds/removes a tag and the customer list exposes a tag filter.

- [ ] **Step 1: Add failing API and utility tests** for `tag_ids` AND filtering, duplicate tag safety, removing a tag, and rendering empty tags without a blank chip.
- [ ] **Step 2: Run the focused backend and frontend tests and confirm the filter/UI behavior fails.**
- [ ] **Step 3: Implement query parsing and tenant-safe joins in `customers.py`; add profile tag controls and a filter select in `App.vue`.**
- [ ] **Step 4: Run `pytest tests/test_customer_tags_api.py -q` and `node --test frontend/tests/customer-segments.test.mjs`.**
- [ ] **Step 5: Run all existing frontend tests and commit the tag/segment slice.**

### Task 3: Complete the unified Customer 360 timeline

**Files:**
- Modify: `backend/app/api/customers.py`
- Modify: `backend/app/schemas/customer.py`
- Test: `backend/tests/test_customer_360_api.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/customer-utils.js`

**Interfaces:**
- `GET /api/customers/{id}/timeline` returns a single descending list whose `event_type` is one of `message`, `note`, `lead`, `sales_order`, `purchase_order`, `ticket`, `ticket_comment`, `assignment`, or `customer_merge`; each item has `event_id`, `occurred_at`, `channel`, `content`, and `metadata`.

- [ ] **Step 1: Add failing fixtures/assertions for lead, order, ticket, comment, assignment, and merge events interleaved by timestamp.**
- [ ] **Step 2: Run the focused test and verify only messages/notes are returned today.**
- [ ] **Step 3: Replace the timeline assembly with tenant-scoped event queries and stable serialization; cap after sorting.**
- [ ] **Step 4: Add UI labels for each event type and run the focused and full Customer 360 tests.**
- [ ] **Step 5: Commit the unified timeline slice.**

### Task 4: Purchase Orders and order lifecycle transitions

**Files:**
- Create: `backend/app/models/purchase_order.py`
- Create: `backend/app/schemas/purchase_order.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/api/purchase_orders.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/alembic/versions/20260904_0018_purchase_orders.py`
- Modify: `backend/app/api/sales.py`
- Modify: `backend/app/schemas/sales.py`
- Test: `backend/tests/test_purchase_order_api.py`
- Test: `backend/tests/test_order_lifecycle.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`

**Interfaces:**
- `GET/POST /api/purchase-orders` and `GET/PATCH /api/purchase-orders/{id}` manage supplier, item, quantity, unit cost, total spend, notes, and status.
- `POST /api/orders/{id}/transition` and `POST /api/purchase-orders/{id}/transition` accept `{ "to_status": string }` and enforce the explicit state graph.
- Sales reports count only `orders`; spend reports count only `purchase_orders`.

- [ ] **Step 1: Write failing tests for purchase order creation, tenant-safe supplier/item validation, totals, transition conflicts, and report separation.**
- [ ] **Step 2: Run the tests and confirm missing tables/routes/transitions.**
- [ ] **Step 3: Add models, migration, schemas, API routes, transition validator, and workflow event emission.**
- [ ] **Step 4: Add a Purchase Orders UI view and lifecycle selectors; run focused tests.**
- [ ] **Step 5: Run existing sales/order/report tests and commit.**

### Task 5: Authentication, RBAC, and audit log

**Files:**
- Create: `backend/app/auth/passwords.py`
- Create: `backend/app/auth/dependencies.py`
- Create: `backend/app/api/auth.py`
- Create: `backend/app/models/audit_log.py`
- Create: `backend/app/services/audit_service.py`
- Modify: `backend/app/models/business.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/alembic/versions/20260904_0019_auth_audit.py`
- Test: `backend/tests/test_auth_api.py`
- Test: `backend/tests/test_rbac_audit.py`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- `POST /api/auth/login` accepts email/password and returns a short-lived bearer token plus safe user profile; `POST /api/auth/logout` revokes it; `GET /api/auth/me` returns the current user.
- `require_user` resolves tenant from the authenticated user; `require_permission("resource:write")` enforces admin/agent/viewer policy.
- `audit_logs` is append-only and redacts credentials, tokens, and message content.

- [ ] **Step 1: Add failing tests for login success/failure, token expiry/revocation, authenticated tenant precedence, role matrix, and redacted audit rows.**
- [ ] **Step 2: Run the tests and confirm no auth endpoints/dependencies exist.**
- [ ] **Step 3: Implement password hashing, signed session tokens, revocation storage, dependencies, and audit writes around mutation routes.**
- [ ] **Step 4: Add login state to the Vue app and hide/disable forbidden controls.**
- [ ] **Step 5: Run all API security/tenant tests and commit.**

### Task 6: Filtered reports and operational workflows

**Files:**
- Modify: `backend/app/api/reports.py`
- Modify: `backend/app/api/sales.py`
- Modify: `backend/app/schemas/*.py`
- Modify: `backend/app/models/workflow.py`
- Modify: `backend/app/services/workflow_engine.py`
- Create: `backend/app/services/notification_service.py`
- Create: `backend/app/api/notifications.py`
- Create: `backend/alembic/versions/20260904_0020_workflow_operations.py`
- Test: `backend/tests/test_reports_filters.py`
- Test: `backend/tests/test_workflow_operations.py`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Write failing tests for date/channel/status/assignee filters, CSV output, delayed workflow jobs, retries, idempotency, and persisted notifications.**
- [ ] **Step 2: Run focused tests and confirm current reports/workflows lack these fields.**
- [ ] **Step 3: Implement validated filter objects, grouped time-series queries, CSV streaming, scheduled run records, bounded retries, and notification persistence.**
- [ ] **Step 4: Add report filter controls and workflow run history in Vue.**
- [ ] **Step 5: Run full reports/workflow regression tests and commit.**

### Task 7: RAG reliability and indexing operations

**Files:**
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/rag/embedder.py`
- Modify: `backend/app/services/ingestion_service.py`
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/services/auto_reply_service.py`
- Create: `backend/alembic/versions/20260904_0021_rag_operations.py`
- Test: `backend/tests/test_rag_operations.py`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add failing tests for provider quota state, retry-after persistence, explicit reindex, source IDs on replies, and no-context auto-reply suppression.**
- [ ] **Step 2: Run the focused tests and confirm the operational fields/actions are missing.**
- [ ] **Step 3: Persist run/provider state, add bounded reindex endpoint, retain lexical fallback, and include source IDs in reply metadata.**
- [ ] **Step 4: Add status/error/reindex controls to the Knowledge Base UI.**
- [ ] **Step 5: Run the full RAG suite and commit.**

### Task 8: Recommendation, supervised data, A/B testing, and contextual bandit primitives

**Files:**
- Create: `backend/app/models/experimentation.py`
- Create: `backend/app/schemas/experimentation.py`
- Create: `backend/app/api/experimentation.py`
- Create: `backend/app/services/rule_recommendation.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/alembic/versions/20260904_0022_experimentation.py`
- Test: `backend/tests/test_experimentation_api.py`

- [ ] **Step 1: Add failing tests for explainable rule suggestions, human confirmation, versioned feature snapshots/labels, experiment assignment/outcome, and bandit decision/reward records.**
- [ ] **Step 2: Run the focused tests and confirm these resources are absent.**
- [ ] **Step 3: Implement tenant-scoped tables, contracts, and APIs; ensure suggestions never mutate production workflows without confirmation.**
- [ ] **Step 4: Add minimal UI panels for pending suggestions and experiment metrics.**
- [ ] **Step 5: Run all backend tests and commit the measurement primitives.**

## Final verification

- [ ] Run `python -m compileall -q app alembic tests` from `backend`.
- [ ] Run the complete backend pytest suite in the configured runtime.
- [ ] Run `node --test frontend/tests/*.test.mjs`.
- [ ] Build the frontend with the repository's Docker Compose build once dependencies are available.
- [ ] Apply Alembic migrations to a disposable verification database and check `alembic current` reaches the newest revision.
- [ ] Manually verify the inbox still receives/sends text and media for Facebook, Instagram, Telegram, and Zalo Bot after the migrations.
