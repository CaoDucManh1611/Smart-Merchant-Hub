import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { normalizeProductUrl } from "../src/product-link-utils.js";

const app = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const industry = fs.readFileSync(new URL("../src/IndustryModules.vue", import.meta.url), "utf8");
const sales = fs.readFileSync(new URL("../../backend/app/api/sales.py", import.meta.url), "utf8");
const onboarding = fs.readFileSync(new URL("../../backend/app/api/onboarding.py", import.meta.url), "utf8");
const reports = fs.readFileSync(new URL("../../backend/app/api/reports.py", import.meta.url), "utf8");

test("product URLs accept safe HTTP links and reject unsafe or malformed schemes", () => {
  assert.equal(normalizeProductUrl(" https://shop.example/products/1 "), "https://shop.example/products/1");
  assert.equal(normalizeProductUrl("http://shop.example/item"), "http://shop.example/item");
  assert.equal(normalizeProductUrl("javascript:alert(1)"), null);
  assert.equal(normalizeProductUrl("https://user:pass@shop.example/item"), null);
  assert.equal(normalizeProductUrl("not a URL"), null);
  assert.equal(normalizeProductUrl(""), "");
});

test("downloadable commerce templates match the current import contracts", () => {
  const productTemplate = fs.readFileSync(new URL("../public/templates/product-catalog-template.csv", import.meta.url), "utf8").trim().split(",");
  const orderTemplate = fs.readFileSync(new URL("../public/templates/sales-orders-template.csv", import.meta.url), "utf8").trim().split(",");
  assert.deepEqual(productTemplate, [
    "sku", "name", "name_en", "description", "price", "stock_quantity", "status",
    "category", "suitable_for", "colors", "sizes", "keywords",
  ]);
  assert.deepEqual(orderTemplate, ["order_number", "customer_id", "sku", "quantity", "conversation_id"]);
  assert.match(sales, /"sku": "sku"[\s\S]*"name": "name"[\s\S]*"stock_quantity": "stock_quantity"/);
  assert.match(sales, /"category": "category"[\s\S]*"suitable_for": "suitable_for"[\s\S]*"keywords": "keywords"/);
  for (const field of ["order_number", "customer_id", "sku", "quantity", "conversation_id"]) {
    assert.match(sales, new RegExp(`"${field}": "${field}"`));
  }
});

test("product links use metadata and safe external-link attributes", () => {
  assert.match(app, /normalizeProductUrl\(form\.product_url\)/);
  assert.match(app, /metadata\.product_url = productUrl/);
  assert.match(app, /rel="noopener noreferrer"/);
  assert.match(app, /Liên kết sản phẩm không hợp lệ/);
});

test("local connector UI waits for backend pairing state and offers retry", () => {
  assert.match(onboarding, /connector_paired=channel\.status == "active"/);
  assert.match(app, /connection\?\.connector_paired/);
  assert.match(app, /@click="createLocalConnectorPairingCode"/);
  assert.match(app, /localConnectorExpiresAt/);
  assert.match(app, /CHỜ GHÉP NỐI/);
});

test("service success dialog supports keyboard and reduced motion", () => {
  assert.match(app, /role="dialog" aria-modal="true" aria-labelledby="service-success-dialog-title"/);
  assert.match(app, /handleServiceSuccessDialogKeydown/);
  assert.match(app, /event\.key === "Escape"/);
  const styles = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
  assert.match(styles, /prefers-reduced-motion: reduce/);
});

test("commerce exports are tenant-scoped snapshots and exclude Shopee", () => {
  assert.match(sales, /@router\.get\("\/products\/export\.csv"\)/);
  assert.match(sales, /sku_snapshot.*on_hand_snapshot/);
  assert.match(sales, /@router\.get\("\/orders\/export\.csv", dependencies=\[Depends\(require_admin_access\)\]\)/);
  assert.match(sales, /func\.lower\(Conversation\.channel\) != "shopee"/);
});

test("order CSV import previews rows and only creates idempotent drafts", () => {
  assert.match(sales, /@router\.post\("\/orders\/import"/);
  assert.match(sales, /preview: bool = Query\(default=False\)/);
  assert.match(sales, /event_type="imported_as_draft", to_status="draft"/);
  assert.match(sales, /correlation_id=import_key/);
  assert.match(app, /\/orders\/import\?preview=true/);
  assert.match(app, /importDraftOrders/);
  assert.match(app, /orderImportPreview\?\.errors/);
});

test("commerce reports share filters, scope Shopee, and open every source type", () => {
  assert.match(reports, /@router\.get\("\/reports\/commerce"\)/);
  assert.match(reports, /Kênh Shopee nằm ngoài phạm vi/);
  assert.match(app, /\/reports\/commerce\$\{suffix\}/);
  assert.match(app, /\['order', 'appointment', 'quote', 'invoice'\]/);
  assert.match(industry, /kind === "invoice"/);
  assert.match(industry, /includeRequestedRecord\(invoiceData, "\/commercial\/invoices/);
});

test("invoice collection retries reuse a durable idempotency key until saved", () => {
  assert.match(industry, /idempotency_key: attempt\.key/);
  assert.match(industry, /paymentAttempts\[invoice\.id\]/);
  assert.match(industry, /delete paymentAttempts\[invoice\.id\]/);
});
