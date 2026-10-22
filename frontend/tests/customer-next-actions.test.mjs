import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("Customer 360 uses customer-scoped product suggestions instead of next actions", () => {
  assert.match(appSource, /apiFetch\(`\$\{API_BASE\}\/recommendations`/);
  assert.match(appSource, /customer_id: customerId, limit: 3/);
  assert.match(appSource, /aria-busy="customerProductSuggestionsLoading"/);
  assert.match(appSource, /nothing is sent automatically/i);
  assert.doesNotMatch(appSource, /customers\/\$\{customerId\}\/next-actions/);
  assert.match(appSource, /safeProductUrl\(item\.product_url\)/);
  assert.match(appSource, /Number\(customer360\.value\?\.id\) === Number\(customerId\)/);
  assert.match(appSource, /customerProductSuggestionSourceLabel\(\)/);
  assert.match(appSource, /Chưa ghi nhận khách đồng ý cá nhân hóa · chỉ dùng danh mục/);
  assert.match(appSource, /Khách đã từ chối cá nhân hóa · chỉ dùng danh mục/);
  assert.match(appSource, /formatMoney\(item\.price\)/);
});
