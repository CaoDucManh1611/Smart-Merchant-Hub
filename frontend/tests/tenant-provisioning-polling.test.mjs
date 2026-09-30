import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("a waiting tenant automatically refreshes provisioning and opens CRM once ready", () => {
  assert.match(appSource, /let tenantProvisioningPollingTimer = null/);
  assert.match(appSource, /function shouldPollTenantProvisioning\(\)/);
  assert.match(appSource, /function startTenantProvisioningPolling\(\)/);
  assert.match(appSource, /function stopTenantProvisioningPolling\(\)/);
  assert.match(appSource, /window\.setInterval\([\s\S]*?pollTenantProvisioning[\s\S]*?5000/);
  assert.match(appSource, /if \(tenantReady\.value\) \{[\s\S]*?currentTab\.value = "inbox";[\s\S]*?await initializeTenantWorkspace\(\);/);
  assert.match(appSource, /window\.addEventListener\("visibilitychange", handleTenantProvisioningVisibilityChange\)/);
  assert.match(appSource, /window\.removeEventListener\("visibilitychange", handleTenantProvisioningVisibilityChange\)/);
});

