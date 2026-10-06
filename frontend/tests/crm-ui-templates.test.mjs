import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const style = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("product editor sends and safely displays the API product URL", () => {
  assert.match(app, /product_url: safeProductUrl\(productUrl\)/);
  assert.match(app, /:href="safeProductUrl\(product\.product_url\)" target="_blank" rel="noopener noreferrer"/);
  assert.match(app, /Link sản phẩm không hợp lệ; hãy chỉnh lại trước khi sử dụng/);
});

test("local connectors are only visually online after backend heartbeat", () => {
  assert.match(app, /function localConnectorIsOnline\(connection\)/);
  assert.match(app, /connected: localConnectorIsOnline\(shopeeChannelConnection\)/);
  assert.match(app, /connected: localConnectorIsOnline\(tiktokChannelConnection\)/);
});

test("plan payment confirmation is an inline checkout state, not a modal", () => {
  const checkout = readFileSync(new URL("../src/ServiceCheckout.vue", import.meta.url), "utf8");
  assert.match(checkout, /class="service-checkout-page" :aria-label="copy\.pageLabel"/);
  assert.match(checkout, /class="checkout-confirmation" role="status"/);
  assert.doesNotMatch(app, /service-success-dialog/);
  assert.match(checkout, /prefers-reduced-motion:reduce/);
});
