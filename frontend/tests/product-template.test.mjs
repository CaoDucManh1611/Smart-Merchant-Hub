import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const template = readFileSync(new URL("../public/templates/product-import-template.csv", import.meta.url), "utf8");

test("product import offers a downloadable CSV using supported import columns", () => {
  assert.match(app, /href="\/templates\/product-import-template\.csv" download="mau-san-pham\.csv"/);
  assert.match(app, /crmUiText\('Tải file mẫu sản phẩm'\)/);
  assert.match(template, /^Mã sản phẩm,Tên sản phẩm,Giá,Tồn kho,Link sản phẩm,Tên tiếng Anh/);
  assert.match(template, /THAY-MA-001,Áo thun cổ tròn,199000,10/);
});
