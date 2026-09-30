# P1-02 — Kiểm chứng Sales và Purchase Operations

Ngày cập nhật: 2026-09-06  
Nhánh: `crm-completion`  
Migration head: `20260906_0024`

## Phạm vi đã triển khai

- Supplier tenant-scoped: tạo, sửa, lưu trữ, tìm kiếm và chống trùng mã.
- Sales Order: snapshot sản phẩm, kiểm tra tenant, vòng đời draft → confirmed → processing → shipped → delivered → completed/refunded/cancelled.
- Tồn kho: giữ tồn khi xác nhận, xuất kho khi shipped, giải phóng khi hủy trước xuất, cộng bù khi hoàn tiền; ledger bất biến và kiểm tra không âm.
- Purchase Order: supplier snapshot, nhận một phần/nhiều lần qua receipt, idempotency, cập nhật `received_quantity` và tồn kho.
- Payment: thu tiền Sales Order và Purchase Order, trạng thái unpaid/partial/paid, chống overpayment.
- Refund: hoàn tiền Sales Order, chống vượt số đã thu, idempotency và cập nhật `refunded_amount`.
- Order events: lịch sử trạng thái, receipt, payment và refund; Customer 360 chỉ chiếu event của Sales Order thuộc khách.
- Báo cáo: tồn thực tế/đang giữ/có thể bán, biến động tồn, chi phí nhập đã nhận theo nhà cung cấp và khoảng thời gian.
- Giao diện: đổi trạng thái Sales Order, cảnh báo thiếu tồn, thu/hoàn tiền, lịch sử đơn; nhận hàng, thanh toán công nợ và báo cáo tồn/chi phí.
- Bảo vệ nghiệp vụ: không cho đổi trạng thái qua PATCH; PO phải dùng receipt để chuyển sang trạng thái đã nhận.

## API chính

### Supplier và tồn kho

- `GET/POST /api/suppliers`
- `GET/PATCH/DELETE /api/suppliers/{supplier_id}`
- `GET /api/inventory/products/{product_id}`
- `GET /api/inventory/movements`

### Sales Order

- `GET/POST /api/orders`
- `GET/PATCH /api/orders/{order_id}` (PATCH chỉ sửa thông tin, không đổi trạng thái)
- `POST /api/orders/{order_id}/transition`
- `POST /api/orders/{order_id}/payments`
- `POST /api/orders/{order_id}/refunds`
- `GET /api/orders/{order_id}/payments`
- `GET /api/orders/{order_id}/events`

### Purchase Order

- `GET/POST /api/purchase-orders`
- `GET/PATCH /api/purchase-orders/{order_id}`
- `POST /api/purchase-orders/{order_id}/transition` (không dùng để đánh dấu đã nhận)
- `POST /api/purchase-orders/{order_id}/receipts`
- `POST /api/purchase-orders/{order_id}/payments`
- `GET /api/purchase-orders/{order_id}/payments`
- `GET /api/purchase-orders/{order_id}/events`

### Customer 360 và báo cáo

- `GET /api/customers/{customer_id}/timeline`
- `GET /api/reports/inventory`
- `GET /api/reports/purchase-costs?start_at=&end_at=`

## Bằng chứng kiểm thử cục bộ

Đã chạy bằng Python runtime của workspace:

- `backend/tests`: **201 passed**.
- Frontend utility tests: **13 passed**.
- Nhóm Sales/PO/payment/timeline: **24 passed** trong các lần kiểm tra tập trung.

Các cảnh báo hiện tại chỉ là deprecation warning của Starlette/FastAPI và Python test cleanup; không có test failure.

## Cách chạy trên máy Windows có Docker

Từ thư mục `smart-merchant-hub`:

```powershell
docker compose up -d db backend frontend
docker compose run --rm backend python -m alembic upgrade head
docker compose run --rm -v "${PWD}\backend\tests:/app/tests:ro" backend python -m pytest /app/tests -q
docker compose run --rm frontend pnpm test -- --run
docker compose run --rm frontend pnpm build
```

Nếu service `backend` đang dừng, dùng `docker compose run --rm backend ...` cho migration/test; không dùng `docker compose exec backend` khi container không chạy.

Image frontend đã cài sẵn `pnpm` trong Dockerfile. Nếu đang dùng image cũ, build lại image trước khi chạy lệnh pnpm.

## Smoke test tối thiểu

1. Tạo Product có `stock_quantity=5` và một Sales Order số lượng 2.
2. Gọi transition `confirmed`, kiểm tra `reserved_quantity=2`, tồn khả dụng bằng 3.
3. Gọi `processing` rồi `shipped`, kiểm tra tồn thực tế giảm còn 3 và reservation về 0.
4. Ghi payment một phần và kiểm tra `payment_status=partial`; gửi lại cùng `idempotency_key` phải trả bản ghi cũ.
5. Gọi `delivered` rồi refund, kiểm tra `refunded_amount` và ledger `sales_refund`.
6. Tạo PO ở `submitted`, nhận một phần qua receipts, kiểm tra `received_quantity`, status `partially_received` và ledger `purchase_receipt`.
7. Đọc Customer 360 timeline: thấy `sales_order`/`order_payment`, không thấy PO không liên kết.
8. Đọc `/api/reports/inventory` và `/api/reports/purchase-costs` bằng `X-Business-Id` khác: không được thấy dữ liệu tenant 1.

## Giới hạn còn lại

- Payment hiện là sổ giao dịch nội bộ, chưa kết nối cổng thanh toán bên ngoài hoặc webhook đối soát.
- Receipt UI đang có nút nhận toàn bộ số lượng còn lại; muốn nhận từng dòng khác nhau có thể mở rộng form chi tiết.
- Cần chạy build/test trong Docker trên máy người dùng trước khi deploy vì runtime Codex không có Docker/npm cache hoàn chỉnh.
- Các hạng mục P1 khác (auth production nâng cao, workflow worker/scheduler, RAG hardening) vẫn nằm trong roadmap riêng.

## Rollback

- Migration chỉ thêm bảng/cột, không xóa dữ liệu. Rollback kỹ thuật dùng `alembic downgrade 20260905_0023` sau khi backup PostgreSQL.
- Không rollback bằng cách xóa volume hoặc reset database.
- Khi rollback code, giữ lại ledger/payment/event rows để đối soát; chỉ hạ phiên bản API sau khi đã dừng các thao tác mới.
