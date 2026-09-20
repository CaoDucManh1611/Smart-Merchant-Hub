import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("new shops wait for tenant provisioning before tenant workspace requests run", () => {
  assert.match(appSource, /tenantProvisioning/);
  assert.match(appSource, /fetchTenantProvisioning/);
  assert.match(appSource, /initializeTenantWorkspace/);
  assert.match(appSource, /const businessId = requireBusinessId\(authUser\.value\)/);
  assert.match(appSource, /onboarding\/shops\/\$\{businessId\}\/provision/);
  assert.match(appSource, /Không gian dữ liệu của shop đang được chuẩn bị/);
  assert.match(appSource, /async function fetchQuotaUsage\(\) \{\s+if \(!tenantReady\.value\)/);
  assert.match(appSource, /:disabled="!tenantReady"/);
  assert.match(styleSource, /\.menu-item:disabled/);
});

test("platform admin can edit the separate chatbot rental price", () => {
  assert.match(appSource, /platformPlanForm/);
  assert.match(appSource, /chatbot_rental_price/);
  assert.match(appSource, /Giá thuê trợ lý chatbot/);
  assert.match(appSource, /\/platform\/plans\/\$\{platformPlanEditingId\.value\}/);
});

test("sidebar and social channels use explicit light and dark theme surfaces", () => {
  assert.match(styleSource, /--leader-sidebar-surface/);
  assert.match(styleSource, /\.crm-app\.crm-dark/);
  assert.match(styleSource, /\.meta-channel-card\.meta-facebook/);
  assert.match(styleSource, /\.meta-channel-card\.meta-instagram/);
});

