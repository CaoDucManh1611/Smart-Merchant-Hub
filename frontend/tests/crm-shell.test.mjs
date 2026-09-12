import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const indexSource = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const channelUtilsSource = fs.readFileSync(new URL("../src/channel-utils.js", import.meta.url), "utf8");

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

test("CRM shell exposes the product's operational navigation", () => {
  assert.match(appSource, />Inbox &amp; Customer 360</);
  assert.match(appSource, />Đơn bán</);
  assert.match(appSource, />Đơn nhập</);
  assert.match(appSource, />Báo cáo</);
  assert.match(appSource, /data-testid="crm-brand-mark"/);
});

test("sidebar groups customer, operations, AI, and system navigation", () => {
  assert.match(appSource, /class="menu-group menu-group-customer"/);
  assert.match(appSource, /class="menu-group menu-group-operations"/);
  assert.match(appSource, /class="menu-group menu-group-ai"/);
  assert.match(appSource, /class="menu-group menu-group-system"/);
  assert.match(appSource, /class="menu-group-label"/);
  assert.doesNotMatch(appSource, /<b>Customer 360<\/b>/);
});

test("AI Rule Lab supports creating and filtering explainable rule suggestions", () => {
  assert.match(appSource, /aiRuleForm/);
  assert.match(appSource, /createRuleSuggestion/);
  assert.match(appSource, /ruleSuggestionFilter/);
  assert.match(appSource, /Lưu đề xuất rule/);
  assert.match(appSource, /Chờ duyệt/);
  assert.match(appSource, /Đã duyệt/);
  assert.match(appSource, /Từ chối/);
  assert.match(appSource, /suggestion.proposed_action/);
  assert.match(appSource, /Chưa đồng bộ database AI/);
});

test("AI experiments can be created from the AI Lab", () => {
  assert.match(appSource, /experimentForm/);
  assert.match(appSource, /createExperiment/);
  assert.match(appSource, /Tạo experiment/);
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
  assert.match(appSource, /RAG run/);
  assert.match(appSource, /retryDocumentRun/);
  assert.match(appSource, /\/documents\/runs\/\$\{run\.id\}\/retry/);
  assert.match(appSource, /Thử lại indexing/);
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
  assert.match(appSource, /Nguồn attribution/);
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
  assert.match(appSource, /Quota|Giới hạn/);
  assert.match(appSource, /schema-per-tenant/);
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
  assert.match(appSource, /Ctrl\+K|Cmd\+K/);
  assert.match(appSource, /Tạo ticket nhanh/);
  assert.match(appSource, /Tạo đơn nháp nhanh/);
  assert.match(appSource, /Nhân viên tiếp quản/);
  assert.match(appSource, /quick-action-dialog/);
});

test("AI navigation keeps the Rule Lab and Assistant under one group", () => {
  assert.match(appSource, /class="ai-submenu"/);
  assert.match(appSource, />AI Rule Lab</);
  assert.match(appSource, />AI Assistant</);
  assert.match(styleSource, /\.menu-group-ai/);
  assert.match(styleSource, /\.ai-submenu/);
});

test("Customer 360 labels the complete profile timeline", () => {
  assert.match(appSource, /identity:\s*"Danh tính đa kênh"/);
  assert.match(appSource, /fact:\s*"Customer Fact"/);
  assert.match(appSource, /ticket_event:\s*"Lịch sử ticket"/);
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
  assert.match(appSource, /Không tải được Customer 360\. Hãy thử lại\./);
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
  assert.match(appSource, /Điểm CSAT/);
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
  assert.match(appSource, /aria-label="Mở Customer 360"[\s\S]*?@click="openMobileCustomer"/);
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
  assert.match(appSource, /const sidebarCollapsed = ref\(true\)/);
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
