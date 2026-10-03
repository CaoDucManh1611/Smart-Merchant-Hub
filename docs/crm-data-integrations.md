# CRM data and integration contract

## Product links

`Product.product_url` is nullable so old catalog rows and older clients remain
valid. `POST /api/products` and `PATCH /api/products/{id}` accept an optional
`product_url`; `GET /api/products` and `GET /api/products/{id}` return it. Only
HTTP(S) URLs with a host and without embedded credentials are accepted. Product
lookups remain constrained to the authenticated shop.

```json
{
  "sku": "SKU-001",
  "name": "Áo màu hồng",
  "product_url": "https://shop.example/products/sku-001"
}
```

## Verified account email change

The shop user's sign-in/OTP email is changed through a two-step authenticated
flow, separate from the shop's SMTP sender settings:

1. `POST /api/auth/email-change/request` with `new_email` and
   `current_password`; the code is sent to the new mailbox via the shop's
   configured SMTP sender or the platform SMTP sender.
2. `POST /api/auth/email-change/verify` with the six-digit `otp`.

The current email remains active until verification succeeds. Codes expire in
10 minutes, allow five attempts, and are limited to one request per minute and
five per hour. Failed or development-chat delivery cannot verify ownership.
Successful changes are audited using keyed email fingerprints and revoke the
user's other active sessions. The legacy staff PATCH route rejects direct
email mutation and points callers to this flow.

```json
{ "new_email": "owner@example.com", "current_password": "••••••••" }
{ "otp": "123456" }
```

## Shop migration to PostgreSQL

The source shared database is read-only during `app.scripts.migrate_tenant`;
the destination is a shop schema in `TENANT_DATABASE_URL`. A PostgreSQL source
uses the existing PostgreSQL backup rehearsal; a SQLite source uses
`--sqlite-source` plus a new `--sqlite-backup` snapshot on the dry run, then the
same snapshot for cutover and verification. The required order is:

1. Back up and validate both source and destination PostgreSQL archives.
2. Apply current tenant migrations and run `python -m app.scripts.migrate_tenant <business_id> --dry-run`.
3. Review row counts/checksums, then run with `--cutover --operation-id <stable-id>`.
4. Verify counts/checksums and foreign keys with `python -m app.scripts.verify_tenant_migration <business_id>`.
5. Complete cutover only after reviewing the report. To roll back, run with `--rollback --operation-id <same-id>`; this disables routing but retains both source rows and the destination copy.

Never restore onto or pass an overwrite option for the source database. Detailed
commands and the backup rehearsal are in `docs/runbooks/postgresql-staging.md`.

## Connector status

`GET /api/onboarding/shops/{business_id}/channels` returns safe status fields,
including `connector_status`, `connector_last_seen_at`, and a bounded
`connector_last_error_code`. The TikTok and Shopee desktop connectors send an
authenticated heartbeat to `POST /api/channels/{channel_type}/heartbeat` every
45 seconds. The CRM reports these as requiring a local device; it does not claim
they run on the CRM server. For a paired, recently-online connector,
`retry_endpoint` points to
`POST /api/onboarding/shops/{business_id}/channels/{channel_type}/retry`. The
server queues a short-lived restart command; the local connector acknowledges
it and restarts with its locally stored session. Offline devices return HTTP
409 and must be started manually—the server cannot wake the customer's PC.
Pairing only proves credential exchange, while `online` requires a recent
heartbeat.

## Shop SMTP provider

Each shop may use any DNS SMTP hostname with either STARTTLS on port 587 or
implicit TLS on port 465. The SMTP password is encrypted at rest and never
returned by the settings API. The sender address may be an authorized alias;
the provider decides whether that account is permitted to send as it.

## RFM and customer-interest contract

`POST /api/customers/rfm/classify` uses completed/revenue-bearing orders for the
current shop. Recency is days since the last eligible order (lower is better);
frequency is eligible order count; monetary is summed order value. Each metric
is ranked into relative 1–5 quintile scores within that shop's current buyers.
Rules are deterministic: no orders → `RFM · Chưa mua`; R/F/M ≥4 → `Giá trị cao`;
R≥3 and F≥4 → `Trung thành`; R≥4 and F≤2 → `Tiềm năng`; R≤2 and F≥3 → `Cần
chăm sóc`; R≤2 and F≤2 → `Nguy cơ rời bỏ`; otherwise → `Duy trì`. Re-running
replaces only CRM-managed RFM tags and preserves manual labels.

Customer interests use the existing tenant-scoped `CustomerFact` API:

```json
{
  "fact_type": "preference",
  "fact_key": "preferred_color",
  "fact_value": "pink",
  "confidence": 0.92,
  "source_type": "extracted",
  "source_message_id": 123,
  "observed_at": "2026-10-01T12:00:00Z"
}
```

Use stable keys such as `preferred_color`, `interested_category`, and
`purchase_frequency`; values are JSON scalars or structures, with source and
observation time retained. Chat extraction must not invent purchase frequency:
derive it from eligible order history. Staff can delete one fact with
`DELETE /api/customers/{customer_id}/facts/{fact_id}`. To stop inferred fact
collection and erase existing inferred facts for a customer, call
`PATCH /api/customers/{customer_id}/fact-collection` with
`{"opt_out": true}`. It preserves manually entered/verified facts. Re-enable
with `{"opt_out": false}`; deleted extracted facts are not recreated unless
new source messages are processed and shop-level extraction is enabled.

## Run and verify

From the repository root, run the backend checks:

```powershell
python -m pytest -q backend/tests/test_product_order_api.py backend/tests/test_customer_fact_extractor.py backend/tests/test_customer_360_final.py backend/tests/test_local_connectors.py backend/tests/test_tenant_migration_runner.py backend/tests/test_tenant_data_migration.py backend/tests/test_container_migrations.py backend/tests/test_tenant_backup_scripts.py
```

The tenant migration script defaults to read-only preview. Check active schema
revisions before applying an additive migration:

```powershell
docker compose exec -T backend python -m app.scripts.upgrade_active_tenants
docker compose exec -T backend python -m app.scripts.upgrade_active_tenants --apply
```

The second command applies pending tenant revisions to active tenant schemas;
review the migration code and before/after revision report first, and keep
database backups through the rollback window.
