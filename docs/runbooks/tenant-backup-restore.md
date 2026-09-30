# Tenant backup and restore verification

The platform database and tenant database have separate recovery boundaries.
Never commit an archive, manifest, or credential file to Git.

## Rehearsal record

On 2026-09-30, the current migration chain was exercised against a disposable
PostgreSQL 16 container: a tenant schema upgraded to `20260930_0009`, downgraded
to `20260926_0007`, and upgraded to head again. A custom-format `pg_dump` was
restored into a separate empty database. Verification returned revision
`20260930_0009`, 85 tenant tables, and the seeded synthetic customer row. The
container and its archive were removed afterward; the active application
database was not accessed. Three Windows tests for `backup-verify.ps1` passed,
and tenant script contract tests passed in the backend suite. The actual tenant
PowerShell scripts were not invoked because native PostgreSQL client tools are
not installed on the Windows host. This rehearsal used the container's native
dump/restore primitives.

On 2026-09-30, the dump/restore primitives were exercised in a disposable,
isolated PostgreSQL 17 Alpine container with synthetic `shop_42` data. A custom
archive was created, restored into a second database, and verified as
`2:1=Khach A,2=Khach B`; the restored tenant revision was `20260930_0009` and
the archive SHA-256 was
`00c702f2f3832525a5d1ad0bd99b431df317bc614942168dda73acfe5659972f`.
The disposable container and archive were removed afterward. This proves the
database dump/restore path; the PowerShell guardrails remain covered by
`backend/tests/test_tenant_backup_scripts.py`. A rehearsal using the exact
production PostgreSQL major version is still required before production.

## Backup one shop

Set `TENANT_DATABASE_URL` through the secret manager, then run:

```powershell
./scripts/tenant-backup.ps1 -BusinessId 42 -BackupFile .\backups\shop-42.dump
```

The script derives the only accepted schema name (`shop_42`), uses
`pg_dump --schema`, checks native exit codes, verifies a non-empty custom
archive, and writes a SHA-256 manifest beside it.

## Restore into a scratch database

Set `TENANT_VERIFY_DATABASE_URL` to a newly created PostgreSQL 16 database:

```powershell
./scripts/tenant-restore-verify.ps1 `
  -BusinessId 42 `
  -BackupFile .\backups\shop-42.dump `
  -ManifestFile .\backups\shop-42.dump.manifest.json
```

Restore is non-destructive by default. `-Overwrite` is required before
`pg_restore --clean --if-exists` can be used during an approved maintenance
window. The verifier checks the archive checksum, schema derivation,
PostgreSQL client/server major compatibility, restored schema table count,
per-table row checksums, Alembic revision, and restore/list exit codes.
`-ManifestFile` is mandatory for a verified restore.

## Platform backup

Use `scripts/backup-verify.ps1` with `DATABASE_URL` (the platform database in
production). Any `pg_dump` or `pg_restore` failure, missing archive, or empty
archive exits non-zero before a success message is printed.
