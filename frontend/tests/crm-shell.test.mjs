import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const indexSource = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const channelUtilsSource = fs.readFileSync(new URL("../src/channel-utils.js", import.meta.url), "utf8");

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

test("Knowledge Base exposes durable RAG run status and retry action", () => {
  assert.match(appSource, /documentRuns/);
  assert.match(appSource, /\/documents\/\$\{doc\.id\}\/runs/);
  assert.match(appSource, /RAG run/);
  assert.match(appSource, /Thử lại indexing/);
});

test("CRM operations expose attribution, lead conversion, and lead activity actions", () => {
  assert.match(appSource, /revenue-attribution\?model=last_touch/);
  assert.match(appSource, /Tính lại nguồn doanh thu/);
  assert.match(appSource, /leads\/\$\{lead\.id\}\/activities/);
  assert.match(appSource, /leads\/\$\{lead\.id\}\/convert/);
  assert.match(appSource, /Ghi nhận chuyển đổi/);
  assert.match(appSource, /Hoạt động/);
});

test("Team settings expose tenant-scoped permission overrides", () => {
  assert.match(appSource, /team\/permissions/);
  assert.match(appSource, /permissionForm/);
  assert.match(appSource, /Quyền chi tiết/);
  assert.match(appSource, /Từ chối luôn được ưu tiên/);
  assert.match(appSource, /Thêm quy tắc/);
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

test("top workspace controls are interactive and searchable", () => {
  assert.match(appSource, /class="top-search-input"/);
  assert.match(appSource, /@keydown\.enter="runGlobalSearch"/);
  assert.match(appSource, /function runGlobalSearch/);
  assert.match(appSource, /@click="openNotifications"/);
  assert.match(appSource, /function openNotifications/);
  assert.match(appSource, /@click="openSettings"/);
});

test("inbox uses a polished filter toolbar instead of a native multi-select", () => {
  assert.match(appSource, /class="inbox-toolbar"/);
  assert.match(appSource, /class="inbox-filter-panel"/);
  assert.match(appSource, /class="tag-chip-list"/);
  assert.match(appSource, /toggleTagFilter/);
  assert.match(appSource, /class="segment-control"/);
  assert.doesNotMatch(appSource, /class="segment-filter" multiple/);
});

test("inbox platform filters keep complete labels in a compact channel grid", () => {
  assert.match(appSource, /class="inbox-channel-filter"/);
  assert.match(appSource, /class="inbox-channel-all"/);
  assert.match(appSource, /class="inbox-channel-grid"/);
  assert.match(appSource, /class="channel-tab-icon"/);
  assert.match(appSource, /class="channel-tab-label"/);
  assert.match(styleSource, /\.inbox-channel-grid[\s\S]*?display:\s*grid/);
  assert.match(styleSource, /\.inbox-channel-all[\s\S]*?grid-column:\s*1\s*\/\s*-1/);
  assert.match(styleSource, /\.inbox-channel-button[\s\S]*?min-width:\s*0/);
  assert.match(styleSource, /\.channel-tab-label[\s\S]*?white-space:\s*nowrap/);
  assert.doesNotMatch(appSource, /class="inbox-channel-scroll"/);
  assert.doesNotMatch(styleSource, /\.inbox-channel-scroll/);
  assert.doesNotMatch(styleSource, /\.inbox-channel-tabs button span\s*\{[^}]*text-overflow:\s*ellipsis/s);
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
