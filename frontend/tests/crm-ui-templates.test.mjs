import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const style = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("opening reply templates keeps the composer expanded and focuses the picker", () => {
  const toggle = app.slice(app.indexOf('function insertReplyTemplate()'), app.indexOf('function applyReplyTemplate()'));
  assert.match(toggle, /replyTemplatePickerOpen.value = !replyTemplatePickerOpen.value/);
  assert.match(toggle, /nextTick.*#reply-template-picker select.*focus/);
  assert.match(app, /'has-composer-content': pendingMedia.length \|\| voiceRecording \|\| replyTemplatePickerOpen/);
});

test("reply templates append editable drafts without sending messages or creating orders", () => {
  const handler = app.slice(app.indexOf('function applyReplyTemplate()'), app.indexOf('async function sendComposerContent()'));
  assert.match(handler, /if \(!canReplyToSelectedConversation.value\) return/);
  assert.match(handler, /draft.value =/);
  assert.match(handler, /\[điền thông tin\]/);
  assert.doesNotMatch(handler, /apiFetch|sendUnifiedReply|saveOrder/);
  assert.match(app, /aria-controls="reply-template-picker"/);
});

test("manual sales entry uses existing product pricing and draft creation without recording payment", () => {
  const form = app.slice(app.indexOf('<details class="report-panel manual-order-panel"'), app.indexOf('<details class="report-panel order-import-panel"'));
  assert.match(form, /Nhập hóa đơn/);
  assert.match(form, /@submit.prevent="saveOrder"/);
  assert.match(form, /orderItemProducts\(index\)/);
  assert.match(form, /formatMoney\(orderFormTotal\)/);
  assert.match(form, /Xác nhận tạo đơn nháp/);
  assert.doesNotMatch(form, /recordPayment|recordOrderPayment/);
  assert.match(app, /async function saveOrder\(\) \{\s+if \(orderSaving.value\) return;/);
});

test("payment re-entry is prominent above the plan catalogue and retains the existing action", () => {
  const entry = app.indexOf('class="service-payment-entry"');
  assert.ok(entry > 0 && entry < app.indexOf('<ServicePricing', entry));
  assert.match(app, /class="service-payment-entry" @click="resumeCheckoutRequest"/);
  assert.match(app, /service-payment-entry:focus-visible/);
  assert.match(app, /\.service-payment-entry \{ transition:none; \}/);
});

test("selecting a plan with a pending request restores its frozen quote before submission", () => {
  const select = app.slice(app.indexOf('function selectServicePlan('), app.indexOf('function servicePlanCodeForPurchase('));
  assert.match(select, /\['awaiting_payment', 'pending'\]\.includes\(existing\?\.status\) && existing\.plan_code === servicePlanCodeForPurchase\(planCode\)/);
  assert.match(select, /serviceCheckoutRequest\.value = existing/);
  assert.match(select, /serviceRequestSubmitted\.value = true/);
  assert.match(select, /void loadServicePayment\(existing\.status === 'awaiting_payment'\)/);
});

test("paid checkout creates a QR first, then lets the shop report payment or cancel", () => {
  const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
  const checkout = readFileSync(new URL("../src/ServiceCheckout.vue", import.meta.url), "utf8");
  assert.match(app, /if \(detail\.status === "awaiting_payment"\) await loadServicePayment\(true\)/);
  assert.match(app, /payment\/confirm/);
  assert.match(app, /subscription\/\$\{request\.id\}\/cancel/);
  assert.match(checkout, /@click="emit\('confirm-payment'\)"/);
  assert.match(checkout, /Hủy đơn thanh toán và chọn gói khác/);
  assert.match(checkout, /status !== 'awaiting_payment'/);
  assert.match(app, /Number\(request\.quoted_amount\) > 0 && !request\.payment_received/);
  assert.match(app, /customer_reported_payment \? t\('Khách báo đã thanh toán/);
});

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
  assert.match(checkout, /checkout-transfer-layout/);
  assert.match(checkout, /class="checkout-summary-art"[^>]*aria-hidden="true"/);
  assert.match(checkout, /\.checkout-card,\.checkout-qr-card \{ animation:none; \}/);
});

test("login password visibility toggles without replacing the bound password field", () => {
  const passwordField = app.slice(app.indexOf('class="login-password-field"'), app.indexOf('class="login-options-row"'));
  assert.match(passwordField, /:type="loginPasswordVisible \? 'text' : 'password'"/);
  assert.match(passwordField, /v-model="loginForm\.password"/);
  assert.match(passwordField, /:aria-pressed="loginPasswordVisible"/);
  assert.match(passwordField, /@click="loginPasswordVisible = !loginPasswordVisible"/);
  assert.match(style, /\.login-password-control \{ display:grid; grid-template-columns:minmax\(0,1fr\) 40px;/);
  assert.match(style, /\.login-password-control input::-ms-reveal \{ display:none; \}/);
  assert.match(style, /\.login-password-toggle \{ position:relative;.*grid-column:2; grid-row:1;/);
  assert.match(style, /\.login-password-toggle:focus-visible/);
});

test("pending payment review keeps the status and cancel action in a responsive row", () => {
  const checkout = readFileSync(new URL("../src/ServiceCheckout.vue", import.meta.url), "utf8");
  assert.match(checkout, /status === 'pending'\" class="checkout-payment-review-row"/);
  assert.match(checkout, /\.checkout-payment-review-row \{ display:flex; flex-wrap:wrap;/);
  assert.match(checkout, /\.checkout-payment > small \{ display:block;/);
  assert.match(checkout, /status === 'awaiting_payment' && payment\?\.status === 'pending'/);
});
