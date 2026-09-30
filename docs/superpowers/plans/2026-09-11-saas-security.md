# SaaS Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a tenant-safe SaaS control plane, quota enforcement, platform administration, session/MFA preparation, customer data lifecycle controls, and a schema-per-tenant migration registry without moving the demo's existing CRM rows.

**Architecture:** Keep the current PostgreSQL database and `business_id` tenant boundary for the demo. Reuse `ServicePlan`, `Subscription`, `Payment`, `AuthSession`, encrypted channel credentials, and redacted `AuditLog`; add additive SaaS control tables and a centralized quota service. Expose platform-only APIs behind an explicit platform membership and keep schema-per-tenant behind an off-by-default registry/feature flag.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite test fixtures, Pydantic, Vue 3/Vite, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-11-saas-security-design.md`

## Global Constraints

- Every shop-owned query and mutation must include `business_id`.
- Do not move existing CRM rows or change the default PostgreSQL `search_path`.
- Do not store raw channel tokens, MFA secrets, passwords, OTP values, customer message bodies, or export bodies in audit logs.
- Outbound webhooks and setup wizard are not part of this workstream.
- Keep current development header compatibility and enforce bearer/platform checks when a session is supplied.
- Keep changes uncommitted until the complete workstream is verified.

---

### Task 1: Add SaaS control-plane models and migration

**Files:**
- Create: `backend/app/models/saas.py`
- Modify: `backend/app/models/business.py`
- Modify: `backend/app/models/auth_session.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database/init_db.py`
- Create: `backend/alembic/versions/20260911_0036_saas_security.py`
- Test: `backend/tests/test_saas_models.py`

**Interfaces:**
- `SaaSUsage(business_id, resource, period_start, used, updated_at)` has a unique key on business/resource/period.
- `PlatformMembership(user_id, is_active, created_at)` identifies platform administrators independently from `X-Business-Id`.
- `DataLifecycleRequest(business_id, request_key, kind, status, requested_by, result_metadata, created_at, completed_at)` is idempotent per tenant/request key.
- `TenantSchemaRegistry(business_id, schema_name, state, feature_enabled, created_at, updated_at)` stores only the future schema mapping.
- `ServicePlan` gains `max_rag_chunks`, `max_ai_calls`, and `max_ai_cost` with safe defaults.
- `AuthSession` gains nullable `device_label`, `user_agent_hash`, `ip_hash`, `last_seen_at`, and `mfa_verified`.

- [ ] **Step 1: Write failing model tests.**

Create `tests/test_saas_models.py` that creates two businesses, two plans, usage rows, a platform membership, a data request, and two schema registry rows. Assert the usage unique constraint rejects a duplicate period/resource, limits are persisted, and tenant/request keys are independent.

- [ ] **Step 2: Run the model tests and confirm the expected missing-model failure.**

Run from `backend`:

```powershell
$env:PYTHONPATH=(Resolve-Path .migrationdeps).Path
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_saas_models.py -q
```

Expected: collection or attribute failures because the SaaS models and new columns do not exist yet.

- [ ] **Step 3: Implement the models and register them.**

Use SQLAlchemy models with foreign keys to `businesses` and `users`, a unique constraint on `(business_id, resource, period_start)`, a unique constraint on `(business_id, request_key)`, and a safe schema-name validator that only accepts `tenant_<integer>` names. Add all imports to `models/__init__.py` and `init_db.py` so legacy `create_all()` databases register the tables.

- [ ] **Step 4: Add the repeatable Alembic migration.**

Create revision `20260911_0036` with `down_revision = "20260909_0035"`. Add the four tables, nullable auth-session columns, and the three service-plan columns with inspector guards. Do not alter CRM rows or set a tenant search path. Register the migration in the Alembic chain test.

- [ ] **Step 5: Run the model and migration tests.**

Run the focused test again and `pytest tests/test_alembic_chain.py -q`; expected result is all green.

---

### Task 2: Implement centralized quota accounting and enforcement

**Files:**
- Create: `backend/app/services/quota_service.py`
- Modify: `backend/app/api/team.py`
- Modify: `backend/app/services/channel_service.py`
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/api/chatbot.py`
- Create: `backend/tests/test_quota_service.py`
- Modify: `backend/tests/test_chatbot_runtime_api.py`

**Interfaces:**
- `QuotaResource = Literal["staff_users", "connected_channels", "documents", "rag_chunks", "ai_calls", "ai_cost"]`.
- `check_quota(db, business_id, resource, requested=1, *, idempotency_key=None) -> QuotaDecision` reads the active subscription and current UTC period without mutating usage.
- `reserve_quota(db, business_id, resource, requested=1, *, idempotency_key=None) -> QuotaDecision` locks/updates one usage row atomically and raises `QuotaExceededError` with `resource`, `used`, `limit`, `requested`, and `period_start`.
- `record_quota_usage(...)` is idempotent for an operation key and supports AI cost as a decimal.

- [ ] **Step 1: Write failing quota tests.**

Cover a plan with limits of one staff user, one channel, one document, two chunks, two AI calls, and cost `10.00`; assert the first reservation succeeds, the next reservation raises the structured error, a new UTC period starts at zero, and repeating an idempotency key does not double-count.

- [ ] **Step 2: Run the quota tests and confirm they fail for missing service behavior.**

Run `pytest tests/test_quota_service.py -q`; expected: import/attribute failures before implementation.

- [ ] **Step 3: Implement quota calculation and stable API error mapping.**

Resolve the latest active subscription by `business_id`, map plan columns to resource keys, create the current-period row when absent, and use `with_for_update()` where supported. Raise a small domain exception that API routes translate to HTTP 429 with detail code `quota_exceeded`. Missing/inactive subscriptions deny only new billable writes.

- [ ] **Step 4: Add the mutation hooks.**

Call `reserve_quota(..., "staff_users")` before `team.create_team_member` commits; reserve a new `connected_channels` slot only when an active channel is not already present; reserve `documents` before `Document` creation and `rag_chunks` when ingestion reports its final chunk count; reserve/record `ai_calls` and `ai_cost` at the chatbot runtime boundary. Roll back quota reservations with the surrounding transaction on mutation failure.

- [ ] **Step 5: Run focused commerce, RAG, and quota tests.**

Run `pytest tests/test_quota_service.py tests/test_chatbot_runtime_api.py tests/test_customer_collection_flow.py -q`; expected: all green.

---

### Task 3: Add platform-admin shop lifecycle and usage APIs

**Files:**
- Create: `backend/app/auth/platform.py`
- Create: `backend/app/api/platform.py`
- Create: `backend/app/schemas/platform.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_platform_api.py`

**Interfaces:**
- `require_platform_admin` checks an active `PlatformMembership` for the bearer user and never trusts `X-Business-Id`.
- `GET /api/platform/shops` returns shop status, active plan, and current usage summary.
- `PATCH /api/platform/shops/{business_id}/status` accepts `active` or `suspended` and records a redacted audit event.
- `GET /api/platform/shops/{business_id}/usage` returns all quota resources for the current period.
- `GET /api/platform/audit-logs` returns filtered platform security events without message content or secrets.

- [ ] **Step 1: Write failing platform isolation tests.**

Create a shop owner, an ordinary agent, and a platform member. Assert the platform member can list and suspend a shop, the ordinary agent receives 403, a shop bearer cannot access another shop's data through a supplied header, and suspension creates one audit row.

- [ ] **Step 2: Run the tests and confirm missing-route/dependency failures.**

Run `pytest tests/test_platform_api.py -q`; expected: 404/import failures.

- [ ] **Step 3: Implement the dependency, schemas, and routes.**

Use a platform membership query scoped to `user.id` and `is_active`; query shops without using the request tenant header; validate status transitions; return 423 for suspended-shop writes and 403 for non-platform callers. Reuse `record_audit` with counts/status only.

- [ ] **Step 4: Register the router and run the focused tests.**

Run `pytest tests/test_platform_api.py tests/test_api_tenant_isolation.py -q`; expected: all green.

---

### Task 4: Harden sessions and prepare MFA

**Files:**
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/auth/dependencies.py`
- Create: `backend/app/services/mfa_service.py`
- Modify: `backend/app/schemas/auth.py`
- Create: `backend/tests/test_auth_security_controls.py`

**Interfaces:**
- Login records hashed user-agent/IP and a caller-provided device label without logging raw values.
- `GET /api/auth/sessions` lists only the current user's non-secret device metadata.
- `POST /api/auth/sessions/{session_id}/revoke` revokes one session owned by the current user and audits it.
- `POST /api/auth/mfa/prepare` creates an encrypted enrollment secret and returns a one-time provisioning payload plus `status="prepared"`.
- `POST /api/auth/mfa/disable` clears the encrypted enrollment secret after admin confirmation and audits it.

- [ ] **Step 1: Write failing auth-control tests.**

Assert login stores only hashes, another user cannot revoke the session, the owner can revoke it and subsequent bearer access returns 401, MFA preparation never returns the stored encrypted value, and audit metadata contains no token/secret/body key.

- [ ] **Step 2: Run the tests to confirm missing endpoints/fields.**

Run `pytest tests/test_auth_security_controls.py -q`; expected: failures before implementation.

- [ ] **Step 3: Implement session metadata and MFA preparation.**

Use SHA-256 for device/IP metadata, keep the existing bearer token hash flow, encrypt MFA enrollment material with the configured channel-encryption primitive, and expose only a one-time provisioning string. Keep enforcement disabled but explicit in the response until a future provider-backed TOTP verifier is enabled.

- [ ] **Step 4: Run auth, tenant, and audit tests.**

Run `pytest tests/test_auth_security_controls.py tests/test_auth_api.py tests/test_webhook_oauth_security.py -q`; expected: all green.

---

### Task 5: Add customer export, anonymization, and deletion requests

**Files:**
- Create: `backend/app/api/privacy.py`
- Create: `backend/app/services/privacy_service.py`
- Create: `backend/app/schemas/privacy.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_privacy_api.py`

**Interfaces:**
- `POST /api/privacy/export` creates an idempotent tenant request and returns request status plus an allow-listed JSON download payload for the demo.
- `POST /api/privacy/anonymize` replaces direct customer identifiers with deterministic placeholders while preserving aggregate/reporting rows.
- `POST /api/privacy/delete` requires an explicit confirmation token, deletes only tenant-owned customer/identity/contact/address/conversation content, and returns row counts.
- All three actions require admin/write access, are tenant-scoped, and audit only counts/status.

- [ ] **Step 1: Write failing privacy tests.**

Create two tenants with customers and messages. Assert export includes only the requesting tenant and approved fields, anonymization preserves the other tenant and removes direct identifiers, deletion requires the confirmation token and is idempotent, and no audit metadata contains message bodies or email/phone values.

- [ ] **Step 2: Run the tests and confirm missing-route/service failures.**

Run `pytest tests/test_privacy_api.py -q`; expected: 404/import failures.

- [ ] **Step 3: Implement allow-listed lifecycle operations.**

Use a `DataLifecycleRequest` row keyed by `(business_id, request_key)`, serialize export data only in the response for the demo, anonymize with a stable per-request salt, and delete rows through tenant-filtered queries in one transaction. Never delete shared products, plans, audit infrastructure, or another tenant's rows.

- [ ] **Step 4: Run privacy and tenant-isolation tests.**

Run `pytest tests/test_privacy_api.py tests/test_customer_360_api.py tests/test_api_tenant_isolation.py -q`; expected: all green.

---

### Task 6: Add schema registry, operational policy, and security UI

**Files:**
- Create: `backend/app/services/schema_registry.py`
- Create: `backend/app/api/schema_registry.py`
- Modify: `backend/app/api/router.py`
- Modify: `docs/production-security-runbook.md`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Create: `frontend/tests/saas-security-ui.test.mjs`

**Interfaces:**
- `register_tenant_schema(db, business_id) -> TenantSchemaRegistry` validates and records `tenant_<business_id>` without creating tables or moving data.
- `GET /api/platform/schema-registry` is platform-admin only and returns state/feature flag, never arbitrary SQL.
- The UI renders Platform Admin only for platform users, with shop status, plan/quota bars, session controls, MFA prepared state, and privacy actions; secrets and raw customer content are never shown.

- [ ] **Step 1: Write failing registry/UI tests.**

Assert safe names are accepted, arbitrary names are rejected, registry creation has no effect on existing CRM queries, and the UI hides platform controls for ordinary shop users while rendering quota/status controls for a platform user.

- [ ] **Step 2: Implement registry helper, endpoint, and UI.**

Keep registry creation additive and feature-disabled by default. Add a compact settings panel that calls the new platform/privacy/session endpoints through the existing `apiFetch` helper and shows explicit loading/error states.

- [ ] **Step 3: Document production operations.**

Add backup cadence, retention, restore drill, secret rotation, rate-limit backend, and health-check verification steps to `docs/production-security-runbook.md`, clearly labeling local demo behavior versus production requirements.

- [ ] **Step 4: Run frontend tests and build.**

Run from `frontend`:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --test tests/*.test.mjs
& .\node_modules\.bin\vite.cmd build
```

Expected: all frontend tests pass and Vite exits 0.

---

### Task 7: Full verification and handoff

**Files:**
- Modify only files identified by failing tests or review; do not rewrite unrelated CRM behavior.

- [ ] **Step 1: Run the complete backend suite except the environment-blocked security test.**

Run `pytest tests --ignore=tests/test_security_hardening.py`; expected: zero failures. Run the security test separately and record the missing dependency if `uvicorn` is unavailable.

- [ ] **Step 2: Run frontend tests, build, and `git diff --check`.**

Expected: all Node tests pass, Vite exits 0, and `git diff --check` emits no whitespace errors.

- [ ] **Step 3: Verify Alembic state and inspect the final diff.**

Run `alembic heads`, inspect `git status`, confirm the new revision is `20260911_0036`, and ensure `ngrok.exe` remains ignored. Do not run destructive reset/checkout operations.

- [ ] **Step 4: Report remaining environment-only checks.**

Document that live Docker migration, provider webhook smoke tests, backup/restore drills, and production rate-limit storage require the user's machine/infrastructure. Keep all implementation changes uncommitted until the user explicitly asks for a final commit/push.
