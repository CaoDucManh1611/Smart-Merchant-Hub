import test from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { customerTagNames, matchesCustomerTagFilter } from "../src/customer-utils.js";

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

test("Customer 360 can classify purchase history with tenant-scoped RFM tags", () => {
  const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
  assert.match(source, /customers\/rfm\/classify/);
  assert.match(source, /Phân loại RFM \+ học nhóm AI/);
  assert.match(source, /model_training/);
  assert.match(source, /rfmClassification\.groups/);
});
