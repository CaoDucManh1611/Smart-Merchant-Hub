# Task 9 — Chuyển commerce, inventory và supplier

## Files
- Modify `backend/app/api/sales.py`, `inventory.py`, `suppliers.py`.
- Modify `backend/app/services/chatbot_agent.py`, `customer_collection_flow.py`, `customer_order_service.py`, `order_service.py`, `inventory_service.py`.
- Modify `backend/app/models/sales.py`, `inventory.py`, `supplier.py`.
- Create `backend/tests/test_tenant_commerce_isolation.py`.

## Interfaces
- Product/order/inventory lookup uses schema-local IDs only.
- Idempotency keys are unique within a tenant schema and cannot resolve an object from another schema.

## Required work
- Write failing tests for equal SKU/order codes in two shops, cancellation by product name within the authenticated shop, inventory reservation rollback and cross-shop order lookup denial.
- Route sales/inventory/supplier APIs and chatbot commerce services through tenant sessions.
- Remove platform DB access from price, stock, draft, OTP-confirmation and cancellation state-machine paths.
- Run `pytest -q tests/test_tenant_commerce_isolation.py tests/test_customer_order_actions.py tests/test_product_order_api.py tests/test_sales_inventory_lifecycle.py tests/test_supplier_api.py`.
- Commit `refactor: isolate commerce and inventory by shop schema`.

## Global constraints
Server-generated `shop_<business_id>` schemas only; transaction-local search_path; no tenant content/tokens in platform DB/logs; TDD required. Reuse the tenant-session seam established by Task 8 and do not edit Task 5-7 auth/platform-owned files.

