import test from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { customerTagDisplayName, customerTagNames, matchesCustomerTagFilter } from "../src/customer-utils.js";

test("customer tag names omit empty chips", () => {
  assert.deepEqual(customerTagNames({ tags: [" VIP ", "", null, "  "] }), ["VIP"]);
});

test("conversation segment filter matches the selected customer tag", () => {
  const conversation = { customer_tags: ["VIP", "prospect"] };
  assert.equal(matchesCustomerTagFilter(conversation, "VIP", "VIP"), true);
  assert.equal(matchesCustomerTagFilter(conversation, "cold", "cold"), false);
  assert.equal(matchesCustomerTagFilter(conversation, "", ""), true);
});

test("conversation tag filter supports all and any modes", () => {
  const conversation = { customer_tags: ["VIP", "prospect"] };
  assert.equal(matchesCustomerTagFilter(conversation, ["VIP", "prospect"], "all"), true);
  assert.equal(matchesCustomerTagFilter(conversation, ["VIP", "cold"], "all"), false);
  assert.equal(matchesCustomerTagFilter(conversation, ["VIP", "cold"], "any"), true);
  assert.equal(matchesCustomerTagFilter(conversation, ["cold", "warm"], "any"), false);
});

test("Customer 360 groups customers using plain-language labels", () => {
  const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
  assert.match(source, /customers\/rfm\/classify/);
  assert.match(source, /Tự động chia nhóm/);
  assert.doesNotMatch(source, /Phân loại RFM \+ học nhóm AI/);
  assert.match(source, /model_training/);
  assert.match(source, /rfmClassification\.groups/);
  assert.equal(customerTagDisplayName("RFM · Trung thành"), "Khách quen");
  assert.equal(customerTagDisplayName("RFM · AI nhóm 2"), "Nhóm 2");
});
