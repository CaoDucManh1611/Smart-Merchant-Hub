import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const app = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const industry = fs.readFileSync(new URL("../src/IndustryModules.vue", import.meta.url), "utf8");
const sales = fs.readFileSync(new URL("../../backend/app/api/sales.py", import.meta.url), "utf8");
const reports = fs.readFileSync(new URL("../../backend/app/api/reports.py", import.meta.url), "utf8");

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

test("appointments, commercial modules, and sales orders share the knowledge-base outer frame", () => {
  assert.match(industry, /<section ref="workspace" class="industry-workspace"/);
  assert.match(app, /class="products-layout orders-layout"/);
  const outerFrame = app.slice(app.indexOf("Give the main operational views one consistent outer surface."));
  assert.match(outerFrame, /\.orders-layout/);
  assert.match(outerFrame, /\.industry-workspace/);
});
