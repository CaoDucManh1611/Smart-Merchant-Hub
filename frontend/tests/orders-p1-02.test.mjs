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
