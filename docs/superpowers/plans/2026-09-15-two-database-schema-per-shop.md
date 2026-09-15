# Two-Database, Schema-per-Shop SaaS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chuyển Smart Merchant Hub thành SaaS có một control-plane database và một tenant database, trong đó mỗi shop có schema riêng, nhân viên chỉ truy cập shop của mình, kết nối độc lập Telegram/Zalo/Facebook/Instagram và platform admin không đọc dữ liệu khách nếu không có quyền hỗ trợ tạm thời.

**Architecture:** `platform_db` giữ định danh shop, tài khoản, gói cước, quota, route webhook và audit nền tảng. `tenant_db` giữ các schema `shop_<business_id>` chứa toàn bộ dữ liệu CRM, hội thoại, bán hàng, tồn kho, kênh và RAG của từng shop. API xác thực trên platform DB, tra registry, rồi mở tenant session bằng `SET LOCAL search_path`; webhook tra route tối thiểu ở platform DB trước khi vào schema shop. Việc chuyển dữ liệu dùng copy/checksum/cutover theo từng shop, không dual-write dài hạn.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL/pgvector, Alembic, Redis worker, Vue 3/Vite, pytest, Node test runner, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-15-two-database-schema-per-shop-design.md`

## Global Constraints

- Schema chỉ được sinh ở server dưới dạng `shop_<business_id>` và phải khớp `^shop_[1-9][0-9]*$`; không nhận schema name từ request.
- Mọi tenant transaction dùng `SET LOCAL search_path TO <quoted_schema>, public`; không thay đổi search path cấp connection/session lâu dài.
- Platform DB không lưu nội dung hội thoại, khách hàng, sản phẩm, đơn hàng, tài liệu RAG hoặc token kênh. Route webhook chỉ lưu fingerprint/hash và khóa định tuyến tối thiểu.
- Token kênh được mã hóa và lưu trong schema shop. Log, metric và platform response không được chứa token, payload webhook hoặc dữ liệu khách.
- Telegram và Zalo Bot Creator dùng luồng mở trang tạo bot bằng QR/deep-link rồi dán token đúng một lần; Facebook và Instagram dùng Meta OAuth, không yêu cầu shop dán access token thủ công.
- Bốn kênh dùng chung trạng thái UI `disconnected`, `verifying`, `connected`, `reconnect_required`, `error`, nhưng giữ adapter và quyền provider riêng biệt.
- Platform admin không được dùng tenant session theo mặc định. Support session bắt buộc có grant, lý do, scope, thời hạn, người cấp và audit bất biến.
- Giữ `backend/alembic` làm legacy chain trong thời gian chuyển đổi. Tạo hai chain mới; chỉ xóa fallback ở cổng release cuối.
- Không stage/commit chung các thay đổi onboarding Telegram/Zalo hiện đang chưa commit. Mỗi task dưới đây phải có commit riêng.
- TDD bắt buộc: tạo test đỏ, xác nhận đỏ vì đúng nguyên nhân, viết tối thiểu để xanh, chạy regression liên quan rồi mới commit.

---

## Workstream A — Database boundary and control plane

### Task 1: Khóa contract cấu hình hai database

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `docker-compose.yml`
- Create: `backend/tests/test_two_database_config.py`

**Interfaces:**
- Produce `Settings.PLATFORM_DATABASE_URL: str`.
- Produce `Settings.TENANT_DATABASE_URL: str`.
- Consume legacy `DATABASE_URL` only through an explicitly named compatibility property during rollout.

- [x] Add a failing test that production rejects identical/missing platform and tenant URLs and that development can temporarily map legacy `DATABASE_URL` to both.

```python
def test_production_requires_two_database_urls():
    with pytest.raises(RuntimeError, match="PLATFORM_DATABASE_URL"):
        Settings(DATABASE_URL="postgresql://x", ENVIRONMENT="production").validate_runtime()
```

- [ ] Run `docker compose run --rm backend pytest -q tests/test_two_database_config.py` and confirm the failure is caused by missing settings.
- [x] Add the two settings plus `platform_database_url` and `tenant_database_url` compatibility properties; warn once in non-production when falling back.
- [x] Update Compose backend/worker environment and health checks to use both URLs; keep the existing PostgreSQL service for local work by creating `crm_platform` and `crm_tenant` databases in an idempotent init script.
- [x] Run the focused test, then `docker compose config`.
- [ ] Commit only these files: `git commit -m "feat: define platform and tenant database boundaries"`.

### Task 2: Tách SQLAlchemy base, engine và dependency

**Files:**
- Create: `backend/app/database/platform_session.py`
- Create: `backend/app/database/tenant_session.py`
- Create: `backend/app/database/bases.py`
- Modify: `backend/app/database/session.py`
- Modify: `backend/app/db/dependencies.py`
- Create: `backend/tests/test_database_boundaries.py`

**Interfaces:**

```python
class PlatformBase(DeclarativeBase): ...
class TenantBase(DeclarativeBase): ...

def get_platform_db() -> Iterator[Session]: ...
def tenant_session(schema_name: str) -> ContextManager[Session]: ...
```

- [x] Write tests proving platform metadata excludes `customers/messages/orders/documents` and tenant metadata excludes `businesses/subscriptions/platform_memberships/support_grants`.
- [x] Write a PostgreSQL test that two consecutive pooled tenant sessions cannot inherit one another's `search_path`.
- [ ] Run `docker compose run --rm backend pytest -q tests/test_database_boundaries.py` and confirm both tests fail.
- [x] Introduce distinct bases/engines/sessionmakers; retain `app.database.session.Base/SessionLocal` as a deprecated rollout alias only.
- [x] Implement `tenant_session` with validated schema, quoted identifier and transaction-local `set_config('search_path', ..., true)` or equivalent safe SQLAlchemy statement.
- [x] Make `get_db` a temporary alias for `get_platform_db`; new code must name its database dependency explicitly.
- [x] Run focused tests and `python -m compileall app/database app/db` inside backend container.
- [ ] Commit: `git commit -m "refactor: split platform and tenant database sessions"`.

### Task 3: Tạo control-plane models và Alembic chain

**Files:**
- Create: `backend/app/models/platform_control.py`
- Create: `backend/app/models/channel_route.py`
- Modify: `backend/app/models/business.py`
- Modify: `backend/app/models/saas.py`
- Create: `backend/alembic-platform.ini`
- Create: `backend/alembic_platform/env.py`
- Create: `backend/alembic_platform/versions/20260915_0001_platform_control_plane.py`
- Create: `backend/tests/test_platform_schema.py`

**Interfaces:**
- `TenantRegistry(business_id, schema_name, state, tenant_revision, migration_error, feature_enabled)`.
- `ChannelRoute(provider, external_account_id_hash, secret_hash, business_id, schema_name, status)`.
- `SupportGrant(business_id, granted_by_user_id, support_user_id, reason, scopes, expires_at, revoked_at)`.
- `ProvisioningOperation(idempotency_key, business_id, state, attempt_count, last_error_code)`.

- [x] Add schema tests asserting unique constraints, allowed states and absence of customer-content columns.
- [ ] Run the focused test and confirm model imports/tables are missing.
- [x] Move control-plane ownership to `PlatformBase`; do not yet move tenant models.
- [x] Implement initial platform migration for businesses, users, sessions, roles/permissions, plans, subscriptions, payments, usage/quota, registry, routes, support grants and platform audit.
- [x] Store only sanitized error codes in provisioning/platform records; detailed stack traces stay in protected operational logs.
- [x] Run `alembic -c alembic-platform.ini upgrade head` against a fresh `crm_platform_test` database and run `pytest -q tests/test_platform_schema.py`.
- [ ] Commit: `git commit -m "feat: add SaaS control-plane schema"`.

### Task 4: Tạo tenant template và migration runner

**Files:**
- Create: `backend/alembic-tenant.ini`
- Create: `backend/alembic_tenant/env.py`
- Create: `backend/alembic_tenant/versions/20260915_0001_tenant_template.py`
- Create: `backend/app/tenancy/schema.py`
- Create: `backend/app/tenancy/migration_runner.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_tenant_migration_runner.py`

**Interfaces:**

```python
def schema_name_for(business_id: int) -> str: ...
def upgrade_tenant_schema(connection: Connection, schema_name: str, revision: str = "head") -> str: ...
def current_tenant_revision(connection: Connection, schema_name: str) -> str | None: ...
```

- [x] Add failing tests for invalid identifiers, schema creation, per-schema `alembic_version`, idempotent upgrade and independent revision state.
- [ ] Run the focused test and capture the expected missing-module failure.
- [x] Classify current ORM tables into `PlatformBase` or `TenantBase`; tenant template includes channels/events, CRM, sales, inventory, workflows, tickets, notifications, lifecycle records and pgvector/RAG tables.
- [x] Implement schema translation/configuration so Alembic creates objects only inside the requested validated schema.
- [x] Create two test schemas, upgrade both, assert equal table sets and separate version rows.
- [x] Run `pytest -q tests/test_tenant_migration_runner.py tests/test_rag_tenant_isolation.py`.
- [ ] Commit: `git commit -m "feat: add versioned tenant schema template"`.

---

## Workstream B — Identity, onboarding and request routing

### Task 5: Làm onboarding thành saga có retry

**Files:**
- Create: `backend/app/tenancy/provisioning.py`
- Modify: `backend/app/api/onboarding.py`
- Modify: `backend/app/schemas/onboarding.py`
- Modify: `backend/app/services/tenant_schema_service.py`
- Modify: `backend/tests/test_onboarding_api.py`
- Create: `backend/tests/test_tenant_provisioning.py`

**Interfaces:**

```python
def provision_shop(platform_db: Session, *, business_id: int, idempotency_key: str) -> TenantRegistry: ...
POST /api/onboarding/shops/{business_id}/provision
POST /api/onboarding/shops/{business_id}/provision/retry
```

- [ ] Test state transitions `provisioning -> active` and `provisioning -> provision_failed`, duplicate idempotency keys, retry after partial schema creation and blocked use before `active`.
- [ ] Confirm focused tests fail against the current registry states `proposed/ready/disabled`.
- [ ] Implement steps: lock operation → create schema → tenant upgrade → seed minimum settings → validate revision/tables → mark active.
- [ ] Ensure rollback never deletes a schema containing data; failed provisioning is retryable and records a non-sensitive error code.
- [ ] Preserve current Telegram/Zalo onboarding edits by rebasing this task after they are committed; resolve overlapping routes with both test sets.
- [ ] Run `pytest -q tests/test_tenant_provisioning.py tests/test_onboarding_api.py`.
- [ ] Commit: `git commit -m "feat: provision shop schemas with retryable saga"`.

### Task 6: Định danh shop từ phiên đăng nhập, bỏ tenant header phía UI

**Files:**
- Modify: `backend/app/auth/dependencies.py`
- Modify: `backend/app/tenancy/context.py`
- Modify: `backend/app/tenancy/dependencies.py`
- Modify: `backend/app/api/auth.py`
- Create: `backend/tests/test_authenticated_tenant_session.py`
- Create: `frontend/src/api-client.js`
- Create: `frontend/src/auth-context.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/tests/crm-shell.test.mjs`

**Interfaces:**

```python
@dataclass(frozen=True)
class AuthenticatedTenant:
    business_id: int
    schema_name: str
    user_id: int
    role: str

def get_tenant_db(context: AuthenticatedTenant = Depends(...)) -> Iterator[Session]: ...
```

- [ ] Add backend tests: JWT business claim must match membership; suspended/unprovisioned shops fail closed; same email can log into separate shops; foreign shop IDs are ignored/rejected.
- [ ] Add frontend source-contract tests forbidding `BUSINESS_ID = "1"` and automatic `X-Business-Id` headers.
- [ ] Run both focused suites and confirm they fail for current hardcoded behavior.
- [ ] Resolve business/schema from authenticated platform membership and registry; open tenant DB only after registry is active.
- [ ] Return safe current-shop metadata from `/api/auth/me`; keep the bearer token as the only frontend tenant selector.
- [ ] Move API fetch/auth storage into the new client/context and update onboarding calls to use authenticated-shop routes rather than interpolating `BUSINESS_ID`.
- [ ] Run `pytest -q tests/test_authenticated_tenant_session.py tests/test_auth_api.py` and `node --test tests/crm-shell.test.mjs`.
- [ ] Commit: `git commit -m "feat: bind authenticated sessions to provisioned shops"`.

### Task 7: Tách platform admin khỏi shop user

**Files:**
- Modify: `backend/app/auth/platform.py`
- Modify: `backend/app/api/platform.py`
- Modify: `backend/app/schemas/platform.py`
- Create: `backend/tests/test_platform_metadata_boundary.py`

**Interfaces:**
- Platform list/detail returns business, plan, quota, billing, schema revision/state, health and timestamps only.
- It must never return customer count sampled from tenant content, names, messages, order lines, documents or channel tokens.

- [ ] Add tests that platform endpoints work when tenant DB access is denied and that response schemas reject content-bearing fields.
- [ ] Add tests that a platform token is rejected by ordinary tenant APIs.
- [ ] Run the focused test and confirm current cross-tenant shared queries violate the boundary.
- [ ] Replace platform joins to tenant tables with platform-owned aggregate counters/events written during normal tenant operations.
- [ ] Remove `set_platform_database_context` bypass and all platform use of shared-schema RLS.
- [ ] Run `pytest -q tests/test_platform_metadata_boundary.py tests/test_platform_api.py tests/test_platform_quality.py`.
- [ ] Commit: `git commit -m "fix: enforce metadata-only platform administration"`.

---

## Workstream C — Move all tenant-owned domains

### Task 8: Chuyển CRM lõi và kênh sang tenant session

**Files:**
- Modify: `backend/app/api/customers.py`
- Modify: `backend/app/api/conversations.py`
- Modify: `backend/app/api/team.py`
- Modify: `backend/app/services/channel_service.py`
- Modify: `backend/app/services/channel_event_service.py`
- Modify: `backend/app/services/message_service.py`
- Modify: `backend/app/models/customer.py`
- Modify: `backend/app/models/conversation.py`
- Modify: `backend/app/models/message.py`
- Modify: `backend/app/models/channel.py`
- Modify: `backend/tests/test_api_tenant_isolation.py`
- Modify: `backend/tests/test_tenant_scoped_queries.py`

**Interfaces:**
- Tenant repositories consume only `Session` already bound to the shop schema.
- Tenant rows no longer depend on foreign keys to platform `businesses`; `business_id` may remain as redundant audit data until Task 15.

- [ ] Extend isolation tests with identical primary keys/external IDs in two schemas and assert no cross-shop reads/writes/assignments.
- [ ] Confirm tests fail while APIs use `get_db` and explicit shared-table filters.
- [ ] Switch dependencies and services to `get_tenant_db`; remove platform joins from tenant transactions.
- [ ] Keep global uniqueness only where the provider requires it, via `ChannelRoute`; channel uniqueness inside schema is provider/account scoped locally.
- [ ] Run `pytest -q tests/test_api_tenant_isolation.py tests/test_tenant_scoped_queries.py tests/test_channel_contracts.py`.
- [ ] Commit: `git commit -m "refactor: isolate core CRM data by shop schema"`.

### Task 9: Chuyển commerce, inventory và supplier

**Files:**
- Modify: `backend/app/api/sales.py`
- Modify: `backend/app/api/inventory.py`
- Modify: `backend/app/api/suppliers.py`
- Modify: `backend/app/services/chatbot_agent.py`
- Modify: `backend/app/services/customer_collection_flow.py`
- Modify: `backend/app/services/customer_order_service.py`
- Modify: `backend/app/services/order_service.py`
- Modify: `backend/app/services/inventory_service.py`
- Modify: `backend/app/models/sales.py`
- Modify: `backend/app/models/inventory.py`
- Modify: `backend/app/models/supplier.py`
- Create: `backend/tests/test_tenant_commerce_isolation.py`

**Interfaces:**
- Product/order/inventory lookup uses schema-local IDs only.
- Idempotency keys are unique within a tenant schema and cannot resolve an object from another schema.

- [ ] Write failing tests for equal SKU/order codes in two shops, cancellation by product name within the authenticated shop, inventory reservation rollback and cross-shop order lookup denial.
- [ ] Route sales/inventory/supplier APIs and chatbot commerce services through tenant sessions.
- [ ] Remove platform DB access from price, stock, draft, OTP-confirmation and cancellation state-machine paths.
- [ ] Run `pytest -q tests/test_tenant_commerce_isolation.py tests/test_customer_order_actions.py tests/test_product_order_api.py tests/test_sales_inventory_lifecycle.py tests/test_supplier_api.py`.
- [ ] Commit: `git commit -m "refactor: isolate commerce and inventory by shop schema"`.

### Task 10: Chuyển tài liệu, RAG, AI usage và cấu hình shop

**Files:**
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/rag/retriever.py`
- Modify: `backend/app/rag/embedder.py`
- Modify: `backend/app/rag/llm_caller.py`
- Modify: `backend/app/rag/run_logger.py`
- Modify: `backend/app/services/ingestion_service.py`
- Modify: `backend/app/services/meta_config_service.py`
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/models/business_setting.py`
- Modify: `backend/tests/test_rag_tenant_isolation.py`
- Create: `backend/tests/test_tenant_provider_settings.py`

**Interfaces:**
- Knowledge documents/chunks/vector indexes and RAG run detail live inside `shop_<id>`.
- Shared LLM pool credentials may remain infrastructure secrets, but shop-specific provider/channel credentials and prompts live encrypted in tenant schema.
- Platform gets aggregated usage/cost counters, never prompt/retrieval text.

- [ ] Add failing tests for identical document IDs across shops, schema-local vector search, no global `AppSetting` fallback and sanitized platform AI aggregates.
- [ ] Move ingestion/retrieval/logging to tenant session and add schema to worker job context rather than query filters.
- [ ] Convert `RAG_AUTO_SEED` to provision-time seed per shop; prevent application startup from seeding every shop through a global session.
- [ ] Remove tenant-sensitive global settings fallback from `meta_config_service.py`; fail closed if a shop credential is absent.
- [ ] Run `pytest -q tests/test_rag_tenant_isolation.py tests/test_rag_components.py tests/test_rag_run_logger.py tests/test_tenant_provider_settings.py`.
- [ ] Commit: `git commit -m "refactor: isolate shop knowledge and AI runtime"`.

### Task 11: Chuyển workflow, ticket, notification, privacy và jobs

**Files:**
- Modify: `backend/app/api/workflows.py`
- Modify: `backend/app/api/tickets.py`
- Modify: `backend/app/api/notifications.py`
- Modify: `backend/app/api/privacy.py`
- Modify: `backend/app/services/crm_job_worker.py`
- Modify: `backend/app/scripts/crm_job_worker.py`
- Modify: `backend/app/models/crm_job.py`
- Modify: `backend/app/models/workflow.py`
- Modify: `backend/app/models/ticket.py`
- Create: `backend/tests/test_tenant_worker_routing.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TenantJobEnvelope:
    business_id: int
    schema_name: str
    job_id: int
```

- [ ] Add tests that workers re-resolve an active registry entry from `business_id`, reject forged schema names, and cannot process a job from a disabled/migrating shop.
- [ ] Add lifecycle tests proving export/delete/anonymize affect only one schema and audit the request in the right scope.
- [ ] Move operational models/services to tenant DB; place only queue dispatch metadata required for global scheduling in platform/Redis.
- [ ] Ensure every retry restores tenant context and clears it on completion/error.
- [ ] Run `pytest -q tests/test_tenant_worker_routing.py tests/test_crm_job_worker.py tests/test_platform_quality.py`.
- [ ] Commit: `git commit -m "refactor: route tenant operations and workers by schema"`.

---

## Workstream D — Webhooks and exceptional support access

### Task 12: Kết nối và định tuyến Telegram, Zalo, Facebook, Instagram theo từng shop

**Files:**
- Create: `backend/app/tenancy/registry.py`
- Modify: `backend/app/tenancy/webhook.py`
- Modify: `backend/app/services/provider_connection.py`
- Modify: `backend/app/services/channel_service.py`
- Modify: `backend/app/services/meta_config_service.py`
- Modify: `backend/app/api/telegram.py`
- Modify: `backend/app/api/zalo.py`
- Modify: `backend/app/api/facebook.py`
- Modify: `backend/app/api/instagram.py`
- Modify: `backend/app/api/meta_oauth.py`
- Modify: `backend/app/api/shopee.py`
- Modify: `backend/app/api/tiktok.py`
- Modify: `backend/app/api/onboarding.py`
- Modify: `backend/app/schemas/onboarding.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Modify: `backend/tests/test_webhook_channel_resolution.py`
- Modify: `backend/tests/test_unified_inbox_webhooks.py`
- Modify: `backend/tests/test_onboarding_api.py`
- Modify: `backend/tests/test_meta_oauth_tenant_security.py`
- Modify: `frontend/tests/crm-shell.test.mjs`

**Interfaces:**

```python
@dataclass(frozen=True)
class WebhookRoute:
    business_id: int
    schema_name: str
    channel_id: int

def resolve_webhook_route(platform_db: Session, provider: str, route_key: str) -> WebhookRoute | None: ...
```

- `GET /api/onboarding/shops/{business_id}/channels` returns one normalized connection record per linked provider account with state `disconnected`, `verifying`, `connected`, `reconnect_required` or `error`.
- `POST /api/onboarding/shops/{business_id}/channels/verify` accepts only `telegram` or `zalo` plus a one-time token; the response never echoes that token.
- `GET /api/oauth/meta/start` and `GET /api/oauth/meta/callback` remain the Facebook/Instagram entry points and bind the OAuth state to the authenticated shop.

- [ ] Add failing contract tests for the shared four-provider connection card, normalized states, masked account details and absence of tokens in every API response.
- [ ] Add failing Telegram tests for QR/deep-link to BotFather, one-time token submission, `getMe`, generated secret, `setWebhook`, `getWebhookInfo`, reconnect and disconnect.
- [ ] Add failing Zalo tests for QR/deep-link to Bot Manager, one-time Bot Creator token submission, provider identity verification, webhook registration/status, reconnect and disconnect.
- [ ] Add failing Meta OAuth tests for CSRF-bound state, authenticated-shop binding, Page selection, Instagram Business Account discovery, required permissions, long-lived/Page token storage, webhook subscription and reconnect-required status after token expiry/revocation.
- [ ] Add failing UI tests proving Telegram/Zalo render the QR/deep-link plus token field while Facebook/Instagram render an OAuth button and never render a manual access-token input.
- [ ] Add failing routing tests for Telegram secret hash and provider account hash routing, ambiguous/no route rejection, inactive shop rejection and no scan over tenant channel tables.
- [ ] Confirm current `resolve_telegram_channel`/`resolve_zalo_channel` scans shared `Channel` rows and document the exact replacement boundary.
- [ ] Normalize provider results into one connection DTO while keeping separate Telegram, Zalo and Meta adapters; one provider failure must not alter another provider's connection.
- [ ] For Facebook, save the selected Page identity and subscribe the Page webhook; for Instagram, require a professional account linked to the selected Page and subscribe only supported messaging fields.
- [ ] During every channel connection, atomically coordinate encrypted tenant token storage and platform route creation with an idempotent operation and compensating cleanup on failure.
- [ ] Verify provider signature before persisting payload; resolve route in platform DB, then store event/content only in tenant schema.
- [ ] Store route keys as keyed HMAC hashes using a route-secret separate from `CHANNEL_ENCRYPTION_KEY`.
- [ ] Encrypt Telegram/Zalo bot tokens and Meta user/page tokens inside the shop schema; store expiry, granted scopes and provider account metadata needed for health checks without exposing secret values.
- [ ] Implement scheduled connection health checks: mark `reconnect_required` on expired/revoked Meta permission or invalid bot token; never silently switch to a global/default credential.
- [ ] Keep provider retry/idempotency keys schema-local; duplicate webhooks return success without duplicate messages/replies.
- [ ] Run all onboarding/webhook/channel tests: `pytest -q tests/test_onboarding_api.py tests/test_meta_oauth_tenant_security.py tests/test_webhook_channel_resolution.py tests/test_unified_inbox_webhooks.py tests/test_auto_reply_channels.py tests/test_channel_reliability.py tests/test_zalo_webhook.py tests/test_instagram_webhook.py tests/test_tiktok_webhook.py`.
- [ ] Run frontend contract tests: `node --test tests/crm-shell.test.mjs`.
- [ ] Commit: `git commit -m "feat: connect and route tenant-owned messaging channels"`.

### Task 13: Thêm quyền hỗ trợ tạm thời có chủ shop cấp

**Files:**
- Create: `backend/app/services/support_access.py`
- Create: `backend/app/api/support.py`
- Create: `backend/app/schemas/support.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/auth/platform.py`
- Create: `backend/tests/test_support_access.py`

**Interfaces:**
- `POST /api/support/grants` is owner-only and requires `support_user_id`, `reason`, `scopes`, `expires_at`.
- `POST /api/support/grants/{id}/revoke` is owner-only.
- `POST /api/platform/support-sessions` consumes an active grant and issues a short-lived, scope-bound token.
- Allowed scopes are an enum such as `settings:read`, `channels:diagnose`, `jobs:retry`; no implicit wildcard.

- [ ] Add failing tests for missing reason, expired/revoked grant, wrong support user, wrong scope, tenant API access without a grant and audit on allow/deny/revoke.
- [ ] Add a test proving support cannot read messages/customers/orders when grant contains only operational scopes.
- [ ] Implement owner grant/revoke in platform DB and a signed support token carrying `grant_id`, `business_id`, exact scopes and short expiry.
- [ ] Validate grant state from platform DB on every support request; open tenant session only after endpoint-level scope check.
- [ ] Record platform audit and tenant-side support activity audit without copying customer payload into platform logs.
- [ ] Run `pytest -q tests/test_support_access.py tests/test_auth_security_controls.py`.
- [ ] Commit: `git commit -m "feat: add owner-approved temporary support access"`.

---

## Workstream E — Migration, recovery and release gates

### Task 14: Viết công cụ pilot copy/checksum/cutover/rollback

**Files:**
- Create: `backend/app/services/tenant_data_migration.py`
- Create: `backend/app/scripts/migrate_tenant.py`
- Create: `backend/app/scripts/verify_tenant_migration.py`
- Create: `backend/tests/test_tenant_data_migration.py`
- Modify: `docs/runbooks/postgresql-staging.md`

**Interfaces:**

```python
def migrate_business(*, business_id: int, dry_run: bool, cutover: bool) -> MigrationReport: ...
def verify_business(*, business_id: int) -> VerificationReport: ...
def rollback_cutover(*, business_id: int, operation_id: str) -> None: ...
```

- [ ] Build fixture data covering every tenant-owned table, attachments, vectors, orders, audit records and idempotency rows.
- [ ] Add failing tests for dry-run, resumable copy, row counts, deterministic checksums, FK validation, write lock during cutover and rollback before cleanup.
- [ ] Implement per-table ordered copy from legacy shared tables filtered by `business_id`; record cursors/checksums in platform migration operation.
- [ ] Cutover sequence: mark maintenance → drain worker/webhook queue for shop → final delta copy → verify → enable registry → smoke read/write → active.
- [ ] Rollback sequence: disable new route → restore legacy feature flag → replay queued inbound events → active legacy; never delete copied schema during rollback window.
- [ ] Require manual approval between dry-run and cutover and print only counts/hashes, never content.
- [ ] Run `pytest -q tests/test_tenant_data_migration.py tests/test_legacy_channel_migration.py`.
- [ ] Commit: `git commit -m "feat: add verified per-shop migration tooling"`.

### Task 15: Backup/restore từng DB và từng shop

**Files:**
- Modify: `scripts/backup-verify.ps1`
- Create: `scripts/tenant-backup.ps1`
- Create: `scripts/tenant-restore-verify.ps1`
- Modify: `backend/tests/test_backup_verify_script.py`
- Create: `docs/runbooks/tenant-backup-restore.md`

**Interfaces:**
- Platform backup is whole-database.
- Tenant backup accepts a validated numeric `BusinessId`, derives the schema internally and uses `pg_dump --schema`.
- Restore defaults to a new verification database/schema and refuses overwrite without an explicit switch.

- [ ] Add static tests checking `--exit-on-error`, non-zero exit propagation, non-empty archive validation, server/client version compatibility and schema derivation.
- [ ] Fix the existing false-success path: any `pg_dump` or `pg_restore` failure must terminate the PowerShell script before printing success.
- [ ] Implement separate platform and tenant backup manifests with timestamp, server version, Alembic revision, archive checksum and schema.
- [ ] Restore a tenant backup into a scratch database, run table-count/checksum queries and tenant smoke tests.
- [ ] Run `pytest -q tests/test_backup_verify_script.py` and execute the runbook against local Docker PostgreSQL 16.
- [ ] Commit: `git commit -m "ops: verify platform and per-shop backup restore"`.

### Task 16: Xóa fallback legacy và dựng release gate

**Files:**
- Modify: `backend/app/database/bootstrap.py`
- Modify: `backend/app/database/init_db.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/auth/dependencies.py`
- Modify: `backend/app/tenancy/dependencies.py`
- Modify: `backend/app/services/legacy_channel_migration.py`
- Modify: `backend/app/services/meta_config_service.py`
- Modify: `docker-compose.yml`
- Create: `backend/tests/test_no_legacy_tenant_fallback.py`
- Create: `scripts/release-smoke.ps1`
- Modify: `docs/runbooks/postgresql-staging.md`

**Interfaces:**
- Production startup accepts only two explicit DB URLs and refuses default business/global channel token/dev tenant header behavior.
- A shop is serviceable only when registry state is `active` and tenant revision equals required head.

- [ ] Add source/runtime tests forbidding `business_id=1`, default-business bootstrap, `X-Business-Id` tenant selection, nullable tenant ownership and global token/config fallbacks.
- [ ] Add a release smoke test provisioning two shops with identical customer/product/order IDs, verifying isolation across API, worker, RAG and webhooks, then deleting the fixtures.
- [ ] Confirm tests fail before removal.
- [ ] Remove startup `create_all`/auto-seed assumptions; production startup checks both DBs and migration heads without mutating schema.
- [ ] Remove legacy aliases only after every active shop has verified cutover and rollback window has elapsed.
- [ ] Add readiness output containing only DB reachability, migration compatibility, queue/provider aggregate health and tenant migration counts.
- [ ] Run the complete backend suite: `docker compose run --rm backend pytest -q`.
- [ ] Run the complete frontend suite/build: `docker compose run --rm frontend node --test tests/*.test.mjs` and `docker compose run --rm frontend npm run build`.
- [ ] Run `./scripts/release-smoke.ps1`; verify logs with a secret/PII pattern scan.
- [ ] Commit: `git commit -m "chore: enforce schema-isolated SaaS release gates"`.

---

## Rollout Checkpoints

| Checkpoint | Exit criteria | Rollback boundary |
|---|---|---|
| A — Foundation | Tasks 1–4 green; fresh platform DB and two tenant schemas migrate independently | Revert new DB config; legacy runtime remains active |
| B — New shops | Tasks 5–7 green; new shop provisions and authenticates without tenant header | Disable provisioning feature flag |
| C — Tenant runtime | Tasks 8–13 green; all tenant domains, RAG, workers and webhooks use schema sessions | Route selected shops back to legacy registry state |
| D — Pilot | Task 14 green; one non-critical shop passes checksums and smoke tests | Execute per-shop cutover rollback |
| E — Production | Tasks 15–16 green; backup restore proven and no legacy fallback remains | Restore database backups and last known compatible release |

## Mandatory Final Verification

- [ ] Run `rg -n "BUSINESS_ID =|X-Business-Id|business_id\s*=\s*1|ensure_default_business|set_platform_database_context" backend frontend` and justify every remaining match; production paths must have none.
- [ ] Run `rg -n "FACEBOOK_PAGE_ACCESS_TOKEN|INSTAGRAM_ACCESS_TOKEN|AppSetting" backend/app` and verify no tenant credential fallback remains.
- [ ] Scan this plan for unfinished placeholders or vague implementation steps; expected result is empty.
- [ ] Run `git diff --check` and confirm no whitespace errors.
- [ ] Verify an operator with platform-admin credentials cannot query tenant tables directly through any API.
- [ ] Verify an expired support grant immediately loses access, even if its signed support token has not yet expired.
- [ ] Restore both databases plus one single-shop schema into clean PostgreSQL 16 and run the release smoke test.

## Definition of Done

- Hai shop có thể dùng cùng email nhân viên, SKU, external customer ID và order code mà không xung đột hoặc nhìn thấy nhau.
- Platform admin quản lý lifecycle/gói/quota/billing/health nhưng không thấy dữ liệu khách.
- Support chỉ truy cập đúng shop, đúng scope và đúng thời hạn do owner cấp, có audit đầy đủ.
- Webhook không scan schema, không đoán tenant và không dùng token mặc định.
- Mỗi shop kết nối độc lập Telegram/Zalo bằng token một lần và Facebook/Instagram bằng Meta OAuth; UI hiển thị đúng trạng thái, tài khoản provider và yêu cầu kết nối lại mà không lộ token.
- Mỗi shop có thể migrate, backup, restore và rollback độc lập.
- Toàn bộ backend tests, frontend tests/build và release smoke test xanh trên PostgreSQL/pgvector 16.
