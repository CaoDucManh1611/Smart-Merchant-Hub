import assert from "node:assert/strict";
import test from "node:test";

import { maskCustomerEmail, maskCustomerName, maskCustomerPhone } from "../src/privacy-utils.js";

test("Customer 360 preserves names while masking email and phone", () => {
  assert.equal(maskCustomerName("Ngô Long Thiên"), "Ngô Long Thiên");
  assert.equal(maskCustomerEmail("phule@gmail.com"), "ph***@gmail.com");
  assert.equal(maskCustomerPhone("+84327262738"), "*******2738");
});
