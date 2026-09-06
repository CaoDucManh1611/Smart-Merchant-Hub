import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("CRM keeps the current neutral Smart Merchant Hub branding", () => {
  assert.match(appSource, /data-testid="crm-brand-mark">SM</);
  assert.match(appSource, /Smart Merchant Hub/);
  assert.doesNotMatch(appSource, /Lunari|Food|food|món ăn|đồ ăn/i);
});

test("CRM uses the red-pink visual system with slightly larger type", () => {
  assert.match(styleSource, /--crm-accent:\s*#d72431/i);
  assert.match(styleSource, /\.menu-item\s*\{[^}]*font-size:\s*14px/i);
  assert.match(styleSource, /\.welcome strong\s*\{[^}]*font-size:\s*22px/i);
  assert.match(styleSource, /\.products-table th,\s*\.products-table td\s*\{[^}]*font-size:\s*0\.92rem/i);
});
