# 03 — Catalog synchronization and live availability

## Implemented

- Added canonical product and appointment-service projection helpers into the shared tenant catalog.
- Wired product create/update/archive/delete-all, CSV import, onboarding import, inventory adjustments, and structured knowledge-document ingestion to update the projection in the same tenant transaction.
- Knowledge-document imports map only chunks whose stored text contains the exact SKU; chunk links are tenant-validated. Catalog upserts retain existing links unless replacement IDs are explicitly supplied.
- Added current-source checks for product stock/status and appointment-service active state. Rental candidates fail closed unless the caller supplies the shop-specific availability reader.
- Catalog text normalization collapses repeated whitespace, matching the retrieval filter's exact-value normalization for SKU and text attributes.
- Existing product recommendation serving continues to read current product rows, status, and available stock before ranking.

## Limits / follow-up

- The tenant migration has not been run, so this projection is not available in an existing database until the migration is applied.
- Existing products need a tenant-scoped backfill before catalog filters can match them. This turn did not run a backfill or connect to a live database.
- The repository has no canonical rental-offer table/model. Rental sync is supported through the generic API, but serving must provide its authoritative availability reader.
- Service availability currently means active/inactive; calendar slot capacity is not modeled by `AppointmentService` and must be checked by the booking flow.

## Verification

- Static AST syntax parsing passed for 24 changed source modules and the tenant migration.
- The initial source review preceded the runtime migration and backend-suite run recorded below. Catalog backfill and live quality evaluation remain pending.
- No commit or push was made.

## Runtime result (2026-11-01)

- Migration `20261101_0015` đã áp dụng và xác minh cho 14 tenant schema trong local Docker PostgreSQL.
- Không chạy backfill catalog; dữ liệu sản phẩm hiện có chưa được nạp hàng loạt vào projection trong lượt này.
- Full backend suite đạt 1,625 passed, 6 skipped, 37 subtests passed; log `2026-11-01-backend-tests-postgres-final.log`.

## Kiểm tra cuối

- Test suite xác nhận các luồng đồng bộ đang có; migration đã có trên 14 schema local.
- Backfill sản phẩm/dịch vụ cũ chưa chạy, do đó các bản ghi hiện có chưa tự xuất hiện trong catalog projection cho đến khi luồng đồng bộ/backfill thực thi.
