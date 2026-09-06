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

test("CRM reports UI renders inventory and received purchase costs", () => {
  assert.match(appSource, /\/reports\/inventory/);
  assert.match(appSource, /\/reports\/purchase-costs/);
  assert.match(appSource, /Tồn kho/);
  assert.match(appSource, /Chi phí nhập đã nhận/);
  assert.match(styleSource, /\.order-payment-cell/);
});
