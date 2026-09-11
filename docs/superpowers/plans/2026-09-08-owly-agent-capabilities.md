# Owly Agent Capabilities Implementation Plan

> **For agentic workers:** Implement this plan inline task-by-task with a test checkpoint after each task. Outbound webhooks and setup wizard are explicitly out of scope.

**Goal:** Add the highest-value Owly-inspired chatbot capabilities to Smart Merchant Hub without replacing its existing RAG, CRM, order, ticket or workflow contracts.

**Architecture:** Keep FastAPI/Vue/PostgreSQL and the current tenant boundary. Add a small deterministic tool registry that validates every action server-side, persist per-conversation bot mode and follow-up records, and reuse the existing ticket, workflow/job, product and message services. RAG auto-reply will receive bounded CRM memory and will stop when a human has taken over or the shop is outside configured business hours.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, Vue 3, Node test runner, pytest.

**Spec:** Owly README and AI Tool System concepts, adapted to Smart Merchant Hub; outbound webhooks and setup wizard remain excluded by user request.

## Global Constraints

- Every read and write is scoped by `business_id`.
- AI actions may create only draft orders and open tickets; no automatic refund, price override or destructive order transition.
- Existing RAG, collection flow, Unified Timeline, workflow and channel integrations remain backward compatible.
- Personal data remains masked in the Customer 360 UI, while server-side order processing keeps the source values.
- Every new behavior has a failing test before production code.

---

### Task 1: Durable chatbot runtime state and settings

**Files:**
- Modify: `backend/app/models/conversation.py`
- Modify: `backend/app/models/chatbot.py`
- Create: `backend/alembic/versions/20260908_0033_chatbot_runtime.py`
- Create: `backend/app/schemas/chatbot.py`
- Create: `backend/app/api/chatbot.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_chatbot_runtime_api.py`

**Produces:** Tenant-scoped chatbot config, business-hours JSON, canned-response records, and conversation `bot_mode` (`auto` or `human`) with API endpoints to pause/resume the bot.

- [x] Write failing tests for config persistence, business-hours validation, pause/resume isolation, and canned-response CRUD.
- [x] Run the focused tests and confirm they fail because the runtime endpoints/models do not exist.
- [x] Add the runtime columns/models, idempotent migration, schemas and APIs.
- [x] Run focused backend tests and confirm they pass.

### Task 2: Agent context memory and controlled tools

**Files:**
- Create: `backend/app/services/chatbot_agent.py`
- Modify: `backend/app/services/auto_reply_service.py`
- Modify: `backend/app/rag/prompt_builder.py`
- Test: `backend/tests/test_chatbot_agent_tools.py`
- Test: `backend/tests/test_auto_reply_memory.py`

**Produces:** Bounded memory containing recent messages, facts, tags and recent orders; safe tools for product lookup, stock lookup, draft-order handoff, ticket creation, tag application and human takeover. Tools validate tenant ownership and never execute a refund or destructive order transition.

- [x] Write failing tests for memory shape, product/stock lookup, ticket creation, tag application and human takeover.
- [x] Run them red.
- [x] Implement the tool registry and add memory to the auto-reply prompt.
- [x] Stop auto-reply when the conversation is human-controlled or outside hours.
- [x] Run focused backend tests green.

### Task 3: Ticket creation and routing from customer messages

**Files:**
- Modify: `backend/app/services/chatbot_agent.py`
- Modify: `backend/app/services/message_service.py`
- Modify: `backend/app/services/workflow_engine.py`
- Test: `backend/tests/test_chatbot_ticket_routing.py`

**Produces:** Deterministic escalation detection for complaints, damaged goods, refunds and explicit human requests; creates one idempotent high-priority ticket, pauses the bot, and assigns an available tenant user when a routing rule exists.

- [x] Write failing tests for complaint escalation, duplicate webhook idempotency and tenant-safe assignment.
- [x] Run them red.
- [x] Implement escalation before normal RAG, using the existing Ticket/SLA/event services.
- [x] Run focused backend tests green.

### Task 4: Business hours and canned responses in the frontend

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Create: `frontend/tests/chatbot-controls.test.mjs`

**Produces:** Settings controls for chatbot mode, business hours, canned responses and conversation takeover/resume; manual staff replies can insert canned text.

- [x] Write failing UI contract tests for the controls and pause/resume actions.
- [x] Run them red.
- [x] Add the smallest Vue controls using the Task 1 endpoints.
- [x] Run all frontend tests and build.

### Task 5: Follow-up scheduling and dispatch

**Files:**
- Create: `backend/app/models/chatbot_followup.py`
- Create: `backend/app/schemas/chatbot.py`
- Create: `backend/app/services/chatbot_followup.py`
- Modify: `backend/app/api/chatbot.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/alembic/versions/20260908_0034_chatbot_followups.py`
- Test: `backend/tests/test_chatbot_followup.py`

**Produces:** Tenant-scoped follow-up records for abandoned checkout, draft orders and post-delivery care, with idempotent scheduling, cancellation and due-job dispatch through the existing channel sender.

- [x] Write failing tests for schedule, duplicate prevention, cancellation, tenant isolation and due dispatch.
- [x] Run them red.
- [x] Implement the model, API and job-backed dispatcher.
- [x] Run focused backend tests green.

### Task 6: Full verification and handoff

**Files:**
- Modify: `README.md` with runtime endpoint and scheduler instructions.

- [x] Run focused backend tests for all new tasks.
- [x] Run the full backend test suite with the project test environment.
- [x] Run all frontend tests and a production Vite build.
- [x] Run `git diff --check` and report any unrelated pre-existing dirty files without reverting them.

### Task 7: CSAT feedback after resolution

**Files:**
- Create: `backend/app/models/customer_feedback.py`
- Create: `backend/app/services/csat_service.py`
- Create: `backend/alembic/versions/20260909_0035_customer_feedback.py`
- Modify: `backend/app/api/tickets.py`
- Modify: `backend/app/services/message_service.py`
- Modify: `backend/app/services/chatbot_followup.py`
- Modify: `backend/app/api/chatbot.py`
- Modify: `frontend/src/App.vue`

**Produces:** A one-time 1–5 survey after a ticket is resolved, persisted feedback and tenant-scoped CSAT metrics. An explicit rating is consumed before commerce/RAG intent parsing, and the CRM displays average score, satisfaction rate and bot-handled rate.

- [x] Add idempotent survey scheduling and response tests.
- [x] Trigger the survey from resolved/closed tickets and persist the response.
- [x] Expose tenant-scoped feedback metrics in the chatbot settings UI.
