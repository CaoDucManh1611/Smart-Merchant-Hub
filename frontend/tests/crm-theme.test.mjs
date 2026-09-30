import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("CRM keeps the current neutral Smart Merchant Hub branding", () => {
  assert.match(appSource, /data-testid="crm-brand-mark"[\s\S]*?<svg/);
  assert.match(appSource, /Smart Merchant Hub/);
  assert.doesNotMatch(appSource, /Lunari|Food|food|món ăn|đồ ăn/i);
});

test("CRM uses the Owly-inspired dark rail with a polished salon accent", () => {
  assert.match(styleSource, /--owly-sidebar:\s*#1d2a3d/i);
  assert.match(styleSource, /--owly-sidebar-active:\s*#4f87aa/i);
  assert.match(styleSource, /--salon-accent:\s*#e56a74/i);
  assert.match(styleSource, /\.side\s*\{[\s\S]*?background:[\s\S]*?var\(--owly-sidebar\)/);
  assert.match(styleSource, /\.menu-item\.active\s*\{[\s\S]*?background:\s*var\(--owly-sidebar-active\)/);
  assert.match(styleSource, /\.products-table th,\s*\.products-table td\s*\{[^}]*font-size:\s*0\.92rem/i);
});

test("CRM operational pages use a shared centered content frame", () => {
  assert.match(appSource, /\.products-layout,\s*\.rag-docs-layout,\s*\.rag-chat-layout,\s*\.settings-layout\s*\{[\s\S]*?width:\s*min\(100%,\s*1480px\)[\s\S]*?margin-inline:\s*auto/);
  assert.match(appSource, /\.products-layout\s*>\s*\.product-form,[\s\S]*?max-width:\s*1120px[\s\S]*?margin-inline:\s*auto/);
  assert.match(appSource, /@media\s*\(max-width:\s*900px\)[\s\S]*?\.products-layout,[\s\S]*?width:\s*100%/);
});
