import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const indexSource = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const channelUtilsSource = fs.readFileSync(new URL("../src/channel-utils.js", import.meta.url), "utf8");

test("CRM shell uses neutral product branding instead of legacy food branding", () => {
  assert.match(appSource, /Smart Merchant Hub/);
  assert.doesNotMatch(appSource, /Lunari Food|Combo gà sốt phô mai|Món yêu thích|Tokbokki|Khoai tây lắc/);
  assert.doesNotMatch(styleSource, /Patrick Hand|lunari-logo|food-cup|side-heart|decor-heart/);
  assert.doesNotMatch(indexSource, /Lunari/);
});

test("CRM shell exposes the product's operational navigation", () => {
  assert.match(appSource, />Inbox &amp; Customer 360</);
  assert.match(appSource, />Đơn bán</);
  assert.match(appSource, />Đơn nhập</);
  assert.match(appSource, />Báo cáo</);
  assert.match(appSource, /data-testid="crm-brand-mark"/);
});

test("sidebar groups customer, operations, AI, and system navigation", () => {
  assert.match(appSource, /class="menu-group menu-group-customer"/);
  assert.match(appSource, /class="menu-group menu-group-operations"/);
  assert.match(appSource, /class="menu-group menu-group-ai"/);
  assert.match(appSource, /class="menu-group menu-group-system"/);
  assert.match(appSource, /class="menu-group-label"/);
  assert.doesNotMatch(appSource, /<b>Customer 360<\/b>/);
});

test("AI Rule Lab supports creating and filtering explainable rule suggestions", () => {
  assert.match(appSource, /aiRuleForm/);
  assert.match(appSource, /createRuleSuggestion/);
  assert.match(appSource, /ruleSuggestionFilter/);
  assert.match(appSource, /Lưu đề xuất rule/);
  assert.match(appSource, /Chờ duyệt/);
  assert.match(appSource, /Đã duyệt/);
  assert.match(appSource, /Từ chối/);
  assert.match(appSource, /suggestion.proposed_action/);
});

test("AI experiments can be created from the AI Lab", () => {
  assert.match(appSource, /experimentForm/);
  assert.match(appSource, /createExperiment/);
  assert.match(appSource, /Tạo experiment/);
  assert.match(appSource, /experiment.variants/);
  assert.match(appSource, /experiment.status/);
});

test("AI navigation keeps the Rule Lab and Assistant under one group", () => {
  assert.match(appSource, /class="ai-submenu"/);
  assert.match(appSource, />AI Rule Lab</);
  assert.match(appSource, />AI Assistant</);
  assert.match(styleSource, /\.menu-group-ai/);
  assert.match(styleSource, /\.ai-submenu/);
});

test("Customer 360 labels the complete profile timeline", () => {
  assert.match(appSource, /identity:\s*"Danh tính đa kênh"/);
  assert.match(appSource, /fact:\s*"Customer Fact"/);
  assert.match(appSource, /ticket_event:\s*"Lịch sử ticket"/);
  assert.match(appSource, /event\.occurred_at/);
  assert.match(appSource, /event\.created_by/);
});

test("Zalo has its own channel label and branded icon fallback", () => {
  assert.match(channelUtilsSource, /zalo:\s*["']ZALO["']/);
  assert.match(styleSource, /\.social-icon\.zalo/);
});

test("inventory stock summary separates total, available, and reserved quantities", () => {
  assert.match(appSource, /class="inventory-summary"/);
  assert.match(appSource, /class="inventory-total"/);
  assert.match(appSource, /class="inventory-available"/);
  assert.match(appSource, /class="inventory-reserved"/);
  assert.doesNotMatch(appSource, /<strong>\{\{ product\.stock_quantity \}\}<\/strong><small>Khả dụng:/);
});

test("sidebar collapse control toggles a real collapsed state", () => {
  assert.match(appSource, /sidebarCollapsed/);
  assert.match(appSource, /toggleSidebar/);
  assert.match(appSource, /sidebar-collapsed/);
  assert.match(appSource, /@click="toggleSidebar"/);
  assert.match(appSource, /aria-expanded/);
});

test("top workspace controls are interactive and searchable", () => {
  assert.match(appSource, /class="top-search-input"/);
  assert.match(appSource, /@keydown\.enter="runGlobalSearch"/);
  assert.match(appSource, /function runGlobalSearch/);
  assert.match(appSource, /@click="openNotifications"/);
  assert.match(appSource, /function openNotifications/);
  assert.match(appSource, /@click="openSettings"/);
});

test("inbox uses a polished filter toolbar instead of a native multi-select", () => {
  assert.match(appSource, /class="inbox-toolbar"/);
  assert.match(appSource, /class="inbox-filter-panel"/);
  assert.match(appSource, /class="tag-chip-list"/);
  assert.match(appSource, /toggleTagFilter/);
  assert.match(appSource, /class="segment-control"/);
  assert.doesNotMatch(appSource, /class="segment-filter" multiple/);
});

test("inbox header and conversation rows expose readable status hierarchy", () => {
  assert.match(appSource, /class="inbox-title-copy"/);
  assert.match(appSource, /class="inbox-title-count"/);
  assert.match(appSource, /class="conversation-status"/);
  assert.match(appSource, /class="conversation-channel-pill"/);
  assert.match(styleSource, /\.inbox-filter-panel/);
  assert.match(styleSource, /\.conversation-channel-pill/);
});
