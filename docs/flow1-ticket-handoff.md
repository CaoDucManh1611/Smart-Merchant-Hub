# Connection support ticket integration

This slice creates shop-to-platform connection support requests. It does not create CRM customer tickets, provider calls, tenant support grants, memberships or permissions. Backend Pydantic schemas in `app.schemas.platform_support_request` are the authoritative HTTP contract and generate OpenAPI when the router is included.

## Main integration

1. Import `app.api.platform_support_requests` in the API router and call `api_router.include_router(platform_support_requests.router)`. The module exports one router with both shop and admin paths; the existing root router supplies `/api`.
2. Register/import `app.models.platform_support_request` wherever platform metadata is loaded, including the platform Alembic environment. Export the two models only if existing conventions require it. No existing exports or routers were edited by this slice.
3. Import `ConnectionSupport` from `./ConnectionSupport.vue` and mount it with `:request="apiFetch"`, `:base-url="apiBase"`, optional `:channel="selectedChannel.type"`, and optional `:error="connectionError"`. `apiBase` must include `/api` (default `/api`). `request(url, init?)` returns a standard fetch Response and attaches auth using the existing apiFetch helper. The component owns its form, list, refresh and pagination. It emits `created` with the ticket response. Remount it when the authenticated shop changes to clear prior shop state. Supply a unique mount per screen (hint element ID is fixed).
4. Migration revision is `20261011_0002_support_requests`, parent `20260922_0014`. A concurrently authored checkout revision may create a second head: main must reconcile the migration chain/merge before deployment. Do not reuse the checkout revision identifier. No live migration was executed.

## Shop API

`POST /api/support/requests` accepts exactly:

```json
{
  "provider": "facebook",
  "description": "Không thể kết nối trang bán hàng.",
  "idempotency_key": "client-generated-uuid"
}
```

Providers: `facebook`, `instagram`, `telegram`, `zalo`, `tiktok`, `shopee` (existing channel labels). Description: 1–2000 characters, trimmed, HTML tags/control characters removed; whitespace-only values rejected. Links, credential assignments, bearer authorization, JWT-shaped strings, long opaque strings, raw JSON/tracebacks and script/style contents are rejected. Unknown fields (including business IDs, tokens and diagnostics) are rejected. No raw error prop is displayed or submitted by the component. Free-text pattern checks cannot recognize every possible secret; only human summaries should be submitted, with no copied diagnostics.

Idempotency key: 8–180 ASCII letters/digits/underscore/hyphen. Unique per authenticated business. Fingerprint uses normalized provider and description, excluding key and actor. Initial creation returns 201; replay of the same normalized content returns 200 and the existing ticket even after status changes. Changed content with the same key returns 409 `idempotency_payload_conflict`. Concurrent uniqueness/identity races without a visible winning ticket return 409 `support_request_retry`; retry the identical payload/key. The component retains the key across network failures and generates a new key when content changes or a submission succeeds.

`GET /api/support/requests?status=open&limit=20&offset=0` returns only the signed-in user's business. Status is optional; limit 1–100 (default 20), offset >=0 (default 0); newest IDs first. The request cannot supply or override shop identity via headers, body or query fields. A user without a business receives 403 `shop_identity_required`.

Identity comes exclusively from `get_current_user().business_id`. POST reuses the existing `_sync_platform_business(platform_db, legacy_db, business_id)` helper to safely mirror an existing shop into `platform_businesses` when necessary. Missing legacy shop returns 404; no ticket can reference a nonexistent platform business.

## Person 3 admin API

Both routes use the existing `require_platform_admin` dependency.

`GET /api/platform/support-requests?status=in_progress&limit=20&offset=0` lists all shops with the same pagination envelope and optional status filter.

`PATCH /api/platform/support-requests/{id}` accepts one or more of:

```json
{"status":"in_progress","response":"Đang kiểm tra kết nối.","assigned_admin_id":99}
```

`assigned_admin_id` may be omitted (preserve), null (unassign) or the authenticated admin's own ID (self-assign). An arbitrary other admin ID returns 403 `assignment_must_match_current_admin`. Assignment is metadata only; it grants no tenant access. Actor/assignment IDs snapshot legacy auth identities rather than incorrectly referencing platform_users in another database. Response uses the same summary sanitation and 1–2000 bounds; explicit null response/status and an empty update are rejected (422). Unknown fields are rejected.

Transitions: `open → in_progress → resolved → closed`, plus `resolved → in_progress` for reopening. Same-status response/assignment updates are allowed and append history. Invalid transitions return 409 `invalid_support_status_transition`. Missing ticket returns 404 `support_request_not_found`. Production row locks serialize admin updates. Closed requests cannot transition; response/assignment metadata can still be updated with history.

## Responses and durability

Ticket fields: `id`, `business_id`, `provider`, `description`, `status`, nullable `response`, nullable `assigned_admin_id`, `created_at`, `updated_at`, and ordered `history`. Keys/fingerprints are not exposed. Datetimes follow existing naive UTC platform timestamps; the component displays them in local time.

Each history entry: `id`, `actor_user_id`, nullable `from_status`, `to_status`, nullable `response`, nullable `assigned_admin_id`, `created_at`. Creation writes one `null → open` entry; every accepted PATCH writes a snapshot entry. Ticket and history are committed atomically in the platform session. Business/history foreign keys use RESTRICT to prevent silent history loss. There are no delete endpoints. Platform schema only; no CRM models are modified.

List envelope: `{ "items": [ticket], "total": 1, "limit": 20, "offset": 0 }`.

Database errors roll back and return safe 503 `support_requests_unavailable`; clients must not display raw validation/error payloads. Existing FastAPI validation remains 422 and may echo invalid input in its standard validation response. The Vue component displays fixed human-facing messages, retains unsent content, disables actions while saving/loading, refreshes after success, and shows list failure separately from successful creation.

## Verification

Focused tests use an isolated FastAPI app, mocked authentication and SQLite with foreign keys enabled. They cover cross-shop isolation, spoofed shop headers, auth failures, create/replay/conflict, bounds/sanitization, self-assignment, transitions, durable history, rollback, database uniqueness/FKs and in-memory migration upgrade/downgrade. No production DB settings, migrations, data writes or commits were used.

Initial contract tests were authored before implementation; their first execution was green because Docker access was pending during implementation. Expanded credential cases were observed red (three failures), then green after sanitation hardening. Do not claim a fully observed initial red/green cycle.

Final verification: **11 tests and 16 subtests passed** with explicit `ENVIRONMENT=test` and temporary SQLite URLs for legacy/platform/tenant DBs. Delegate review found a tag/control normalization bypass; regression tests reproduced it red, then passed after checking original and normalized text. Vue script/template/style compilation and mocked request checks passed. Playwright CLI in installed Edge verified 375px light and `.crm-dark` layouts without overflow, desktop keyboard focus with reduced motion, hidden raw diagnostics, draft retention, successful retry and stable idempotency keys. Browser API calls were mocked; no live ticket mutations occurred. The isolated browser fixture must import the same versioned Vue module URL as Vite's component and install the existing `$t` translation function.

Not checked: production PostgreSQL concurrency, full-project regression/build checks, or the main agent's integrated app routes. Main reported App/router integration complete. Before deployment, reconcile concurrent migration heads and register platform model metadata as described above. No live migrations or commits were made.
