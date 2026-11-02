# 08 — Backfill catalog cũ

**Trạng thái:** Hoàn tất trên local Docker PostgreSQL.

## Kết quả

- Duyệt đủ 14 tenant đăng ký; không có tenant lỗi.
- Trước backfill: 1.556 sản phẩm, 0 dịch vụ hẹn và 0 catalog entry.
- Đã thêm 1.556 sản phẩm vào catalog chuẩn; không ghi đè entry có sẵn.
- Tạo 58 liên kết chunk theo SKU chính xác hoặc `catalog_chunk_ids` đã khai báo.
- Sau khi chạy, dry-run lại cho thấy 0 sản phẩm/dịch vụ còn thiếu và 0 lỗi tenant.
- Không tìm thấy bản ghi dịch vụ hẹn trong các tenant local. Hệ thống hiện chưa có bảng/model nguồn chuẩn cho dịch vụ cho thuê, nên không thể backfill dịch vụ/thuê từ dữ liệu không tồn tại.

## Cách chạy lại

`python backend/scripts/backfill_recommendation_catalog.py` chỉ đọc và báo cáo. Thêm `--apply` để thêm các entry còn thiếu. Script dùng tenant registry, xác thực `shop_<business_id>`, và chỉ xử lý catalog trên PostgreSQL local đã cấu hình.

## Phạm vi

Backfill này không làm mới các entry đã có và không cập nhật cloud/production. Bản ghi sản phẩm được đồng bộ tiếp bởi các luồng create/update hiện hành. Chỉ các chunk khớp SKU toàn token hoặc được khai báo trong metadata mới được liên kết.

## Bằng chứng

- Số liệu đầy đủ theo tenant: `2026-11-01-08-catalog-backfill.json`.
- Bộ đếm sau backfill: dry-run báo 14/14 tenant thành công, 0 entry thiếu.
- Không commit hoặc push.
