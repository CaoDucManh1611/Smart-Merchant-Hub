import assert from "node:assert/strict";
import test from "node:test";
import { safeProductUrl } from "../src/product-url.js";

test("accepts only usable product HTTP(S) links", () => {
  assert.equal(safeProductUrl(" https://shop.example/pink-shirt "), "https://shop.example/pink-shirt");
  assert.equal(safeProductUrl("http://shop.example/item"), "http://shop.example/item");
  for (const value of ["javascript:alert(1)", "/relative", "https://user:secret@shop.example", "https://", "", "https://shop.example/a b"]) {
    assert.equal(safeProductUrl(value), null);
  }
});
