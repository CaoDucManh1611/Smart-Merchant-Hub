import assert from "node:assert/strict";
import fs from "node:fs";
import QRCode from "qrcode";
import { buildVietQrPreviewPayload } from "../src/vietqr-preview.js";
import { mergeVietnamBankOptions, VIETNAM_BANK_OPTIONS } from "../src/vietnam-banks.js";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const backendSource = fs.readFileSync(new URL("../../backend/app/services/shop_bank_transfer.py", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

test("shop bank check validates local QR data without claiming bank verification", () => {
  assert.match(appSource, /async function validateShopBankTransfer/);
  assert.doesNotMatch(appSource, /workspace\/bank-transfer\/validate/);
  assert.match(appSource, /const qrPayload = shopBankTransferQrPayload\.value/);
  assert.match(appSource, /beneficiary_verified: false/);
  assert.match(backendSource, /beneficiary_verified": False/);
  assert.match(backendSource, /Chưa xác minh tên chủ tài khoản với ngân hàng/);
  assert.match(templateSource, /Kiểm tra định dạng và QR/);
  assert.match(templateSource, /shopBankTransferQrPreview/);
  assert.match(templateSource, /Không chuyển tiền theo mã mẫu này/);
  assert.match(appSource, /QRCode\.toDataURL\(qrPayload/);
  assert.match(templateSource, /v-for="bank in shopBankTransferBankOptions"/);
  assert.match(templateSource, /v-if="shopBankTransferQrPreview" class="shop-bank-transfer-preview"/);
  assert.match(appSource, /Vui lòng chọn ngân hàng\./);
  assert.match(appSource, /Chưa xác minh tên chủ tài khoản với ngân hàng/);
});

test("sample VietQR payload matches the backend validation fixture", () => {
  assert.equal(
    buildVietQrPreviewPayload("970403", "1234567890", "Test Account"),
    "00020101021138540010A00000072701240006970403011012345678900208QRIBFTTA5303704540410005802VN62120808SMHCHECK63046328",
  );
  assert.equal(buildVietQrPreviewPayload("", "1234567890", "Test Account"), "");
  assert.equal(buildVietQrPreviewPayload("970403", "12345", "Test Account"), "");
  assert.equal(buildVietQrPreviewPayload("970403", "1234567890", ""), "");
});

test("sample VietQR renders to a local PNG data URL", async () => {
  const payload = buildVietQrPreviewPayload("970403", "1234567890", "Test Account");
  const image = await QRCode.toDataURL(payload, { errorCorrectionLevel: "M", margin: 2, width: 240 });
  assert.match(image, /^data:image\/png;base64,/);
});

test("bank selector has a transfer-enabled fallback and merges server bank options", () => {
  assert.equal(VIETNAM_BANK_OPTIONS.length, 47);
  assert.equal(mergeVietnamBankOptions([]).length, 47);
  assert.ok(mergeVietnamBankOptions([]).some((bank) => bank.bin === "970429"));
  assert.ok(mergeVietnamBankOptions([]).some((bank) => bank.bin === "970463"));
  assert.equal(mergeVietnamBankOptions([{ bin: "999999", name: "Extra Bank" }]).length, 48);
});

