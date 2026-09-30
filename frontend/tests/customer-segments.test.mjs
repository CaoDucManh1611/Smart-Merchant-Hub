import test from "node:test";
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
