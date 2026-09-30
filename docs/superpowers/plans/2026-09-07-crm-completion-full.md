# CRM Completion Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining live CRM gaps so AI Rule Lab, multi-channel avatars, durable RAG operations, CRM write flows, and CI/CD are usable and verifiable on `crm-completion`.

**Architecture:** Preserve the existing tenant-scoped FastAPI/Vue contracts. Add provider-specific Zalo profile enrichment behind the existing customer-profile resolver, make AI/RAG migrations and failures observable, and verify write flows through API tests plus read-only UI smoke checks. Keep existing compatibility fields and do not add food-specific branding.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, Vue 3/Vite, Node test runner, pytest, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-07-crm-completion-gaps-design.md`

## Global Constraints

- Every new read/write is tenant-scoped by `business_id`.
- Existing endpoint response fields and development-header authentication remain backward compatible.
- Provider credentials and message bodies never appear in job errors or browser URLs.
- New behavior is introduced test-first: a focused failing test is observed before implementation.
- Do not commit or push unless the user explicitly requests it.

---

### Task 1: Make AI Rule Lab production-safe

**Files:**
- Modify: `backend/app/api/experimentation.py` for safe error responses and lifecycle contracts.
- Modify: `backend/app/models/experimentation.py` and the next Alembic migration only if schema drift is found.
- Modify: `frontend/src/App.vue` for actionable AI load/error states.
- Test: `backend/tests/test_ai_measurement_api.py`, `frontend/tests/crm-shell.test.mjs`.

**Interfaces:**
- Keep `GET /api/experiments`, `GET /api/experiments/rule-suggestions`, review, convert and rollback routes unchanged.
- Errors must expose a safe detail string and never a raw SQL/provider secret.

- [ ] **Step 1: Write the failing regression test** asserting the experimentation router can list suggestions and experiments after an Alembic-created schema is present, and that the frontend renders a migration/action hint for a failed load.
- [ ] **Step 2: Run the focused tests and observe the expected failure** with the current missing-live-schema/opaque-error behavior.
- [ ] **Step 3: Implement the minimal fix**: ensure the migration chain creates every experimentation table, wrap unexpected database failures in safe HTTP 503 details, and show a retry/migration hint in the UI.
- [ ] **Step 4: Run focused backend and frontend tests and verify they pass.**
- [ ] **Step 5: Run a live smoke request for both experimentation GET endpoints after `alembic upgrade head`.**

### Task 2: Complete Zalo avatar persistence and display

**Files:**
- Modify: `backend/app/integrations/zalo.py` with a provider profile lookup using the active bot token when webhook payloads omit `avatar_url`.
- Modify: `backend/app/services/message_service.py` and `backend/app/services/customer_profile.py` to persist the returned URL/proxy safely.
- Create or modify: `backend/app/api/customer_avatar.py` for a tenant-signed Zalo proxy route if the provider URL is token-bound.
- Test: `backend/tests/test_zalo_adapter.py`, `backend/tests/test_customer_avatar.py`, `backend/tests/test_media_persistence.py`.
- Modify: `frontend/src/App.vue` only if the existing avatar fallback prevents rendering a persisted Zalo URL.

**Interfaces:**
- Inbound Zalo processing remains non-blocking if the profile endpoint is unavailable.
- `Customer.avatar_url` remains a browser-loadable URL or `null`; no bot token is persisted.

- [ ] **Step 1: Add failing adapter/service tests** for a Zalo webhook without an avatar and a mocked profile response containing a public avatar URL.
- [ ] **Step 2: Run those tests and confirm they fail because no enrichment occurs.**
- [ ] **Step 3: Implement profile enrichment with timeout/error isolation and tenant-safe persistence.**
- [ ] **Step 4: Run the focused avatar/Zalo tests and confirm pass, including the no-token and provider-failure cases.**
- [ ] **Step 5: Refresh the live Inbox and verify the Zalo row and header render an image when provider data exists; otherwise show the documented fallback.**

### Task 3: Finish durable RAG reindex status

**Files:**
- Modify: `backend/app/api/documents.py`, `backend/app/services/job_service.py`, and `backend/app/models/rag_run.py` only where status/retry transitions are incomplete.
- Modify: `frontend/src/App.vue` to display queued/running/failed/completed states and a retry action.
- Test: `backend/tests/test_rag_operations.py`, `backend/tests/test_crm_jobs.py`, `frontend/tests/crm-shell.test.mjs`.

**Interfaces:**
- Existing upload, list, chunk, reindex, and dispatch endpoints remain compatible.
- Legacy documents without `source_bytes` return 409 with the existing Vietnamese explanation.

- [ ] **Step 1: Add failing tests for a queued reindex run, successful dispatch, retry after sanitized failure, and the legacy-source 409.**
- [ ] **Step 2: Run focused tests and verify the missing transitions fail.**
- [ ] **Step 3: Implement minimal status polling/retry behavior and preserve the JSONL diagnostic sink.**
- [ ] **Step 4: Run focused backend/frontend tests and verify pass.**
- [ ] **Step 5: Reindex a newly uploaded test document in the UI and confirm its run status reaches completed.**

### Task 4: Verify CRM write flows end-to-end

**Files:**
- Test: `backend/tests/test_lead_pipeline_api.py`, `backend/tests/test_ticket_sla_api.py`, `backend/tests/test_customer_merge_api.py`, `backend/tests/test_order_payments.py`, `backend/tests/test_permissions_api.py`.
- Modify: the smallest affected API/schema file only when a focused regression test identifies a real gap.
- Modify: `frontend/src/App.vue` only for missing loading/conflict/empty feedback discovered by the tests.

**Interfaces:**
- Lead conversion is idempotent and returns 409 on duplicate conversion.
- Merge/undo stays tenant-scoped and audited.
- Payment/refund and ticket/workflow transitions preserve existing status semantics.

- [ ] **Step 1: Add or tighten focused API tests for create → transition → history on lead, ticket, order, workflow, merge/undo, and permission deny-overrides-grant.**
- [ ] **Step 2: Run each focused test group and record any actual failures.**
- [ ] **Step 3: Fix one root cause at a time, adding no unrelated refactors.**
- [ ] **Step 4: Run the full backend suite and frontend suite.**
- [ ] **Step 5: Use the live UI to exercise only seeded/test records and confirm histories, errors, and empty states render correctly.**

### Task 5: Enforce CI/CD gates

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/cd.yml`, `docker-compose.yml`.
- Create or modify: `scripts/ci-smoke.ps1`.
- Test: workflow YAML parsing and the local smoke script.

**Interfaces:**
- CI runs backend pytest, frontend tests/build, compileall, Alembic upgrade/current, Docker builds, and health smoke checks.
- CD uses immutable SHA tags, migrates before rollout, checks backend/frontend readiness, and never promotes `latest` after a failed check.

- [ ] **Step 1: Add a failing local smoke assertion for migration/current, backend health, frontend readiness, and test/build exit codes.**
- [ ] **Step 2: Run it and observe failure on any missing command or stale schema.**
- [ ] **Step 3: Implement the minimal CI/CD/script corrections with no `continue-on-error`.**
- [ ] **Step 4: Run the complete local gate and inspect workflow diffs.**
- [ ] **Step 5: Run `git diff --check`; leave changes uncommitted for the user.**

### Task 6: Final verification checklist

- [ ] Run backend full pytest and capture the exact pass/fail count.
- [ ] Run frontend `node --test tests/*.test.mjs` from `frontend`.
- [ ] Run `python -m compileall -q app alembic tests` from `backend`.
- [ ] Run Alembic upgrade/current against the running PostgreSQL service.
- [ ] Run frontend production build and Docker health smoke when Docker is available.
- [ ] Re-test AI Rule Lab, Zalo avatar, Knowledge Base reindex, and the seeded CRM write flows in the UI.
- [ ] Report remaining environmental blockers separately from code defects; do not claim completion without fresh evidence.
