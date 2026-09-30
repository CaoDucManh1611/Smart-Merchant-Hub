# Task 8 — Chuyển CRM lõi và kênh sang tenant session

Source plan: `docs/superpowers/plans/2026-09-15-two-database-schema-per-shop.md`

## Files
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

## Interfaces
- Tenant repositories consume only `Session` already bound to the shop schema.
- Tenant rows no longer depend on foreign keys to platform `businesses`; `business_id` may remain as redundant audit data until Task 15.

## Required work
- Extend isolation tests with identical primary keys/external IDs in two schemas and assert no cross-shop reads/writes/assignments.
- Confirm tests fail while APIs use `get_db` and explicit shared-table filters.
- Switch dependencies and services to tenant sessions; remove platform joins from tenant transactions.
- Keep global uniqueness only where the provider requires it, via `ChannelRoute`; channel uniqueness inside schema is provider/account scoped locally.
- Run `pytest -q tests/test_api_tenant_isolation.py tests/test_tenant_scoped_queries.py tests/test_channel_contracts.py`.
- Commit only Task 8 work with message `refactor: isolate core CRM data by shop schema`.

## Branch-specific ruling
Task 6's canonical `get_tenant_db` is not present yet and belongs to another branch. Do not edit Task 5-7 auth/platform-owned files. Build a schema-bound tenant-session seam within Task 8-owned/new tenant-domain code that can be replaced or re-exported by the canonical Task 6 dependency at merge time. Do not use shared RLS/global DB as the real tenant storage path.

## Global constraints that bind this task
- Schema names are server-generated `shop_<business_id>` only and must match `^shop_[1-9][0-9]*$`.
- Tenant transactions use transaction-local search_path only.
- Platform DB must not store customer/conversation/channel-token content.
- TDD: red for the intended reason, minimal green, related regression tests, then commit.
