# 01 — Catalog schema đa ngành

**Trạng thái:** Hoàn tất phần mã nguồn và đã áp dụng migration trên local Docker PostgreSQL.

## Đã làm

- Dùng một catalog theo `business_id` và `object_type` (`product`, `service`, `rental`), với SKU chuẩn hóa, trạng thái, khả dụng, tồn kho, giá và revision.
- Lưu thuộc tính đã chuẩn hóa theo kiểu text/number/boolean/date; liên kết catalog entry với các `document_chunks`.
- Đăng ký các ORM catalog và quality-gate trong tenant metadata tại `backend/app/models/tenant_template.py`.
- Đồng bộ các index khai báo giữa ORM và migration; thêm index theo shop/type/trạng thái, shop/SKU; bỏ index đơn lẻ bị trùng với index tổng hợp.
- Migration yêu cầu và xác thực tenant schema trước khi tạo bảng.

## Tệp

- `backend/app/models/recommendation_catalog.py`
- `backend/app/models/recommendation_quality_gate.py`
- `backend/app/models/tenant_template.py` (đăng ký model đã có trong checkout)
- `backend/alembic_tenant/versions/20261101_0015_recommendation_catalog.py`

## Giới hạn còn lại

- Migration đã được xác minh trên local Docker PostgreSQL; chưa áp dụng trên cloud/production.
- Bảng catalog chưa có dữ liệu cho tới khi chạy backfill/đồng bộ ở mục 03.

Ghi chú ban đầu trước khi chạy migration và backend suite; kết quả cập nhật ở phần runtime bên dưới.

## Kết quả runtime (2026-11-01)

- Đã áp dụng migration `20261101_0015` cho 14 tenant schema trong local Docker PostgreSQL.
- Đã kiểm tra lại: 14/14 schema ở revision mới và có đủ bốn bảng catalog/quality-gate.
- Chưa backfill catalog từ sản phẩm hiện có; bảng catalog mới chưa có dữ liệu cho tới khi đồng bộ/backfill.

## Kiểm tra cuối

- PostgreSQL backend suite: **1,625 passed, 6 skipped, 37 subtests passed**, 9 warnings; log đầy đủ tại `2026-11-01-backend-tests-postgres-final.log`.
- Migration chỉ được áp dụng/xác minh trên local Docker PostgreSQL; chưa chạy trên cloud/production.
