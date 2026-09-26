import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

test("platform admin loads shop subscription, payment and quota details through existing APIs", () => {
  assert.match(appSource, /const platformShopDetails = ref\(\{\}\)/);
  assert.match(appSource, /platform\/shops\/\$\{shop\.id\}\/subscription/);
  assert.match(appSource, /platform\/shops\/\$\{shop\.id\}\/payments/);
  assert.match(appSource, /platform\/shops\/\$\{shop\.id\}\/usage/);
  assert.match(appSource, /subscriptionResponse\.status === 404/);
  assert.match(appSource, /platform\/plans\/\$\{plan\.id\}/);
  assert.match(appSource, /deletePlatformPlan/);
  assert.match(appSource, /Tạo cấu hình trước/);
  assert.match(appSource, /delivery: "url"/);
  assert.match(appSource, /:href="tiktokBridgeDownloadUrl" download="SmartMerchantTikTok\.zip"/);
  assert.match(templateSource, /Gói đang dùng/);
  assert.match(templateSource, /Trạng thái thanh toán/);
  assert.match(templateSource, /Dung lượng tra cứu/);
  assert.match(templateSource, /aria-expanded/);
});
test("shop lifecycle actions expose confirmation, busy and result states", () => {
  assert.match(appSource, /platformShopMutatingIds/);
  assert.match(appSource, /requestConfirmation/);
  assert.match(templateSource, /Đang cập nhật/);
  assert.match(templateSource, /role="status"/);
});

test("auth and onboarding communicate the current step", () => {
  assert.match(templateSource, /signup-stepper/);
  assert.match(templateSource, /Thông tin shop/);
  assert.match(templateSource, /Xác minh OTP/);
  assert.match(templateSource, /Chọn gói/);
  assert.match(templateSource, /autocomplete="one-time-code"/);
});

test("channel cards expose quota blockers and normalized provider states", () => {
  assert.match(appSource, /channelCapacityState/);
  assert.match(appSource, /connectionStateMeta/);
  assert.match(templateSource, /channel-capacity-alert/);
  assert.match(templateSource, /Nâng cấp gói/);
});

test("AI language keeps retrieval, topic grouping and experiments honest", () => {
  assert.match(templateSource, /tra cứu kho kiến thức/i);
  assert.match(templateSource, /chưa phải học không giám sát hoàn chỉnh/i);
  assert.match(templateSource, /A\/B.*đang thử nghiệm/i);
  assert.match(templateSource, /chưa tự thay đổi bot/i);
});

test("admin, auth and channel layouts have explicit mobile overflow protection", () => {
  assert.match(styleSource, /@media\s*\(max-width:\s*768px\)[\s\S]*?\.platform-admin-tenant-list/);
  assert.match(styleSource, /\.platform-admin-layout[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /\.login-shell[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /\.settings-grid[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /overflow-wrap:\s*anywhere/);
});
