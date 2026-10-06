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
  assert.match(appSource, /createLocalConnectorPairingCode/);
  assert.match(appSource, /connector-app/);
  assert.match(templateSource, /Shopee Seller Chat/);
  assert.match(templateSource, /Tải bộ ZIP Shopee/);
  assert.match(templateSource, /Tải bộ ZIP TikTok/);
  assert.match(templateSource, /Giải nén ZIP rồi chạy SmartMerchantTikTok\.exe/);
  assert.match(templateSource, /Giải nén ZIP rồi chạy SmartMerchantShopee\.exe/);
  assert.match(templateSource, /Tải ZIP Meta/);
  assert.match(templateSource, /Tải ZIP Instagram/);
  assert.match(appSource, /SmartMerchantMessenger\.zip/);
  assert.match(appSource, /SmartMerchantInstagram\.zip/);
  assert.match(templateSource, /Gói đang dùng/);
  assert.match(templateSource, /Trạng thái thanh toán/);
  assert.match(templateSource, /Dung lượng tra cứu/);
  assert.match(templateSource, /aria-expanded/);
});

test("connector downloads make one ZIP save through the browser", () => {
  const start = appSource.indexOf("async function downloadLocalConnectorApp()");
  const end = appSource.indexOf("async function copyLocalConnectorPairingCode()", start);
  const downloadFunction = appSource.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.match(downloadFunction, /connector-app\/download-ticket.*method: "POST"/);
  assert.match(downloadFunction, /connector-app\/file\?ticket=/);
  assert.match(downloadFunction, /encodeURIComponent\(ticketDetail\.ticket/);
  assert.match(downloadFunction, /headers\.get\("content-type"\)/);
  assert.match(downloadFunction, /filename\\s\*=\\s\*/);
  assert.match(downloadFunction, /showSaveFilePicker/);
  assert.match(downloadFunction, /\.zip/);
  assert.match(downloadFunction, /application\/zip/);
  assert.match(downloadFunction, /fileResponse\.body\.pipeTo\(writable\)/);
  assert.match(downloadFunction, /link\.click\(\)/);
  assert.match(downloadFunction, /URL\.createObjectURL\(blob\)/);
  assert.match(downloadFunction, /signature\[0\] !== 0x50/);
  assert.match(downloadFunction, /setTimeout\(\(\) => URL\.revokeObjectURL\(blobUrl\), 60_000\)/);
  assert.doesNotMatch(downloadFunction, /SmartMerchant\$\{[^}]+\}\.exe/);
});

test("Facebook and Instagram open focused connector dialogs", () => {
  assert.match(templateSource, /channelModalTab === 'facebook' \? 'Kết nối Meta' : channelModalTab === 'instagram' \? 'Kết nối Instagram'/);
  assert.doesNotMatch(templateSource, /meta-oauth-section/);
  assert.match(templateSource, /class="settings-card meta-business-suite-bridge-card"/);
  assert.match(templateSource, /v-if="channelModalTab !== 'instagram'" class="primary-btn bot-connect-submit"[^>]*@click="downloadMessengerConnectorApp"/);
  assert.match(templateSource, /v-if="channelModalTab !== 'facebook'" class="primary-btn bot-connect-submit"[^>]*@click="downloadInstagramConnectorApp"/);
  assert.match(templateSource, /channelModalTab === 'meta' \|\| connection\.channel_type === channelModalTab/);
});
test("shop lifecycle actions expose confirmation, busy and result states", () => {
  assert.match(appSource, /platformShopMutatingIds/);
  assert.match(appSource, /requestConfirmation/);
  assert.match(templateSource, /Đang cập nhật/);
  assert.match(templateSource, /role="status"/);
});

test("auth keeps OTP verification inline in the signup form", () => {
  assert.doesNotMatch(templateSource, /signup-stepper|Xác minh OTP/);
  assert.match(templateSource, /signupStep === 'otp'/);
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
