# PostgreSQL staging rehearsal

Use a disposable PostgreSQL staging database. The rehearsal must use the
same two-database layout as production: `crm_platform` for control-plane
metadata and `crm_tenant` for shop schemas.

## Preflight

Set the URLs in the protected environment (do not put passwords in command
history):

```powershell
$env:PLATFORM_DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>:5432/crm_platform"
$env:TENANT_DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>:5432/crm_tenant"
$env:DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>:5432/crm_chatbot"
```

Check that the PostgreSQL client matches the server major version and that
`pg_dump`, `pg_restore`, and `psql` resolve from the same installation.

## Platform and tenant migrations

Run the two Alembic heads independently from the backend container:

```powershell
python -m alembic -c alembic-platform.ini upgrade head
```

Tenant migrations are applied to a validated schema by the provisioning
saga (or `python -m app.scripts.migrate_tenant <business_id>` during a pilot);
do not run `CREATE SCHEMA` using a request-provided name. Provision one shop,
then verify its registry state is `active` and its revision equals the
required tenant head before enabling traffic.

The CRM worker also refreshes provider health on the configured
`CHANNEL_HEALTH_INTERVAL_SECONDS` interval. It checks only active registry
entries and records aggregate counts; provider credentials stay inside the
tenant schema.

## Per-shop migration pilot

Use the dry run first. Output is limited to counts and checksums:

```powershell
python -m app.scripts.migrate_tenant 42 --dry-run
```

After review, copy the rows only with an explicit cutover approval, then
verify them before enabling the shop:

```powershell
python -m app.scripts.migrate_tenant 42 --cutover
python -m app.scripts.verify_tenant_migration 42
```

If the pilot must be stopped, disable the route while retaining the schema so
the copy can be resumed:

```powershell
python -m app.scripts.migrate_tenant 42 --rollback
```

Rollback never drops the copied schema or deletes legacy rows. Re-run the
verification after any retry and only use `--complete <tenant_revision>` once
the operator has reviewed the report and smoke-test results.

## Backup rehearsal

Create and validate the source archive before restoring into a new scratch
database. Every command must stop on a non-zero `pg_dump`/`pg_restore` exit:

```powershell
.\scripts\backup-verify.ps1 -BackupFile .\artifacts\crm-staging.dump
.\scripts\backup-verify.ps1 -BackupFile .\artifacts\crm-staging.dump -VerifyOnly
```

Restore only to an isolated database unless an approved maintenance window
explicitly supplies `-Overwrite`. Record the archive checksum, PostgreSQL
server version, Alembic revision, and table/checksum report; do not record
customer messages, document text, or provider credentials.

## Release gate

Run the release smoke script against the disposable staging URLs. Confirm
health, both database connections, tenant webhook routing, RAG isolation,
worker routing, and frontend readiness. Any failed check blocks cutover.
