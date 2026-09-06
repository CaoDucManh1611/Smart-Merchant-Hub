import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("CRM orders UI wires Sales Order lifecycle, payment and refund endpoints", () => {
  assert.match(appSource, /\/orders\/\$\{order\.id\}\/transition/);
  assert.match(appSource, /\/orders\/\$\{order\.id\}\/\$\{isRefund \? "refunds" : "payments"\}/);
  assert.match(appSource, /Xác nhận đơn/);
  assert.match(appSource, /Thiếu tồn khả dụng/);
  assert.match(appSource, /Lịch sử/);
});

test("CRM order status picker only offers valid next lifecycle steps", () => {
  assert.match(appSource, /salesStatusTransitions/);
  assert.match(appSource, /salesStatusOptions\(order\)/);
  assert.doesNotMatch(appSource, /v-for="status in salesStatuses"/);
});

test("CRM order history renders meaningful lifecycle and payment events", () => {
  assert.match(appSource, /function orderEventLabel\(event\)/);
  assert.match(appSource, /function orderEventSummary\(event\)/);
  assert.match(appSource, /orderEventLabel\(event\)/);
  assert.match(appSource, /refund_created/);
  assert.doesNotMatch(appSource, /timelineLabel\(\{ event_type: event\.event_type \}\)/);
});

test("CRM order history action is an explicit control that reveals the panel", () => {
  assert.match(appSource, /data-testid="order-history-button"/);
  assert.match(appSource, /@click\.stop="loadSalesOrderEvents\(order\)"/);
  assert.match(appSource, /scrollIntoView\(/);
  assert.match(appSource, /data-testid="order-events-panel"/);
});

test("CRM order form auto-generates the order number and selects an optional conversation", () => {
  assert.match(appSource, /Mã đơn \(tự sinh\)/);
  assert.match(appSource, /orderConversationOptions/);
  assert.match(appSource, /v-for="conversation in orderConversationOptions"/);
  assert.match(appSource, /Không gắn hội thoại/);
  assert.match(appSource, /<select v-model="orderForm\.conversation_id"/);
});

test("CRM orders page remains vertically scrollable when content exceeds the viewport", () => {
  assert.match(styleSource, /\.main\s*\{[^}]*overflow-y:\s*auto/);
  assert.match(styleSource, /\.orders-layout\s*\{[^}]*padding-bottom:/);
});

test("CRM purchase UI wires receipts and supplier debt payment", () => {
  assert.match(appSource, /\/purchase-orders\/\$\{order\.id\}\/receipts/);
  assert.match(appSource, /\/purchase-orders\/\$\{order\.id\}\/payments/);
  assert.match(appSource, /Nhận hàng/);
  assert.match(appSource, /Thanh toán công nợ/);
  assert.match(appSource, /received_quantity/);
});

test("CRM purchase UI selects active suppliers and exposes PO history", () => {
  assert.match(appSource, /fetchSuppliers/);
  assert.match(appSource, /\/suppliers\?status=active/);
  assert.match(appSource, /saveSupplier/);
  assert.match(appSource, /method: "POST"[\s\S]*\/suppliers/);
  assert.match(appSource, /purchaseOrderForm\.supplier_id/);
  assert.match(appSource, /\/purchase-orders\/\$\{purchase\.id\}\/events/);
  assert.match(appSource, /data-testid="purchase-order-history-button"/);
  assert.match(appSource, /data-testid="purchase-order-events-panel"/);
});

test("CRM purchase UI supports partial receiving quantities per PO line", () => {
  assert.match(appSource, /purchaseReceiptDrafts/);
  assert.match(appSource, /v-model\.number="purchaseReceiptDrafts\[item\.id\]"/);
  assert.match(appSource, /Math\.min\(remaining, requested\)/);
});

test("CRM inventory UI records stock changes through the adjustment ledger", () => {
  assert.match(appSource, /productAdjustmentDrafts/);
  assert.match(appSource, /\/inventory\/products\/\$\{product\.id\}\/adjustments/);
  assert.match(appSource, /Điều chỉnh tồn/);
  assert.match(appSource, /Lý do điều chỉnh/);
});

test("CRM inventory adjustment uses an expandable, signed quantity control", () => {
  assert.match(appSource, /openInventoryAdjustment/);
  assert.match(appSource, /closeInventoryAdjustment/);
  assert.match(appSource, /Nhập thêm \(\+\)/);
  assert.match(appSource, /Ghi giảm \(−\)/);
  assert.match(appSource, /Tồn sau điều chỉnh/);
  assert.match(appSource, /inventory-adjustment-panel/);
});

test("CRM reports UI renders inventory and received purchase costs", () => {
  assert.match(appSource, /\/reports\/inventory/);
  assert.match(appSource, /\/reports\/purchase-costs/);
  assert.match(appSource, /Tồn kho/);
  assert.match(appSource, /Chi phí nhập đã nhận/);
  assert.match(styleSource, /\.order-payment-cell/);
});

test("CRM product editor records stock changes through the inventory adjustment API", () => {
  assert.match(appSource, /\/inventory\/products\/\$\{form\.id\}\/adjustments/);
  assert.match(appSource, /Điều chỉnh tồn kho/);
});
