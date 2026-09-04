import test from "node:test";
import assert from "node:assert/strict";
import { customerTagNames } from "../src/customer-utils.js";

test("uses tenant-backed customer tags and omits empty labels", () => {
  assert.deepEqual(
    customerTagNames({ tags: ["khach moi", "", null, "ga"] }),
    ["khach moi", "ga"],
  );
});

test("returns no tags when the profile has no tags", () => {
  assert.deepEqual(customerTagNames({}), []);
});
