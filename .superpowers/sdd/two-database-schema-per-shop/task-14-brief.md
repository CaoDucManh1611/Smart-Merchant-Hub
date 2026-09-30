# Task 14 — Pilot copy/checksum/cutover/rollback

## Files
- Create `backend/app/services/tenant_data_migration.py`.
- Create `backend/app/scripts/migrate_tenant.py`.
- Create `backend/app/scripts/verify_tenant_migration.py`.
- Create `backend/tests/test_tenant_data_migration.py`.
- Modify `docs/runbooks/postgresql-staging.md`.

## Interfaces
```python
def migrate_business(*, business_id: int, dry_run: bool, cutover: bool) -> MigrationReport: ...
def verify_business(*, business_id: int) -> VerificationReport: ...
def rollback_cutover(*, business_id: int, operation_id: str) -> None: ...
```

## Required work
- Fixture data covering every tenant-owned table, attachments, vectors, orders, audit records and idempotency rows.
- Tests for dry-run, resumable copy, row counts, deterministic checksums, FK validation, write lock during cutover and rollback before cleanup.
- Ordered per-table copy from legacy shared tables filtered by `business_id`; record cursors/checksums in platform migration operation.
- Cutover: maintenance → drain shop worker/webhook queue → final delta → verify → enable registry → smoke read/write → active.
- Rollback: disable new route → restore legacy feature flag → replay queued inbound events → active legacy; never delete copied schema during rollback window.
- Manual approval required between dry-run and cutover; output counts/hashes only, never content.
- Run `pytest -q tests/test_tenant_data_migration.py tests/test_legacy_channel_migration.py`.
- Commit `feat: add verified per-shop migration tooling`.

## Global constraints
Never infer schema from user input; never copy tenant content to platform reports/logs; no destructive schema cleanup on rollback; TDD required.
