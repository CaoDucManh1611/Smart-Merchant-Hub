import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("leader feedback removes redundant header-level new-item controls", () => {
  assert.doesNotMatch(appSource, /\+ Sản phẩm mới/);
  assert.doesNotMatch(appSource, /\+ Tạo đơn hàng/);
  assert.doesNotMatch(appSource, /\+ Tạo lead/);
  assert.doesNotMatch(appSource, /\+ Tạo ticket/);
  assert.doesNotMatch(appSource, /\+ Tạo PO/);
  assert.doesNotMatch(appSource, /\+ Workflow mới/);
});

test("product workspace is processing-only rather than an intake form", () => {
  assert.match(appSource, /data-testid="products-processing-only"/);
  assert.match(appSource, /Chế độ xử lý sản phẩm/);
  assert.doesNotMatch(appSource, /<form class="product-form"/);
  assert.doesNotMatch(appSource, /Tồn đầu kỳ/);
});

test("sales order workspace keeps lifecycle processing without an intake form", () => {
  const ordersStart = appSource.indexOf('<section v-if="currentTab === \'orders\'"');
  const ordersEnd = appSource.indexOf('<section v-if="currentTab === \'purchase-orders\'"', ordersStart);
  const ordersView = appSource.slice(ordersStart, ordersEnd);
  assert.match(ordersView, /data-testid="orders-processing-only"/);
  assert.match(ordersView, /Chế độ xử lý đơn bán/);
  assert.doesNotMatch(ordersView, /<form class="product-form order-form"/);
  assert.match(ordersView, /transitionSalesOrder/);
  assert.match(ordersView, /recordSalesPayment/);
});

test("sales orders show the selected customer phone and an append-only process history", () => {
  assert.match(appSource, /SĐT khách/);
  assert.match(appSource, /function orderCustomerPhone\(customerId\)/);
  assert.match(appSource, /Xem toàn bộ quy trình/);
  assert.match(appSource, /function chronologicalOrderEvents\(events\)/);
  assert.match(appSource, /Nhật ký bất biến theo thời gian/);
  assert.match(appSource, /không rollback/);
});

test("ticket descriptions occupy a dedicated readable table column", () => {
  assert.match(appSource, /<th>Phiếu hỗ trợ<\/th><th>Mô tả<\/th>/);
  assert.match(appSource, /class="ticket-description-cell"/);
  assert.match(appSource, /<td colspan="8">/);
  assert.match(styleSource, /\.ticket-description-cell/);
});
