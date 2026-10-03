import test from "node:test";
import assert from "node:assert/strict";
import { customerTagNames, matchesCustomerTagFilter } from "../src/customer-utils.js";
import { customerInsightView } from "../src/customer-insights-utils.js";

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

test("customer insight view distinguishes observed data from unknown interests", () => {
  const unknown = customerInsightView({}, { total_events: 0, top_product_ids: [] });
  assert.equal(unknown.segmentKnown, false);
  assert.equal(unknown.interestsKnown, false);
  assert.deepEqual(unknown.interests, []);

  const view = customerInsightView(
    { segment: "champion", items: [{ product_id: 7, name: "Áo xanh", reason: "Mua gần đây" }] },
    { total_events: 3, top_product_ids: [7, 9] },
    [{ id: 7, name: "Áo xanh" }],
  );
  assert.equal(view.segmentKnown, true);
  assert.equal(view.interestsKnown, true);
  assert.deepEqual(view.interests, [
    { id: 7, name: "Áo xanh", known: true },
    { id: 9, name: "", known: false },
  ]);
  assert.equal(view.recommendations[0].reason, "Mua gần đây");
});
