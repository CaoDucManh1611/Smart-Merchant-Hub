# Customer Care and Logistics Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make customer-care actions complete and add tenant-safe logistics metadata without creating a standalone delivery module.

**Architecture:** Reuse the existing bot takeover, ticket, assignment, follow-up, CSAT, and timeline systems. Add three nullable order fields (`shipping_provider`, `tracking_code`, `shipping_status`) and a dedicated update endpoint that records an order event and audit entry.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Vue 3, Node test runner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-crm-completion-followups-design.md`

## Global Constraints

- No carrier booking, label generation, price calculation, or outbound webhook is added.
- Every logistics read/write filters by `business_id`.
- Tracking codes may be shown to shop staff but never placed in public audit metadata.
- Existing sales order lifecycle transitions remain the source of truth.

---

### Task 1: Add order logistics fields and migration

**Files:**
- Modify: `backend/app/models/sales.py`
- Modify: `backend/app/schemas/sales.py`
- Modify: `backend/app/api/sales.py`
- Create: `backend/alembic/versions/20260911_0037_order_logistics_metadata.py`
- Modify: `backend/app/database/init_db.py`
- Test: `backend/tests/test_order_logistics_api.py`

- [ ] **Step 1: Write failing tests** for tenant-safe update, allowed statuses, missing order, and response fields.
- [ ] **Step 2: Run the focused test and confirm missing columns/route failures.**
- [ ] **Step 3: Add nullable columns and `OrderLogisticsUpdate`/`OrderLogisticsOut` schemas with statuses `pending`, `in_transit`, `delivered`, `failed`, `returned`.**
- [ ] **Step 4: Add `PATCH /api/orders/{order_id}/logistics`, create an `OrderEvent`, and record a redacted audit entry.**
- [ ] **Step 5: Add repeatable SQLite/PostgreSQL-compatible migration guards and direct-create compatibility.**
- [ ] **Step 6: Run focused order tests and migration-chain tests.**

### Task 2: Add customer-care quick actions

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Modify: `frontend/tests/crm-shell.test.mjs`

- [ ] **Step 1: Add static source tests for ticket, note, assignment, takeover, and follow-up quick actions.**
- [ ] **Step 2: Add a compact Customer 360 action bar that uses existing API methods and displays loading/error state.**
- [ ] **Step 3: Add a logistics summary card to the order details view with provider/tracking/status and an update form.**
- [ ] **Step 4: Verify the actions stay inside the selected customer/order context and remain usable on narrow screens.**
- [ ] **Step 5: Run all frontend tests and build.**

### Task 3: Verify care workflows

**Files:**
- Test: `backend/tests/test_customer_care_workflow.py`
- Modify: `backend/tests/test_chatbot_runtime_api.py`

- [ ] **Step 1: Cover complaint → urgent ticket → bot pause → assignment.**
- [ ] **Step 2: Cover resolved ticket → CSAT/follow-up scheduling and idempotency.**
- [ ] **Step 3: Cover timeline actor labels for customer, bot, employee, and system.**
- [ ] **Step 4: Run focused workflow, timeline, and follow-up tests.**
