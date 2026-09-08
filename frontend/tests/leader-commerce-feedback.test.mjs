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

test("product quantity is labelled plainly rather than as an opening balance", () => {
  assert.match(appSource, /<label>Số lượng\{\{ productForm\.id/);
  assert.doesNotMatch(appSource, /Tồn đầu kỳ/);
});

test("sales order form supports distinct multi-product lines and validates them before submit", () => {
  assert.match(appSource, /items: \[createOrderItem\(\)\]/);
  assert.match(appSource, /function addOrderItem\(\)/);
  assert.match(appSource, /function removeOrderItem\(itemIndex\)/);
  assert.match(appSource, /function orderItemProducts\(itemIndex\)/);
  assert.match(appSource, /Mỗi sản phẩm chỉ được chọn một lần trong đơn bán/);
  assert.match(appSource, /items,\s*\}\),/);
  assert.match(appSource, /Chọn nhiều sản phẩm khác nhau/);
  assert.match(styleSource, /\.order-items-editor/);
});

test("sales orders show the selected customer phone and an append-only process history", () => {
  assert.match(appSource, /Số điện thoại khách hàng/);
  assert.match(appSource, /SĐT khách/);
  assert.match(appSource, /function orderCustomerPhone\(customerId\)/);
  assert.match(appSource, /Xem toàn bộ quy trình/);
  assert.match(appSource, /function chronologicalOrderEvents\(events\)/);
  assert.match(appSource, /Nhật ký bất biến theo thời gian/);
  assert.match(appSource, /không rollback/);
});

test("ticket descriptions occupy a dedicated readable table column", () => {
  assert.match(appSource, /<th>Ticket<\/th><th>Mô tả<\/th>/);
  assert.match(appSource, /class="ticket-description-cell"/);
  assert.match(appSource, /<td colspan="8">/);
  assert.match(styleSource, /\.ticket-description-cell/);
});
