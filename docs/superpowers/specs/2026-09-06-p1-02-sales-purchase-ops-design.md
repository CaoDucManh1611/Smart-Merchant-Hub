# P1-02 Sales and Purchase Operations Design

## Goal

Đưa Sales Order và Purchase Order từ mức CRUD cơ bản lên quy trình vận hành CRM có thể theo dõi bán hàng, nhập hàng, tồn kho, thanh toán và lịch sử nghiệp vụ trong phạm vi một business.

## Context

Hệ thống hiện đã có `Product`, `Order`/`OrderItem` và `PurchaseOrder`/`PurchaseOrderItem`, cùng API tạo, đọc, sửa và chuyển trạng thái cơ bản. `Product.stock_quantity` hiện là số tồn trực tiếp, chưa có sổ biến động; Purchase Order chỉ lưu tên nhà cung cấp dạng text và chưa có nhận hàng theo lần; Sales Order chưa có giữ tồn, xuất kho, thanh toán hoặc hoàn tiền.

## Scope

### 1. Supplier master data

- Thêm nhà cung cấp thuộc `business_id`.
- Lưu mã, tên, thông tin liên hệ, trạng thái active/archived và metadata.
- Không cho truy cập hoặc liên kết supplier khác tenant.
- Purchase Order tham chiếu supplier; giữ snapshot tên supplier trên đơn để lịch sử không đổi khi supplier được sửa.

### 2. Purchase Order

- Giữ mã PO duy nhất trong từng business.
- Mỗi dòng lưu sản phẩm, số lượng đặt, số lượng đã nhận, đơn giá nhập tại thời điểm đặt và thành tiền.
- Cho phép nhận nhiều lần qua receipt; mỗi receipt có người thực hiện, thời gian, ghi chú và số lượng theo dòng.
- Vòng đời hợp lệ:

  `draft -> submitted -> partially_received -> received -> closed`

  `draft -> cancelled`, `submitted -> cancelled`, `partially_received -> cancelled`.

- Chỉ receipt trên PO `submitted` hoặc `partially_received`.
- Không cho nhận vượt số lượng đặt.
- Khi receipt thành công, ghi stock movement loại `purchase_receipt` và tăng tồn trong cùng transaction.
- Hủy PO không xóa receipt hoặc stock movement đã có; chỉ dừng nhận thêm.

### 3. Inventory ledger

- Thêm sổ `stock_movements` tenant-scoped, liên kết product và nguồn nghiệp vụ (PO receipt, SO shipment, refund hoặc adjustment).
- Mỗi movement có loại, số lượng signed, tồn trước/sau, actor, thời gian và metadata nguồn.
- Cập nhật tồn với row lock/transaction để không bán hoặc nhận hàng vượt dữ liệu đồng thời.
- Tồn khả dụng được tính từ tồn thực tế trừ số lượng đang giữ cho Sales Order.
- Không cho tồn thực tế hoặc tồn khả dụng âm.
- Không xóa movement; điều chỉnh phải tạo movement đối ứng và audit.

### 4. Sales Order

- Giữ liên kết customer/conversation hiện có và snapshot tên sản phẩm, SKU, giá tại thời điểm đặt.
- Bổ sung số lượng giữ tồn, trạng thái thanh toán và lý do hủy/hoàn.
- Vòng đời bán hàng:

  `draft -> confirmed -> processing -> shipped -> delivered -> completed`

  `draft -> cancelled`, `confirmed -> cancelled`, `processing -> cancelled`, `delivered -> refunded`.

- `confirmed` giữ tồn; `shipped` chuyển tồn giữ thành xuất kho; hủy trước khi giao giải phóng tồn giữ; hoàn sau giao tạo movement nhập hoàn.
- Không cho transition ngược hoặc transition bỏ qua điều kiện tồn kho.

### 5. Payment and debt

- Thêm payment theo Sales Order với phương thức, số tiền, trạng thái pending/paid/failed/refunded, mã tham chiếu và thời gian.
- Cho phép thanh toán một phần; tổng đã thanh toán không vượt tổng đơn.
- Chỉ đơn `paid` hoặc quy tắc business tương ứng mới chuyển `completed`.
- Refund không vượt tổng đã thanh toán; cập nhật số tiền hoàn và tạo audit/event.
- Purchase Order lưu trạng thái công nợ ở mức tối thiểu (unpaid/partial/paid) và số đã trả; chưa xây cổng thanh toán nhà cung cấp.

### 6. Events, audit and Customer 360

- Mọi transition, receipt, stock movement, payment, refund và cancellation tạo order event/audit tenant-scoped.
- Sales Order event của khách cuối xuất hiện trong Customer 360 timeline.
- Purchase Order chỉ xuất hiện trong timeline business/admin, không gán nhầm vào customer nếu không có liên kết customer.
- Audit không ghi credential hoặc dữ liệu bí mật.

### 7. API and UI

- API supplier CRUD và archive.
- API PO receipt, PO detail/history, inventory movements/balance, sales payment/refund.
- API transition trả lỗi 409 cho transition không hợp lệ, 422 cho payload sai và 404 khi resource không thuộc tenant.
- UI Orders có tab Sales/Purchase, bộ lọc trạng thái/supplier/customer, form dòng sản phẩm, chi tiết, transition, nhận hàng, thanh toán và lịch sử.
- UI hiển thị tồn khả dụng, số lượng đã nhận, công nợ và lỗi thao tác; không hiển thị token/credential.

## Non-goals

- Chưa xây cổng thanh toán thực tế hoặc đối soát ngân hàng.
- Chưa xây quản lý nhiều kho, lô/hạn sử dụng hoặc serial number.
- Chưa xây vận chuyển tích hợp bên thứ ba.
- Chưa thay đổi contract webhook các kênh.
- Không dùng `metadata` để thay thế các bảng nghiệp vụ chính.

## Data and migration strategy

- Tạo migration Alembic kế tiếp từ head hiện tại.
- Bảng mới dự kiến: `suppliers`, `stock_movements`, `purchase_receipts`, `purchase_receipt_items`, `order_payments`, `order_events`.
- Bổ sung cột cần thiết vào `products`, `orders`, `order_items`, `purchase_orders`, `purchase_order_items` với default tương thích dữ liệu hiện có.
- Backfill số lượng đã nhận bằng 0, số lượng giữ tồn bằng 0 và payment state `unpaid`.
- Migration phải chạy được trên database hiện có mà không xóa dữ liệu.

## Error handling and consistency

- Mọi thao tác thay đổi tồn, trạng thái và payment thực hiện trong một transaction.
- Rollback toàn bộ nếu bất kỳ dòng sản phẩm, receipt hoặc payment không hợp lệ.
- Dùng row locking khi tính và cập nhật tồn.
- Idempotency key cho receipt/payment để retry không tạo movement hoặc giao dịch trùng.
- Lỗi provider hoặc webhook không được làm mất order event nội bộ.

## Testing and acceptance criteria

- Unit/API tests cho supplier tenant isolation, PO lifecycle, partial receipt, over-receipt rejection, sales reservation/shipment/cancel/refund, partial payment/refund và idempotency.
- Regression tests bảo đảm Product/Order API hiện có vẫn đọc được dữ liệu cũ.
- Tests xác nhận audit/event không vượt tenant và Customer 360 chỉ nhận event Sales Order của đúng customer.
- Frontend tests cho tab/filter/detail/transition/receipt/payment và hiển thị lỗi.
- Migration upgrade từ head hiện tại thành công.
- Docker backend test, frontend test/build và smoke test API phải pass trước khi commit.

## Rollout order

1. Supplier + schema line snapshot.
2. Inventory ledger + PO receiving.
3. Sales reservation/shipment/refund.
4. Payment/debt + audit/events.
5. UI Orders và báo cáo tồn/chi phí.

Mỗi mốc phải có test đỏ trước khi viết code, test xanh sau implementation và commit nhỏ trên nhánh `crm-completion` hiện tại theo yêu cầu của chủ dự án.
