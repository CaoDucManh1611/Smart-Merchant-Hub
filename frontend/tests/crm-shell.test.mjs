import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const indexSource = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const channelUtilsSource = fs.readFileSync(new URL("../src/channel-utils.js", import.meta.url), "utf8");
const apiClientSource = fs.readFileSync(new URL("../src/api-client.js", import.meta.url), "utf8");
const authContextSource = fs.readFileSync(new URL("../src/auth-context.js", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

function openingButtonTags(source) {
  const start = source.indexOf("<template>");
  const end = source.lastIndexOf("</template>");
  const template = source.slice(start, end);
  const tags = [];
  let cursor = 0;

  while (cursor < template.length) {
    const tagStart = template.indexOf("<button", cursor);
    if (tagStart < 0) break;
    let quote = null;
    let tagEnd = -1;
    for (let index = tagStart + 7; index < template.length; index += 1) {
      const char = template[index];
      if (quote) {
        if (char === quote && template[index - 1] !== "\\") quote = null;
      } else if (char === "\"" || char === "'") {
        quote = char;
      } else if (char === ">") {
        tagEnd = index + 1;
        break;
      }
    }
    assert.notEqual(tagEnd, -1, "button opening tag must be closed");
    tags.push(template.slice(tagStart, tagEnd));
    cursor = tagEnd;
  }

  return tags;
}

test("CRM shell uses neutral product branding instead of legacy food branding", () => {
  assert.match(appSource, /Smart Merchant Hub/);
  assert.doesNotMatch(appSource, /Lunari Food|Combo gà sốt phô mai|Món yêu thích|Tokbokki|Khoai tây lắc/);
  assert.doesNotMatch(styleSource, /Patrick Hand|lunari-logo|food-cup|side-heart|decor-heart/);
  assert.doesNotMatch(indexSource, /Lunari/);
});

test("inbox starts compact and loads further conversation pages on scroll", () => {
  assert.match(appSource, /const INBOX_PAGE_SIZE = 10/);
  assert.match(appSource, /inboxHasMore/);
  assert.match(appSource, /function handleInboxConversationScroll\(event\)/);
  assert.match(appSource, /@scroll\.passive="handleInboxConversationScroll"/);
  assert.match(appSource, /Cuộn xuống để tải thêm/);
  assert.match(appSource, /Đã tải \{\{ conversations\.length \}\}\/\{\{ inboxConversationTotal/);
  assert.match(styleSource, /overscroll-behavior: contain/);
  assert.match(templateSource, /<details class="inbox-filter-disclosure">/);
  assert.doesNotMatch(templateSource, /<details class="inbox-filter-disclosure" open>/);
});

test("inbox supports confirmed bulk assignment for selected conversations", () => {
  assert.match(appSource, /\/conversations\/bulk-assignment/);
  assert.match(appSource, /conversation_ids: conversationIds, assigned_user_id: assignedUserId/);
  assert.match(templateSource, /class="inbox-bulk-toolbar"/);
  assert.match(templateSource, /toggleBulkConversationSelection/);
  assert.match(appSource, /Chỉ có thể phân công tối đa 100 hội thoại cùng lúc/);
  assert.match(appSource, /requestConfirmation\([\s\S]*?Phân công các hội thoại đã chọn/);
});

test("inbox shows blue unread badges and red badges for urgent customer work", () => {
  assert.match(appSource, /criticalConversationNotificationCount/);
  assert.match(appSource, /pending_order_confirmation_count/);
  assert.match(appSource, /function conversationUrgentCount/);
  assert.match(templateSource, /class="conversation-unread urgent"/);
  assert.match(styleSource, /\.conversation-unread\.urgent/);
  assert.match(styleSource, /background: var\(--salon-accent\)/);
});

test("customer 360 shows bought products and staff can process a customer-confirmed invoice", () => {
  assert.match(appSource, /pending_confirmation: \["confirmed", "cancelled"\]/);
  assert.match(appSource, /pending_confirmation: "Chờ nhân viên xác nhận"/);
  assert.match(appSource, /customerConfirmedOrderCount/);
  assert.match(appSource, /confirmCustomerOrder/);
  assert.match(templateSource, /Đồng ý đơn/);
  assert.match(templateSource, /class="customer-order-items"/);
  assert.match(templateSource, /order\.items\.map/);
});

test("service plans declare channel limits without preselecting channels and include the 3-platform tier", () => {
  assert.match(appSource, /code: "scale"/);
  assert.match(appSource, /FALLBACK_SERVICE_PLANS\.filter\(\(plan\) => !returnedCodes\.has\(plan\.code\)\)/);
  assert.match(templateSource, /plan\.max_channels \}\} nền tảng kết nối/);
  assert.match(templateSource, /Không chọn nền tảng tại đây để tránh lệch dữ liệu/);
  assert.match(templateSource, /Nâng cấp không cần hủy gói hiện tại/);
  assert.doesNotMatch(templateSource, /class="service-channel-picker"/);
});

test("business hours support dated exceptions and use the knowledge-base label consistently", () => {
  assert.match(appSource, /specialBusinessDates/);
  assert.match(templateSource, /Giờ đặc biệt/);
  assert.match(templateSource, /hệ thống không tự nhắn hàng loạt/);
  assert.doesNotMatch(templateSource, /Kho thông tin/);
});

test("tenant identity comes from the authenticated session, never a hardcoded browser selector", () => {
  assert.doesNotMatch(appSource, /BUSINESS_ID\s*=|X-Business-Id/);
  assert.match(appSource, /from "\.\/api-client\.js"/);
  assert.match(appSource, /from "\.\/auth-context\.js"/);
  assert.match(apiClientSource, /Authorization/);
  assert.doesNotMatch(apiClientSource, /X-Business-Id|BUSINESS_ID/);
  assert.match(authContextSource, /AUTH_TOKEN_KEY/);
  assert.match(appSource, /function openSettings\(\)\s*\{[\s\S]*?if \(!authUser\.value\) return;/);
  for (const card of ["quota-card", "channel-connect-card", "chatbot-runtime-card", "followup-card", "csat-card", "team-card"]) {
    assert.match(appSource, new RegExp(`<div v-if="authUser" class="settings-card ${card}"`));
  }
});

test("customer avatars use the local API proxy and fall back when providers reject stale URLs", () => {
  assert.match(appSource, /function resolvedAvatarUrl\(item\)/);
  assert.match(appSource, /\/api\\\/customers\\\/\\d\+\\\/avatar/);
  assert.match(appSource, /function markAvatarFailed\(item\)/);
  assert.equal((appSource.match(/@error="markAvatarFailed\(/g) || []).length, 4);
});

test("CRM shell exposes the product's operational navigation", () => {
  assert.match(appSource, /t\(["']Hộp thư & Khách hàng 360["']\)/);
  assert.match(appSource, /t\(["']Đơn bán["']\)/);
  assert.doesNotMatch(appSource, />Đơn nhập</);
  assert.match(appSource, /t\(["']Báo cáo["']\)/);
  assert.match(appSource, /data-testid="crm-brand-mark"/);
});

test("anonymous visitors land on a branded Owly/Salon login gate", () => {
  assert.match(appSource, /<section v-else class="login-page"/);
  assert.match(appSource, /data-testid="login-page"/);
    assert.match(appSource, /class="login-form"/);
    assert.match(appSource, /class="login-brand-mark"/);
    assert.match(appSource, /CỔNG VẬN HÀNH SHOP|Cổng nhân viên|CỔNG NHÂN VIÊN/);
    assert.match(appSource, /<aside v-if="authUser && !inPlatformAdminWorkspace && !sessionBootstrapLoading" class="side"/);
    assert.match(appSource, /<main v-if="\(authUser && !sessionBootstrapLoading\) \|\| serviceLandingOpen" class="main"/);
  assert.match(styleSource, /\.login-page/);
  assert.match(styleSource, /\.login-card/);
});

test("login form surfaces a retry countdown when the auth endpoint rate-limits", () => {
    assert.match(appSource, /authRateLimitSeconds/);
    assert.match(appSource, /Retry-After/);
    assert.match(appSource, /detail\.detail\?\.retry_after/);
  assert.match(appSource, /startAuthRateLimit/);
  assert.match(appSource, /formatRateLimitDuration/);
  assert.match(appSource, /Thử lại sau/);
  assert.match(appSource, /class="login-rate-limit"/);
});

test("login shows the configured admin email in valid email fields", () => {
  assert.match(appSource, /Email đăng nhập/);
  assert.equal((appSource.match(/v-model="loginForm\.email" required type="email" maxlength="255" autocomplete="username" placeholder="admin@gmail\.com"/g) || []).length, 2);
});

test("platform admins land in the shop control plane instead of the CRM inbox", () => {
  const loginSource = appSource.slice(appSource.indexOf("async function login()"), appSource.indexOf("async function logout()"));
  const mountedSource = appSource.slice(appSource.indexOf("onMounted(async () =>"), appSource.indexOf("/* =========================================================\n   STOP POLLING"));

  assert.match(loginSource, /await fetchPlatformAdmin\(\);\s+if \(platformAdmin\.value && !mfaVerifyPending\.value\) \{[\s\S]*?currentTab\.value = "platform_admin";[\s\S]*?return;/);
  assert.match(mountedSource, /loadThemePreference\(\);\s+if \(platformAdmin\.value\) \{[\s\S]*?currentTab\.value = "platform_admin";[\s\S]*?return;/);
});

test("platform admins use a dedicated shop-administration shell, not CRM chrome", () => {
  assert.match(appSource, /const inPlatformAdminWorkspace = computed\(\(\) => \([\s\S]*?currentTab\.value === "platform_admin"/);
  assert.match(templateSource, /'platform-admin-workspace': inPlatformAdminWorkspace/);
  assert.match(templateSource, /<aside v-if="authUser && !inPlatformAdminWorkspace && !sessionBootstrapLoading" class="side"/);
  assert.match(templateSource, /<header v-if="authUser && !inPlatformAdminWorkspace" class="top">/);
  assert.match(templateSource, /v-if="authUser && !tenantReady && !inPlatformAdminWorkspace" class="tenant-provisioning-banner"/);
  assert.match(templateSource, /class="platform-workspace-header"/);
  assert.match(templateSource, /t\('Đăng xuất'\)/);
  assert.match(styleSource, /\.crm-app\.platform-admin-workspace\s*\{/);
});

test("a restored admin session waits for the role check before rendering any CRM chrome", () => {
  const mountedSource = appSource.slice(appSource.indexOf("onMounted(async () =>"), appSource.indexOf("/* =========================================================\n   STOP POLLING"));

  assert.match(appSource, /const sessionBootstrapLoading = ref\(true\)/);
  assert.match(mountedSource, /await fetchPlatformAdmin\(\);[\s\S]*?finally \{[\s\S]*?sessionBootstrapLoading\.value = false;/);
  assert.match(templateSource, /'session-bootstrap-active': sessionBootstrapLoading/);
  assert.match(templateSource, /<section v-else-if="sessionBootstrapLoading" class="session-bootstrap"/);
  assert.match(templateSource, /<main v-if="\(authUser && !sessionBootstrapLoading\) \|\| serviceLandingOpen" class="main"/);
  assert.match(styleSource, /\.session-bootstrap\s*\{/);
});

test("operations navigation keeps only customer-facing processing modules", () => {
  const operationsStart = appSource.indexOf('class="menu-group menu-group-operations"');
  const operationsEnd = appSource.indexOf('class="menu-group menu-group-ai"', operationsStart);
  const operationsNav = appSource.slice(operationsStart, operationsEnd);
  assert.match(operationsNav, /t\(["']Sản phẩm["']\)/);
  assert.match(operationsNav, /t\(["']Đơn bán["']\)/);
  assert.doesNotMatch(operationsNav, /Đơn nhập|purchase-orders/);
  assert.doesNotMatch(operationsNav, /Tạo sản phẩm|Tạo đơn bán/);
});

test("AI navigation keeps knowledge and workflow without assistant or rule lab shortcuts", () => {
  const aiStart = appSource.indexOf('class="menu-group menu-group-ai"');
  const aiEnd = appSource.indexOf('class="menu-group menu-group-insights"', aiStart);
  const aiNav = appSource.slice(aiStart, aiEnd);
  assert.match(aiNav, /t\(["']Kho kiến thức["']\)/);
  assert.match(aiNav, /t\(["']Quy trình["']\)/);
  assert.doesNotMatch(aiNav, />AI Assistant</);
  assert.doesNotMatch(aiNav, />AI Rule Lab</);
});

test("product and sales screens expose processing controls without intake forms", () => {
  const productsStart = appSource.indexOf('currentTab === \'products\'');
  const productsEnd = appSource.indexOf('currentTab === \'leads\'', productsStart);
  const productsView = appSource.slice(productsStart, productsEnd);
  assert.doesNotMatch(productsView, /<form class="product-form"/);
  assert.match(productsView, /Điều chỉnh tồn/);

  const ordersStart = appSource.indexOf('currentTab === \'orders\'');
  const ordersEnd = appSource.indexOf('currentTab === \'purchase-orders\'', ordersStart);
  const ordersView = appSource.slice(ordersStart, ordersEnd);
  assert.doesNotMatch(ordersView, /<form class="product-form order-form"/);
  assert.match(ordersView, /Xác nhận đơn|Quy trình|Lưu vận chuyển/);
});

test("sidebar groups customer, operations, AI, and system navigation", () => {
  assert.match(appSource, /class="menu-group menu-group-customer"/);
  assert.match(appSource, /class="menu-group menu-group-operations"/);
  assert.match(appSource, /class="menu-group menu-group-ai"/);
  assert.match(appSource, /class="menu-group menu-group-insights"/);
  assert.match(appSource, /class="menu-group menu-group-system"/);
  assert.match(appSource, /class="menu-group-label"/);
  assert.match(appSource, /t\(["']Kiến thức & tự động hóa["']\)/);
  assert.match(appSource, /t\(["']Phân tích["']\)/);
  assert.doesNotMatch(appSource, /<b>Customer 360<\/b>/);
});

test("AI Rule Lab supports creating and filtering explainable rule suggestions", () => {
  assert.match(appSource, /aiRuleForm/);
  assert.match(appSource, /createRuleSuggestion/);
  assert.match(appSource, /ruleSuggestionFilter/);
  assert.match(appSource, /Lưu đề xuất/);
  assert.match(appSource, /Chờ duyệt/);
  assert.match(appSource, /Đã duyệt/);
  assert.match(appSource, /Từ chối/);
  assert.match(appSource, /suggestion.proposed_action/);
  assert.match(appSource, /Chưa đồng bộ database AI/);
});

test("AI experiments can be created from the AI Lab", () => {
  assert.match(appSource, /experimentForm/);
  assert.match(appSource, /createExperiment/);
  assert.match(appSource, /Tạo thử nghiệm/);
  assert.match(appSource, /experiment.variants/);
  assert.match(appSource, /experiment.status/);
});

test("AI Lab operates model versions, experiment reports, and bandit policies", () => {
  assert.match(appSource, /modelVersions/);
  assert.match(appSource, /createModelVersion/);
  assert.match(appSource, /\/experiments\/models/);
  assert.match(appSource, /loadExperimentSignals/);
  assert.match(appSource, /\/report/);
  assert.match(appSource, /createBanditPolicy/);
  assert.match(appSource, /Bandit policy/);
});

test("Knowledge Base exposes durable RAG run status and retry action", () => {
  assert.match(appSource, /documentRuns/);
  assert.match(appSource, /\/documents\/\$\{doc\.id\}\/runs/);
  assert.match(appSource, /Lần xử lý/);
  assert.match(appSource, /retryDocumentRun/);
  assert.match(appSource, /\/documents\/runs\/\$\{run\.id\}\/retry/);
  assert.match(appSource, /Thử lại xử lý/);
  assert.match(templateSource, /<progress[^>]+:value="documentRuns\[doc\.id\]\.progress_percent"/);
  assert.match(appSource, /docRetryingIds/);
});

test("CRM operations expose attribution, lead conversion, and lead activity actions", () => {
  assert.match(appSource, /revenue-attribution\$\{attributionSuffix\}/);
  assert.match(appSource, /attributionParams\.set\("model", "last_touch"\)/);
  assert.match(appSource, /Tính lại nguồn doanh thu/);
  assert.match(appSource, /leads\/\$\{lead\.id\}\/activities/);
  assert.match(appSource, /leads\/\$\{lead\.id\}\/convert/);
  assert.match(appSource, /Ghi nhận chuyển đổi/);
  assert.match(appSource, /Hoạt động/);
});

test("report workspace applies shared date, channel, owner, status, and source filters", () => {
  assert.match(appSource, /reportFilters = ref\(\{ start_at: "", end_at: "", channel: "", source: "", status: "", assigned_user_id: "" \}\)/);
  assert.match(appSource, /\/reports\/pipeline\$\{suffix\}/);
  assert.match(appSource, /\/reports\/tickets\$\{suffix\}/);
  assert.match(appSource, /Nguồn ghi nhận/);
});

test("report workspace exposes tenant platform quality signals", () => {
  assert.match(appSource, /\/reports\/quality\?days=30/);
  assert.match(appSource, /qualityDashboard/);
  assert.match(appSource, /Vận hành nền tảng/);
  assert.match(appSource, /Kênh lỗi/);
  assert.match(appSource, /Chi phí trợ lý/);
  assert.match(appSource, /Phiếu quá hạn/);
});

test("report workspace exposes provider circuit state", () => {
  assert.match(appSource, /qualityDashboard\.provider\?\.circuits/);
  assert.match(appSource, /Bộ ngắt kênh/);
  assert.match(appSource, /Đang tạm dừng|Đang hoạt động/);
});

test("AI quality dashboard exposes handoff and duplicate reply signals", () => {
  assert.match(appSource, /Tỷ lệ chuyển nhân viên/);
  assert.match(appSource, /Phản hồi trùng/);
  assert.match(appSource, /Đơn chốt tự động/);
});

test("Inbox records staff-confirmed outcomes for chatbot conversations", () => {
  assert.match(appSource, /selectedHasAiActivity/);
  assert.match(appSource, /conversations\/\$\{conversation\.conversation_id\}\/outcome/);
  assert.match(appSource, /confirmed_outcomes/);
  assert.match(appSource, /Kết quả được nhân viên xác nhận/);
});

test("Team settings expose tenant-scoped permission overrides", () => {
  assert.match(appSource, /team\/permissions/);
  assert.match(appSource, /permissionForm/);
  assert.match(appSource, /Quyền chi tiết/);
  assert.match(appSource, /Từ chối luôn được ưu tiên/);
  assert.match(appSource, /Thêm quy tắc/);
  assert.match(appSource, /deletePermissionOverride/);
  assert.match(appSource, /team\/permissions\/\$\{override\.id\}/);
  assert.match(appSource, /Xóa quy tắc/);
});

test("platform administration exposes shop status, usage, and schema pilot controls", () => {
  assert.match(appSource, /platformAdmin/);
  assert.match(appSource, /platform\/shops/);
  assert.match(appSource, /platform\/tenant-schemas/);
  assert.match(appSource, /platform\/audit-logs/);
  assert.match(appSource, /Khóa shop|Mở shop/);
  assert.match(appSource, /Hạn mức|Giới hạn/);
  assert.match(appSource, /tách kho dữ liệu theo shop/);
});

test("platform administration surfaces pending package approvals before tenant operations", () => {
  assert.match(appSource, /const platformPendingRequests = ref\(\[\]\)/);
  assert.match(appSource, /platform\/subscription-requests/);
  assert.match(appSource, /async function approvePlatformSubscriptionRequest/);
  assert.match(appSource, /async function rejectPlatformSubscriptionRequest/);
  assert.match(appSource, /async function refreshPlatformSubscriptionRequests/);
  assert.match(appSource, /platformRequestPollingTimer = window\.setInterval/);
  assert.match(appSource, /contact_name: String\(serviceRequestForm\.value\.contact_name/);
  assert.match(appSource, /channels: \[\.\.\.serviceRequestForm\.value\.channels\]/);
  assert.match(templateSource, /Yêu cầu chờ duyệt/);
  assert.match(templateSource, /request\.contact_name \|\| request\.requester_name/);
  assert.match(templateSource, /request\.contact_email \|\| request\.requester_email/);
  assert.match(templateSource, /request\.requested_at \|\| request\.created_at/);
  assert.match(templateSource, /request\.requested_channels/);
  assert.match(templateSource, /@click="approvePlatformSubscriptionRequest\(request\)"/);
  assert.match(templateSource, /@click="rejectPlatformSubscriptionRequest\(request\)"/);
  assert.match(appSource, /Đã gửi yêu cầu thuê gói.*chờ quản trị viên duyệt/);
  assert.match(styleSource, /\.platform-approval-panel/);
});

test("shop self-service signup verifies email before creating a shop", () => {
  assert.doesNotMatch(appSource, /Chưa có workspace/);
  assert.match(appSource, /Đăng ký shop mới/);
  assert.match(appSource, /signupLoading \? \(signupStep === 'otp' \? 'Đang tạo shop\.\.\.' : 'Đang gửi mã\.\.\.'\)/);
  assert.match(templateSource, /class="signup-stepper"/);
  assert.match(appSource, /onboarding\/signup\/request/);
  assert.match(appSource, /onboarding\/signup\/verify/);
  assert.match(appSource, /Mã OTP/);
  assert.match(appSource, /onboarding\/shops\/\$\{requireBusinessId\(authUser\.value\)\}\/channels/);
  assert.match(appSource, /usage/);
  assert.match(appSource, /quotaSnapshot/);
  assert.match(appSource, /near_limit/);
  assert.match(appSource, /provider-errors/);
});

test("channel onboarding exposes guided Telegram and Zalo Bot Creator token verification", () => {
  assert.match(appSource, /botConnections/);
  assert.match(appSource, /Kết nối Telegram\/Zalo/);
  assert.match(appSource, /Quét QR để tạo bot/);
  assert.match(appSource, /Sao chép token/);
  assert.match(appSource, /Kiểm tra và kết nối/);
  assert.match(appSource, /channels\/verify/);
  assert.match(appSource, /BotFather/);
  assert.match(appSource, /Zalo Bot Manager/);
  assert.match(appSource, /access_token: token/);
  assert.doesNotMatch(appSource, /`personal:\$\{token\}`/);
    assert.match(styleSource, /\.channel-connect-card/);
  });

  test("linked channels are split into social connections and webhook operations", () => {
    assert.match(appSource, /Kênh liên kết/);
    assert.match(appSource, /currentTab === 'channels'/);
    assert.match(appSource, /currentTab === 'webhooks'/);
    assert.match(appSource, /Kết nối mạng xã hội/);
    assert.match(appSource, /<h2>Nhận sự kiện<\/h2>/);
    assert.match(appSource, /webhook-card/);
    assert.match(appSource, /refreshWebhookStatus/);
  });

test("P1 explainable AI evidence is visible in the unified timeline", () => {
  assert.match(appSource, /function timelineExplainability\(event\)/);
  assert.match(appSource, /Trợ lý dùng dữ liệu/);
  assert.match(appSource, /Trợ lý chuyển nhân viên/);
  assert.match(appSource, /Tài liệu tham khảo:/);
  assert.match(appSource, /class="timeline-explainability"/);
  assert.match(styleSource, /\.timeline-explainability/);
});

test("P1 conversation revenue metrics are visible in the AI dashboard", () => {
  assert.match(appSource, /Doanh thu cứu lại/);
  assert.match(appSource, /recovered_revenue/);
  assert.match(appSource, /recovered_orders/);
  assert.match(appSource, /Bot phản hồi, chưa bàn giao/);
  assert.match(appSource, /bot_resolution_rate/);
});

test("P2 workflow builder exposes durable trigger, action and run controls", () => {
  assert.match(appSource, /currentTab === 'workflows'/);
  assert.match(appSource, /fetchWorkflows/);
  assert.match(appSource, /workflows\/\$\{workflow\.id\}\/runs/);
  assert.match(appSource, /toggleWorkflow/);
  assert.match(appSource, /Chạy lại/);
  assert.match(appSource, /Tạo quy trình/);
});

test("shops can configure customer fields and lead stages, and Customer 360 edits configured values", () => {
  assert.match(appSource, /workspace\/crm-config/);
  assert.match(appSource, /customer_fields: crmConfig\.value\.customer_fields/);
  assert.match(appSource, /pipeline_stages: crmConfig\.value\.pipeline_stages/);
  assert.match(appSource, /customers\/\$\{customerId\}\/custom-fields/);
  assert.match(appSource, /v-for="stage in crmConfig\.pipeline_stages"/);
});

test("P2 logistics and payment history remain actionable in sales orders", () => {
  assert.match(appSource, /order-logistics-card/);
  assert.match(appSource, /updateOrderLogistics/);
  assert.match(appSource, /shipping_status/);
  assert.match(appSource, /recordSalesPayment/);
  assert.match(appSource, /"refunds"/);
  assert.match(appSource, /Xem toàn bộ quy trình/);
});

test("settings expose session, MFA, and privacy controls", () => {
  assert.match(appSource, /auth\/sessions/);
  assert.match(appSource, /auth\/mfa\/prepare/);
  assert.match(appSource, /auth\/mfa\/disable/);
  assert.match(appSource, /privacy\/\$\{kind\}/);
  assert.match(appSource, /Bảo mật tài khoản & dữ liệu/);
  assert.match(appSource, /Thu hồi/);
});

test("CRM exposes a three-step quick action palette", () => {
  assert.match(appSource, /quickActionOpen/);
  assert.match(appSource, /Ctrl\+K|Ctrl K/);
  assert.doesNotMatch(appSource, /Cmd\+K|Ctrl\/Cmd\+K|⌘K/);
  assert.match(appSource, /Tạo phiếu hỗ trợ nhanh/);
  assert.match(appSource, /Tạo đơn nháp nhanh/);
  assert.match(appSource, /Nhân viên tiếp quản/);
  assert.match(appSource, /quick-action-dialog/);
});

test("sidebar navigation stays compact without repeated record-count badges", () => {
  const navStart = templateSource.indexOf('<nav class="menu">');
  const navEnd = templateSource.indexOf("</nav>", navStart);
  assert.notEqual(navStart, -1, "sidebar navigation must be present");
  assert.notEqual(navEnd, -1, "sidebar navigation must be closed");
  const navSource = templateSource.slice(navStart, navEnd);
  assert.doesNotMatch(navSource, /<em>\{\{/);
});

test("AI navigation keeps knowledge and workflow under one group", () => {
  const navStart = appSource.indexOf('<nav class="menu">');
  const navEnd = appSource.indexOf("</nav>", navStart);
  const navSource = appSource.slice(navStart, navEnd);
  assert.match(navSource, /class="ai-submenu"/);
  assert.match(navSource, /t\(["']Kho kiến thức["']\)/);
  assert.match(navSource, /t\(["']Quy trình["']\)/);
  assert.doesNotMatch(navSource, />AI Rule Lab</);
  assert.doesNotMatch(navSource, />AI Assistant</);
  assert.match(styleSource, /\.menu-group-ai/);
  assert.match(styleSource, /\.ai-submenu/);
});

test("Customer 360 labels the complete profile timeline", () => {
  assert.match(appSource, /identity:\s*"Danh tính đa kênh"/);
  assert.match(appSource, /fact:\s*"Thông tin khách hàng"/);
  assert.match(appSource, /ticket_event:\s*"Lịch sử phiếu hỗ trợ"/);
  assert.match(appSource, /event\.occurred_at/);
  assert.match(appSource, /event\.created_by/);
});

test("assigned conversations remain visible but make other staff read-only", () => {
  assert.match(appSource, /const canReplyToSelectedConversation = computed/);
  assert.match(appSource, /Hội thoại này đang có nhân viên phụ trách; bạn chỉ có thể xem nội dung\./);
  assert.match(templateSource, /:disabled="composerMode === 'reply' && !canReplyToSelectedConversation"/);
  assert.match(appSource, /Bạn đang ở chế độ chỉ xem/);
  assert.match(styleSource, /\.composer-access-notice\.is-read-only/);
});

test("Customer 360 keeps activity history compact and scopes a selected staff member", () => {
  assert.match(appSource, /Chỉ hiển thị hoạt động do nhân viên đã chọn thực hiện/);
  assert.match(appSource, /Để xem toàn bộ hoạt động trong ngày, giữ “Tất cả nhân viên”/);
  assert.match(appSource, /customerTimelineSummaryCards/);
  assert.match(appSource, /customerTimelineDetailsOpen/);
  assert.match(appSource, /function customerTimelineContent\(event\)/);
  assert.match(appSource, /Xem chi tiết/);
  assert.match(styleSource, /\.customer-timeline-summary-card/);
  assert.match(styleSource, /\.customer-timeline-detail-toggle/);
});

test("Customer 360 searches chat messages in pages and jumps to the matching bubble", () => {
  assert.match(appSource, /message-search\?\$\{params\.toString\(\)\}/);
  assert.match(appSource, /limit: "10"/);
  assert.match(appSource, /function handleCustomerMessageSearchScroll/);
  assert.match(appSource, /function jumpToCustomerSearchMessage/);
  assert.match(appSource, /data-message-id/);
  assert.match(appSource, /customer-message-search-trigger/);
  assert.match(styleSource, /\.customer-message-search-results/);
  assert.match(styleSource, /\.search-jump-highlight/);
});

test("Customer 360 contact cards stay readable in the narrow details panel", () => {
  assert.match(appSource, /class="customer-contact-grid"/);
  assert.match(styleSource, /\.customer-contact-grid\s*\{[\s\S]*?grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(210px,\s*1fr\)\)/);
  assert.match(styleSource, /\.customer-contact-row span\s*\{[\s\S]*?white-space:\s*nowrap/);
  assert.match(styleSource, /\.customer-contact-row span\s*\{[\s\S]*?text-overflow:\s*ellipsis/);
});

test("Customer 360 displays the collected profile name, email, and phone", () => {
  assert.match(appSource, /nameOf\(\s*customer360\s*\|\|\s*selected\s*\)/);
  assert.match(appSource, /item\?\.name/);
  assert.match(appSource, /class="customer-profile-email"/);
  assert.match(appSource, /customer360\.email/);
  assert.match(appSource, /class="customer-profile-fields"/);
  assert.match(appSource, /customer360\.phone/);
  assert.match(appSource, /customer360\.name/);
});

test("Customer 360 projects one primary contact/address and keeps history expandable", () => {
  assert.match(appSource, /customer360PrimaryContacts/);
  assert.match(appSource, /customer360VisibleAddresses/);
  assert.match(appSource, /customer360OverflowCount/);
  assert.match(appSource, /Xem thêm/);
  assert.match(appSource, /:aria-expanded="customer360OverflowOpen"/);
  assert.match(styleSource, /\.customer-contact-card\s*\{[\s\S]*?max-height:\s*13rem/);
  assert.match(styleSource, /\.customer-contact-overflow-list\s*\{[\s\S]*?max-height:\s*8\.5rem/);
});

test("Order table keeps actions compact and keyboard discoverable", () => {
  assert.match(appSource, /data-testid="order-history-button"[^>]*title="Xem toàn bộ quy trình"[^>]*aria-label="Xem toàn bộ quy trình"/);
  assert.match(appSource, /aria-label="Ghi nhận thanh toán"/);
  assert.match(appSource, /aria-label="Ghi nhận hoàn tiền"/);
  assert.match(styleSource, /\.orders-table\s+\.table-action-btn,[\s\S]*?white-space:\s*nowrap/);
  assert.match(styleSource, /\.orders-table\s+\.order-payment-actions\s*\{[\s\S]*?flex-wrap:\s*nowrap/);
});

test("Customer Ops masks customer PII consistently across order and CRM selectors", () => {
  assert.match(appSource, /function customerOptionLabel\(customer\)/);
  assert.match(appSource, /const email = maskCustomerEmail\(customer\?\.email\)/);
  assert.match(appSource, /const phone = maskCustomerPhone\(customer\?\.phone\)/);
  assert.match(appSource, /function orderCustomerPhone\(customerId\)[\s\S]*?maskCustomerPhone\(customer\?\.phone\)/);
  assert.match(appSource, /const selectedOrderCustomerPhone = computed\(\(\) => \([\s\S]*?maskCustomerPhone/);
  assert.doesNotMatch(appSource, /customer\.name \|\| customer\.email \|\| customer\.phone \|\| customer\.channel/);
});

test("Customer Ops exposes a recoverable Customer 360 error state", () => {
  assert.match(appSource, /const customer360Error = ref\(""\)/);
  assert.match(appSource, /class="customer-360-error" role="alert"/);
  assert.match(appSource, /Không tải được hồ sơ khách hàng\. Hãy thử lại\./);
  assert.match(appSource, /@click="loadCustomer360\(selected\?\.customer_id\)"/);
  assert.match(styleSource, /\.customer-360-error\s*\{/);
});

test("Customer Ops refreshes the Customer 360 timeline after staff actions", () => {
  assert.match(appSource, /async function reassignConversation[\s\S]*?conversation\.assigned_user_id = result\.assigned_user_id;[\s\S]*?await loadCustomer360\(conversation\.customer_id\)/);
  assert.match(appSource, /async function toggleBotMode[\s\S]*?await loadCustomer360\(customerId\)/);
});

test("Internal notes save without referencing an unrelated media variable", () => {
  const start = appSource.indexOf("async function sendComposerContent()");
  const end = appSource.indexOf("async function fetchLeadActivities", start);
  const internalNoteHandler = appSource.slice(start, end);
  assert.match(internalNoteHandler, /clearImage\(\)/);
  assert.doesNotMatch(internalNoteHandler, /removePendingMedia\(media\.id\)/);
});

test("chatbot settings expose CSAT results for resolved conversations", () => {
  assert.match(appSource, /csatSummary/);
  assert.match(appSource, /\/chatbot\/csat/);
  assert.match(appSource, /Điểm hài lòng/);
  assert.match(appSource, /Tỷ lệ hài lòng/);
});

test("Customer 360 details use a scrollable panel so the full profile remains visible", () => {
  assert.match(appSource, /class="customer customer-panel-scroll"/);
  assert.match(styleSource, /\.customer-panel-scroll\s*\{[\s\S]*?overflow-y:\s*auto/);
  assert.match(styleSource, /\.customer-panel-scroll\s*\{[\s\S]*?overflow-x:\s*hidden/);
});

test("Customer Ops has explicit tablet and mobile layout fallbacks", () => {
  assert.match(appSource, /'has-selected-conversation': !!selected/);
  assert.match(appSource, /'mobile-inbox-open': mobileInboxOpen/);
  assert.match(appSource, /'mobile-customer-open': mobileCustomerOpen/);
  assert.match(appSource, /aria-label="Quay lại danh sách hội thoại"[\s\S]*?@click="openMobileInbox"/);
  assert.match(appSource, /aria-label="Mở hồ sơ khách hàng 360"[\s\S]*?@click="openMobileCustomer"/);
  assert.match(styleSource, /\.layout\.mobile-customer-open \.customer\s*\{[\s\S]*?display:\s*flex/);
  assert.match(styleSource, /\.layout:not\(\.has-selected-conversation\) \.inbox,[\s\S]*?\.layout\.mobile-inbox-open \.inbox\s*\{[\s\S]*?display:\s*flex/);
  assert.match(styleSource, /\.layout\.has-selected-conversation:not\(\.mobile-inbox-open\) \.chat\s*\{[\s\S]*?display:\s*flex/);
  assert.match(styleSource, /\.products-table-wrap\s*\{[\s\S]*?overflow-x:\s*auto/);
});

test("Customer Ops restores keyboard focus when responsive panels close", () => {
  assert.match(appSource, /function openMobileInbox\(\)[\s\S]*?inboxSearchInput\.value\?\.focus\(\)/);
  assert.match(appSource, /function closeMobileInbox\(\)[\s\S]*?mobileInboxTrigger\.value\?\.focus\(\)/);
  assert.match(appSource, /function openMobileCustomer\(\)[\s\S]*?mobileCustomerClose\.value\?\.focus\(\)/);
  assert.match(appSource, /function closeMobileCustomer\(\)[\s\S]*?mobileCustomerTrigger\.value\?\.focus\(\)/);
  assert.match(appSource, /event\.key === "Escape" && mobileCustomerOpen\.value/);
  assert.match(appSource, /event\.key === "Escape" && mobileInboxOpen\.value/);
  assert.match(appSource, /<h2 ref="chatHeading" tabindex="-1">/);
  assert.match(styleSource, /:where\(button, input, select, textarea, summary, \[tabindex\]\):focus-visible/);
  assert.match(styleSource, /\.customer-title \.mobile-panel-close\s*\{[\s\S]*?display:\s*none/);
});

test("Zalo has its own channel label and branded icon fallback", () => {
  assert.match(channelUtilsSource, /zalo:\s*["']ZALO["']/);
  assert.match(styleSource, /\.social-icon\.zalo/);
});

test("inventory stock summary separates total, available, and reserved quantities", () => {
  assert.match(appSource, /class="inventory-summary"/);
  assert.match(appSource, /class="inventory-total"/);
  assert.match(appSource, /class="inventory-available"/);
  assert.match(appSource, /class="inventory-reserved"/);
  assert.doesNotMatch(appSource, /<strong>\{\{ product\.stock_quantity \}\}<\/strong><small>Khả dụng:/);
});

test("sidebar collapse control toggles a real collapsed state", () => {
  assert.match(appSource, /sidebarCollapsed/);
  assert.match(appSource, /toggleSidebar/);
  assert.match(appSource, /sidebar-collapsed/);
  assert.match(appSource, /@click="toggleSidebar"/);
  assert.match(appSource, /aria-expanded/);
});

test("collapsed sidebar hides navigation text instead of clipping it", () => {
  assert.match(styleSource, /\.crm-app\.sidebar-collapsed \.side \.menu-item\s*>\s*:\s*not\(\.nav-icon\)[\s\S]*?display:\s*none\s*!important/);
  assert.match(styleSource, /\.crm-app\.sidebar-collapsed \.side \.menu-group-label[\s\S]*?display:\s*none\s*!important/);
  assert.match(styleSource, /\.crm-app\.sidebar-collapsed \.side \.collapse\s*>\s*span:not\(\.collapse-icon\)[\s\S]*?display:\s*none\s*!important/);
  assert.match(styleSource, /@media \(max-width: 1100px\)[\s\S]*?\.crm-app:not\(\.platform-admin-workspace\) \.side \.menu-item\s*>\s*:\s*not\(\.nav-icon\)[\s\S]*?display:\s*none\s*!important/);
});

test("CRM workspace header exposes logout independently of tenant readiness", () => {
  const headerStart = templateSource.indexOf('<header v-if="authUser && !inPlatformAdminWorkspace" class="top">');
  const headerEnd = templateSource.indexOf("</header>", headerStart);
  assert.notEqual(headerStart, -1);
  assert.notEqual(headerEnd, -1);
  const crmHeader = templateSource.slice(headerStart, headerEnd);
  assert.match(crmHeader, /class="top-logout"/);
  assert.match(crmHeader, /:aria-label="t\('Đăng xuất'\)"/);
  assert.match(crmHeader, /@click="logout"/);
});

test("compact CRM header keeps logout visible without squeezing the greeting", () => {
  assert.match(styleSource, /\.crm-app:not\(\.platform-admin-workspace\) \.top > \.welcome[\s\S]*?min-width:\s*160px/);
  assert.match(styleSource, /@media \(max-width: 1180px\)[\s\S]*?\.crm-app:not\(\.platform-admin-workspace\) \.top-search[\s\S]*?width:\s*clamp\(190px,\s*25vw,\s*300px\)/);
  assert.match(styleSource, /@media \(max-width: 1180px\)[\s\S]*?\.crm-app:not\(\.platform-admin-workspace\) \.top-logout > span[\s\S]*?display:\s*none/);
  assert.match(styleSource, /@media \(max-width: 860px\)[\s\S]*?\.crm-app:not\(\.platform-admin-workspace\) \.top-search[\s\S]*?display:\s*none/);
});

test("compact inbox workspace keeps every new UI control actionable", () => {
  assert.match(appSource, /const sidebarCollapsed = ref\(false\)/);
  assert.match(appSource, /class="inbox-filter-disclosure"/);
  assert.match(appSource, /const customerPanelCollapsed = ref\(false\)/);
  assert.match(appSource, /function toggleCustomerPanel\(\)/);
  assert.match(appSource, /@click="toggleCustomerPanel"/);
  assert.match(appSource, /customer-collapsed/);
  assert.match(appSource, /@click="toggleVoiceRecording"/);
  assert.match(styleSource, /\.layout\s*\{[\s\S]*?grid-template-columns:\s*218px\s+minmax\(0,\s*1fr\)/);
  assert.match(styleSource, /\.customer\.customer-collapsed\s*>\s*:not\(\.customer-title\)/);
});

test("empty workspace explains missing data without rendering fake customer records", () => {
  assert.match(appSource, /class="inbox-empty-state"/);
  assert.match(appSource, /Hộp thư đang chờ tin nhắn đầu tiên/);
  assert.match(appSource, /class="empty-chat-steps"/);
  assert.match(appSource, /Hộp thư sẵn sàng cho khách hàng đầu tiên/);
  assert.match(appSource, /class="customer-empty-state"/);
  assert.match(appSource, /Hồ sơ khách hàng sẽ hiện ở đây/);
  assert.match(appSource, /<template v-if="selected">[\s\S]*?<template v-else>/);
});

test("every rendered button declares a click handler or form behavior", () => {
  const inactiveButtons = openingButtonTags(appSource).filter((tag) => !(
    /@click|@submit|@mousedown|@pointerdown/.test(tag)
    || /type\s*=\s*["'](?:submit|reset)["']/.test(tag)
    // A genuinely disabled “coming soon” control is deliberately not an
    // action. All enabled controls still require an explicit interaction.
    || /\bdisabled\b/.test(tag)
  ));
  assert.deepEqual(inactiveButtons, []);
});

test("every directly referenced UI event handler exists", () => {
  const handlerPattern = /@(?:click|submit|change|keyup|keydown)(?:\.[\w]+)*\s*=\s*(["'])\s*([A-Za-z_][\w]*)\s*(?=\(|\1)/g;
  const handlers = new Set(Array.from(templateSource.matchAll(handlerPattern), (match) => match[2]));
  const importedHandlers = new Set(["setUiLocale"]);
  const missing = Array.from(handlers).filter((handler) => !importedHandlers.has(handler) && !new RegExp(`\\b(?:async\\s+)?function\\s+${handler}\\s*\\(`).test(appSource));
  assert.deepEqual(missing, []);
});

test("CSV export uses authenticated apiFetch and visible feedback", () => {
  assert.match(appSource, /async function downloadReportCsv\(\)/);
  assert.match(appSource, /const response = await apiFetch\(reportCsvUrl\.value\)/);
  assert.match(appSource, /response\.blob\(\)/);
  assert.match(appSource, /reportCsvDownloading/);
  assert.match(appSource, /reportCsvStatus/);
  assert.match(appSource, /@click="downloadReportCsv"/);
  assert.doesNotMatch(templateSource, /<a[^>]+:href="reportCsvUrl"/);
});

test("network-backed controls expose busy, success, and failure feedback", () => {
  assert.match(appSource, /notificationError\.value/);
  assert.match(templateSource, /notification-error" role="alert"/);
  assert.match(appSource, /autoReplySaving\.value/);
  assert.match(appSource, /autoReplyNotice\.value/);
  assert.match(appSource, /autoReplyError\.value/);
  assert.match(templateSource, /:disabled="autoReplySaving"/);
  assert.match(appSource, /followupNotice\.value/);
  assert.match(appSource, /followupError\.value/);
  assert.match(appSource, /csatError\.value/);
  assert.match(templateSource, /v-if="followupError"[^>]+role="alert"/);
  assert.match(templateSource, /v-if="csatError"[^>]+role="alert"/);
  assert.match(templateSource, /class="btn-meta-connect"[\s\S]*?:disabled="metaLoading"/);
});

test("destructive follow-up cancellation requires confirmation and reports errors", () => {
  const start = appSource.indexOf("async function cancelFollowup");
  const end = appSource.indexOf("async function fetchCsat", start);
  const body = appSource.slice(start, end);
  assert.match(body, /requestConfirmation\("Hủy lịch chăm sóc này\?"/);
  assert.match(body, /if \(!response\.ok\)/);
  assert.match(body, /followupError\.value/);
  assert.match(body, /followupNotice\.value/);
});

test("top workspace controls are interactive and searchable", () => {
  assert.match(appSource, /class="top-search-input"/);
  assert.match(appSource, /@keydown\.enter="runGlobalSearch"/);
  assert.match(appSource, /function runGlobalSearch/);
  assert.match(appSource, /@click="openNotifications"/);
  assert.match(appSource, /function openNotifications/);
  assert.match(appSource, /@click="openSettings"/);
});

test("workspace navigation and header use a consistent vector icon system", () => {
  assert.match(appSource, /class="nav-icon nav-icon-inbox" viewBox="0 0 24 24"/);
  assert.match(appSource, /class="nav-icon nav-icon-products" viewBox="0 0 24 24"/);
  assert.match(appSource, /class="nav-icon nav-icon-settings" viewBox="0 0 24 24"/);
  assert.match(appSource, /class="top-search-icon" viewBox="0 0 24 24"/);
  assert.match(appSource, /class="top-action-icon" viewBox="0 0 24 24"/);
  assert.match(appSource, /class="help"/);
  assert.match(styleSource, /\.nav-icon\s*\{[\s\S]*?stroke:\s*currentColor/);
  assert.match(styleSource, /\.top-action-icon\s*\{/);
  assert.doesNotMatch(appSource, /nav-icon-inbox" aria-hidden="true"><\/span>/);
});

test("inbox uses a polished filter toolbar instead of a native multi-select", () => {
  assert.match(appSource, /class="inbox-toolbar"/);
  assert.match(appSource, /class="inbox-filter-panel"/);
  assert.match(appSource, /class="tag-chip-list"/);
  assert.match(appSource, /toggleTagFilter/);
  assert.match(appSource, /class="segment-control"/);
  assert.doesNotMatch(appSource, /class="segment-filter" multiple/);
});

test("inbox keeps actionable quick tabs and a complete channel selector", () => {
  assert.match(appSource, /class="inbox-channel-filter"/);
  assert.match(appSource, /const inboxQuickFilter = ref\("all"\)/);
  assert.match(appSource, /class="inbox-quick-tabs"/);
  assert.match(appSource, /inboxQuickFilter === 'unread'/);
  assert.match(appSource, /inboxQuickFilter === 'important'/);
  assert.match(appSource, /class="inbox-channel-select"/);
  assert.match(appSource, /<select v-model="activeFilter"/);
  assert.match(appSource, /channel\.label \}\} \(\{\{ channel\.count \}\}\)/);
  assert.match(styleSource, /\.inbox-quick-tabs\s*\{/);
  assert.match(styleSource, /\.inbox-channel-select select\s*\{/);
  assert.doesNotMatch(appSource, /class="inbox-channel-scroll"/);
  assert.doesNotMatch(styleSource, /\.inbox-channel-scroll/);
});

test("inbox no longer renders the selected-customer order strip", () => {
  assert.match(appSource, />Đơn bán</);
  assert.doesNotMatch(appSource, /class="inbox-order-strip"/);
});

test("sales order history exposes logistics metadata without a separate delivery module", () => {
  assert.match(appSource, /data-testid="order-logistics-card"/);
  assert.match(appSource, /updateOrderLogistics/);
  assert.match(appSource, /shipping_provider/);
  assert.match(appSource, /tracking_code/);
  assert.match(appSource, /Lưu vận chuyển/);
  assert.match(appSource, /logistics_updated: "Cập nhật vận chuyển"/);
  assert.match(styleSource, /\.order-logistics-card/);
  assert.match(styleSource, /\.order-logistics-grid/);
  assert.doesNotMatch(appSource, />Đơn giao hàng</);
});

test("inbox workspace fills the remaining viewport instead of reserving a blank lower area", () => {
  const refinementStart = styleSource.indexOf("INBOX DESKTOP REFINEMENT");
  const refinementStyles = styleSource.slice(refinementStart);
  assert.match(refinementStyles, /\.layout\s*\{[\s\S]*?height:\s*calc\(100vh - 92px\)/);
  assert.match(refinementStyles, /\.layout\s*\{[\s\S]*?min-height:\s*0/);
  assert.doesNotMatch(refinementStyles, /height:\s*calc\(100vh - 238px\)/);
});

test("inbox header and conversation rows expose readable status hierarchy", () => {
  assert.match(appSource, /class="inbox-title-copy"/);
  assert.match(appSource, /class="inbox-title-count"/);
  assert.match(appSource, /class="conversation-status"/);
  assert.match(appSource, /class="conversation-channel-pill"/);
  assert.match(styleSource, /\.inbox-filter-panel/);
  assert.match(styleSource, /\.conversation-channel-pill/);
});

test("chat workspace uses a neutral timeline and aligned composer layout", () => {
  assert.match(appSource, /class="chat chat-shell"/);
  assert.match(appSource, /class="messages-scroll chat-timeline"/);
  assert.match(appSource, /class="composer chat-composer"/);
  assert.match(styleSource, /\.chat-shell/);
  assert.match(styleSource, /\.chat-timeline/);
  assert.match(styleSource, /\.chat-composer/);
  assert.doesNotMatch(styleSource, /url\("data:image\/svg\+xml/);
});

test("chat controls are actionable and the composer keeps a standard input hint", () => {
  assert.match(appSource, /@click="toggleConversationActions"/);
  assert.match(appSource, /@click="toggleConversationPriority"/);
  assert.match(appSource, /@click="toggleConversationFavorite"/);
  assert.match(appSource, /:aria-pressed="conversationPriorityActive"/);
  assert.match(appSource, /:aria-pressed="conversationFavoriteActive"/);
  assert.doesNotMatch(appSource, /MÃ\s*\n?\s*Tạo mã giảm giá/);
  assert.doesNotMatch(appSource, /Ctrl\+V để dán ảnh/);
  assert.match(styleSource, /\.conversation-actions-popover/);
});

test("inbox personal filters narrow conversations by customer phone and email", () => {
  assert.match(appSource, /const inboxPersonalFilters = ref\(\{ phone: "", email: "" \}\)/);
  assert.match(appSource, /aria-label="Lọc khách hàng theo số điện thoại"/);
  assert.match(appSource, /aria-label="Lọc khách hàng theo Gmail hoặc email"/);
  assert.match(appSource, /String\(item\.customer_phone \|\| ""\)\.replace\(\/\\D\/g, ""\)\.includes\(phoneQuery\)/);
  assert.match(appSource, /String\(item\.customer_email \|\| ""\)\.trim\(\)\.toLowerCase\(\)\.includes\(emailQuery\)/);
  assert.match(styleSource, /\.personal-filter-grid/);
});

test("conversation header can limit the inbox to accounts linked to its customer", () => {
  assert.match(appSource, /const linkedCustomerOnly = ref\(false\)/);
  assert.match(appSource, /@click="toggleLinkedCustomerInbox"/);
  assert.match(appSource, /class="linked-customer-toggle"/);
  assert.match(appSource, /Number\(item\.customer_id\) === Number\(selected\.value\?\.customer_id\)/);
  assert.match(appSource, /params\.set\("customer_id", String\(customerId\)\)/);
  assert.match(styleSource, /\.linked-customer-toggle svg/);
});

test("chat bot toggle stays on one line in the compact header", () => {
  assert.match(
    styleSource,
    /\.chat-shell \.chat-tools\s*>\s*\.bot-mode-button\s*\{[\s\S]*?flex:\s*0\s+0\s+auto[\s\S]*?white-space:\s*nowrap/
  );
});

test("opening a conversation marks its inbound messages as read through the Inbox API", () => {
  assert.match(appSource, /function markConversationRead/);
  assert.match(appSource, /\/mark-read/);
  assert.match(appSource, /await markConversationRead\(id\)/);
  assert.match(appSource, /unread_count:\s*0/);
});

test("chat attachments stay compact and action menu labels remain readable", () => {
  assert.match(styleSource, /\.chat-composer \.image-preview-box[\s\S]*?max-height:\s*80px/);
  assert.match(styleSource, /\.chat-composer \.image-preview-info[\s\S]*?flex-direction:\s*row/);
  assert.match(styleSource, /\.conversation-actions-popover[\s\S]*?min-width:\s*220px/);
  assert.match(styleSource, /\.conversation-actions-popover[\s\S]*?white-space:\s*nowrap/);
});

test("chat attachment tray exposes a Messenger-style removable thumbnail", () => {
  assert.match(appSource, /class="composer-attachment-visual"/);
  assert.match(appSource, /class="image-preview-remove"/);
  assert.match(appSource, /aria-label="Xóa media"/);
  assert.match(styleSource, /\.chat-composer \.composer-attachment-visual[\s\S]*?position:\s*relative/);
  assert.match(styleSource, /\.chat-composer \.image-preview-remove[\s\S]*?position:\s*absolute/);
});

test("chat attachment tray sits above the input without a media-type selector", () => {
  assert.match(styleSource, /\.chat-composer\s*\{[\s\S]*?display:\s*flex/);
  assert.match(styleSource, /\.chat-composer \.image-preview-box[\s\S]*?order:\s*1/);
  assert.match(styleSource, /\.chat-composer textarea[\s\S]*?order:\s*2/);
  assert.doesNotMatch(appSource, /class="composer-media-type"/);
});

test("chat composer queues multiple media items without filenames or quick replies", () => {
  assert.match(appSource, /const pendingMedia = ref\(\[\]\)/);
  assert.match(appSource, /multiple/);
  assert.match(appSource, /v-for="media in pendingMedia"/);
  assert.match(appSource, /removePendingMedia/);
  assert.match(appSource, /const files = Array\.from\(event\.target\.files/);
  assert.match(appSource, /files\.forEach\(\(file\) => setImageFile\(file\)\)/);
  assert.match(appSource, /for \(const \[index, media\] of mediaQueue\.entries\(\)\)/);
  assert.match(appSource, /await sendMedia\(media, index\)/);
  assert.doesNotMatch(appSource, /image-preview-name/);
  assert.doesNotMatch(appSource, /class="quick"/);
  assert.doesNotMatch(appSource, /Xin chào 👋/);
  assert.match(styleSource, /\.chat-composer \.composer-attachment-grid/);
  assert.match(styleSource, /\.chat-composer \.image-preview-box[\s\S]*?width:\s*max-content/);
  assert.match(styleSource, /\.chat-composer \.image-preview-box[\s\S]*?background:\s*transparent/);
});

test("chat composer keeps non-JPEG images on the generic media upload path", () => {
  assert.match(appSource, /canUseNormalizedImagePath/);
  assert.match(appSource, /!canUseNormalizedImagePath/);
  assert.match(appSource, /mediaType !== "image" \|\| !canUseNormalizedImagePath/);
});

test("chat composer replaces the search control with a voice recorder", () => {
  assert.match(appSource, /navigator\.mediaDevices\?\.getUserMedia/);
  assert.match(appSource, /new (?:window\.)?MediaRecorder/);
  assert.match(appSource, /toggleVoiceRecording/);
  assert.match(appSource, /new File\(\[blob\]/);
  assert.match(appSource, /queueMediaFile\(file, \{ mediaType: "audio" \}/);
  assert.match(appSource, /:title="voiceRecording \? 'Dừng ghi âm' : 'Ghi âm'"/);
  assert.doesNotMatch(appSource, /title="Đặt con trỏ vào ô nhập"/);
  assert.match(appSource, /async function selectConversation\(id\) \{[\s\S]*?discardVoiceRecording\(\);/);
});
