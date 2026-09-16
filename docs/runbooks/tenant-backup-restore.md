# Tenant backup and restore verification

The platform database and tenant database have separate recovery boundaries.
Never commit an archive, manifest, or credential file to Git.

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
