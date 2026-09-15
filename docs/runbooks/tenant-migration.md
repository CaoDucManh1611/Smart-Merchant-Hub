# Per-shop migration runbook

The migration command copies one shop at a time from the legacy database into
its `shop_<business_id>` schema. It never deletes the source rows.

## 1. Dry run

Run from the backend container (or with the backend virtual environment):

```powershell
python -m app.scripts.migrate_tenant 42 --dry-run
```

The output contains only row counts and SHA-256 checksums. Review the output
before starting a cutover.

## 2. Copy and cut over

```powershell
python -m app.scripts.migrate_tenant 42
python -m app.scripts.migrate_tenant 42 --complete 20260915_0001
```

The first command marks the registry `migrating`, copies rows in dependency
order and leaves the tenant disabled until verification. The `--complete`
step is the explicit operator approval that marks the shop `active`.

## 3. Verify

```powershell
python -m app.scripts.verify_tenant_migration 42
```

Verification compares row counts and deterministic checksums for both sides;
it does not print customer content. Exit code `0` means all selected tables
match; exit code `2` means at least one table differs.

## 4. Rollback

If verification or smoke tests fail, disable the new route and mark the
registry in the platform database as `error`. The copied schema is retained so
the operation can resume safely; rollback never drops tenant data.

