import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { platformAuditActionLabel, platformAuditResourceLabel } from "../src/platform-audit-labels.js";

const platformActions = [
  "platform_plan_created",
  "platform_plan_updated",
  "platform_plan_deleted",
  "platform_subscription_approved",
  "platform_subscription_rejected",
  "platform_subscription_updated",
  "platform_payment_recorded",
  "platform_payment_updated",
  "platform_status_changed",
  "platform_privacy_export_queued",
  "platform_privacy_anonymize_queued",
  "platform_privacy_delete_queued",
  "platform_tenant_schema_registered",
  "platform_tenant_schema_staged",
];

test("all existing platform audit actions display readable Vietnamese labels", () => {
  for (const action of platformActions) {
    const label = platformAuditActionLabel(action);
    assert.notEqual(label, "Hoạt động quản trị khác", action);
    assert.doesNotMatch(label, /platform_|_/);
  }
  assert.equal(platformAuditActionLabel("platform_subscription_approved"), "Đã duyệt đăng ký gói dịch vụ");
});

test("audit records show Vietnamese resource names and safe fallback labels", () => {
  for (const type of ["service_plan", "subscription", "subscription_payment", "business", "data_lifecycle_request", "tenant_schema_registry", "platform"]) {
    assert.notEqual(platformAuditResourceLabel(type), "Đối tượng quản trị", type);
  }
  assert.equal(platformAuditActionLabel("platform_future_event"), "Hoạt động quản trị khác");
  assert.equal(platformAuditResourceLabel("future_resource"), "Đối tượng quản trị");
});

test("platform admin audit renders localized labels instead of raw action codes", () => {
  const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
  const auditSection = appSource.slice(appSource.indexOf('<section id="admin-audit"'), appSource.indexOf('<!-- ===================================================', appSource.indexOf('<section id="admin-audit"')));
  assert.match(auditSection, /platformAuditActionLabel\(log\.action\)/);
  assert.match(auditSection, /platformAuditResourceLabel\(log\.resource_type\)/);
  assert.doesNotMatch(auditSection, /\{\{ log\.action \}\}/);
});
