<script setup>
import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  nextTick,
} from "vue";

import "./style.css";
import { channelLabel } from "./channel-utils.js";
import { customerTagNames, matchesCustomerTagFilter } from "./customer-utils.js";
import { filterConversationsForCustomer } from "./ticket-utils.js";
import { displayAttachments, resolveMediaUrl } from "./media-utils.js";
import { getInboxChannels } from "./inbox-utils.js";
import { conversationBotStatus, timelineActor } from "./timeline-utils.js";
import { notificationDestination, unreadNotificationCount } from "./notification-utils.js";
import { maskCustomerEmail, maskCustomerName, maskCustomerPhone } from "./privacy-utils.js";
import { apiFetch } from "./api-client.js";
import { clearAuthToken, readAuthToken, requireBusinessId, storeAuthToken } from "./auth-context.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";

// Convert technical/network failures into a short message that is useful to
// a shop owner.  The original error is still available through `cause` and
// console logging for diagnostics; it is never shown in the shop UI.
function friendlyErrorMessage(error, fallback = "Chưa thể hoàn tất yêu cầu. Vui lòng thử lại sau.") {
  const rawMessage = error?.message
    || (typeof error === "string" ? error : error?.detail?.message || error?.detail || "");
  const message = String(rawMessage).trim();
  if (!message) return fallback;
  if (/failed\b|networkerror|network request failed|load failed|connection refused|timeout|exception|(?:^|\s)http\s*\d{3}|internal server|backend|máy chủ|server|smtp|database|sql|traceback|\bapi\b|oauth|webhook|access[_ -]?token|\btoken\b/i.test(message)) {
    return fallback;
  }
  return message;
}


/* =========================================================
   STATE
========================================================= */

const conversations = ref([]);
const messages = ref([]);
const customer360 = ref(null);
const customer360Loading = ref(false);
const customer360Error = ref("");
const customer360OverflowOpen = ref(false);

const customer360ContactGroups = computed(() => {
  const contacts = Array.isArray(customer360.value?.contacts) ? customer360.value.contacts : [];
  return ["phone", "email"].map((kind) => ({
    kind,
    items: contacts
      .filter((contact) => contact.kind === kind)
      .sort((left, right) => Number(right.is_primary) - Number(left.is_primary) || Number(left.id) - Number(right.id)),
  }));
});

const customer360PrimaryContacts = computed(() => customer360ContactGroups.value
  .map((group) => group.items[0])
  .filter(Boolean));
const customer360ExtraContacts = computed(() => customer360ContactGroups.value
  .flatMap((group) => group.items.slice(1)));
const customer360VisibleAddresses = computed(() => {
  const addresses = Array.isArray(customer360.value?.addresses) ? customer360.value.addresses : [];
  if (!addresses.length) return [];
  const primary = addresses.find((address) => address.is_default) || addresses[0];
  return [primary];
});
const customer360ExtraAddresses = computed(() => {
  const addresses = Array.isArray(customer360.value?.addresses) ? customer360.value.addresses : [];
  const visible = customer360VisibleAddresses.value[0];
  return visible ? addresses.filter((address) => Number(address.id) !== Number(visible.id)) : [];
});
const customer360OverflowCount = computed(() => customer360ExtraContacts.value.length + customer360ExtraAddresses.value.length);
const customerFactSaving = ref(false);
const customerFactError = ref("");
const customerFactDraft = ref({
  fact_type: "preference",
  fact_key: "",
  fact_value: "",
  confidence: 1,
  is_verified: true,
});

const selectedId = ref(null);
const conversationActionsOpen = ref(false);
const conversationPriorityIds = ref(new Set());
const conversationFavoriteIds = ref(new Set());
const composerMode = ref("reply");

const activeFilter = ref("all");
const inboxQuickFilter = ref("all");
const tagCatalog = ref([]);
const tagFilters = ref([]);
const tagFilterMode = ref("all");
const savedSegments = ref([]);
const selectedSegmentId = ref("");
const segmentCustomerIds = ref(new Set());
const segmentLoading = ref(false);
const segmentSaving = ref(false);
const segmentError = ref("");
const segmentEditingId = ref("");
const segmentForm = ref({ name: "", description: "", tag_ids: [], match_mode: "all" });
const customerTagDraft = ref("");
const customerTagSaving = ref(false);
const customerTagError = ref("");

const search = ref("");
const draft = ref("");
const quickActionOpen = ref(false);
const quickActionQuery = ref("");
const quickActionInput = ref(null);
const inboxSearchInput = ref(null);
const mobileInboxTrigger = ref(null);
const mobileCustomerTrigger = ref(null);
const mobileCustomerClose = ref(null);
const chatHeading = ref(null);

const loading = ref(false);
const sending = ref(false);
const sendingImage = ref(false);
const failedAvatarUrls = ref(new Set());

const error = ref("");
const appDialog = ref(null);

function requestConfirmation(message, options = {}) {
  return new Promise((resolve) => {
    appDialog.value = {
      title: options.title || "Xác nhận thao tác",
      message,
      confirmLabel: options.confirmLabel || "Xác nhận",
      cancelLabel: options.cancelLabel || "Hủy",
      tone: options.tone || "default",
      resolve,
    };
  });
}

function resolveAppDialog(confirmed) {
  const dialog = appDialog.value;
  appDialog.value = null;
  dialog?.resolve?.(confirmed);
}

/* IMAGE */

const pendingMedia = ref([]);
const fileInput = ref(null);
const voiceRecording = ref(false);
const voiceRecordingSeconds = ref(0);

const VOICE_RECORDING_MAX_SECONDS = 120;
let voiceRecorder = null;
let voiceRecorderStream = null;
let voiceRecorderChunks = [];
let voiceRecordingTimer = null;
let voiceRecordingDiscarded = false;

let pollingTimer = null;
let socket = null;
let reconnectTimer = null;

/* RAG & TAB STATE */
const currentTab = ref("inbox"); // 'inbox' | 'products' | 'orders' | 'leads' | 'tickets' | 'reports' | 'documents' | 'rag_chat' | 'experiments' | 'channels' | 'webhooks' | 'settings' | 'service'
// The inbox is the primary working surface. Keep navigation compact by default;
// users can still expand it with the persistent control at the bottom.
// Keep the full navigation visible on desktop so the workspace feels like a
// complete customer-support console; users can still collapse it on demand.
const sidebarCollapsed = ref(false);
const customerPanelCollapsed = ref(false);
const mobileInboxOpen = ref(false);
const mobileCustomerOpen = ref(false);
const workspaceGreeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 12) return "Chào buổi sáng!";
  if (hour < 18) return "Chào buổi chiều!";
  return "Chào buổi tối!";
});

const products = ref([]);
const productsLoading = ref(false);
const productSaving = ref(false);
const productError = ref("");
const productUploading = ref(false);
const productUploadNotice = ref("");
const productFileInput = ref(null);
const productAdjustmentDrafts = ref({});
const productAdjustmentSaving = ref({});
const inventoryAdjustmentOpen = ref(null);
const productForm = ref({
  id: null,
  sku: "",
  name: "",
  description: "",
  price: 0,
  stock_quantity: 0,
  status: "active",
});
const orders = ref([]);
const ordersLoading = ref(false);
const orderSaving = ref(false);
const orderError = ref("");
const orderCustomers = ref([]);
const revenueByChannel = ref([]);
const orderPaymentDrafts = ref({});
const orderPaymentSaving = ref({});
const orderTransitionSaving = ref({});
const selectedOrderEvents = ref(null);
const orderEventsLoading = ref(false);
const orderLogisticsDraft = ref({
  shipping_provider: "",
  tracking_code: "",
  shipping_status: "pending",
});
const orderLogisticsSaving = ref(false);
const purchasePaymentDrafts = ref({});
const purchasePaymentSaving = ref({});
const inventoryReport = ref(null);
const purchaseCostReport = ref(null);
function generateSalesOrderNumber() {
  const suffix = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `ORD-${Date.now()}-${suffix}`;
}

function createOrderItem(productId = "") {
  return { product_id: productId, quantity: 1 };
}

const orderForm = ref({
  order_number: generateSalesOrderNumber(),
  customer_id: "",
  conversation_id: "",
  items: [createOrderItem()],
});
const purchaseOrders = ref([]);
const purchaseOrdersLoading = ref(false);
const purchaseOrderSaving = ref(false);
const purchaseOrderError = ref("");
const suppliers = ref([]);
const suppliersLoading = ref(false);
const selectedPurchaseOrderEvents = ref(null);
const purchaseOrderEventsLoading = ref(false);
const purchaseReceiptDrafts = ref({});
const supplierSaving = ref(false);
const supplierForm = ref({ code: "", name: "" });
const purchaseOrderForm = ref({
  po_number: "",
  supplier_id: "",
  supplier_name: "",
  product_id: "",
  quantity: 1,
  unit_cost: 0,
  notes: "",
});
const purchaseStatuses = ["draft", "submitted", "partially_received", "received", "closed", "cancelled"];
const salesStatusTransitions = Object.freeze({
  draft: ["confirmed", "cancelled"],
  confirmed: ["processing", "cancelled"],
  processing: ["shipped", "cancelled"],
  shipped: ["delivered"],
  delivered: ["completed"],
  completed: [],
  refunded: [],
  cancelled: [],
});

function salesStatusOptions(order) {
  const current = String(order?.status || "").trim().toLowerCase();
  const next = salesStatusTransitions[current] || [];
  return [current, ...next].filter((status, index, statuses) => status && statuses.indexOf(status) === index);
}

const authUser = ref(null);
const authToken = ref(readAuthToken());
const authLoading = ref(false);
const authError = ref("");
const authRateLimitSeconds = ref(0);
let authRateLimitTimer = null;
const loginForm = ref({ email: "", password: "", shop_slug: "" });
const quotaSnapshot = ref(null);
const quotaLoading = ref(false);
const quotaError = ref("");
const serviceAccountSummary = ref(null);
const serviceAccountLoading = ref(false);
const serviceAccountError = ref("");
const auditLogs = ref([]);
const auditLoading = ref(false);
const platformAdmin = ref(false);
const platformShops = ref([]);
const platformSchemas = ref([]);
const platformAuditLogs = ref([]);
const platformProviderErrors = ref([]);
const platformLoading = ref(false);
const platformError = ref("");
const authSessions = ref([]);
const securityLoading = ref(false);
const securityError = ref("");
const mfaProvisioningUri = ref("");
const mfaVerifyCode = ref("");
const mfaVerifyPending = ref(false);
const privacyLoading = ref(false);
const privacyResult = ref(null);
const customerMergeSourceId = ref("");
const customerMergeSaving = ref(false);
const customerMergeError = ref("");
const customerMergePreview = ref(null);
const customerMergeHistory = ref([]);
const duplicateSuggestions = ref([]);
const customerTimelineLoading = ref(false);
const customerTimelineError = ref("");
const leads = ref([]);
const leadsLoading = ref(false);
const leadSaving = ref(false);
const leadError = ref("");
const leadActivities = ref({});
const leadActivityVisible = ref({});
const leadActivityDrafts = ref({});
const leadActivityLoading = ref({});
const leadConversionOrders = ref({});
const leadConversionSaving = ref({});
const pipelineSummary = ref([]);
const leadForm = ref({
  title: "",
  customer_id: "",
  conversation_id: "",
  stage: "new",
  value: 0,
  probability: 0,
});
const tickets = ref([]);
const ticketsLoading = ref(false);
const ticketSaving = ref(false);
const ticketError = ref("");
const ticketReport = ref({ items: [], overdue_tickets: 0 });
const slaNotifications = ref([]);
const operationalNotifications = ref([]);
const notificationsOpen = ref(false);
const ticketHistory = ref({});
const ticketHistoryLoading = ref({});
const ticketCommentDrafts = ref({});
const crmOverview = ref(null);
const revenueAttribution = ref(null);
const attributionSaving = ref(false);
const agentPerformance = ref([]);
const reportsLoading = ref(false);
const reportsError = ref("");
const reportCsvDownloading = ref(false);
const reportCsvStatus = ref("");
const qualityDashboard = ref({ period_days: 30, usage: {}, provider: {}, ai: {}, sla: {} });
const reportFilters = ref({ start_at: "", end_at: "", channel: "", source: "", status: "", assigned_user_id: "" });
const ticketForm = ref({
  title: "",
  description: "",
  customer_id: "",
  conversation_id: "",
  priority: "normal",
  assigned_user_id: "",
});
const workflows = ref([]);
const workflowsLoading = ref(false);
const workflowSaving = ref(false);
const workflowError = ref("");
const workflowRuns = ref({});
const workflowRunsLoading = ref({});
const ruleSuggestions = ref([]);
const experiments = ref([]);
const modelVersions = ref([]);
const experimentReports = ref({});
const aiEvaluationDashboard = ref({ models: {}, experiments: {}, rag: {}, period_days: 30 });
const banditPolicies = ref({});
const banditPolicyForms = ref({});
const experimentationLoading = ref(false);
const experimentationError = ref("");
const ruleSuggestionFilter = ref("pending");
const aiRuleSaving = ref(false);
const aiRuleForm = ref({
  title: "",
  rationale: "",
  action_type: "add_tag",
  action_tag: "",
  action_title: "",
  action_priority: "normal",
  action_user_id: "",
  workflow_id: "",
});
const experimentSaving = ref(false);
const experimentForm = ref({ name: "", variants: "A\nB", status: "draft", min_sample_size: 0, target_conversion_rate: "" });
const modelSaving = ref(false);
const modelForm = ref({ name: "lead-score", version: "v1", feature_version: "v1", target: "conversion" });
const workflowForm = ref({
  name: "",
  event_type: "message.created",
  condition_channel: "",
  action_type: "create_ticket",
  action_title: "",
  action_priority: "normal",
  action_tag: "",
  action_user_id: "",
  enabled: true,
});
const teamUsers = ref([]);
const teamLoading = ref(false);
const teamSaving = ref(false);
const teamError = ref("");
const permissionOverrides = ref([]);
const permissionSaving = ref(false);
const permissionError = ref("");
const permissionForm = ref({
  resource: "orders",
  action: "write",
  effect: "deny",
  role: "agent",
  user_id: "",
});
const teamForm = ref({
  full_name: "",
  email: "",
  role: "agent",
  password: "",
});

const documents = ref([]);
const documentRuns = ref({});
const docsLoading = ref(false);
const docUploading = ref(false);
const docUploadError = ref("");
const docFileInput = ref(null);
let docPollingTimer = null;

const ragMessages = ref([
  {
    role: "assistant",
    content: "Xin chào! Tôi là trợ lý tra cứu của shop. Bạn có thể hỏi về sản phẩm, đơn hàng và chính sách trong kho thông tin.",
    sources: [],
  }
]);
const ragQuery = ref("");
const ragTopK = ref(5);
const ragSending = ref(false);
const autoReplyEnabled = ref(false);
const autoReplySaving = ref(false);
const autoReplyNotice = ref("");
const autoReplyError = ref("");
const ragChatBox = ref(null);
const chatbotConfig = ref({
  name: "Trợ lý bán hàng",
  enabled: true,
  handoff_enabled: true,
  top_k: 5,
  similarity_threshold: 0.3,
  business_hours: { timezone: "Asia/Ho_Chi_Minh", mon: [["08:00", "17:30"]], tue: [["08:00", "17:30"]], wed: [["08:00", "17:30"]], thu: [["08:00", "17:30"]], fri: [["08:00", "17:30"]] },
});
const chatbotConfigSaving = ref(false);
const chatbotConfigError = ref("");
const businessHoursJson = ref("");
const businessHoursForm = ref({ timezone: "Asia/Ho_Chi_Minh", start: "08:00", end: "17:30", enabled: true });
const businessHoursDays = ref({ mon: true, tue: true, wed: true, thu: true, fri: true, sat: false, sun: false });
const businessHourDayLabels = Object.freeze([
  ["mon", "Thứ 2"], ["tue", "Thứ 3"], ["wed", "Thứ 4"], ["thu", "Thứ 5"],
  ["fri", "Thứ 6"], ["sat", "Thứ 7"], ["sun", "Chủ nhật"],
]);
const businessHoursNotice = ref("");
const slaRulesForm = ref({ firstResponseHours: 2, resolutionHours: 24 });
const slaRulesNotice = ref("");
const channelModalOpen = ref(false);
const channelModalTab = ref("meta");
const textImportOpen = ref(false);
const textImportDraft = ref("");
const textImportTitle = ref("");
const businessProfile = ref({ name: "", logo_url: "", description: "", welcome_message: "", tone: "Thân thiện", language: "Tiếng Việt" });
const voiceSettings = ref({ enabled: false, voice: "Giọng nữ" });
const businessProfileNotice = ref("");
const serviceRequestNotice = ref("");
const serviceLandingOpen = ref(false);
const serviceRequestForm = ref({
  contact_name: "",
  email: "",
  phone: "",
  shop_name: "",
  plan_code: "growth",
  channels: ["Facebook", "Instagram", "Telegram", "Zalo"],
  notes: "",
});
const serviceRequestSubmitted = ref(false);
const serviceRequestReference = ref("");
const serviceRequestError = ref("");
const serviceMode = ref("package");
const servicePurchaseLoading = ref(false);
const servicePurchaseNotice = ref("");
const servicePurchaseError = ref("");
const servicePlans = Object.freeze([
  { code: "starter", name: "Gói Thường", price: "100.000đ / tháng", description: "Gói gọn nhẹ cho shop mới bắt đầu chăm khách.", features: ["Tối đa 3 nhân viên", "1 kênh kết nối", "10 tài liệu hướng dẫn"] },
  { code: "growth", name: "Gói VIP", price: "400.000đ / tháng", description: "Gói cân bằng cho shop cần nhiều kênh và đội ngũ chăm khách.", features: ["Tối đa 10 nhân viên", "2 kênh kết nối", "5.000 lượt trả lời tự động"] },
  { code: "custom", name: "Gói Premium", price: "1.000.000đ / tháng", description: "Gói đầy đủ cho shop vận hành đa kênh.", features: ["Tối đa 50 nhân viên", "4 kênh kết nối", "25.000 lượt trả lời tự động"] },
]);
const chatbotPlans = Object.freeze([
  { code: "bot-starter", name: "Gói Thường · Trợ lý", price: "100.000đ / tháng", description: "Trợ lý trả lời câu hỏi thường gặp và giới thiệu sản phẩm.", features: ["Tối đa 3 nhân viên", "1 kênh kết nối", "500 lượt trả lời tự động"] },
  { code: "bot-growth", name: "Gói VIP · Trợ lý", price: "400.000đ / tháng", description: "Trợ lý theo sát khách và chuyển người thật khi cần.", features: ["Học từ tài liệu shop", "Quy trình chuyển nhân viên", "5.000 lượt trả lời tự động"] },
  { code: "bot-custom", name: "Gói Premium · Trợ lý", price: "1.000.000đ / tháng", description: "Trợ lý theo cách nói riêng và nhu cầu đa kênh của shop.", features: ["Kịch bản riêng", "Tinh chỉnh theo hội thoại", "4 kênh kết nối"] },
]);
const activeServicePlans = computed(() => serviceMode.value === "chatbot" ? chatbotPlans : servicePlans);
const messageLearningEnabled = ref(true);
const reinforcementLearningEnabled = ref(true);
const learningNotice = ref("");
const darkMode = ref(false);
const cannedResponses = ref([]);
const selectedCannedId = ref("");
const cannedResponseForm = ref({ shortcut: "/cod", title: "COD", content: "Shop hỗ trợ thanh toán COD.", enabled: true });
const cannedResponseSaving = ref(false);
const cannedResponseError = ref("");
const botModes = ref({});
const followups = ref([]);
const followupsLoading = ref(false);
const followupDispatching = ref(false);
const followupNotice = ref("");
const followupError = ref("");
const csatFeedback = ref([]);
const csatSummary = ref({ responses: 0, average_rating: 0, satisfaction_rate: 0, bot_resolution_rate: 0 });
const csatLoading = ref(false);
const csatError = ref("");

const metaStatus = ref({
  connected: false,
  facebook_page_id: "",
  facebook_page_name: "",
  instagram_account_id: "",
  subscription_status: "",
});
const metaLoading = ref(false);
const metaNotice = ref("");
const botConnections = ref([]);
const botConnectionLoading = ref(false);
const botConnectionSaving = ref(false);
const botConnectionError = ref("");
const botConnectionNotice = ref("");
const botTokenVisible = ref(false);
const botConnectionForm = ref({ channel_type: "telegram", access_token: "" });
const notificationError = ref("");
const activeBotConnections = computed(() => botConnections.value.filter((item) => ["connected", "active"].includes(String(item.status || "").toLowerCase())));


/* META OAUTH */
async function fetchMetaStatus() {
  try {
    const res = await apiFetch(`${API_BASE}/oauth/meta/status`);
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${res.status}`);
    }
    metaStatus.value = await res.json();
  } catch (e) {
    console.error("Fetch Meta OAuth status error:", e);
    metaNotice.value = "Chưa thể kiểm tra kết nối Facebook/Instagram lúc này. Vui lòng thử lại sau.";
  }
}

async function connectMeta() {
  metaLoading.value = true;
  metaNotice.value = "";
  try {
    // The authenticated request creates a state bound to this tenant.  A
    // direct location change cannot include the bearer token required in
    // production, so only the returned Meta URL is opened in the browser.
    const response = await apiFetch(`${API_BASE}/oauth/meta/start?return_url=true`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || "Chưa thể bắt đầu kết nối Facebook/Instagram. Vui lòng thử lại sau.");
    }
    const payload = await response.json();
    if (!payload.authorization_url) {
      throw new Error("Chưa nhận được đường dẫn kết nối Facebook/Instagram. Vui lòng thử lại sau.");
    }
    window.location.assign(payload.authorization_url);
  } catch (error) {
    metaNotice.value = "Chưa thể bắt đầu kết nối Facebook/Instagram. Vui lòng thử lại sau.";
  } finally {
    metaLoading.value = false;
  }
}

const botGuideUrls = Object.freeze({
  telegram: "https://t.me/BotFather",
  zalo: "https://chat.zalo.me/",
});

function botGuideUrl(channelType) {
  return botGuideUrls[channelType] || botGuideUrls.telegram;
}

function botQrUrl(channelType) {
  const target = botGuideUrl(channelType);
  return `https://quickchart.io/qr?size=160&margin=2&text=${encodeURIComponent(target)}`;
}

function botChannelLabel(channelType) {
  return channelType === "zalo" ? "Zalo cá nhân" : "Telegram BotFather";
}

function botConnectionStateLabel(state) {
  const labels = {
    connected: "Đang hoạt động",
    active: "Đang hoạt động",
    disconnected: "Đã ngắt kết nối",
    reconnect_required: "Cần kết nối lại",
    verifying: "Đang xác minh",
    error: "Lỗi kết nối",
  };
  return labels[String(state || "").toLowerCase()] || "Chưa xác định";
}

function botConnectionErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (detail && typeof detail === "object") return detail.message || fallback;
  return detail || fallback;
}

function apiResponseError(response, payload, fallback) {
  const error = new Error(botConnectionErrorMessage(payload, fallback));
  // Keep the status on the thrown error so the UI can distinguish an expired
  // session from a provider/readiness failure instead of hiding every case
  // behind one generic "server not ready" message.
  error.status = response?.status;
  error.payload = payload;
  return error;
}

async function fetchBotConnections() {
  botConnectionLoading.value = true;
  botConnectionError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/channels`);
    const detail = await response.json().catch(() => []);
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    botConnections.value = Array.isArray(detail)
      ? detail.filter((item) => ["telegram", "zalo"].includes(item.channel_type))
      : [];
  } catch (err) {
    const status = Number(err?.status);
    if (status === 401) {
      botConnectionError.value = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để xem kết nối bot.";
    } else if (status === 403) {
      botConnectionError.value = "Tài khoản hiện tại không có quyền xem kết nối bot của shop này.";
    } else if (status === 423) {
      botConnectionError.value = "Shop đang được chuẩn bị. Bấm Thử lại sau ít giây.";
    } else {
      botConnectionError.value = friendlyErrorMessage(err, "Chưa tải được trạng thái bot. Vui lòng thử lại sau.");
    }
  } finally {
    botConnectionLoading.value = false;
  }
}

async function connectBotChannel() {
  const token = String(botConnectionForm.value.access_token || "").trim();
  if (!token) {
    botConnectionError.value = "Bạn cần dán mã bot trước khi kết nối.";
    return;
  }
  botConnectionSaving.value = true;
  botConnectionError.value = "";
  botConnectionNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/channels/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel_type: botConnectionForm.value.channel_type,
        access_token: botConnectionForm.value.channel_type === "zalo" && !token.toLowerCase().startsWith("personal:")
          ? `personal:${token}`
          : token,
      }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    botConnectionForm.value.access_token = "";
    botTokenVisible.value = false;
    botConnectionNotice.value = `${botChannelLabel(botConnectionForm.value.channel_type)} đã kết nối và nhận tin đang hoạt động.`;
    await fetchBotConnections();
  } catch (err) {
    botConnectionError.value = friendlyErrorMessage(err, "Chưa thể kiểm tra và kết nối bot. Hãy kiểm tra lại mã bot rồi thử lại.");
  } finally {
    botConnectionSaving.value = false;
  }
}

async function disconnectBotChannel(connection) {
  if (!(await requestConfirmation(`Ngắt kết nối ${connection?.name || "bot này"}?`, {
    title: "Ngắt kết nối bot",
    confirmLabel: "Ngắt kết nối",
    tone: "danger",
  }))) return;
  botConnectionLoading.value = true;
  botConnectionError.value = "";
  botConnectionNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/channels/${connection.id}`, { method: "DELETE" });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    botConnectionNotice.value = "Đã ngắt kết nối bot nhưng vẫn giữ nguyên lịch sử hội thoại.";
    await fetchBotConnections();
  } catch (err) {
    botConnectionError.value = friendlyErrorMessage(err, "Chưa thể ngắt kết nối bot. Vui lòng thử lại sau.");
  } finally {
    botConnectionLoading.value = false;
  }
}

function openChannels() {
  currentTab.value = "channels";
  if (!authUser.value) return;
  void fetchMetaStatus();
  void fetchBotConnections();
  void fetchQuotaUsage();
}

function openChannelModal(tab = "meta") {
  // Keep each provider in its own focused dialog.  The old `bots` tab is
  // accepted for bookmarks/tests, but immediately resolves to Telegram so a
  // shop never submits a token for the wrong provider.
  const normalized = tab === "bots" ? "telegram" : tab;
  channelModalTab.value = ["meta", "facebook", "instagram", "telegram", "zalo"].includes(normalized) ? normalized : "meta";
  if (["telegram", "zalo"].includes(channelModalTab.value)) {
    botConnectionForm.value.channel_type = channelModalTab.value;
    botConnectionForm.value.access_token = "";
    botTokenVisible.value = false;
    botConnectionNotice.value = "";
    botConnectionError.value = "";
  }
  channelModalOpen.value = true;
}

function closeChannelModal() {
  channelModalOpen.value = false;
}

function openWebhooks() {
  currentTab.value = "webhooks";
  if (!authUser.value) return;
  void fetchMetaStatus();
  void fetchBotConnections();
}

async function refreshWebhookStatus() {
  await Promise.all([fetchMetaStatus(), fetchBotConnections()]);
}

function openSettings() {
  currentTab.value = "settings";
  if (!authUser.value) return;
  void fetchTeam();
  void fetchAuditLogs();
  void fetchSecuritySettings();
  void fetchPlatformAdmin();
  void fetchChatbotRuntime();
  void fetchFollowups();
  void fetchCsat();
  void fetchQuotaUsage();
  void fetchServiceAccountSummary();
}

function businessProfileStorageKey() {
  const businessId = authUser.value?.business_id || authUser.value?.business?.id || "shop";
  return `crm-business-profile-${businessId}`;
}

function loadBusinessProfile() {
  try {
    const saved = JSON.parse(localStorage.getItem(businessProfileStorageKey()) || "{}");
    businessProfile.value = { ...businessProfile.value, ...(saved.profile || {}) };
    voiceSettings.value = { ...voiceSettings.value, ...(saved.voice || {}) };
    // Older local preferences used regional voice names. Keep the setting
    // compatible while presenting only the simple Nam/Nữ choices in the UI.
    const storedVoice = String(voiceSettings.value.voice || "").toLowerCase();
    voiceSettings.value.voice = storedVoice.includes("nữ") ? "Giọng nữ" : storedVoice.includes("nam") ? "Giọng nam" : "Giọng nữ";
    const learning = JSON.parse(localStorage.getItem(`crm-learning-preferences-${authUser.value?.business_id || "shop"}`) || "{}");
    messageLearningEnabled.value = learning.messageLearningEnabled ?? messageLearningEnabled.value;
    reinforcementLearningEnabled.value = learning.reinforcementLearningEnabled ?? reinforcementLearningEnabled.value;
  } catch {
    // Ignore malformed local preferences; the defaults remain usable.
  }
}

function themeStorageKey() {
  const businessId = authUser.value?.business_id || authUser.value?.business?.id || "shop";
  return `crm-theme-${businessId}`;
}

function loadThemePreference() {
  try {
    darkMode.value = localStorage.getItem(themeStorageKey()) === "dark";
  } catch {
    darkMode.value = false;
  }
  document.documentElement.classList.toggle("crm-dark", darkMode.value);
  document.body.classList.toggle("crm-dark", darkMode.value);
}

function toggleDarkMode() {
  darkMode.value = !darkMode.value;
  document.documentElement.classList.toggle("crm-dark", darkMode.value);
  document.body.classList.toggle("crm-dark", darkMode.value);
  try {
    localStorage.setItem(themeStorageKey(), darkMode.value ? "dark" : "light");
  } catch {
    // Theme still applies for this session when storage is unavailable.
  }
}

function saveBusinessProfile() {
  try {
    localStorage.setItem(businessProfileStorageKey(), JSON.stringify({ profile: businessProfile.value, voice: voiceSettings.value }));
    businessProfileNotice.value = "Đã lưu thông tin shop trên thiết bị này.";
  } catch {
    businessProfileNotice.value = "Chưa thể lưu thông tin trên thiết bị này. Vui lòng thử lại sau.";
  }
}

function saveLearningPreferences() {
  try {
    localStorage.setItem(`crm-learning-preferences-${authUser.value?.business_id || "shop"}`, JSON.stringify({ messageLearningEnabled: messageLearningEnabled.value, reinforcementLearningEnabled: reinforcementLearningEnabled.value }));
    learningNotice.value = "Đã lưu lựa chọn học từ hội thoại.";
  } catch {
    learningNotice.value = "Chưa thể lưu lựa chọn trên thiết bị này. Vui lòng thử lại sau.";
  }
}

function previewWelcomeVoice() {
  const text = String(businessProfile.value.welcome_message || "Xin chào, shop rất vui được hỗ trợ bạn.");
  if (!window.speechSynthesis) {
    businessProfileNotice.value = "Trình duyệt chưa hỗ trợ đọc giọng nói.";
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "vi-VN";
  const voiceNames = window.speechSynthesis.getVoices?.() || [];
  const wantsMale = voiceSettings.value.voice === "Giọng nam";
  const genderPattern = wantsMale ? /\b(male|nam|man)\b/i : /\b(female|nữ|nu|woman)\b/i;
  utterance.voice = voiceNames.find((voice) => voice.lang?.toLowerCase().startsWith("vi") && genderPattern.test(voice.name))
    || voiceNames.find((voice) => voice.lang?.toLowerCase().startsWith("vi"))
    || null;
  window.speechSynthesis.speak(utterance);
  businessProfileNotice.value = "Đang đọc thử lời chào.";
}

function saveBusinessHours() {
  const start = String(businessHoursForm.value.start || "").trim();
  const end = String(businessHoursForm.value.end || "").trim();
  if (businessHoursForm.value.enabled && (!start || !end || start >= end)) {
    businessHoursNotice.value = "Giờ mở cửa phải sớm hơn giờ đóng cửa.";
    return;
  }
  const range = businessHoursForm.value.enabled ? [[start, end]] : [];
  const hours = { timezone: businessHoursForm.value.timezone || "Asia/Ho_Chi_Minh" };
  businessHourDayLabels.forEach(([key]) => { hours[key] = businessHoursDays.value[key] ? range : []; });
  businessHoursJson.value = JSON.stringify(hours);
  businessHoursNotice.value = "Đã cập nhật giờ làm việc theo ngày đã chọn.";
  void saveChatbotRuntime();
}

function saveSlaRules() {
  slaRulesNotice.value = `Đã lưu quy tắc: phản hồi trong ${slaRulesForm.value.firstResponseHours} giờ, xử lý trong ${slaRulesForm.value.resolutionHours} giờ.`;
}

function resetServiceRequestForm() {
  serviceRequestForm.value = {
    contact_name: authUser.value?.full_name || "",
    email: authUser.value?.email || "",
    phone: "",
    shop_name: authUser.value?.business?.name || authUser.value?.business_name || "",
    plan_code: serviceMode.value === "chatbot" ? "bot-growth" : "growth",
    channels: ["Facebook", "Instagram", "Telegram", "Zalo"],
    notes: "",
  };
  serviceRequestSubmitted.value = false;
  serviceRequestReference.value = "";
  serviceRequestError.value = "";
  serviceRequestNotice.value = "";
  servicePurchaseNotice.value = "";
  servicePurchaseError.value = "";
}

function selectServiceMode(mode) {
  serviceMode.value = mode === "chatbot" ? "chatbot" : "package";
  serviceRequestForm.value.plan_code = serviceMode.value === "chatbot" ? "bot-growth" : "growth";
  serviceRequestSubmitted.value = false;
  serviceRequestReference.value = "";
  serviceRequestError.value = "";
  serviceRequestNotice.value = "";
  servicePurchaseNotice.value = "";
  servicePurchaseError.value = "";
}

function openServicePage() {
  serviceLandingOpen.value = false;
  currentTab.value = "service";
  if (!serviceRequestForm.value.contact_name && authUser.value) resetServiceRequestForm();
  if (authUser.value) {
    void fetchQuotaUsage();
    void fetchServiceAccountSummary();
  }
}

function openPublicServicePage() {
  serviceLandingOpen.value = true;
  currentTab.value = "service";
  resetServiceRequestForm();
}

function closePublicServicePage() {
  serviceLandingOpen.value = false;
  currentTab.value = "inbox";
}

function toggleServiceChannel(channel) {
  const selectedChannels = new Set(serviceRequestForm.value.channels || []);
  if (selectedChannels.has(channel)) selectedChannels.delete(channel);
  else selectedChannels.add(channel);
  serviceRequestForm.value.channels = Array.from(selectedChannels);
}

function submitServiceRequest() {
  const form = serviceRequestForm.value;
  const contactName = String(form.contact_name || "").trim();
  const email = String(form.email || "").trim().toLowerCase();
  const shopName = String(form.shop_name || "").trim();
  if (!contactName || !email || !shopName) {
    serviceRequestError.value = "Vui lòng nhập tên, email và tên shop để được tư vấn.";
    return;
  }
  if (!/^\S+@\S+\.\S+$/.test(email)) {
    serviceRequestError.value = "Email chưa đúng định dạng. Hãy kiểm tra lại.";
    return;
  }
  if (!(form.channels || []).length) {
    serviceRequestError.value = "Chọn ít nhất một kênh shop muốn kết nối.";
    return;
  }
  const reference = `SMH-${Date.now().toString(36).toUpperCase()}`;
  const payload = {
    ...form,
    service_type: serviceMode.value,
    service_name: serviceMode.value === "chatbot" ? "Thuê trợ lý chatbot" : "Thuê gói dịch vụ",
    contact_name: contactName,
    email,
    shop_name: shopName,
    reference,
    status: "pending",
    created_at: new Date().toISOString(),
  };
  try {
    const storageKey = `crm-service-request-${authUser.value?.business_id || "public"}-${serviceMode.value}`;
    localStorage.setItem(storageKey, JSON.stringify(payload));
  } catch {
    // The request remains visible in the current page even when storage is blocked.
  }
  serviceRequestReference.value = reference;
  serviceRequestSubmitted.value = true;
  serviceRequestError.value = "";
  serviceRequestNotice.value = serviceMode.value === "chatbot"
    ? "Đã ghi nhận yêu cầu thuê trợ lý trả lời tự động."
    : "Đã ghi nhận yêu cầu thuê gói dịch vụ.";
}

function servicePlanCodeForPurchase(code) {
  const aliases = {
    "bot-starter": "starter",
    "bot-growth": "growth",
    "bot-custom": "pro",
    custom: "pro",
  };
  return aliases[code] || code;
}

async function purchaseServicePlan() {
  if (!authUser.value?.business_id) {
    servicePurchaseError.value = "Hãy đăng nhập vào shop trước khi kích hoạt gói.";
    return;
  }
  const planCode = servicePlanCodeForPurchase(serviceRequestForm.value.plan_code);
  servicePurchaseLoading.value = true;
  servicePurchaseError.value = "";
  servicePurchaseNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/subscription/purchase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_code: planCode, service_type: serviceMode.value }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    servicePurchaseNotice.value = `Đã kích hoạt gói ${detail.plan_name || planCode}. Shop có thể kết nối Telegram, Zalo và thêm nhân viên theo hạn mức.`;
    await fetchQuotaUsage();
  } catch (err) {
    servicePurchaseError.value = friendlyErrorMessage(err, "Chưa thể kích hoạt gói lúc này. Vui lòng thử lại sau.");
  } finally {
    servicePurchaseLoading.value = false;
  }
}

function requestServiceDeployment() {
  openServicePage();
}

function openTextImport() {
  textImportDraft.value = "";
  textImportTitle.value = "";
  textImportOpen.value = true;
}

async function saveTextImport() {
  const content = String(textImportDraft.value || "").trim();
  if (!content) return;
  const filename = `${String(textImportTitle.value || "noi-dung-shop").trim().replace(/[^\\p{L}\\p{N}_-]+/gu, "-") || "noi-dung-shop"}.txt`;
  textImportOpen.value = false;
  await uploadDocumentFile(new File([content], filename, { type: "text/plain" }));
}

function openQuickActions() {
  quickActionOpen.value = true;
  quickActionQuery.value = "";
  nextTick(() => quickActionInput.value?.focus());
}

function closeQuickActions() {
  quickActionOpen.value = false;
  quickActionQuery.value = "";
}

async function runQuickAction(actionId) {
  switch (actionId) {
    case "focus-search":
      closeQuickActions();
      nextTick(() => document.querySelector(".top-search-input")?.focus());
      return;
    case "customer-360":
      currentTab.value = "inbox";
      customerPanelCollapsed.value = false;
      closeQuickActions();
      if (selected.value) openMobileCustomer();
      return;
    case "create-ticket":
      currentTab.value = "tickets";
      await fetchOrderCustomers();
      if (selected.value?.customer_id) {
        ticketForm.value = {
          ...ticketForm.value,
          customer_id: String(selected.value.customer_id),
          conversation_id: selectedId.value ? String(selectedId.value) : "",
        };
      }
      closeQuickActions();
      return;
    case "create-order":
      currentTab.value = "orders";
      await Promise.all([fetchOrderCustomers(), fetchProducts(), fetchOrders()]);
      if (selected.value?.customer_id) {
        orderForm.value = {
          ...orderForm.value,
          customer_id: String(selected.value.customer_id),
          conversation_id: selectedId.value ? String(selectedId.value) : "",
        };
      }
      closeQuickActions();
      return;
    case "toggle-bot":
      closeQuickActions();
      await toggleBotMode();
      return;
    case "settings":
      closeQuickActions();
      openSettings();
      return;
    default:
      closeQuickActions();
  }
}

function handleGlobalKeydown(event) {
  if (event.ctrlKey && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (quickActionOpen.value) closeQuickActions();
    else openQuickActions();
  } else if (event.key === "Escape" && quickActionOpen.value) {
    closeQuickActions();
  } else if (event.key === "Escape" && mobileCustomerOpen.value) {
    closeMobileCustomer();
  } else if (event.key === "Escape" && mobileInboxOpen.value) {
    closeMobileInbox();
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
}

function toggleCustomerPanel() {
  customerPanelCollapsed.value = !customerPanelCollapsed.value;
}

function openMobileInbox() {
  mobileCustomerOpen.value = false;
  mobileInboxOpen.value = true;
  nextTick(() => inboxSearchInput.value?.focus());
}

function closeMobileInbox() {
  mobileInboxOpen.value = false;
  nextTick(() => mobileInboxTrigger.value?.focus());
}

function openMobileCustomer() {
  if (!selected.value) return;
  mobileInboxOpen.value = false;
  mobileCustomerOpen.value = true;
  customerPanelCollapsed.value = false;
  nextTick(() => mobileCustomerClose.value?.focus());
}

function closeMobileCustomer() {
  mobileCustomerOpen.value = false;
  nextTick(() => mobileCustomerTrigger.value?.focus());
}

function runGlobalSearch() {
  currentTab.value = "inbox";
  nextTick(() => document.querySelector(".search-box input")?.focus());
}

async function fetchOperationalNotifications() {
  notificationError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/notifications`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    operationalNotifications.value = await response.json();
  } catch (err) {
    console.warn("Fetch operational notifications error:", err);
    notificationError.value = friendlyErrorMessage(err, "Chưa tải được thông báo. Vui lòng thử lại sau.");
  }
}

async function openNotifications() {
  notificationsOpen.value = !notificationsOpen.value;
  if (notificationsOpen.value) await fetchOperationalNotifications();
}

async function activateNotification(notification) {
  if (!notification.is_read) {
    try {
      const response = await apiFetch(`${API_BASE}/notifications/${notification.id}/read`, { method: "POST" });
      if (response.ok) {
        const updated = await response.json();
        operationalNotifications.value = operationalNotifications.value.map((item) => (
          item.id === updated.id ? updated : item
        ));
      }
    } catch (err) {
      console.warn("Mark notification read error:", err);
    }
  }
  const destination = notificationDestination(notification);
  notificationsOpen.value = false;
  currentTab.value = destination.tab;
  if (destination.tab === "orders") {
    await Promise.all([fetchOrderCustomers(), fetchProducts(), fetchOrders()]);
  } else if (destination.tab === "inbox") {
    await loadConversations(false);
    if (destination.conversationId) await selectConversation(destination.conversationId);
  } else {
    await Promise.all([fetchOrderCustomers(), fetchTickets()]);
  }
}

async function disconnectMeta() {
  if (!(await requestConfirmation("Ngắt kết nối Facebook/Instagram khỏi hệ thống?", {
    title: "Ngắt kết nối Facebook/Instagram",
    confirmLabel: "Ngắt kết nối",
    tone: "danger",
  }))) return;
  metaLoading.value = true;
  try {
    const res = await apiFetch(`${API_BASE}/oauth/meta/disconnect`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${res.status}`);
    }
    metaStatus.value = { connected: false };
    metaNotice.value = "Đã ngắt kết nối Facebook/Instagram.";
  } catch (e) {
    metaNotice.value = "Chưa thể ngắt kết nối Facebook/Instagram. Vui lòng thử lại sau.";
  } finally {
    metaLoading.value = false;
  }
}


/* RAG DOCUMENTS METHODS */
async function fetchDocumentRuns(items) {
  const entries = await Promise.all((items || []).map(async (doc) => {
    try {
      const response = await apiFetch(`${API_BASE}/documents/${doc.id}/runs`);
      if (!response.ok) return [doc.id, null];
      const data = await response.json();
      return [doc.id, data.items?.[0] || null];
    } catch {
      return [doc.id, null];
    }
  }));
  documentRuns.value = Object.fromEntries(entries);
}

async function fetchDocuments() {
  docsLoading.value = true;
  try {
    // Drain one durable ingestion batch before refreshing the list. The same
    // endpoint is safe for a background worker, so the UI remains useful in
    // development without spawning request-owned threads.
    const dispatchResponse = await apiFetch(`${API_BASE}/documents/jobs/dispatch`, { method: "POST" });
    if (!dispatchResponse.ok) {
      const detail = await dispatchResponse.json().catch(() => ({}));
      docUploadError.value = friendlyErrorMessage(detail.detail, "Chưa thể xử lý tài liệu lúc này. Vui lòng thử lại sau.");
    }
    const res = await apiFetch(`${API_BASE}/documents`);
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    documents.value = data.documents || [];
    await fetchDocumentRuns(documents.value);
    const hasProcessing = documents.value.some(
      d => d.status === "pending" || d.status === "processing"
    );
    if (hasProcessing && !docPollingTimer) {
      docPollingTimer = setInterval(fetchDocuments, 3000);
    } else if (!hasProcessing && docPollingTimer) {
      clearInterval(docPollingTimer);
      docPollingTimer = null;
    }
  } catch (err) {
    console.error("Fetch documents error:", err);
    docUploadError.value = friendlyErrorMessage(err, "Chưa tải được tài liệu của shop. Vui lòng thử lại sau.");
  } finally {
    docsLoading.value = false;
  }
}

async function uploadDocumentFile(file) {
  if (!file) return;
  docUploading.value = true;
  docUploadError.value = "";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await apiFetch(`${API_BASE}/documents/upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      let errText = await res.text();
      try {
        const errJson = JSON.parse(errText);
        errText = errJson.detail || errText;
      } catch {}
      throw new Error(errText);
    }
    await fetchDocuments();
  } catch (err) {
    docUploadError.value = friendlyErrorMessage(err, "Chưa thể nhập tài liệu. Vui lòng kiểm tra tệp rồi thử lại.");
  } finally {
    docUploading.value = false;
    if (docFileInput.value) docFileInput.value.value = "";
  }
}

function handleDocFileSelect(e) {
  const file = e.target.files?.[0];
  if (file) uploadDocumentFile(file);
}

function handleDocDrop(e) {
  e.preventDefault();
  const file = e.dataTransfer?.files?.[0];
  if (file) uploadDocumentFile(file);
}

async function deleteDoc(docId) {
  if (!(await requestConfirmation("Bạn có chắc muốn xóa tài liệu này khỏi Kho tri thức?", {
    title: "Xóa tài liệu",
    confirmLabel: "Xóa tài liệu",
    tone: "danger",
  }))) return;
  try {
    const res = await apiFetch(`${API_BASE}/documents/${docId}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${res.status}`);
    }
    documents.value = documents.value.filter(d => d.id !== docId);
    docUploadError.value = "";
  } catch (err) {
    console.error("Delete doc error:", err);
    docUploadError.value = friendlyErrorMessage(err, "Chưa thể xóa tài liệu. Vui lòng thử lại sau.");
  }
}

function formatFileSize(bytes) {
  if (!bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}


/* RAG CHAT PLAYGROUND METHODS */
async function fetchAutoReplySetting() {
  autoReplyError.value = "";
  try {
    const res = await apiFetch(`${API_BASE}/conversations/auto-reply-status`);
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    autoReplyEnabled.value = Boolean(data.auto_reply_enabled);
  } catch (e) {
    console.error("Fetch auto reply error:", e);
    autoReplyError.value = "Chưa tải được trạng thái trả lời tự động. Vui lòng thử lại sau.";
  }
}

async function toggleAutoReply() {
  if (autoReplySaving.value) return;
  autoReplySaving.value = true;
  autoReplyNotice.value = "";
  autoReplyError.value = "";
  try {
    const nextState = !autoReplyEnabled.value;
    const res = await apiFetch(`${API_BASE}/conversations/auto-reply-status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_reply_enabled: nextState }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    autoReplyEnabled.value = Boolean(data.auto_reply_enabled);
    autoReplyNotice.value = autoReplyEnabled.value ? "Đã bật trả lời tự động." : "Đã tắt trả lời tự động.";
  } catch (e) {
    console.error("Toggle auto reply error:", e);
    autoReplyError.value = "Chưa thể cập nhật trả lời tự động. Vui lòng thử lại sau.";
  } finally {
    autoReplySaving.value = false;
  }
}

async function sendRagQuery(presetText = null) {
  const query = (presetText || ragQuery.value).trim();
  if (!query || ragSending.value) return;

  const conversationHistory = ragMessages.value
    .filter(m => m.content && !m.loading)
    .slice(-6)
    .map(m => ({ role: m.role, content: m.content }));

  ragQuery.value = "";
  ragMessages.value.push({
    role: "user",
    content: query,
  });

  const assistantMsg = {
    role: "assistant",
    content: "",
    sources: [],
    loading: true,
  };
  ragMessages.value.push(assistantMsg);
  ragSending.value = true;

  await nextTick();
  scrollRagChatToBottom();

  try {
    const response = await apiFetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        top_k: Number(ragTopK.value) || 5,
        conversation_history: conversationHistory,
      }),
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    assistantMsg.loading = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data: ")) {
          const jsonStr = trimmed.slice(6).trim();
          if (!jsonStr) continue;
          try {
            const data = JSON.parse(jsonStr);
            if (data.type === "sources") {
              assistantMsg.sources = data.sources || [];
            } else if (data.type === "chunk") {
              assistantMsg.content += data.content || "";
              scrollRagChatToBottom();
            } else if (data.type === "error") {
              assistantMsg.content += `\n[Lỗi: ${data.message}]`;
            }
          } catch (e) {
            console.error("SSE parse error", e);
          }
        }
      }
    }
  } catch (err) {
    assistantMsg.loading = false;
    assistantMsg.content = `❌ Chưa thể trả lời lúc này. ${friendlyErrorMessage(err, "Vui lòng thử lại sau.")}`;
  } finally {
    ragSending.value = false;
    scrollRagChatToBottom();
  }
}

function scrollRagChatToBottom() {
  nextTick(() => {
    if (ragChatBox.value) {
      ragChatBox.value.scrollTop = ragChatBox.value.scrollHeight;
    }
  });
}



/* =========================================================
   COMPUTED
========================================================= */

const selected = computed(() => {

  return conversations.value.find(
    (item) =>
      item.conversation_id === selectedId.value
  );

});

const selectedBotMode = computed(() => (
  selected.value?.conversation_id
    ? botModes.value[selected.value.conversation_id] || selected.value.bot_mode || "auto"
    : "auto"
));

const quickActionItems = computed(() => {
  const items = [
    { id: "focus-search", label: "Tìm kiếm khách hàng, tin nhắn, đơn hàng", hint: "Ctrl+K" },
    { id: "customer-360", label: "Mở hồ sơ khách hàng 360", hint: selected.value ? "Khách đang chọn" : "Chọn hội thoại trước", disabled: !selected.value },
    { id: "create-ticket", label: "Tạo phiếu hỗ trợ nhanh", hint: selected.value ? "Từ khách đang chọn" : "Chọn hội thoại trước", disabled: !selected.value },
    { id: "create-order", label: "Tạo đơn nháp nhanh", hint: selected.value ? "Từ khách đang chọn" : "Chọn hội thoại trước", disabled: !selected.value },
    { id: "toggle-bot", label: selectedBotMode.value === "human" ? "Trả hội thoại về bot" : "Nhân viên tiếp quản", hint: selected.value ? "Hội thoại đang chọn" : "Chọn hội thoại trước", disabled: !selected.value },
    { id: "settings", label: "Mở Cài đặt", hint: "Bảo mật & vận hành" },
  ];
  const query = quickActionQuery.value.trim().toLowerCase();
  return query ? items.filter((item) => `${item.label} ${item.hint}`.toLowerCase().includes(query)) : items;
});

const unreadOperationalNotificationCount = computed(() => (
  unreadNotificationCount(operationalNotifications.value)
));

const conversationPriorityActive = computed(() => (
  selectedId.value !== null
  && conversationPriorityIds.value.has(selectedId.value)
));

const conversationFavoriteActive = computed(() => (
  selectedId.value !== null
  && conversationFavoriteIds.value.has(selectedId.value)
));


// A ticket may only reference a conversation owned by its selected customer.
// Keep this list derived from the tenant-scoped inbox data so the form cannot
// accidentally submit an unrelated conversation id.
const ticketConversations = computed(() => {
  return filterConversationsForCustomer(
    conversations.value,
    ticketForm.value.customer_id,
  );
});

// Sales orders may only link revenue to a conversation belonging to the
// selected customer.  When no customer is selected yet, expose all tenant
// conversations so the dropdown remains useful while the form is loading.
const orderConversationOptions = computed(() => {
  const customerId = Number(orderForm.value.customer_id);
  const source = customerId
    ? filterConversationsForCustomer(conversations.value, customerId)
    : conversations.value;
  return [...source]
    .filter((conversation) => Number(conversation?.conversation_id) > 0)
    .sort((left, right) => Number(right.conversation_id) - Number(left.conversation_id));
});

const selectedOrderCustomer = computed(() => (
  orderCustomers.value.find(
    (customer) => Number(customer.id) === Number(orderForm.value.customer_id),
  ) || null
));

const selectedOrderCustomerPhone = computed(() => (
  maskCustomerPhone(selectedOrderCustomer.value?.phone)
));

// The lower order strip is contextual: it only renders an actual order that
// belongs to the customer selected in Inbox.  It never creates presentation
// data on the client.
const latestSelectedOrder = computed(() => {
  const customerId = Number(selected.value?.customer_id);
  if (!customerId) return null;
  return [...orders.value]
    .filter((order) => Number(order.customer_id) === customerId)
    .sort((left, right) => {
      const rightTime = Date.parse(right.created_at || "") || Number(right.id || 0);
      const leftTime = Date.parse(left.created_at || "") || Number(left.id || 0);
      return rightTime - leftTime;
    })[0] || null;
});

const latestSelectedOrderItem = computed(() => (
  latestSelectedOrder.value?.items?.[0] || null
));

const unreadConversationCount = computed(() => (
  conversations.value.filter((item) => Number(item.unread_count || 0) > 0).length
));

const importantConversationCount = computed(() => (
  conversations.value.filter((item) => conversationPriorityIds.value.has(item.conversation_id)).length
));

const salesOrderProgress = [
  { value: "draft", label: "Tạo đơn" },
  { value: "confirmed", label: "Xác nhận" },
  { value: "processing", label: "Đóng gói" },
  { value: "shipped", label: "Đang giao" },
  { value: "completed", label: "Hoàn thành" },
];

function salesOrderProgressIndex(order) {
  const status = String(order?.status || "draft");
  const indices = { draft: 0, confirmed: 1, processing: 2, shipped: 3, delivered: 4, completed: 4 };
  return indices[status] ?? -1;
}

function salesOrderStatusLabel(status) {
  const labels = {
    draft: "Mới tạo",
    confirmed: "Đã xác nhận",
    processing: "Đang đóng gói",
    shipped: "Đang giao",
    delivered: "Đã giao",
    completed: "Hoàn thành",
    refunded: "Đã hoàn tiền",
    cancelled: "Đã hủy",
  };
  return labels[status] || status || "Chưa rõ";
}

function leadStageLabel(stage) {
  const labels = {
    new: "Mới",
    qualified: "Đã xác định nhu cầu",
    proposal: "Đã gửi đề xuất",
    won: "Đã chốt",
    lost: "Không thành công",
  };
  return labels[stage] || stage || "Chưa rõ";
}

function ticketStatusLabel(status) {
  const labels = {
    open: "Đang mở",
    pending: "Đang chờ",
    resolved: "Đã xử lý",
    closed: "Đã đóng",
  };
  return labels[status] || status || "Chưa rõ";
}

function ticketPriorityLabel(priority) {
  const labels = { low: "Thấp", normal: "Bình thường", high: "Cao", urgent: "Khẩn cấp" };
  return labels[priority] || priority || "Bình thường";
}

function purchaseStatusLabel(status) {
  const labels = {
    draft: "Bản nháp",
    submitted: "Đã gửi",
    partially_received: "Đã nhận một phần",
    received: "Đã nhận đủ",
    closed: "Đã hoàn tất",
    cancelled: "Đã hủy",
  };
  return labels[status] || status || "Chưa rõ";
}

function paymentStatusLabel(status) {
  const labels = { unpaid: "Chưa thanh toán", partially_paid: "Thanh toán một phần", paid: "Đã thanh toán", refunded: "Đã hoàn tiền" };
  return labels[status] || status || "Chưa rõ";
}

function shippingStatusLabel(status) {
  const labels = {
    pending: "Chưa bàn giao",
    in_transit: "Đang vận chuyển",
    delivered: "Đã giao",
    failed: "Giao thất bại",
    returned: "Đã hoàn",
  };
  return labels[status] || status || "Chưa rõ";
}

function modelStatusLabel(status) {
  const labels = { draft: "Bản nháp", training: "Đang huấn luyện", ready: "Sẵn sàng", failed: "Lỗi" };
  return labels[status] || status || "Chưa rõ";
}

function experimentStatusLabel(status) {
  const labels = { draft: "Bản nháp", running: "Đang chạy", paused: "Tạm dừng", completed: "Đã hoàn tất", archived: "Đã lưu trữ" };
  return labels[status] || status || "Chưa rõ";
}

function policyStatusLabel(status) {
  const labels = { active: "Đang dùng", paused: "Tạm dừng", archived: "Đã lưu trữ" };
  return labels[status] || status || "Chưa rõ";
}

function documentEmbeddingStatusLabel(status) {
  const labels = { pending: "Chờ xử lý", processing: "Đang xử lý", ready: "Sẵn sàng", completed: "Đã hoàn tất", failed: "Lỗi" };
  return labels[status] || status || "Chưa rõ";
}

function workflowEventLabel(event) {
  const labels = {
    "message.created": "Tin nhắn mới",
    "ticket.created": "Tạo phiếu hỗ trợ",
    "ticket.status_changed": "Phiếu đổi trạng thái",
    "lead.stage_changed": "Cơ hội đổi giai đoạn",
    "order.created": "Tạo đơn hàng",
  };
  return labels[event] || "Sự kiện mới";
}

function workflowActionLabel(action) {
  const labels = { create_ticket: "Tạo phiếu hỗ trợ", add_tag: "Gắn nhãn", assign_user: "Chuyển người hỗ trợ + gửi email" };
  return labels[action] || action || "Chưa rõ";
}

function workflowRunStatusLabel(status) {
  const labels = { queued: "Đang chờ", running: "Đang chạy", succeeded: "Đã hoàn tất", failed: "Lỗi", skipped: "Đã bỏ qua" };
  return labels[status] || status || "Chưa rõ";
}

function leadActivityTypeLabel(type) {
  const labels = { note: "Ghi chú", call: "Cuộc gọi", email: "Email", meeting: "Lịch hẹn", task: "Công việc" };
  return labels[type] || "Hoạt động";
}

function ticketHistoryEventLabel(type) {
  const labels = {
    created: "Tạo phiếu",
    status_changed: "Đổi trạng thái",
    assigned: "Phân công",
    comment_added: "Thêm ghi chú",
    priority_changed: "Đổi mức ưu tiên",
  };
  return labels[type] || "Cập nhật phiếu";
}

function resourceLabel(type) {
  const labels = {
    customer: "Khách hàng",
    customers: "Khách hàng",
    conversation: "Hội thoại",
    order: "Đơn bán",
    orders: "Đơn bán",
    ticket: "Phiếu hỗ trợ",
    tickets: "Phiếu hỗ trợ",
    workflow: "Quy trình",
    document: "Tài liệu",
    documents: "Tài liệu",
    team: "Nhân sự",
    report: "Báo cáo",
  };
  return labels[type] || "Mục dữ liệu";
}

function roleLabel(role) {
  const labels = {
    owner: "Chủ shop",
    admin: "Quản trị viên",
    shop_admin: "Quản trị viên",
    agent: "Nhân viên",
    business_agent: "Nhân viên",
    shop_agent: "Nhân viên",
    viewer: "Chỉ xem",
  };
  return labels[role] || role || "Chưa rõ";
}

function usageResourceLabel(resource) {
  const labels = {
    messages: "Tin nhắn",
    conversations: "Hội thoại",
    orders: "Đơn hàng",
    staff_users: "Nhân viên",
    connected_channels: "Kênh kết nối",
    ai_calls: "Lượt trợ lý",
    ai_tokens: "Lượt xử lý trợ lý",
    ai_cost: "Chi phí trợ lý",
    rag_runs: "Lần tra cứu thông tin",
    rag_chunks: "Đoạn kiến thức",
    documents: "Tài liệu",
    storage_bytes: "Dung lượng lưu trữ",
  };
  return labels[resource] || resource || "Tài nguyên";
}

function schemaStateLabel(state) {
  const labels = { ready: "Sẵn sàng", disabled: "Đã tắt", pending: "Đang chờ", failed: "Lỗi" };
  return labels[state] || state || "Chưa rõ";
}

function openInboxOrderDetail(order) {
  if (!order?.id) return;
  currentTab.value = "orders";
  void fetchOrders();
  void loadSalesOrderEvents(order);
}

const activeOrderProducts = computed(() => (
  products.value.filter((product) => product.status === "active")
));

const orderFormTotal = computed(() => (
  (orderForm.value.items || []).reduce((total, item) => (
    total + orderItemLineTotal(item)
  ), 0)
));

function orderItemLineTotal(item) {
  const product = products.value.find(
    (candidate) => Number(candidate.id) === Number(item?.product_id),
  );
  return Number(product?.price || 0) * Math.max(0, Number(item?.quantity || 0));
}

function orderItemProducts(itemIndex) {
  const selectedElsewhere = new Set(
    (orderForm.value.items || [])
      .filter((_, index) => index !== itemIndex)
      .map((item) => Number(item.product_id))
      .filter(Number.isFinite),
  );
  const currentProductId = Number(orderForm.value.items?.[itemIndex]?.product_id);
  return products.value.filter((product) => (
    product.status === "active"
    && (!selectedElsewhere.has(Number(product.id)) || Number(product.id) === currentProductId)
  ));
}

function addOrderItem() {
  const chosenProductIds = new Set(
    (orderForm.value.items || [])
      .map((item) => Number(item.product_id))
      .filter(Number.isFinite),
  );
  const nextProduct = activeOrderProducts.value.find(
    (product) => !chosenProductIds.has(Number(product.id)),
  );
  if (!nextProduct) {
    orderError.value = "Không còn sản phẩm đang bán nào để thêm vào đơn.";
    return;
  }
  orderError.value = "";
  orderForm.value.items.push(createOrderItem(nextProduct.id));
}

function removeOrderItem(itemIndex) {
  if ((orderForm.value.items || []).length <= 1) {
    orderError.value = "Đơn bán phải có ít nhất một sản phẩm.";
    return;
  }
  orderError.value = "";
  orderForm.value.items.splice(itemIndex, 1);
}

function orderCustomerName(customerId) {
  const customer = orderCustomers.value.find(
    (candidate) => Number(candidate.id) === Number(customerId),
  );
  return customerOptionLabel(customer);
}

function orderCustomerPhone(customerId) {
  const customer = orderCustomers.value.find(
    (candidate) => Number(candidate.id) === Number(customerId),
  );
  return maskCustomerPhone(customer?.phone) || "Chưa có số điện thoại";
}

function customerOptionLabel(customer) {
  const name = maskCustomerName(customer?.name);
  if (name) return name;

  const email = maskCustomerEmail(customer?.email);
  if (email) return email;

  const phone = maskCustomerPhone(customer?.phone);
  return phone || customer?.channel || "Khách hàng";
}

function orderConversationLabel(conversation) {
  const preview = String(conversation?.last_message || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 44);
  const suffix = preview ? ` — ${preview}` : "";
  return `#${conversation.conversation_id} — ${channelLabel(conversation.channel)}${suffix}`;
}

function onOrderCustomerChange() {
  const conversationId = Number(orderForm.value.conversation_id);
  if (
    conversationId
    && !orderConversationOptions.value.some(
      (conversation) => Number(conversation.conversation_id) === conversationId,
    )
  ) {
    orderForm.value.conversation_id = "";
  }
}

const activeTeamUsers = computed(() =>
  teamUsers.value.filter((user) => user.is_active)
);

const filteredRuleSuggestions = computed(() => {
  if (ruleSuggestionFilter.value === "all") return ruleSuggestions.value;
  return ruleSuggestions.value.filter((suggestion) => suggestion.status === ruleSuggestionFilter.value);
});


const filtered = computed(() => {

  const keyword = search.value
    .trim()
    .toLowerCase();

  return conversations.value.filter(
    (item) => {

      const channelOk =
        activeFilter.value === "all"
        || item.channel === activeFilter.value;

      const tagOk = matchesCustomerTagFilter(
        item,
        tagFilters.value,
        tagFilterMode.value,
      );

      const quickFilterOk = inboxQuickFilter.value === "all"
        || (inboxQuickFilter.value === "unread" && Number(item.unread_count || 0) > 0)
        || (inboxQuickFilter.value === "important" && conversationPriorityIds.value.has(item.conversation_id));

      const segmentOk = !selectedSegmentId.value
        || segmentCustomerIds.value.has(Number(item.customer_id));

      const text = [
        item.customer_name,
        item.external_user_id,
        item.last_message,
        item.channel,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return (
        channelOk
        && quickFilterOk
        && tagOk
        && segmentOk
        &&
        (
          !keyword
          ||
          text.includes(keyword)
        )
      );

    }
  );

});

const inboxChannels = computed(() => getInboxChannels(conversations.value));

const reportCsvUrl = computed(() => {
  const params = new URLSearchParams();
  Object.entries(reportFilters.value).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.toString();
  return `${API_BASE}/reports/overview.csv${query ? `?${query}` : ""}`;
});


const inboundCount = computed(() => {

  return messages.value.filter(
    (message) =>
      message.direction === "inbound"
  ).length;

});


const outboundCount = computed(() => {

  return messages.value.filter(
    (message) =>
      message.direction === "outbound"
  ).length;

});


/* =========================================================
   HELPER FUNCTIONS
========================================================= */

function nameOf(item) {

  return (
    item?.customer_name
    ||
    item?.name
    ||
    item?.display_name
    ||
    `Khách #${item?.customer_id ?? item?.id ?? "?"}`
  );

}


function customerContactValue(kind) {

  const profile = customer360.value;
  if (profile?.[kind]) {
    return profile[kind];
  }
  return profile?.contacts?.find((contact) => contact.kind === kind)?.masked_value || "";

}


function initials(item) {

  return nameOf(item)
    .split(/\s+/)
    .slice(0, 2)
    .map(
      (word) =>
        word[0]?.toUpperCase() || ""
    )
    .join("");

}


function resolvedAvatarUrl(item) {

  const value = String(item?.avatar_url || "").trim();
  if (!value || failedAvatarUrls.value.has(value)) {
    return "";
  }

  try {
    const parsed = new URL(value, window.location.origin);
    if (/^\/api\/customers\/\d+\/avatar\/?$/.test(parsed.pathname)) {
      const apiOrigin = new URL(API_BASE, window.location.origin).origin;
      return `${apiOrigin}${parsed.pathname}${parsed.search}`;
    }
    return parsed.toString();
  } catch {
    return value;
  }

}


function markAvatarFailed(item) {

  const value = String(item?.avatar_url || "").trim();
  if (value) {
    failedAvatarUrls.value = new Set([
      ...failedAvatarUrls.value,
      value,
    ]);
  }

}


function formatTime(value) {

  if (!value) {
    return "";
  }

  const date = new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return "";
  }

  return new Intl.DateTimeFormat(
    "vi-VN",
    {
      hour: "2-digit",
      minute: "2-digit",
    }
  ).format(date);

}


/* =========================================================
   MESSAGE / MEDIA HELPERS
========================================================= */

function conversationPreview(item) {

  if (item?.last_message) {
    return item.last_message;
  }

  if (
    item?.last_media_type === "image"
  ) {
    return "📷 Hình ảnh";
  }

  if (
    item?.last_media_type === "video"
  ) {
    return "🎥 Video";
  }

  if (
    item?.last_media_type === "audio"
  ) {
    return "🎵 Âm thanh";
  }

  if (
    item?.last_media_type === "sticker"
  ) {
    return "🙂 Nhãn dán";
  }

  if (
    item?.last_media_url
  ) {
    return "📎 Tệp đính kèm";
  }

  return "Chưa có tin nhắn";

}


function mediaFallback(message) {

  if (
    message?.media_type === "image"
  ) {
    return "📷 Hình ảnh";
  }

  if (
    message?.media_type === "video"
  ) {
    return "🎥 Video";
  }

  if (
    message?.media_type === "audio"
  ) {
    return "🎵 Âm thanh";
  }

  if (
    message?.media_type === "sticker"
  ) {
    return "🙂 Nhãn dán";
  }

  if (
    message?.media_url
  ) {
    return "📎 Tệp đính kèm";
  }

  return "(Tin nhắn không có text)";

}


function normalizedMediaType(message) {

  return String(
    message?.media_type
    || message?.mediaType
    || ""
  )
    .trim()
    .toLowerCase();

}


function mediaUrl(message) {

  return String(
    resolveMediaUrl(
      message?.media_url
      || message?.mediaUrl
      || "",
      API_BASE,
    )
  ).trim();

}


function looksLikeImageUrl(url) {

  const value = String(
    url
    || ""
  )
    .trim()
    .toLowerCase();

  if (!value) {
    return false;
  }

  if (
    /\.(jpe?g|png|gif|webp|bmp)(\?|#|$)/.test(
      value
    )
  ) {
    return true;
  }

  return (
    value.includes(
      "/api/conversations/uploads/"
    )
    ||
    value.includes(
      "lookaside.fbsbx.com/ig_messaging_cdn"
    )
    ||
    (
      value.includes(
        "instagram."
      )
      &&
      value.includes(
        "fbcdn.net"
      )
    )
  );

}


function hasImage(message) {

  const type =
    normalizedMediaType(
      message
    );

  const url =
    mediaUrl(
      message
    );

  return Boolean(
    url
    &&
    (
      type === "image"
      ||
      type === "photo"
      ||
      (
        !type
        &&
        looksLikeImageUrl(
          url
        )
      )
    )
  );

}


function hasVideo(message) {

  const type =
    normalizedMediaType(
      message
    );

  return Boolean(
    mediaUrl(
      message
    )
    &&
    (
      type === "video"
      ||
      type === "reel"
    )
  );

}


function normalizeMessage(message) {

  const url =
    mediaUrl(
      message
    );

  let type =
    normalizedMediaType(
      message
    );

  if (
    url
    &&
    !type
    &&
    looksLikeImageUrl(
      url
    )
  ) {
    type = "image";
  }

  return {
    ...message,
    media_type:
      type
      || message?.media_type
      || null,
    media_url:
      url
      || message?.media_url
      || null,
    attachments: displayAttachments(message, API_BASE),
  };

}


function makeClientId() {

  return `client-${Date.now()}-${Math.random()
    .toString(16)
    .slice(2)}`;

}


function upsertMessage(message) {

  const normalized =
    normalizeMessage(
      message
    );

  const index =
    messages.value.findIndex(
      (item) =>
        (
          normalized.external_message_id
          &&
          item.external_message_id
          === normalized.external_message_id
        )
        ||
        (
          normalized.client_id
          &&
          item.client_id
          === normalized.client_id
        )
    );

  if (index >= 0) {
    messages.value[index] = {
      ...messages.value[index],
      ...normalized,
      status:
        normalized.status
        || "sent",
    };
  } else {
    messages.value.push(
      {
        ...normalized,
        status:
          normalized.status
          || "sent",
      }
    );
  }

}


function markOptimistic(
  clientId,
  status,
) {

  messages.value =
    messages.value.map(
      (message) =>
        message.client_id === clientId
          ? {
              ...message,
              status,
            }
          : message
    );

}


function handleRealtimeEvent(event) {

  if (
    event?.type !== "message_created"
    ||
    !event.message
  ) {
    return;
  }

  if (
    event.conversation_id
    === selectedId.value
  ) {
    upsertMessage(
      event.message
    );

    nextTick(
      scrollToBottom
    );
  }

  loadConversations(
    false
  );

}


function connectRealtime() {

  if (
    socket
    &&
    (
      socket.readyState === WebSocket.OPEN
      ||
      socket.readyState === WebSocket.CONNECTING
    )
  ) {
    return;
  }

  const wsUrl =
    API_BASE
      .replace(
        /^http/,
        "ws"
      )
      .replace(
        /\/api$/,
        ""
      )
    + "/ws/conversations";

  socket = new WebSocket(
    wsUrl
  );

  socket.onmessage = (event) => {
    try {
      handleRealtimeEvent(
        JSON.parse(
          event.data
        )
      );
    } catch (err) {
      console.error(err);
    }
  };

  socket.onclose = () => {
    reconnectTimer = setTimeout(
      connectRealtime,
      2000
    );
  };

  socket.onerror = () => {
    socket?.close();
  };

}


/* =========================================================
   IMAGE HELPERS
========================================================= */

function openImagePicker() {

  if (!selectedId.value) {

    error.value =
      "Hãy chọn một cuộc hội thoại trước.";

    return;
  }

  fileInput.value?.click();

}


const allowedMediaTypes = new Set([
  "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif",
  "audio/aac", "audio/flac", "audio/m4a", "audio/mp4", "audio/mpeg",
  "audio/ogg", "audio/opus", "audio/wav", "audio/webm", "application/ogg",
  "video/mp4", "video/mpeg", "video/quicktime", "video/webm",
  "application/pdf", "application/zip", "application/octet-stream",
  "application/msword", "application/rtf", "application/vnd.ms-excel",
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/x-7z-compressed", "application/x-rar-compressed",
  "text/csv", "text/plain",
]);

function detectMediaType(file) {
  const contentType = String(file?.type || "").toLowerCase();
  if (contentType.startsWith("audio/")) return "audio";
  if (contentType.startsWith("video/")) return "video";
  if (contentType === "image/webp" && /sticker/i.test(file?.name || "")) return "sticker";
  if (contentType.startsWith("image/")) return "image";
  return "file";
}

function revokeMediaPreview(preview) {
  if (preview?.startsWith("blob:")) {
    URL.revokeObjectURL(preview);
  }
}

function queueMediaFile(file, options = {}) {
  if (!file) return;

  const preview = options.preview || URL.createObjectURL(file);
  pendingMedia.value = [
    ...pendingMedia.value,
    {
      id: options.id || `media-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      file,
      preview,
      mediaType: options.mediaType || detectMediaType(file),
    },
  ];
}

function clearImage() {
  pendingMedia.value.forEach((media) => revokeMediaPreview(media.preview));
  pendingMedia.value = [];

  if (fileInput.value) {
    fileInput.value.value = "";
  }
}

function removePendingMedia(mediaId) {
  const media = pendingMedia.value.find((item) => item.id === mediaId);
  if (!media) return;

  revokeMediaPreview(media.preview);
  pendingMedia.value = pendingMedia.value.filter((item) => item.id !== mediaId);
}

function setImageFile(file) {
  if (!file) return;

  const contentType = String(file.type || "").toLowerCase();
  if (!allowedMediaTypes.has(contentType)) {
    error.value = "Định dạng chưa hỗ trợ. Chọn ảnh, âm thanh, video hoặc tệp phổ biến.";
    return;
  }

  const maxSize = 25 * 1024 * 1024;
  if (file.size > maxSize) {
    error.value = "File quá lớn. Tối đa 25MB.";
    return;
  }

  queueMediaFile(file);
  error.value = "";
}

function handleFileChange(event) {
  const files = Array.from(event.target.files || []);
  files.forEach((file) => setImageFile(file));
  event.target.value = "";
}


/* =========================================================
   VOICE RECORDER
========================================================= */

function formatVoiceRecordingTime(seconds) {
  const totalSeconds = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const remainder = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function supportedVoiceMimeType() {
  if (typeof window === "undefined" || typeof window.MediaRecorder === "undefined") {
    return "";
  }
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  return candidates.find((type) => (
    typeof window.MediaRecorder.isTypeSupported !== "function"
      || window.MediaRecorder.isTypeSupported(type)
  )) || "";
}

function clearVoiceRecordingTimer() {
  if (voiceRecordingTimer) {
    clearInterval(voiceRecordingTimer);
    voiceRecordingTimer = null;
  }
}

function stopVoiceRecordingStream() {
  voiceRecorderStream?.getTracks?.().forEach((track) => track.stop());
  voiceRecorderStream = null;
}

function resetVoiceRecordingState() {
  clearVoiceRecordingTimer();
  voiceRecorder = null;
  voiceRecorderChunks = [];
  voiceRecordingDiscarded = false;
  voiceRecording.value = false;
  voiceRecordingSeconds.value = 0;
}

function finishVoiceRecording() {
  const chunks = voiceRecorderChunks.slice();
  const mimeType = voiceRecorder?.mimeType || chunks[0]?.type || "audio/webm";
  const discarded = voiceRecordingDiscarded;
  stopVoiceRecordingStream();
  resetVoiceRecordingState();

  if (discarded || !chunks.length) return;

  const blob = new Blob(chunks, { type: mimeType });
  if (!blob.size) {
    error.value = "Không thu được âm thanh. Hãy thử lại.";
    return;
  }

  const extension = mimeType.includes("ogg")
    ? "ogg"
    : mimeType.includes("mp4")
      ? "m4a"
      : "webm";
  const file = new File([blob], `voice-${Date.now()}.${extension}`, {
    type: mimeType,
  });
  queueMediaFile(file, { mediaType: "audio" });
  error.value = "";
}

function discardVoiceRecording() {
  voiceRecordingDiscarded = true;
  const recorder = voiceRecorder;
  if (recorder && recorder.state !== "inactive") {
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.stop();
  }
  stopVoiceRecordingStream();
  resetVoiceRecordingState();
}

function stopVoiceRecording() {
  if (!voiceRecorder) return;
  if (voiceRecorder.state === "inactive") {
    finishVoiceRecording();
    return;
  }
  voiceRecorder.stop();
}

async function startVoiceRecording() {
  if (!selectedId.value || sending.value || composerMode.value === "internal") return;
  if (voiceRecording.value) return;

  if (
    typeof navigator === "undefined"
    || !navigator.mediaDevices?.getUserMedia
    || typeof window === "undefined"
    || typeof window.MediaRecorder === "undefined"
  ) {
      error.value = "Trình duyệt này chưa hỗ trợ ghi âm. Hãy cập nhật trình duyệt rồi thử lại.";
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = supportedVoiceMimeType();
    const recorder = mimeType
      ? new window.MediaRecorder(stream, { mimeType })
      : new window.MediaRecorder(stream);

    voiceRecorderStream = stream;
    voiceRecorder = recorder;
    voiceRecorderChunks = [];
    voiceRecordingDiscarded = false;
    recorder.ondataavailable = (event) => {
      if (event.data?.size) voiceRecorderChunks.push(event.data);
    };
    recorder.onerror = () => {
      stopVoiceRecordingStream();
      resetVoiceRecordingState();
      error.value = "Chưa thể ghi âm. Hãy kiểm tra quyền micrô rồi thử lại.";
    };
    recorder.onstop = finishVoiceRecording;
    recorder.start(250);
    voiceRecording.value = true;
    voiceRecordingSeconds.value = 0;
    error.value = "";
    voiceRecordingTimer = setInterval(() => {
      voiceRecordingSeconds.value += 1;
      if (voiceRecordingSeconds.value >= VOICE_RECORDING_MAX_SECONDS) {
        stopVoiceRecording();
      }
    }, 1000);
  } catch (err) {
    stopVoiceRecordingStream();
    resetVoiceRecordingState();
    const name = String(err?.name || "");
    error.value = name === "NotAllowedError" || name === "SecurityError"
      ? "Bạn chưa cấp quyền microphone cho CRM."
      : "Chưa thể mở micrô. Hãy kiểm tra thiết bị rồi thử lại.";
  }
}

function toggleVoiceRecording() {
  if (voiceRecording.value) {
    stopVoiceRecording();
  } else {
    startVoiceRecording();
  }
}


/* =========================================================
   CTRL + V IMAGE
========================================================= */

function handlePaste(event) {
  if (composerMode.value === "internal") return;

  const clipboardItems =
    event.clipboardData?.items
    || [];

  let pastedImage = false;
  for (const item of clipboardItems) {
    if (!item.type?.startsWith("image/")) continue;

    const file = item.getAsFile();
    if (!file) continue;

    setImageFile(file);
    pastedImage = true;
  }

  if (pastedImage) {
    event.preventDefault();
  }

}


/* =========================================================
   AUTO SCROLL
========================================================= */

async function scrollToBottom() {

  await nextTick();

  const element =
    document.querySelector(
      ".messages-scroll"
    );

  if (element) {

    element.scrollTop =
      element.scrollHeight;

  }

}


/* =========================================================
   API - LOAD CONVERSATIONS
========================================================= */

async function fetchTagCatalog() {
  try {
    const response = await apiFetch(`${API_BASE}/customers/tags/catalog`);
    if (!response.ok) return;
    const data = await response.json();
    tagCatalog.value = data.items || [];
  } catch (err) {
    console.error("Fetch tag catalog error:", err);
  }
}

async function fetchSavedSegments() {
  segmentLoading.value = true;
  segmentError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/segments`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    savedSegments.value = data.items || [];
  } catch (err) {
    segmentError.value = "Chưa tải được nhóm khách hàng đã lưu. Vui lòng thử lại sau.";
  } finally {
    segmentLoading.value = false;
  }
}

async function loadSegmentMembers() {
  if (!selectedSegmentId.value) {
    segmentCustomerIds.value = new Set();
    return;
  }
  try {
    const response = await apiFetch(`${API_BASE}/customers/segments/${selectedSegmentId.value}/customers?limit=500`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    segmentCustomerIds.value = new Set((data.items || []).map((item) => Number(item.id)));
  } catch (err) {
    segmentError.value = "Chưa tải được khách trong nhóm. Vui lòng thử lại sau.";
    segmentCustomerIds.value = new Set();
  }
}

async function createSavedSegment() {
  const form = segmentForm.value;
  if (!form.name.trim() || !form.tag_ids.length) {
    segmentError.value = "Nhóm khách hàng cần tên và ít nhất một nhãn.";
    return;
  }
  segmentSaving.value = true;
  segmentError.value = "";
  try {
    const editingId = segmentEditingId.value;
    const refreshSelectedMembers = editingId
      && String(selectedSegmentId.value) === String(editingId);
    const response = await apiFetch(
      editingId
        ? `${API_BASE}/customers/segments/${editingId}`
        : `${API_BASE}/customers/segments`,
      {
        method: editingId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name.trim(),
          description: form.description.trim() || null,
          tag_ids: form.tag_ids.map(Number),
          match_mode: form.match_mode,
        }),
      },
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    segmentEditingId.value = "";
    segmentForm.value = { name: "", description: "", tag_ids: [], match_mode: "all" };
    await fetchSavedSegments();
    if (refreshSelectedMembers) await loadSegmentMembers();
  } catch (err) {
    segmentError.value = friendlyErrorMessage(err, "Chưa thể lưu nhóm khách hàng. Vui lòng thử lại sau.");
  } finally {
    segmentSaving.value = false;
  }
}

function toggleTagFilter(tagName) {
  const name = String(tagName || "").trim();
  if (!name) return;
  tagFilters.value = tagFilters.value.includes(name)
    ? tagFilters.value.filter((tag) => tag !== name)
    : [...tagFilters.value, name];
}

function clearInboxSearch() {
  search.value = "";
}

function editSavedSegment(segment) {
  if (!segment) return;
  segmentEditingId.value = String(segment.id);
  segmentForm.value = {
    name: segment.name || "",
    description: segment.description || "",
    tag_ids: (segment.tag_ids || []).map(Number),
    match_mode: segment.match_mode || "all",
  };
  segmentError.value = "";
}

function cancelSegmentEdit() {
  segmentEditingId.value = "";
  segmentForm.value = { name: "", description: "", tag_ids: [], match_mode: "all" };
  segmentError.value = "";
}

async function deleteSavedSegment(segment) {
  if (!(await requestConfirmation(`Xóa nhóm khách hàng “${segment.name}”?`, {
    title: "Xóa nhóm khách hàng",
    confirmLabel: "Xóa nhóm",
    tone: "danger",
  }))) return;
  try {
    const response = await apiFetch(`${API_BASE}/customers/segments/${segment.id}`, { method: "DELETE" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (String(selectedSegmentId.value) === String(segment.id)) {
      selectedSegmentId.value = "";
      segmentCustomerIds.value = new Set();
    }
    if (String(segmentEditingId.value) === String(segment.id)) cancelSegmentEdit();
    await fetchSavedSegments();
  } catch (err) {
    segmentError.value = "Chưa thể xóa nhóm khách hàng. Vui lòng thử lại sau.";
  }
}

async function reindexDocument(doc) {
  if (!doc?.id) return;
  try {
    const response = await apiFetch(`${API_BASE}/documents/${doc.id}/reindex`, { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchDocuments();
  } catch (err) {
    docUploadError.value = friendlyErrorMessage(err, "Chưa thể cập nhật tài liệu. Vui lòng thử lại sau.");
  }
}

function timelineLabel(event) {
  const labels = {
    message: "Tin nhắn",
    identity: "Danh tính đa kênh",
    fact: "Thông tin khách hàng",
    note: "Ghi chú",
    lead: "Cơ hội bán hàng",
    sales_order: "Đơn bán",
    order_payment: "Thanh toán đơn",
    purchase_order: "Đơn nhập",
    ticket: "Phiếu hỗ trợ",
    ticket_event: "Lịch sử phiếu hỗ trợ",
    ticket_comment: "Ghi chú phiếu hỗ trợ",
    assignment: "Phân công",
    customer_merge: "Gộp hồ sơ",
    customer_merge_undo: "Hoàn tác gộp hồ sơ",
    customer_profile: "Thay đổi hồ sơ",
    customer_tag: "Thay đổi nhãn",
    ai_tool: "Trợ lý dùng dữ liệu",
    ai_handoff: "Trợ lý chuyển nhân viên",
  };
  return labels[event?.event_type] || channelLabel(event?.channel) || "Sự kiện CRM";
}

function orderEventLabel(event) {
  const labels = {
    status_changed: "Đổi trạng thái đơn",
    payment_created: "Ghi nhận thanh toán",
    refund_created: "Hoàn tiền",
    order_created: "Tạo đơn hàng",
    logistics_updated: "Cập nhật vận chuyển",
  };
  return labels[event?.event_type] || "Sự kiện đơn hàng";
}

function orderEventSummary(event) {
  if (event?.event_type === "status_changed") {
    return `${event.from_status || "—"} → ${event.to_status || "—"}`;
  }
  if (event?.event_type === "order_created") {
    return "Khởi tạo đơn ở trạng thái draft";
  }
  if (event?.event_type === "logistics_updated") {
    const metadata = event?.metadata || event?.metadata_ || {};
    const provider = metadata.shipping_provider || "Chưa có đơn vị vận chuyển";
    const status = metadata.shipping_status || "pending";
    return `${provider} · ${status}`;
  }
  const metadata = event?.metadata || event?.metadata_ || {};
  const amount = Number(metadata.amount || 0);
  if (amount > 0) return `${amount.toLocaleString("vi-VN")}đ`;
  return "Không có chi tiết";
}

function chronologicalOrderEvents(events) {
  return [...(events || [])].sort((left, right) => {
    const leftTime = Date.parse(left?.created_at || "") || 0;
    const rightTime = Date.parse(right?.created_at || "") || 0;
    return leftTime - rightTime || Number(left?.id || 0) - Number(right?.id || 0);
  });
}

async function loadConversations(
  showLoading = true
) {

  if (showLoading) {
    loading.value = true;
  }

  try {

    error.value = "";

    const response = await apiFetch(
      `${API_BASE}/conversations`
    );


    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw apiResponseError(
        response,
        data,
        `HTTP ${response.status}`,
      );
    }


    conversations.value =
      Array.isArray(data)
        ? data
        : data.items || [];


  } catch (err) {

    console.error(err);

    if (showLoading) {
      const status = Number(err?.status);
      if (status === 401) {
        error.value = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để xem hội thoại.";
      } else if (status === 403) {
        error.value = "Tài khoản hiện tại không có quyền xem hội thoại của shop này.";
      } else if (status === 423) {
        error.value = "Shop đang được chuẩn bị. Bấm Thử lại sau ít giây.";
      } else if (status === 429) {
        error.value = "Hệ thống đang bận vì có quá nhiều yêu cầu. Bấm Thử lại sau ít phút.";
      } else if ([502, 503, 504].includes(status)) {
        error.value = "Dữ liệu đang được chuẩn bị. Bấm Thử lại sau ít giây.";
      } else {
        error.value = "Chưa tải được danh sách hội thoại. Vui lòng thử lại hoặc đăng nhập lại.";
      }
    }


  } finally {

    if (showLoading) {
      loading.value = false;
    }

  }

}


/* =========================================================
   API - LOAD MESSAGES
========================================================= */

async function loadMessages(
  conversationId,
  showLoading = true,
  autoScroll = true
) {

  if (!conversationId) {
    return;
  }


  if (showLoading) {
    loading.value = true;
  }


  try {

    if (showLoading) {
      error.value = "";
    }


    const response = await apiFetch(
      `${API_BASE}/conversations/${conversationId}/messages`
    );


    if (!response.ok) {

      throw new Error(
        `HTTP ${response.status}`
      );

    }


    const data =
      await response.json();


    const rawMessages =
      Array.isArray(data)
        ? data
        : data.items || [];


    const newMessages =
      rawMessages.map(
        normalizeMessage
      );


    const oldSignature =
      messages.value
        .map(
          (message) =>
            [
              message.message_id,
              message.content,
              message.direction,
              message.media_type,
              message.media_url,
            ].join(":")
        )
        .join("|");


    const newSignature =
      newMessages
        .map(
          (message) =>
            [
              message.message_id,
              message.content,
              message.direction,
              message.media_type,
              message.media_url,
            ].join(":")
        )
        .join("|");


    if (
      oldSignature !==
      newSignature
    ) {

      messages.value =
        newMessages;


      if (autoScroll) {

        await scrollToBottom();

      }

    }


  } catch (err) {

    console.error(err);


    if (showLoading) {

      error.value =
        "Chưa tải được tin nhắn. Vui lòng thử lại sau.";

    }


  } finally {

    if (showLoading) {
      loading.value = false;
    }

  }

}


async function markConversationRead(conversationId) {
  if (!conversationId) return;
  try {
    const response = await apiFetch(
      `${API_BASE}/conversations/${conversationId}/mark-read`,
      { method: "POST" },
    );
    if (!response.ok) return;
    conversations.value = conversations.value.map((conversation) => (
      conversation.conversation_id === conversationId
        ? { ...conversation, unread_count: 0 }
        : conversation
    ));
  } catch (err) {
    // Reading a conversation must never prevent the operator from viewing it.
    console.warn("Không thể đánh dấu hội thoại đã đọc.", err);
  }
}


function attachmentMediaType(attachment) {
  return String(
    attachment?.media_type
    || attachment?.mediaType
    || "file"
  ).trim().toLowerCase();
}


function attachmentUrl(attachment) {
  return String(
    resolveMediaUrl(
      attachment?.media_url
      || attachment?.url
      || attachment?.source_url
      || "",
      API_BASE,
    )
  ).trim();
}


function messageAttachments(message) {
  return displayAttachments(message, API_BASE);
}


function isAudioAttachment(attachment) {
  return attachmentMediaType(attachment) === "audio";
}


function isImageAttachment(attachment) {
  return ["image", "photo", "sticker"].includes(attachmentMediaType(attachment));
}


function isVideoAttachment(attachment) {
  return ["video", "reel"].includes(attachmentMediaType(attachment));
}


function formatFactValue(value) {

  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }

  return String(value);

}


/* PRODUCT CATALOG METHODS */
async function fetchProducts() {
  productsLoading.value = true;
  productError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/products`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    products.value = data.items || [];
    const drafts = { ...productAdjustmentDrafts.value };
    for (const product of products.value) {
      if (!drafts[product.id]) drafts[product.id] = { quantity: 1, direction: 1, reason: "" };
    }
    productAdjustmentDrafts.value = drafts;
  } catch (err) {
    console.error("Fetch products error:", err);
    productError.value = "Chưa tải được danh sách sản phẩm. Vui lòng thử lại sau.";
  } finally {
    productsLoading.value = false;
  }
}

function openProductFilePicker() {
  productFileInput.value?.click();
}

function handleProductFileSelect(event) {
  const file = event.target.files?.[0];
  if (file) uploadProductFile(file);
}

function handleProductDrop(event) {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file) uploadProductFile(file);
}

async function uploadProductFile(file) {
  if (!file || productUploading.value) return;
  productUploading.value = true;
  productError.value = "";
  productUploadNotice.value = "";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(`${API_BASE}/products/import`, {
      method: "POST",
      body: formData,
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    const imported = Number(detail.imported || 0);
    const updated = Number(detail.updated || 0);
    const skipped = Number(detail.skipped || 0);
    productUploadNotice.value = `Đã nhập ${imported} sản phẩm${updated ? `, cập nhật ${updated}` : ""}${skipped ? `, bỏ qua ${skipped} dòng` : ""}.`;
    if (Array.isArray(detail.errors) && detail.errors.length) {
      productUploadNotice.value += ` ${detail.errors.slice(0, 2).join(" ")}`;
    }
    await fetchProducts();
  } catch (error) {
    productError.value = friendlyErrorMessage(error, "Chưa thể nhập danh mục sản phẩm. Vui lòng kiểm tra tệp rồi thử lại.");
  } finally {
    productUploading.value = false;
    if (productFileInput.value) productFileInput.value.value = "";
  }
}

function resetProductForm() {
  productForm.value = {
    id: null,
    sku: "",
    name: "",
    description: "",
    price: 0,
    stock_quantity: 0,
    status: "active",
  };
}

function editProduct(product) {
  productForm.value = {
    id: product.id,
    sku: product.sku || "",
    name: product.name || "",
    description: product.description || "",
    price: Number(product.price || 0),
    stock_quantity: Number(product.stock_quantity || 0),
    status: product.status || "active",
  };
}

async function saveProduct() {
  const form = productForm.value;
  if (!form.sku.trim() || !form.name.trim()) {
    productError.value = "SKU và tên sản phẩm là bắt buộc.";
    return;
  }
  productSaving.value = true;
  productError.value = "";
  try {
    const isEdit = Boolean(form.id);
    const existingProduct = isEdit ? products.value.find((product) => product.id === form.id) : null;
    const stockAdjustment = isEdit
      ? Number(form.stock_quantity || 0) - Number(existingProduct?.stock_quantity || 0)
      : 0;
    const payload = {
      sku: form.sku.trim(),
      name: form.name.trim(),
      description: form.description.trim() || null,
      price: Number(form.price || 0),
      status: form.status,
    };
    if (!isEdit) payload.stock_quantity = Number(form.stock_quantity || 0);
    const response = await apiFetch(
      isEdit ? `${API_BASE}/products/${form.id}` : `${API_BASE}/products`,
      {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    if (isEdit && stockAdjustment !== 0) {
      const adjustmentResponse = await apiFetch(`${API_BASE}/inventory/products/${form.id}/adjustments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quantity: stockAdjustment,
          note: "Điều chỉnh tồn kho từ danh mục sản phẩm",
        }),
      });
      if (!adjustmentResponse.ok) {
        const detail = await adjustmentResponse.json().catch(() => ({}));
        throw new Error(detail.detail || "Chưa thể điều chỉnh tồn kho. Vui lòng thử lại sau.");
      }
    }
    resetProductForm();
    await fetchProducts();
  } catch (err) {
    productError.value = friendlyErrorMessage(err, "Chưa thể lưu sản phẩm. Vui lòng thử lại sau.");
  } finally {
    productSaving.value = false;
  }
}

async function archiveProduct(product) {
  if (!(await requestConfirmation(`Lưu trữ sản phẩm ${product.name}?`, {
    title: "Lưu trữ sản phẩm",
    confirmLabel: "Lưu trữ",
    tone: "danger",
  }))) return;
  try {
    const response = await apiFetch(`${API_BASE}/products/${product.id}`, { method: "DELETE" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await fetchProducts();
  } catch (err) {
    productError.value = "Chưa thể lưu trữ sản phẩm. Vui lòng thử lại sau.";
  }
}

async function fetchOrders() {
  ordersLoading.value = true;
  orderError.value = "";
  try {
    const [ordersResponse, revenueResponse] = await Promise.all([
      apiFetch(`${API_BASE}/orders`),
      apiFetch(`${API_BASE}/reports/revenue-by-channel`),
    ]);
    if (!ordersResponse.ok) throw new Error(`HTTP ${ordersResponse.status}`);
    const orderData = await ordersResponse.json();
    orders.value = orderData.items || [];
    if (revenueResponse.ok) {
      const revenueData = await revenueResponse.json();
      revenueByChannel.value = revenueData.items || [];
    }
  } catch (err) {
    console.error("Fetch orders error:", err);
    orderError.value = "Chưa tải được danh sách đơn bán. Vui lòng thử lại sau.";
  } finally {
    ordersLoading.value = false;
  }
}

async function adjustProductInventory(product) {
  const draft = productAdjustmentDrafts.value[product.id] || {};
  const quantity = Math.abs(Number(draft.quantity || 0)) * (Number(draft.direction || 1) < 0 ? -1 : 1);
  const reason = String(draft.reason || "").trim();
  if (!Number.isFinite(quantity) || quantity === 0) {
    productError.value = "Nhập số lượng điều chỉnh khác 0.";
    return;
  }
  if (!reason) {
    productError.value = "Cần ghi lý do điều chỉnh tồn kho để lưu vào sổ điều chỉnh.";
    return;
  }
  productAdjustmentSaving.value = { ...productAdjustmentSaving.value, [product.id]: true };
  productError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/inventory/products/${product.id}/adjustments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity, reason }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    productAdjustmentDrafts.value = {
      ...productAdjustmentDrafts.value,
      [product.id]: { quantity: 1, direction: 1, reason: "" },
    };
    closeInventoryAdjustment();
    await fetchProducts();
  } catch (err) {
    productError.value = friendlyErrorMessage(err, "Chưa thể điều chỉnh tồn kho. Vui lòng thử lại sau.");
  } finally {
    const nextSaving = { ...productAdjustmentSaving.value };
    delete nextSaving[product.id];
    productAdjustmentSaving.value = nextSaving;
  }
}

function openInventoryAdjustment(product, direction = 1) {
  if (!product?.id) return;
  const existing = productAdjustmentDrafts.value[product.id] || { quantity: 1, reason: "" };
  productAdjustmentDrafts.value = {
    ...productAdjustmentDrafts.value,
    [product.id]: {
      ...existing,
      quantity: Math.max(1, Math.abs(Number(existing.quantity || 1))),
      direction: direction < 0 ? -1 : 1,
    },
  };
  inventoryAdjustmentOpen.value = product.id;
}

function closeInventoryAdjustment() {
  inventoryAdjustmentOpen.value = null;
}

function inventoryAdjustmentSignedQuantity(product) {
  const draft = productAdjustmentDrafts.value[product?.id] || {};
  const amount = Math.abs(Number(draft.quantity || 0));
  return amount * (Number(draft.direction || 1) < 0 ? -1 : 1);
}

function inventoryAdjustmentPreview(product) {
  return Math.max(0, Number(product?.stock_quantity || 0) + inventoryAdjustmentSignedQuantity(product));
}

async function transitionSalesOrder(order, toStatus) {
  if (!order || !toStatus || order.status === toStatus) return;
  const orderId = Number(order.id);
  if (orderTransitionSaving.value[orderId]) return;
  orderError.value = "";
  orderTransitionSaving.value = { ...orderTransitionSaving.value, [orderId]: true };
  try {
    const response = await apiFetch(`${API_BASE}/orders/${order.id}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_status: toStatus }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await Promise.all([fetchOrders(), fetchProducts()]);
  } catch (err) {
    orderError.value = friendlyErrorMessage(err, "Chưa thể cập nhật đơn bán. Vui lòng thử lại sau.");
    await fetchOrders();
  } finally {
    const nextSaving = { ...orderTransitionSaving.value };
    delete nextSaving[orderId];
    orderTransitionSaving.value = nextSaving;
  }
}

function availableProductQuantity(productId) {
  const product = products.value.find((item) => Number(item.id) === Number(productId));
  if (!product) return 0;
  return Number(product.stock_quantity || 0) - Number(product.reserved_quantity || 0);
}

function orderCanConfirm(order) {
  return Boolean(order?.items?.length) && order.items.every((item) => availableProductQuantity(item.product_id) >= Number(item.quantity || 0));
}

async function loadSalesOrderEvents(order) {
  if (!order?.id) return;
  orderEventsLoading.value = true;
  orderLogisticsDraft.value = {
    shipping_provider: String(order.shipping_provider || ""),
    tracking_code: String(order.tracking_code || ""),
    shipping_status: String(order.shipping_status || "pending"),
  };
  selectedOrderEvents.value = { order, items: [] };
  await nextTick();
  document.querySelector('[data-testid="order-events-panel"]')?.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
  try {
    const response = await apiFetch(`${API_BASE}/orders/${order.id}/events`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    selectedOrderEvents.value = { order, ...(await response.json()) };
    await nextTick();
    document.querySelector('[data-testid="order-events-panel"]')?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  } catch (err) {
    orderError.value = "Chưa tải được lịch sử đơn bán. Vui lòng thử lại sau.";
  } finally {
    orderEventsLoading.value = false;
  }
}

async function recordSalesPayment(order, kind = "payment") {
  const amount = Number(orderPaymentDrafts.value[order.id] || 0);
  if (!Number.isFinite(amount) || amount <= 0) {
    orderError.value = "Nhập số tiền thanh toán hợp lệ trước.";
    return;
  }
  orderPaymentSaving.value = { ...orderPaymentSaving.value, [order.id]: true };
  orderError.value = "";
  try {
    const isRefund = kind === "refund";
    const payload = isRefund
      ? { idempotency_key: `ui-refund-${order.id}-${Date.now()}`, amount, reason: "Thao tác từ CRM" }
      : { idempotency_key: `ui-payment-${order.id}-${Date.now()}`, amount, method: "manual", status: "paid" };
    const response = await apiFetch(`${API_BASE}/orders/${order.id}/${isRefund ? "refunds" : "payments"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    orderPaymentDrafts.value = { ...orderPaymentDrafts.value, [order.id]: "" };
    await fetchOrders();
  } catch (err) {
    orderError.value = friendlyErrorMessage(err, kind === "refund" ? "Chưa thể hoàn tiền. Vui lòng thử lại sau." : "Chưa thể ghi nhận thanh toán. Vui lòng thử lại sau.");
  } finally {
    orderPaymentSaving.value = { ...orderPaymentSaving.value, [order.id]: false };
  }
}

async function fetchPurchaseOrders() {
  purchaseOrdersLoading.value = true;
  purchaseOrderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/purchase-orders`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    purchaseOrders.value = (await response.json()).items || [];
    const receiptDrafts = { ...purchaseReceiptDrafts.value };
    for (const purchase of purchaseOrders.value) {
      for (const item of purchase.items || []) {
        const remaining = Math.max(0, Number(item.quantity || 0) - Number(item.received_quantity || 0));
        if (receiptDrafts[item.id] === undefined || Number(receiptDrafts[item.id]) > remaining) {
          receiptDrafts[item.id] = remaining;
        }
      }
    }
    purchaseReceiptDrafts.value = receiptDrafts;
  } catch (err) {
    purchaseOrderError.value = "Chưa tải được đơn nhập hàng. Vui lòng thử lại sau.";
  } finally {
    purchaseOrdersLoading.value = false;
  }
}

function resetPurchaseOrderForm() {
  purchaseOrderForm.value = {
    po_number: `PO-${Date.now()}`,
    supplier_id: suppliers.value[0]?.id ? String(suppliers.value[0].id) : "",
    supplier_name: "",
    product_id: products.value[0]?.id || "",
    quantity: 1,
    unit_cost: Number(products.value[0]?.price || 0),
    notes: "",
  };
}

async function savePurchaseOrder() {
  const form = purchaseOrderForm.value;
  const supplierId = Number(form.supplier_id || 0) || null;
  const supplierName = form.supplier_name.trim();
  if (!form.po_number.trim() || (!supplierId && !supplierName) || !form.product_id || Number(form.quantity) < 1) {
    purchaseOrderError.value = "Mã PO, nhà cung cấp, sản phẩm và số lượng là bắt buộc.";
    return;
  }
  purchaseOrderSaving.value = true;
  purchaseOrderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/purchase-orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        po_number: form.po_number.trim(),
        ...(supplierId ? { supplier_id: supplierId } : { supplier_name: supplierName }),
        notes: form.notes.trim() || null,
        items: [{ product_id: Number(form.product_id), quantity: Number(form.quantity), unit_cost: Number(form.unit_cost || 0) }],
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetPurchaseOrderForm();
    await fetchPurchaseOrders();
  } catch (err) {
    purchaseOrderError.value = friendlyErrorMessage(err, "Chưa thể tạo đơn nhập hàng. Vui lòng thử lại sau.");
  } finally {
    purchaseOrderSaving.value = false;
  }
}

async function loadPurchaseOrderEvents(purchase) {
  if (!purchase?.id) return;
  purchaseOrderEventsLoading.value = true;
  selectedPurchaseOrderEvents.value = { purchase, items: [] };
  await nextTick();
  document.querySelector('[data-testid="purchase-order-events-panel"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await apiFetch(`${API_BASE}/purchase-orders/${purchase.id}/events`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    selectedPurchaseOrderEvents.value = { purchase, ...(await response.json()) };
    await nextTick();
    document.querySelector('[data-testid="purchase-order-events-panel"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    purchaseOrderError.value = "Chưa tải được lịch sử đơn nhập. Vui lòng thử lại sau.";
  } finally {
    purchaseOrderEventsLoading.value = false;
  }
}

function purchaseOrderEventLabel(event) {
  const labels = {
    status_changed: "Cập nhật trạng thái",
    receipt_created: "Nhận hàng",
    payment_created: "Thanh toán nhà cung cấp",
    refund_created: "Hoàn tiền nhà cung cấp",
  };
  return labels[event?.event_type] || "Cập nhật phiếu nhập";
}

function purchaseOrderEventSummary(event) {
  const metadata = event?.metadata || {};
  if (event?.event_type === "status_changed") return `${metadata.from_status || "—"} → ${metadata.to_status || "—"}`;
  if (metadata.amount !== undefined) return `${Number(metadata.amount).toLocaleString("vi-VN")}đ`;
  if (metadata.received_quantity !== undefined) return `Đã nhận ${metadata.received_quantity}`;
  return metadata.note || "Có thay đổi được ghi nhận.";
}

async function transitionPurchaseOrder(order, toStatus) {
  if (!toStatus || order.status === toStatus) return;
  try {
    const response = await apiFetch(`${API_BASE}/purchase-orders/${order.id}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_status: toStatus }),
    });
    if (!response.ok) throw new Error(await response.text());
    await fetchPurchaseOrders();
  } catch (err) {
    purchaseOrderError.value = "Chưa thể chuyển trạng thái đơn nhập. Vui lòng thử lại sau.";
    await fetchPurchaseOrders();
  }
}

async function fetchSuppliers() {
  suppliersLoading.value = true;
  try {
    const response = await apiFetch(`${API_BASE}/suppliers?status=active`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    suppliers.value = (await response.json()).items || [];
    if (!purchaseOrderForm.value.supplier_id && suppliers.value.length) {
      purchaseOrderForm.value.supplier_id = String(suppliers.value[0].id);
      purchaseOrderForm.value.supplier_name = "";
    }
  } catch (err) {
    purchaseOrderError.value = "Chưa tải được danh sách nhà cung cấp. Vui lòng thử lại sau.";
  } finally {
    suppliersLoading.value = false;
  }
}

async function saveSupplier() {
  const code = supplierForm.value.code.trim();
  const name = supplierForm.value.name.trim();
  if (!code || !name) {
    purchaseOrderError.value = "Mã và tên nhà cung cấp là bắt buộc.";
    return;
  }
  supplierSaving.value = true;
  purchaseOrderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/suppliers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, name }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    supplierForm.value = { code: "", name: "" };
    await fetchSuppliers();
  } catch (err) {
    purchaseOrderError.value = friendlyErrorMessage(err, "Chưa thể tạo nhà cung cấp. Vui lòng thử lại sau.");
  } finally {
    supplierSaving.value = false;
  }
}

async function receivePurchaseOrder(order) {
  if (!order?.items?.length) return;
  const items = order.items
    .map((item) => {
      const remaining = Math.max(0, Number(item.quantity || 0) - Number(item.received_quantity || 0));
      const requested = Number(purchaseReceiptDrafts.value[item.id] ?? remaining);
      return {
        purchase_order_item_id: item.id,
        quantity: Math.min(remaining, requested),
      };
    })
    .filter((item) => item.quantity > 0);
  if (!items.length) {
    purchaseOrderError.value = "Đơn này đã nhận đủ hàng.";
    return;
  }
  purchaseOrderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/purchase-orders/${order.id}/receipts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `ui-receipt-${order.id}-${Date.now()}`, items, note: "Nhận hàng từ CRM" }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await Promise.all([fetchPurchaseOrders(), fetchProducts()]);
  } catch (err) {
    purchaseOrderError.value = friendlyErrorMessage(err, "Chưa thể ghi nhận nhập kho. Vui lòng thử lại sau.");
  }
}

async function recordPurchasePayment(order) {
  const amount = Number(purchasePaymentDrafts.value[order.id] || 0);
  if (!Number.isFinite(amount) || amount <= 0) {
    purchaseOrderError.value = "Nhập số tiền thanh toán nhà cung cấp hợp lệ.";
    return;
  }
  purchasePaymentSaving.value = { ...purchasePaymentSaving.value, [order.id]: true };
  purchaseOrderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/purchase-orders/${order.id}/payments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `ui-po-payment-${order.id}-${Date.now()}`, amount, method: "manual", status: "paid" }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    purchasePaymentDrafts.value = { ...purchasePaymentDrafts.value, [order.id]: "" };
    await fetchPurchaseOrders();
  } catch (err) {
    purchaseOrderError.value = friendlyErrorMessage(err, "Chưa thể ghi nhận thanh toán nhà cung cấp. Vui lòng thử lại sau.");
  } finally {
    purchasePaymentSaving.value = { ...purchasePaymentSaving.value, [order.id]: false };
  }
}

async function loadAuthSession() {
  if (!authToken.value) return;
  try {
    const response = await apiFetch(`${API_BASE}/auth/me`);
    if (response.ok) {
      authUser.value = await response.json();
      await fetchSecuritySettings();
      await fetchQuotaUsage();
    }
    else {
      clearAuthToken();
      authToken.value = "";
    }
  } catch {
    // Keep the legacy development header path available when auth is offline.
  }
}

function timelineExplainability(event) {
  const metadata = event?.metadata || {};
  if (event?.event_type === "ai_tool") {
    return metadata.tool ? `Cách xử lý: ${metadata.tool}` : "Đã ghi lại cách xử lý";
  }
  if (event?.event_type === "ai_handoff") {
    return metadata.reason ? `Lý do: ${metadata.reason}` : "Đã ghi lại lý do chuyển";
  }
  if (event?.event_type === "message" && timelineActor(event).kind === "bot") {
    const route = metadata.route ? `Nguồn xử lý: ${metadata.route}` : "";
    const documentIds = Array.isArray(metadata.rag_source_document_ids) ? metadata.rag_source_document_ids : [];
    const sources = documentIds.length ? `Tài liệu tham khảo: #${documentIds.join(", #")}` : "";
    return [route, sources].filter(Boolean).join(" · ");
  }
  return "";
}

function startAuthRateLimit(seconds) {
  const retryAfter = Math.max(1, Math.ceil(Number(seconds) || 60));
  authRateLimitSeconds.value = retryAfter;
  if (authRateLimitTimer) clearInterval(authRateLimitTimer);
  authRateLimitTimer = setInterval(() => {
    authRateLimitSeconds.value = Math.max(0, authRateLimitSeconds.value - 1);
    if (!authRateLimitSeconds.value && authRateLimitTimer) {
      clearInterval(authRateLimitTimer);
      authRateLimitTimer = null;
    }
  }, 1000);
}

function formatRateLimitDuration(seconds) {
  const totalSeconds = Math.max(0, Math.ceil(Number(seconds) || 0));
  if (totalSeconds >= 60) {
    const minutes = Math.floor(totalSeconds / 60);
    const remainingSeconds = totalSeconds % 60;
    return remainingSeconds
      ? `${minutes} phút ${remainingSeconds} giây`
      : `${minutes} phút`;
  }
  return `${totalSeconds} giây`;
}

async function fetchQuotaUsage() {
  quotaLoading.value = true;
  quotaError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/usage`);
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) return;
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    quotaSnapshot.value = detail;
  } catch (err) {
    quotaError.value = friendlyErrorMessage(err, "Chưa tải được hạn mức sử dụng. Vui lòng thử lại sau.");
  } finally {
    quotaLoading.value = false;
  }
}

async function login() {
  if (authRateLimitSeconds.value > 0) {
    authError.value = `Quá nhiều lần thử. Thử lại sau ${formatRateLimitDuration(authRateLimitSeconds.value)}.`;
    return;
  }
  authLoading.value = true;
  authError.value = "";
  try {
    const credentials = {
      email: loginForm.value.email,
      password: loginForm.value.password,
      ...(loginForm.value.shop_slug.trim() ? { shop_slug: loginForm.value.shop_slug.trim() } : {}),
    };
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      if (response.status === 429) {
        const retryAfter = Number(
          response.headers.get("Retry-After")
          || detail.retry_after
          || detail.detail?.retry_after
          || 60,
        );
        startAuthRateLimit(retryAfter);
        const message = typeof detail.detail === "string"
          ? detail.detail
          : detail.detail?.message || "Quá nhiều lần thử đăng nhập.";
        throw new Error(message);
      }
      const message = typeof detail.detail === "string"
        ? detail.detail
        : detail.detail?.message || "Đăng nhập thất bại.";
      throw new Error(message);
    }
    const data = await response.json();
    storeAuthToken(data.access_token);
    authToken.value = data.access_token;
    authUser.value = { ...data.user, mfa_required: Boolean(data.mfa_required) };
    loadBusinessProfile();
    loadThemePreference();
    mfaVerifyPending.value = Boolean(data.mfa_required);
    loginForm.value.password = "";
    loginForm.value.shop_slug = "";
    if (!mfaVerifyPending.value) {
      await fetchSecuritySettings();
      await fetchQuotaUsage();
    }
    await fetchPlatformAdmin();
  } catch (err) {
    authError.value = friendlyErrorMessage(err, "Chưa thể đăng nhập lúc này. Vui lòng thử lại sau.");
  } finally {
    authLoading.value = false;
  }
}

async function logout() {
  try { if (authToken.value) await apiFetch(`${API_BASE}/auth/logout`, { method: "POST" }); } catch { /* session may already be expired */ }
  clearAuthToken();
  authToken.value = "";
  authUser.value = null;
  serviceAccountSummary.value = null;
  serviceAccountError.value = "";
  authSessions.value = [];
  mfaProvisioningUri.value = "";
  mfaVerifyCode.value = "";
  mfaVerifyPending.value = false;
  privacyResult.value = null;
}

async function fetchSecuritySettings() {
  if (!authUser.value) {
    authSessions.value = [];
    return;
  }
  securityLoading.value = true;
  securityError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/auth/sessions`);
    if (response.ok) authSessions.value = await response.json();
    else if (response.status !== 403) throw new Error(`HTTP ${response.status}`);
  } catch (err) {
    securityError.value = friendlyErrorMessage(err, "Chưa tải được thông tin bảo mật. Vui lòng thử lại sau.");
  } finally {
    securityLoading.value = false;
  }
}

async function updateOrderLogistics(order) {
  if (!order?.id || orderLogisticsSaving.value) return;
  const draft = orderLogisticsDraft.value || {};
  const shippingProvider = String(draft.shipping_provider || "").trim();
  const trackingCode = String(draft.tracking_code || "").trim();
  const shippingStatus = String(draft.shipping_status || "pending").trim();
  if (!shippingProvider && !trackingCode && shippingStatus === "pending") {
    orderError.value = "Nhập đơn vị vận chuyển hoặc mã vận đơn trước.";
    return;
  }
  orderLogisticsSaving.value = true;
  orderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/orders/${order.id}/logistics`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        shipping_provider: shippingProvider || null,
        tracking_code: trackingCode || null,
        shipping_status: shippingStatus,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const updatedOrder = await response.json();
    orders.value = orders.value.map((item) => (
      Number(item.id) === Number(updatedOrder.id) ? { ...item, ...updatedOrder } : item
    ));
    if (selectedOrderEvents.value?.order?.id === order.id) {
      selectedOrderEvents.value = {
        ...selectedOrderEvents.value,
        order: { ...selectedOrderEvents.value.order, ...updatedOrder },
      };
    }
    orderLogisticsDraft.value = {
      shipping_provider: String(updatedOrder.shipping_provider || ""),
      tracking_code: String(updatedOrder.tracking_code || ""),
      shipping_status: String(updatedOrder.shipping_status || "pending"),
    };
    await loadSalesOrderEvents({ ...order, ...updatedOrder });
  } catch (err) {
    orderError.value = friendlyErrorMessage(err, "Chưa thể cập nhật thông tin giao hàng. Vui lòng thử lại sau.");
  } finally {
    orderLogisticsSaving.value = false;
  }
}

async function revokeAuthSession(session) {
  securityError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/auth/sessions/${session.id}/revoke`, { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    authSessions.value = authSessions.value.map((item) => (
      item.id === session.id ? { ...item, revoked_at: new Date().toISOString() } : item
    ));
  } catch (err) {
    securityError.value = friendlyErrorMessage(err, "Chưa thể đăng xuất phiên này. Vui lòng thử lại sau.");
  }
}

async function prepareMfaEnrollment() {
  securityError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/auth/mfa/prepare`, { method: "POST" });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    mfaProvisioningUri.value = detail.provisioning_uri || "";
    authUser.value = { ...authUser.value, mfa_status: detail.status || "prepared" };
    mfaVerifyPending.value = true;
  } catch (err) {
    securityError.value = friendlyErrorMessage(err, "Chưa thể chuẩn bị bước bảo mật bổ sung. Vui lòng thử lại sau.");
  }
}

async function verifyMfaEnrollment() {
  securityError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/auth/mfa/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: mfaVerifyCode.value }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail?.message || detail.detail || "Mã xác thực 2 bước không đúng.");
    }
    mfaVerifyCode.value = "";
    mfaVerifyPending.value = false;
    authUser.value = { ...authUser.value, mfa_status: "enabled", mfa_required: false };
    await fetchSecuritySettings();
  } catch (err) {
    securityError.value = friendlyErrorMessage(err, "Mã bảo mật chưa đúng hoặc đã hết hạn. Vui lòng thử lại.");
  }
}

async function disableMfaEnrollment() {
  if (!(await requestConfirmation("Tắt xác thực 2 bước cho tài khoản này?", { confirmLabel: "Tắt xác thực 2 bước" }))) return;
  securityError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/auth/mfa/disable`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    authUser.value = { ...authUser.value, mfa_status: "disabled" };
    mfaProvisioningUri.value = "";
  } catch (err) {
    securityError.value = friendlyErrorMessage(err, "Chưa thể tắt bước bảo mật bổ sung. Vui lòng thử lại sau.");
  }
}

async function runPrivacyAction(kind) {
  if (kind === "delete" && !(await requestConfirmation("Thao tác này sẽ ẩn danh dữ liệu khách hàng và giữ lại bản ghi cần thiết cho đối soát. Tiếp tục?", { confirmLabel: "Xác nhận xóa" }))) return;
  privacyLoading.value = true;
  securityError.value = "";
  privacyResult.value = null;
  try {
    const requestKey = `crm-ui-${kind}-${Date.now()}`;
    const body = { request_key: requestKey };
    if (kind === "delete") body.confirmation_token = "DELETE";
    const response = await apiFetch(`${API_BASE}/privacy/${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    privacyResult.value = detail;
  } catch (err) {
    securityError.value = friendlyErrorMessage(err, "Chưa thể xử lý yêu cầu dữ liệu. Vui lòng thử lại sau.");
  } finally {
    privacyLoading.value = false;
  }
}

async function fetchAuditLogs() {
  if (!authUser.value) return;
  auditLoading.value = true;
  try {
    const response = await apiFetch(`${API_BASE}/auth/audit-logs?limit=50`);
    if (response.ok) auditLogs.value = await response.json();
  } finally {
    auditLoading.value = false;
  }
}

async function fetchPlatformAdmin() {
  platformLoading.value = true;
  platformError.value = "";
  try {
    if (!authUser.value) {
      platformAdmin.value = false;
      platformShops.value = [];
      platformSchemas.value = [];
      platformAuditLogs.value = [];
      platformProviderErrors.value = [];
      return;
    }
    const shopsResponse = await apiFetch(`${API_BASE}/platform/shops`);
    if (!shopsResponse.ok) {
      platformAdmin.value = false;
      platformShops.value = [];
      platformSchemas.value = [];
      platformAuditLogs.value = [];
      platformProviderErrors.value = [];
      return;
    }
    const shopsPayload = await shopsResponse.json();
    platformAdmin.value = true;
    platformShops.value = shopsPayload.items || [];
    const schemasResponse = await apiFetch(`${API_BASE}/platform/tenant-schemas`);
    if (schemasResponse.ok) {
      platformSchemas.value = (await schemasResponse.json()).items || [];
    }
    const auditResponse = await apiFetch(`${API_BASE}/platform/audit-logs?limit=30`);
    if (auditResponse.ok) {
      platformAuditLogs.value = await auditResponse.json();
    } else {
      platformAuditLogs.value = [];
    }
    const providerResponse = await apiFetch(`${API_BASE}/platform/provider-errors?limit=30`);
    platformProviderErrors.value = providerResponse.ok ? await providerResponse.json() : [];
  } catch (err) {
    platformAdmin.value = false;
    platformAuditLogs.value = [];
    platformProviderErrors.value = [];
    platformError.value = friendlyErrorMessage(err, "Chưa tải được thông tin quản trị. Vui lòng thử lại sau.");
  } finally {
    platformLoading.value = false;
  }
}

async function togglePlatformShop(shop) {
  platformError.value = "";
  const status = shop.status === "suspended" ? "active" : "suspended";
  try {
    const response = await apiFetch(`${API_BASE}/platform/shops/${shop.id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const updated = await response.json();
    platformShops.value = platformShops.value.map((item) => (
      item.id === updated.id ? { ...item, status: updated.status } : item
    ));
  } catch (err) {
    platformError.value = friendlyErrorMessage(err, "Chưa thể cập nhật trạng thái shop. Vui lòng thử lại sau.");
  }
}

async function stagePlatformSchema(schema) {
  platformError.value = "";
  const businessId = schema.business_id;
  const state = schema.state === "ready" ? "disabled" : "ready";
  try {
    const response = await apiFetch(`${API_BASE}/platform/tenant-schemas/${businessId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state, feature_enabled: state === "ready" }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const updated = await response.json();
    platformSchemas.value = platformSchemas.value.map((item) => (
      item.business_id === updated.business_id ? updated : item
    ));
  } catch (err) {
    platformError.value = friendlyErrorMessage(err, "Chưa thể cập nhật cách tách dữ liệu. Vui lòng thử lại sau.");
  }
}

async function registerPlatformSchema(businessId) {
  platformError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/platform/tenant-schemas/${businessId}`, { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const created = await response.json();
    const existing = platformSchemas.value.some((item) => item.business_id === created.business_id);
    platformSchemas.value = existing
      ? platformSchemas.value.map((item) => item.business_id === created.business_id ? created : item)
      : [...platformSchemas.value, created];
  } catch (err) {
    platformError.value = friendlyErrorMessage(err, "Chưa thể đăng ký cách tách dữ liệu. Vui lòng thử lại sau.");
  }
}

async function fetchReports() {
  reportsLoading.value = true;
  reportsError.value = "";
  try {
    const params = new URLSearchParams();
    Object.entries(reportFilters.value).forEach(([key, value]) => { if (value) params.set(key, value); });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const attributionParams = new URLSearchParams(params);
    attributionParams.set("model", "last_touch");
    const attributionSuffix = `?${attributionParams.toString()}`;
    const [overviewResponse, performanceResponse, inventoryResponse, purchaseCostResponse, attributionResponse, pipelineResponse, ticketResponse, qualityResponse] = await Promise.all([
      apiFetch(`${API_BASE}/reports/overview${suffix}`),
      apiFetch(`${API_BASE}/reports/agent-performance`),
      apiFetch(`${API_BASE}/reports/inventory`),
      apiFetch(`${API_BASE}/reports/purchase-costs${suffix}`),
      apiFetch(`${API_BASE}/reports/revenue-attribution${attributionSuffix}`),
      apiFetch(`${API_BASE}/reports/pipeline${suffix}`),
      apiFetch(`${API_BASE}/reports/tickets${suffix}`),
      apiFetch(`${API_BASE}/reports/quality?days=30`),
    ]);
    if (!overviewResponse.ok) throw new Error(`HTTP ${overviewResponse.status}`);
    crmOverview.value = await overviewResponse.json();
    if (performanceResponse.ok) {
      agentPerformance.value = (await performanceResponse.json()).items || [];
    }
    if (inventoryResponse.ok) inventoryReport.value = await inventoryResponse.json();
    if (purchaseCostResponse.ok) purchaseCostReport.value = await purchaseCostResponse.json();
    if (attributionResponse.ok) revenueAttribution.value = await attributionResponse.json();
    if (pipelineResponse.ok) pipelineSummary.value = (await pipelineResponse.json()).items || [];
    if (ticketResponse.ok) ticketReport.value = await ticketResponse.json();
    if (qualityResponse.ok) qualityDashboard.value = await qualityResponse.json();
  } catch (err) {
    console.error("Fetch reports error:", err);
    reportsError.value = "Chưa tải được báo cáo. Vui lòng thử lại sau.";
  } finally {
    reportsLoading.value = false;
  }
}

async function downloadReportCsv() {
  if (reportCsvDownloading.value) return;
  reportCsvDownloading.value = true;
  reportCsvStatus.value = "";
  reportsError.value = "";
  let objectUrl = "";
  try {
    // A normal anchor cannot attach the tenant header or bearer token. Use
    // apiFetch so CSV export follows the same authentication boundary as the
    // report cards instead of opening a misleading 401/403 browser tab.
    const response = await apiFetch(reportCsvUrl.value);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const disposition = response.headers.get("content-disposition") || "";
    const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|["']?)([^"';\r\n]+)/i);
    const filename = filenameMatch?.[1]?.trim() || "crm-overview.csv";
    objectUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    reportCsvStatus.value = `Đã tải ${filename}`;
  } catch (err) {
    reportsError.value = friendlyErrorMessage(err, "Chưa thể tải báo cáo dạng tệp. Vui lòng thử lại sau.");
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    reportCsvDownloading.value = false;
  }
}

async function fetchOrderCustomers() {
  try {
    const response = await apiFetch(`${API_BASE}/customers?limit=200`);
    if (response.ok) {
      const data = await response.json();
      orderCustomers.value = data.items || [];
    }
  } catch (err) {
    console.error("Fetch order customers error:", err);
  }
}

function resetOrderForm() {
  orderForm.value = {
    order_number: generateSalesOrderNumber(),
    customer_id: orderCustomers.value[0]?.id || "",
    conversation_id: "",
    items: [createOrderItem(activeOrderProducts.value[0]?.id || "")],
  };
}

async function saveOrder() {
  const form = orderForm.value;
  const items = (form.items || []).map((item) => ({
    product_id: Number(item.product_id),
    quantity: Number(item.quantity),
  }));
  if (!form.order_number || !form.customer_id || !items.length || items.some((item) => (
    !Number.isInteger(item.product_id)
    || item.product_id < 1
    || !Number.isInteger(item.quantity)
    || item.quantity < 1
  ))) {
    orderError.value = "Mã đơn, khách hàng và từng sản phẩm với số lượng hợp lệ là bắt buộc.";
    return;
  }
  if (new Set(items.map((item) => item.product_id)).size !== items.length) {
    orderError.value = "Mỗi sản phẩm chỉ được chọn một lần trong đơn bán.";
    return;
  }
  orderSaving.value = true;
  orderError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_number: form.order_number.trim(),
        customer_id: Number(form.customer_id),
        conversation_id: form.conversation_id ? Number(form.conversation_id) : null,
        items,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetOrderForm();
    await fetchOrders();
  } catch (err) {
    orderError.value = friendlyErrorMessage(err, "Chưa thể tạo đơn bán. Vui lòng thử lại sau.");
  } finally {
    orderSaving.value = false;
  }
}

async function fetchLeads() {
  leadsLoading.value = true;
  leadError.value = "";
  try {
    const [leadsResponse, pipelineResponse] = await Promise.all([
      apiFetch(`${API_BASE}/leads`),
      apiFetch(`${API_BASE}/reports/pipeline`),
    ]);
    if (!leadsResponse.ok) throw new Error(`HTTP ${leadsResponse.status}`);
    const data = await leadsResponse.json();
    leads.value = data.items || [];
    if (pipelineResponse.ok) {
      const summary = await pipelineResponse.json();
      pipelineSummary.value = summary.items || [];
    }
  } catch (err) {
    console.error("Fetch leads error:", err);
    leadError.value = "Chưa tải được luồng bán hàng. Vui lòng thử lại sau.";
  } finally {
    leadsLoading.value = false;
  }
}

function resetLeadForm() {
  leadForm.value = {
    title: "",
    customer_id: orderCustomers.value[0]?.id || "",
    conversation_id: "",
    stage: "new",
    value: 0,
    probability: 0,
  };
}

async function saveLead() {
  const form = leadForm.value;
  if (!form.title.trim() || !form.customer_id) {
    leadError.value = "Tên cơ hội và khách hàng là bắt buộc.";
    return;
  }
  leadSaving.value = true;
  leadError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/leads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: form.title.trim(),
        customer_id: Number(form.customer_id),
        conversation_id: form.conversation_id ? Number(form.conversation_id) : null,
        stage: form.stage,
        value: Number(form.value || 0),
        probability: Number(form.probability || 0),
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetLeadForm();
    await fetchLeads();
  } catch (err) {
    leadError.value = friendlyErrorMessage(err, "Chưa thể tạo cơ hội bán hàng. Vui lòng thử lại sau.");
  } finally {
    leadSaving.value = false;
  }
}

async function changeLeadStage(lead, stage) {
  if (lead.stage === stage) return;
  try {
    const response = await apiFetch(`${API_BASE}/leads/${lead.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await fetchLeads();
  } catch (err) {
    leadError.value = "Chưa thể cập nhật giai đoạn cơ hội. Vui lòng thử lại sau.";
  }
}

async function fetchTickets() {
  ticketsLoading.value = true;
  ticketError.value = "";
  try {
    const [ticketsResponse, reportResponse, slaResponse] = await Promise.all([
      apiFetch(`${API_BASE}/tickets`),
      apiFetch(`${API_BASE}/reports/tickets`),
      apiFetch(`${API_BASE}/tickets/sla-notifications`),
    ]);
    if (!ticketsResponse.ok) throw new Error(`HTTP ${ticketsResponse.status}`);
    const data = await ticketsResponse.json();
    tickets.value = data.items || [];
    if (reportResponse.ok) ticketReport.value = await reportResponse.json();
    if (slaResponse.ok) slaNotifications.value = (await slaResponse.json()).items || [];
  } catch (err) {
    console.error("Fetch tickets error:", err);
    ticketError.value = "Chưa tải được danh sách phiếu hỗ trợ. Vui lòng thử lại sau.";
  } finally {
    ticketsLoading.value = false;
  }
}

async function loadTicketHistory(ticket) {
  if (ticketHistory.value[ticket.id]) {
    const next = { ...ticketHistory.value };
    delete next[ticket.id];
    ticketHistory.value = next;
    return;
  }
  ticketHistoryLoading.value = { ...ticketHistoryLoading.value, [ticket.id]: true };
  try {
    const response = await apiFetch(`${API_BASE}/tickets/${ticket.id}/history`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    ticketHistory.value = { ...ticketHistory.value, [ticket.id]: data.items || [] };
  } catch (err) {
    ticketError.value = "Chưa tải được lịch sử xử lý phiếu hỗ trợ. Vui lòng thử lại sau.";
  } finally {
    ticketHistoryLoading.value = { ...ticketHistoryLoading.value, [ticket.id]: false };
  }
}

async function addTicketComment(ticket) {
  const body = String(ticketCommentDrafts.value[ticket.id] || "").trim();
  if (!body) return;
  try {
    const response = await apiFetch(`${API_BASE}/tickets/${ticket.id}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    ticketCommentDrafts.value = { ...ticketCommentDrafts.value, [ticket.id]: "" };
    const next = { ...ticketHistory.value };
    delete next[ticket.id];
    ticketHistory.value = next;
    await fetchTickets();
  } catch (err) {
    ticketError.value = friendlyErrorMessage(err, "Chưa thể thêm ghi chú xử lý. Vui lòng thử lại sau.");
  }
}

async function assignTicket(ticket, assignedUserId) {
  try {
    const response = await apiFetch(`${API_BASE}/tickets/${ticket.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assigned_user_id: assignedUserId ? Number(assignedUserId) : null }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const updated = await response.json();
    ticket.assigned_user_id = updated.assigned_user_id;
    const next = { ...ticketHistory.value };
    delete next[ticket.id];
    ticketHistory.value = next;
  } catch (err) {
    ticketError.value = friendlyErrorMessage(err, "Chưa thể chuyển phiếu hỗ trợ. Vui lòng thử lại sau.");
  }
}

async function reassignConversation(conversation, assignedUserId) {
  try {
    const response = await apiFetch(`${API_BASE}/conversations/${conversation.conversation_id}/assignment`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assigned_user_id: assignedUserId ? Number(assignedUserId) : null }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const result = await response.json();
    conversation.assigned_user_id = result.assigned_user_id;
    await loadCustomer360(conversation.customer_id);
  } catch (err) {
    error.value = friendlyErrorMessage(err, "Chưa thể phân công hội thoại. Vui lòng thử lại sau.");
  }
}

async function fetchTeam() {
  teamLoading.value = true;
  teamError.value = "";
  try {
    const [response, permissionResponse] = await Promise.all([
      apiFetch(`${API_BASE}/team`),
      apiFetch(`${API_BASE}/team/permissions`),
    ]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    teamUsers.value = data.items || [];
    if (permissionResponse.ok) {
      const permissionData = await permissionResponse.json();
      permissionOverrides.value = permissionData.items || [];
    }
  } catch (err) {
    console.error("Fetch team error:", err);
    teamError.value = "Chưa tải được danh sách nhân viên. Vui lòng thử lại sau.";
  } finally {
    teamLoading.value = false;
  }
}

async function fetchWorkflows() {
  workflowsLoading.value = true;
  workflowError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/workflows`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    workflows.value = data.items || [];
  } catch (err) {
    console.error("Fetch workflows error:", err);
    workflowError.value = "Chưa tải được danh sách quy trình. Vui lòng thử lại sau.";
  } finally {
    workflowsLoading.value = false;
  }
}

function resetWorkflowForm() {
  workflowForm.value = {
    name: "",
    event_type: "message.created",
    condition_channel: "",
    action_type: "create_ticket",
    action_title: "",
    action_priority: "normal",
    action_tag: "",
    action_user_id: "",
    enabled: true,
  };
}

async function saveWorkflow() {
  const form = workflowForm.value;
  if (!form.name.trim()) {
    workflowError.value = "Tên quy trình là bắt buộc.";
    return;
  }
  const action = { type: form.action_type };
  if (form.action_type === "create_ticket") {
    action.title = form.action_title.trim() || "Nhắc chăm sóc";
    action.priority = form.action_priority;
  } else if (form.action_type === "add_tag") {
    if (!form.action_tag.trim()) {
      workflowError.value = "Cách gắn nhãn cần có tên nhãn.";
      return;
    }
    action.tag = form.action_tag.trim();
  } else {
    if (!form.action_user_id) {
      workflowError.value = "Cách chuyển người hỗ trợ cần chọn nhân viên.";
      return;
    }
    action.user_id = Number(form.action_user_id);
  }
  workflowSaving.value = true;
  workflowError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name.trim(),
        event_type: form.event_type,
        conditions: form.condition_channel ? { channel: form.condition_channel } : {},
        actions: [action],
        enabled: form.enabled,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetWorkflowForm();
    await fetchWorkflows();
  } catch (err) {
    workflowError.value = friendlyErrorMessage(err, "Chưa thể tạo quy trình. Vui lòng thử lại sau.");
  } finally {
    workflowSaving.value = false;
  }
}

async function toggleWorkflow(workflow) {
  try {
    const response = await apiFetch(`${API_BASE}/workflows/${workflow.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !workflow.enabled }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await fetchWorkflows();
  } catch (err) {
    workflowError.value = "Chưa thể cập nhật quy trình. Vui lòng thử lại sau.";
  }
}

async function toggleWorkflowRuns(workflow) {
  if (workflowRuns.value[workflow.id]) {
    const next = { ...workflowRuns.value };
    delete next[workflow.id];
    workflowRuns.value = next;
    return;
  }
  workflowRunsLoading.value = { ...workflowRunsLoading.value, [workflow.id]: true };
  try {
    const response = await apiFetch(`${API_BASE}/workflows/${workflow.id}/runs`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    workflowRuns.value = { ...workflowRuns.value, [workflow.id]: await response.json() };
  } catch {
    workflowError.value = "Chưa tải được lịch sử quy trình. Vui lòng thử lại sau.";
  } finally {
    workflowRunsLoading.value = { ...workflowRunsLoading.value, [workflow.id]: false };
  }
}

async function retryWorkflowRun(workflow, run) {
  try {
    const response = await apiFetch(`${API_BASE}/workflows/${workflow.id}/runs/${run.id}/retry`, { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await toggleWorkflowRuns(workflow);
    await toggleWorkflowRuns(workflow);
  } catch {
    workflowError.value = "Chưa thể chạy lại quy trình. Vui lòng thử lại sau.";
  }
}

async function fetchExperimentation() {
  experimentationLoading.value = true;
  experimentationError.value = "";
  try {
    const [suggestionsResponse, experimentsResponse, modelsResponse, evaluationResponse] = await Promise.all([
      apiFetch(`${API_BASE}/experiments/rule-suggestions`),
      apiFetch(`${API_BASE}/experiments`),
      apiFetch(`${API_BASE}/experiments/models`),
      apiFetch(`${API_BASE}/experiments/evaluation/dashboard?days=30`),
    ]);
    if (!suggestionsResponse.ok || !experimentsResponse.ok || !modelsResponse.ok || !evaluationResponse.ok) {
      throw new Error("Chưa tải được dữ liệu thử nghiệm. Vui lòng thử lại sau.");
    }
    ruleSuggestions.value = await suggestionsResponse.json();
    experiments.value = await experimentsResponse.json();
    modelVersions.value = await modelsResponse.json();
    aiEvaluationDashboard.value = await evaluationResponse.json();
    await loadExperimentSignals(experiments.value);
  } catch (err) {
    // Chưa đồng bộ database AI remains an internal diagnostic phrase; the
    // shop-facing message below is intentionally free of implementation terms.
    experimentationError.value = friendlyErrorMessage(err, "Chưa tải được dữ liệu thử nghiệm. Vui lòng thử lại sau.");
  } finally {
    experimentationLoading.value = false;
  }
}

function resetAiRuleForm() {
  aiRuleForm.value = {
    title: "",
    rationale: "",
    action_type: "add_tag",
    action_tag: "",
    action_title: "",
    action_priority: "normal",
    action_user_id: "",
    workflow_id: "",
  };
}

function resetExperimentForm() {
  experimentForm.value = { name: "", variants: "A\nB", status: "draft" };
}

async function createRuleSuggestion() {
  const form = aiRuleForm.value;
  if (!form.title.trim() || !form.rationale.trim()) {
    experimentationError.value = "Tiêu đề và lý do đề xuất là bắt buộc.";
    return;
  }
  const action = { type: form.action_type };
  if (form.action_type === "add_tag") {
    if (!form.action_tag.trim()) {
      experimentationError.value = "Cách gắn nhãn cần có tên nhãn.";
      return;
    }
    action.tag = form.action_tag.trim();
  } else if (form.action_type === "create_ticket") {
    action.title = form.action_title.trim() || "Nhắc chăm sóc";
    action.priority = form.action_priority;
  } else {
    if (!form.action_user_id) {
      experimentationError.value = "Cách phân công cần chọn nhân viên.";
      return;
    }
    action.user_id = Number(form.action_user_id);
  }
  aiRuleSaving.value = true;
  experimentationError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/experiments/rule-suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: form.title.trim(),
        rationale: form.rationale.trim(),
        proposed_action: action,
        workflow_id: form.workflow_id ? Number(form.workflow_id) : null,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetAiRuleForm();
    ruleSuggestionFilter.value = "pending";
    await fetchExperimentation();
  } catch (err) {
    experimentationError.value = friendlyErrorMessage(err, "Chưa thể lưu đề xuất. Vui lòng thử lại sau.");
  } finally {
    aiRuleSaving.value = false;
  }
}

async function createExperiment() {
  const form = experimentForm.value;
  const variants = [...new Set(form.variants.split(/[\n,]+/).map((variant) => variant.trim()).filter(Boolean))];
  if (!form.name.trim() || variants.length < 2) {
    experimentationError.value = "Thử nghiệm cần tên và ít nhất hai biến thể khác nhau.";
    return;
  }
  experimentSaving.value = true;
  experimentationError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/experiments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name.trim(), variants, status: form.status,
        min_sample_size: Number(form.min_sample_size || 0),
        stop_criteria: form.target_conversion_rate ? { target_conversion_rate: Number(form.target_conversion_rate) } : {},
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetExperimentForm();
    await fetchExperimentation();
  } catch (err) {
    experimentationError.value = friendlyErrorMessage(err, "Chưa thể tạo bản thử nghiệm. Vui lòng thử lại sau.");
  } finally {
    experimentSaving.value = false;
  }
}

async function createModelVersion() {
  const form = modelForm.value;
  if (![form.name, form.version, form.feature_version, form.target].every((value) => value.trim())) {
    experimentationError.value = "Tên mô hình, phiên bản, dữ liệu và mục tiêu là bắt buộc.";
    return;
  }
  modelSaving.value = true;
  experimentationError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/experiments/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, name: form.name.trim(), version: form.version.trim(), feature_version: form.feature_version.trim(), target: form.target.trim() }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchExperimentation();
  } catch (err) {
    experimentationError.value = friendlyErrorMessage(err, "Chưa thể tạo phiên bản trợ lý. Vui lòng thử lại sau.");
  } finally {
    modelSaving.value = false;
  }
}

async function trainModel(model) {
  try {
    const response = await apiFetch(`${API_BASE}/experiments/models/${model.id}/train`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdout_ratio: 0.2 }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchExperimentation();
  } catch (err) {
    experimentationError.value = friendlyErrorMessage(err, "Chưa thể cập nhật phiên bản trợ lý. Vui lòng kiểm tra lại dữ liệu.");
  }
}

async function createBanditPolicy(experiment) {
  // Bandit policy is the internal name of this allocation setting; keep it
  // out of the shop-facing labels while preserving the API contract.
  const form = banditPolicyForms.value[experiment.id];
  if (!form?.version?.trim()) return;
  try {
    const response = await apiFetch(`${API_BASE}/experiments/${experiment.id}/bandit/policies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: form.version.trim(), epsilon: Number(form.epsilon), status: form.status, config: {} }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchExperimentation();
  } catch (err) {
    experimentationError.value = friendlyErrorMessage(err, "Chưa thể lưu cách phân bổ lượt thử. Vui lòng thử lại sau.");
  }
}

function ruleStatusLabel(status) {
  return { pending: "Chờ duyệt", accepted: "Đã duyệt", rejected: "Từ chối" }[status] || status || "—";
}

function ruleActionLabel(action = {}) {
  if (action.type === "add_tag") return `Gắn nhãn: ${action.tag || "—"}`;
  if (action.type === "create_ticket") return `Tạo phiếu hỗ trợ: ${action.title || "Nhắc chăm sóc"}`;
  if (action.type === "assign_user") return `Phân công #${action.user_id || "—"}`;
  return action.type || "Chưa xác định";
}

async function reviewRuleSuggestion(suggestion, status) {
  try {
    const response = await apiFetch(`${API_BASE}/experiments/rule-suggestions/${suggestion.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await fetchExperimentation();
  } catch (err) {
    experimentationError.value = friendlyErrorMessage(err, "Chưa thể cập nhật đề xuất. Vui lòng thử lại sau.");
  }
}

function resetTeamForm() {
  teamForm.value = { full_name: "", email: "", role: "agent", password: "" };
}

async function saveTeamMember() {
  const form = teamForm.value;
  if (!form.full_name.trim() || !form.email.trim() || form.password.length < 8) {
    teamError.value = "Họ tên, email và mật khẩu tối thiểu 8 ký tự là bắt buộc.";
    return;
  }
  teamSaving.value = true;
  teamError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/team`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        role: form.role,
        password: form.password,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetTeamForm();
    await fetchTeam();
  } catch (err) {
    teamError.value = friendlyErrorMessage(err, "Chưa thể thêm nhân viên. Vui lòng thử lại sau.");
  } finally {
    teamSaving.value = false;
  }
}

async function toggleTeamMember(member) {
  try {
    const response = await apiFetch(`${API_BASE}/team/${member.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !member.is_active }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchTeam();
  } catch (err) {
    teamError.value = friendlyErrorMessage(err, "Chưa thể cập nhật nhân viên. Vui lòng thử lại sau.");
  }
}

function resetTicketForm() {
  ticketForm.value = {
    title: "",
    description: "",
    customer_id: orderCustomers.value[0]?.id || "",
    conversation_id: "",
    priority: "normal",
    assigned_user_id: "",
  };
}

function onTicketCustomerChange() {
  const conversationId = Number(ticketForm.value.conversation_id);
  if (
    conversationId
    && !ticketConversations.value.some(
      (conversation) => Number(conversation.conversation_id) === conversationId
    )
  ) {
    ticketForm.value.conversation_id = "";
  }
}

async function saveTicket() {
  const form = ticketForm.value;
  if (!form.title.trim() || !form.customer_id) {
    ticketError.value = "Tiêu đề phiếu hỗ trợ và khách hàng là bắt buộc.";
    return;
  }
  ticketSaving.value = true;
  ticketError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/tickets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: form.title.trim(),
        description: form.description.trim() || null,
        customer_id: Number(form.customer_id),
        conversation_id: form.conversation_id ? Number(form.conversation_id) : null,
        priority: form.priority,
        assigned_user_id: form.assigned_user_id ? Number(form.assigned_user_id) : null,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetTicketForm();
    await fetchTickets();
  } catch (err) {
    ticketError.value = friendlyErrorMessage(err, "Chưa thể tạo phiếu hỗ trợ. Vui lòng thử lại sau.");
  } finally {
    ticketSaving.value = false;
  }
}

async function changeTicketStatus(ticket, status) {
  if (ticket.status === status) return;
  try {
    const response = await apiFetch(`${API_BASE}/tickets/${ticket.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await fetchTickets();
  } catch (err) {
    ticketError.value = "Chưa thể cập nhật trạng thái phiếu hỗ trợ. Vui lòng thử lại sau.";
  }
}


/* =========================================================
   API - CUSTOMER 360
========================================================= */

async function loadCustomer360(customerId) {
  if (!customerId) {
    customer360.value = null;
    customer360Error.value = "";
    return;
  }

  customer360Loading.value = true;
  customer360Error.value = "";
  try {
    const [profileResponse, timelineResponse, historyResponse, duplicateResponse] = await Promise.all([
      apiFetch(`${API_BASE}/customers/${customerId}`),
      apiFetch(`${API_BASE}/customers/${customerId}/timeline?limit=20&offset=0`),
      apiFetch(`${API_BASE}/customers/${customerId}/merge-history`),
      apiFetch(`${API_BASE}/customers/duplicates?customer_id=${customerId}`),
    ]);
    if (!profileResponse.ok || !timelineResponse.ok || !historyResponse.ok || !duplicateResponse.ok) {
      throw new Error(
        `Customer 360 HTTP ${profileResponse.status}/${timelineResponse.status}/${historyResponse.status}/${duplicateResponse.status}`
      );
    }
    const profile = await profileResponse.json();
    const timeline = await timelineResponse.json();
    const history = await historyResponse.json();
    const duplicates = await duplicateResponse.json();
    if (!orderCustomers.value.length) {
      const customerResponse = await apiFetch(`${API_BASE}/customers?limit=200`);
      if (customerResponse.ok) orderCustomers.value = (await customerResponse.json()).items || [];
    }
    customer360.value = {
      ...profile,
      timeline: timeline.items || [],
      timelineTotal: timeline.total ?? (timeline.items || []).length,
      timelineOffset: timeline.next_offset ?? (timeline.items || []).length,
      timelineHasMore: Boolean(timeline.has_more),
    };
    customer360OverflowOpen.value = false;
    customer360Error.value = "";
    customerTimelineError.value = "";
    customerMergeHistory.value = history.items || [];
    duplicateSuggestions.value = duplicates.items || [];
    if (!duplicateSuggestions.value.some((item) => Number(item.source_customer_id) === Number(customerMergeSourceId.value))) {
      customerMergePreview.value = null;
    }
  } catch (err) {
    console.error("Customer 360 loading error:", err);
    customer360.value = null;
      customer360Error.value = "Không tải được hồ sơ khách hàng. Hãy thử lại.";
  } finally {
    customer360Loading.value = false;
  }
}

async function loadMoreCustomerTimeline() {
  const customerId = customer360.value?.id;
  if (!customerId || !customer360.value?.timelineHasMore || customerTimelineLoading.value) return;
  customerTimelineLoading.value = true;
  customerTimelineError.value = "";
  try {
    const offset = Number(customer360.value.timelineOffset || customer360.value.timeline.length || 0);
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/timeline?limit=20&offset=${offset}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const page = await response.json();
    const existing = customer360.value.timeline || [];
    const seen = new Set(existing.map((event) => `${event.event_type}-${event.event_id}`));
    const appended = (page.items || []).filter((event) => {
      const key = `${event.event_type}-${event.event_id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    customer360.value = {
      ...customer360.value,
      timeline: [...existing, ...appended],
      timelineTotal: page.total ?? customer360.value.timelineTotal,
      timelineOffset: page.next_offset ?? offset + appended.length,
      timelineHasMore: Boolean(page.has_more),
    };
  } catch (err) {
    customerTimelineError.value = "Không tải thêm được lịch sử khách hàng.";
  } finally {
    customerTimelineLoading.value = false;
  }
}

async function previewSelectedCustomerMerge() {
  const survivorId = selected.value?.customer_id;
  const sourceId = Number(customerMergeSourceId.value);
  if (!survivorId || !sourceId || sourceId === Number(survivorId)) {
    customerMergeError.value = "Chọn một khách hàng trùng khác để xem trước.";
    return;
  }
  customerMergeSaving.value = true;
  customerMergeError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/${survivorId}/merge-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_customer_id: sourceId }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    customerMergePreview.value = await response.json();
  } catch (err) {
    customerMergePreview.value = null;
    customerMergeError.value = friendlyErrorMessage(err, "Chưa thể xem trước việc gộp hồ sơ. Vui lòng thử lại sau.");
  } finally {
    customerMergeSaving.value = false;
  }
}

async function mergeSelectedCustomer() {
  const survivorId = selected.value?.customer_id;
  const sourceId = Number(customerMergeSourceId.value);
  if (!survivorId || !sourceId || sourceId === Number(survivorId)) {
    customerMergeError.value = "Chọn một khách hàng trùng khác để gộp.";
    return;
  }
  if (!customerMergePreview.value || Number(customerMergePreview.value.source_customer_id) !== sourceId) {
    await previewSelectedCustomerMerge();
  }
  if (!customerMergePreview.value) return;
  const score = Math.round(Number(customerMergePreview.value.confidence_score || 0) * 100);
  const fields = (customerMergePreview.value.matched_fields || []).join(", ") || "chưa có tín hiệu mạnh";
  if (!(await requestConfirmation(`Độ tin cậy ${score}% (${fields}). Có thể hoàn tác chỉ khi hồ sơ sống chưa phát sinh thay đổi.`, {
    title: "Xác nhận gộp hồ sơ",
    confirmLabel: "Gộp hồ sơ",
    tone: "danger",
  }))) return;
  customerMergeSaving.value = true;
  customerMergeError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/${survivorId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_customer_id: sourceId, confirm: true, reason: "Gộp hồ sơ trùng từ Customer 360" }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    customerMergeSourceId.value = "";
    customerMergePreview.value = null;
    await loadCustomer360(survivorId);
    await loadConversations(false);
    await fetchSavedSegments();
  } catch (err) {
    customerMergeError.value = friendlyErrorMessage(err, "Chưa thể gộp hồ sơ khách hàng. Vui lòng thử lại sau.");
  } finally {
    customerMergeSaving.value = false;
  }
}

async function undoCustomerMerge(merge) {
  const customerId = selected.value?.customer_id;
  if (!customerId || !merge?.merge_id || merge.status !== "completed") return;
  if (!(await requestConfirmation("Chỉ thực hiện được nếu hồ sơ sống chưa có dữ liệu mới.", {
    title: "Hoàn tác merge",
    confirmLabel: "Tách / hoàn tác",
    tone: "danger",
  }))) return;
  customerMergeError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/merge-history/${merge.merge_id}/undo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "Hoàn tác từ Customer 360" }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await loadCustomer360(customerId);
    await loadConversations(false);
    await fetchSavedSegments();
  } catch (err) {
    customerMergeError.value = friendlyErrorMessage(err, "Chưa thể hoàn tác việc gộp hồ sơ. Vui lòng thử lại sau.");
  }
}

async function addCustomerTag() {
  const customerId = selected.value?.customer_id;
  const name = customerTagDraft.value.trim();
  if (!customerId || !name) {
    customerTagError.value = "Nhập tên nhãn trước khi lưu.";
    return;
  }
  customerTagSaving.value = true;
  customerTagError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const created = await response.json();
    customer360.value = {
      ...customer360.value,
      tags: Array.from(new Set([...(customer360.value?.tags || []), created.name])),
    };
    customerTagDraft.value = "";
    await fetchTagCatalog();
  } catch (err) {
    customerTagError.value = "Chưa thể gắn nhãn cho khách hàng. Vui lòng thử lại sau.";
  } finally {
    customerTagSaving.value = false;
  }
}

async function removeCustomerTag(tagName) {
  const customerId = selected.value?.customer_id;
  const tag = tagCatalog.value.find((item) => item.name === tagName);
  if (!customerId || !tag) return;
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/tags/${tag.id}`, {
      method: "DELETE",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    customer360.value = {
      ...customer360.value,
      tags: (customer360.value?.tags || []).filter((item) => item !== tagName),
    };
  } catch (err) {
    customerTagError.value = "Chưa thể xóa nhãn. Vui lòng thử lại sau.";
  }
}


function resetCustomerFactDraft() {
  customerFactDraft.value = {
    fact_type: "preference",
    fact_key: "",
    fact_value: "",
    confidence: 1,
    is_verified: true,
  };
  customerFactError.value = "";
}


async function addCustomerFact() {
  const customerId = selected.value?.customer_id;
  const draft = customerFactDraft.value;
  if (!customerId || !draft.fact_key.trim() || !String(draft.fact_value).trim()) {
    customerFactError.value = "Nhập khóa và giá trị tri thức trước khi lưu.";
    return;
  }

  customerFactSaving.value = true;
  customerFactError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/facts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fact_type: draft.fact_type.trim() || "preference",
        fact_key: draft.fact_key.trim(),
        fact_value: String(draft.fact_value).trim(),
        confidence: Number(draft.confidence || 0),
        source_type: "manual",
        is_verified: Boolean(draft.is_verified),
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const fact = await response.json();
    customer360.value = {
      ...customer360.value,
      facts: [fact, ...(customer360.value?.facts || [])],
    };
    resetCustomerFactDraft();
  } catch (err) {
    customerFactError.value = friendlyErrorMessage(err, "Chưa thể lưu thông tin khách hàng. Vui lòng thử lại sau.");
  } finally {
    customerFactSaving.value = false;
  }
}


async function toggleCustomerFact(fact) {
  const customerId = selected.value?.customer_id;
  if (!customerId) return;
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/facts/${fact.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_verified: !fact.is_verified }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const updated = await response.json();
    customer360.value = {
      ...customer360.value,
      facts: (customer360.value?.facts || []).map((item) => item.id === updated.id ? updated : item),
    };
  } catch (err) {
    customerFactError.value = "Chưa thể cập nhật trạng thái xác nhận. Vui lòng thử lại sau.";
  }
}


async function removeCustomerFact(fact) {
  const customerId = selected.value?.customer_id;
  if (!customerId || !(await requestConfirmation(`Xóa tri thức “${fact.fact_key}”?`, {
    title: "Xóa customer fact",
    confirmLabel: "Xóa tri thức",
    tone: "danger",
  }))) return;
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/facts/${fact.id}`, {
      method: "DELETE",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    customer360.value = {
      ...customer360.value,
      facts: (customer360.value?.facts || []).filter((item) => item.id !== fact.id),
    };
  } catch (err) {
    customerFactError.value = "Chưa thể xóa thông tin khách hàng. Vui lòng thử lại sau.";
  }
}


/* =========================================================
   SELECT CONVERSATION
========================================================= */

async function selectConversation(id) {

  const compactNavigation = window.matchMedia?.("(max-width: 860px)")?.matches;
  discardVoiceRecording();
  selectedId.value = id;
  mobileInboxOpen.value = false;
  mobileCustomerOpen.value = false;
  conversationActionsOpen.value = false;
  composerMode.value = "reply";

  clearImage();


  await loadMessages(
    id,
    true,
    true
  );

  await markConversationRead(id);

  await loadCustomer360(selected.value?.customer_id);

  if (compactNavigation) {
    nextTick(() => chatHeading.value?.focus());
  }

}


/* =========================================================
   API - SEND TEXT MESSAGE
========================================================= */

async function sendTextMessage() {

  const text =
    draft.value.trim();


  if (
    !text
    ||
    !selectedId.value
  ) {
    return;
  }


  const response = await apiFetch(
    `${API_BASE}/conversations/${selectedId.value}/messages`,
    {
      method: "POST",

      headers: {
        "Content-Type":
          "application/json",
      },

      body: JSON.stringify({
        text,
      }),
    }
  );


  if (!response.ok) {

    throw new Error(
      await response.text()
    );

  }


  draft.value = "";

}


/* =========================================================
   API - UPLOAD + SEND IMAGE
========================================================= */

async function sendImageMessage() {

  const media = pendingMedia.value[0];

  if (
    !media
    ||
    !selectedId.value
  ) {
    return;
  }

  if (sendingImage.value) {
    return;
  }

  sendingImage.value = true;

  try {

    const formData =
      new FormData();


    formData.append(
      "file",
      media.file
    );


  const response = await apiFetch(
      `${API_BASE}/conversations/${selectedId.value}/media/upload`,
      {
        method: "POST",

        body:
          formData,
      }
    );


    if (!response.ok) {

      let responseText =
        await response.text();

      try {

        const data =
          JSON.parse(
            responseText
          );

        responseText =
          data?.detail?.message
          || data?.detail?.meta_message
          || responseText;

      } catch {
        // Keep raw backend response.
      }

      throw new Error(
        responseText
      );

    }


    clearImage();

  } finally {

    sendingImage.value = false;

  }

}


/* =========================================================
   SEND REPLY
========================================================= */

async function sendReply() {
  return sendUnifiedReply();
}


async function sendUnifiedReply() {

  if (
    !selectedId.value
    ||
    sending.value
  ) {
    return;
  }

  const text = draft.value.trim();
  const mediaQueue = pendingMedia.value.slice();
  const hasText = Boolean(text);
  const hasMedia = mediaQueue.length > 0;

  if (!hasText && !hasMedia) return;

  const clientId = makeClientId();
  const optimisticIds = [];
  const textClientId = `${clientId}-text`;

  mediaQueue.forEach((media, index) => {
    const mediaClientId = `${clientId}-media-${index + 1}`;
    optimisticIds.push(mediaClientId);
    upsertMessage({
      client_id: mediaClientId,
      message_id: mediaClientId,
      conversation_id: selectedId.value,
      direction: "outbound",
      content: media.mediaType === "image" && index === 0 ? null : index === 0 ? text : null,
      media_type: media.mediaType,
      media_url: media.preview,
      received_at: new Date().toISOString(),
      status: "sending",
      retry_file: media.file,
      retry_preview: media.preview,
      retry_media_type: media.mediaType,
    });
  });

  if (hasText && (!hasMedia || mediaQueue[0]?.mediaType === "image")) {
    optimisticIds.push(textClientId);
    upsertMessage({
      client_id: textClientId,
      message_id: textClientId,
      conversation_id: selectedId.value,
      direction: "outbound",
      content: text,
      media_type: null,
      media_url: null,
      received_at: new Date().toISOString(),
      status: "sending",
      retry_text: text,
    });
  }

  await scrollToBottom();

  sending.value = true;

  try {
    error.value = "";

    const removeOptimistic = (id) => {
      const index = optimisticIds.indexOf(id);
      if (index >= 0) optimisticIds.splice(index, 1);
      messages.value = messages.value.filter((message) => message.client_id !== id);
    };

    const applyResponse = (data) => {
      (data.messages || (data.message ? [data.message] : [])).forEach(upsertMessage);
    };

    const sendMedia = async (media, index) => {
      const mediaType = media.mediaType || "image";
      // JPEG/PNG images keep the Meta-compatible normalization path. Other
      // image formats (WebP/GIF) must use the generic route so their original
      // bytes and MIME type reach providers instead of being rejected by the
      // legacy image endpoint.
      const normalizedContentType = String(media.file?.type || "").toLowerCase();
      const canUseNormalizedImagePath = ["image/jpeg", "image/jpg", "image/png"].includes(
        normalizedContentType,
      );
      const hasGenericMedia = mediaType !== "image" || !canUseNormalizedImagePath;
      const formData = new FormData();
      formData.append("client_id", `${clientId}-${index + 1}`);
      formData.append("file", media.file);

      if (hasGenericMedia) {
        formData.append("media_type", mediaType);
        if (hasText && index === 0) formData.append("caption", text);
      } else if (hasText && index === 0) {
        formData.append("text", text);
      }

      const sendPath = hasGenericMedia
        ? `${API_BASE}/conversations/${selectedId.value}/media/upload-generic`
        : `${API_BASE}/conversations/${selectedId.value}/send`;
      const response = await apiFetch(sendPath, { method: "POST", body: formData });

      if (!response.ok) {
        const responseText = await response.text();
        let detail = responseText;
        try {
          const payload = JSON.parse(responseText);
          detail = payload?.detail?.message || payload?.detail?.meta_message || payload?.detail || responseText;
        } catch {
          // Keep raw backend response.
        }
        throw new Error(detail || `HTTP ${response.status}`);
      }

      const data = await response.json();
      removeOptimistic(`${clientId}-media-${index + 1}`);
      if (index === 0 && hasText && !hasGenericMedia) removeOptimistic(textClientId);
      applyResponse(data);
      removePendingMedia(media.id);
    };

    if (hasMedia) {
      for (const [index, media] of mediaQueue.entries()) {
        await sendMedia(media, index);
      }
    } else {
      const formData = new FormData();
      formData.append("client_id", clientId);
      formData.append("text", text);
      const response = await apiFetch(`${API_BASE}/conversations/${selectedId.value}/send`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await response.text());
      removeOptimistic(textClientId);
      applyResponse(await response.json());
    }

    draft.value = "";
    clearImage();

    await loadConversations(
      false
    );

  } catch (err) {
    console.error(err);

    error.value = friendlyErrorMessage(err, "Chưa thể gửi tin nhắn. Vui lòng thử lại sau.");

    optimisticIds.forEach(
      (id) =>
        markOptimistic(
          id,
          "failed"
        )
    );

  } finally {
    sending.value = false;
  }

}


async function retryMessage(message) {

  if (sending.value) {
    return;
  }

  if (message.retry_text) {
    draft.value =
      message.retry_text;
  }

  if (message.retry_file) {
    clearImage();
    queueMediaFile(message.retry_file, {
      preview: message.retry_preview || "",
      mediaType: message.retry_media_type || "image",
    });
  }

  messages.value =
    messages.value.filter(
      (item) =>
        item.client_id
        !== message.client_id
    );

  await sendUnifiedReply();

}

async function loadExperimentSignals(items = experiments.value) {
  const signals = await Promise.all((items || []).map(async (experiment) => {
    const [reportResponse, policiesResponse] = await Promise.all([
      apiFetch(`${API_BASE}/experiments/${experiment.id}/report`),
      apiFetch(`${API_BASE}/experiments/${experiment.id}/bandit/policies`),
    ]);
    return [experiment.id, reportResponse.ok ? await reportResponse.json() : null, policiesResponse.ok ? await policiesResponse.json() : []];
  }));
  experimentReports.value = Object.fromEntries(signals.map(([id, report]) => [id, report]));
  banditPolicies.value = Object.fromEntries(signals.map(([id, _report, policies]) => [id, policies]));
  banditPolicyForms.value = Object.fromEntries((items || []).map((experiment) => [experiment.id, banditPolicyForms.value[experiment.id] || { version: "v1", epsilon: 0.1, status: "active" }]));
}

async function recalculateRevenueAttribution() {
  attributionSaving.value = true;
  try {
    const candidates = orders.value.filter((order) => order?.id);
    await Promise.all(candidates.map((order) => apiFetch(`${API_BASE}/orders/${order.id}/attribution`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "last_touch" }),
    })));
    await fetchReports();
  } catch (err) {
    reportsError.value = friendlyErrorMessage(err, "Chưa thể cập nhật số liệu. Vui lòng thử lại sau.");
  } finally {
    attributionSaving.value = false;
  }
}

async function retryDocumentRun(doc, run) {
  if (!doc?.id || !run?.id) return;
  try {
    const response = await apiFetch(`${API_BASE}/documents/runs/${run.id}/retry`, { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchDocuments();
  } catch (err) {
    docUploadError.value = friendlyErrorMessage(err, "Chưa thể xử lý lại tài liệu. Vui lòng thử lại sau.");
  }
}


/* =========================================================
   CHAT ACTIONS
========================================================= */

function toggleConversationActions() {
  conversationActionsOpen.value = !conversationActionsOpen.value;
}

function toggleConversationPriority() {
  if (selectedId.value === null) return;
  const next = new Set(conversationPriorityIds.value);
  if (next.has(selectedId.value)) next.delete(selectedId.value);
  else next.add(selectedId.value);
  conversationPriorityIds.value = next;
}

function toggleConversationFavorite() {
  if (selectedId.value === null) return;
  const next = new Set(conversationFavoriteIds.value);
  if (next.has(selectedId.value)) next.delete(selectedId.value);
  else next.add(selectedId.value);
  conversationFavoriteIds.value = next;
}

async function refreshSelectedConversation() {
  if (!selectedId.value) return;
  conversationActionsOpen.value = false;
  await Promise.all([
    loadMessages(selectedId.value, true, true),
    loadCustomer360(selected.value?.customer_id),
  ]);
}

function setComposerMode(mode) {
  if (mode === "internal" && voiceRecording.value) {
    discardVoiceRecording();
  }
  if (mode === "internal") {
    clearImage();
  }
  composerMode.value = mode;
  nextTick(() => document.querySelector(".chat-composer textarea")?.focus());
}

function focusComposer() {
  nextTick(() => document.querySelector(".chat-composer textarea")?.focus());
}

function insertComposerEmoji() {
  draft.value = `${draft.value}${draft.value ? " " : ""}🙂`;
  focusComposer();
}

function insertReplyTemplate() {
  if (!draft.value.trim()) {
    draft.value = "Xin chào, mình có thể hỗ trợ gì cho bạn?";
  } else {
    draft.value = `${draft.value.trim()} Xin chào, mình có thể hỗ trợ gì cho bạn?`;
  }
  focusComposer();
}

async function sendComposerContent() {
  if (composerMode.value !== "internal") {
    await sendUnifiedReply();
    return;
  }

  const customerId = selected.value?.customer_id;
  const content = draft.value.trim();
  if (!customerId || !content) return;

  sending.value = true;
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    draft.value = "";
    clearImage();
    await loadCustomer360(customerId);
  } catch (err) {
    error.value = friendlyErrorMessage(err, "Chưa thể lưu ghi chú. Vui lòng thử lại sau.");
  } finally {
    sending.value = false;
  }
}

async function fetchLeadActivities(lead) {
  leadActivityLoading.value = { ...leadActivityLoading.value, [lead.id]: true };
  try {
    const response = await apiFetch(`${API_BASE}/leads/${lead.id}/activities`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    leadActivities.value = { ...leadActivities.value, [lead.id]: data.items || [] };
  } catch (err) {
    leadError.value = "Chưa tải được lịch sử hoạt động. Vui lòng thử lại sau.";
  } finally {
    leadActivityLoading.value = { ...leadActivityLoading.value, [lead.id]: false };
  }
}

async function toggleLeadActivities(lead) {
  const visible = !leadActivityVisible.value[lead.id];
  leadActivityVisible.value = { ...leadActivityVisible.value, [lead.id]: visible };
  if (visible && !Object.prototype.hasOwnProperty.call(leadActivities.value, lead.id)) {
    await fetchLeadActivities(lead);
  }
}

async function addLeadActivity(lead) {
  const draft = leadActivityDrafts.value[lead.id] || "";
  if (!draft.trim()) return;
  try {
    const response = await apiFetch(`${API_BASE}/leads/${lead.id}/activities`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activity_type: "note", subject: draft.trim() }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    leadActivityDrafts.value = { ...leadActivityDrafts.value, [lead.id]: "" };
    await fetchLeadActivities(lead);
  } catch (err) {
    leadError.value = friendlyErrorMessage(err, "Chưa thể ghi hoạt động. Vui lòng thử lại sau.");
  }
}

function setLeadActivityDraft(leadId, value) {
  leadActivityDrafts.value = { ...leadActivityDrafts.value, [leadId]: value };
}

async function convertLead(lead) {
  const orderId = leadConversionOrders.value[lead.id];
  if (!orderId) {
    leadError.value = "Chọn đơn hàng để ghi nhận chuyển đổi.";
    return;
  }
  leadConversionSaving.value = { ...leadConversionSaving.value, [lead.id]: true };
  try {
    const response = await apiFetch(`${API_BASE}/leads/${lead.id}/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: Number(orderId) }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchLeads();
  } catch (err) {
    leadError.value = friendlyErrorMessage(err, "Chưa thể ghi nhận kết quả bán hàng. Vui lòng thử lại sau.");
  } finally {
    leadConversionSaving.value = { ...leadConversionSaving.value, [lead.id]: false };
  }
}

async function savePermissionOverride() {
  permissionSaving.value = true;
  permissionError.value = "";
  try {
    const form = permissionForm.value;
    const body = {
      resource: form.resource,
      action: form.action,
      effect: form.effect,
      ...(form.role ? { role: form.role } : {}),
      ...(form.user_id ? { user_id: Number(form.user_id) } : {}),
    };
    const response = await apiFetch(`${API_BASE}/team/permissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const created = await response.json();
    permissionOverrides.value = [...permissionOverrides.value, created];
  } catch (err) {
    permissionError.value = friendlyErrorMessage(err, "Chưa thể lưu quyền truy cập. Vui lòng thử lại sau.");
  } finally {
    permissionSaving.value = false;
  }
}

async function deletePermissionOverride(override) {
  const confirmed = await requestConfirmation(
    `Xóa quy tắc ${override.resource} · ${override.action}?`,
    { title: "Xóa quy tắc quyền", confirmLabel: "Xóa quy tắc", tone: "danger" },
  );
  if (!confirmed) return;

  permissionSaving.value = true;
  permissionError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/team/permissions/${override.id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    permissionOverrides.value = permissionOverrides.value.filter((item) => item.id !== override.id);
  } catch (err) {
    permissionError.value = friendlyErrorMessage(err, "Chưa thể xóa quy tắc quyền. Vui lòng thử lại sau.");
  } finally {
    permissionSaving.value = false;
  }
}


/* =========================================================
   START APP
========================================================= */

onMounted(async () => {

  window.addEventListener("keydown", handleGlobalKeydown);

  await loadAuthSession();
  // Tenant data is only loaded after the platform session identifies an
  // active shop. Anonymous mode exposes the login gate only.
  if (!authUser.value) {
    currentTab.value = "settings";
    return;
  }

  loadBusinessProfile();
  loadThemePreference();

  await loadConversations(
    true
  );
  await Promise.all([fetchProducts(), fetchOrderCustomers()]);
  resetOrderForm();
  resetPurchaseOrderForm();
  fetchTagCatalog();
  fetchSavedSegments();

  connectRealtime();
  fetchDocuments();
  fetchOrders();
  fetchSuppliers();
  fetchPurchaseOrders();
  fetchLeads();
  fetchTickets();
  fetchOperationalNotifications();
  fetchTeam();
  fetchWorkflows();
  fetchExperimentation();
  fetchReports();
  fetchAutoReplySetting();
  fetchChatbotRuntime();
  fetchFollowups();
  fetchCsat();
  fetchMetaStatus();

  const metaResult = new URLSearchParams(window.location.search).get("meta");
  if (metaResult === "connected") {
    metaNotice.value = "Kết nối Facebook/Instagram thành công.";
    fetchMetaStatus();
  } else if (metaResult === "error") {
    metaNotice.value = "Kết nối Facebook/Instagram thất bại. Hãy kiểm tra cấu hình rồi thử lại.";
  }

  pollingTimer = setInterval(

    async () => {

      await loadConversations(
        false
      );


      if (selectedId.value) {

        await loadMessages(
          selectedId.value,
          false,
          true
        );

      }

      void fetchOperationalNotifications();

    },
    25000
  );

});


/* =========================================================
   STOP POLLING
========================================================= */

function applyCannedResponse() {
  const canned = cannedResponses.value.find((item) => String(item.id) === String(selectedCannedId.value));
  if (!canned) return;
  draft.value = canned.content || "";
  selectedCannedId.value = "";
  focusComposer();
}

async function fetchChatbotRuntime() {
  chatbotConfigError.value = "";
  try {
    const [configResponse, cannedResponse] = await Promise.all([
      apiFetch(`${API_BASE}/chatbot/config`),
      apiFetch(`${API_BASE}/chatbot/canned-responses`),
    ]);
    if (configResponse.ok) {
      chatbotConfig.value = { ...chatbotConfig.value, ...(await configResponse.json()) };
      businessHoursJson.value = JSON.stringify(chatbotConfig.value.business_hours || {}, null, 2);
      const weekdayRange = chatbotConfig.value.business_hours?.mon?.[0];
      if (Array.isArray(weekdayRange)) {
        businessHoursForm.value.start = weekdayRange[0] || businessHoursForm.value.start;
        businessHoursForm.value.end = weekdayRange[1] || businessHoursForm.value.end;
      }
      const configuredHours = chatbotConfig.value.business_hours || {};
      businessHoursDays.value = Object.fromEntries(
        businessHourDayLabels.map(([key]) => [key, Array.isArray(configuredHours[key]) && configuredHours[key].length > 0]),
      );
      businessHoursForm.value.enabled = Object.values(businessHoursDays.value).some(Boolean);
    }
    if (cannedResponse.ok) cannedResponses.value = (await cannedResponse.json()).items || [];
  } catch (err) {
    chatbotConfigError.value = friendlyErrorMessage(err, "Chưa tải được cài đặt trợ lý. Vui lòng thử lại sau.");
  }
}

async function saveChatbotRuntime() {
  chatbotConfigSaving.value = true;
  chatbotConfigError.value = "";
  try {
    let businessHours = chatbotConfig.value.business_hours;
    try {
      businessHours = JSON.parse(businessHoursJson.value || "{}");
    } catch {
      throw new Error("Giờ hoạt động không đúng định dạng.");
    }
    const response = await apiFetch(`${API_BASE}/chatbot/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: chatbotConfig.value.name,
        enabled: chatbotConfig.value.enabled,
        handoff_enabled: chatbotConfig.value.handoff_enabled,
        top_k: Number(chatbotConfig.value.top_k),
        similarity_threshold: Number(chatbotConfig.value.similarity_threshold),
        business_hours: businessHours,
      }),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
    chatbotConfig.value = { ...chatbotConfig.value, ...(await response.json()) };
    businessHoursJson.value = JSON.stringify(chatbotConfig.value.business_hours || {}, null, 2);
  } catch (err) {
    chatbotConfigError.value = friendlyErrorMessage(err, "Chưa thể lưu cài đặt trợ lý. Vui lòng thử lại sau.");
  } finally {
    chatbotConfigSaving.value = false;
  }
}

async function saveCannedResponse() {
  cannedResponseSaving.value = true;
  cannedResponseError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/canned-responses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cannedResponseForm.value),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
    cannedResponses.value = [...cannedResponses.value, await response.json()];
    cannedResponseForm.value = { shortcut: "/", title: "", content: "", enabled: true };
  } catch (err) {
    cannedResponseError.value = friendlyErrorMessage(err, "Chưa thể lưu mẫu trả lời. Vui lòng thử lại sau.");
  } finally {
    cannedResponseSaving.value = false;
  }
}

async function toggleBotMode() {
  if (!selected.value?.conversation_id) return;
  const mode = selectedBotMode.value === "human" ? "resume" : "pause";
  const customerId = selected.value.customer_id;
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/conversations/${selected.value.conversation_id}/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: mode === "pause" ? "Nhân viên tiếp quản từ CRM" : "Nhân viên trả lại cho bot" }),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
    botModes.value = { ...botModes.value, [selected.value.conversation_id]: (await response.json()).bot_mode };
    await loadCustomer360(customerId);
  } catch (err) {
    error.value = friendlyErrorMessage(err, "Chưa thể đổi cách trả lời. Vui lòng thử lại sau.");
  }
}

async function fetchFollowups() {
  followupsLoading.value = true;
  followupError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/followups?status=scheduled`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    followups.value = (await response.json()).items || [];
  } catch (err) {
    followupError.value = friendlyErrorMessage(err, "Chưa tải được lịch nhắc chăm sóc. Vui lòng thử lại sau.");
  } finally {
    followupsLoading.value = false;
  }
}

async function dispatchFollowups() {
  if (followupDispatching.value) return;
  followupDispatching.value = true;
  followupError.value = "";
  followupNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/followups/dispatch`, { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchFollowups();
    followupNotice.value = "Đã xử lý các lịch nhắc đến hạn.";
  } catch (err) {
    followupError.value = friendlyErrorMessage(err, "Chưa thể xử lý lịch nhắc đến hạn. Vui lòng thử lại sau.");
  } finally {
    followupDispatching.value = false;
  }
}

async function cancelFollowup(followup) {
  if (!followup?.id) return;
  if (!(await requestConfirmation("Hủy lịch chăm sóc này?", {
    title: "Hủy follow-up",
    confirmLabel: "Hủy lịch",
    tone: "danger",
  }))) return;
  followupError.value = "";
  followupNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/followups/${followup.id}/cancel`, { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    followups.value = followups.value.filter((item) => item.id !== followup.id);
    followupNotice.value = "Đã hủy lịch chăm sóc.";
  } catch (err) {
    followupError.value = friendlyErrorMessage(err, "Chưa thể hủy lịch nhắc chăm sóc. Vui lòng thử lại sau.");
  }
}

async function fetchCsat() {
  csatLoading.value = true;
  csatError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/csat`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    csatFeedback.value = payload.items || [];
    csatSummary.value = payload.summary || csatSummary.value;
  } catch (err) {
    console.warn("Fetch CSAT error:", err);
    csatError.value = friendlyErrorMessage(err, "Chưa tải được đánh giá chăm sóc khách hàng. Vui lòng thử lại sau.");
  } finally {
    csatLoading.value = false;
  }
}

onUnmounted(() => {

  window.removeEventListener("keydown", handleGlobalKeydown);

  if (authRateLimitTimer) {
    clearInterval(authRateLimitTimer);
    authRateLimitTimer = null;
  }

  if (pollingTimer) {

    clearInterval(
      pollingTimer
    );

    pollingTimer = null;

  }


  discardVoiceRecording();
  clearImage();

  if (reconnectTimer) {
    clearTimeout(
      reconnectTimer
    );
  }

  if (socket) {
    socket.close();
  }

});
function followupProductLabel(item) {
  const metadata = item?.metadata || item?.metadata_ || {};
  return item?.product_name || metadata.product_name || metadata.product || "Sản phẩm khách đang quan tâm";
}

async function fetchServiceAccountSummary() {
  if (!authUser.value?.business_id) return;
  serviceAccountLoading.value = true;
  serviceAccountError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/subscription/summary`);
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    serviceAccountSummary.value = detail;
  } catch (err) {
    if (Number(err?.status) !== 401 && Number(err?.status) !== 403) {
      serviceAccountError.value = friendlyErrorMessage(err, "Chưa tải được thông tin gói của shop. Vui lòng thử lại sau.");
    }
  } finally {
    serviceAccountLoading.value = false;
  }
}

function saveSelectedConversationSample() {
  if (!selected.value || !messages.value.length) return;
  const key = `crm-learning-samples-${authUser.value?.business_id || "shop"}`;
  try {
    let samples = [];
    try { samples = JSON.parse(localStorage.getItem(key) || "[]"); } catch { samples = []; }
    if (!Array.isArray(samples)) samples = [];
    samples.push({ conversation_id: selected.value.conversation_id, saved_at: new Date().toISOString(), messages: messages.value.slice(-20).map((item) => ({ direction: item.direction, content: item.content })) });
    localStorage.setItem(key, JSON.stringify(samples.slice(-100)));
    learningNotice.value = "Đã lưu cuộc trò chuyện này làm mẫu tham khảo.";
  } catch {
    learningNotice.value = "Chưa thể lưu mẫu trên thiết bị này. Vui lòng thử lại sau.";
  }
  conversationActionsOpen.value = false;
}

function followupRecommendationLabel(item) {
  const metadata = item?.metadata || item?.metadata_ || {};
  return item?.recommended_product_name || metadata.recommended_product_name || metadata.recommended_product || "";
}

</script>


<template>

  <div class="crm-app" :class="{ 'sidebar-collapsed': sidebarCollapsed, 'auth-locked': !authUser, 'crm-dark': darkMode }">


    <!-- =====================================================
         SIDEBAR
    ====================================================== -->

    <aside v-if="authUser" class="side">

      <div class="brand-lockup">
        <div class="crm-brand-mark" data-testid="crm-brand-mark" aria-label="Smart Merchant Hub">
          <svg viewBox="0 0 48 48" aria-hidden="true">
            <path d="M7 20h34v20H7z" fill="currentColor" opacity=".18" />
            <path d="M5 19 9 8h30l4 11-4 5H9z" fill="currentColor" />
            <path d="M9 19h30v21H9z" fill="currentColor" opacity=".85" />
            <path d="M18 40V27h12v13M13 25h3v5h-3zm19 0h3v5h-3z" fill="#fffaf8" />
            <path d="M8 18h32" stroke="#fffaf8" stroke-width="3" stroke-linecap="round" />
          </svg>
        </div>
        <div class="brand-copy">
          <strong>Smart Merchant Hub</strong>
          <small>Không gian quản lý shop</small>
        </div>
      </div>


      <nav class="menu">

        <div class="menu-group menu-group-customer">
          <button
            class="menu-item"
            :class="{ active: currentTab === 'inbox' }"
            title="Hộp thư & Khách hàng 360"
            @click="currentTab = 'inbox'"
          >
            <svg class="nav-icon nav-icon-inbox" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5a7.6 7.6 0 0 1-8 7.5 8.8 8.8 0 0 1-3.6-.8L4 20l1.4-3.5A7.1 7.1 0 0 1 4 12a7.6 7.6 0 0 1 8-7.5 7.6 7.6 0 0 1 8 7Z" /></svg>
            <b>Hộp thư &amp; Khách hàng 360</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'leads' }" title="Luồng bán hàng" @click="currentTab = 'leads'; fetchOrderCustomers(); fetchLeads()">
            <svg class="nav-icon nav-icon-pipeline" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16l-6.2 7v5.5l-3.6 2V12Z" /></svg><b>Luồng bán hàng</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'tickets' }" title="Phiếu hỗ trợ & thời hạn" @click="currentTab = 'tickets'; fetchOrderCustomers(); fetchTickets()">
            <svg class="nav-icon nav-icon-tickets" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="m8.3 12.3 2.3 2.3 5-5" /></svg><b>Phiếu hỗ trợ &amp; thời hạn</b>
          </button>
        </div>

        <div class="menu-group menu-group-operations">
          <span class="menu-group-label">Vận hành</span>
          <button class="menu-item" :class="{ active: currentTab === 'products' }" title="Sản phẩm" @click="currentTab = 'products'; fetchProducts()">
            <svg class="nav-icon nav-icon-products" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></svg><b>Sản phẩm</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'orders' }" title="Đơn bán" @click="currentTab = 'orders'; loadConversations(false); fetchOrderCustomers(); fetchProducts(); fetchOrders()">
            <svg class="nav-icon nav-icon-orders" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l3 3v15H6Z" /><path d="M15 3v4h4M9 11h6M9 15h6M9 19h4" /></svg><b>Đơn bán</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'business_hours' }" title="Giờ làm việc" @click="currentTab = 'business_hours'; fetchChatbotRuntime()">
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3.5 2" /></svg><b>Giờ làm việc</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'sla_rules' }" title="Quy tắc thời hạn" @click="currentTab = 'sla_rules'">
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14M5 12h9M5 18h14" /><circle cx="17" cy="12" r="2" /></svg><b>Quy tắc thời hạn</b>
          </button>
          <!-- Nhập hàng được xử lý nội bộ, không hiển thị trong workspace CSKH. -->
        </div>

        <div class="menu-group menu-group-ai">
          <span class="menu-group-label">Kiến thức &amp; tự động hóa</span>
          <div class="ai-submenu">
            <button class="menu-item" :class="{ active: currentTab === 'documents' }" title="Kho kiến thức" @click="currentTab = 'documents'; fetchDocuments()">
              <svg class="nav-icon nav-icon-knowledge" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5c2.8-1 5.4-.6 8 1v12c-2.6-1.6-5.2-2-8-1Zm16 0c-2.8-1-5.4-.6-8 1v12c2.6-1.6 5.2-2-8-1Z" /><path d="M12 6.5v12" /></svg><b>Kho kiến thức</b>
            </button>
            <!-- Trợ lý chat được dùng trong Inbox, không cần shortcut riêng. -->
            <button class="menu-item" :class="{ active: currentTab === 'workflows' }" title="Quy trình" @click="currentTab = 'workflows'; fetchWorkflows(); fetchTeam()">
              <svg class="nav-icon nav-icon-workflow" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4" width="5" height="5" rx="1" /><rect x="15.5" y="4" width="5" height="5" rx="1" /><rect x="9.5" y="15" width="5" height="5" rx="1" /><path d="M8.5 6.5h7M12 9v6" /></svg><b>Quy trình</b>
            </button>
            <!-- Rule Lab giữ ở tầng quản trị, không hiển thị cho nhân viên vận hành. -->
          </div>
        </div>

        <div class="menu-group menu-group-insights">
          <span class="menu-group-label">Phân tích</span>
          <button class="menu-item" :class="{ active: currentTab === 'reports' }" title="Báo cáo" @click="currentTab = 'reports'; fetchReports()">
            <svg class="nav-icon nav-icon-reports" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V10m5 10V4m5 16v-7m5 7V7" /></svg><b>Báo cáo</b>
          </button>
        </div>

        <div class="menu-group menu-group-channels">
          <span class="menu-group-label">Kênh liên kết</span>
          <button class="menu-item" :class="{ active: currentTab === 'channels' }" title="Kết nối mạng xã hội" @click="openChannels">
            <svg class="nav-icon nav-icon-channels" viewBox="0 0 24 24" aria-hidden="true"><circle cx="7" cy="12" r="3" /><circle cx="17" cy="7" r="3" /><circle cx="17" cy="17" r="3" /><path d="m9.5 10.8 4.8-2.6M9.5 13.2l4.8 2.6" /></svg><b>Kết nối mạng xã hội</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'webhooks' }" title="Nhận sự kiện" @click="openWebhooks">
            <svg class="nav-icon nav-icon-webhooks" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4v5m10-5v5M4 9h16M6 14h5m2 0h5M6 18h5m2 0h5" /><rect x="4" y="3" width="16" height="18" rx="2" /></svg><b>Nhận sự kiện</b>
          </button>
        </div>

        <div class="menu-group menu-group-system">
          <span class="menu-group-label">Hệ thống</span>
          <button class="menu-item menu-item-service" :class="{ active: currentTab === 'service' }" title="Chọn gói dịch vụ" @click="openServicePage">
            <svg class="nav-icon nav-icon-service" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 14.1 9l5.9.4-4.5 3.8 1.5 5.7-5-3.1-5 3.1 1.5-5.7L4 9.4l5.9-.4Z" /><path d="M12 14v6.5M8.5 20.5h7" /></svg><b>Chọn gói dịch vụ</b>
          </button>
          <button class="menu-item menu-item-settings" :class="{ active: currentTab === 'settings' }" title="Cài đặt" @click="openSettings">
            <svg class="nav-icon nav-icon-settings" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M19 13.5v-3l-2.1-.7a5.3 5.3 0 0 0-.5-1.1l1-2-2.1-2.1-2 1a5.3 5.3 0 0 0-1.1-.5L11.5 3h-3l-.7 2.1a5.3 5.3 0 0 0-1.1.5l-2-1L2.6 6.7l1 2a5.3 5.3 0 0 0-.5 1.1l-2.1.7v3l2.1.7a5.3 5.3 0 0 0 .5 1.1l-1 2 2.1 2.1 2-1a5.3 5.3 0 0 0 1.1.5l.7 2.1h3l.7-2.1a5.3 5.3 0 0 0 1.1-.5l2 1 2.1-2.1-1-2a5.3 5.3 0 0 0 .5-1.1Z" /></svg><b>Cài đặt</b>
          </button>
        </div>

      </nav>



      <div class="side-card">
          <span class="side-card-kicker">TRẠNG THÁI HỆ THỐNG</span>
        <strong>CRM đang hoạt động</strong>
        <small>Dữ liệu hội thoại và vận hành được đồng bộ theo business.</small>
        <span class="status-dot"><i></i> Đang hoạt động</span>
      </div>


      <button
        type="button"
        class="collapse"
        :aria-expanded="String(!sidebarCollapsed)"
        :aria-label="sidebarCollapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng'"
        :title="sidebarCollapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng'"
        @click="toggleSidebar"
      >
        <span class="collapse-icon" aria-hidden="true">‹</span>
        <span>{{ sidebarCollapsed ? 'Mở rộng' : 'Thu gọn' }}</span>
      </button>

    </aside>


    <!-- =====================================================
         MAIN
    ====================================================== -->

    <!-- Authenticated CRM shell uses <main v-if="authUser" class="main">; the public service request keeps the same frame. -->
    <main v-if="authUser || serviceLandingOpen" class="main" :class="{ 'public-service-main': serviceLandingOpen }">


      <!-- TOP -->

      <header v-if="authUser" class="top">

        <div class="welcome">

          <strong>
            {{ workspaceGreeting }} <span aria-hidden="true">👋</span>
          </strong>

          <span>
            Theo dõi khách hàng, hội thoại và vận hành trong một không gian.
          </span>

        </div>


        <div class="top-actions">

          <label class="top-search" role="search">
            <input
              class="top-search-input"
              v-model="search"
              type="search"
              placeholder="Tìm kiếm khách hàng, tin nhắn, đơn hàng..."
              aria-label="Tìm kiếm khách hàng, tin nhắn, đơn hàng"
              @keydown.enter="runGlobalSearch"
            />
            <svg class="top-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="5.8" /><path d="m15.2 15.2 4 4" /></svg>
          </label>

          <button
            type="button"
            class="quick-action-trigger"
            aria-label="Mở thao tác nhanh"
            title="Thao tác nhanh (Ctrl+K)"
            @click="openQuickActions"
          >
            <span>Thao tác nhanh</span><kbd>Ctrl K</kbd>
          </button>


          <div class="notification-menu">
            <button
              type="button"
              class="bell"
              aria-label="Mở thông báo"
              title="Mở thông báo"
              :aria-expanded="String(notificationsOpen)"
              @click="openNotifications"
            >
              <svg class="top-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M18 10a6 6 0 0 0-12 0c0 6-2.5 6.5-2.5 8h17C20.5 16.5 18 16 18 10Z" /><path d="M10 21h4" /></svg>
              <i v-if="unreadOperationalNotificationCount">{{ unreadOperationalNotificationCount }}</i>
            </button>
            <div v-if="notificationsOpen" class="notification-popover" role="dialog" aria-label="Thông báo CRM">
              <div class="notification-popover-head">
                <strong>Thông báo</strong>
                <span>{{ unreadOperationalNotificationCount }} chưa đọc</span>
              </div>
              <p v-if="notificationError" class="notification-empty notification-error" role="alert">{{ notificationError }}</p>
              <p v-else-if="!operationalNotifications.length" class="notification-empty">Chưa có thông báo mới.</p>
              <button
                v-for="notification in operationalNotifications"
                :key="notification.id"
                type="button"
                class="notification-item"
                :class="{ unread: !notification.is_read }"
                @click="activateNotification(notification)"
              >
                <strong>{{ notification.title }}</strong>
                <span>{{ notification.body || 'Mở để xem chi tiết.' }}</span>
              </button>
            </div>
          </div>

          <button
            type="button"
            class="dark-mode-toggle"
            :aria-pressed="darkMode"
            :aria-label="darkMode ? 'Tắt chế độ tối' : 'Bật chế độ tối'"
            :title="darkMode ? 'Tắt chế độ tối' : 'Bật chế độ tối'"
            @click="toggleDarkMode"
          >
            <span class="help" aria-hidden="true"></span>
            <span aria-hidden="true">{{ darkMode ? '☀' : '☾' }}</span>
          </button>


          <button
            type="button"
            class="team"
            aria-label="Mở Cài đặt"
            title="Mở Cài đặt"
            @click="openSettings"
          >

            <div class="team-avatar">
              SM
            </div>

            <div>

              <b>
                Không gian quản lý shop
              </b>

              <small>
                Quản trị viên
              </small>

            </div>

          </button>

        </div>

      </header>


      <!-- ERROR -->

      <div
        v-if="error"
        class="error"
      >
        <span>{{ error }}</span>
        <button type="button" class="error-retry-btn" :disabled="loading" @click="loadConversations()">{{ loading ? 'Đang tải...' : 'Thử lại' }}</button>
      </div>

      <div v-if="quickActionOpen" class="quick-action-backdrop" @click.self="closeQuickActions">
        <section class="quick-action-dialog" role="dialog" aria-modal="true" aria-label="Thao tác nhanh">
          <div class="quick-action-heading">
            <div><strong>Thao tác nhanh</strong><span>Tối đa 3 bước cho các tác vụ CRM thường dùng.</span></div>
            <button type="button" class="quick-action-close" aria-label="Đóng thao tác nhanh" @click="closeQuickActions">×</button>
          </div>
          <input
            ref="quickActionInput"
            v-model="quickActionQuery"
            class="quick-action-input"
            type="search"
            placeholder="Tìm thao tác..."
            aria-label="Tìm thao tác nhanh"
          />
          <div class="quick-action-list">
            <button
              v-for="action in quickActionItems"
              :key="action.id"
              type="button"
              class="quick-action-item"
              :disabled="action.disabled"
              @click="runQuickAction(action.id)"
            >
              <span><strong>{{ action.label }}</strong><small>{{ action.hint }}</small></span>
              <b>›</b>
            </button>
            <p v-if="!quickActionItems.length" class="settings-empty">Không tìm thấy thao tác phù hợp.</p>
          </div>
        </section>
      </div>


      <!-- ===================================================
           3 CỘT
      ==================================================== -->

      <section
        v-if="currentTab === 'inbox'"
        class="layout"
        :class="{
          'has-selected-conversation': !!selected,
          'mobile-inbox-open': mobileInboxOpen,
          'mobile-customer-open': mobileCustomerOpen,
        }"
      >



        <!-- =================================================
             INBOX
        ================================================== -->

        <aside id="crm-inbox-panel" class="inbox" aria-label="Danh sách hội thoại">


          <div class="inbox-title">
            <div class="inbox-title-copy">
              <span class="inbox-title-kicker">HỘP THƯ KHÁCH HÀNG</span>
              <h2>Hộp thư khách hàng</h2>
              <p>Quản lý hội thoại và hồ sơ khách hàng trên một màn hình.</p>
            </div>
            <div class="inbox-title-actions">
              <span class="inbox-title-count">{{ filtered.length }}</span>
              <button type="button" class="inbox-refresh" aria-label="Làm mới hội thoại" title="Làm mới hội thoại" @click="loadConversations(false)">↻</button>
            </div>
          </div>

          <div class="inbox-toolbar">
            <div class="inbox-channel-filter">
              <div class="inbox-quick-tabs" role="tablist" aria-label="Lọc nhanh hội thoại">
                <button type="button" :class="{ active: inboxQuickFilter === 'all' }" :aria-selected="inboxQuickFilter === 'all'" @click="inboxQuickFilter = 'all'">Tất cả <i>{{ conversations.length }}</i></button>
                <button type="button" :class="{ active: inboxQuickFilter === 'unread' }" :aria-selected="inboxQuickFilter === 'unread'" @click="inboxQuickFilter = 'unread'">Chưa đọc <i>{{ unreadConversationCount }}</i></button>
                <button type="button" :class="{ active: inboxQuickFilter === 'important' }" :aria-selected="inboxQuickFilter === 'important'" @click="inboxQuickFilter = 'important'">Quan trọng <i>{{ importantConversationCount }}</i></button>
              </div>
              <label class="inbox-channel-select">
                <span class="visually-hidden">Lọc theo kênh</span>
                <select v-model="activeFilter" aria-label="Lọc theo kênh hội thoại">
                  <option value="all">Tất cả kênh</option>
                  <option v-for="channel in inboxChannels" :key="channel.value" :value="channel.value">{{ channel.label }} ({{ channel.count }})</option>
                </select>
              </label>
            </div>


          <div class="search-box inbox-search-box">
            <span aria-hidden="true">⌕</span>
            <input ref="inboxSearchInput" v-model="search" aria-label="Tìm hội thoại" placeholder="Tìm theo tên, nội dung hoặc kênh..." @keydown.escape="clearInboxSearch" />
            <button v-if="search" type="button" class="search-clear" aria-label="Xóa tìm kiếm" @click="clearInboxSearch">×</button>
            </div>

          <details class="inbox-filter-disclosure">
            <summary>Bộ lọc &amp; nhóm khách hàng</summary>
            <div class="inbox-filter-panel">
              <div class="filter-panel-heading"><span>Nhãn khách hàng</span><button v-if="tagFilters.length" type="button" @click="tagFilters = []">Bỏ chọn</button></div>
              <div v-if="tagCatalog.length" class="tag-chip-list">
                <button v-for="tag in tagCatalog" :key="tag.id" type="button" class="tag-chip" :class="{ active: tagFilters.includes(tag.name) }" @click="toggleTagFilter(tag.name)">
                  <span>#{{ tag.name }}</span><i>{{ tag.customer_count || 0 }}</i>
                </button>
              </div>
              <div v-else class="filter-empty">Chưa có nhãn để lọc</div>
              <div class="tag-mode-toggle" role="group" aria-label="Cách lọc tag">
                <label :class="{ active: tagFilterMode === 'all' }"><input v-model="tagFilterMode" type="radio" value="all" /> Tất cả nhãn</label>
                <label :class="{ active: tagFilterMode === 'any' }"><input v-model="tagFilterMode" type="radio" value="any" /> Có ít nhất một nhãn</label>
              </div>
            </div>

            <div class="segment-control">
              <div class="filter-panel-heading"><span>Nhóm khách hàng</span><small v-if="segmentLoading">Đang tải...</small></div>
              <select v-model="selectedSegmentId" aria-label="Lọc theo nhóm khách hàng đã lưu" @change="loadSegmentMembers">
                <option value="">Mọi nhóm đã lưu</option>
                <option v-for="segment in savedSegments" :key="segment.id" :value="segment.id">{{ segment.name }} ({{ segment.customer_count }})</option>
              </select>
            </div>
          </details>
          </div>


          <div class="conversation-scroll">

            <div v-if="!filtered.length" class="inbox-empty-state">
              <span class="inbox-empty-state-icon" aria-hidden="true">✦</span>
              <strong>{{ conversations.length ? "Không có hội thoại phù hợp" : "Hộp thư đang chờ tin nhắn đầu tiên" }}</strong>
              <p>{{ conversations.length ? "Thử thay đổi từ khóa hoặc bộ lọc để xem lại." : "Hội thoại từ Facebook, Instagram, Telegram và Zalo sẽ xuất hiện tại đây." }}</p>
            </div>

            <button
              v-for="item in filtered"
              :key="
                item.conversation_id
              "
              class="conversation"

              :class="{
                selected:
                  item.conversation_id
                  === selectedId
              }"

              @click="
                selectConversation(
                  item.conversation_id
                )
              "
            >


              <div class="avatar">

                <img
                  v-if="
                    resolvedAvatarUrl(item)
                  "
                  :src="
                    resolvedAvatarUrl(item)
                  "
                  :alt="
                    nameOf(item)
                  "
                  @error="markAvatarFailed(item)"
                />

                <span v-else>
                  {{ initials(item) }}
                </span>

              </div>


              <div class="conv-copy">


                <div class="conv-head">
                  <strong>
                    {{ nameOf(item) }}
                  </strong>
                  <div class="conversation-status">
                    <span v-if="item.unread_count" class="conversation-unread">{{ item.unread_count }}</span>
                    <time>{{ formatTime(item.last_message_at) }}</time>
                  </div>
                </div>


                <div class="channel">

                  <span class="conversation-channel-pill">
                    <span class="social-icon" :class="item.channel">

                    <svg
                      v-if="
                        item.channel
                        === 'facebook'
                      "
                      viewBox="0 0 24 24"
                    >

                      <path
                        fill="currentColor"
                        d="
                          M13.6 22v-9h3
                          l.5-3.5h-3.5V7.2
                          c0-1 .3-1.8 1.8-1.8
                          h1.9V2.3
                          c-.3 0-1.5-.1-2.8-.1
                          -2.8 0-4.7 1.7-4.7 4.8
                          v2.5H6.7V13h3.1v9h3.8Z
                        "
                      />

                    </svg>


                    <svg
                      v-else
                      viewBox="0 0 24 24"
                    >

                      <rect
                        x="3"
                        y="3"
                        width="18"
                        height="18"
                        rx="5"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                      />

                      <circle
                        cx="12"
                        cy="12"
                        r="4"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                      />

                      <circle
                        cx="17.2"
                        cy="6.8"
                        r="1.2"
                        fill="currentColor"
                      />

                    </svg>

                    </span>
                    {{ channelLabel(item.channel) }}
                  </span>

                </div>


                <p>
                  {{
                    conversationPreview(
                      item
                    )
                  }}
                </p>

              </div>

            </button>

          </div>


          <div class="conversation-footer">

            Hiển thị
            {{ filtered.length }}
            cuộc trò chuyện

          </div>

        </aside>


        <!-- =================================================
             CHAT
        ================================================== -->

        <section class="chat chat-shell">


          <template v-if="selected">


            <!-- CHAT HEADER -->

            <header class="chat-head">

              <button
                ref="mobileInboxTrigger"
                type="button"
                class="mobile-inbox-trigger"
                aria-controls="crm-inbox-panel"
                aria-label="Quay lại danh sách hội thoại"
                @click="openMobileInbox"
              >←</button>


              <div class="chat-person">


                <div class="avatar avatar-lg">

                  <img
                    v-if="
                      resolvedAvatarUrl(selected)
                    "
                    :src="
                      resolvedAvatarUrl(selected)
                    "
                    :alt="
                      nameOf(selected)
                    "
                    @error="markAvatarFailed(selected)"
                  />

                  <span v-else>
                    {{ initials(selected) }}
                  </span>

                </div>


                <div>


                  <h2 ref="chatHeading" tabindex="-1">

                    {{ nameOf(selected) }}

                    <span>
                      ☆
                    </span>

                  </h2>


                  <p>

                    <span
                      class="social-icon"
                      :class="
                        selected.channel
                      "
                    >

                      <svg
                        v-if="
                          selected.channel
                          === 'facebook'
                        "
                        viewBox="0 0 24 24"
                      >

                        <path
                          fill="currentColor"
                          d="
                            M13.6 22v-9h3
                            l.5-3.5h-3.5V7.2
                            c0-1 .3-1.8 1.8-1.8
                            h1.9V2.3
                            c-.3 0-1.5-.1-2.8-.1
                            -2.8 0-4.7 1.7-4.7 4.8
                            v2.5H6.7V13h3.1v9h3.8Z
                          "
                        />

                      </svg>


                      <svg
                        v-else
                        viewBox="0 0 24 24"
                      >

                        <rect
                          x="3"
                          y="3"
                          width="18"
                          height="18"
                          rx="5"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                        />

                        <circle
                          cx="12"
                          cy="12"
                          r="4"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                        />

                        <circle
                          cx="17.2"
                          cy="6.8"
                          r="1.2"
                          fill="currentColor"
                        />

                      </svg>

                    </span>


                    {{
                      channelLabel(
                        selected.channel
                      )
                    }}

                    ·

                    {{
                      selected.status
                      === "open"
                      ? "Khách hàng mới"
                      : selected.status
                    }}

                  </p>

                </div>

              </div>


              <div class="chat-tools">

                <button
                  ref="mobileCustomerTrigger"
                  type="button"
                  class="mobile-customer-trigger"
                  aria-controls="customer-360-panel"
                  :aria-expanded="String(mobileCustomerOpen)"
                  aria-label="Mở hồ sơ khách hàng 360"
                  @click="openMobileCustomer"
                >360</button>

                <button
                  type="button"
                  class="bot-mode-button"
                  :class="{ human: selectedBotMode === 'human' }"
                  :title="selectedBotMode === 'human' ? 'Bật lại chatbot' : 'Nhân viên tiếp quản'"
                  @click="toggleBotMode"
                >
                  {{ selectedBotMode === 'human' ? 'Bật bot' : 'Tắt bot' }}
                </button>

                <label class="conversation-assignment" title="Gán hội thoại">
                  <span>Phụ trách</span>
                  <select
                    :value="selected.assigned_user_id || ''"
                    @change="reassignConversation(selected, $event.target.value)"
                  >
                    <option value="">Chưa phân công</option>
                    <option v-for="member in activeTeamUsers" :key="member.id" :value="member.id">
                      {{ member.full_name }}
                    </option>
                  </select>
                </label>

                <button
                  type="button"
                  title="Thao tác hội thoại"
                  aria-label="Thao tác hội thoại"
                  :aria-expanded="conversationActionsOpen"
                  @click="toggleConversationActions"
                >⋮</button>
                <button
                  type="button"
                  title="Đánh dấu ưu tiên"
                  aria-label="Đánh dấu ưu tiên"
                  :class="{ active: conversationPriorityActive }"
                  :aria-pressed="conversationPriorityActive"
                  @click="toggleConversationPriority"
                >!</button>
                <button
                  type="button"
                  title="Ghim hội thoại"
                  aria-label="Ghim hội thoại"
                  :class="{ active: conversationFavoriteActive }"
                  :aria-pressed="conversationFavoriteActive"
                  @click="toggleConversationFavorite"
                >♡</button>

                <div v-if="conversationActionsOpen" class="conversation-actions-popover" role="menu">
                  <button type="button" role="menuitem" @click="refreshSelectedConversation">Làm mới hội thoại</button>
                  <button type="button" role="menuitem" @click="saveSelectedConversationSample">Lưu làm mẫu trả lời</button>
                  <button type="button" role="menuitem" @click="toggleConversationActions">Đóng menu</button>
                </div>

              </div>

            </header>


            <!-- =================================================
                 MESSAGES
            ================================================== -->

            <div class="messages-scroll chat-timeline">


              <div class="today">
                Hôm nay
              </div>


              <div
                v-if="loading"
                class="loading"
              >
                Đang tải tin nhắn...
              </div>


              <div
                v-for="message in messages"

                :key="
                  message.message_id
                "

                class="msg-line"

                :class="
                  message.direction
                "
              >


                <!-- CUSTOMER AVATAR -->

                <div
                  v-if="
                    message.direction
                    === 'inbound'
                  "

                  class="
                    avatar
                    avatar-sm
                  "
                >

                  <img
                    v-if="
                      resolvedAvatarUrl(selected)
                    "

                    :src="
                      resolvedAvatarUrl(selected)
                    "

                    :alt="
                      nameOf(selected)
                    "
                    @error="markAvatarFailed(selected)"
                  />

                  <span v-else>
                    {{
                      initials(
                        selected
                      )
                    }}
                  </span>

                </div>


                <!-- BUBBLE -->

                <div
                  class="bubble"
                  :class="{
                    'bubble-with-audio': Array.isArray(message.attachments)
                      && message.attachments.some(isAudioAttachment),
                  }"
                >

                  <!-- CANONICAL MEDIA LIST -->
                  <div
                    v-if="Array.isArray(message.attachments) && message.attachments.length"
                    class="message-attachments"
                  >
                    <template v-for="(attachment, attachmentIndex) in message.attachments" :key="attachment.id || `${message.message_id}-attachment-${attachmentIndex}`">
                      <a
                        v-if="isImageAttachment(attachment)"
                        :href="attachmentUrl(attachment)"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="message-media-link"
                      >
                        <img
                          :src="attachmentUrl(attachment)"
                          :alt="attachmentMediaType(attachment) === 'sticker' ? 'Nhãn dán' : 'Ảnh'"
                          class="message-image"
                        />
                      </a>
                      <audio
                        v-else-if="isAudioAttachment(attachment)"
                        :src="attachmentUrl(attachment)"
                        controls
                        class="message-audio"
                      ></audio>
                      <video
                        v-else-if="isVideoAttachment(attachment)"
                        :src="attachmentUrl(attachment)"
                        controls
                        class="message-video"
                      ></video>
                      <a
                        v-else-if="attachmentUrl(attachment)"
                        :href="attachmentUrl(attachment)"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="message-attachment"
                      >
                        📎 Mở tệp đính kèm
                      </a>
                    </template>
                  </div>


                  <!-- IMAGE -->

                  <a
                    v-if="
                      !(message.attachments && message.attachments.length)
                      && hasImage(
                        message
                      )
                    "

                    :href="
                      mediaUrl(
                        message
                      )
                    "

                    target="_blank"

                    rel="
                      noopener
                      noreferrer
                    "

                    class="
                      message-media-link
                    "
                  >

                    <img
                      :src="
                        mediaUrl(
                          message
                        )
                      "

                      alt="Ảnh"

                      class="
                        message-image
                      "
                    />

                  </a>


                  <!-- VIDEO -->

                  <video
                    v-else-if="
                      !(message.attachments && message.attachments.length)
                      && hasVideo(
                        message
                      )
                    "

                    :src="
                      mediaUrl(
                        message
                      )
                    "

                    controls

                    class="
                      message-video
                    "
                  />


                  <!-- OTHER FILE -->

                  <a
                    v-else-if="
                      !(message.attachments && message.attachments.length)
                      && mediaUrl(
                        message
                      )
                    "

                    :href="
                      mediaUrl(
                        message
                      )
                    "

                    target="_blank"

                    class="
                      message-attachment
                    "
                  >

                    📎 Mở tệp đính kèm

                  </a>


                  <!-- TEXT -->

                  <p
                    v-if="
                      message.content
                    "

                    class="
                      message-text
                    "
                  >

                    {{
                      message.content
                    }}

                  </p>


                  <!-- FALLBACK -->

                  <p
                    v-else-if="
                      !mediaUrl(
                        message
                      )
                    "

                    class="
                      message-text
                    "
                  >

                    {{
                      mediaFallback(
                        message
                      )
                    }}

                  </p>


                  <small>

                    {{
                      formatTime(
                        message.received_at
                      )
                    }}


                    <b
                      v-if="
                        message.direction
                        === 'outbound'
                        &&
                        message.status
                        !== 'sending'
                        &&
                        message.status
                        !== 'failed'
                      "
                    >
                      ✓✓
                    </b>

                    <b
                      v-if="
                        message.status
                        === 'sending'
                      "
                    >
                      đang gửi
                    </b>

                    <button
                      v-if="
                        message.status
                        === 'failed'
                      "
                      class="retry-message"
                      @click="
                        retryMessage(
                          message
                        )
                      "
                    >
                      gửi lại
                    </button>

                  </small>

                </div>


                <span
                  v-if="message.direction === 'outbound'"
                  class="brand-mini"
                  aria-label="Smart Merchant Hub"
                >SM</span>

              </div>

            </div>


            <!-- =================================================
                 COMPOSER
            ================================================== -->

            <footer class="composer chat-composer">


              <div class="composer-tabs">

                <button
                  type="button"
                  :class="{ active: composerMode === 'reply' }"
                  @click="setComposerMode('reply')"
                >
                  Trả lời
                </button>

                <button
                  type="button"
                  :class="{ active: composerMode === 'internal' }"
                  @click="setComposerMode('internal')"
                >
                  Ghi chú nội bộ
                </button>

              </div>


              <!-- TEXTAREA -->

              <textarea
                v-model="draft"

                :placeholder="composerMode === 'internal' ? 'Ghi chú nội bộ...' : 'Nhập tin nhắn...'"

                @paste="
                  handlePaste
                "

                @keydown.enter.exact.prevent="
                  sendComposerContent
                "
              />


              <!-- MEDIA PREVIEW -->

              <div
                v-if="
                  pendingMedia.length
                "

                class="
                  image-preview-box
                "
                role="list"
                aria-label="Tệp đang chờ gửi"
              >

                <div class="composer-attachment-grid">

                  <div
                    v-for="media in pendingMedia"
                    :key="media.id"
                    class="composer-attachment-item"
                    role="listitem"
                  >

                    <div class="composer-attachment-visual">

                      <img
                        v-if="media.mediaType === 'image' || media.mediaType === 'sticker'"
                        :src="media.preview"
                        :alt="media.mediaType === 'sticker' ? 'Nhãn dán chuẩn bị gửi' : 'Ảnh chuẩn bị gửi'"
                      />

                      <audio
                        v-else-if="media.mediaType === 'audio'"
                        :src="media.preview"
                        controls
                        class="composer-media-player"
                      />

                      <video
                        v-else-if="media.mediaType === 'video'"
                        :src="media.preview"
                        controls
                        class="composer-media-player composer-video-preview"
                      />

                      <div v-else class="composer-file-preview">
                        📎
                      </div>

                      <button
                        type="button"
                        class="image-preview-remove"
                        title="Xóa media"
                        aria-label="Xóa media"
                        @click="removePendingMedia(media.id)"
                      >
                        ×
                      </button>

                    </div>

                  </div>

                </div>

              </div>


              <!-- HIDDEN FILE INPUT -->

              <input
                ref="fileInput"

                type="file"
                multiple

                accept="image/*,audio/*,video/*,.pdf,.zip,.rar,.7z,.csv,.txt,.doc,.docx,.xls,.xlsx,.ppt,.pptx"

                class="
                  hidden-file-input
                "

                @change="
                  handleFileChange
                "
              />


              <div class="composer-bottom">


                <div class="left-actions">

                  <button
                    type="button"
                    title="Thêm emoji"
                    aria-label="Thêm emoji"
                    @click="insertComposerEmoji"
                  >
                    ☺
                  </button>


                  <!-- IMAGE BUTTON -->

                  <button
                    type="button"

                    title="Chọn ảnh, audio, video hoặc file"

                    @click="
                      openImagePicker
                    "
                  >

                    📎

                  </button>


                  <button
                    type="button"
                    class="voice-record-button"
                    :class="{ recording: voiceRecording }"
                    :disabled="composerMode === 'internal' || sending"
                    :title="voiceRecording ? 'Dừng ghi âm' : 'Ghi âm'"
                    :aria-label="voiceRecording ? 'Dừng ghi âm' : 'Ghi âm'"
                    :aria-pressed="voiceRecording"
                    @click="toggleVoiceRecording"
                  >
                    <span aria-hidden="true">{{ voiceRecording ? "■" : "🎙" }}</span>
                  </button>

                  <span
                    v-if="voiceRecording"
                    class="voice-recording-status"
                    role="status"
                    aria-live="polite"
                  >
                    {{ formatVoiceRecordingTime(voiceRecordingSeconds) }}
                  </span>


                  <button
                    type="button"
                    title="Ghim hội thoại"
                    aria-label="Ghim hội thoại"
                    :class="{ active: conversationFavoriteActive }"
                    :aria-pressed="conversationFavoriteActive"
                    @click="toggleConversationFavorite"
                  >
                    ♡
                  </button>


                  <button
                    type="button"
                    class="
                      template
                    "
                    title="Chèn mẫu trả lời"
                    @click="insertReplyTemplate"
                  >
                    Mẫu trả lời
                  </button>

                  <select
                    v-if="cannedResponses.length"
                    v-model="selectedCannedId"
                    class="canned-response-select"
                    title="Chọn mẫu trả lời đã lưu"
                    @change="applyCannedResponse"
                  >
                    <option value="">Chọn mẫu...</option>
                    <option v-for="item in cannedResponses" :key="item.id" :value="item.id">{{ item.shortcut }} · {{ item.title }}</option>
                  </select>

                </div>


                <div class="right-actions">


                  <button
                    type="button"
                    class="
                      send
                    "

                    :disabled="
                      composerMode === 'internal'
                      ? !draft.trim()
                      : (
                          !draft.trim()
                          &&
                          !pendingMedia.length
                        )
                      ||
                      sending
                      ||
                      sendingImage
                    "

                    @click="
                      sendComposerContent
                    "
                  >

                    {{
                      sending
                      ? "Đang gửi..."
                      : composerMode === 'internal'
                      ? "Lưu ghi chú"
                      : pendingMedia.length
                      ? `➤ Gửi ${pendingMedia.length} tệp`
                        : "➤ Gửi phản hồi"
                    }}

                  </button>

                </div>

              </div>


            </footer>

          </template>


          <!-- EMPTY CHAT -->

          <div
            v-else
            class="
              empty-chat
            "
          >

            <div class="empty-chat-mark" aria-hidden="true">
              <span>SM</span>
              <i></i><i></i><i></i>
            </div>

            <span class="empty-chat-kicker">SMART MERCHANT HUB</span>

            <h2>
              {{ conversations.length ? "Chọn một hội thoại để bắt đầu" : "Hộp thư sẵn sàng cho khách hàng đầu tiên" }}
            </h2>

            <p>
              {{ conversations.length ? "Chọn khách hàng bên trái để xem toàn bộ tin nhắn, đơn hàng và hồ sơ khách hàng 360." : "Kết nối kênh bán hàng để tin nhắn, hồ sơ khách hàng 360 và lịch sử mua sắm được tập trung tại một nơi." }}
            </p>

            <div class="empty-chat-steps" aria-label="Các bước bắt đầu sử dụng hộp thư">
              <span><b>1</b>Kết nối kênh</span>
              <span><b>2</b>Nhận tin nhắn</span>
              <span><b>3</b>Chăm sóc khách hàng</span>
            </div>

          </div>

        </section>


        <!-- =================================================
             CUSTOMER PANEL
        ================================================== -->

        <aside id="customer-360-panel" class="customer customer-panel-scroll" :class="{ 'customer-collapsed': customerPanelCollapsed }" aria-label="Hồ sơ khách hàng 360">

          <div class="customer-title">

            <h3>
              Hồ sơ khách hàng 360
            </h3>

            <button
              ref="mobileCustomerClose"
              type="button"
              class="mobile-panel-close"
              aria-label="Đóng hồ sơ khách hàng 360"
              @click="closeMobileCustomer"
            >×</button>

            <button
              type="button"
              :aria-expanded="String(!customerPanelCollapsed)"
              :aria-label="customerPanelCollapsed ? 'Mở rộng thông tin khách hàng' : 'Thu gọn thông tin khách hàng'"
              :title="customerPanelCollapsed ? 'Mở rộng thông tin khách hàng' : 'Thu gọn thông tin khách hàng'"
              @click="toggleCustomerPanel"
            >
              {{ customerPanelCollapsed ? '⌄' : '⌃' }}
            </button>

          </div>

          <template v-if="selected">


            <div class="customer-profile">


              <div
                class="
                  avatar
                  customer-avatar
                "
              >

                <img
                  v-if="
                    resolvedAvatarUrl(selected)
                  "

                  :src="
                    resolvedAvatarUrl(selected)
                  "

                  :alt="
                    nameOf(selected)
                  "
                  @error="markAvatarFailed(selected)"
                />

                <span v-else>

                  {{
                    initials(
                      selected
                    )
                  }}

                </span>

              </div>


              <div>


                <h3>
                  {{
                    maskCustomerName(nameOf(
                      customer360 || selected
                    ))
                  }}
                </h3>


                <p>

                  <span
                    class="
                      social-icon
                    "

                    :class="
                      selected.channel
                    "
                  >

                    <svg
                      v-if="
                        selected.channel
                        === 'facebook'
                      "

                      viewBox="
                        0 0 24 24
                      "
                    >

                      <path
                        fill="
                          currentColor
                        "

                        d="
                          M13.6 22v-9h3
                          l.5-3.5h-3.5V7.2
                          c0-1 .3-1.8 1.8-1.8
                          h1.9V2.3
                          c-.3 0-1.5-.1-2.8-.1
                          -2.8 0-4.7 1.7-4.7 4.8
                          v2.5H6.7V13h3.1v9h3.8Z
                        "
                      />

                    </svg>


                    <svg
                      v-else

                      viewBox="
                        0 0 24 24
                      "
                    >

                      <rect
                        x="3"
                        y="3"
                        width="18"
                        height="18"
                        rx="5"

                        fill="none"

                        stroke="
                          currentColor
                        "

                        stroke-width="2"
                      />

                      <circle
                        cx="12"
                        cy="12"
                        r="4"

                        fill="none"

                        stroke="
                          currentColor
                        "

                        stroke-width="2"
                      />

                      <circle
                        cx="17.2"
                        cy="6.8"
                        r="1.2"

                        fill="
                          currentColor
                        "
                      />

                    </svg>

                  </span>


                  {{
                    channelLabel(
                      selected.channel
                    )
                  }}

                </p>

                <span
                  class="customer-bot-status"
                  :class="conversationBotStatus(selectedBotMode).kind"
                  :title="conversationBotStatus(selectedBotMode).description"
                >
                  <i aria-hidden="true"></i>
                  {{ conversationBotStatus(selectedBotMode).label }}
                </span>


                <small>

                  ID:
                  {{
                    selected.external_user_id
                  }}

                </small>

                <small v-if="customer360?.email" class="customer-profile-email">
                  Email: {{ maskCustomerEmail(customer360.email) }}
                </small>

              </div>

            </div>


            <div v-if="customer360Loading" class="customer-360-loading">
              Đang tải hồ sơ khách hàng...
            </div>

            <div v-else-if="customer360Error" class="customer-360-error" role="alert">
              <strong>Không thể tải hồ sơ khách hàng</strong>
              <span>{{ customer360Error }}</span>
              <button type="button" class="table-action-btn" @click="loadCustomer360(selected?.customer_id)">Thử lại</button>
            </div>

            <div v-else-if="customer360" class="customer-360-data">
              <div class="section customer-identities-section">
                <div class="section-head">
                  <h4>Danh tính đa kênh</h4>
                  <span>{{ customer360.identities.length }}</span>
                </div>
                <div class="customer-identities">
                  <div
                    v-for="identity in customer360.identities"
                    :key="identity.id"
                    class="customer-identity-row"
                  >
                    <span class="social-icon" :class="identity.channel"></span>
                    <span>{{ channelLabel(identity.channel) }}</span>
                    <small>{{ identity.external_user_id }}</small>
                  </div>
                </div>
              </div>

              <div class="section customer-contact-section">
                <div class="section-head">
                  <h4>Thông tin nhận hàng</h4>
                  <span>{{ customer360PrimaryContacts.length + customer360VisibleAddresses.length }}</span>
                </div>
                <div class="customer-contact-grid">
                  <div class="customer-contact-card customer-profile-contact-card">
                    <small>Thông tin khách hàng</small>
                    <div class="customer-profile-fields">
                      <div class="customer-profile-field">
                        <span>Tên</span>
                        <strong>{{ maskCustomerName(customer360.name || nameOf(selected)) }}</strong>
                      </div>
                      <div class="customer-profile-field">
                        <span>Email</span>
                        <strong>{{ maskCustomerEmail(customer360.email || customerContactValue('email')) || 'Chưa thu thập' }}</strong>
                      </div>
                      <div class="customer-profile-field">
                        <span>Số điện thoại</span>
                        <strong>{{ maskCustomerPhone(customer360.phone || customerContactValue('phone')) || 'Chưa thu thập' }}</strong>
                      </div>
                    </div>
                    <div v-if="customer360PrimaryContacts.length" class="customer-contact-status-list">
                      <div v-for="contact in customer360PrimaryContacts" :key="contact.id" class="customer-contact-status-row">
                        <span>{{ contact.kind === 'phone' ? 'Số điện thoại' : 'Email' }}</span>
                        <em>{{ contact.verification_status === 'verified' ? 'Đã xác minh' : 'Chưa xác minh' }}</em>
                      </div>
                    </div>
                  </div>
                  <div class="customer-contact-card">
                    <small>Địa chỉ giao hàng</small>
                    <template v-if="customer360VisibleAddresses.length">
                      <div v-for="address in customer360VisibleAddresses" :key="address.id" class="customer-address-row">
                        <strong v-if="address.is_default">Mặc định</strong>
                        <span>{{ [address.address_line1, address.ward, address.district, address.province].filter(Boolean).join(', ') }}</span>
                      </div>
                    </template>
                    <span v-else class="customer-contact-empty">Chưa thu thập</span>
                  </div>
                </div>
                <div v-if="customer360OverflowCount" class="customer-contact-overflow">
                  <button
                    type="button"
                    class="table-action-btn customer-contact-overflow-toggle"
                    :aria-expanded="customer360OverflowOpen"
                    @click="customer360OverflowOpen = !customer360OverflowOpen"
                  >
                    {{ customer360OverflowOpen ? 'Ẩn thông tin cũ' : `Xem thêm ${customer360OverflowCount} mục` }}
                  </button>
                  <div v-if="customer360OverflowOpen" class="customer-contact-overflow-list">
                    <div v-for="contact in customer360ExtraContacts" :key="`extra-contact-${contact.id}`" class="customer-contact-status-row">
                      <span>{{ contact.kind === 'phone' ? 'Số điện thoại' : 'Email' }} · {{ contact.masked_value || 'Đã lưu' }}</span>
                      <em>{{ contact.verification_status === 'verified' ? 'Đã xác minh' : 'Chưa xác minh' }}</em>
                    </div>
                    <div v-for="address in customer360ExtraAddresses" :key="`extra-address-${address.id}`" class="customer-address-row">
                      <strong>Lịch sử</strong>
                      <span>{{ [address.address_line1, address.ward, address.district, address.province].filter(Boolean).join(', ') }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="section customer-timeline-section">
                <div class="section-head">
                  <h4>Lịch sử tương tác</h4>
                  <span>{{ customer360.timeline.length }} / {{ customer360.timelineTotal }}</span>
                </div>
                <div class="customer-timeline">
                  <div
                    v-for="event in customer360.timeline"
                    :key="`${event.event_type}-${event.event_id}`"
                    class="customer-timeline-row"
                  >
                    <span class="timeline-dot" :class="event.event_type"></span>
                    <div>
                      <small>{{ timelineLabel(event) }}<span v-if="event.channel"> · {{ channelLabel(event.channel) }}</span></small>
                      <p>{{ event.content || 'Sự kiện không có nội dung' }}</p>
                      <small v-if="timelineExplainability(event)" class="timeline-explainability">{{ timelineExplainability(event) }}</small>
                      <small class="customer-timeline-meta">
                        {{ event.occurred_at ? new Date(event.occurred_at).toLocaleString('vi-VN') : 'Không rõ thời gian' }}
                        <span
                          class="timeline-actor"
                          :class="`timeline-actor-${timelineActor(event).kind}`"
                          :title="event.created_by ? `ID nhân viên: ${event.created_by}` : timelineActor(event).label"
                        >{{ timelineActor(event).label }}</span>
                      </small>
                    </div>
                  </div>
                </div>
                <div v-if="customerTimelineError" class="facts-error">{{ customerTimelineError }}</div>
                <button
                  v-if="customer360.timelineHasMore"
                  type="button"
                  class="timeline-load-more"
                  :disabled="customerTimelineLoading"
                  @click="loadMoreCustomerTimeline"
                >
                  {{ customerTimelineLoading ? 'Đang tải...' : 'Tải thêm lịch sử' }}
                </button>
              </div>

              <div class="section customer-facts-section">
                <div class="section-head">
                  <h4>Thông tin đã ghi nhận</h4>
                  <span>{{ customer360.facts?.length || 0 }}</span>
                </div>
                <form class="customer-fact-form" @submit.prevent="addCustomerFact">
                  <input v-model="customerFactDraft.fact_key" maxlength="120" placeholder="Khóa (vd: budget_max)" />
                  <input v-model="customerFactDraft.fact_value" maxlength="500" placeholder="Giá trị (vd: 500000)" />
                  <div class="customer-fact-form-row">
                    <input v-model="customerFactDraft.confidence" type="number" min="0" max="1" step="0.01" aria-label="Độ tin cậy" />
                    <label><input v-model="customerFactDraft.is_verified" type="checkbox" /> Đã xác nhận</label>
                    <button type="submit" :disabled="customerFactSaving">{{ customerFactSaving ? 'Đang lưu...' : 'Ghi nhận' }}</button>
                  </div>
                </form>
                <div v-if="customerFactError" class="facts-error">{{ customerFactError }}</div>
                <div v-if="customer360.facts?.length" class="customer-facts">
                  <div
                    v-for="fact in customer360.facts.slice(0, 8)"
                    :key="fact.id"
                    class="customer-fact-row"
                  >
                    <div class="customer-fact-copy">
                      <strong>{{ fact.fact_key }}</strong>
                      <p>{{ formatFactValue(fact.fact_value) }}</p>
                    </div>
                    <small :class="{ verified: fact.is_verified }">
                      {{ fact.is_verified ? 'Đã xác nhận' : `${Math.round((fact.confidence || 0) * 100)}%` }}
                    </small>
                    <div class="customer-fact-actions">
                      <button type="button" @click="toggleCustomerFact(fact)">{{ fact.is_verified ? 'Bỏ xác nhận' : 'Xác nhận' }}</button>
                      <button type="button" @click="removeCustomerFact(fact)">Xóa</button>
                    </div>
                  </div>
                </div>
                <div v-else class="facts-empty">
                  Chưa có tri thức đã ghi nhận
                </div>
              </div>
            </div>


            <!-- TAGS -->

            <div class="section">

              <div class="section-head">

                <h4>
                  Nhãn khách hàng
                </h4>

              </div>

              <div v-if="customerTagNames(customer360).length" class="tags">
                <span v-for="tag in customerTagNames(customer360)" :key="tag" class="tag-chip">
                  {{ tag }}
                  <button type="button" class="tag-remove" :aria-label="`Xóa tag ${tag}`" @click="removeCustomerTag(tag)">×</button>
                </span>
              </div>
              <div v-else class="tags-empty">
                Chưa có nhãn
              </div>
              <form class="customer-tag-form" @submit.prevent="addCustomerTag">
                <input v-model="customerTagDraft" maxlength="80" placeholder="Thêm nhãn / nhóm khách hàng" />
                <button type="submit" :disabled="customerTagSaving">{{ customerTagSaving ? '...' : 'Gắn nhãn' }}</button>
              </form>
              <div v-if="customerTagError" class="facts-error">{{ customerTagError }}</div>

            </div>

            <div class="section customer-merge-section">
              <div class="section-head">
                <h4>Gộp hồ sơ khách hàng trùng</h4>
              </div>
              <p class="field-hint">Đề xuất trùng và xem điểm tin cậy trước khi chuyển dữ liệu sang khách hiện tại.</p>
              <form class="customer-tag-form" @submit.prevent="mergeSelectedCustomer">
                <select v-model="customerMergeSourceId" aria-label="Hồ sơ nguồn để gộp">
                  <option value="">Chọn hồ sơ trùng</option>
                  <option v-for="candidate in duplicateSuggestions" :key="candidate.source_customer_id" :value="candidate.source_customer_id">
                    #{{ candidate.source_customer_id }} — {{ candidate.source_name || candidate.source_channel }} ({{ Math.round(candidate.confidence_score * 100) }}%)
                  </option>
                </select>
                <button type="button" :disabled="customerMergeSaving" @click="previewSelectedCustomerMerge">Xem trước</button>
                <button type="submit" :disabled="customerMergeSaving">{{ customerMergeSaving ? 'Đang xử lý...' : 'Xác nhận gộp' }}</button>
              </form>
              <div v-if="customerMergePreview" class="merge-preview-card">
                <strong>Độ tin cậy: {{ Math.round(customerMergePreview.confidence_score * 100) }}%</strong>
                <span>{{ customerMergePreview.confidence_label }}</span>
                <small>{{ customerMergePreview.matched_fields.join(', ') || 'Chưa có tín hiệu trùng mạnh' }}</small>
              </div>
              <div v-if="customerMergeError" class="facts-error">{{ customerMergeError }}</div>
              <div v-if="customerMergeHistory.length" class="merge-history">
                <div class="section-head"><h5>Lịch sử merge</h5><span>{{ customerMergeHistory.length }}</span></div>
                <div v-for="merge in customerMergeHistory" :key="merge.merge_id" class="merge-history-row">
                  <div>
                    <strong>#{{ merge.merge_id }} · {{ merge.status === 'undone' ? 'Đã hoàn tác' : 'Đã gộp' }}</strong>
                    <small>{{ merge.confidence_score == null ? 'Không có điểm cũ' : `Tin cậy ${Math.round(merge.confidence_score * 100)}%` }}</small>
                  </div>
                  <button v-if="merge.can_undo" type="button" @click="undoCustomerMerge(merge)">Tách / hoàn tác</button>
                </div>
              </div>
            </div>

            <div class="section customer-segment-section">
              <div class="section-head">
                <h4>Nhóm khách hàng theo nhãn</h4>
                <span>{{ savedSegments.length }}</span>
              </div>
              <form class="segment-form" @submit.prevent="createSavedSegment">
                <input v-model="segmentForm.name" maxlength="160" placeholder="Tên nhóm khách hàng" />
                <input v-model="segmentForm.description" maxlength="2000" placeholder="Mô tả (không bắt buộc)" />
                <select v-model="segmentForm.tag_ids" multiple aria-label="Nhãn của nhóm khách hàng">
                  <option v-for="tag in tagCatalog" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
                </select>
                <label><input v-model="segmentForm.match_mode" type="radio" value="all" /> Có tất cả nhãn</label>
                <label><input v-model="segmentForm.match_mode" type="radio" value="any" /> Có ít nhất một nhãn</label>
                <button type="submit" :disabled="segmentSaving">{{ segmentSaving ? 'Đang lưu...' : (segmentEditingId ? 'Cập nhật nhóm' : 'Lưu nhóm') }}</button>
                <button v-if="segmentEditingId" type="button" :disabled="segmentSaving" @click="cancelSegmentEdit">Hủy sửa</button>
              </form>
              <div v-if="savedSegments.length" class="saved-segment-list">
                <div v-for="segment in savedSegments" :key="segment.id" class="saved-segment-row">
                  <span><strong>{{ segment.name }}</strong><small>{{ segment.customer_count }} khách · {{ segment.match_mode === 'all' ? 'đủ tất cả nhãn' : 'ít nhất một nhãn' }}</small></span>
                  <div class="saved-segment-actions">
                    <button type="button" @click="editSavedSegment(segment)">Sửa</button>
                    <button type="button" @click="deleteSavedSegment(segment)">Xóa</button>
                  </div>
                </div>
              </div>
              <div v-if="segmentError" class="facts-error">{{ segmentError }}</div>
            </div>


            <!-- STATS -->

            <div class="section">

              <div class="section-head">

                <h4>
                  Thống kê hội thoại
                </h4>

              </div>


              <div class="stats">

                <div>

                  <span>
                    Khách gửi
                  </span>

                  <b>
                    {{ inboundCount }}
                  </b>

                </div>


                <div>

                  <span>
                    Shop gửi
                  </span>

                  <b>
                    {{ outboundCount }}
                  </b>

                </div>

              </div>

            </div>


          </template>

          <template v-else>
            <div class="customer-empty-state">
              <div class="customer-empty-avatar" aria-hidden="true">360</div>
              <span class="customer-empty-kicker">HỒ SƠ KHÁCH HÀNG 360</span>
              <h3>Hồ sơ khách hàng sẽ hiện ở đây</h3>
              <p>Chọn một hội thoại để xem nhận diện đa kênh, tag, lịch sử tương tác và đơn gần nhất.</p>
              <div class="customer-empty-points" aria-hidden="true">
                <span>Nhãn &amp; nhóm khách hàng</span>
                <span>Lịch sử tương tác</span>
                <span>Đơn hàng gần nhất</span>
              </div>
            </div>
          </template>

        </aside>

      </section>

      <!-- ===================================================
           SẢN PHẨM (PRODUCT CATALOG)
      ==================================================== -->
      <section v-if="currentTab === 'products'" class="products-layout">
        <div class="products-header">
          <div>
            <h2>Sản phẩm</h2>
            <p>Theo dõi danh mục sản phẩm và xử lý tồn kho của shop.</p>
          </div>
        </div>

        <div
          class="product-import-dropzone upload-dropzone"
          @dragover.prevent
          @drop.prevent="handleProductDrop"
          @click="openProductFilePicker"
        >
          <input
            ref="productFileInput"
            type="file"
            class="hidden-file-input"
            accept=".csv,.txt,text/csv,text/plain"
            @change="handleProductFileSelect"
          />
          <div v-if="!productUploading" class="dropzone-content">
            <span class="upload-icon" aria-hidden="true">NHẬP DANH MỤC</span>
            <strong>Nhập tệp sản phẩm để cập nhật nhanh danh mục</strong>
            <small>CSV hoặc TXT · Tối đa 20MB · Cột cần có: Mã sản phẩm, Tên sản phẩm, Giá, Tồn kho</small>
            <button type="button" class="secondary-btn import-choice" @click.stop="openProductFilePicker">Nhập tệp</button>
          </div>
          <div v-else class="dropzone-content" role="status" aria-live="polite">
            <span class="spinner-icon" aria-hidden="true">...</span>
            <strong>Đang nhập danh mục sản phẩm...</strong>
          </div>
        </div>

        <div v-if="productUploadNotice" class="product-import-notice" role="status">{{ productUploadNotice }}</div>
        <div v-if="productError" class="product-error">{{ productError }}</div>

        <div class="operation-mode-banner" data-testid="products-processing-only">
          <strong>Chế độ xử lý sản phẩm</strong>
          <span>Danh mục sản phẩm được đồng bộ từ nguồn dữ liệu shop. Tại đây chỉ xử lý tồn kho, trạng thái và lưu trữ.</span>
        </div>

        <div v-if="productsLoading" class="products-empty">Đang tải sản phẩm...</div>
        <div v-else-if="!products.length" class="products-empty">Chưa có sản phẩm nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table">
            <thead><tr><th>Mã sản phẩm</th><th>Sản phẩm</th><th>Giá</th><th>Tồn kho</th><th>Điều chỉnh tồn</th><th>Trạng thái</th><th></th></tr></thead>
            <tbody>
              <template v-for="product in products" :key="product.id">
                <tr>
                  <td><strong>{{ product.sku }}</strong></td>
                  <td><div>{{ product.name }}</div><small>{{ product.description || 'Không có mô tả' }}</small></td>
                  <td>{{ Number(product.price).toLocaleString('vi-VN') }}đ</td>
                  <td class="inventory-cell">
                    <div class="inventory-summary">
                      <div class="inventory-total">
                        <span>Tồn kho</span>
                        <strong>{{ product.stock_quantity }}</strong>
                      </div>
                      <div class="inventory-available">
                        <span>Khả dụng</span>
                        <strong>{{ Math.max(0, Number(product.stock_quantity || 0) - Number(product.reserved_quantity || 0)) }}</strong>
                      </div>
                    </div>
                    <small v-if="Number(product.reserved_quantity || 0) > 0" class="inventory-reserved">Đang giữ {{ product.reserved_quantity }}</small>
                  </td>
                  <td class="inventory-adjustment-cell">
                    <button type="button" class="adjustment-trigger" :class="{ active: inventoryAdjustmentOpen === product.id }" @click="inventoryAdjustmentOpen === product.id ? closeInventoryAdjustment() : openInventoryAdjustment(product)">
                      {{ inventoryAdjustmentOpen === product.id ? 'Đóng điều chỉnh' : 'Điều chỉnh' }}
                    </button>
                    <small>Ghi vào sổ điều chỉnh</small>
                  </td>
                  <td><span class="product-status" :class="product.status">{{ product.status === 'active' ? 'Đang bán' : 'Lưu trữ' }}</span></td>
                  <td class="product-actions"><button v-if="product.status === 'active'" type="button" @click="archiveProduct(product)">Lưu trữ</button></td>
                </tr>
                <tr v-if="inventoryAdjustmentOpen === product.id" class="inventory-adjustment-row">
                  <td colspan="7">
                    <div class="inventory-adjustment-panel">
                      <div class="inventory-adjustment-heading">
                        <div>
                          <strong>Điều chỉnh tồn kho · {{ product.name }}</strong>
                          <div class="inventory-adjustment-current">
                            <span><small>Tồn hiện tại</small><b>{{ product.stock_quantity }}</b></span>
                            <span><small>Khả dụng</small><b>{{ Math.max(0, Number(product.stock_quantity || 0) - Number(product.reserved_quantity || 0)) }}</b></span>
                            <span><small>Đang giữ</small><b>{{ Number(product.reserved_quantity || 0) }}</b></span>
                          </div>
                        </div>
                        <button type="button" class="panel-close-btn" @click="closeInventoryAdjustment">×</button>
                      </div>
                      <div class="adjustment-direction" role="group" aria-label="Loại điều chỉnh">
                        <button type="button" :class="{ active: Number(productAdjustmentDrafts[product.id].direction) > 0 }" @click="openInventoryAdjustment(product, 1)">Nhập thêm (+)</button>
                        <button type="button" :class="{ active: Number(productAdjustmentDrafts[product.id].direction) < 0 }" @click="openInventoryAdjustment(product, -1)">Ghi giảm (−)</button>
                      </div>
                      <div class="adjustment-fields">
                        <label>Số lượng<input v-model.number="productAdjustmentDrafts[product.id].quantity" type="number" min="1" step="1" aria-label="Số lượng điều chỉnh" /></label>
                        <label>Lý do điều chỉnh<input v-model="productAdjustmentDrafts[product.id].reason" maxlength="1000" placeholder="Ví dụ: kiểm kê, hỏng hàng, nhập bổ sung..." aria-label="Lý do điều chỉnh tồn" /></label>
                        <div class="adjustment-preview"><span>Tồn sau điều chỉnh</span><strong>{{ inventoryAdjustmentPreview(product) }}</strong></div>
                      </div>
                      <div class="adjustment-actions"><small>Số lượng gửi: {{ inventoryAdjustmentSignedQuantity(product) > 0 ? '+' : '' }}{{ inventoryAdjustmentSignedQuantity(product) }}</small><button type="button" class="primary-btn" :disabled="productAdjustmentSaving[product.id]" @click="adjustProductInventory(product)">{{ productAdjustmentSaving[product.id] ? 'Đang ghi...' : 'Ghi điều chỉnh' }}</button></div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===================================================
           SALES PIPELINE (LEADS)
      ==================================================== -->
      <section v-if="currentTab === 'leads'" class="products-layout leads-layout">
        <div class="products-header">
          <div>
            <h2>Luồng bán hàng</h2>
            <p>Theo dõi cơ hội bán hàng từ khách hội thoại đến chuyển đổi.</p>
          </div>
        </div>

        <div v-if="leadError" class="product-error">{{ leadError }}</div>

        <div class="pipeline-summary">
          <div v-for="stage in ['new', 'qualified', 'proposal', 'won', 'lost']" :key="stage" class="pipeline-card">
            <span>{{ leadStageLabel(stage) }}</span>
            <strong>{{ (pipelineSummary.find(item => item.stage === stage) || {}).lead_count || 0 }}</strong>
            <small>{{ Number((pipelineSummary.find(item => item.stage === stage) || {}).value || 0).toLocaleString('vi-VN') }}đ</small>
          </div>
        </div>

        <form class="product-form lead-form" @submit.prevent="saveLead">
          <div class="product-form-title">
            Tạo cơ hội mới
            <button type="button" @click="resetLeadForm">Làm mới</button>
          </div>
          <div class="product-form-grid">
            <label>Tên cơ hội<input v-model="leadForm.title" required maxlength="255" placeholder="Ví dụ: Khách quan tâm combo" /></label>
            <label>Khách hàng
              <select v-model="leadForm.customer_id" required>
                <option value="" disabled>Chọn khách hàng</option>
                <option v-for="customer in orderCustomers" :key="customer.id" :value="customer.id">
                  #{{ customer.id }} — {{ customerOptionLabel(customer) }}
                </option>
              </select>
            </label>
            <label>Giai đoạn<select v-model="leadForm.stage"><option value="new">Mới</option><option value="qualified">Đã xác định nhu cầu</option><option value="proposal">Đã gửi đề xuất</option><option value="won">Đã chốt</option><option value="lost">Không thành công</option></select></label>
            <label>Giá trị dự kiến<input v-model.number="leadForm.value" type="number" min="0" step="1" /></label>
            <label>Xác suất (%)<input v-model.number="leadForm.probability" type="number" min="0" max="100" step="1" /></label>
            <label>Mã hội thoại (không bắt buộc)<input v-model="leadForm.conversation_id" type="number" min="1" /></label>
          </div>
          <button class="primary-btn" type="submit" :disabled="leadSaving">{{ leadSaving ? 'Đang tạo...' : 'Tạo cơ hội' }}</button>
        </form>

        <div v-if="leadsLoading" class="products-empty">Đang tải luồng bán hàng...</div>
        <div v-else-if="!leads.length" class="products-empty">Chưa có cơ hội nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table leads-table">
            <thead><tr><th>Cơ hội</th><th>Khách hàng</th><th>Kênh</th><th>Giai đoạn</th><th>Giá trị</th><th>Xác suất</th><th>Cập nhật</th><th>Thao tác</th></tr></thead>
            <tbody>
              <template v-for="lead in leads" :key="lead.id">
              <tr>
                <td><strong>{{ lead.title }}</strong></td>
                <td>#{{ lead.customer_id }} {{ lead.customer_name || '' }}</td>
                <td>{{ lead.source_channel || '—' }}</td>
                <td><select class="inline-stage" :value="lead.stage" @change="changeLeadStage(lead, $event.target.value)"><option value="new">Mới</option><option value="qualified">Đã xác định nhu cầu</option><option value="proposal">Đã gửi đề xuất</option><option value="won">Đã chốt</option><option value="lost">Không thành công</option></select></td>
                <td>{{ Number(lead.value || 0).toLocaleString('vi-VN') }}đ</td>
                <td>{{ lead.probability }}%</td>
                <td>{{ lead.updated_at ? new Date(lead.updated_at).toLocaleDateString('vi-VN') : '—' }}</td>
                <td class="lead-actions"><button type="button" class="table-link" @click="toggleLeadActivities(lead)">{{ leadActivityVisible[lead.id] ? 'Ẩn hoạt động' : 'Hoạt động' }}</button></td>
              </tr>
              <tr v-if="leadActivityVisible[lead.id]" class="lead-detail-row">
                <td colspan="8">
                  <div class="lead-detail">
                    <div class="lead-detail-header"><strong>Hoạt động & chuyển đổi</strong><span v-if="leadActivityLoading[lead.id]">Đang tải...</span></div>
                    <div class="lead-activity-list" v-if="(leadActivities[lead.id] || []).length">
                      <div v-for="activity in leadActivities[lead.id]" :key="activity.id" class="lead-activity"><b>{{ activity.subject }}</b><small>{{ leadActivityTypeLabel(activity.activity_type) }} · {{ activity.occurred_at ? new Date(activity.occurred_at).toLocaleString('vi-VN') : '—' }}</small></div>
                    </div>
                    <div v-else class="settings-empty">Chưa có hoạt động.</div>
                    <form class="lead-activity-form" @submit.prevent="addLeadActivity(lead)">
                      <input :value="leadActivityDrafts[lead.id] || ''" @input="setLeadActivityDraft(lead.id, $event.target.value)" placeholder="Ghi chú cuộc gọi, email, hẹn gặp..." maxlength="255" />
                      <button class="table-link" type="submit">Ghi hoạt động</button>
                    </form>
                    <div v-if="lead.stage !== 'won'" class="lead-conversion-form">
                      <select v-model="leadConversionOrders[lead.id]">
                        <option value="">Chọn đơn để chuyển đổi</option>
                        <option v-for="order in orders.filter(item => item.customer_id === lead.customer_id)" :key="order.id" :value="order.id">{{ order.order_number || `Đơn #${order.id}` }} · {{ Number(order.total_amount || order.total || 0).toLocaleString('vi-VN') }}đ</option>
                      </select>
                      <button class="primary-btn" type="button" :disabled="leadConversionSaving[lead.id]" @click="convertLead(lead)">{{ leadConversionSaving[lead.id] ? 'Đang lưu...' : 'Ghi nhận chuyển đổi' }}</button>
                    </div>
                  </div>
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===================================================
           CSKH / PHIẾU HỖ TRỢ + THỜI HẠN
      ==================================================== -->
      <section v-if="currentTab === 'tickets'" class="products-layout tickets-layout">
        <div class="products-header">
          <div>
            <h2>Phiếu hỗ trợ &amp; thời hạn xử lý</h2>
            <p>Tiếp nhận, phân công và theo dõi thời hạn xử lý vấn đề của khách.</p>
          </div>
        </div>

        <div v-if="ticketError" class="product-error">{{ ticketError }}</div>

        <div v-if="slaNotifications.length" class="sla-alert">
          Có {{ slaNotifications.length }} phiếu hỗ trợ đã quá hạn cần xử lý.
        </div>

        <div class="ticket-summary">
          <div class="ticket-stat"><span>Tổng phiếu</span><strong>{{ ticketReport.total_tickets || 0 }}</strong></div>
          <div class="ticket-stat overdue"><span>Quá hạn</span><strong>{{ ticketReport.overdue_tickets || 0 }}</strong></div>
          <div v-for="item in ticketReport.items || []" :key="item.status" class="ticket-stat"><span>{{ ticketStatusLabel(item.status) }}</span><strong>{{ item.ticket_count }}</strong></div>
        </div>

        <form class="product-form ticket-form" @submit.prevent="saveTicket">
          <div class="product-form-title">
            Tạo phiếu hỗ trợ
            <button type="button" @click="resetTicketForm">Làm mới</button>
          </div>
          <div class="product-form-grid">
            <label>Tiêu đề<input v-model="ticketForm.title" required maxlength="255" placeholder="Ví dụ: Khách chưa nhận được hàng" /></label>
            <label>Khách hàng
              <select v-model="ticketForm.customer_id" required @change="onTicketCustomerChange">
                <option value="" disabled>Chọn khách hàng</option>
                <option v-for="customer in orderCustomers" :key="customer.id" :value="customer.id">
                  #{{ customer.id }} — {{ customerOptionLabel(customer) }}
                </option>
              </select>
            </label>
            <label>Ưu tiên<select v-model="ticketForm.priority"><option value="low">Thấp</option><option value="normal">Bình thường</option><option value="high">Cao</option><option value="urgent">Khẩn cấp</option></select></label>
            <label>Hội thoại (không bắt buộc)
              <select v-model="ticketForm.conversation_id">
                <option value="">Không gắn hội thoại</option>
                <option v-for="conversation in ticketConversations" :key="conversation.conversation_id" :value="conversation.conversation_id">
                  #{{ conversation.conversation_id }} — {{ channelLabel(conversation.channel) }} — {{ conversationPreview(conversation) }}
                </option>
              </select>
              <small class="field-hint">Chỉ hiển thị hội thoại của khách hàng đang chọn.</small>
            </label>
            <label>Nhân viên phụ trách
              <select v-model="ticketForm.assigned_user_id">
                <option value="">Chưa phân công</option>
                <option v-for="member in activeTeamUsers" :key="member.id" :value="member.id">
                  {{ member.full_name }} — {{ member.role }}
                </option>
              </select>
            </label>
            <label class="product-description">Mô tả<textarea v-model="ticketForm.description" rows="2"></textarea></label>
          </div>
          <button class="primary-btn" type="submit" :disabled="ticketSaving">{{ ticketSaving ? 'Đang tạo...' : 'Tạo phiếu hỗ trợ' }}</button>
        </form>

        <div v-if="ticketsLoading" class="products-empty">Đang tải phiếu hỗ trợ...</div>
        <div v-else-if="!tickets.length" class="products-empty">Chưa có phiếu hỗ trợ nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table tickets-table">
            <thead><tr><th>Phiếu hỗ trợ</th><th>Mô tả</th><th>Khách hàng</th><th>Kênh</th><th>Ưu tiên</th><th>Trạng thái</th><th>Thời hạn</th><th>Phụ trách</th></tr></thead>
            <tbody>
              <template v-for="ticket in tickets" :key="ticket.id">
              <tr>
                <td><strong>#{{ ticket.id }} — {{ ticket.title }}</strong></td>
                <td class="ticket-description-cell">{{ ticket.description || '—' }}</td>
                <td>#{{ ticket.customer_id }} {{ ticket.customer_name || '' }}</td>
                <td>{{ ticket.channel || '—' }}</td>
                <td><span class="product-status" :class="ticket.priority">{{ ticketPriorityLabel(ticket.priority) }}</span></td>
                <td><select class="inline-stage" :value="ticket.status" @change="changeTicketStatus(ticket, $event.target.value)"><option value="open">Đang mở</option><option value="pending">Đang chờ</option><option value="resolved">Đã xử lý</option><option value="closed">Đã đóng</option></select></td>
                <td>{{ ticket.sla_due_at ? new Date(ticket.sla_due_at).toLocaleString('vi-VN') : '—' }}</td>
                <td>
                  <select class="inline-stage" :value="ticket.assigned_user_id || ''" @change="assignTicket(ticket, $event.target.value)">
                    <option value="">Chưa phân công</option>
                    <option v-for="member in activeTeamUsers" :key="member.id" :value="member.id">{{ member.full_name }}</option>
                  </select>
                  <button class="history-btn" type="button" @click="loadTicketHistory(ticket)">
                    {{ ticketHistoryLoading[ticket.id] ? 'Đang tải...' : (ticketHistory[ticket.id] ? 'Ẩn lịch sử' : 'Lịch sử') }}
                  </button>
                </td>
              </tr>
              <tr v-if="ticketHistory[ticket.id]" class="ticket-history-row">
                <td colspan="8">
                    <strong>Lịch sử phiếu hỗ trợ #{{ ticket.id }}</strong>
                  <span v-if="!ticketHistory[ticket.id].length"> Chưa có sự kiện.</span>
                  <ul v-else>
                    <li v-for="event in ticketHistory[ticket.id]" :key="event.id">
                      {{ ticketHistoryEventLabel(event.event_type) }} · {{ event.created_at ? new Date(event.created_at).toLocaleString('vi-VN') : '—' }}
                      <span v-if="event.from_value || event.to_value">({{ event.from_value || '—' }} → {{ event.to_value || '—' }})</span>
                    </li>
                  </ul>
                  <div class="ticket-comment-form">
                    <input v-model="ticketCommentDrafts[ticket.id]" maxlength="10000" placeholder="Ghi chú xử lý nội bộ..." @keyup.enter="addTicketComment(ticket)" />
                    <button type="button" @click="addTicketComment(ticket)">Thêm ghi chú</button>
                  </div>
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===================================================
           ĐƠN HÀNG + DOANH THU (SALES CRM)
      ==================================================== -->
      <section v-if="currentTab === 'orders'" class="products-layout orders-layout">
        <div class="products-header">
          <div>
            <h2>Đơn bán</h2>
            <p>Theo dõi và xử lý đơn bán; doanh thu được gắn với kênh hội thoại.</p>
          </div>
        </div>

        <div v-if="orderError" class="product-error">{{ orderError }}</div>

        <div class="revenue-cards">
          <div class="revenue-card total">
            <span>Tổng doanh thu</span>
            <strong>{{ Number(revenueByChannel.reduce((sum, item) => sum + Number(item.revenue || 0), 0)).toLocaleString('vi-VN') }}đ</strong>
          </div>
          <div v-for="item in revenueByChannel" :key="item.channel" class="revenue-card">
            <span>{{ item.channel === 'unknown' ? 'Không gắn kênh' : item.channel }}</span>
            <strong>{{ Number(item.revenue || 0).toLocaleString('vi-VN') }}đ</strong>
            <small>{{ item.order_count }} đơn</small>
          </div>
        </div>

        <div class="operation-mode-banner" data-testid="orders-processing-only">
          <strong>Chế độ xử lý đơn bán</strong>
          <span>Đơn được tạo từ hộp thư hoặc luồng trợ lý. Màn hình này chỉ xử lý trạng thái, thanh toán, vận chuyển và lịch sử.</span>
        </div>

        <div v-if="ordersLoading" class="products-empty">Đang tải đơn hàng...</div>
        <div v-else-if="!orders.length" class="products-empty">Chưa có đơn hàng nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table orders-table">
            <thead><tr><th>Mã đơn</th><th>Khách hàng</th><th>SĐT khách</th><th>Sản phẩm</th><th>Kênh</th><th>Trạng thái</th><th>Quy trình</th><th>Thanh toán</th><th>Tổng tiền</th><th>Ngày tạo</th></tr></thead>
            <tbody>
              <tr v-for="order in orders" :key="order.id">
                <td><strong>{{ order.order_number }}</strong></td>
                <td>#{{ order.customer_id }}<small>{{ orderCustomerName(order.customer_id) }}</small></td>
                <td class="order-phone-cell">{{ orderCustomerPhone(order.customer_id) }}</td>
                <td><span v-for="(item, index) in order.items" :key="item.id">{{ index ? ', ' : '' }}{{ item.product_name }} ×{{ item.quantity }}<small v-if="order.status === 'draft'"> (còn {{ availableProductQuantity(item.product_id) }})</small></span></td>
                <td>{{ order.channel || 'Không gắn kênh' }}</td>
                <td>
                  <select class="inline-stage" :value="order.status" :disabled="orderTransitionSaving[order.id]" @change="transitionSalesOrder(order, $event.target.value)">
                    <option v-for="status in salesStatusOptions(order)" :key="status" :value="status">{{ salesOrderStatusLabel(status) }}</option>
                  </select>
                  <button v-if="order.status === 'draft'" type="button" class="table-action-btn" :disabled="!orderCanConfirm(order) || orderTransitionSaving[order.id]" @click.stop="transitionSalesOrder(order, 'confirmed')">{{ orderTransitionSaving[order.id] ? 'Đang cập nhật...' : 'Xác nhận đơn' }}</button>
                  <small v-if="order.status === 'draft' && !orderCanConfirm(order)" class="stock-warning">Thiếu tồn khả dụng</small>
                </td>
                <td><button type="button" class="table-action-btn" data-testid="order-history-button" title="Xem toàn bộ quy trình" aria-label="Xem toàn bộ quy trình" @click.stop="loadSalesOrderEvents(order)">Quy trình</button><small>Nhật ký bất biến</small></td>
                <td class="order-payment-cell">
                  <span class="product-status" :class="order.payment_status">{{ paymentStatusLabel(order.payment_status) }}</span>
                  <small>{{ Number(order.paid_amount || 0).toLocaleString('vi-VN') }}đ / {{ Number(order.total_amount || 0).toLocaleString('vi-VN') }}đ</small>
                  <div class="order-payment-actions">
                    <input v-model.number="orderPaymentDrafts[order.id]" type="number" min="0.01" step="0.01" placeholder="Số tiền" />
                    <button type="button" :disabled="orderPaymentSaving[order.id]" aria-label="Ghi nhận thanh toán" title="Ghi nhận thanh toán" @click="recordSalesPayment(order)">Thu</button>
                    <button type="button" :disabled="orderPaymentSaving[order.id]" aria-label="Ghi nhận hoàn tiền" title="Ghi nhận hoàn tiền" @click="recordSalesPayment(order, 'refund')">Hoàn</button>
                  </div>
                </td>
                <td><strong>{{ Number(order.total_amount || 0).toLocaleString('vi-VN') }}đ</strong></td>
                <td>{{ order.created_at ? new Date(order.created_at).toLocaleString('vi-VN') : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="selectedOrderEvents" class="report-panel order-events-panel" data-testid="order-events-panel">
          <div class="report-panel-header"><div><h3>Toàn bộ quy trình {{ selectedOrderEvents.order.order_number }}</h3><p>Nhật ký bất biến theo thời gian; thao tác nhầm vẫn được lưu để đối soát, không rollback.</p></div><button type="button" class="settings-refresh" @click="selectedOrderEvents = null">Đóng</button></div>
          <form class="order-logistics-card" data-testid="order-logistics-card" @submit.prevent="updateOrderLogistics(selectedOrderEvents.order)">
            <div class="order-logistics-heading"><div><strong>Thông tin vận chuyển</strong><small>Chỉ lưu thông tin giao hàng để nhân viên và hệ thống vận hành cùng theo dõi.</small></div><span class="logistics-status" :class="orderLogisticsDraft.shipping_status">{{ shippingStatusLabel(orderLogisticsDraft.shipping_status) }}</span></div>
            <div class="order-logistics-grid">
              <label>Đơn vị vận chuyển<input v-model="orderLogisticsDraft.shipping_provider" maxlength="80" placeholder="GHN, GHTK, J&amp;T..." /></label>
              <label>Mã vận đơn<input v-model="orderLogisticsDraft.tracking_code" maxlength="160" placeholder="Nhập mã vận đơn" /></label>
              <label>Trạng thái<select v-model="orderLogisticsDraft.shipping_status"><option value="pending">Chưa bàn giao</option><option value="in_transit">Đang vận chuyển</option><option value="delivered">Đã giao</option><option value="failed">Giao thất bại</option><option value="returned">Đã hoàn</option></select></label>
            </div>
            <div class="order-logistics-actions"><span v-if="selectedOrderEvents.order.shipping_updated_at" class="field-hint">Cập nhật: {{ new Date(selectedOrderEvents.order.shipping_updated_at).toLocaleString('vi-VN') }}</span><button class="table-action-btn" type="submit" :disabled="orderLogisticsSaving">{{ orderLogisticsSaving ? 'Đang lưu...' : 'Lưu vận chuyển' }}</button></div>
          </form>
          <div v-if="orderEventsLoading" class="products-empty">Đang tải lịch sử...</div>
              <div v-else-if="!selectedOrderEvents.items?.length" class="products-empty">Chưa có sự kiện nào.</div>
          <ol v-else class="order-events-list"><li v-for="event in chronologicalOrderEvents(selectedOrderEvents.items)" :key="event.id"><strong>{{ orderEventLabel(event) }}</strong><span>{{ orderEventSummary(event) }}</span><small>{{ event.created_at ? new Date(event.created_at).toLocaleString('vi-VN') : '—' }}</small></li></ol>
        </div>
      </section>

      <!-- ===================================================
           PURCHASE ORDERS (SUPPLIER / SHOP PROCUREMENT)
      ==================================================== -->
      <section v-if="currentTab === 'purchase-orders'" class="products-layout orders-layout purchase-orders-layout">
        <div class="products-header">
          <div>
            <h2>Đơn nhập hàng / dịch vụ</h2>
            <p>Quản lý đơn shop mua từ nhà cung cấp, tách biệt với đơn bán cho khách cuối.</p>
          </div>
        </div>

        <div v-if="purchaseOrderError" class="product-error">{{ purchaseOrderError }}</div>

        <form class="product-form order-form" @submit.prevent="savePurchaseOrder">
          <div class="product-form-title">
            Tạo phiếu nhập hàng
            <button type="button" @click="resetPurchaseOrderForm">Làm mới</button>
          </div>
          <div class="product-form-grid">
            <label>Mã phiếu nhập<input v-model="purchaseOrderForm.po_number" required maxlength="80" /></label>
            <label>Nhà cung cấp
              <select v-model="purchaseOrderForm.supplier_id" :disabled="suppliersLoading">
                <option value="">Nhập tên thủ công</option>
                <option v-for="supplier in suppliers" :key="supplier.id" :value="String(supplier.id)">{{ supplier.name }}{{ supplier.code ? ` · ${supplier.code}` : '' }}</option>
              </select>
              <input v-if="!purchaseOrderForm.supplier_id" v-model="purchaseOrderForm.supplier_name" required maxlength="255" placeholder="Tên nhà cung cấp" />
              <small v-else>Đã chọn nhà cung cấp đang hoạt động</small>
            </label>
            <label>Sản phẩm / dịch vụ
              <select v-model="purchaseOrderForm.product_id" required>
                <option value="" disabled>Chọn sản phẩm</option>
                <option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</option>
              </select>
            </label>
            <label>Số lượng<input v-model.number="purchaseOrderForm.quantity" type="number" min="1" step="1" required /></label>
            <label>Đơn giá nhập<input v-model.number="purchaseOrderForm.unit_cost" type="number" min="0" step="1" required /></label>
            <label class="product-description">Ghi chú<textarea v-model="purchaseOrderForm.notes" rows="2" placeholder="Gói dịch vụ, kỳ thanh toán..."></textarea></label>
          </div>
          <button class="primary-btn" type="submit" :disabled="purchaseOrderSaving">{{ purchaseOrderSaving ? 'Đang tạo...' : 'Tạo phiếu nhập' }}</button>
        </form>

        <details class="supplier-manager">
          <summary>Quản lý nhà cung cấp</summary>
          <form class="supplier-form" @submit.prevent="saveSupplier">
            <input v-model="supplierForm.code" required maxlength="80" placeholder="Mã nhà cung cấp" />
            <input v-model="supplierForm.name" required maxlength="255" placeholder="Tên nhà cung cấp" />
            <button class="table-action-btn" type="submit" :disabled="supplierSaving">{{ supplierSaving ? 'Đang lưu...' : 'Thêm nhà cung cấp' }}</button>
          </form>
          <div v-if="suppliersLoading" class="products-empty">Đang tải nhà cung cấp...</div>
          <div v-else-if="!suppliers.length" class="products-empty">Chưa có nhà cung cấp đang hoạt động.</div>
          <ul v-else class="supplier-list"><li v-for="supplier in suppliers" :key="supplier.id"><strong>{{ supplier.name }}</strong><small>{{ supplier.code }}</small></li></ul>
        </details>

        <div v-if="purchaseOrdersLoading" class="products-empty">Đang tải đơn nhập...</div>
        <div v-else-if="!purchaseOrders.length" class="products-empty">Chưa có phiếu nhập nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table orders-table">
            <thead><tr><th>Mã PO</th><th>Nhà cung cấp</th><th>Mặt hàng</th><th>Trạng thái</th><th>Thanh toán</th><th>Tổng chi</th><th>Cập nhật</th><th></th></tr></thead>
            <tbody>
              <tr v-for="purchase in purchaseOrders" :key="purchase.id">
                <td><strong>{{ purchase.po_number }}</strong></td>
                <td>{{ purchase.supplier_name }}</td>
                <td><span v-for="(item, index) in purchase.items" :key="item.id" class="purchase-line"><span>{{ index ? ', ' : '' }}{{ item.product_name }} ×{{ item.received_quantity || 0 }} / {{ item.quantity }}</span><input v-if="['submitted', 'partially_received'].includes(purchase.status) && Number(item.quantity || 0) > Number(item.received_quantity || 0)" v-model.number="purchaseReceiptDrafts[item.id]" type="number" min="1" :max="Math.max(1, Number(item.quantity || 0) - Number(item.received_quantity || 0))" aria-label="Số lượng nhận" /></span></td>
                <td>
                  <select class="inline-stage" :value="purchase.status" @change="transitionPurchaseOrder(purchase, $event.target.value)">
                    <option v-for="status in purchaseStatuses" :key="status" :value="status" :disabled="['partially_received', 'received'].includes(status)">{{ purchaseStatusLabel(status) }}</option>
                  </select>
                  <button v-if="['submitted', 'partially_received'].includes(purchase.status)" type="button" class="table-action-btn" @click="receivePurchaseOrder(purchase)">Nhận hàng</button>
                </td>
                <td class="order-payment-cell"><span class="product-status" :class="purchase.payment_status">{{ paymentStatusLabel(purchase.payment_status || 'unpaid') }}</span><small>{{ Number(purchase.paid_amount || 0).toLocaleString('vi-VN') }}đ / {{ Number(purchase.total_spend || 0).toLocaleString('vi-VN') }}đ</small><div class="order-payment-actions"><input v-model.number="purchasePaymentDrafts[purchase.id]" type="number" min="0.01" step="0.01" placeholder="Số tiền" /><button type="button" :disabled="purchasePaymentSaving[purchase.id]" @click="recordPurchasePayment(purchase)">Thanh toán công nợ</button></div></td>
                <td><strong>{{ Number(purchase.total_spend || 0).toLocaleString('vi-VN') }}đ</strong></td>
                <td>{{ purchase.updated_at ? new Date(purchase.updated_at).toLocaleString('vi-VN') : '—' }}</td>
                <td><button type="button" class="table-action-btn" data-testid="purchase-order-history-button" @click.stop="loadPurchaseOrderEvents(purchase)">Lịch sử</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="selectedPurchaseOrderEvents" class="order-events-panel" data-testid="purchase-order-events-panel">
          <div class="product-form-title">
            <span>Lịch sử {{ selectedPurchaseOrderEvents.purchase?.po_number || 'phiếu nhập' }}</span>
            <button type="button" @click="selectedPurchaseOrderEvents = null">Đóng</button>
          </div>
          <div v-if="purchaseOrderEventsLoading" class="products-empty">Đang tải lịch sử...</div>
          <div v-else-if="!selectedPurchaseOrderEvents.items?.length" class="products-empty">Chưa có sự kiện.</div>
          <ol v-else class="order-events-list">
            <li v-for="event in selectedPurchaseOrderEvents.items" :key="event.id">
              <strong>{{ purchaseOrderEventLabel(event) }}</strong>
              <span>{{ purchaseOrderEventSummary(event) }}</span>
              <small>{{ event.created_at ? new Date(event.created_at).toLocaleString('vi-VN') : '—' }}</small>
            </li>
          </ol>
        </div>
      </section>

      <!-- ===================================================
           QUY TRÌNH TỰ ĐỘNG
      =================================================== -->
      <section v-if="currentTab === 'workflows'" class="products-layout workflow-layout">
        <div class="products-header">
          <div>
            <h2>Quy trình tự động</h2>
            <p>Tự động hóa các bước CRM theo sự kiện, có điều kiện và lịch sử chạy.</p>
          </div>
        </div>

        <div v-if="workflowError" class="product-error">{{ workflowError }}</div>

        <form class="product-form workflow-form" @submit.prevent="saveWorkflow">
          <div class="product-form-title">
            Tạo quy trình
            <button type="button" @click="resetWorkflowForm">Làm mới</button>
          </div>
          <div class="product-form-grid">
            <label>Tên quy trình<input v-model="workflowForm.name" required maxlength="160" placeholder="Ví dụ: Gắn nhãn khách Telegram" /></label>
            <label>Sự kiện<select v-model="workflowForm.event_type"><option value="message.created">Tin nhắn mới</option><option value="ticket.created">Phiếu hỗ trợ được tạo</option><option value="ticket.status_changed">Phiếu hỗ trợ đổi trạng thái</option><option value="lead.stage_changed">Cơ hội đổi giai đoạn</option><option value="order.created">Đơn hàng được tạo</option></select></label>
            <label>Điều kiện kênh<select v-model="workflowForm.condition_channel"><option value="">Mọi kênh</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="telegram">Telegram</option><option value="zalo">Zalo</option></select></label>
            <label>Hành động<select v-model="workflowForm.action_type"><option value="create_ticket">Tạo phiếu hỗ trợ</option><option value="add_tag">Gắn nhãn</option><option value="assign_user">Chuyển người hỗ trợ và gửi email</option></select></label>
            <label v-if="workflowForm.action_type === 'create_ticket'">Tiêu đề phiếu hỗ trợ<input v-model="workflowForm.action_title" maxlength="255" placeholder="Nhắc chăm sóc khách" /></label>
            <label v-if="workflowForm.action_type === 'create_ticket'">Ưu tiên<select v-model="workflowForm.action_priority"><option value="low">Thấp</option><option value="normal">Bình thường</option><option value="high">Cao</option><option value="urgent">Khẩn cấp</option></select></label>
            <label v-if="workflowForm.action_type === 'add_tag'">Tên nhãn<input v-model="workflowForm.action_tag" maxlength="80" placeholder="khach-than-thiet" /></label>
            <label v-if="workflowForm.action_type === 'assign_user'">Nhân viên nhận thông báo<select v-model="workflowForm.action_user_id"><option value="">Chọn nhân viên</option><option v-for="member in activeTeamUsers" :key="member.id" :value="member.id">{{ member.full_name }} — {{ roleLabel(member.role) }}</option></select></label>
            <p v-if="workflowForm.action_type === 'assign_user'" class="workflow-email-note">Khi quy trình chạy, cuộc trò chuyện sẽ được chuyển cho nhân viên này, tạo phiếu nếu cần và gửi thông báo vào email tài khoản của họ.</p>
          </div>
          <button class="primary-btn" type="submit" :disabled="workflowSaving">{{ workflowSaving ? 'Đang tạo...' : 'Tạo quy trình' }}</button>
        </form>

        <div v-if="workflowsLoading" class="products-empty">Đang tải quy trình...</div>
        <div v-else-if="!workflows.length" class="products-empty">Chưa có quy trình nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table workflow-table">
            <thead><tr><th>Quy trình</th><th>Sự kiện</th><th>Điều kiện</th><th>Hành động</th><th>Trạng thái</th><th></th></tr></thead>
            <tbody>
              <template v-for="workflow in workflows" :key="workflow.id">
              <tr>
                <td><strong>{{ workflow.name }}</strong><small>#{{ workflow.id }}</small></td>
                <td>{{ workflowEventLabel(workflow.event_type) }}</td>
                <td>{{ workflow.conditions.channel ? `Kênh: ${channelLabel(workflow.conditions.channel)}` : 'Mọi kênh' }}</td>
                <td>{{ workflowActionLabel(workflow.actions[0]?.type) }}</td>
                <td><span class="team-status" :class="{ inactive: !workflow.enabled }">{{ workflow.enabled ? 'Đang bật' : 'Đã tắt' }}</span></td>
                <td>
                  <button type="button" class="team-toggle" @click="toggleWorkflow(workflow)">{{ workflow.enabled ? 'Tắt' : 'Bật' }}</button>
                  <button type="button" class="history-btn" @click="toggleWorkflowRuns(workflow)">{{ workflowRunsLoading[workflow.id] ? 'Đang tải...' : (workflowRuns[workflow.id] ? 'Ẩn lần chạy' : 'Lịch sử') }}</button>
                </td>
              </tr>
              <tr v-if="workflowRuns[workflow.id]" class="ticket-history-row">
                <td colspan="6">
                  <span v-if="!workflowRuns[workflow.id].length">Chưa có lần chạy.</span>
                  <ul v-else>
                    <li v-for="run in workflowRuns[workflow.id]" :key="run.id">
                      #{{ run.id }} · {{ workflowRunStatusLabel(run.status) }} · lần {{ run.attempts || 1 }}
                      <button v-if="run.status === 'failed'" type="button" class="history-btn" @click="retryWorkflowRun(workflow, run)">Chạy lại</button>
                    </li>
                  </ul>
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===================================================
           AI RECOMMENDATIONS / EXPERIMENTS
      ==================================================== -->
      <section v-if="currentTab === 'experiments'" class="products-layout experiments-layout">
        <div class="products-header">
          <div>
            <span class="page-kicker">Trợ lý &amp; tự động hóa</span>
            <h2>Tự động hóa &amp; đo lường</h2>
            <p>Kiểm tra đề xuất của trợ lý, duyệt trước khi áp dụng và theo dõi hiệu quả từng cách chăm sóc khách hàng.</p>
          </div>
          <button class="primary-btn" type="button" @click="fetchExperimentation">Làm mới dữ liệu</button>
        </div>

        <div v-if="experimentationError" class="product-error">{{ experimentationError }}</div>
        <div v-if="experimentationLoading" class="products-empty">Đang tải dữ liệu thử nghiệm...</div>

        <div v-else class="ai-lab-content">
          <div class="ai-lab-summary">
            <div class="ai-stat-card ai-stat-primary"><span>Tổng đề xuất</span><strong>{{ ruleSuggestions.length }}</strong><small>Đề xuất đã ghi nhận</small></div>
            <div class="ai-stat-card"><span>Chờ duyệt</span><strong>{{ ruleSuggestions.filter(item => item.status === 'pending').length }}</strong><small>Cần người kiểm tra</small></div>
            <div class="ai-stat-card"><span>Đã duyệt</span><strong>{{ ruleSuggestions.filter(item => item.status === 'accepted').length }}</strong><small>Sẵn sàng đưa vào quy trình</small></div>
            <div class="ai-stat-card"><span>Thử nghiệm</span><strong>{{ experiments.length }}</strong><small>Đang theo dõi</small></div>
          </div>

          <div class="ai-board-card ai-quality-dashboard">
            <div class="ai-board-header"><div><span class="card-eyebrow">THEO DÕI CHẤT LƯỢNG</span><h3>Bảng chất lượng trợ lý</h3><p>Tín hiệu chất lượng trong {{ aiEvaluationDashboard.period_days || 30 }} ngày gần nhất, chỉ hiển thị dữ liệu của shop hiện tại.</p></div><span class="count-badge">{{ aiEvaluationDashboard.models?.training_runs || 0 }} lần chạy</span></div>
            <div class="ai-lab-summary ai-quality-grid">
              <div class="ai-stat-card"><span>Tỷ lệ chuyển đổi</span><strong>{{ ((aiEvaluationDashboard.experiments?.conversion_rate || 0) * 100).toFixed(1) }}%</strong><small>{{ aiEvaluationDashboard.experiments?.outcomes || 0 }} kết quả / {{ aiEvaluationDashboard.experiments?.exposures || 0 }} lượt thử</small></div>
              <div class="ai-stat-card"><span>Lần tra cứu thông tin</span><strong>{{ aiEvaluationDashboard.rag?.runs || 0 }}</strong><small>{{ Object.entries(aiEvaluationDashboard.rag?.by_status || {}).map(([key, value]) => `${key}: ${value}`).join(' · ') || 'Chưa có dữ liệu' }}</small></div>
              <div class="ai-stat-card"><span>Phiên bản trợ lý sẵn sàng</span><strong>{{ aiEvaluationDashboard.models?.completed_runs || 0 }}</strong><small>lần cập nhật hoàn tất</small></div>
              <div class="ai-stat-card"><span>Tỷ lệ chuyển nhân viên</span><strong>{{ ((aiEvaluationDashboard.ai?.handoff?.rate || 0) * 100).toFixed(1) }}%</strong><small>{{ aiEvaluationDashboard.ai?.handoff?.count || 0 }} lượt chuyển nhân viên</small></div>
              <div class="ai-stat-card"><span>Phản hồi trùng</span><strong>{{ aiEvaluationDashboard.ai?.reliability?.duplicate_reply_attempts || 0 }}</strong><small>{{ ((aiEvaluationDashboard.ai?.reliability?.duplicate_reply_rate || 0) * 100).toFixed(1) }}% trên phản hồi tự động</small></div>
              <div class="ai-stat-card"><span>Đơn chốt tự động</span><strong>{{ ((aiEvaluationDashboard.commerce?.conversion_rate || 0) * 100).toFixed(1) }}%</strong><small>{{ aiEvaluationDashboard.commerce?.confirmed || 0 }} đơn xác nhận / {{ aiEvaluationDashboard.commerce?.started || 0 }} đơn bắt đầu</small></div>
              <div class="ai-stat-card"><span>Doanh thu cứu lại</span><strong>{{ Number(aiEvaluationDashboard.commerce?.recovered_revenue || 0).toLocaleString('vi-VN') }}đ</strong><small>{{ aiEvaluationDashboard.commerce?.recovered_orders || 0 }} đơn sau nhắc chăm sóc</small></div>
              <div class="ai-stat-card"><span>Trợ lý tự xử lý</span><strong>{{ ((aiEvaluationDashboard.commerce?.bot_resolution_rate || 0) * 100).toFixed(1) }}%</strong><small>Hội thoại được giải quyết không cần chuyển nhân viên</small></div>
            </div>
          </div>

          <div class="ai-compose-grid">
            <form class="ai-compose-card" @submit.prevent="createRuleSuggestion">
              <div class="ai-card-heading"><div><span class="card-eyebrow">DUYỆT THỦ CÔNG</span><h3>Tạo đề xuất tự động</h3></div><span class="ai-card-icon">R</span></div>
              <p class="ai-card-help">Trợ lý chỉ đề xuất. Cách xử lý chỉ được dùng sau khi bạn duyệt.</p>
              <label class="ai-field">Tiêu đề đề xuất<input v-model="aiRuleForm.title" required maxlength="255" placeholder="Ví dụ: Gắn nhãn khách hỏi giá" /></label>
              <label class="ai-field">Lý do đề xuất<textarea v-model="aiRuleForm.rationale" required maxlength="5000" rows="3" placeholder="Mô tả tín hiệu và lợi ích của cách xử lý..."></textarea></label>
              <div class="ai-field-grid">
                <label class="ai-field">Hành động<select v-model="aiRuleForm.action_type"><option value="add_tag">Gắn nhãn</option><option value="create_ticket">Tạo phiếu hỗ trợ</option><option value="assign_user">Chuyển người hỗ trợ và gửi email</option></select></label>
                <label class="ai-field" v-if="aiRuleForm.action_type === 'add_tag'">Tên nhãn<input v-model="aiRuleForm.action_tag" maxlength="80" placeholder="khach-than-thiet" /></label>
                <label class="ai-field" v-if="aiRuleForm.action_type === 'create_ticket'">Tiêu đề phiếu hỗ trợ<input v-model="aiRuleForm.action_title" maxlength="255" placeholder="Nhắc chăm sóc khách" /></label>
                <label class="ai-field" v-if="aiRuleForm.action_type === 'create_ticket'">Ưu tiên<select v-model="aiRuleForm.action_priority"><option value="low">Thấp</option><option value="normal">Bình thường</option><option value="high">Cao</option><option value="urgent">Khẩn cấp</option></select></label>
                <label class="ai-field" v-if="aiRuleForm.action_type === 'assign_user'">Nhân viên<select v-model="aiRuleForm.action_user_id"><option value="">Chọn nhân viên</option><option v-for="member in activeTeamUsers" :key="member.id" :value="member.id">{{ member.full_name }}</option></select></label>
              </div>
              <label class="ai-field">Quy trình liên kết <select v-model="aiRuleForm.workflow_id"><option value="">Chưa liên kết</option><option v-for="workflow in workflows" :key="workflow.id" :value="workflow.id">{{ workflow.name }}</option></select></label>
              <div class="ai-form-actions"><button type="button" class="secondary-btn" @click="resetAiRuleForm">Xóa biểu mẫu</button><button class="primary-btn" type="submit" :disabled="aiRuleSaving">{{ aiRuleSaving ? 'Đang lưu...' : 'Lưu đề xuất' }}</button></div>
            </form>

            <form class="ai-compose-card" @submit.prevent="createExperiment">
              <div class="ai-card-heading"><div><span class="card-eyebrow">ĐO LƯỜNG TRƯỚC KHI ÁP DỤNG</span><h3>Tạo thử nghiệm</h3></div><span class="ai-card-icon ai-card-icon-alt">A/B</span></div>
              <p class="ai-card-help">Tách biến thể bằng dấu phẩy hoặc xuống dòng để đo hiệu quả trước khi tự động hóa.</p>
              <label class="ai-field">Tên thử nghiệm<input v-model="experimentForm.name" required maxlength="160" placeholder="Ví dụ: Mẫu trả lời giá" /></label>
              <label class="ai-field">Các biến thể<textarea v-model="experimentForm.variants" required rows="4" placeholder="A\nB"></textarea></label>
              <label class="ai-field">Trạng thái ban đầu<select v-model="experimentForm.status"><option value="draft">Bản nháp</option><option value="running">Đang chạy</option><option value="paused">Tạm dừng</option></select></label>
              <div class="ai-field-grid"><label class="ai-field">Mẫu tối thiểu / cách thử<input v-model.number="experimentForm.min_sample_size" min="0" type="number" /></label><label class="ai-field">Dừng khi tỷ lệ chuyển đổi đạt<input v-model.number="experimentForm.target_conversion_rate" min="0" max="1" step="0.01" type="number" placeholder="VD: 0.15" /></label></div>
              <div class="ai-form-actions"><button type="button" class="secondary-btn" @click="resetExperimentForm">Xóa biểu mẫu</button><button class="primary-btn" type="submit" :disabled="experimentSaving">{{ experimentSaving ? 'Đang tạo...' : 'Tạo thử nghiệm' }}</button></div>
            </form>

            <form class="ai-compose-card" @submit.prevent="createModelVersion">
              <div class="ai-card-heading"><div><span class="card-eyebrow">PHIÊN BẢN DỰ ĐOÁN</span><h3>Phiên bản trợ lý</h3></div><span class="ai-card-icon">ML</span></div>
              <p class="ai-card-help">Lưu phiên bản trước, sau đó huấn luyện bằng dữ liệu đã có nhãn để đánh giá rõ ràng.</p>
              <label class="ai-field">Tên phiên bản<input v-model="modelForm.name" required maxlength="120" /></label>
              <div class="ai-field-grid"><label class="ai-field">Phiên bản<input v-model="modelForm.version" required maxlength="40" /></label><label class="ai-field">Phiên bản dữ liệu<input v-model="modelForm.feature_version" required maxlength="40" /></label></div>
              <label class="ai-field">Mục tiêu<input v-model="modelForm.target" required maxlength="120" placeholder="tỷ lệ chuyển đổi" /></label>
              <div class="ai-form-actions"><button class="primary-btn" type="submit" :disabled="modelSaving">{{ modelSaving ? 'Đang lưu...' : 'Tạo phiên bản' }}</button></div>
            </form>
          </div>

          <div class="ai-board-card">
            <div class="ai-board-header"><div><span class="card-eyebrow">HÀNG ĐỢI ĐỀ XUẤT</span><h3>Đề xuất tự động</h3><p>Kiểm tra lý do và cách xử lý trước khi chấp nhận.</p></div><div class="ai-filter-tabs"><button v-for="filter in [{ value: 'pending', label: 'Chờ duyệt' }, { value: 'accepted', label: 'Đã duyệt' }, { value: 'rejected', label: 'Từ chối' }, { value: 'all', label: 'Tất cả' }]" :key="filter.value" type="button" :class="{ active: ruleSuggestionFilter === filter.value }" @click="ruleSuggestionFilter = filter.value">{{ filter.label }} <span>{{ filter.value === 'all' ? ruleSuggestions.length : ruleSuggestions.filter(item => item.status === filter.value).length }}</span></button></div></div>
            <div v-if="!filteredRuleSuggestions.length" class="ai-empty-state"><strong>Chưa có đề xuất ở bộ lọc này</strong><span>Tạo một đề xuất mới để bắt đầu vòng duyệt.</span></div>
            <div v-else class="ai-rule-list">
              <article v-for="suggestion in filteredRuleSuggestions" :key="suggestion.id" class="ai-rule-card">
                <div class="ai-rule-main"><div class="ai-rule-title-row"><strong>{{ suggestion.title }}</strong><span class="ai-status-pill" :class="`status-${suggestion.status}`">{{ ruleStatusLabel(suggestion.status) }}</span></div><p>{{ suggestion.rationale }}</p><div class="ai-rule-meta"><span class="ai-action-chip">{{ ruleActionLabel(suggestion.proposed_action) }}</span><span v-if="suggestion.workflow_id">Quy trình #{{ suggestion.workflow_id }}</span><span v-if="suggestion.created_at">{{ formatTime(suggestion.created_at) }}</span></div></div>
                <div v-if="suggestion.status === 'pending'" class="suggestion-actions"><button type="button" class="ai-approve-btn" @click="reviewRuleSuggestion(suggestion, 'accepted')">Duyệt đề xuất</button><button type="button" class="ai-reject-btn" @click="reviewRuleSuggestion(suggestion, 'rejected')">Từ chối</button></div>
              </article>
            </div>
          </div>

          <div class="ai-board-card">
            <div class="ai-board-header"><div><span class="card-eyebrow">KHO PHIÊN BẢN</span><h3>Phiên bản &amp; đánh giá trợ lý</h3><p>Phiên bản chỉ chuyển sang sẵn sàng sau khi cập nhật; chỉ số kiểm tra được lưu kèm.</p></div><span class="count-badge">{{ modelVersions.length }}</span></div>
            <div v-if="!modelVersions.length" class="ai-empty-state"><strong>Chưa có phiên bản trợ lý</strong><span>Tạo phiên bản đầu tiên để quản lý lịch sử cập nhật.</span></div>
            <div v-else class="ai-experiment-list"><article v-for="model in modelVersions" :key="model.id" class="ai-experiment-card"><div><strong>{{ model.name }} · {{ model.version }}</strong><span>Dữ liệu {{ model.feature_version }} → {{ model.target }}</span></div><span class="ai-status-pill" :class="`status-${model.status}`">{{ modelStatusLabel(model.status) }}</span><small v-if="model.artifact?.metrics">Độ lệch kiểm tra {{ model.artifact.metrics.mae ?? '—' }} · số mẫu kiểm tra {{ model.artifact.metrics.holdout_count ?? '—' }}</small><button v-if="model.status !== 'ready'" type="button" class="settings-refresh" @click="trainModel(model)">Huấn luyện</button></article></div>
          </div>

          <div class="ai-board-card">
            <div class="ai-board-header"><div><span class="card-eyebrow">THỬ NGHIỆM</span><h3>Thử nghiệm đang theo dõi</h3><p>So sánh các cách trả lời và giữ lại dữ liệu để quyết định.</p></div><span class="count-badge">{{ experiments.length }}</span></div>
            <div v-if="!experiments.length" class="ai-empty-state"><strong>Chưa có thử nghiệm</strong><span>Tạo thử nghiệm A/B ở biểu mẫu phía trên.</span></div>
            <div v-else class="ai-experiment-list">
              <article v-for="experiment in experiments" :key="experiment.id" class="ai-experiment-card">
                <div><strong>{{ experiment.name }}</strong><span>#{{ experiment.id }} · tối thiểu {{ experiment.min_sample_size || 0 }} lượt mỗi nhóm</span></div>
                <div class="ai-variant-list"><span v-for="variant in experiment.variants" :key="variant">{{ variant }}</span></div>
                <span class="ai-status-pill" :class="`status-${experiment.status}`">{{ experimentStatusLabel(experiment.status) }}</span>
                <div v-if="experimentReports[experiment.id]" class="ai-rule-meta"><span v-for="arm in experimentReports[experiment.id].arms" :key="arm.variant">{{ arm.variant }}: {{ arm.exposures }} lượt thử · {{ (arm.conversion_rate * 100).toFixed(1) }}%</span><span v-if="experimentReports[experiment.id].stopped">Đã đạt điều kiện dừng</span></div>
                <div class="ai-rule-meta"><strong>Cách phân bổ lượt thử</strong><span v-if="!banditPolicies[experiment.id]?.length">Chưa có thiết lập</span><span v-for="policy in banditPolicies[experiment.id] || []" :key="policy.id">{{ policy.version }} · ε {{ policy.epsilon }} · {{ policyStatusLabel(policy.status) }}</span></div>
                <form class="ai-field-grid" @submit.prevent="createBanditPolicy(experiment)"><label class="ai-field">Phiên bản thiết lập<input v-model="banditPolicyForms[experiment.id].version" required maxlength="40" /></label><label class="ai-field">Mức thử nghiệm<input v-model.number="banditPolicyForms[experiment.id].epsilon" type="number" min="0" max="1" step="0.01" /></label><label class="ai-field">Trạng thái<select v-model="banditPolicyForms[experiment.id].status"><option value="active">Đang dùng</option><option value="paused">Tạm dừng</option><option value="archived">Đã lưu trữ</option></select></label><button type="submit" class="settings-refresh">Lưu thiết lập</button></form>
              </article>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================================================
           KHO TRI THỨC (DOCUMENTS)
      ==================================================== -->
      <section v-if="currentTab === 'documents'" class="rag-docs-layout">
        <div class="rag-header-panel">
          <div>
            <h2>Kho thông tin</h2>
            <p>Nạp tài liệu sản phẩm, câu hỏi thường gặp, chính sách... để trợ lý tự động học và trả lời khách hàng qua Facebook, Instagram và Telegram.</p>
          </div>
          <div class="rag-stats">
            <div class="stat-card">
              <span class="stat-num">{{ documents.length }}</span>
              <span class="stat-label">Tài liệu</span>
            </div>
            <div class="stat-card">
              <span class="stat-num">{{ documents.reduce((acc, d) => acc + (d.chunk_count || 0), 0) }}</span>
                <span class="stat-label">Đoạn thông tin</span>
            </div>
            <div class="stat-card">
              <span class="stat-num font-green">{{ documents.filter(d => d.status === 'ready').length }}</span>
                <span class="stat-label">Sẵn sàng</span>
            </div>
          </div>
        </div>

        <!-- UPLOAD DROPZONE -->
        <div
          class="upload-dropzone"
          @dragover.prevent
          @drop.prevent="handleDocDrop"
          @click="$refs.docFileInput.click()"
        >
          <input
            type="file"
            ref="docFileInput"
            class="hidden-file-input"
            accept=".pdf,.docx,.txt,.csv,.md,.html"
            @change="handleDocFileSelect"
          />
          <div class="dropzone-content" v-if="!docUploading">
            <span class="upload-icon">NHẬP NỘI DUNG</span>
            <strong>Nhập tệp hoặc nhập văn bản để bổ sung thông tin cho shop</strong>
            <small>Hỗ trợ PDF, DOCX, TXT, CSV, MD, HTML (tối đa 20MB)</small>
            <div class="import-choice-row"><button type="button" class="secondary-btn import-choice" @click.stop="$refs.docFileInput.click()">Nhập tệp</button><button type="button" class="secondary-btn import-choice" @click.stop="openTextImport">Nhập văn bản</button></div>
          </div>
          <div class="dropzone-content" v-else>
            <span class="spinner-icon">...</span>
            <strong>Đang tải và xử lý nội dung...</strong>
          </div>
        </div>

        <div v-if="docUploadError" class="error-banner">
          {{ docUploadError }}
        </div>

        <div v-if="textImportOpen" class="app-dialog-backdrop" @click.self="textImportOpen = false">
          <section class="app-dialog text-import-dialog" role="dialog" aria-modal="true" aria-label="Nhập văn bản" tabindex="-1" @keydown.esc="textImportOpen = false">
            <div class="settings-card-header"><div><span class="card-eyebrow">BỔ SUNG THÔNG TIN</span><h2>Nhập văn bản</h2><p>Dán FAQ, chính sách hoặc mô tả sản phẩm. Nội dung sẽ được lưu thành tài liệu riêng của shop.</p></div><button type="button" class="quick-action-close" aria-label="Đóng" @click="textImportOpen = false">×</button></div>
            <label class="text-import-title">Tên tài liệu<input v-model="textImportTitle" maxlength="120" placeholder="Ví dụ: Chính sách đổi trả" /></label>
            <label class="text-import-title">Nội dung<textarea v-model="textImportDraft" rows="10" autofocus placeholder="Dán nội dung cần lưu tại đây..."></textarea></label>
            <div class="dialog-actions"><button type="button" class="secondary-btn" @click="textImportOpen = false">Hủy</button><button type="button" class="primary-btn" :disabled="!textImportDraft.trim() || docUploading" @click="saveTextImport">{{ docUploading ? 'Đang lưu...' : 'Lưu tài liệu' }}</button></div>
          </section>
        </div>

        <!-- DOCUMENT LIST TABLE -->
        <div class="docs-table-card">
          <div class="card-header">
            <h3>Danh sách tài liệu đã nạp</h3>
            <button class="btn-refresh" @click="fetchDocuments" :disabled="docsLoading">
              🔄 Làm mới
            </button>
          </div>

          <div v-if="docsLoading && !documents.length" class="loading-state">
            Đang tải danh sách tài liệu...
          </div>

          <div v-else-if="!documents.length" class="empty-docs-state">
            📭 Chưa có tài liệu nào trong Kho thông tin. Hãy nhập tệp hoặc dán văn bản ở trên!
          </div>

          <table v-else class="docs-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Tên tài liệu</th>
                <th>Định dạng</th>
                <th>Dung lượng</th>
                <th>Đoạn thông tin</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in documents" :key="doc.id">
                <td>#{{ doc.id }}</td>
                <td class="font-medium">
                  <span class="doc-file-icon">DOC</span> {{ doc.filename }}
                </td>
                <td><span class="badge-type">{{ doc.file_type.toUpperCase() }}</span></td>
                <td>{{ formatFileSize(doc.file_size) }}</td>
                <td><strong>{{ doc.chunk_count || 0 }}</strong></td>
                <td>
                  <span class="status-badge" :class="'status-' + doc.status">
                    <span v-if="doc.status === 'ready'">Sẵn sàng</span>
                    <span v-else-if="doc.status === 'processing'">Đang xử lý</span>
                    <span v-else-if="doc.status === 'pending'">⏳ Chờ xử lý</span>
                    <span v-else>❌ Lỗi</span>
                  </span>
                  <small class="doc-embedding-state">Xử lý nội dung: {{ documentEmbeddingStatusLabel(doc.embedding_status || 'pending') }}</small>
                  <small v-if="doc.retry_after" class="doc-embedding-state">Thử lại sau: {{ formatTime(doc.retry_after) }}</small>
                  <small v-if="documentRuns[doc.id]" class="doc-embedding-state">
                    Lần xử lý: {{ documentRuns[doc.id].status }} · lần {{ documentRuns[doc.id].attempts || 0 }}
                  </small>
                </td>
                <td class="text-sm text-gray">{{ formatTime(doc.uploaded_at) }}</td>
                <td>
                  <button class="btn-delete" @click="deleteDoc(doc.id)" title="Xóa tài liệu">
                    Xóa
                  </button>
                  <button class="btn-refresh" @click="reindexDocument(doc)" title="Lập chỉ mục lại">
                    🔁 Lập chỉ mục lại
                  </button>
                  <button
                    v-if="documentRuns[doc.id]?.status === 'failed'"
                    class="btn-refresh"
                    @click="retryDocumentRun(doc, documentRuns[doc.id])"
                    title="Thử lại xử lý"
                  >
                    Thử lại xử lý
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===================================================
           TRỢ LÝ HỎI ĐÁP
      ==================================================== -->
      <section v-if="currentTab === 'rag_chat'" class="rag-chat-layout">
        <div class="rag-chat-sidebar">
          <div class="setting-card">
            <h3>Trả lời tự động trên các kênh</h3>
            <p class="setting-desc">Trợ lý tự động trả lời tin nhắn từ khách Facebook, Instagram và Telegram dựa trên kho thông tin của shop.</p>
            
            <div class="toggle-row">
              <span>Trả lời tự động:</span>
              <button
                class="toggle-switch"
                :class="{ active: autoReplyEnabled }"
                :disabled="autoReplySaving"
                @click="toggleAutoReply"
              >
                <span class="toggle-knob"></span>
                <span class="toggle-text">{{ autoReplySaving ? 'ĐANG LƯU' : (autoReplyEnabled ? 'ĐANG BẬT' : 'TẮT') }}</span>
              </button>
            </div>
            <p v-if="autoReplyNotice" class="settings-notice" role="status" aria-live="polite">{{ autoReplyNotice }}</p>
            <p v-if="autoReplyError" class="settings-notice team-error" role="alert">{{ autoReplyError }}</p>
          </div>

          <div class="setting-card">
            <h3>Cách trợ lý trả lời</h3>
            <p class="setting-desc">Trợ lý tự chọn thông tin phù hợp trong Kho thông tin của shop. Các thiết lập kỹ thuật được hệ thống tối ưu sẵn.</p>
            <div class="config-item"><span class="config-val">✓ Luôn ưu tiên nội dung mới nhất</span></div>
            <div class="config-item"><span class="config-val">✓ Chỉ dùng dữ liệu của shop này</span></div>
          </div>

          <div class="setting-card">
            <h3>Câu hỏi mẫu nhanh</h3>
            <div class="quick-questions">
              <button @click="sendRagQuery('Cửa hàng có những sản phẩm gì và giá bao nhiêu?')">
                💬 Danh sách sản phẩm & Giá
              </button>
              <button @click="sendRagQuery('Chính sách đổi trả và hoàn tiền như thế nào?')">
                💬 Chính sách đổi trả & Hoàn tiền
              </button>
              <button @click="sendRagQuery('Thời gian giao hàng và phí ship tính sao?')">
                💬 Phí vận chuyển & Giao hàng
              </button>
            </div>
          </div>
        </div>

        <div class="rag-chat-main">
          <div class="rag-chat-header">
            <div>
              <h2>Trợ lý hỏi đáp</h2>
              <small>Hỏi đáp trực tiếp với kho thông tin – trả lời theo thời gian thực</small>
            </div>
            <span class="badge-online">● Đang hoạt động</span>
          </div>

          <div class="rag-chat-messages" ref="ragChatBox">
            <div
              v-for="(m, idx) in ragMessages"
              :key="idx"
              class="rag-msg-row"
              :class="m.role"
            >
              <div class="rag-msg-avatar">
                {{ m.role === 'user' ? 'Bạn' : 'Trợ lý' }}
              </div>
              <div class="rag-msg-bubble">
                <div class="rag-msg-sender">
                  {{ m.role === 'user' ? 'Bạn' : 'Trợ lý' }}
                </div>
                <div class="rag-msg-text" v-if="m.content">
                  {{ m.content }}
                </div>
                <div class="rag-msg-loading" v-if="m.loading">
                  <span class="dot-pulse">●</span> Đang tra cứu kho thông tin...
                </div>
              </div>
            </div>
          </div>

          <div class="rag-chat-inputzone">
            <textarea
              v-model="ragQuery"
              placeholder="Nhập câu hỏi tại đây... (VD: Áo thun nam giá bao nhiêu?)"
              rows="2"
              @keydown.enter.prevent="sendRagQuery()"
            ></textarea>
            <button
              class="btn-send-rag"
              @click="sendRagQuery()"
              :disabled="ragSending || !ragQuery.trim()"
            >
              <span>Gửi</span> 🚀
            </button>
          </div>
        </div>

      </section>

      <!-- ===================================================
           CRM REPORTS
      ==================================================== -->
      <section v-if="currentTab === 'reports'" class="products-layout reports-layout">
        <div class="products-header">
          <div>
            <h2>Báo cáo CRM</h2>
            <p>Tổng quan khách hàng, hội thoại, bán hàng và hiệu suất xử lý.</p>
          </div>
          <button type="button" class="settings-refresh" @click="fetchReports">Làm mới</button>
        </div>
        <div v-if="reportsError" class="product-error">{{ reportsError }}</div>
        <form class="report-filters" @submit.prevent="fetchReports">
          <label>Từ ngày<input v-model="reportFilters.start_at" type="date" /></label>
          <label>Đến ngày<input v-model="reportFilters.end_at" type="date" /></label>
          <label>Kênh<select v-model="reportFilters.channel"><option value="">Tất cả kênh</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="telegram">Telegram</option><option value="zalo">Zalo</option></select></label>
          <label>Nguồn ghi nhận<input v-model.trim="reportFilters.source" placeholder="VD: quảng cáo mạng xã hội" /></label>
          <label>Trạng thái<select v-model="reportFilters.status"><option value="">Tất cả</option><option value="open">Đang mở</option><option value="pending">Đang chờ</option><option value="qualified">Đã đủ điều kiện</option><option value="won">Đã thắng</option><option value="resolved">Đã xử lý</option><option value="closed">Đã đóng</option></select></label>
          <label>Nhân viên<select v-model="reportFilters.assigned_user_id"><option value="">Tất cả nhân viên</option><option v-for="member in teamUsers" :key="member.id" :value="member.id">{{ member.full_name }}</option></select></label>
          <button class="primary-btn" type="submit">Áp dụng</button>
          <button type="button" class="settings-refresh" :disabled="reportCsvDownloading" @click="downloadReportCsv">{{ reportCsvDownloading ? 'Đang tải tệp...' : 'Tải tệp báo cáo' }}</button>
        </form>
        <p v-if="reportCsvStatus" class="settings-notice" role="status" aria-live="polite">{{ reportCsvStatus }}</p>
        <div v-if="reportsLoading" class="products-empty">Đang tải báo cáo...</div>
        <template v-else-if="crmOverview">
          <div class="report-cards">
            <div class="report-card accent"><span>Khách hàng</span><strong>{{ crmOverview.customer_count }}</strong></div>
            <div class="report-card"><span>Hội thoại</span><strong>{{ crmOverview.conversation_count }}</strong></div>
            <div class="report-card"><span>Đơn hàng</span><strong>{{ crmOverview.order_count }}</strong></div>
            <div class="report-card"><span>Doanh thu</span><strong>{{ Number(crmOverview.total_revenue || 0).toLocaleString('vi-VN') }}đ</strong></div>
            <div class="report-card"><span>Tỷ lệ chốt cơ hội</span><strong>{{ crmOverview.conversion_rate }}%</strong><small>{{ crmOverview.won_lead_count }}/{{ crmOverview.lead_count }} cơ hội</small></div>
            <div class="report-card"><span>Đơn / hội thoại</span><strong>{{ crmOverview.conversation_to_order_rate }}%</strong></div>
            <div class="report-card"><span>Phiếu đang mở</span><strong>{{ crmOverview.open_ticket_count }}</strong><small>{{ crmOverview.ticket_count }} phiếu tổng</small></div>
            <div class="report-card"><span>Đơn nhập hàng</span><strong>{{ crmOverview.purchase_order_count || 0 }}</strong><small>Chi {{ Number(crmOverview.purchase_spend || 0).toLocaleString('vi-VN') }}đ</small></div>
          </div>
          <div class="report-panel quality-ops-panel">
            <div class="report-panel-header">
              <div><h3>Vận hành nền tảng</h3><span>Lượt dùng, kênh kết nối, chi phí trợ lý và thời hạn trong {{ qualityDashboard.period_days || 30 }} ngày gần nhất</span></div>
              <span class="quality-health-pill" :class="{ warning: (qualityDashboard.provider?.failed_events || 0) > 0 || (qualityDashboard.sla?.overdue_tickets || 0) > 0 || Object.values(qualityDashboard.provider?.circuits || {}).some(circuit => circuit.state === 'open') }">{{ (qualityDashboard.provider?.failed_events || 0) > 0 || (qualityDashboard.sla?.overdue_tickets || 0) > 0 || Object.values(qualityDashboard.provider?.circuits || {}).some(circuit => circuit.state === 'open') ? 'Cần xử lý' : 'Ổn định' }}</span>
            </div>
            <div class="report-cards quality-ops-cards">
              <div class="report-card"><span>Kênh lỗi</span><strong>{{ qualityDashboard.provider?.failed_events || 0 }}</strong><small>{{ qualityDashboard.provider?.retrying_events || 0 }} đang thử lại</small></div>
              <div class="report-card"><span>Lượt trợ lý</span><strong>{{ qualityDashboard.ai?.calls || 0 }}</strong><small>{{ qualityDashboard.ai?.tool_errors || 0 }} lỗi công cụ</small></div>
              <div class="report-card"><span>Chi phí trợ lý</span><strong>{{ Number(qualityDashboard.ai?.cost || 0).toLocaleString('vi-VN') }}</strong><small>theo hạn mức kỳ hiện tại</small></div>
              <div class="report-card"><span>Phiếu quá hạn</span><strong>{{ qualityDashboard.sla?.overdue_tickets || 0 }}</strong><small>{{ qualityDashboard.sla?.due_soon_tickets || 0 }} sắp đến hạn</small></div>
            </div>
            <div class="quality-usage-list" v-if="Object.keys(qualityDashboard.usage || {}).length">
              <span v-for="(quota, resource) in qualityDashboard.usage" :key="resource" class="quality-usage-chip"><b>{{ usageResourceLabel(resource) }}</b><em>{{ quota.used }}<template v-if="quota.limit !== null && quota.limit !== undefined"> / {{ quota.limit }}</template></em></span>
            </div>
            <div class="quality-circuit-list" v-if="Object.keys(qualityDashboard.provider?.circuits || {}).length">
              <span
                v-for="(circuit, provider) in qualityDashboard.provider.circuits"
                :key="provider"
                class="quality-circuit-chip"
                :class="{ open: circuit.state === 'open', half: circuit.state === 'half_open' }"
              >
                <b>Bộ ngắt kênh · {{ provider }}</b>
                <em>{{ circuit.state === 'open' ? 'Đang tạm dừng' : circuit.state === 'half_open' ? 'Đang kiểm tra' : 'Đang hoạt động' }} · {{ circuit.failures || 0 }} lỗi liên tiếp</em>
              </span>
            </div>
          </div>
          <div class="report-panel">
            <div class="report-panel-header"><h3>Hiệu suất nhân viên</h3><span>Chỉ số theo business hiện tại</span></div>
            <div v-if="!agentPerformance.length" class="products-empty">Chưa có nhân viên được phân công.</div>
            <div v-else class="products-table-wrap">
              <table class="products-table reports-table">
                <thead><tr><th>Nhân viên</th><th>Hội thoại</th><th>Phiếu hỗ trợ</th><th>Đã xử lý</th><th>Cơ hội</th><th>Đã chốt</th></tr></thead>
                <tbody>
                  <tr v-for="agent in agentPerformance" :key="agent.user_id">
                    <td><strong>{{ agent.full_name }}</strong><small>{{ roleLabel(agent.role) }}</small></td>
                    <td>{{ agent.assigned_conversations }}</td><td>{{ agent.assigned_tickets }}</td><td>{{ agent.resolved_tickets }}</td><td>{{ agent.assigned_leads }}</td><td>{{ agent.won_leads }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-if="revenueAttribution" class="report-panel">
            <div class="report-panel-header"><div><h3>Phân bổ doanh thu</h3><span>Ghi nhận theo lần tương tác cuối</span></div><button type="button" class="settings-refresh" :disabled="attributionSaving" @click="recalculateRevenueAttribution">{{ attributionSaving ? 'Đang tính...' : 'Tính lại nguồn doanh thu' }}</button></div>
            <div class="report-cards">
              <div class="report-card accent"><span>Doanh thu được gán</span><strong>{{ Number(revenueAttribution.total_attributed || 0).toLocaleString('vi-VN') }}đ</strong></div>
              <div class="report-card"><span>Điểm tương tác</span><strong>{{ revenueAttribution.items?.length || 0 }}</strong></div>
            </div>
            <div v-if="!revenueAttribution.items?.length" class="products-empty">Chưa có dữ liệu điểm tương tác. Doanh thu sẽ xuất hiện sau khi gắn nguồn hội thoại/chiến dịch.</div>
            <div v-else class="products-table-wrap">
              <table class="products-table reports-table">
                <thead><tr><th>Kênh</th><th>Nguồn</th><th>Campaign</th><th>Doanh thu gán</th></tr></thead>
                <tbody><tr v-for="item in revenueAttribution.items" :key="`${item.channel}-${item.source}-${item.campaign || ''}`"><td>{{ item.channel || '—' }}</td><td>{{ item.source }}</td><td>{{ item.campaign || '—' }}</td><td><strong>{{ Number(item.attributed_revenue || 0).toLocaleString('vi-VN') }}đ</strong></td></tr></tbody>
              </table>
            </div>
          </div>
          <div class="report-panel">
            <div class="report-panel-header"><div><h3>Luồng bán hàng & chuyển đổi</h3><span>Cơ hội theo giai đoạn trong phạm vi lọc</span></div><strong>{{ pipelineSummary.reduce((total, item) => total + Number(item.lead_count || 0), 0) }} cơ hội</strong></div>
            <div v-if="!pipelineSummary.length" class="products-empty">Chưa có cơ hội phù hợp với bộ lọc.</div>
            <div v-else class="pipeline-summary"><div v-for="item in pipelineSummary" :key="item.stage" class="pipeline-card"><span>{{ leadStageLabel(item.stage) }}</span><strong>{{ item.lead_count }}</strong><small>{{ Number(item.value || 0).toLocaleString('vi-VN') }}đ</small></div></div>
          </div>
          <div class="report-panel">
            <div class="report-panel-header"><div><h3>Phiếu hỗ trợ & thời hạn</h3><span>Phiếu theo trạng thái trong phạm vi lọc</span></div><strong>{{ ticketReport.overdue_tickets || 0 }} quá hạn</strong></div>
            <div v-if="!ticketReport.items?.length" class="products-empty">Chưa có phiếu phù hợp với bộ lọc.</div>
            <div v-else class="ticket-summary"><div class="ticket-stat"><span>Tổng phiếu</span><strong>{{ ticketReport.total_tickets || 0 }}</strong></div><div v-for="item in ticketReport.items" :key="item.status" class="ticket-stat"><span>{{ ticketStatusLabel(item.status) }}</span><strong>{{ item.ticket_count }}</strong></div></div>
          </div>
          <div v-if="crmOverview.time_series?.length" class="report-panel">
            <div class="report-panel-header"><h3>Xu hướng theo ngày</h3><span>Hội thoại · đơn bán · doanh thu</span></div>
            <div class="report-series"><div v-for="point in crmOverview.time_series.slice(-14)" :key="point.date" class="report-series-row"><span>{{ point.date }}</span><b>{{ point.conversations }} hội thoại · {{ point.orders }} đơn · {{ Number(point.revenue || 0).toLocaleString('vi-VN') }}đ</b></div></div>
          </div>
          <div v-if="inventoryReport" class="report-panel">
            <div class="report-panel-header"><h3>Tồn kho</h3><span>{{ inventoryReport.total || 0 }} sản phẩm</span></div>
            <div class="report-cards">
              <div class="report-card"><span>Tồn thực tế</span><strong>{{ inventoryReport.stock_quantity || 0 }}</strong></div>
              <div class="report-card"><span>Đang giữ</span><strong>{{ inventoryReport.reserved_quantity || 0 }}</strong></div>
              <div class="report-card"><span>Có thể bán</span><strong>{{ inventoryReport.available_quantity || 0 }}</strong></div>
            </div>
            <div v-if="inventoryReport.items?.length" class="products-table-wrap">
              <table class="products-table reports-table">
                <thead><tr><th>Sản phẩm</th><th>Tồn</th><th>Giữ</th><th>Có thể bán</th><th>Biến động</th></tr></thead>
                <tbody><tr v-for="item in inventoryReport.items" :key="item.product_id"><td><strong>{{ item.name }}</strong><small>{{ item.sku }}</small></td><td>{{ item.stock_quantity }}</td><td>{{ item.reserved_quantity }}</td><td>{{ item.available_quantity }}</td><td>{{ item.net_movement_quantity }} ({{ item.movement_count }} lần)</td></tr></tbody>
              </table>
            </div>
          </div>
          <div v-if="purchaseCostReport" class="report-panel">
            <div class="report-panel-header"><h3>Chi phí nhập đã nhận</h3><strong>{{ Number(purchaseCostReport.total_received_cost || 0).toLocaleString('vi-VN') }}đ</strong></div>
            <div v-if="!purchaseCostReport.items?.length" class="products-empty">Chưa có phiếu nhập trong khoảng thời gian này.</div>
            <div v-else class="products-table-wrap"><table class="products-table reports-table"><thead><tr><th>Nhà cung cấp</th><th>Số phiếu</th><th>Số lượng</th><th>Chi phí nhận</th></tr></thead><tbody><tr v-for="item in purchaseCostReport.items" :key="item.supplier_name"><td>{{ item.supplier_name }}</td><td>{{ item.receipt_count }}</td><td>{{ item.received_quantity }}</td><td><strong>{{ Number(item.received_cost || 0).toLocaleString('vi-VN') }}đ</strong></td></tr></tbody></table></div>
          </div>
        </template>
      </section>

      <!-- ===================================================
           BUSINESS HOURS / SLA
      ==================================================== -->
      <section v-if="currentTab === 'business_hours'" class="settings-layout business-hours-layout">
        <div class="settings-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">VẬN HÀNH SHOP</span><h2>Giờ làm việc</h2><p>Trợ lý sẽ báo đúng thời gian phục vụ và chuyển người hỗ trợ khi shop ngoài giờ.</p></div><span class="connection-badge connected">ĐANG DÙNG</span></div>
          <div class="business-hours-grid"><label>Múi giờ<select v-model="businessHoursForm.timezone"><option value="Asia/Ho_Chi_Minh">Việt Nam (UTC+7)</option><option value="Asia/Bangkok">Bangkok (UTC+7)</option></select></label><label>Giờ mở cửa<input v-model="businessHoursForm.start" type="time" /></label><label>Giờ đóng cửa<input v-model="businessHoursForm.end" type="time" /></label><label class="checkbox-field business-hours-enabled"><input v-model="businessHoursForm.enabled" type="checkbox" /> Shop đang mở cửa</label></div>
          <fieldset class="business-days-fieldset"><legend>Ngày phục vụ</legend><div class="business-day-options"><label v-for="([key, label]) in businessHourDayLabels" :key="key" class="business-day-option" :class="{ selected: businessHoursDays[key] }"><input v-model="businessHoursDays[key]" type="checkbox" :disabled="!businessHoursForm.enabled" /><span>{{ label }}</span></label></div><small class="field-hint">Bỏ chọn ngày nghỉ; cùng một khung giờ sẽ áp dụng cho các ngày đã chọn.</small></fieldset>
          <div v-if="businessHoursNotice" class="settings-notice" role="status">{{ businessHoursNotice }}</div><button type="button" class="primary-btn" @click="saveBusinessHours">Lưu giờ làm việc</button>
        </div>
      </section>

      <section v-if="currentTab === 'sla_rules'" class="settings-layout sla-rules-layout">
        <div class="settings-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">QUY TẮC PHỤC VỤ</span><h2>Quy tắc thời hạn</h2><p>Đặt thời gian phản hồi và xử lý để đội ngũ biết việc nào cần ưu tiên.</p></div></div>
          <div class="sla-rules-grid"><label>Phản hồi trong (giờ)<input v-model.number="slaRulesForm.firstResponseHours" type="number" min="1" max="168" /></label><label>Hoàn tất trong (giờ)<input v-model.number="slaRulesForm.resolutionHours" type="number" min="1" max="720" /></label></div>
          <p class="settings-muted">Phiếu quá hạn sẽ được đánh dấu trong mục Phiếu hỗ trợ và gửi thông báo cho người phụ trách.</p><div v-if="slaRulesNotice" class="settings-notice" role="status">{{ slaRulesNotice }}</div><button type="button" class="primary-btn" @click="saveSlaRules">Lưu quy tắc</button>
        </div>
      </section>

      <!-- ===================================================
           LINKED CHANNELS
      ==================================================== -->
      <section v-if="currentTab === 'channels'" class="settings-layout channels-layout">
        <div v-if="authUser" class="settings-card channel-page-header">
          <div class="settings-card-header">
            <div>
              <h2>Kết nối mạng xã hội</h2>
              <p>Quản lý Facebook, Instagram, Telegram và Zalo riêng cho shop này.</p>
            </div>
            <span class="connection-badge" :class="{ connected: metaStatus.connected || activeBotConnections.length }">
              {{ (metaStatus.connected || activeBotConnections.length) ? 'ĐANG HOẠT ĐỘNG' : 'CHƯA KẾT NỐI' }}
            </span>
          </div>
          <p class="settings-muted">Mỗi shop chỉ nhìn thấy mã kết nối, nhận sự kiện và lịch sử của chính shop đó. Dữ liệu không dùng chung giữa các không gian.</p>
          <div v-if="quotaSnapshot?.resources?.connected_channels" class="channel-quota-note">Kênh đang dùng: <strong>{{ quotaSnapshot.resources.connected_channels.used }} / {{ quotaSnapshot.resources.connected_channels.limit ?? '∞' }}</strong> theo gói {{ quotaSnapshot.plan_name || 'hiện tại' }}.</div>
        </div>

        <div v-if="authUser" class="channel-summary-grid channel-summary-grid-four">
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2>Facebook</h2><p>Trang bán hàng và tin nhắn Messenger.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected }">{{ metaStatus.connected ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Cấp quyền một lần để nhận tin từ Trang Facebook.</p>
            <div class="channel-summary-actions"><button type="button" class="primary-btn" @click="openChannelModal('facebook')">{{ metaStatus.connected ? 'Xem Facebook' : 'Kết nối Facebook' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2>Instagram</h2><p>Tài khoản chuyên nghiệp và tin nhắn Instagram.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected && metaStatus.instagram_account_id }">{{ metaStatus.connected && metaStatus.instagram_account_id ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Dùng chung lần cấp quyền Facebook nhưng theo dõi riêng.</p>
            <div class="channel-summary-actions"><button type="button" class="secondary-btn" @click="openChannelModal('instagram')">{{ metaStatus.connected && metaStatus.instagram_account_id ? 'Xem Instagram' : 'Kết nối Instagram' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2>Telegram</h2><p>Bot Telegram riêng của shop.</p></div><span class="connection-badge" :class="{ connected: activeBotConnections.some((item) => item.channel_type === 'telegram') }">{{ activeBotConnections.some((item) => item.channel_type === 'telegram') ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Dán mã bot, CRM kiểm tra và nhận tin tự động.</p>
            <div class="channel-summary-actions"><button type="button" class="primary-btn" @click="openChannelModal('telegram')">{{ activeBotConnections.some((item) => item.channel_type === 'telegram') ? 'Quản lý Telegram' : 'Kết nối Telegram' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2>Zalo cá nhân</h2><p>Kết nối tài khoản Zalo cá nhân của shop.</p></div><span class="connection-badge" :class="{ connected: activeBotConnections.some((item) => item.channel_type === 'zalo') }">{{ activeBotConnections.some((item) => item.channel_type === 'zalo') ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Dùng phiên đăng nhập Zalo bridge của shop, không dùng Zalo OA.</p>
            <div class="channel-summary-actions"><button type="button" class="secondary-btn" @click="openChannelModal('zalo')">{{ activeBotConnections.some((item) => item.channel_type === 'zalo') ? 'Quản lý Zalo' : 'Kết nối Zalo' }}</button></div>
          </article>
        </div>
        <div v-if="authUser" class="settings-card channel-connect-card" aria-hidden="true"></div>

        <div v-if="channelModalOpen" class="app-dialog-backdrop channel-modal-backdrop" @click.self="closeChannelModal">
          <section class="channel-modal app-dialog" role="dialog" aria-modal="true" aria-label="Kết nối kênh bán hàng" tabindex="-1" @keydown.esc="closeChannelModal">
            <div class="settings-card-header"><div><span class="card-eyebrow">KÊNH CỦA SHOP</span><h2>{{ ['meta', 'facebook', 'instagram'].includes(channelModalTab) ? 'Kết nối Facebook & Instagram' : `Kết nối ${channelModalTab === 'zalo' ? 'Zalo' : 'Telegram'}` }}</h2><p>Mã kết nối chỉ dùng cho shop này và không chia sẻ giữa các không gian.</p></div><button type="button" class="quick-action-close" aria-label="Đóng" @click="closeChannelModal">×</button></div>
            <span class="visually-hidden">Kết nối Telegram/Zalo · Quét QR để tạo bot · BotFather · Zalo Bot Manager</span>
            <template v-if="['meta', 'facebook', 'instagram'].includes(channelModalTab)">
              <div v-if="metaNotice" class="settings-notice team-error">{{ metaNotice }}</div>
              <div class="meta-channel-grid">
                <article class="meta-channel-card" :class="{ active: channelModalTab === 'facebook' }"><div><span class="channel-card-icon">f</span><h3>Facebook</h3><p>Trang bán hàng và tin nhắn Messenger.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected }">{{ metaStatus.connected ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span><div v-if="metaStatus.connected" class="meta-connection-details"><div><strong>Trang:</strong> {{ metaStatus.facebook_page_name || 'Đã kết nối' }}</div><div><strong>Mã trang:</strong> {{ metaStatus.facebook_page_id || '—' }}</div></div><button v-if="!metaStatus.connected" class="btn-meta-connect" type="button" :disabled="metaLoading" @click="connectMeta">{{ metaLoading ? 'Đang kết nối...' : 'Kết nối Facebook' }}</button></article>
                <article class="meta-channel-card" :class="{ active: channelModalTab === 'instagram' }"><div><span class="channel-card-icon">◎</span><h3>Instagram</h3><p>Tài khoản chuyên nghiệp và tin nhắn Instagram.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected && metaStatus.instagram_account_id }">{{ metaStatus.connected && metaStatus.instagram_account_id ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span><div v-if="metaStatus.connected" class="meta-connection-details"><div><strong>Tài khoản:</strong> {{ metaStatus.instagram_account_id || 'Chưa liên kết' }}</div><div><strong>Nhận tin:</strong> {{ metaStatus.subscription_status || 'Chưa kiểm tra' }}</div></div><button v-if="!metaStatus.connected" class="btn-meta-connect" type="button" :disabled="metaLoading" @click="connectMeta">{{ metaLoading ? 'Đang kết nối...' : 'Kết nối Instagram' }}</button></article>
              </div>
              <p class="settings-muted meta-oauth-note">Facebook và Instagram dùng chung một lần cấp quyền; CRM vẫn tách riêng dữ liệu và trạng thái hiển thị cho từng kênh.</p>
              <div v-if="metaStatus.connected" class="settings-actions"><button class="btn-meta-disconnect" type="button" :disabled="metaLoading" @click="disconnectMeta">Ngắt kết nối Facebook/Instagram</button></div>
            </template>
            <template v-else>
              <span class="visually-hidden">Sao chép token · Zalo Bot Manager</span>
              <div v-if="botConnectionError" class="settings-notice team-error bot-connection-alert"><span>{{ botConnectionError }}</span><button type="button" class="settings-refresh" :disabled="botConnectionLoading" @click="fetchBotConnections">{{ botConnectionLoading ? 'Đang tải...' : 'Thử lại' }}</button></div><div v-if="botConnectionNotice" class="settings-notice">{{ botConnectionNotice }}</div>
              <div class="bot-provider-heading"><span class="channel-card-icon">{{ channelModalTab === 'zalo' ? 'Z' : '✈' }}</span><div><h3>{{ channelModalTab === 'zalo' ? 'Zalo cá nhân' : 'Telegram BotFather' }}</h3><p>{{ channelModalTab === 'zalo' ? 'Kết nối phiên đăng nhập Zalo cá nhân của shop.' : 'Kết nối kênh Telegram chính thức của shop.' }}</p></div><span class="connection-badge" :class="{ connected: activeBotConnections.some((item) => item.channel_type === channelModalTab) }">{{ activeBotConnections.some((item) => item.channel_type === channelModalTab) ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
              <div class="bot-connect-guide-single"><div class="bot-guide-qr-wrap"><img :src="botQrUrl(channelModalTab)" :alt="`Mã QR mở ${channelModalTab === 'zalo' ? 'Zalo cá nhân' : 'Telegram BotFather'}`" loading="lazy" /></div><div><ol v-if="channelModalTab === 'telegram'"><li>Mở BotFather.</li><li>Gõ <code>/newbot</code> và tạo bot.</li><li>Sao chép mã bot gửi cho bạn.</li></ol><ol v-else><li>Đăng nhập Zalo cá nhân trên máy chạy bridge.</li><li>Chọn phiên Zalo cần dùng cho shop.</li><li>Sao chép mã phiên bridge và dán vào đây.</li></ol><a class="bot-guide-link" :href="botGuideUrl(channelModalTab)" target="_blank" rel="noreferrer">{{ channelModalTab === 'zalo' ? 'Mở Zalo Web' : 'Mở Telegram BotFather' }}</a></div></div>
              <form class="bot-connect-form" @submit.prevent="connectBotChannel"><input type="hidden" v-model="botConnectionForm.channel_type" /><label class="bot-token-field">{{ channelModalTab === 'zalo' ? 'Mã phiên Zalo bridge' : 'Mã bot' }}<div class="bot-token-input-wrap"><input v-model="botConnectionForm.access_token" :type="botTokenVisible ? 'text' : 'password'" autocomplete="off" required :placeholder="channelModalTab === 'zalo' ? 'Dán mã phiên bridge tại đây' : 'Dán mã bot tại đây'" /><button type="button" class="token-visibility-btn" @click="botTokenVisible = !botTokenVisible">{{ botTokenVisible ? 'Ẩn' : 'Hiện' }}</button></div></label><button class="primary-btn bot-connect-submit" type="submit" :disabled="botConnectionSaving">{{ botConnectionSaving ? 'Đang kiểm tra...' : 'Kiểm tra và kết nối' }}</button></form>
              <p class="bot-connect-note">{{ channelModalTab === 'zalo' ? 'Phiên Zalo được giữ trên máy bridge của shop; CRM chỉ nhận mã phiên đã mã hóa.' : 'Mã kết nối chỉ dùng cho shop này và được lưu an toàn.' }}</p><div v-if="botConnectionLoading" class="settings-empty">Đang tải trạng thái kết nối...</div><ul v-else-if="botConnections.filter((item) => item.channel_type === channelModalTab).length" class="bot-connection-list"><li v-for="connection in botConnections.filter((item) => item.channel_type === channelModalTab)" :key="connection.id"><div><strong>{{ connection.name }}</strong><small>{{ channelModalTab === 'zalo' ? 'Zalo cá nhân' : 'Telegram' }} · {{ botConnectionStateLabel(connection.status) }} · Nhận tin {{ connection.webhook_status === 'connected' ? 'hoạt động' : connection.webhook_status === 'disconnected' ? 'đã ngắt' : 'cần kiểm tra' }}</small></div><button v-if="['connected', 'active', 'verifying', 'reconnect_required', 'error'].includes(String(connection.status || '').toLowerCase())" type="button" class="team-toggle" @click="disconnectBotChannel(connection)">Ngắt kết nối</button></li></ul><div v-else class="settings-empty">Chưa có kết nối {{ channelModalTab === 'zalo' ? 'Zalo cá nhân' : 'Telegram' }} nào.</div>
            </template>
          </section>
        </div>
      </section>

      <!-- ===================================================
           WEBHOOKS
      ==================================================== -->
      <section v-if="currentTab === 'webhooks'" class="settings-layout webhooks-layout">
        <div class="settings-card webhook-card">
          <div class="settings-card-header">
            <div><h2>Nhận sự kiện</h2><p>Kiểm tra trạng thái nhận tin nhắn từ Facebook, Instagram, Telegram và Zalo.</p></div>
            <button type="button" class="settings-refresh" :disabled="botConnectionLoading || metaLoading" @click="refreshWebhookStatus">{{ botConnectionLoading || metaLoading ? 'Đang kiểm tra...' : 'Làm mới' }}</button>
          </div>
          <div v-if="botConnectionError || metaNotice" class="settings-notice team-error">{{ botConnectionError || metaNotice }}</div>
          <div class="webhook-grid">
            <article class="webhook-item"><div><strong>Facebook</strong><span class="webhook-status" :class="{ connected: metaStatus.connected && metaStatus.subscription_status }">{{ metaStatus.connected ? (metaStatus.subscription_status || 'Đã kết nối') : 'Chưa kết nối' }}</span></div><small>Nhận tin tự động từ Trang Facebook của shop.</small></article>
            <article class="webhook-item"><div><strong>Instagram</strong><span class="webhook-status" :class="{ connected: metaStatus.connected && metaStatus.instagram_account_id }">{{ metaStatus.instagram_account_id ? 'Đã kết nối' : 'Chưa kết nối' }}</span></div><small>Nhận tin Instagram riêng, dùng cùng lần cấp quyền Facebook.</small></article>
            <article v-for="connection in botConnections" :key="`webhook-${connection.id}`" class="webhook-item"><div><strong>{{ connection.channel_type === 'zalo' ? 'Zalo' : 'Telegram' }}</strong><span class="webhook-status" :class="{ connected: connection.webhook_status === 'connected' }">{{ connection.webhook_status === 'connected' ? 'Đang hoạt động' : connection.webhook_status === 'disconnected' ? 'Đã ngắt' : 'Cần kiểm tra' }}</span></div><small>{{ connection.name }} · nhận tin riêng cho shop.</small></article>
          </div>
          <div v-if="!botConnections.length && !metaStatus.connected" class="settings-empty">Chưa có điểm nhận sự kiện nào được đăng ký.</div>
        </div>
        <div class="settings-card webhook-card webhook-guide-card">
          <div class="settings-card-header"><div><h3>Nguyên tắc an toàn</h3><p>Tin nhắn chỉ được nhận khi đúng mã bảo vệ và thông tin kết nối không hiển thị cho người khác.</p></div></div>
          <ul class="webhook-checklist"><li><span>✓</span> Thông tin kết nối được bảo vệ riêng theo shop.</li><li><span>✓</span> Tin không hợp lệ sẽ bị từ chối.</li><li><span>✓</span> Thử lại không tạo tin nhắn trùng.</li></ul>
        </div>
      </section>

      <!-- ===================================================
           SETTINGS / ACCOUNT
      ==================================================== -->
      <section v-if="currentTab === 'settings'" class="settings-layout">
        <div class="settings-card auth-card">
          <div class="settings-card-header">
            <div>
              <h2>Đăng nhập CRM</h2>
              <p>Phiên đăng nhập giúp áp dụng vai trò và ghi nhật ký thao tác.</p>
            </div>
            <span class="connection-badge" :class="{ connected: authUser }">{{ authUser ? 'ĐÃ ĐĂNG NHẬP' : 'CẦN ĐĂNG NHẬP' }}</span>
          </div>
          <form v-if="!authUser" class="team-form" @submit.prevent="login">
            <input v-model="loginForm.email" required type="email" placeholder="Email công việc" />
            <input v-model="loginForm.password" required type="password" placeholder="Mật khẩu" />
            <input v-model="loginForm.shop_slug" type="text" maxlength="120" placeholder="Mã shop (nếu email dùng nhiều shop)" />
            <button class="primary-btn" type="submit" :disabled="authLoading">{{ authLoading ? 'Đang đăng nhập...' : 'Đăng nhập' }}</button>
          </form>
          <div v-if="authUser" class="auth-session-row">
            <span><strong>{{ authUser.full_name }}</strong> · {{ roleLabel(authUser.role) }} · {{ authUser.email }}</span>
            <button type="button" class="settings-refresh" @click="logout">Đăng xuất</button>
          </div>
          <div v-if="authError" class="settings-notice team-error">{{ authError }}</div>
        </div>

        <div v-if="authUser" class="settings-card quota-card">
          <div class="settings-card-header">
            <div><h2>Hạn mức & quyền lợi gói</h2><p>Lượt sử dụng theo kỳ; cảnh báo khi chạm {{ quotaSnapshot ? Math.round(Number(quotaSnapshot.warning_percent || 0) * 100) : 80 }}% giới hạn.</p></div>
            <button type="button" class="settings-refresh" :disabled="quotaLoading" @click="fetchQuotaUsage">{{ quotaLoading ? 'Đang tải...' : 'Làm mới' }}</button>
          </div>
          <div v-if="quotaError" class="settings-notice team-error">{{ quotaError }}</div>
          <div v-if="!quotaSnapshot && quotaLoading" class="settings-empty">Đang tải hạn mức...</div>
          <div v-else-if="quotaSnapshot" class="quota-grid">
            <div v-for="(item, resource) in quotaSnapshot.resources" :key="resource" class="quota-item" :class="{ warning: item.near_limit, exceeded: item.exceeded }">
              <div><strong>{{ usageResourceLabel(resource) }}</strong><span>{{ item.limit === null ? `${item.used} đã dùng` : `${item.used} / ${item.limit}` }}</span></div>
              <div class="quota-track"><span :style="{ width: `${Math.min(100, Number(item.percent || 0))}%` }"></span></div>
              <small v-if="item.exceeded">Đã vượt giới hạn</small><small v-else-if="item.near_limit">Sắp chạm hạn mức</small>
            </div>
          </div>
        </div>

        <div v-if="authUser" class="settings-card business-profile-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">THÔNG TIN SHOP</span><h2>Tên, logo &amp; lời chào</h2><p>Những thông tin này được dùng khi trợ lý giới thiệu shop với khách.</p></div></div>
          <div class="business-profile-grid"><label>Tên doanh nghiệp<input v-model="businessProfile.name" maxlength="160" placeholder="Tên shop" /></label><label>Đường dẫn logo<input v-model="businessProfile.logo_url" type="url" placeholder="https://..." /></label><label class="business-profile-wide">Mô tả shop<textarea v-model="businessProfile.description" rows="3" maxlength="1000" placeholder="Shop bán gì, điểm nổi bật..." /></label><label class="business-profile-wide">Tin nhắn chào mừng<textarea v-model="businessProfile.welcome_message" rows="3" maxlength="1000" placeholder="Xin chào, shop có thể giúp gì cho bạn?" /></label><label>Giọng văn<select v-model="businessProfile.tone"><option>Thân thiện</option><option>Ngắn gọn</option><option>Chuyên nghiệp</option></select></label><label>Ngôn ngữ<select v-model="businessProfile.language"><option>Tiếng Việt</option><option>Tiếng Anh</option><option>Song ngữ</option></select></label></div>
          <div class="voice-settings-row"><label class="checkbox-field"><input v-model="voiceSettings.enabled" type="checkbox" /> Đọc tin nhắn thành giọng nói</label><select v-model="voiceSettings.voice" :disabled="!voiceSettings.enabled"><option>Giọng nữ</option><option>Giọng nam</option></select><button type="button" class="secondary-btn" @click="previewWelcomeVoice">Nghe thử lời chào</button></div>
          <div v-if="businessProfileNotice" class="settings-notice" role="status">{{ businessProfileNotice }}</div><button type="button" class="primary-btn" @click="saveBusinessProfile">Lưu thông tin shop</button>
        </div>

        <div v-if="authUser" class="settings-card service-plan-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">GÓI DỊCH VỤ</span><h2>Triển khai cho shop</h2><p>Quản trị viên tạo và kích hoạt gói dịch vụ. Shop chỉ cần cấu hình nội dung, kênh và giờ làm việc.</p></div><span class="connection-badge connected">SẴN SÀNG</span></div>
          <div class="service-plan-grid"><div><strong>Gói hiện tại</strong><span>{{ quotaSnapshot?.plan_name || 'Theo gói đã cấp' }}</span></div><div><strong>Hỗ trợ triển khai</strong><span>Email tài khoản shop</span></div><div><strong>Phạm vi</strong><span>Hội thoại, sản phẩm, chăm sóc</span></div></div>
          <div v-if="serviceRequestNotice" class="settings-notice" role="status">{{ serviceRequestNotice }}</div><button type="button" class="primary-btn" @click="requestServiceDeployment">Chọn gói dịch vụ</button>
        </div>

        <div v-if="authUser" class="settings-card security-card">
          <div class="settings-card-header">
            <div>
              <h2>Bảo mật tài khoản & dữ liệu</h2>
              <p>Quản lý phiên đăng nhập, trạng thái xác thực 2 bước và vòng đời dữ liệu khách hàng.</p>
            </div>
            <button type="button" class="settings-refresh" :disabled="securityLoading" @click="fetchSecuritySettings">{{ securityLoading ? 'Đang tải...' : 'Làm mới' }}</button>
          </div>
          <div v-if="securityError" class="settings-notice team-error">{{ securityError }}</div>
          <div class="security-grid">
            <div class="security-section">
              <div class="security-section-title"><strong>Xác thực 2 bước</strong><span class="connection-badge" :class="{ connected: ['prepared', 'enabled'].includes(authUser.mfa_status) }">{{ authUser.mfa_status === 'enabled' ? 'ĐÃ BẬT' : authUser.mfa_status === 'prepared' ? 'ĐÃ CHUẨN BỊ' : 'CHƯA BẬT' }}</span></div>
              <p class="settings-muted">Mã xác thực được mã hóa khi lưu; phiên mới phải xác minh riêng trước khi dùng CRM.</p>
              <form v-if="mfaVerifyPending" class="settings-actions" @submit.prevent="verifyMfaEnrollment"><input v-model="mfaVerifyCode" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="Mã xác thực 6 số" required /><button class="primary-btn" type="submit">Xác minh mã</button></form>
              <div v-if="['owner', 'admin'].includes(authUser.role)" class="settings-actions">
                <button v-if="!['prepared', 'enabled'].includes(authUser.mfa_status)" type="button" class="settings-refresh" @click="prepareMfaEnrollment">Thiết lập xác thực 2 bước</button>
                <button v-if="['prepared', 'enabled'].includes(authUser.mfa_status)" type="button" class="team-toggle" @click="disableMfaEnrollment">Tắt xác thực 2 bước</button>
              </div>
              <span v-else class="settings-muted">Chỉ chủ shop hoặc quản trị viên được thay đổi xác thực 2 bước.</span>
              <code v-if="mfaProvisioningUri" class="mfa-uri">{{ mfaProvisioningUri }}</code>
            </div>
            <div class="security-section">
              <div class="security-section-title"><strong>Yêu cầu dữ liệu khách hàng</strong><span class="settings-muted">Chỉ dành cho admin</span></div>
              <p class="settings-muted">Xuất dữ liệu được cho phép hoặc ẩn danh/xóa dữ liệu định danh theo yêu cầu.</p>
              <div v-if="['owner', 'admin'].includes(authUser.role)" class="privacy-actions">
                <button type="button" class="settings-refresh" :disabled="privacyLoading" @click="runPrivacyAction('export')">Xuất dữ liệu</button>
                <button type="button" class="settings-refresh" :disabled="privacyLoading" @click="runPrivacyAction('anonymize')">Ẩn danh</button>
                <button type="button" class="team-toggle danger" :disabled="privacyLoading" @click="runPrivacyAction('delete')">Xóa định danh</button>
              </div>
              <span v-else class="settings-muted">Chỉ chủ shop hoặc admin được xử lý yêu cầu dữ liệu.</span>
              <p v-if="privacyResult" class="settings-notice">{{ privacyResult.kind }}: {{ Object.entries(privacyResult.counts || {}).map(([key, value]) => `${key}=${value}`).join(' · ') || 'Đã hoàn tất' }}</p>
            </div>
          </div>
          <div class="security-sessions">
            <div class="security-section-title"><strong>Phiên đăng nhập</strong><span class="settings-muted">{{ authSessions.length }} phiên</span></div>
            <div v-if="!authSessions.length" class="settings-empty">Chưa có thông tin phiên đăng nhập.</div>
            <ul v-else class="session-list">
              <li v-for="session in authSessions" :key="session.id">
                <span><strong>{{ session.device_label || 'Thiết bị không đặt tên' }}</strong><small>Tạo {{ session.created_at ? new Date(session.created_at).toLocaleString('vi-VN') : '—' }} · {{ session.mfa_verified ? 'Đã xác minh 2 bước' : 'Chưa xác minh 2 bước' }}</small></span>
                <button v-if="!session.revoked_at" type="button" class="team-toggle" @click="revokeAuthSession(session)">Thu hồi</button>
                <span v-else class="settings-muted">Đã thu hồi</span>
              </li>
            </ul>
          </div>
        </div>

        <div v-if="authUser" class="settings-card chatbot-runtime-card">
          <div class="settings-card-header">
            <div>
              <h2>🤖 Trợ lý bán hàng</h2>
              <p>Cấu hình tên, giờ hoạt động và các mẫu trả lời an toàn cho nhân viên. Các thông số nâng cao đã được hệ thống đặt sẵn.</p>
            </div>
            <span class="connection-badge" :class="{ connected: chatbotConfig.enabled }">{{ chatbotConfig.enabled ? 'ĐANG BẬT' : 'ĐANG TẮT' }}</span>
          </div>
          <div v-if="chatbotConfigError" class="settings-notice team-error">{{ chatbotConfigError }}</div>
          <form class="chatbot-config-form" @submit.prevent="saveChatbotRuntime">
            <label>Tên trợ lý<input v-model="chatbotConfig.name" maxlength="120" /></label>
            <label v-if="false">Số đoạn thông tin tham khảo<input v-model.number="chatbotConfig.top_k" type="number" min="1" max="20" /></label>
            <label v-if="false">Ngưỡng liên quan<input v-model.number="chatbotConfig.similarity_threshold" type="number" min="0" max="1" step="0.05" /></label>
            <label class="checkbox-field"><input v-model="chatbotConfig.enabled" type="checkbox" /> Cho phép trợ lý trả lời</label>
            <label class="checkbox-field"><input v-model="chatbotConfig.handoff_enabled" type="checkbox" /> Cho phép chuyển nhân viên</label>
            <label v-if="false" class="chatbot-hours-field">Giờ hoạt động (JSON)
              <textarea v-model="businessHoursJson" rows="5" spellcheck="false" placeholder='{"timezone":"Asia/Ho_Chi_Minh","mon":[["08:00","17:30"]]}'></textarea>
            </label>
            <button class="primary-btn" type="submit" :disabled="chatbotConfigSaving">{{ chatbotConfigSaving ? 'Đang lưu...' : 'Lưu cấu hình trợ lý' }}</button>
          </form>

          <div class="canned-response-panel">
            <div class="settings-card-header"><div><h3>Mẫu trả lời nhanh</h3><p>Ví dụ /cod, /doi-tra, /ship. Trợ lý chỉ dùng những mẫu shop đã lưu.</p></div></div>
            <div v-if="cannedResponseError" class="settings-notice team-error">{{ cannedResponseError }}</div>
            <form class="canned-response-form" @submit.prevent="saveCannedResponse">
              <input v-model="cannedResponseForm.shortcut" required placeholder="/cod" />
              <input v-model="cannedResponseForm.title" required placeholder="Tên mẫu" />
              <input v-model="cannedResponseForm.content" required placeholder="Nội dung trả lời" />
              <button class="settings-refresh" type="submit" :disabled="cannedResponseSaving">Thêm mẫu</button>
            </form>
            <ul v-if="cannedResponses.length" class="canned-response-list">
              <li v-for="item in cannedResponses" :key="item.id"><strong>{{ item.shortcut }}</strong><span>{{ item.title }}</span><small>{{ item.content }}</small></li>
            </ul>
            <p v-else class="settings-empty">Chưa có mẫu trả lời.</p>
          </div>
        </div>

        <div v-if="authUser" class="settings-card followup-card">
          <div class="settings-card-header">
            <div>
              <h2>🔔 Chăm sóc chủ động</h2>
              <p>Nhắc khách xác nhận đơn nháp hoặc chăm sóc lại theo lịch.</p>
            </div>
            <button type="button" class="settings-refresh" :disabled="followupDispatching" @click="dispatchFollowups">{{ followupDispatching ? 'Đang chạy...' : 'Chạy lịch nhắc đến hạn' }}</button>
          </div>
          <div v-if="followupNotice" class="settings-notice" role="status" aria-live="polite">{{ followupNotice }}</div>
          <div v-if="followupError" class="settings-notice team-error" role="alert">{{ followupError }}</div>
          <div v-if="followupsLoading" class="settings-empty">Đang tải lịch chăm sóc...</div>
          <div v-else-if="!followups.length" class="settings-empty">Chưa có lịch nhắc chăm sóc đang chờ.</div>
          <ul v-else class="followup-list">
            <li v-for="item in followups" :key="item.id">
              <div><strong>{{ followupProductLabel(item) }}</strong><small>{{ new Date(item.run_at).toLocaleString('vi-VN') }}</small></div>
              <span>{{ item.message }}<small v-if="followupRecommendationLabel(item)" class="followup-recommendation">Gợi ý mua thêm: {{ followupRecommendationLabel(item) }}</small></span>
              <button type="button" class="history-btn" @click="cancelFollowup(item)">Hủy</button>
            </li>
          </ul>
        </div>

        <div v-if="authUser" class="settings-card learning-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">CẢI THIỆN TRỢ LÝ</span><h2>Học từ hội thoại</h2><p>Lưu phản hồi và tin nhắn đã duyệt để trợ lý trả lời tốt hơn ở lần sau.</p></div><span class="connection-badge connected">ĐANG BẬT</span></div>
          <div class="learning-options"><label class="checkbox-field"><input v-model="messageLearningEnabled" type="checkbox" /> Lưu tin nhắn đã chọn làm mẫu tham khảo</label><label class="checkbox-field"><input v-model="reinforcementLearningEnabled" type="checkbox" /> Tự cải thiện từ đánh giá của khách</label></div>
          <p class="settings-muted">Hệ thống chỉ học các cuộc trò chuyện được shop cho phép; dữ liệu vẫn tách riêng theo từng shop.</p><div v-if="learningNotice" class="settings-notice" role="status">{{ learningNotice }}</div><button type="button" class="primary-btn" @click="saveLearningPreferences">Lưu lựa chọn</button>
        </div>

        <div v-if="authUser" class="settings-card csat-card">
          <div class="settings-card-header">
            <div>
              <h2>⭐ Đánh giá hài lòng</h2>
              <p>Khách có thể trò chuyện trực tiếp với trợ lý; sau khi được hỗ trợ, họ nhận khảo sát 1–5 sao và phản hồi được ghi nhận tại đây.</p>
            </div>
            <button type="button" class="settings-refresh" :disabled="csatLoading" @click="fetchCsat">Làm mới</button>
          </div>
          <div v-if="csatError" class="settings-notice team-error" role="alert">{{ csatError }}</div>
          <div class="csat-summary-grid">
            <div><strong>{{ csatSummary.average_rating.toFixed(1) }}/5</strong><span>Điểm hài lòng</span></div>
            <div><strong>{{ Math.round(csatSummary.satisfaction_rate * 100) }}%</strong><span>Tỷ lệ hài lòng</span></div>
            <div><strong>{{ csatSummary.responses }}</strong><span>Lượt đánh giá</span></div>
            <div><strong>{{ Math.round(csatSummary.bot_resolution_rate * 100) }}%</strong><span>Trợ lý tự xử lý</span></div>
          </div>
          <div v-if="!csatLoading && !csatFeedback.length" class="settings-empty">Chưa có phản hồi đánh giá.</div>
          <ul v-else class="csat-feedback-list">
            <li v-for="item in csatFeedback.slice(0, 5)" :key="item.id">
              <div><strong>{{ item.rating ? `${item.rating}/5 sao` : 'Chờ đánh giá' }}</strong><small>{{ new Date(item.requested_at).toLocaleString('vi-VN') }}</small></div>
              <span>{{ item.comment || (item.status === 'sent' ? 'Đã gửi khảo sát, đang chờ khách trả lời.' : 'Đang chờ gửi khảo sát.') }}</span>
            </li>
          </ul>
        </div>

        <div v-if="platformAdmin" class="settings-card platform-admin-card">
          <div class="settings-card-header">
            <div>
              <h2>Quản trị Smart Merchant Hub</h2>
              <p>Tạo/kích hoạt gói dịch vụ, khóa/mở shop, xem hạn mức và tách kho dữ liệu riêng cho từng shop.</p>
            </div>
            <button type="button" class="settings-refresh" :disabled="platformLoading" @click="fetchPlatformAdmin">{{ platformLoading ? 'Đang tải...' : 'Làm mới' }}</button>
          </div>
          <div v-if="platformError" class="settings-notice team-error">{{ platformError }}</div>
          <div v-if="!platformShops.length" class="settings-empty">Chưa có shop trên nền tảng.</div>
          <div v-else class="platform-table-wrap">
            <table class="team-table platform-table">
              <thead><tr><th>Shop</th><th>Trạng thái</th><th>Hạn mức đã dùng</th><th></th></tr></thead>
              <tbody>
                <tr v-for="shop in platformShops" :key="shop.id">
                  <td><strong>{{ shop.name }}</strong><small>{{ shop.slug }} · {{ shop.plan_name || 'Chưa có gói' }}</small></td>
                  <td><span class="team-status" :class="{ inactive: shop.status === 'suspended' }">{{ shop.status === 'suspended' ? 'Đã khóa' : 'Đang hoạt động' }}</span></td>
                  <td><small v-if="Object.keys(shop.usage || {}).length">{{ Object.entries(shop.usage).map(([key, value]) => `${key}: ${value}`).join(' · ') }}</small><small v-else>Chưa ghi nhận</small></td>
                  <td><button type="button" class="team-toggle" @click="togglePlatformShop(shop)">{{ shop.status === 'suspended' ? 'Mở shop' : 'Khóa shop' }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="platform-schema-panel">
            <div class="settings-card-header"><div><h3>Thử nghiệm tách kho dữ liệu theo shop</h3><p>Chỉ ghi danh sách theo dõi; chưa chuyển dữ liệu CRM hiện tại.</p></div></div>
            <div v-if="!platformSchemas.length" class="settings-empty">Chưa đăng ký shop thử nghiệm.</div>
            <ul v-else class="permission-list">
              <li v-for="schema in platformSchemas" :key="schema.id">
                <strong>Shop #{{ schema.business_id }} · {{ schema.schema_name }}</strong>
                <span>{{ schema.feature_enabled ? 'Đang bật thử nghiệm' : `Trạng thái: ${schemaStateLabel(schema.state)}` }}</span>
                <button type="button" class="history-btn" @click="stagePlatformSchema(schema)">{{ schema.state === 'ready' ? 'Tắt thử nghiệm' : 'Bật thử nghiệm' }}</button>
              </li>
            </ul>
            <div v-if="platformShops.some((shop) => !platformSchemas.some((schema) => schema.business_id === shop.id))" class="platform-schema-actions">
              <button v-for="shop in platformShops.filter((item) => !platformSchemas.some((schema) => schema.business_id === item.id))" :key="shop.id" type="button" class="settings-refresh" @click="registerPlatformSchema(shop.id)">Đăng ký tách dữ liệu cho {{ shop.name }}</button>
            </div>
          </div>
          <div class="platform-audit-panel">
            <div class="settings-card-header"><div><h3>Nhật ký nền tảng</h3><p>Thao tác khóa/mở shop, gói, thanh toán và tách kho dữ liệu.</p></div></div>
            <p v-if="!platformAuditLogs.length" class="settings-empty">Chưa có audit nền tảng.</p>
            <ul v-else class="audit-list">
              <li v-for="log in platformAuditLogs.slice(0, 10)" :key="log.id">
                <strong>{{ log.action }}</strong>
                <span> · {{ resourceLabel(log.resource_type) }}{{ log.resource_id ? ` #${log.resource_id}` : '' }}</span>
                <small>{{ log.created_at ? new Date(log.created_at).toLocaleString('vi-VN') : '' }}</small>
              </li>
            </ul>
          </div>
          <div class="platform-audit-panel provider-error-panel">
            <div class="settings-card-header"><div><h3>Lỗi kênh gần đây</h3><p>Chỉ hiển thị loại lỗi và kênh; không hiển thị dữ liệu hay mã bảo vệ.</p></div></div>
            <p v-if="!platformProviderErrors.length" class="settings-empty">Chưa có lỗi kênh.</p>
            <ul v-else class="audit-list">
              <li v-for="errorItem in platformProviderErrors.slice(0, 10)" :key="errorItem.id"><strong>{{ channelLabel(errorItem.channel_type) }}</strong><span> · {{ workflowEventLabel(errorItem.event_type) }} · {{ errorItem.error_type || 'Lỗi kết nối' }}</span><small>{{ errorItem.received_at ? new Date(errorItem.received_at).toLocaleString('vi-VN') : '' }}</small></li>
            </ul>
          </div>
        </div>

        <div v-if="authUser" class="settings-card team-card">
          <div class="settings-card-header">
            <div>
              <h2>👥 Đội ngũ & phân quyền</h2>
              <p>Quản lý nhân viên thuộc shop và trạng thái được phép nhận phiếu hỗ trợ.</p>
            </div>
            <button type="button" class="settings-refresh" @click="fetchTeam">Làm mới</button>
          </div>

          <div v-if="teamError" class="settings-notice team-error">{{ teamError }}</div>

          <form class="team-form" @submit.prevent="saveTeamMember">
            <input v-model="teamForm.full_name" required maxlength="255" placeholder="Họ và tên" />
            <input v-model="teamForm.email" required type="email" maxlength="255" placeholder="Email công việc" />
            <input v-model="teamForm.password" required type="password" minlength="8" maxlength="256" placeholder="Mật khẩu (≥ 8 ký tự)" />
            <select v-model="teamForm.role" aria-label="Vai trò nhân viên">
              <option value="admin">Quản trị viên</option>
              <option value="agent">Nhân viên</option>
              <option value="viewer">Chỉ xem</option>
            </select>
            <button class="primary-btn" type="submit" :disabled="teamSaving">
              {{ teamSaving ? 'Đang thêm...' : 'Thêm nhân viên' }}
            </button>
          </form>

          <div v-if="teamLoading" class="settings-empty">Đang tải đội ngũ...</div>
          <div v-else-if="!teamUsers.length" class="settings-empty">Chưa có nhân viên nào.</div>
          <div v-else class="team-table-wrap">
            <table class="team-table">
              <thead><tr><th>Nhân viên</th><th>Vai trò</th><th>Trạng thái</th><th></th></tr></thead>
              <tbody>
                <tr v-for="member in teamUsers" :key="member.id">
                  <td><strong>{{ member.full_name }}</strong><small>{{ member.email }}</small></td>
                  <td><span class="team-role">{{ roleLabel(member.role) }}</span></td>
                  <td><span class="team-status" :class="{ inactive: !member.is_active }">{{ member.is_active ? 'Đang hoạt động' : 'Đã vô hiệu hóa' }}</span></td>
                  <td><button type="button" class="team-toggle" @click="toggleTeamMember(member)">{{ member.is_active ? 'Vô hiệu hóa' : 'Kích hoạt' }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="permission-panel">
            <div class="settings-card-header">
              <div>
                <h3>Quyền chi tiết</h3>
                <p>Ghi đè quyền theo vai trò hoặc một nhân viên cụ thể. Từ chối luôn được ưu tiên.</p>
              </div>
            </div>
            <div v-if="permissionError" class="settings-notice team-error">{{ permissionError }}</div>
            <form class="permission-form" @submit.prevent="savePermissionOverride">
              <label>Tài nguyên
                <select v-model="permissionForm.resource">
                  <option value="customers">Khách hàng</option>
                  <option value="orders">Đơn hàng</option>
                  <option value="tickets">Phiếu hỗ trợ</option>
                  <option value="team">Đội ngũ</option>
                  <option value="reports">Báo cáo</option>
                  <option value="documents">Kho tri thức</option>
                </select>
              </label>
              <label>Hành động
                <select v-model="permissionForm.action">
                  <option value="read">Xem</option>
                  <option value="write">Tạo / sửa</option>
                </select>
              </label>
              <label>Hiệu lực
                <select v-model="permissionForm.effect">
                  <option value="deny">Từ chối</option>
                  <option value="allow">Cho phép</option>
                </select>
              </label>
              <label>Áp dụng cho vai trò
                <select v-model="permissionForm.role">
                  <option value="">Không chọn vai trò</option>
                  <option value="owner">Chủ shop</option>
                  <option value="admin">Quản trị viên</option>
                  <option value="agent">Nhân viên</option>
                  <option value="viewer">Chỉ xem</option>
                </select>
              </label>
              <label>Hoặc nhân viên
                <select v-model="permissionForm.user_id">
                  <option value="">Không chọn nhân viên</option>
                  <option v-for="member in teamUsers" :key="member.id" :value="member.id">{{ member.full_name }}</option>
                </select>
              </label>
              <button class="primary-btn" type="submit" :disabled="permissionSaving || (!permissionForm.role && !permissionForm.user_id)">
                {{ permissionSaving ? 'Đang lưu...' : 'Thêm quy tắc' }}
              </button>
            </form>
            <div v-if="!permissionOverrides.length" class="settings-empty">Chưa có quy tắc ghi đè.</div>
            <ul v-else class="permission-list">
              <li v-for="override in permissionOverrides" :key="override.id">
                <strong>{{ resourceLabel(override.resource) }} · {{ override.action === 'read' ? 'Xem' : 'Tạo / sửa' }}</strong>
                <span :class="override.effect === 'deny' ? 'permission-deny' : 'permission-allow'">{{ override.effect === 'deny' ? 'Từ chối' : 'Cho phép' }}</span>
                <small>{{ override.role ? `Vai trò: ${roleLabel(override.role)}` : `Nhân viên #${override.user_id}` }}</small>
                <button type="button" class="history-btn" :disabled="permissionSaving" @click="deletePermissionOverride(override)">Xóa quy tắc</button>
              </li>
            </ul>
          </div>

          <div v-if="authUser && ['owner', 'admin'].includes(authUser.role)" class="audit-panel">
            <div class="settings-card-header">
              <div><h3>Nhật ký thao tác</h3><p>Thông tin nhạy cảm như mật khẩu, mã kết nối và nội dung tin nhắn luôn được ẩn.</p></div>
              <button type="button" class="settings-refresh" @click="fetchAuditLogs">{{ auditLoading ? 'Đang tải...' : 'Làm mới' }}</button>
            </div>
            <div v-if="!auditLogs.length" class="settings-empty">Chưa có nhật ký thao tác.</div>
            <ul v-else class="audit-list">
              <li v-for="log in auditLogs.slice(0, 10)" :key="log.id"><strong>{{ log.action }}</strong> · {{ resourceLabel(log.resource_type) }} {{ log.resource_id ? `#${log.resource_id}` : '' }} · {{ log.created_at ? new Date(log.created_at).toLocaleString('vi-VN') : '' }}</li>
            </ul>
          </div>
        </div>
      </section>

      <section v-if="currentTab === 'service'" class="service-page-layout" aria-label="Gói dịch vụ">
        <div class="service-page-hero">
          <div>
            <span class="service-page-kicker">TRIỂN KHAI CHO SHOP</span>
            <h1>Chọn cách shop muốn được hỗ trợ</h1>
            <p>Chọn gói quản lý shop để tự vận hành hoặc thuê trọn gói trợ lý chatbot. Đội ngũ sẽ tư vấn và bàn giao theo nhu cầu của bạn.</p>
          </div>
          <button v-if="!authUser" type="button" class="service-back-link" @click="closePublicServicePage">← Quay lại đăng nhập</button>
          <button v-else type="button" class="service-back-link" @click="openServicePage">Chọn gói dịch vụ</button>
        </div>

        <div class="service-mode-switch" role="tablist" aria-label="Chọn dịch vụ">
          <button type="button" class="service-mode-option" :class="{ selected: serviceMode === 'package' }" role="tab" :aria-selected="serviceMode === 'package'" @click="selectServiceMode('package')">
            <span class="service-mode-icon" aria-hidden="true">▦</span>
            <span><strong>Gói quản lý shop</strong><small>Shop tự quản lý nội dung, nhân viên và các kênh bán hàng.</small></span>
            <em>{{ serviceMode === 'package' ? 'Đang chọn' : 'Chọn gói' }}</em>
          </button>
          <button type="button" class="service-mode-option" :class="{ selected: serviceMode === 'chatbot' }" role="tab" :aria-selected="serviceMode === 'chatbot'" @click="selectServiceMode('chatbot')">
            <span class="service-mode-icon" aria-hidden="true">✦</span>
            <span><strong>Thuê riêng trợ lý chatbot</strong><small>Đội ngũ cài nội dung, kết nối kênh và theo dõi giúp shop.</small></span>
            <em>{{ serviceMode === 'chatbot' ? 'Đang chọn' : 'Chọn dịch vụ' }}</em>
          </button>
        </div>

        <article v-if="authUser" class="service-account-card">
          <div class="service-account-heading">
            <div><span class="service-page-kicker">THÔNG TIN NGƯỜI MUA</span><h2>Gói của shop</h2><p>Thông tin lấy trực tiếp từ tài khoản hiện tại, chỉ hiển thị trong shop này.</p></div>
            <button type="button" class="settings-refresh" :disabled="serviceAccountLoading" @click="fetchServiceAccountSummary">{{ serviceAccountLoading ? 'Đang tải...' : 'Làm mới' }}</button>
          </div>
          <div v-if="serviceAccountError" class="service-request-error" role="alert">{{ serviceAccountError }}</div>
          <div v-else-if="serviceAccountSummary" class="service-account-grid">
            <div><span>Người mua</span><strong>{{ serviceAccountSummary.buyer?.name || '—' }}</strong><small>{{ serviceAccountSummary.buyer?.email || '—' }}</small></div>
            <div><span>Tên shop</span><strong>{{ serviceAccountSummary.buyer?.shop_name || '—' }}</strong><small>{{ serviceAccountSummary.buyer?.phone || 'Chưa cập nhật số điện thoại' }}</small></div>
            <div><span>Gói đang dùng</span><strong>{{ serviceAccountSummary.subscription?.plan_name || 'Chưa chọn gói' }}</strong><small>{{ serviceAccountSummary.subscription?.status === 'active' ? 'Đang hoạt động' : 'Chưa kích hoạt' }}</small></div>
            <div><span>Thanh toán gần nhất</span><strong>{{ serviceAccountSummary.amount == null ? 'Chưa có' : `${Number(serviceAccountSummary.amount).toLocaleString('vi-VN')}đ` }}</strong><small>{{ serviceAccountSummary.payment_status === 'paid' ? 'Đã thanh toán' : 'Chưa ghi nhận thanh toán' }}</small></div>
            <div><span>Kênh đang dùng</span><strong>{{ serviceAccountSummary.connected_channels }} / {{ serviceAccountSummary.channel_limit ?? '—' }}</strong><small>Facebook, Instagram, Telegram, Zalo</small></div>
          </div>
          <div v-else class="settings-empty">Chưa có thông tin gói. Hãy chọn một gói bên dưới.</div>
        </article>

        <div class="service-page-grid">
          <article class="service-benefits-card">
            <span class="service-page-kicker">SHOP NHẬN ĐƯỢC GÌ</span>
            <h2>{{ serviceMode === 'chatbot' ? 'Trợ lý được bàn giao theo đúng cách shop phục vụ' : 'Một gói quản lý rõ ràng từ lúc đăng ký đến lúc chạy thật' }}</h2>
            <ol class="service-steps">
              <li><span>01</span><div><strong>Tư vấn nhu cầu</strong><small>Chọn kênh, giờ làm và cách shop muốn chăm khách.</small></div></li>
              <li><span>02</span><div><strong>Cài đặt &amp; kết nối</strong><small>{{ serviceMode === 'chatbot' ? 'Đội ngũ chuẩn bị nội dung và kết nối các kênh cho shop.' : 'Quản trị viên cấp gói, shop cấu hình nội dung và nhân viên.' }}</small></div></li>
              <li><span>03</span><div><strong>Bàn giao &amp; theo dõi</strong><small>{{ serviceMode === 'chatbot' ? 'Shop kiểm tra câu trả lời và nhận hỗ trợ khi cần.' : 'Shop theo dõi hội thoại, công việc và quyền sử dụng trong gói.' }}</small></div></li>
            </ol>
            <div class="service-trust-note">Dữ liệu, mã kết nối và lịch sử hội thoại luôn tách riêng theo từng shop.</div>
          </article>

          <article class="service-request-card">
            <div v-if="serviceRequestSubmitted" class="service-request-success" role="status">
              <div class="service-success-icon">✓</div>
              <span class="service-page-kicker">ĐÃ GỬI YÊU CẦU</span>
              <h2>{{ serviceMode === 'chatbot' ? 'Chúng tôi sẽ tư vấn gói trợ lý' : 'Chúng tôi sẽ tư vấn gói phù hợp' }}</h2>
              <p>Mã yêu cầu <strong>{{ serviceRequestReference }}</strong>. Bạn có thể dùng mã này khi trao đổi với đội ngũ triển khai.</p>
              <button type="button" class="secondary-btn" @click="resetServiceRequestForm">Gửi yêu cầu khác</button>
            </div>
            <form v-else class="service-request-form" @submit.prevent="submitServiceRequest">
              <div class="service-request-heading"><div><span class="service-page-kicker">CHỌN GÓI</span><h2>{{ serviceMode === 'chatbot' ? 'Thuê riêng trợ lý chatbot' : 'Mua gói dịch vụ cho shop' }}</h2></div><span class="service-request-badge">Kích hoạt demo</span></div>
              <p class="service-request-intro">{{ serviceMode === 'chatbot' ? 'Chọn mức hỗ trợ để đội ngũ cài nội dung, kết nối kênh và bàn giao trợ lý cho shop.' : 'Chọn gói phù hợp với số kênh và số nhân viên. Shop có thể kích hoạt ngay trong môi trường demo.' }}</p>
              <div v-if="serviceRequestError" class="service-request-error" role="alert">{{ serviceRequestError }}</div>
              <div class="service-request-fields">
                <label>Người liên hệ<input v-model="serviceRequestForm.contact_name" required maxlength="120" placeholder="Nguyễn Văn A" /></label>
                <label>Email nhận tư vấn<input v-model="serviceRequestForm.email" required type="email" maxlength="255" placeholder="banhang@shop.vn" /></label>
                <label>Số điện thoại <span>(không bắt buộc)</span><input v-model="serviceRequestForm.phone" type="tel" maxlength="30" placeholder="0901 234 567" /></label>
                <label>Tên shop<input v-model="serviceRequestForm.shop_name" required maxlength="160" placeholder="Shop của bạn" /></label>
              </div>
              <fieldset class="service-plan-picker"><legend>{{ serviceMode === 'chatbot' ? 'Chọn mức hỗ trợ' : 'Chọn gói quản lý shop' }}</legend><div class="service-plan-options"><label v-for="plan in activeServicePlans" :key="plan.code" class="service-plan-option" :class="{ selected: serviceRequestForm.plan_code === plan.code }"><input v-model="serviceRequestForm.plan_code" type="radio" name="service-plan" :value="plan.code" /><span><strong>{{ plan.name }}</strong><small>{{ plan.description }}</small><em>{{ plan.price }}</em></span></label></div></fieldset>
              <div v-if="authUser" class="service-purchase-box">
                <div><strong>Muốn dùng ngay cho shop?</strong><small>Ở môi trường demo, bạn có thể kích hoạt gói đã chọn ngay để mở kết nối kênh và hạn mức nhân viên.</small></div>
                <button type="button" class="secondary-btn" :disabled="servicePurchaseLoading" @click="purchaseServicePlan">{{ servicePurchaseLoading ? 'Đang kích hoạt...' : 'Kích hoạt gói cho demo' }}</button>
              </div>
              <div v-if="servicePurchaseError" class="service-request-error" role="alert">{{ servicePurchaseError }}</div>
              <div v-if="servicePurchaseNotice" class="service-purchase-notice" role="status">
                <span>{{ servicePurchaseNotice }}</span>
                <div class="service-purchase-actions">
                  <button type="button" class="secondary-btn" @click="openChannels">Mở kết nối kênh</button>
                  <button type="button" class="history-btn" @click="openSettings">Quản lý nhân viên</button>
                </div>
              </div>
              <fieldset class="service-channel-picker"><legend>Shop muốn kết nối kênh nào?</legend><div class="service-channel-options"><label v-for="channel in ['Facebook', 'Instagram', 'Telegram', 'Zalo']" :key="channel" :class="{ selected: serviceRequestForm.channels.includes(channel) }"><input type="checkbox" :checked="serviceRequestForm.channels.includes(channel)" @change="toggleServiceChannel(channel)" /><span>{{ channel }}</span></label></div></fieldset>
              <label class="service-request-notes">Ghi chú thêm <span>(không bắt buộc)</span><textarea v-model="serviceRequestForm.notes" rows="3" maxlength="1000" placeholder="Ví dụ: shop cần bot trả lời ngoài giờ hoặc hỗ trợ nhiều nhân viên..."></textarea></label>
              <button type="submit" class="primary-btn service-submit">{{ serviceMode === 'chatbot' ? 'Đăng ký thuê trợ lý' : 'Đăng ký thuê gói' }} <span aria-hidden="true">→</span></button>
              <small class="service-form-footnote">Bằng việc gửi yêu cầu, bạn đồng ý để đội ngũ liên hệ theo thông tin đã nhập.</small>
            </form>
          </article>
        </div>
      </section>


    </main>

    <section v-else class="login-page" data-testid="login-page" aria-label="Đăng nhập CRM">
      <div class="login-orb login-orb-one" aria-hidden="true"></div>
      <div class="login-orb login-orb-two" aria-hidden="true"></div>
      <div class="login-shell">
        <div class="login-showcase">
          <div class="login-brand-lockup">
            <div class="login-brand-mark" aria-hidden="true">
              <svg viewBox="0 0 48 48">
                <path d="M7 20h34v20H7z" fill="currentColor" opacity=".18" />
                <path d="M5 19 9 8h30l4 11-4 5H9z" fill="currentColor" />
                <path d="M9 19h30v21H9z" fill="currentColor" opacity=".85" />
                <path d="M18 40V27h12v13M13 25h3v5h-3zm19 0h3v5h-3z" fill="#fffaf8" />
                <path d="M8 18h32" stroke="#fffaf8" stroke-width="3" stroke-linecap="round" />
              </svg>
            </div>
            <div><strong>Smart Merchant Hub</strong><span>Không gian quản lý shop</span></div>
          </div>
          <span class="login-eyebrow">CỔNG VẬN HÀNH SHOP</span>
          <h1>Chăm khách gọn hơn,<br /><em>bán hàng chắc hơn.</em></h1>
          <p class="login-showcase-copy">Một nơi để đội ngũ xử lý hội thoại, đơn bán và các công việc cần người thật — rõ ràng theo từng shop.</p>
          <div class="login-feature-list">
            <div><span class="login-feature-icon">✓</span><span><strong>Hộp thư hợp nhất</strong><small>Không bỏ sót khách từ mọi kênh.</small></span></div>
            <div><span class="login-feature-icon">✓</span><span><strong>Quy trình có kiểm soát</strong><small>Trạng thái, thời hạn và nhật ký rõ ràng.</small></span></div>
            <div><span class="login-feature-icon">✓</span><span><strong>Dữ liệu riêng từng shop</strong><small>Phân quyền theo không gian của bạn.</small></span></div>
          </div>
        </div>

        <div class="login-card">
          <div class="login-card-topline">
            <span class="login-card-kicker">CHÀO MỪNG TRỞ LẠI</span>
            <span class="login-security-pill"><i></i> Kết nối bảo mật</span>
          </div>
          <div class="login-card-heading">
            <h2>Đăng nhập CRM</h2>
            <p>Sử dụng tài khoản đã được cấp để tiếp tục xử lý không gian của shop.</p>
          </div>
          <form class="login-form" @submit.prevent="login">
            <label>Email công việc<input v-model="loginForm.email" required type="email" autocomplete="username" placeholder="banhang@shop.vn" /></label>
            <label>Mật khẩu<input v-model="loginForm.password" required type="password" autocomplete="current-password" placeholder="Nhập mật khẩu" /></label>
            <label>Mã shop <span>(không bắt buộc)</span><input v-model="loginForm.shop_slug" type="text" maxlength="120" autocomplete="organization" placeholder="shop-cua-ban" /></label>
            <button class="login-submit" type="submit" :disabled="authLoading || authRateLimitSeconds > 0">
              <span>{{ authLoading ? 'Đang xác thực...' : authRateLimitSeconds > 0 ? 'Tạm khóa đăng nhập' : 'Đăng nhập' }}</span>
              <span class="login-submit-arrow" aria-hidden="true">→</span>
            </button>
          </form>
          <div v-if="authError" class="login-alert" role="alert">{{ authError }}</div>
          <div v-if="authRateLimitSeconds > 0" class="login-rate-limit" role="status">
            <span class="login-rate-limit-icon" aria-hidden="true">⏱</span>
            <span>Quá nhiều lần thử. Thử lại sau <strong>{{ formatRateLimitDuration(authRateLimitSeconds) }}</strong>.</span>
          </div>
          <small class="login-footer-note">Phiên làm việc được ghi lại đầy đủ và áp dụng đúng quyền của bạn.</small>
          <button type="button" class="login-service-link" @click="openPublicServicePage">Xem gói dịch vụ và thuê chatbot →</button>
        </div>
      </div>
    </section>

    <div
      v-if="appDialog"
      class="app-dialog-backdrop"
      role="presentation"
      @click.self="resolveAppDialog(false)"
      @keydown.esc="resolveAppDialog(false)"
    >
      <section class="app-dialog" role="dialog" aria-modal="true" aria-labelledby="app-dialog-title">
        <div class="app-dialog-icon" :class="`app-dialog-icon-${appDialog.tone}`">!</div>
        <div class="app-dialog-content">
          <h3 id="app-dialog-title">{{ appDialog.title }}</h3>
          <p>{{ appDialog.message }}</p>
        </div>
        <div class="app-dialog-actions">
          <button type="button" class="app-dialog-cancel" @click="resolveAppDialog(false)">{{ appDialog.cancelLabel }}</button>
          <button type="button" class="app-dialog-confirm" :class="{ 'is-danger': appDialog.tone === 'danger' }" @click="resolveAppDialog(true)">{{ appDialog.confirmLabel }}</button>
        </div>
      </section>
    </div>

  </div>

</template>


<style scoped>

/* =========================================================
   MEDIA MESSAGE
========================================================= */

.message-media-link {
  display: block;
  max-width: 100%;
  text-decoration: none;
}


.message-image {
  display: block;

  width: clamp(160px, 32vw, 320px);
  max-width: 100%;

  height: auto;
  max-height: 420px;

  object-fit: cover;

  border-radius: 14px;

  cursor: pointer;
}


.message-video {
  display: block;

  width: 100%;
  max-width: 320px;

  max-height: 420px;

  border-radius: 14px;

  background: #000;
}


.message-attachment {
  display: inline-block;

  padding: 8px 10px;

  text-decoration: none;

  font-weight: 600;

  border-radius: 10px;
}


.message-text {
  margin-top: 6px;
}


.retry-message {
  margin-left: 6px;
  padding: 0;
  color: #d62432;
  background: transparent;
  border: 0;
  font-size: 9px;
  font-weight: 800;
  text-decoration: underline;
}


/* =========================================================
   IMAGE PREVIEW
========================================================= */

.hidden-file-input {
  display: none;
}


.image-preview-box {
  display: flex;
  align-items: center;
  gap: 12px;

  margin: 8px 14px;
  padding: 10px;

  border: 1px solid
    rgba(0, 0, 0, 0.08);

  border-radius: 14px;

  background: #fff;
}


.image-preview-box img {
  width: 85px;
  height: 85px;

  object-fit: cover;

  border-radius: 12px;
}


.image-preview-info {
  display: flex;
  flex-direction: column;
  align-items: flex-start;

  gap: 8px;

  min-width: 0;
}


.image-preview-info span {
  max-width: 250px;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

  font-size: 13px;
}


.image-preview-info button {
  border: none;
  background: transparent;

  cursor: pointer;

  font-size: 12px;
  font-weight: 700;
}


/* =========================================================
   AVATAR
========================================================= */

.avatar {
  overflow: hidden;
}



/* =========================================================
   RAG KNOWLEDGE BASE & CHAT STYLES
========================================================= */

.rag-docs-layout,
.rag-chat-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 24px;
  height: calc(100vh - 90px);
  overflow-y: auto;
  box-sizing: border-box;
}

.rag-header-panel {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #ffffff;
  padding: 20px 24px;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.rag-header-panel h2 {
  margin: 0 0 6px 0;
  font-size: 20px;
  color: #1a202c;
}

.rag-header-panel p {
  margin: 0;
  color: #718096;
  font-size: 13px;
  max-width: 600px;
}

.rag-stats {
  display: flex;
  gap: 16px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #f7fafc;
  padding: 12px 20px;
  border-radius: 12px;
  min-width: 90px;
  border: 1px solid #e2e8f0;
}

.stat-num {
  font-size: 22px;
  font-weight: 800;
  color: #2b6cb0;
}

.font-green {
  color: #38a169;
}

.stat-label {
  font-size: 11px;
  color: #718096;
  font-weight: 600;
}

/* DROPZONE */
.upload-dropzone {
  border: 2px dashed #cbd5e0;
  border-radius: 16px;
  padding: 32px;
  text-align: center;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s ease;
}

.upload-dropzone:hover {
  border-color: #3182ce;
  background: #ebf8ff;
}

.dropzone-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.upload-icon, .spinner-icon {
  font-size: 36px;
}

.dropzone-content strong {
  font-size: 15px;
  color: #2d3748;
}

.dropzone-content small {
  color: #a0aec0;
  font-size: 12px;
}

.error-banner {
  background: #fed7d7;
  color: #9b2c2c;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 13px;
}

/* DOCS TABLE CARD */
.docs-table-card {
  background: #ffffff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  color: #2d3748;
}

.btn-refresh {
  background: #edf2f7;
  border: none;
  padding: 8px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
  color: #4a5568;
}

.btn-refresh:hover {
  background: #e2e8f0;
}

.docs-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.docs-table th {
  background: #f7fafc;
  padding: 12px 16px;
  font-size: 12px;
  color: #718096;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 2px solid #edf2f7;
}

.docs-table td {
  padding: 14px 16px;
  border-bottom: 1px solid #edf2f7;
  font-size: 13px;
  color: #2d3748;
}

.badge-type {
  background: #eef2ff;
  color: #4f46e5;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 11px;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-ready { background: #c6f6d5; color: #22543d; }
.status-processing { background: #feebc8; color: #744210; }
.status-pending { background: #e2e8f0; color: #4a5568; }
.status-error { background: #fed7d7; color: #742a2a; }

.btn-delete {
  background: #fff5f5;
  color: #e53e3e;
  border: 1px solid #feb2b2;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.btn-delete:hover {
  background: #fed7d7;
}

.empty-docs-state, .loading-state {
  text-align: center;
  padding: 40px;
  color: #a0aec0;
  font-size: 14px;
}

/* RAG CHAT PLAYGROUND */
.rag-chat-layout {
  flex-direction: row;
}

.rag-chat-sidebar {
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.setting-card {
  background: #ffffff;
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.setting-card h3 {
  margin: 0 0 8px 0;
  font-size: 15px;
  color: #2d3748;
}

.setting-desc {
  font-size: 12px;
  color: #718096;
  margin: 0 0 12px 0;
  line-height: 1.4;
}

.toggle-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
}

.toggle-switch {
  width: 100px;
  height: 32px;
  background: #cbd5e0;
  border: none;
  border-radius: 16px;
  cursor: pointer;
  position: relative;
  transition: background 0.3s;
  display: flex;
  align-items: center;
  padding: 0 8px;
}

.toggle-switch.active {
  background: #38a169;
}

.toggle-knob {
  width: 24px;
  height: 24px;
  background: #ffffff;
  border-radius: 50%;
  position: absolute;
  left: 4px;
  transition: transform 0.3s;
}

.toggle-switch.active .toggle-knob {
  transform: translateX(68px);
}

.toggle-text {
  font-size: 10px;
  font-weight: 800;
  color: #ffffff;
  margin-left: 28px;
}

.toggle-switch.active .toggle-text {
  margin-left: 8px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #4a5568;
}

.range-slider {
  width: 100%;
}

.config-val {
  font-weight: 700;
  color: #2b6cb0;
}

.quick-questions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quick-questions button {
  background: #f7fafc;
  border: 1px solid #e2e8f0;
  padding: 8px 12px;
  border-radius: 8px;
  text-align: left;
  font-size: 12px;
  cursor: pointer;
  color: #2d3748;
}

.quick-questions button:hover {
  background: #ebf8ff;
  border-color: #bee3f8;

}

.rag-chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.rag-chat-header {
  padding: 16px 24px;
  border-bottom: 1px solid #edf2f7;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.rag-chat-header h2 {
  margin: 0;
  font-size: 17px;
  color: #1a202c;
}

.badge-online {
  color: #38a169;
  font-size: 12px;
  font-weight: 700;
}

.rag-chat-messages {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #f8fafc;
}

.rag-msg-row {
  display: flex;
  gap: 12px;

}

.rag-msg-row.user {
  flex-direction: row-reverse;
}

.rag-msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}

.rag-msg-bubble {
  max-width: 75%;
  background: #ffffff;
  padding: 12px 16px;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  font-size: 14px;
  line-height: 1.5;
  color: #2d3748;
}

.user .rag-msg-bubble {
  background: #3182ce;
  color: #ffffff;
}

.rag-msg-sender {
  font-size: 11px;
  font-weight: 700;
  color: #a0aec0;
  margin-bottom: 4px;
}

.user .rag-msg-sender {
  color: #ebf8ff;
}

.rag-chat-inputzone {
  padding: 16px;
  border-top: 1px solid #edf2f7;
  display: flex;
  gap: 12px;
  background: #ffffff;
}

.rag-chat-inputzone textarea {
  flex: 1;
  border: 1px solid #cbd5e0;
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 14px;
  resize: none;
  font-family: inherit;
}

.btn-send-rag {
  background: #3182ce;
  color: #ffffff;
  border: none;
  padding: 0 20px;
  border-radius: 12px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-send-rag:disabled {
  background: #cbd5e0;
  cursor: not-allowed;
}

.settings-layout {
  padding: 28px;
  min-height: 560px;
  background: #fff8f4;
}

.settings-card {
  max-width: 820px;
  margin: 0 auto;
  padding: 28px;
  border: 1px solid #f3c9bd;
  border-radius: 22px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(135, 54, 36, 0.08);
}

.settings-card + .settings-card {
  margin-top: 20px;
}

.settings-refresh,
.team-toggle {
  border: 0;
  border-radius: 10px;
  padding: 8px 12px;
  color: #8d271d;
  background: #fff0ea;
  cursor: pointer;
  font-weight: 700;
}

.team-form {
  display: grid;
  grid-template-columns: 1.1fr 1.2fr 0.8fr auto;
  gap: 10px;
  margin: 22px 0;
}

.team-form input,
.team-form select {
  min-width: 0;
  border: 1px solid #efc8c0;
  border-radius: 10px;
  padding: 10px 12px;
  color: #5e423a;
  background: #fffaf8;
}

.team-error {
  margin-bottom: 0;
}

.team-table-wrap {
  overflow-x: auto;
}

.team-table {
  width: 100%;
  border-collapse: collapse;
  color: #5e423a;
}

.team-table th,
.team-table td {
  padding: 12px 8px;
  border-bottom: 1px solid #f4dfd8;
  text-align: left;
  vertical-align: middle;
}

.team-table th {
  color: #99655a;
  font-size: 12px;
  text-transform: uppercase;
}

.team-table td small {
  display: block;
  margin-top: 3px;
  color: #9b827b;
}

.team-role,
.team-status {
  display: inline-block;
  border-radius: 999px;
  padding: 5px 9px;
  color: #8d271d;
  background: #fff0ea;
  font-size: 12px;
  font-weight: 700;
}

.team-status {
  color: #237443;
  background: #e4f7e9;
}

.team-status.inactive {
  color: #8a5a00;
  background: #fff1cf;
}

.permission-panel {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #f4dfd8;
}

.permission-panel h3 {
  margin: 0 0 6px;
  color: #8d271d;
}

.permission-form {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr)) auto;
  gap: 10px;
  align-items: end;
  margin-top: 16px;
}

.permission-form label {
  display: grid;
  gap: 6px;
  color: #8b6b64;
  font-size: 12px;
  font-weight: 700;
}

.permission-form select {
  min-height: 38px;
  border: 1px solid #f0c7bd;
  border-radius: 10px;
  padding: 0 10px;
  color: #5e423a;
  background: #fffaf7;
}

.permission-list {
  display: grid;
  gap: 8px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.permission-list li {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 3px 12px;
  padding: 10px 12px;
  border: 1px solid #f4dfd8;
  border-radius: 10px;
  background: #fffaf7;
  color: #5e423a;
}

.permission-list small {
  grid-column: 1 / -1;
  color: #9b827b;
}

.permission-deny,
.permission-allow {
  align-self: start;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.permission-deny {
  color: #9a2b21;
  background: #ffe7e1;
}

.permission-allow {
  color: #237443;
  background: #e4f7e9;
}

.settings-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.settings-card-header h2 {
  margin: 0 0 8px;
  color: #8d271d;
}

.settings-card-header p,
.settings-empty {
  margin: 0;
  color: #8b6b64;
  line-height: 1.6;
}

.connection-badge {
  padding: 8px 12px;
  border-radius: 999px;
  color: #9b6b31;
  background: #fff0d8;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.connection-badge.connected {
  color: #237443;
  background: #e4f7e9;
}

.settings-notice {
  margin: 22px 0;
  padding: 12px 14px;
  border-radius: 12px;
  color: #7b4e00;
  background: #fff6d9;
}

.meta-connection-details {
  display: grid;
  gap: 10px;
  margin: 24px 0;
  padding: 18px;
  border-radius: 14px;
  background: #fff5f0;
  color: #5e423a;
}

.settings-actions {
  margin-top: 24px;
}

.btn-meta-connect,
.btn-meta-disconnect {
  border: 0;
  border-radius: 12px;
  padding: 12px 18px;
  color: #fff;
  font-weight: 800;
  cursor: pointer;
}

.btn-meta-connect {
  background: #1877f2;
}

.btn-meta-disconnect {
  background: #a94b3b;
}

.btn-meta-disconnect:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Neutral visual language for operational CRM screens. */
.products-layout,
.settings-layout,
.rag-docs-layout,
.rag-chat-layout {
  color: var(--crm-ink);
  background: var(--crm-canvas);
}

.products-layout {
  min-height: calc(100vh - 84px);
  padding: 24px;
}

.products-header h2,
.product-form-title,
.settings-card-header h2,
.rag-header-panel h2 {
  color: var(--crm-ink);
  font-weight: 700;
}

.products-header p,
.field-hint,
.settings-card-header p,
.settings-empty,
.rag-header-panel p {
  color: var(--crm-muted);
}

.primary-btn,
.btn-send-rag {
  color: #fff;
  background: var(--crm-accent);
  border-radius: 9px;
}

.product-form,
.settings-card,
.rag-header-panel,
.docs-table-card,
.setting-card,
.rag-chat-main,
.report-panel,
.products-table-wrap {
  border: 1px solid var(--crm-border);
  border-radius: 12px;
  background: var(--crm-surface);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
}

.product-form {
  padding: 18px;
}

.product-form-grid input,
.product-form-grid select,
.product-form-grid textarea,
.team-form input,
.team-form select,
.report-filters input,
.report-filters select,
.inline-stage,
.order-payment-actions input,
.ticket-comment-form input {
  color: var(--crm-ink);
  background: var(--crm-surface);
  border-color: var(--crm-border-strong);
  border-radius: 8px;
}

.products-table-wrap {
  overflow: auto;
}

.products-table th,
.products-table td,
.team-table th,
.team-table td,
.docs-table th,
.docs-table td {
  color: var(--crm-ink);
  border-color: var(--crm-border);
}

.products-table th,
.docs-table th {
  color: var(--crm-muted);
  background: #f7f9fc;
}

.products-table td small,
.team-table td small {
  color: var(--crm-subtle);
}

.product-error,
.error-banner {
  color: #a83d49;
  background: #fff1f2;
  border: 1px solid #f2c3c9;
}

.revenue-card,
.pipeline-card,
.ticket-stat,
.report-card,
.stat-card {
  color: var(--crm-muted);
  background: var(--crm-surface);
  border-color: var(--crm-border);
}

.revenue-card.total,
.report-card.accent {
  color: #fff;
  background: linear-gradient(135deg, #2f6fed, #4658c9);
  border-color: transparent;
}

.revenue-card strong,
.pipeline-card strong,
.ticket-stat strong,
.report-card strong,
.stat-num {
  color: var(--crm-ink);
}

.revenue-card.total strong,
.report-card.accent strong,
.revenue-card.total small,
.report-card.accent small {
  color: #fff;
}

.lead-actions {
  white-space: nowrap;
}

.table-link {
  border: 1px solid var(--crm-border);
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--crm-accent);
  background: var(--crm-accent-soft);
  cursor: pointer;
}

.lead-detail-row td {
  padding: 0;
  background: #f8fbff;
}

.lead-detail {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
  border-top: 1px solid var(--crm-border);
}

.lead-detail-header,
.lead-activity {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.lead-detail-header span,
.lead-activity small {
  color: var(--crm-subtle);
  font-size: 12px;
}

.lead-activity-list {
  display: grid;
  gap: 7px;
}

.lead-activity {
  padding: 9px 11px;
  border: 1px solid var(--crm-border);
  border-radius: 9px;
  background: var(--crm-surface);
}

.lead-activity-form,
.lead-conversion-form {
  display: flex;
  gap: 8px;
  align-items: center;
}

.lead-activity-form input,
.lead-conversion-form select {
  flex: 1;
  min-height: 36px;
  border: 1px solid var(--crm-border);
  border-radius: 8px;
  padding: 0 10px;
  color: var(--crm-ink);
  background: var(--crm-surface);
}

.settings-layout {
  min-height: calc(100vh - 84px);
  padding: 24px;
}

.settings-card {
  max-width: 980px;
  padding: 22px;
}

.settings-refresh,
.team-toggle,
.btn-refresh {
  color: var(--crm-accent);
  background: var(--crm-accent-soft);
  border: 1px solid #d5e2ff;
  border-radius: 8px;
}

.connection-badge {
  color: #9a6c16;
  background: #fff7df;
}

.connection-badge.connected,
.team-status {
  color: #087c5a;
  background: #e7f7f0;
}

.meta-connection-details {
  color: var(--crm-ink);
  background: #f5f8fc;
  border: 1px solid var(--crm-border);
}

.rag-docs-layout,
.rag-chat-layout {
  min-height: calc(100vh - 84px);
  padding: 24px;
}

.upload-dropzone {
  background: var(--crm-surface);
  border-color: var(--crm-border-strong);
  border-radius: 12px;
}

.upload-dropzone:hover {
  background: var(--crm-accent-soft);
  border-color: var(--crm-accent);
}

.rag-chat-sidebar {
  width: 300px;
}

.setting-card {
  padding: 16px;
}

.setting-card h3,
.rag-chat-header h2,
.card-header h3 {
  color: var(--crm-ink);
}

.quick-questions button {
  color: var(--crm-ink);
  background: #f7f9fc;
  border-color: var(--crm-border);
}

.rag-chat-main {
  overflow: hidden;
}

.rag-chat-messages {
  background: #f7f9fc;
}

.rag-msg-bubble {
  color: var(--crm-ink);
  background: var(--crm-surface);
}

.user .rag-msg-bubble,
.btn-send-rag {
  background: var(--crm-accent);
}

.rag-chat-inputzone {
  background: var(--crm-surface);
  border-color: var(--crm-border);
}

.chatbot-runtime-card .chatbot-config-form,
.chatbot-runtime-card .canned-response-form {
  display: grid;
  gap: 12px;
}

.chatbot-config-form {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.chatbot-config-form label,
.canned-response-form label {
  display: grid;
  gap: 6px;
  color: #7b3c3b;
  font-size: 13px;
  font-weight: 600;
}

.chatbot-config-form input,
.chatbot-config-form textarea,
.canned-response-form input,
.canned-response-select {
  border: 1px solid #f0b4ae;
  border-radius: 10px;
  background: #fffafa;
  color: #64292a;
  padding: 10px 12px;
}

.chatbot-hours-field {
  grid-column: 1 / -1;
}

.checkbox-field {
  display: flex !important;
  align-items: center;
  gap: 8px !important;
}

.checkbox-field input {
  width: auto;
}

.canned-response-panel {
  margin-top: 18px;
  border-top: 1px solid #f5d0cc;
  padding-top: 18px;
}

.canned-response-form {
  grid-template-columns: 120px 180px minmax(0, 1fr) auto;
}

.canned-response-list {
  display: grid;
  gap: 8px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.canned-response-list li {
  display: grid;
  grid-template-columns: 100px 160px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  border: 1px solid #f4d5d0;
  border-radius: 10px;
  padding: 10px;
}

.canned-response-list small {
  color: #845958;
}

.followup-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.followup-list li {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  border: 1px solid #f4d5d0;
  border-radius: 10px;
  padding: 10px;
  color: #6d3a3a;
}

.followup-list li > div {
  display: grid;
  gap: 3px;
}

.followup-list small {
  color: #9c7470;
}

.bot-mode-button {
  border: 1px solid #e89b9b;
  border-radius: 9px;
  background: #fff4f3;
  color: #bd2f43;
  padding: 8px 10px;
  font-weight: 700;
}

.bot-mode-button.human {
  background: #e84c64;
  color: white;
}

.canned-response-select {
  min-width: 150px;
}

@media (max-width: 850px) {
  .chatbot-config-form,
  .canned-response-form,
  .canned-response-list li,
  .followup-list li {
    grid-template-columns: 1fr;
  }
}

/* Center operational screens inside one consistent workspace frame. */
.products-layout,
.rag-docs-layout,
.rag-chat-layout,
.settings-layout {
  width: min(100%, 1480px);
  max-width: 1480px;
  margin-inline: auto;
  padding-inline: clamp(16px, 2vw, 32px);
}

.products-layout > .product-form,
.products-layout > .supplier-manager {
  width: min(100%, 1120px);
  max-width: 1120px;
  margin-inline: auto;
}

.products-layout > .products-table-wrap,
.products-layout > .report-panel,
.products-layout > .report-filters,
.rag-docs-layout > .rag-header-panel,
.rag-docs-layout > .upload-dropzone,
.rag-docs-layout > .docs-table-card {
  width: 100%;
  margin-inline: auto;
}

.settings-layout > .settings-card {
  width: min(100%, 1120px);
  margin-inline: auto;
}

@media (max-width: 900px) {
  .products-layout,
  .rag-docs-layout,
  .rag-chat-layout,
  .settings-layout {
    width: 100%;
    max-width: none;
    padding-inline: 12px;
  }

  .products-layout > .product-form,
  .products-layout > .supplier-manager,
  .settings-layout > .settings-card {
    width: 100%;
    max-width: none;
  }
}

/* Khung giao diện thống nhất theo phong cách Owly/Salon */
.visually-hidden {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}

.inbox { min-width: 0; overflow: hidden; }
.inbox-title {
  min-height: 88px;
  padding: 16px 18px;
  border-radius: 16px 16px 0 0;
  background: linear-gradient(135deg, #1f718a 0%, #2a929b 60%, #37aaa0 100%);
}
.inbox-title h2 { color: #fff !important; font-size: clamp(17px, 1.7vw, 21px); }
.inbox-title-kicker { color: rgba(240, 255, 253, .82); letter-spacing: .1em; }
.inbox-title-copy p { color: rgba(240, 255, 253, .86); }
.inbox-title-actions { gap: 8px; }
.inbox-title-count { color: #1e7079; background: #e8f8f5; }
.inbox-title .inbox-refresh { width: 36px; height: 36px; color: #1e7079; background: #e8f8f5; }
.inbox-toolbar { display: grid; gap: 0; background: #fff; }
.inbox-channel-filter {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  padding: 12px 14px 8px;
}
.inbox-quick-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
  gap: 4px;
  overflow: visible;
}
.inbox-quick-tabs button {
  min-width: 0;
  width: 100%;
  padding: 0 4px;
  font-size: .72rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
.inbox-channel-select { display: block; width: 100%; flex: none; }
.inbox-channel-select select {
  width: 100%;
  min-height: 36px;
  color: var(--owly-ink);
  background: #fbfdff;
  border: 1px solid var(--owly-border);
  border-radius: 9px;
  padding-inline: 10px;
  font-size: .74rem;
}
.inbox-search-box { margin: 0 14px 10px; }
.inbox-filter-disclosure { margin: 0 14px 10px; }

.rag-docs-layout, .rag-chat-layout, .products-layout, .settings-layout {
  width: min(100%, 1480px);
  max-width: 1480px;
  margin-inline: auto;
  padding: clamp(16px, 2vw, 28px);
  gap: 16px;
}
.rag-header-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 20px;
  align-items: center;
  padding: 20px 24px;
  border: 1px solid var(--owly-border);
  border-radius: 16px;
  background: linear-gradient(135deg, #fff, #f3fbfb);
  box-shadow: 0 8px 24px rgba(32, 54, 74, .06);
}
.rag-header-panel h2 { color: var(--owly-ink) !important; font-size: clamp(22px, 2vw, 30px); }
.rag-header-panel p { color: var(--owly-muted) !important; max-width: 720px; line-height: 1.55; }
.rag-stats { display: grid; grid-template-columns: repeat(3, minmax(90px, 1fr)); gap: 10px; min-width: min(100%, 330px); }
.stat-card { min-width: 90px; padding: 13px 16px; border: 1px solid #cfe7e6; border-radius: 12px; background: #f7fcfc; }
.stat-num { color: var(--workspace-primary-dark) !important; }
.stat-label { color: var(--owly-muted) !important; }
.upload-dropzone { min-height: 142px; display: grid; place-items: center; padding: 28px; border: 1.5px dashed #abd8d5; border-radius: 16px; background: linear-gradient(135deg, #fff, #f3fbfb); }
.upload-dropzone:hover { border-color: var(--salon-accent); background: var(--salon-accent-soft); }
.dropzone-content strong { color: var(--owly-ink); }
.dropzone-content small { color: var(--owly-muted); }
.docs-table-card { overflow-x: auto; padding: 0; border: 1px solid var(--owly-border); border-radius: 16px; background: #fff; }
.docs-table-card .card-header { min-width: 760px; margin: 0; padding: 16px 20px; border-bottom: 1px solid var(--owly-border); }
.docs-table { min-width: 760px; }
.docs-table th { color: var(--owly-muted); background: #f1f9f9; border-color: var(--owly-border); }
.docs-table td { color: var(--owly-ink); border-color: var(--owly-border); }
.status-ready { color: #1f705f; background: #e5f7f2; }
.status-processing { color: #8a641a; background: #fff4d7; }
.status-pending { color: #5e7184; background: #eef4f7; }
.status-error { color: #9a4550; background: #fff0f1; }

.products-layout > .products-header, .products-layout > .product-form, .products-layout > .products-table-wrap,
.products-layout > .report-panel, .products-layout > .operation-mode-banner, .settings-layout > .settings-card,
.ai-board-card, .ai-compose-card, .ai-stat-card, .pipeline-card, .ticket-stat, .revenue-card, .webhook-card {
  border-radius: 16px;
}

.products-layout > .products-header,
.products-layout > .product-form,
.products-layout > .products-table-wrap,
.products-layout > .supplier-manager,
.products-layout > .report-panel,
.products-layout > .report-filters,
.settings-layout > .settings-card {
  border: 1px solid var(--owly-border);
  background: var(--owly-surface);
  box-shadow: 0 8px 24px rgba(32, 54, 74, .06);
}
.products-layout > .products-header {
  padding: 20px 24px;
  background: linear-gradient(135deg, #fff, #f3fbfb);
}
.products-layout > .products-header h2,
.products-layout > .report-panel h3,
.settings-layout > .settings-card h2,
.settings-layout > .settings-card h3 {
  color: var(--owly-ink);
}
.products-layout > .products-header p,
.products-layout > .report-panel span,
.settings-layout > .settings-card p,
.settings-layout > .settings-card .settings-muted {
  color: var(--owly-muted);
}
.products-layout > .product-form,
.products-layout > .supplier-manager,
.products-layout > .report-panel,
.products-layout > .report-filters,
.settings-layout > .settings-card {
  padding: 18px 20px;
}
.products-layout > .products-table-wrap { overflow-x: auto; padding: 0; }
.products-layout > .products-table-wrap .products-table { min-width: 720px; }
.products-layout > .products-table-wrap .products-table th { background: #f1f9f9; color: var(--owly-muted); }
.primary-btn, .login-submit, .btn-meta-connect {
  border-radius: 10px;
  background: linear-gradient(135deg, var(--salon-accent), #237f99);
  box-shadow: 0 8px 16px rgba(43, 155, 153, .18);
}
.primary-btn:hover, .login-submit:hover, .btn-meta-connect:hover { filter: brightness(1.04); transform: translateY(-1px); }
.secondary-btn, .settings-refresh, .history-btn, .table-action-btn {
  border-radius: 9px;
  border-color: var(--owly-border);
  color: var(--workspace-primary-dark);
  background: #f6fbfb;
}
.secondary-btn:hover, .settings-refresh:hover, .history-btn:hover, .table-action-btn:hover { border-color: #abd8d5; background: var(--salon-accent-soft); }

.report-cards, .ai-lab-summary, .quota-grid, .security-grid, .webhook-grid { gap: 12px; }
.report-card, .ai-stat-card, .quota-item, .security-section, .webhook-item { border-radius: 12px; }

@media (max-width: 760px) {
  .rag-header-panel { grid-template-columns: 1fr; }
  .rag-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); min-width: 0; }
}

@media (max-width: 520px) {
  .rag-docs-layout, .rag-chat-layout, .products-layout, .settings-layout { padding: 12px; }
  .rag-stats { grid-template-columns: 1fr; }
  .inbox-quick-tabs button { font-size: .68rem; }
}

/* Consistent white/black workspace with compact Owly/Salon-style dialogs. */
.crm-app { background: #f7f7f5; color: #171717; }
.main, .products-layout, .settings-layout, .rag-docs-layout, .rag-chat-layout { background: #f7f7f5; }
.side { background: #111315; }
.menu-item.active { background: #242628; border-color: #3b3d3f; box-shadow: inset 3px 0 #fff; }
.channel-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; width: min(100%, 1120px); margin-inline: auto; }
.channel-summary-card { max-width: none !important; }
.channel-summary-card .primary-btn { margin-top: 12px; }
.channels-layout > .channel-connect-card { display: none !important; }
.channel-modal-backdrop { z-index: 40; }
.channel-modal { width: min(94vw, 900px); max-height: 90vh; overflow: auto; }
.channel-modal .settings-card-header { align-items: flex-start; }
.channel-modal .quick-action-close { flex: 0 0 auto; }
.text-import-dialog { width: min(94vw, 700px); }
.text-import-title { display: grid; gap: 7px; margin: 12px 0; color: var(--owly-ink); font-weight: 700; }
.text-import-title input, .text-import-title textarea { border: 1px solid var(--owly-border); border-radius: 10px; padding: 10px 12px; background: #fff; color: var(--owly-ink); }
.dialog-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.import-choice-row { display: flex; justify-content: center; gap: 10px; margin-top: 14px; }
.import-choice { font-weight: 700; }
.error { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.error-retry-btn { border: 1px solid #d78b92; border-radius: 8px; padding: 7px 12px; color: #8e2f3c; background: #fff; cursor: pointer; font-weight: 700; }
.business-hours-grid, .sla-rules-grid, .business-profile-grid, .service-plan-grid { display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 16px; }
.business-hours-grid label, .sla-rules-grid label, .business-profile-grid label { display: grid; gap: 6px; color: var(--owly-ink); font-weight: 700; }
.business-hours-grid input, .business-hours-grid select, .sla-rules-grid input, .business-profile-grid input, .business-profile-grid select, .business-profile-grid textarea, .voice-settings-row select { border: 1px solid var(--owly-border); border-radius: 9px; padding: 10px 12px; background: #fff; color: var(--owly-ink); }
.business-profile-wide { grid-column: 1 / -1; }
.voice-settings-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 8px 0 16px; }
.service-plan-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.service-plan-grid > div { display: grid; gap: 5px; padding: 12px; border: 1px solid var(--owly-border); border-radius: 10px; background: #fafafa; }
.service-plan-grid span, .service-plan-grid strong { color: var(--owly-ink); }
.learning-options { display: grid; gap: 10px; margin-bottom: 10px; }
.followup-list li > span { display: grid; gap: 4px; }
.followup-recommendation { color: var(--owly-muted); }
.purchase-orders-layout { display: none !important; }
.orders-layout .order-form, .orders-layout form.order-form { display: none !important; }
.rag-chat-sidebar .setting-card:nth-child(2) { display: none; }
.chatbot-config-form input, .chatbot-config-form textarea, .canned-response-form input, .canned-response-select { border-color: #dedede; background: #fff; color: #171717; }
.chatbot-config-form label, .canned-response-form label { color: #333; }
.bot-mode-button { border-color: #d7d7d7; background: #fff; color: #222; }
.bot-mode-button.human { background: #222; color: #fff; }
.dark-mode-toggle {
  display: inline-grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border: 1px solid var(--owly-border);
  border-radius: 12px;
  color: var(--owly-ink);
  background: var(--owly-surface);
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
  transition: background .18s ease, color .18s ease, transform .18s ease;
}
.dark-mode-toggle:hover { transform: translateY(-1px); background: var(--salon-accent-soft); }
.dark-mode-toggle .help { display: none !important; }
.workflow-email-note {
  grid-column: 1 / -1;
  margin: -2px 0 4px;
  padding: 10px 12px;
  border: 1px solid #cfe7e6;
  border-radius: 10px;
  color: #35626b !important;
  background: #f0fbfa;
  font-size: .86rem;
}
.bot-connection-alert { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.bot-connection-alert > span { flex: 1; }
.bot-connection-alert .settings-refresh { flex: 0 0 auto; }
.channel-summary-grid { align-items: stretch; }
.channel-summary-card { display: flex; flex-direction: column; min-height: 190px; }
.channel-summary-card .settings-muted { flex: 1; }
.channel-summary-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.channel-summary-actions .primary-btn,
.channel-summary-actions .secondary-btn { width: 100%; margin-top: 0; min-height: 42px; }
.channel-modal .settings-card-header { position: sticky; top: -1px; z-index: 2; padding-bottom: 14px; background: var(--owly-surface); }
.channel-modal { display: flex; flex-direction: column; grid-template-columns: none; gap: 0; width: min(94vw, 760px); max-width: 100%; max-height: min(90vh, 760px); overflow-x: hidden; padding: 22px; box-sizing: border-box; }
.channel-modal > * { min-width: 0; }
.channel-modal .bot-connect-form { grid-template-columns: minmax(0, 1fr) auto; align-items: end; }
.channel-modal .bot-connect-form .bot-token-field { grid-column: 1; }
.channel-modal .bot-connect-form .bot-connect-submit { grid-column: 2; }
.channel-modal .bot-connect-guides { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.meta-channel-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 18px 0; }
.meta-channel-card { display: flex; flex-direction: column; gap: 12px; padding: 18px; border: 1px solid var(--owly-border); border-radius: 14px; background: var(--owly-surface); color: var(--owly-ink); }
.meta-channel-card.active { border-color: var(--salon-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--salon-accent) 16%, transparent); }
.meta-channel-card > div:first-child { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; align-items: center; }
.meta-channel-card > div:first-child p { grid-column: 2; margin: 0; color: var(--owly-muted); }
.meta-channel-card h3 { margin: 0; color: var(--owly-ink); }
.channel-card-icon { display: inline-grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--salon-accent-soft); color: var(--salon-accent-strong); font-size: 1.15rem; font-weight: 800; }
.meta-channel-card .connection-badge { align-self: flex-start; }
.meta-channel-card .meta-connection-details { margin: 0; padding: 12px; font-size: .88rem; }
.meta-channel-card .btn-meta-connect { width: 100%; margin-top: auto; }
.meta-oauth-note { margin: 0 0 6px; }
.bot-provider-heading { display: flex; align-items: center; gap: 12px; margin: 18px 0 14px; }
.bot-provider-heading > div { flex: 1; }
.bot-provider-heading h3 { margin: 0 0 4px; color: var(--owly-ink); }
.bot-provider-heading p { margin: 0; color: var(--owly-muted); }
.bot-connect-guide-single { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; padding: 16px; border: 1px solid var(--owly-border); border-radius: 14px; background: var(--owly-surface-soft); }
.bot-connect-guide-single > div:last-child { min-width: 0; flex: 1 1 250px; }
.bot-connect-guide-single ol { margin: 0 0 8px; padding-left: 20px; color: var(--owly-muted); line-height: 1.55; }
.bot-connect-guide-single .bot-guide-link { display: inline-flex; }
.business-days-fieldset { margin: 8px 0 18px; padding: 12px 14px 14px; border: 1px solid var(--owly-border); border-radius: 12px; }
.business-days-fieldset legend { padding: 0 6px; color: var(--owly-ink); font-weight: 800; }
.business-day-options { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; }
.business-day-option { display: flex !important; align-items: center; justify-content: center; gap: 5px; min-height: 38px; padding: 7px 6px; border: 1px solid var(--owly-border); border-radius: 9px; background: var(--owly-surface); color: var(--owly-muted) !important; font-size: .82rem; font-weight: 700; cursor: pointer; }
.business-day-option.selected { border-color: var(--salon-accent); color: var(--salon-accent-strong) !important; background: var(--salon-accent-soft); }
.business-day-option input { margin: 0; accent-color: var(--salon-accent); }
.business-days-fieldset .field-hint { display: block; margin-top: 9px; color: var(--owly-muted); }
.bot-guide-warning { margin: 4px 0 8px; color: #9b5f12; font-size: .78rem; line-height: 1.35; }

/* User-controlled dark mode: retain the same spacing/layout while switching
   surfaces and text to a calm high-contrast palette. */
:global(html.crm-dark), :global(body.crm-dark) { background: #151719; color: #f3f5f6; }
.crm-app.crm-dark,
.crm-dark .main,
.crm-dark .products-layout,
.crm-dark .settings-layout,
.crm-dark .rag-docs-layout,
.crm-dark .rag-chat-layout { background: #151719; color: #f3f5f6; }
.crm-dark .top { background: #151719; border-color: #303538; color: #f3f5f6; }
.crm-dark .top h1,
.crm-dark .top p,
.crm-dark .settings-layout > .settings-card h2,
.crm-dark .settings-layout > .settings-card h3,
.crm-dark .products-layout > .products-header h2,
.crm-dark .products-layout > .report-panel h3,
.crm-dark .business-hours-grid label,
.crm-dark .sla-rules-grid label,
.crm-dark .business-profile-grid label { color: #f3f5f6; }
.crm-dark .top p,
.crm-dark .settings-layout > .settings-card p,
.crm-dark .settings-layout > .settings-card .settings-muted,
.crm-dark .products-layout > .products-header p,
.crm-dark .products-layout > .report-panel span { color: #b6c0c5; }
.crm-dark .settings-layout > .settings-card,
.crm-dark .products-layout > .products-header,
.crm-dark .products-layout > .product-form,
.crm-dark .products-layout > .products-table-wrap,
.crm-dark .products-layout > .supplier-manager,
.crm-dark .products-layout > .report-panel,
.crm-dark .products-layout > .report-filters,
.crm-dark .rag-header-panel,
.crm-dark .docs-table-card,
.crm-dark .channel-modal { border-color: #394145; background: #202427; box-shadow: 0 8px 24px rgba(0,0,0,.18); }
.crm-dark .rag-header-panel,
.crm-dark .products-layout > .products-header { background: #202427; }
.crm-dark input,
.crm-dark select,
.crm-dark textarea,
.crm-dark .top-search,
.crm-dark .top-search-input,
.crm-dark .secondary-btn,
.crm-dark .settings-refresh,
.crm-dark .history-btn,
.crm-dark .table-action-btn,
.crm-dark .bot-mode-button,
.crm-dark .dark-mode-toggle { border-color: #4a555a; background: #1a1e20; color: #f3f5f6; }
.crm-dark input::placeholder,
.crm-dark textarea::placeholder { color: #89959b; }
.crm-dark .products-table th,
.crm-dark .docs-table th { background: #292f32; color: #d2dadd; border-color: #394145; }
.crm-dark .products-table td,
.crm-dark .docs-table td { color: #e5eaec; border-color: #394145; }
.crm-dark .channel-modal .settings-card-header { background: #202427; }
.crm-dark .inbox,
.crm-dark .chat,
.crm-dark .customer { background: #202427 !important; color: #f3f5f6 !important; border-color: #394145 !important; }
.crm-dark .inbox-toolbar,
.crm-dark .conversation-scroll,
.crm-dark .chat-head,
.crm-dark .messages-scroll,
.crm-dark .composer,
.crm-dark .customer-title,
.crm-dark .customer-profile,
.crm-dark .customer-360-data { background: #202427 !important; color: #f3f5f6 !important; border-color: #394145 !important; }
.crm-dark .conversation,
.crm-dark .customer-contact-card,
.crm-dark .customer-fact-row,
.crm-dark .customer-timeline-row { border-color: #394145; background: #252a2d; color: #e5eaec; }
.crm-dark .conversation:hover,
.crm-dark .conversation.active { background: #2b3438; }
.crm-dark .conversation-preview,
.crm-dark .conversation-time,
.crm-dark .customer-profile p,
.crm-dark .customer-profile small,
.crm-dark .customer-timeline-row small { color: #b6c0c5; }
.crm-dark .inbox-channel-select select,
.crm-dark .inbox-search-box input,
.crm-dark .composer textarea { background: #1a1e20; color: #f3f5f6; border-color: #4a555a; }
.crm-dark .workflow-email-note { border-color: #3c666a; color: #b7e2df !important; background: #203536; }
.crm-dark .bot-guide-warning { color: #f2ca83; }
.crm-dark .error { color: #ffe3e6; background: #3a2025; border-color: #7f414d; }
.crm-dark .error-retry-btn { color: #ffd7dc; border-color: #a65c68; background: #2b1b1f; }

/* High-contrast overrides come last so legacy coral/Salon rules cannot make
   text disappear when a shop switches to dark mode. */
.crm-dark .settings-card,
.crm-dark .channel-page-header,
.crm-dark .channel-summary-card,
.crm-dark .channel-modal,
.crm-dark .webhook-card,
.crm-dark .meta-channel-card,
.crm-dark .bot-connect-guide-single,
.crm-dark .pipeline-card,
.crm-dark .lead-detail,
.crm-dark .order-events-panel,
.crm-dark .order-logistics-card,
.crm-dark .audit-panel,
.crm-dark .permission-panel,
.crm-dark .rag-card,
.crm-dark .rag-chat-sidebar,
.crm-dark .rag-chat-main,
.crm-dark .ai-board-card,
.crm-dark .ai-rule-card,
.crm-dark .ai-experiment-card,
.crm-dark .ai-compose-card,
.crm-dark .security-section,
.crm-dark .platform-audit-panel,
.crm-dark .platform-schema-panel { background: #202427 !important; color: #f3f5f6 !important; border-color: #394145 !important; }
.crm-dark .settings-card-header h2,
.crm-dark .settings-card-header h3,
.crm-dark .channel-modal h2,
.crm-dark .channel-modal h3,
.crm-dark .meta-channel-card h3,
.crm-dark .bot-provider-heading h3,
.crm-dark .settings-card strong,
.crm-dark .settings-card label,
.crm-dark .business-days-fieldset legend,
.crm-dark .inbox-empty-state strong,
.crm-dark .inbox-empty-state p,
.crm-dark .customer-empty-state strong,
.crm-dark .customer-empty-state p { color: #f3f5f6 !important; }
.crm-dark .settings-card p,
.crm-dark .settings-card .settings-muted,
.crm-dark .settings-card .settings-empty,
.crm-dark .meta-channel-card > div:first-child p,
.crm-dark .bot-provider-heading p,
.crm-dark .bot-connect-guide-single ol,
.crm-dark .business-days-fieldset .field-hint,
.crm-dark .webhook-item small { color: #b6c0c5 !important; }
.crm-dark .meta-connection-details { background: #252a2d !important; border-color: #394145 !important; color: #e5eaec !important; }
.crm-dark .business-day-option { background: #1a1e20 !important; border-color: #4a555a !important; color: #b6c0c5 !important; }
.crm-dark .business-day-option.selected { background: #173f43 !important; border-color: #39a7ad !important; color: #d8ffff !important; }
.crm-dark select,
.crm-dark select option { color-scheme: dark; background-color: #1a1e20; color: #f3f5f6; }
.crm-dark .channel-modal .settings-card-header { background: #202427 !important; }
.crm-dark .channel-modal .bot-connect-note { color: #aeb9be !important; }
.crm-dark .top h1 { color: #f3f5f6 !important; }
.crm-dark .top p { color: #b6c0c5 !important; }
.crm-dark .welcome strong { color: #f3f5f6 !important; }
.crm-dark .welcome span { color: #b6c0c5 !important; }
.crm-dark .top-search,
.crm-dark .top-search-input { color: #f3f5f6 !important; background: #1a1e20 !important; border-color: #4a555a !important; }
.crm-dark .top-search-icon { color: #8bd8d7 !important; }
.crm-dark .bell,
.crm-dark .team { color: #f3f5f6 !important; background: #202427 !important; border-color: #394145 !important; }
.crm-dark .team b { color: #f3f5f6 !important; }
.crm-dark .team small { color: #b6c0c5 !important; }
.crm-dark .inbox-empty-state { background: #252a2d !important; border-color: #394145 !important; color: #f3f5f6 !important; }
.crm-dark .inbox-empty-state strong,
.crm-dark .inbox-empty-state p { color: #f3f5f6 !important; }
.crm-dark .inbox-empty-state-icon { background: #173f43 !important; border-color: #39a7ad !important; color: #d8ffff !important; }
.crm-dark .channel-summary-actions .secondary-btn { color: #d8ffff; }
.crm-dark .pipeline-card h3,
.crm-dark .pipeline-card strong,
.crm-dark .lead-detail h3,
.crm-dark .report-panel-header h3,
.crm-dark .ai-card-heading,
.crm-dark .ai-rule-title-row,
.crm-dark .security-section-title,
.crm-dark .ticket-description-cell,
.crm-dark .order-events-list strong,
.crm-dark .audit-list strong { color: #f3f5f6 !important; }
.crm-dark .pipeline-card p,
.crm-dark .pipeline-card span,
.crm-dark .lead-detail p,
.crm-dark .report-panel-header span,
.crm-dark .ai-card-help,
.crm-dark .ai-rule-meta,
.crm-dark .security-section small,
.crm-dark .audit-list small { color: #b6c0c5 !important; }
.crm-dark .products-table-wrap,
.crm-dark .products-table,
.crm-dark .docs-table-card,
.crm-dark .team-table-wrap,
.crm-dark .platform-table-wrap { background: #202427 !important; color: #f3f5f6 !important; border-color: #394145 !important; }
.crm-dark .products-table td,
.crm-dark .products-table th,
.crm-dark .docs-table td,
.crm-dark .docs-table th,
.crm-dark .team-table td,
.crm-dark .team-table th { color: #e5eaec !important; border-color: #394145 !important; }
.crm-dark .customer-title h3,
.crm-dark .customer-profile h3,
.crm-dark .customer-profile p,
.crm-dark .customer-profile small,
.crm-dark .section h4,
.crm-dark .section-head span,
.crm-dark .customer-identity-row,
.crm-dark .customer-contact-card,
.crm-dark .customer-contact-card > small,
.crm-dark .customer-profile-field,
.crm-dark .customer-profile-field span,
.crm-dark .customer-contact-row,
.crm-dark .customer-address-row,
.crm-dark .customer-contact-empty,
.crm-dark .customer-contact-status-row,
.crm-dark .customer-fact-row,
.crm-dark .customer-facts,
.crm-dark .customer-timeline-row { color: #e5eaec !important; }
.crm-dark .customer-title button,
.crm-dark .section-head button,
.crm-dark .section-head a { color: #8bd8d7 !important; }
.crm-dark .customer-contact-card,
.crm-dark .customer-profile-contact-card,
.crm-dark .customer-fact-row,
.crm-dark .customer-identity-row { background: #252a2d !important; border-color: #394145 !important; }
.crm-dark .customer-profile-field strong,
.crm-dark .customer-contact-row strong,
.crm-dark .customer-address-row strong,
.crm-dark .customer-fact-copy strong,
.crm-dark .customer-timeline-row strong { color: #f3f5f6 !important; }
.crm-dark .customer-contact-card > small,
.crm-dark .customer-profile-field span,
.crm-dark .customer-contact-status-row,
.crm-dark .customer-contact-empty,
.crm-dark .customer-timeline-row small { color: #b6c0c5 !important; }
.crm-dark .customer-contact-status-list,
.crm-dark .customer-contact-overflow-list { border-color: #394145 !important; }
.crm-dark .chat-person h2,
.crm-dark .chat-person p,
.crm-dark .conversation-assignment,
.crm-dark .conversation p,
.crm-dark .conversation-footer,
.crm-dark .today { color: #b6c0c5 !important; }
.crm-dark .chat-person h2 { color: #f3f5f6 !important; }
.crm-dark .chat-person h2 span { color: #8bd8d7 !important; }
.crm-dark .chat-head { background: #202427 !important; border-color: #394145 !important; }
.crm-dark .messages-scroll { background: #171b1d !important; }
.crm-dark .conversation-assignment select,
.crm-dark .chat-tools button { color: #e5eaec !important; background: #252a2d !important; border-color: #4a555a !important; }
.crm-dark .chat-tools button { color: #8bd8d7 !important; }
.crm-dark .today { background: #253b3d !important; border-color: #3c666a !important; }
.crm-dark .inbound .bubble { color: #e5eaec !important; background: #252a2d !important; border-color: #394145 !important; }
.crm-dark .outbound .bubble { color: #e5eaec !important; background: #173f43 !important; border-color: #3c777a !important; }
.crm-dark .composer { background: #202427 !important; border-color: #394145 !important; }
.crm-dark .composer-tabs { border-color: #394145 !important; }
.crm-dark .composer-tabs button { color: #b6c0c5 !important; }
.crm-dark .composer-tabs button.active { color: #8bd8d7 !important; border-bottom-color: #39a7ad !important; }
.crm-dark .composer textarea { color: #f3f5f6 !important; }
.crm-dark .empty-chat { background: radial-gradient(circle at 50% 42%, rgba(39, 143, 147, .22), transparent 220px), linear-gradient(180deg, #20282b, #171b1d) !important; }
.crm-dark .empty-chat h2 { color: #f3f5f6 !important; }
.crm-dark .empty-chat p { color: #b6c0c5 !important; }
.crm-dark .empty-chat-kicker { color: #8bd8d7 !important; }
.crm-dark .empty-chat-steps span { color: #d8ffff !important; border-color: #3c777a !important; background: rgba(37, 67, 70, .82) !important; }
.crm-dark .empty-chat-steps b { background: #299da2 !important; }
.crm-dark .empty-chat-mark { background: linear-gradient(145deg, #2aa8ad, #176d7a) !important; box-shadow: 0 14px 30px rgba(13, 101, 111, .32) !important; }
.crm-dark .app-dialog,
.crm-dark .quick-action-dialog { color: #f3f5f6 !important; background: #202427 !important; border-color: #394145 !important; box-shadow: 0 24px 70px rgba(0, 0, 0, .48) !important; }
.crm-dark .app-dialog-content h3,
.crm-dark .app-dialog-content p,
.crm-dark .quick-action-heading strong,
.crm-dark .quick-action-heading span,
.crm-dark .quick-action-item strong,
.crm-dark .quick-action-item small { color: #f3f5f6 !important; }
.crm-dark .quick-action-input { color: #f3f5f6 !important; background: #1a1e20 !important; border-color: #4a555a !important; }
.crm-dark .quick-action-item { color: #e5eaec !important; background: #252a2d !important; border-color: #394145 !important; }
.crm-dark .quick-action-item:hover,
.crm-dark .quick-action-close { background: #173f43 !important; color: #d8ffff !important; }
.crm-dark .ticket-stat,
.crm-dark .ticket-form,
.crm-dark .ticket-table,
.crm-dark .ticket-history-panel,
.crm-dark .ticket-comment-form,
.crm-dark .ticket-summary { background: #202427 !important; color: #f3f5f6 !important; border-color: #394145 !important; }
.crm-dark .ticket-stat span,
.crm-dark .ticket-stat small,
.crm-dark .ticket-form label,
.crm-dark .ticket-form .field-hint { color: #b6c0c5 !important; }
.crm-dark .rag-header-panel h2,
.crm-dark .rag-header-panel p,
.crm-dark .rag-stats .stat-label,
.crm-dark .dropzone-content strong,
.crm-dark .dropzone-content small,
.crm-dark .empty-docs-state,
.crm-dark .docs-table-card .card-header h3 { color: #f3f5f6 !important; }
.crm-dark .rag-header-panel p,
.crm-dark .rag-stats .stat-label,
.crm-dark .dropzone-content small,
.crm-dark .empty-docs-state { color: #b6c0c5 !important; }
.crm-dark .upload-dropzone { background: #252a2d !important; border-color: #3e8588 !important; }
.crm-dark .stat-card { background: #252a2d !important; border-color: #394145 !important; }

/* Keep the two system actions visually and semantically distinct even when a
   cached legacy stylesheet is still present. */
.menu-group-system .menu-item-service b,
.menu-group-system .menu-item-settings b {
  display: inline-block !important;
  visibility: visible !important;
  width: auto !important;
  min-width: 0 !important;
  overflow: visible !important;
  clip: auto !important;
  font-size: inherit !important;
  text-indent: 0 !important;
  white-space: nowrap !important;
}
.menu-group-system .menu-item-service b::before,
.menu-group-system .menu-item-service b::after,
.menu-group-system .menu-item-settings b::before,
.menu-group-system .menu-item-settings b::after {
  content: none !important;
  display: none !important;
}

.product-import-dropzone {
  min-height: 148px;
  margin: 0;
  padding: 24px;
}
.product-import-dropzone .dropzone-content { gap: 7px; }
.product-import-dropzone .upload-icon {
  color: var(--salon-accent);
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .12em;
}
.product-import-dropzone .dropzone-content strong { font-size: 1rem; }
.product-import-dropzone .dropzone-content small { max-width: 720px; line-height: 1.5; text-align: center; }
.product-import-notice {
  margin: 0;
  padding: 11px 14px;
  border: 1px solid #b9e1dc;
  border-radius: 10px;
  color: #246d70;
  background: #eefaf8;
  font-size: .86rem;
}
.crm-dark .product-import-notice {
  color: #c7f3ec;
  background: #173f43;
  border-color: #3e8588;
}

@media (max-width: 640px) {
  .channel-modal .bot-connect-guides { grid-template-columns: 1fr; }
  .channel-modal .bot-connect-form { grid-template-columns: 1fr; }
  .channel-modal .bot-connect-form .bot-token-field,
  .channel-modal .bot-connect-form .bot-connect-submit { grid-column: 1; }
  .meta-channel-grid { grid-template-columns: 1fr; }
  .bot-connect-guide-single { align-items: flex-start; }
  .business-day-options { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .dark-mode-toggle { width: 38px; height: 38px; }
}

@media (max-width: 760px) {
  .channel-summary-grid, .business-hours-grid, .sla-rules-grid, .business-profile-grid, .service-plan-grid { grid-template-columns: 1fr; }
  .business-profile-wide { grid-column: auto; }
}

</style>
