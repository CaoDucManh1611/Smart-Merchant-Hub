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

test("account verification email editor is not shown in shop settings", () => {
  assert.doesNotMatch(appSource, /auth-email-change-card/);
  assert.doesNotMatch(templateSource, /Email tài khoản nhận xác minh/);
  assert.doesNotMatch(templateSource, /accountEmailChange/);
  assert.match(i18nSource, /Account email for OTP/);
});
