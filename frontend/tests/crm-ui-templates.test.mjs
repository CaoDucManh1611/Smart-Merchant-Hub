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

test("purchase confirmation is a keyboard-reachable dialog with reduced motion", () => {
  assert.match(app, /class="service-success-dialog" role="dialog" aria-modal="true"/);
  assert.match(app, /@keydown\.esc="closeServiceSuccessDialog"/);
  assert.match(style, /@media \(prefers-reduced-motion: reduce\) \{ \.service-success-dialog \{ animation: none; \} \}/);
});
