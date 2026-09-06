# P1-02 Sales and Purchase Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Đưa Sales Order và Purchase Order lên quy trình vận hành có supplier, nhận hàng, tồn kho, thanh toán, hoàn tiền, audit và giao diện CRM.

**Architecture:** Giữ các API order hiện có và bổ sung service nghiệp vụ tập trung cho transition, inventory và payment. Tồn kho được ghi bằng ledger bất biến; Product.stock_quantity và reserved_quantity là cache cập nhật trong cùng transaction. Mọi nghiệp vụ thay đổi trạng thái hoặc tiền đều tạo order event/audit theo tenant.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL/pgvector, Alembic, Pydantic v2, Vue 3, Vitest, pytest.

**Spec:** docs/superpowers/specs/2026-09-06-p1-02-sales-purchase-ops-design.md

## Global Constraints

- Làm trực tiếp trên nhánh crm-completion; không tạo branch mới và không sửa main.
- Migration phải nâng cấp an toàn từ head hiện tại 20260905_0023 và không xóa dữ liệu.
- Mọi truy vấn và mutation bắt buộc lọc business_id từ TenantContext.
- Không dùng metadata để thay thế bảng supplier, inventory, receipt, payment hoặc event.
- Không cho tồn thực tế, tồn giữ hoặc số tiền thanh toán/hoàn âm; lỗi nghiệp vụ trả về status code nhất quán.
- Không ghi token, password, credential hoặc payload bí mật vào audit/log.
- Mỗi task chạy test đỏ trước implementation, test xanh sau implementation và commit riêng.

---

### Task 1: Schema foundation

**Files:**
- Create: backend/app/models/supplier.py
- Create: backend/app/models/inventory.py
- Create: backend/app/models/order_event.py
- Create: backend/app/models/order_payment.py
- Create: backend/app/schemas/supplier.py
- Create: backend/alembic/versions/20260906_0024_sales_purchase_ops.py
- Modify: backend/app/models/sales.py
- Modify: backend/app/models/purchase_order.py
- Modify: backend/app/models/__init__.py
- Test: backend/tests/test_p1_02_schema.py

**Interfaces:**
- Supplier: id, business_id, code, name, contact_name, email, phone, address, status, metadata_.
- StockMovement: business_id, product_id, movement_type, signed quantity, quantity_before, quantity_after, source_type, source_id, actor_id, note, created_at.
- PurchaseReceipt and PurchaseReceiptItem: receipt header, PO link, actor, note, idempotency_key, and received quantities per PO line.
- OrderPayment: business_id, order_id, amount, method, status, reference, paid_at, refunded_amount, idempotency_key.
- OrderEvent: business_id, order_type, order_id, event_type, from_status, to_status, actor_id, metadata_, created_at.
- Product adds reserved_quantity default 0; Order adds payment_status, paid_amount, refunded_amount, cancel_reason; PurchaseOrder adds supplier_id, supplier_name_snapshot, payment_status, paid_amount, cancel_reason; line items add product/SKU/name snapshots and PO received_quantity default 0.

- [ ] **Step 1: Write the failing schema tests**

~~~python
def test_new_business_tables_and_columns_exist(db_engine):
    inspector = inspect(db_engine)
    assert {"suppliers", "stock_movements", "purchase_receipts", "purchase_receipt_items", "order_payments", "order_events"}.issubset(inspector.get_table_names())
    assert "reserved_quantity" in {column["name"] for column in inspector.get_columns("products")}

def test_purchase_order_item_received_quantity_defaults_to_zero(db_session, business, product):
    order = PurchaseOrder(business_id=business.id, po_number="PO-SCHEMA", supplier_name="Supplier")
    db_session.add(order)
    db_session.flush()
    item = PurchaseOrderItem(purchase_order_id=order.id, product_id=product.id, quantity=3, unit_cost=10, line_total=30)
    db_session.add(item)
    db_session.commit()
    assert item.received_quantity == 0
~~~

- [ ] **Step 2: Run the schema tests and confirm the expected failure**

Run: python -m pytest backend/tests/test_p1_02_schema.py -q

Expected: FAIL because the new tables and columns do not exist.

- [ ] **Step 3: Add models and the Alembic migration**

Create the six tenant-scoped tables with foreign keys and indexes. Add nullable supplier reference plus non-null snapshots/defaults to existing order tables. Register every model in models/__init__.py; use inspector guards for repeatable upgrade on an existing database.

- [ ] **Step 4: Run schema and existing order tests**

Run: python -m pytest backend/tests/test_p1_02_schema.py backend/tests/test_product_order_api.py backend/tests/test_purchase_order_api.py -q

Expected: PASS with existing API behavior preserved.

- [ ] **Step 5: Commit**

~~~powershell
git add backend/app/models backend/alembic/versions/20260906_0024_sales_purchase_ops.py backend/tests/test_p1_02_schema.py
git commit -m "feat: add sales purchase operations schema"
~~~

### Task 2: Supplier API and Purchase Order snapshots

**Files:**
- Create: backend/app/api/suppliers.py
- Modify: backend/app/api/router.py
- Modify: backend/app/api/purchase_orders.py
- Modify: backend/app/schemas/purchase_order.py
- Test: backend/tests/test_supplier_api.py
- Test: backend/tests/test_purchase_order_api.py

**Interfaces:**
- GET /api/suppliers?status=&search=&limit=&offset= returns items and total.
- POST /api/suppliers accepts code, name, contact fields and metadata.
- PATCH /api/suppliers/{supplier_id} edits fields; DELETE archives the supplier.
- POST /api/purchase-orders accepts optional supplier_id while accepting supplier_name for old clients; it writes supplier_name_snapshot and product/SKU/name snapshots.
- Supplier/product from another business returns 404; duplicate supplier code returns 409.

- [ ] **Step 1: Write failing API tests**

~~~python
def test_supplier_crud_is_tenant_scoped(client, headers, other_business):
    created = client.post("/api/suppliers", headers=headers, json={"code": "SUP-01", "name": "Nhà cung cấp 1"})
    assert created.status_code == 201
    supplier_id = created.json()["id"]
    assert client.get(f"/api/suppliers/{supplier_id}", headers={"X-Business-Id": str(other_business.id)}).status_code == 404

def test_purchase_order_persists_supplier_and_product_snapshots(client, headers, supplier, product):
    response = client.post("/api/purchase-orders", headers=headers, json={"po_number": "PO-SNAP-1", "supplier_id": supplier.id, "items": [{"product_id": product.id, "quantity": 2, "unit_cost": "12.50"}]})
    assert response.status_code == 201
    assert response.json()["supplier_name"] == supplier.name
    assert response.json()["items"][0]["product_name"] == product.name
~~~

- [ ] **Step 2: Run tests and confirm failure**

Run: python -m pytest backend/tests/test_supplier_api.py backend/tests/test_purchase_order_api.py -q

Expected: FAIL because supplier routes and snapshot fields are not implemented.

- [ ] **Step 3: Implement supplier routes and PO snapshot handling**

Add tenant-filtered queries, require_write_access on mutations, audit records for create/update/archive, and validation that supplier_id belongs to the active business. Preserve old supplier_name requests as snapshots when no supplier id is supplied.

- [ ] **Step 4: Run focused and regression tests**

Run: python -m pytest backend/tests/test_supplier_api.py backend/tests/test_purchase_order_api.py backend/tests/test_customer_360_api.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add backend/app/api/router.py backend/app/api/suppliers.py backend/app/api/purchase_orders.py backend/app/schemas/purchase_order.py backend/tests/test_supplier_api.py backend/tests/test_purchase_order_api.py
git commit -m "feat: add tenant scoped suppliers and order snapshots"
~~~

### Task 3: Inventory ledger and Purchase Order receiving

**Files:**
- Create: backend/app/services/inventory_service.py
- Create: backend/app/api/inventory.py
- Modify: backend/app/api/router.py
- Modify: backend/app/api/purchase_orders.py
- Modify: backend/app/schemas/purchase_order.py
- Test: backend/tests/test_inventory_receiving.py

**Interfaces:**
- receive_purchase_order(db, purchase_order_id, lines, actor_id, business_id, idempotency_key) returns PurchaseReceipt and updates stock atomically.
- POST /api/purchase-orders/{order_id}/receipts accepts idempotency_key, note and items with purchase_order_item_id and quantity.
- GET /api/inventory/products/{product_id} returns stock_quantity, reserved_quantity and available_quantity.
- GET /api/inventory/movements?product_id=&source_type=&limit=&offset= returns tenant-scoped ledger rows.
- Receipt on submitted or partially_received is allowed; over-receipt returns 409; duplicate idempotency returns the original receipt.

- [ ] **Step 1: Write failing receiving and ledger tests**

~~~python
def test_partial_receipt_increases_stock_and_updates_po(client, headers, submitted_po):
    item_id = submitted_po["items"][0]["id"]
    response = client.post(f"/api/purchase-orders/{submitted_po['id']}/receipts", headers=headers, json={"idempotency_key": "rcpt-1", "items": [{"purchase_order_item_id": item_id, "quantity": 2}]})
    assert response.status_code == 201
    assert response.json()["status"] == "partially_received"

def test_receipt_cannot_exceed_ordered_quantity(client, headers, submitted_po):
    response = client.post(f"/api/purchase-orders/{submitted_po['id']}/receipts", headers=headers, json={"idempotency_key": "rcpt-over", "items": [{"purchase_order_item_id": submitted_po["items"][0]["id"], "quantity": 999}]})
    assert response.status_code == 409

def test_receipt_idempotency_does_not_duplicate_stock(client, headers, submitted_po):
    payload = {"idempotency_key": "rcpt-same", "items": [{"purchase_order_item_id": submitted_po["items"][0]["id"], "quantity": 1}]}
    first = client.post(f"/api/purchase-orders/{submitted_po['id']}/receipts", headers=headers, json=payload)
    second = client.post(f"/api/purchase-orders/{submitted_po['id']}/receipts", headers=headers, json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
~~~

- [ ] **Step 2: Run tests and confirm failure**

Run: python -m pytest backend/tests/test_inventory_receiving.py -q

Expected: FAIL because receipt endpoint and inventory service do not exist.

- [ ] **Step 3: Implement transactional inventory service and routes**

Use with_for_update() on PO, PO items and products. Compute quantity_before/after, insert immutable movement, update received_quantity, derive PO status, and commit once. Scope every row by business_id and roll back the full transaction on validation failure.

- [ ] **Step 4: Run focused, lifecycle and tenant tests**

Run: python -m pytest backend/tests/test_inventory_receiving.py backend/tests/test_purchase_order_api.py backend/tests/test_customer_360_api.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add backend/app/services/inventory_service.py backend/app/api/inventory.py backend/app/api/router.py backend/app/api/purchase_orders.py backend/app/schemas/purchase_order.py backend/tests/test_inventory_receiving.py
git commit -m "feat: add purchase receiving and inventory ledger"
~~~

### Task 4: Sales Order reservation, shipment, cancellation and refund

**Files:**
- Create: backend/app/services/order_service.py
- Modify: backend/app/api/sales.py
- Modify: backend/app/schemas/sales.py
- Modify: backend/app/services/inventory_service.py
- Test: backend/tests/test_sales_inventory_lifecycle.py

**Interfaces:**
- transition_sales_order(db, order_id, to_status, actor_id, business_id) returns Order and applies inventory rules atomically.
- confirmed reserves each line; shipped converts reservation into outbound movement; cancelled releases reservation before shipment; refunded creates compensating inbound movement after shipment.
- GET /api/orders/{order_id} exposes payment_status, paid_amount, refunded_amount, reserved_quantity and line snapshots.
- Insufficient available stock and terminal/invalid transitions return 409.

- [ ] **Step 1: Write failing lifecycle tests**

~~~python
def test_confirm_reserves_stock_and_shipped_decrements_on_hand(client, headers, draft_order):
    confirmed = client.post(f"/api/orders/{draft_order['id']}/transition", headers=headers, json={"to_status": "confirmed"})
    assert confirmed.status_code == 200
    shipped = client.post(f"/api/orders/{draft_order['id']}/transition", headers=headers, json={"to_status": "processing"})
    assert shipped.status_code == 200
    shipped = client.post(f"/api/orders/{draft_order['id']}/transition", headers=headers, json={"to_status": "shipped"})
    assert shipped.status_code == 200

def test_confirm_rejects_when_available_stock_is_insufficient(client, headers, order_for_more_than_available):
    response = client.post(f"/api/orders/{order_for_more_than_available['id']}/transition", headers=headers, json={"to_status": "confirmed"})
    assert response.status_code == 409

def test_cancel_releases_reservation(client, headers, confirmed_order):
    response = client.post(f"/api/orders/{confirmed_order['id']}/transition", headers=headers, json={"to_status": "cancelled"})
    assert response.status_code == 200
~~~

- [ ] **Step 2: Run tests and confirm failure**

Run: python -m pytest backend/tests/test_sales_inventory_lifecycle.py -q

Expected: FAIL because existing transitions do not change inventory.

- [ ] **Step 3: Implement order service and transition rules**

Lock products in deterministic product-id order, calculate available stock, update reservations and movements, and write order_events for every transition. Preserve existing statuses and paths; add refunded only from delivered.

- [ ] **Step 4: Run lifecycle and legacy order tests**

Run: python -m pytest backend/tests/test_sales_inventory_lifecycle.py backend/tests/test_order_lifecycle.py backend/tests/test_product_order_api.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add backend/app/services/order_service.py backend/app/services/inventory_service.py backend/app/api/sales.py backend/app/schemas/sales.py backend/tests/test_sales_inventory_lifecycle.py
git commit -m "feat: enforce sales inventory lifecycle"
~~~

### Task 5: Payments, refunds, debt and order events

**Files:**
- Create: backend/app/api/payments.py
- Create: backend/app/schemas/payment.py
- Modify: backend/app/api/router.py
- Modify: backend/app/api/sales.py
- Modify: backend/app/api/purchase_orders.py
- Modify: backend/app/services/order_service.py
- Test: backend/tests/test_order_payments.py

**Interfaces:**
- POST /api/orders/{order_id}/payments accepts idempotency_key, amount, method, reference and status; returns payment plus order summary.
- POST /api/orders/{order_id}/refunds accepts idempotency_key, amount and reason; amount cannot exceed paid amount.
- GET /api/orders/{order_id}/payments returns payments for the active business.
- POST /api/purchase-orders/{order_id}/payments records supplier debt settlement with the same idempotency and overpayment rules.
- GET /api/orders/{order_id}/events and GET /api/purchase-orders/{order_id}/events return append-only history.
- Partial payment sets partial; full payment sets paid; full refund sets refunded.

- [ ] **Step 1: Write failing payment and event tests**

~~~python
def test_partial_payment_updates_order_summary(client, headers, order):
    response = client.post(f"/api/orders/{order['id']}/payments", headers=headers, json={"idempotency_key": "pay-1", "amount": "25", "method": "bank_transfer", "status": "paid"})
    assert response.status_code == 201
    assert response.json()["order"]["payment_status"] == "partial"
    assert response.json()["order"]["paid_amount"] == "25.00"

def test_payment_and_refund_are_idempotent_and_cannot_overpay(client, headers, order):
    payload = {"idempotency_key": "pay-same", "amount": "10", "method": "cash", "status": "paid"}
    first = client.post(f"/api/orders/{order['id']}/payments", headers=headers, json=payload)
    second = client.post(f"/api/orders/{order['id']}/payments", headers=headers, json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["payment"]["id"] == first.json()["payment"]["id"]
~~~

- [ ] **Step 2: Run tests and confirm failure**

Run: python -m pytest backend/tests/test_order_payments.py -q

Expected: FAIL because payment and event routes are not implemented.

- [ ] **Step 3: Implement payment service/routes and event serialization**

Validate order ownership, lock the order for summary updates, enforce idempotency per business, create audit records without payment secrets, and emit workflow events for payment/refund. Use Decimal arithmetic only.

- [ ] **Step 4: Run payment, report and Customer 360 regressions**

Run: python -m pytest backend/tests/test_order_payments.py backend/tests/test_reports_api.py backend/tests/test_customer_360_api.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add backend/app/api/payments.py backend/app/api/router.py backend/app/schemas/payment.py backend/app/api/sales.py backend/app/api/purchase_orders.py backend/app/services/order_service.py backend/tests/test_order_payments.py
git commit -m "feat: add order payments refunds and events"
~~~

### Task 6: Customer 360 timeline and reporting integration

**Files:**
- Modify: backend/app/api/customers.py
- Modify: backend/app/api/reports.py
- Modify: backend/app/schemas/customer.py
- Modify: backend/app/schemas/reports.py
- Test: backend/tests/test_p1_02_timeline_reports.py

**Interfaces:**
- Customer timeline includes Sales Order created/transition/payment/refund events and excludes unlinked Purchase Order events.
- GET /api/reports/inventory returns stock on hand, reserved, available and movement totals by product.
- GET /api/reports/purchase-costs returns spend by supplier and received cost by date range.
- Existing report response fields remain backward compatible.

- [ ] **Step 1: Write failing timeline/report tests**

~~~python
def test_customer_timeline_includes_sales_payment_event_but_not_unlinked_purchase(client, headers, customer, sales_order, purchase_order):
    timeline = client.get(f"/api/customers/{customer.id}/timeline", headers=headers).json()
    event_types = {item["event_type"] for item in timeline["items"]}
    assert "sales_order" in event_types
    assert "order_payment" in event_types
    assert "purchase_order" not in event_types

def test_inventory_report_is_tenant_scoped(client, headers):
    response = client.get("/api/reports/inventory", headers=headers)
    assert response.status_code == 200
    assert "items" in response.json()
~~~

- [ ] **Step 2: Run tests and confirm failure**

Run: python -m pytest backend/tests/test_p1_02_timeline_reports.py -q

Expected: FAIL because timeline and report aggregations do not include new event/ledger data.

- [ ] **Step 3: Implement event projection and report queries**

Join only tenant-owned rows, preserve timeline pagination, aggregate movement quantities by type, and use UTC/date filters consistently with existing reports.

- [ ] **Step 4: Run all backend tests**

Run: python -m pytest backend/tests -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add backend/app/api/customers.py backend/app/api/reports.py backend/app/schemas/customer.py backend/app/schemas/reports.py backend/tests/test_p1_02_timeline_reports.py
git commit -m "feat: connect order events to customer timeline and reports"
~~~

### Task 7: CRM Orders UI

**Files:**
- Modify: frontend/src/App.vue
- Modify: frontend/src/style.css
- Modify: frontend/src/api.js if shared request helpers are needed
- Test: frontend/src/orders-p1-02.test.mjs

**Interfaces:**
- Orders navigation exposes Sales and Purchase tabs without removing existing product/order screens.
- Sales detail shows status, payment summary, items, stock warning, transition buttons, payment/refund form and event history.
- Purchase detail shows supplier, ordered/received quantities, receipt form, payment/debt summary and event history.
- Inventory view shows on-hand/reserved/available and movement history.
- Every mutation displays API error text and disables duplicate submission while pending.

- [ ] **Step 1: Write failing frontend tests**

~~~javascript
test("purchase detail renders partial receipt and payment actions", async () => {
  const screen = renderOrdersWithPurchase({ status: "partially_received", received_quantity: 2, quantity: 5, payment_status: "partial" });
  expect(screen.getByText("Nhận hàng")).toBeTruthy();
  expect(screen.getByText("Thanh toán công nợ")).toBeTruthy();
  expect(screen.getByText("2 / 5")).toBeTruthy();
});

test("sales detail disables confirm when available stock is insufficient", async () => {
  const screen = renderOrdersWithSales({ available_quantity: 0, quantity: 1, status: "draft" });
  expect(screen.getByRole("button", { name: "Xác nhận đơn" }).disabled).toBe(true);
});
~~~

- [ ] **Step 2: Run frontend tests and confirm failure**

Run: pnpm test -- orders-p1-02.test.mjs

Expected: FAIL because the new detail, receipt and payment controls are not present.

- [ ] **Step 3: Implement UI state and API calls**

Add loading/error refs for receipt, payment, refund and transition actions. Render status labels in Vietnamese, keep the inbox layout intact, and use existing apiFetch tenant/auth headers.

- [ ] **Step 4: Run frontend tests and production build**

Run: pnpm test -- orders-p1-02.test.mjs then pnpm build

Expected: PASS and a successful Vite production build.

- [ ] **Step 5: Commit**

~~~powershell
git add frontend/src/App.vue frontend/src/style.css frontend/src/api.js frontend/src/orders-p1-02.test.mjs
git commit -m "feat: add operational sales and purchase order UI"
~~~

### Task 8: End-to-end verification and handoff

**Files:**
- Modify: CRM_KNOWLEDGE_AND_ROADMAP_VI.md
- Create: docs/superpowers/plans/2026-09-06-p1-02-sales-purchase-ops-verification.md

- [ ] **Step 1: Apply migration and verify current head**

Run from the project directory:

~~~powershell
docker compose run --rm backend python -m alembic upgrade head
docker compose run --rm backend python -m alembic current
~~~

Expected: current revision is the new P1-02 migration head and no table is dropped.

- [ ] **Step 2: Run backend tests with repository tests mounted**

~~~powershell
$testsPath = (Resolve-Path .\backend\tests).Path
docker compose run --rm -v "${testsPath}:/app/tests:ro" backend python -m pytest /app/tests -q
~~~

Expected: all backend tests pass.

- [ ] **Step 3: Run frontend tests and build in Docker**

~~~powershell
docker compose run --rm frontend pnpm test -- --run
docker compose run --rm frontend pnpm build
~~~

Expected: all frontend tests pass and the production bundle builds.

- [ ] **Step 4: Perform API smoke test with two tenants**

Create a supplier, product, PO, partial receipt, Sales Order, payment, shipment and refund for business 1. Repeat one read with X-Business-Id 2 and confirm 404/empty results. Confirm Customer 360 timeline contains only linked Sales Order events.

- [ ] **Step 5: Update handoff documentation and commit verification evidence**

Record the final migration revision, test counts, endpoint list, rollback note and known limitations in CRM_KNOWLEDGE_AND_ROADMAP_VI.md and the verification file.

~~~powershell
git add CRM_KNOWLEDGE_AND_ROADMAP_VI.md docs/superpowers/plans/2026-09-06-p1-02-sales-purchase-ops-verification.md
git commit -m "docs: record P1-02 verification and handoff"
~~~
