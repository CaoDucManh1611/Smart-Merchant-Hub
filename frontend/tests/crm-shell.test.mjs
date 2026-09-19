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
  assert.match(appSource, />Hộp thư &amp; Khách hàng 360</);
  assert.match(appSource, />Đơn bán</);
  assert.doesNotMatch(appSource, />Đơn nhập</);
  assert.match(appSource, />Báo cáo</);
  assert.match(appSource, /data-testid="crm-brand-mark"/);
});

test("anonymous visitors land on a branded Owly/Salon login gate", () => {
  assert.match(appSource, /<section v-else class="login-page"/);
  assert.match(appSource, /data-testid="login-page"/);
    assert.match(appSource, /class="login-form"/);
    assert.match(appSource, /class="login-brand-mark"/);
    assert.match(appSource, /CỔNG VẬN HÀNH SHOP|Cổng nhân viên|CỔNG NHÂN VIÊN/);
    assert.match(appSource, /<aside v-if="authUser" class="side"/);
    assert.match(appSource, /<main v-if="authUser" class="main">/);
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

test("operations navigation keeps only customer-facing processing modules", () => {
  const operationsStart = appSource.indexOf('class="menu-group menu-group-operations"');
  const operationsEnd = appSource.indexOf('class="menu-group menu-group-ai"', operationsStart);
  const operationsNav = appSource.slice(operationsStart, operationsEnd);
  assert.match(operationsNav, />Sản phẩm</);
  assert.match(operationsNav, />Đơn bán</);
  assert.doesNotMatch(operationsNav, /Đơn nhập|purchase-orders/);
  assert.doesNotMatch(operationsNav, /Tạo sản phẩm|Tạo đơn bán/);
});

test("AI navigation keeps knowledge and workflow without assistant or rule lab shortcuts", () => {
  const aiStart = appSource.indexOf('class="menu-group menu-group-ai"');
  const aiEnd = appSource.indexOf('class="menu-group menu-group-insights"', aiStart);
  const aiNav = appSource.slice(aiStart, aiEnd);
  assert.match(aiNav, />Kho kiến thức</);
  assert.match(aiNav, />Quy trình</);
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
  assert.match(appSource, />Kiến thức &amp; tự động hóa</);
  assert.match(appSource, />Phân tích</);
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

test("shop self-service signup verifies email before creating a shop", () => {
  assert.doesNotMatch(appSource, /Chưa có workspace/);
  assert.match(appSource, /Đăng ký shop mới/);
  assert.match(appSource, /signupLoading \? 'Đang gửi mã\.\.\.' : 'Đăng ký'/);
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
  assert.match(appSource, /Trợ lý tự xử lý/);
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
  assert.match(navSource, />Kho kiến thức</);
  assert.match(navSource, />Quy trình</);
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
  ));
  assert.deepEqual(inactiveButtons, []);
});

test("every directly referenced UI event handler exists", () => {
  const handlerPattern = /@(?:click|submit|change|keyup|keydown)(?:\.[\w]+)*\s*=\s*(["'])\s*([A-Za-z_][\w]*)\s*(?=\(|\1)/g;
  const handlers = new Set(Array.from(templateSource.matchAll(handlerPattern), (match) => match[2]));
  const missing = Array.from(handlers).filter((handler) => !new RegExp(`\\b(?:async\\s+)?function\\s+${handler}\\s*\\(`).test(appSource));
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
