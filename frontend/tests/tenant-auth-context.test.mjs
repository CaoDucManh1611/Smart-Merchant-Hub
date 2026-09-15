import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("frontend never selects a tenant with a hardcoded id or header", () => {
  assert.doesNotMatch(appSource, /BUSINESS_ID\s*=\s*["']1["']/);
  assert.doesNotMatch(appSource, /X-Business-Id/);
});

test("tenant API paths are derived from the authenticated shop", () => {
  assert.match(appSource, /activeBusinessId|requireBusinessId/);
  assert.match(appSource, /requireBusinessId\(authUser\.value\)/);
});
