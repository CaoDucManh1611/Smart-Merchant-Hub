import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const i18nSource = fs.readFileSync(new URL("../src/i18n.js", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

test("shop settings can save a private SMTP sender for staff OTP", () => {
  assert.match(appSource, /workspace\/otp-email/);
  assert.match(appSource, /async function fetchShopOtpEmail/);
  assert.match(appSource, /async function saveShopOtpEmail/);
  assert.match(templateSource, /shopOtpEmail\.enabled/);
  assert.match(templateSource, /shopOtpEmail\.from_email/);
  assert.match(templateSource, /shopOtpEmail\.from_name/);
  assert.match(templateSource, /shopOtpEmail\.password/);
  assert.match(templateSource, /v-model="shopOtpEmail\.host"/);
  assert.match(templateSource, /shopOtpEmail\.security/);
  assert.match(templateSource, /STARTTLS · 587/);
  assert.match(templateSource, /SSL\/TLS · 465/);
  assert.match(templateSource, /@change="shopOtpEmail\.port = shopOtpEmail\.security === 'ssl' \? 465 : 587"/);
  assert.match(templateSource, /OTP đăng ký shop mới vẫn dùng email hệ thống/);
  assert.match(i18nSource, /OTP sender email/);
});

test("account email changes require OTP verification before switching the sign-in address", () => {
  assert.match(appSource, /auth\/email-change\/request/);
  assert.match(appSource, /auth\/email-change\/verify/);
  assert.match(appSource, /async function requestAccountEmailChange/);
  assert.match(appSource, /async function verifyAccountEmailChange/);
  assert.match(templateSource, /accountEmailChange\.current_password/);
  assert.match(templateSource, /accountEmailChange\.otp/);
  assert.match(appSource, /Email hiện tại vẫn được giữ cho đến khi xác minh xong/);
  assert.match(i18nSource, /Account email for OTP/);
});
