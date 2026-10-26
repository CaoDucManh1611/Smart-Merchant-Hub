import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

test("platform admin connection health lists each shop's linked social channels", () => {
  assert.match(appSource, /async function fetchPlatformChannelConnections\(\)/);
  assert.match(appSource, /platform\/channel-connections/);
  assert.match(appSource, /activePlatformSection\.value === "health"/);
  assert.match(templateSource, /v-for="shop in platformChannelConnections"/);
  assert.match(templateSource, /v-for="channel in shop\.channels"/);
  assert.match(templateSource, /platformConnectionStatusLabel\(channel\.status\)/);
  assert.match(templateSource, /shop\.unavailable/);
  assert.match(templateSource, /Chưa ghi nhận lỗi kết nối gần đây/);
});

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
  assert.match(templateSource, /channelModalTab === 'shopee' \? 'Shopee'/);
  assert.match(templateSource, /Tải ứng dụng kết nối Shopee/);
  assert.match(templateSource, /Tải ứng dụng kết nối TikTok/);
  assert.match(templateSource, /Tạo mã kết nối bên dưới, nhập vào ứng dụng rồi đăng nhập Shopee trong trình duyệt\./);
  assert.match(templateSource, /Tạo mã kết nối, nhập vào ứng dụng rồi đăng nhập TikTok Shop trong trình duyệt\./);
  assert.match(appSource, /channels\/\$\{channelType\}\/connector-app\/download-ticket/);
  assert.match(appSource, /channels\/\$\{channelType\}\/connector-app\/file\?ticket=/);
  assert.match(templateSource, /Gói đang dùng/);
  assert.match(templateSource, /Trạng thái thanh toán/);
  assert.match(templateSource, /Dung lượng tra cứu/);
  assert.match(templateSource, /aria-expanded/);
});

test("payment receipt is recorded from its pending approval and shop details keep history only", () => {
  const approvalsStart = templateSource.indexOf('id="admin-approvals"');
  const shopsStart = templateSource.indexOf('id="admin-shops"', approvalsStart);
  const plansStart = templateSource.indexOf("v-show=\"activePlatformSection === 'plans'\"", shopsStart);
  const approvals = templateSource.slice(approvalsStart, shopsStart);
  const shops = templateSource.slice(shopsStart, plansStart);
  assert.ok(approvalsStart >= 0 && shopsStart > approvalsStart && plansStart > shopsStart);
  assert.match(approvals, /platform-approval-payment-form[\s\S]*recordPlatformPayment\(request\)/);
  assert.match(approvals, /platformPaymentDrafts\[request\.subscription_id\]/);
  assert.match(approvals, /Mã giao dịch trên sao kê/);
  assert.match(approvals, /Xác nhận đã thu tiền/);
  assert.match(appSource, /platform\/shops\/\$\{request\.business_id\}\/payments/);
  assert.doesNotMatch(shops, /platform-payment-form|Mã giao dịch đã nhận tiền|Xác nhận đã thu tiền/);
  assert.match(shops, /Lịch sử thanh toán/);
  assert.match(shops, /provider_transaction_id/);
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
  assert.match(templateSource, /channelModalTab === 'facebook' \? 'Kết nối Facebook' : channelModalTab === 'instagram' \? 'Kết nối Instagram'/);
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

test("social channel cards distinguish reserved plan slots from live connectors", () => {
  assert.match(appSource, /detail\.filter\(\(item\) => \["facebook", "instagram", "telegram", "zalo", "tiktok", "shopee"\]/);
  assert.match(appSource, /const socialChannelOnlineCount = computed/);
  assert.match(appSource, /function isSocialChannelOnline\(channelType\)/);
  assert.match(templateSource, /Lượt kết nối đang giữ/);
  assert.match(templateSource, /socialChannelOnlineCount \}\} \/ 6/);
  assert.match(appSource, /function botChannelStatus\(channelType\)/);
  assert.match(templateSource, /botChannelStatus\('telegram'\)/);
  assert.match(templateSource, /metaChannelStatus\('facebook'\)/);
  assert.match(templateSource, /metaChannelStatus\('instagram'\)/);
  assert.match(templateSource, /offline: metaChannelIsOffline\('facebook'\)/);
  assert.match(templateSource, /offline: metaChannelIsOffline\('instagram'\)/);
});

test("paired local connectors must be disconnected before a replacement pairing code", () => {
  assert.match(appSource, /function localConnectorPairingBlocked\(channelType\)/);
  assert.match(appSource, /if \(localConnectorPairingBlocked\(channelType\)\)/);
  assert.match(templateSource, /localConnectorPairingDisabled\('facebook'\)/);
  assert.match(templateSource, /localConnectorPairingDisabled\('instagram'\)/);
  assert.match(templateSource, /localConnectorPairingDisabled\('tiktok'\)/);
  assert.match(templateSource, /localConnectorPairingDisabled\('shopee'\)/);
  assert.match(templateSource, /@click="createLocalConnectorPairingCode\('tiktok'\)"/);
  assert.match(templateSource, /@click="createLocalConnectorPairingCode\('shopee'\)"/);
});

test("sales guidance uses plain language and marks changes that need approval", () => {
  assert.match(templateSource, /Trợ lý tìm câu trả lời trong tài liệu do shop cung cấp/);
  assert.match(templateSource, /Nhu cầu khách hàng/);
  assert.match(templateSource, /So sánh &amp; dự đoán/);
  assert.match(templateSource, /chưa tự thay đổi câu trả lời gửi khách/);
  assert.doesNotMatch(templateSource, /học không giám sát|A\/B và dự đoán/);
});

test("admin, auth and channel layouts have explicit mobile overflow protection", () => {
  assert.match(styleSource, /@media\s*\(max-width:\s*768px\)[\s\S]*?\.platform-admin-tenant-list/);
  assert.match(styleSource, /\.platform-admin-layout[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /\.login-shell[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /\.settings-grid[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /overflow-wrap:\s*anywhere/);
});
