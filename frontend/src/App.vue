<script setup>
import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  nextTick,
  watch,
} from "vue";

import "./style.css";
import { channelLabel } from "./channel-utils.js";
import { customerTagNames, matchesCustomerTagFilter } from "./customer-utils.js";
import { filterConversationsForCustomer } from "./ticket-utils.js";
import { displayAttachments, resolveMediaUrl } from "./media-utils.js";
import { getInboxChannels } from "./inbox-utils.js";
import { MAX_SAVED_INBOX_VIEWS, normalizeInboxViewFilters, normalizeSavedInboxViews } from "./inbox-view-utils.js";
import { conversationBotStatus, timelineActor } from "./timeline-utils.js";
import { criticalConversationNotificationCounts, notificationDestination, unreadNotificationCount } from "./notification-utils.js";
import { maskCustomerEmail, maskCustomerName, maskCustomerPhone } from "./privacy-utils.js";
import { apiFetch } from "./api-client.js";
import { clearAuthToken, readAuthToken, requireBusinessId, storeAuthToken } from "./auth-context.js";
import { formatDate, formatDateTime, formatMoney, locale as uiLocale, setLocale as setUiLocale, t } from "./i18n.js";
import IndustryModules from "./IndustryModules.vue";
import {
  channelCapacityState,
  connectionStateMeta,
  latestPayment,
  paymentStatusMeta,
  platformQuotaCards,
  subscriptionStatusMeta,
} from "./platform-admin-utils.js";

// Keep browser requests same-origin by default. Vite proxies /api to the
// backend container in development, and an Ngrok frontend address therefore
// works without hard-coding a user's localhost API origin.
const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

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
const INBOX_PAGE_SIZE = 10;
const inboxConversationTotal = ref(0);
const inboxHasMore = ref(false);
const inboxLoadingMore = ref(false);
const inboxConversationScroll = ref(null);
const inboxLegacyPageCache = ref([]);
const inboxUsesLocalPaging = ref(false);
const messages = ref([]);
const customer360 = ref(null);
const customer360Loading = ref(false);
const customer360Error = ref("");
const customer360OverflowOpen = ref(false);
const customerCustomFieldsDraft = ref({});
const customerCustomFieldsSaving = ref(false);
const customerCustomFieldsError = ref("");
const customerCustomFieldsNotice = ref("");

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
const bulkSelectionMode = ref(false);
const bulkSelectedConversationIds = ref(new Set());
const bulkAssignmentTarget = ref("");
const bulkAssignmentSaving = ref(false);
const bulkAssignmentError = ref("");
const bulkAssignmentNotice = ref("");
const conversationOutcomeSaving = ref(false);
const conversationOutcomeError = ref("");
const conversationActionsOpen = ref(false);
const conversationPriorityIds = ref(new Set());
const conversationFavoriteIds = ref(new Set());
const composerMode = ref("reply");

const activeFilter = ref("all");
const inboxQuickFilter = ref("all");
// The link control in the conversation header narrows the inbox to the
// selected customer's other channels without clearing existing filters.
const linkedCustomerOnly = ref(false);
const inboxCustomerFilterId = ref(null);
const inboxPersonalFilters = ref({ phone: "", email: "" });
const tagCatalog = ref([]);
const tagFilters = ref([]);
const tagFilterMode = ref("all");
const savedInboxViews = ref([]);
const selectedSavedInboxViewId = ref("");
const savedInboxViewName = ref("");
const savedInboxViewNotice = ref("");
const savedInboxViewError = ref("");
const applyingSavedInboxView = ref(false);
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
let platformRequestPollingTimer = null;
let tenantProvisioningPollingTimer = null;
let platformRequestRefreshInFlight = false;
let socket = null;
let reconnectTimer = null;

/* RAG & TAB STATE */
const currentTab = ref("inbox"); // 'inbox' | 'products' | 'orders' | 'leads' | 'tickets' | 'reports' | 'documents' | 'rag_chat' | 'experiments' | 'channels' | 'webhooks' | 'settings' | 'platform_admin' | 'service'
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
const productStatusSaving = ref({});
const productStatusNotice = ref("");
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
  draft: ["pending_confirmation", "confirmed", "cancelled"],
  pending_confirmation: ["confirmed", "cancelled"],
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
const sessionBootstrapLoading = ref(true);
const tenantProvisioning = ref({ state: "unknown", feature_enabled: false, subscription_active: false, subscription_status: null });
const tenantProvisioningLoading = ref(false);
const tenantProvisioningError = ref("");
const tenantWorkspaceInitialized = ref(false);
const tenantWorkspaceActive = ref(false);
const tenantReady = computed(() => (
  tenantProvisioning.value?.state === "active"
  && Boolean(tenantProvisioning.value?.feature_enabled)
  && Boolean(tenantProvisioning.value?.subscription_active)
));
const authLoading = ref(false);
const authError = ref("");
const authRateLimitSeconds = ref(0);
let authRateLimitTimer = null;
const loginForm = ref({ email: "", password: "", shop_slug: "" });
const authView = ref("login");
const signupStep = ref("details");
const signupLoading = ref(false);
const signupError = ref("");
const signupNotice = ref("");
const signupForm = ref({ owner_name: "", email: "", shop_name: "", password: "", otp: "" });
const quotaSnapshot = ref(null);
const workspaceConfig = ref({ business_type: "retail", enabled_modules: ["retail"], modules: [] });
const workspaceConfigLoading = ref(false);
const workspaceConfigSaving = ref(false);
const workspaceConfigError = ref("");
const workspaceConfigNotice = ref("");
const canManageWorkspace = computed(() => ["owner", "admin"].includes(String(authUser.value?.role || "").toLowerCase()));
const defaultCrmPipelineStages = [
  { key: "new", label: "Mới" },
  { key: "qualified", label: "Đã xác định nhu cầu" },
  { key: "proposal", label: "Đã gửi đề xuất" },
  { key: "won", label: "Đã chốt" },
  { key: "lost", label: "Không thành công" },
];
const crmConfig = ref({ customer_fields: [], pipeline_stages: defaultCrmPipelineStages.map((item) => ({ ...item })) });
const crmConfigLoading = ref(false);
const crmConfigSaving = ref(false);
const crmConfigError = ref("");
const crmConfigNotice = ref("");
const crmFieldDraft = ref({ key: "", label: "", type: "text", options: "" });
const crmStageDraft = ref("");

async function fetchCrmConfig() {
  if (!authUser.value || !tenantReady.value) return;
  crmConfigLoading.value = true;
  crmConfigError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/workspace/crm-config`);
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    crmConfig.value = {
      customer_fields: Array.isArray(detail.customer_fields) ? detail.customer_fields : [],
      pipeline_stages: Array.isArray(detail.pipeline_stages) && detail.pipeline_stages.length
        ? detail.pipeline_stages : defaultCrmPipelineStages.map((item) => ({ ...item })),
    };
  } catch (err) {
    crmConfigError.value = friendlyErrorMessage(err, "Chưa tải được cấu hình trường và pipeline.");
  } finally {
    crmConfigLoading.value = false;
  }
}

function addCrmCustomerField() {
  const draft = crmFieldDraft.value;
  const key = draft.key.trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "");
  const field = { key, label: draft.label.trim(), type: draft.type, options: draft.type === "select" ? draft.options.split(",").map((value) => value.trim()).filter(Boolean) : [] };
  if (!field.key || !field.label || crmConfig.value.customer_fields.some((item) => item.key === field.key)) {
    crmConfigError.value = "Nhập mã và tên trường hợp lệ, chưa được dùng.";
    return;
  }
  crmConfig.value.customer_fields.push(field);
  crmFieldDraft.value = { key: "", label: "", type: "text", options: "" };
  crmConfigError.value = "";
}

function addCrmPipelineStage() {
  const label = crmStageDraft.value.trim();
  const base = label.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 26);
  if (!label || !base || crmConfig.value.pipeline_stages.length >= 20) return;
  let key = base;
  let suffix = 2;
  while (crmConfig.value.pipeline_stages.some((item) => item.key === key)) key = `${base.slice(0, 27 - String(suffix).length)}_${suffix++}`;
  crmConfig.value.pipeline_stages.push({ key, label });
  crmStageDraft.value = "";
}

async function saveCrmConfig() {
  if (!canManageWorkspace.value) return;
  crmConfigSaving.value = true;
  crmConfigError.value = "";
  crmConfigNotice.value = "";
  try {
    const payload = {
      customer_fields: crmConfig.value.customer_fields.map(({ key, label, type, options }) => ({ key, label, type, options: type === "select" ? options || [] : [] })),
      pipeline_stages: crmConfig.value.pipeline_stages,
    };
    const response = await apiFetch(`${API_BASE}/workspace/crm-config`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    crmConfig.value = detail;
    crmConfigNotice.value = "Đã lưu trường khách hàng và pipeline cho shop.";
  } catch (err) {
    crmConfigError.value = friendlyErrorMessage(err, "Chưa lưu được cấu hình quản lý khách hàng.");
  } finally {
    crmConfigSaving.value = false;
  }
}

async function saveCustomerCustomFields() {
  const customerId = customer360.value?.id;
  if (!customerId || customerCustomFieldsSaving.value) return;
  customerCustomFieldsSaving.value = true;
  customerCustomFieldsError.value = "";
  customerCustomFieldsNotice.value = "";
  const values = Object.fromEntries(Object.entries(customerCustomFieldsDraft.value).filter(([key, value]) => (
    crmConfig.value.customer_fields.some((field) => field.key === key) && value !== "" && value !== null && value !== undefined
  )));
  try {
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/custom-fields`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    customerCustomFieldsDraft.value = detail.custom_fields || {};
    customer360.value = { ...customer360.value, custom_fields: detail.custom_fields || {} };
    customerCustomFieldsNotice.value = "Đã lưu thông tin bổ sung.";
  } catch (err) {
    customerCustomFieldsError.value = friendlyErrorMessage(err, "Chưa lưu được thông tin bổ sung.");
  } finally {
    customerCustomFieldsSaving.value = false;
  }
}

function workspaceModuleEnabled(module) {
  return workspaceConfig.value.enabled_modules.includes(module);
}

async function fetchWorkspaceConfig() {
  if (!authUser.value || !tenantReady.value) return;
  workspaceConfigLoading.value = true;
  workspaceConfigError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/workspace/modules`);
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    workspaceConfig.value = {
      business_type: detail.business_type || "retail",
      enabled_modules: Array.isArray(detail.enabled_modules) ? detail.enabled_modules : ["retail"],
      modules: Array.isArray(detail.modules) ? detail.modules : [],
    };
  } catch (err) {
    workspaceConfigError.value = friendlyErrorMessage(err, "Chưa tải được mô hình shop.");
  } finally {
    workspaceConfigLoading.value = false;
  }
}

async function saveWorkspaceConfig() {
  if (!canManageWorkspace.value) return;
  workspaceConfigSaving.value = true;
  workspaceConfigError.value = "";
  workspaceConfigNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/workspace/modules`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        business_type: workspaceConfig.value.business_type,
        enabled_modules: workspaceConfig.value.enabled_modules,
      }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    workspaceConfig.value = { ...workspaceConfig.value, ...detail };
    workspaceConfigNotice.value = "Đã lưu mô hình và module cho shop. Dữ liệu cũ vẫn được giữ nguyên.";
    if ((["appointments"].includes(currentTab.value) && !workspaceModuleEnabled("appointments"))
      || (["commercial"].includes(currentTab.value) && !workspaceModuleEnabled("projects"))
      || (!workspaceModuleEnabled("retail") && ["products", "orders", "purchase-orders"].includes(currentTab.value))) {
      currentTab.value = "inbox";
    }
  } catch (err) {
    workspaceConfigError.value = friendlyErrorMessage(err, "Chưa lưu được cấu hình mô hình shop.");
  } finally {
    workspaceConfigSaving.value = false;
  }
}
const quotaLoading = ref(false);
const quotaError = ref("");
const serviceAccountSummary = ref(null);
const serviceAccountLoading = ref(false);
const serviceAccountError = ref("");
const auditLogs = ref([]);
const auditLoading = ref(false);
const platformAdmin = ref(false);
const inPlatformAdminWorkspace = computed(() => (
  Boolean(authUser.value && platformAdmin.value && currentTab.value === "platform_admin")
));
const platformShops = ref([]);
const platformShopDetails = ref({});
const platformShopDetailLoadingIds = ref(new Set());
const platformShopMutatingIds = ref(new Set());
const platformShopNotice = ref("");
const platformPlans = ref([]);
const platformPlanEditingId = ref(null);
const platformPlanSaving = ref(false);
const platformPlanDeletingId = ref(null);
const platformPlanNotice = ref("");
const platformPlanForm = ref({
  code: "",
  name: "",
  description: "",
  price: 0,
  chatbot_rental_price: 0,
  billing_cycle: "monthly",
  max_users: 5,
  max_channels: 2,
  max_documents: 20,
  max_rag_chunks: 500,
  max_ai_calls: 1000,
  max_ai_cost: 100,
  features: {},
  status: "active",
});
const platformSchemas = ref([]);
const platformAuditLogs = ref([]);
const platformProviderErrors = ref([]);
const platformPendingRequests = ref([]);
const platformApprovalLoadingId = ref(null);
const platformApprovalNotice = ref("");
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
const customerTimelineFilterLoading = ref(false);
const customerTimelineFilterApplied = ref(false);
const customerTimelineFilterCustomerId = ref(null);
const customerTimelineDetailsOpen = ref(false);
const customerMessageSearchOpen = ref(false);
const customerMessageSearchCustomerId = ref(null);
const customerMessageSearchQuery = ref("");
const customerMessageSearchItems = ref([]);
const customerMessageSearchTotal = ref(0);
const customerMessageSearchOffset = ref(0);
const customerMessageSearchHasMore = ref(false);
const customerMessageSearchLoading = ref(false);
const customerMessageSearchError = ref("");
const customerMessageSearchJumpingId = ref(null);
let customerMessageSearchTimer = null;
const customerTimelineFilters = ref({
  start_date: "",
  end_date: "",
  staff_id: "",
});
const customerOrderHistory = ref([]);
const customerOrderHistoryLoading = ref(false);
const customerOrderHistoryExpanded = ref(false);
const customerTimelineHasFilters = computed(() => {
  const filters = customerTimelineFilters.value;
  return Boolean(filters.start_date || filters.end_date || filters.staff_id);
});
const customerTimelineSummaryCards = computed(() => {
  const summary = customer360.value?.timelineSummary;
  if (!summary) return [];
  return [
    { key: "events", value: summary.total_events || 0, label: "Hoạt động", note: `${summary.conversation_count || 0} hội thoại` },
    { key: "messages", value: summary.message_events || 0, label: "Tin nhắn", note: `${summary.customer_messages || 0} từ khách hàng` },
    { key: "staff", value: summary.staff_actions || 0, label: "Nhân viên", note: `${summary.automated_actions || 0} tự động / hệ thống` },
    { key: "operations", value: summary.operational_events || 0, label: "Nghiệp vụ", note: "Đơn hàng, hỗ trợ, phân công" },
  ];
});
const customerVisibleOrderHistory = computed(() => (
  customerOrderHistoryExpanded.value ? customerOrderHistory.value : customerOrderHistory.value.slice(0, 5)
));
const customerConfirmedOrderCount = computed(() => customerOrderHistory.value.filter((order) => (
  ["confirmed", "processing", "shipped", "delivered", "completed"].includes(String(order?.status || ""))
)).length);
const customerPendingApprovalOrders = computed(() => customerOrderHistory.value.filter((order) => (
  String(order?.status || "") === "pending_confirmation"
)));
const customerOrderApprovalNotice = ref("");
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
const teamOtpSending = ref(false);
const teamOtpSent = ref(false);
const teamDeletingId = ref(null);
const teamError = ref("");
const teamNotice = ref("");
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
  otp: "",
});

const documents = ref([]);
const documentRuns = ref({});
const docRetryingIds = ref(new Set());
const docsLoading = ref(false);
const docUploading = ref(false);
const docUploadError = ref("");
const docUploadNotice = ref("");
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
const specialBusinessDates = ref([]);
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
  channels: [],
  notes: "",
});
const serviceRequestSubmitted = ref(false);
const serviceRequestReference = ref("");
const serviceRequestError = ref("");
const serviceMode = ref("package");
const servicePurchaseLoading = ref(false);
const servicePurchaseNotice = ref("");
const servicePurchaseError = ref("");
const servicePurchaseStatus = ref("");
const SERVICE_CHANNELS = Object.freeze(["Facebook", "Instagram", "Telegram", "Zalo", "TikTok", "Shopee"]);
const SERVICE_CHANNEL_LIMITS = Object.freeze({ demo: 0, starter: 1, growth: 2, scale: 4, custom: 6, pro: 6, "bot-starter": 1, "bot-growth": 2, "bot-scale": 4, "bot-custom": 6 });
const FALLBACK_SERVICE_PLANS = Object.freeze([
  { code: "demo", name: "Gói Demo", price: 0, chatbot_rental_price: 0, description: "Dùng thử CRM, chưa mở kết nối kênh.", max_channels: 0 },
  { code: "starter", name: "Gói Thường", price: 0, chatbot_rental_price: 100000, description: "Gói gọn nhẹ cho shop mới bắt đầu chăm khách.", max_channels: 1 },
  { code: "growth", name: "Gói VIP", price: 400000, chatbot_rental_price: 400000, description: "Gói cân bằng cho shop cần nhiều kênh và đội ngũ chăm khách.", max_channels: 2 },
  { code: "scale", name: "Gói Scale", price: 1000000, chatbot_rental_price: 1000000, description: "Gói cho shop vận hành đồng thời trên 4 nền tảng.", max_channels: 4 },
  { code: "pro", name: "Gói Premium", price: 1500000, chatbot_rental_price: 1500000, description: "Gói đầy đủ cho shop vận hành đủ 6 nền tảng.", max_channels: 6 },
]);
const SERVICE_PLAN_CODES = new Set(["demo", "starter", "growth", "scale", "pro"]);
const CHATBOT_PLAN_COPY = Object.freeze({
  demo: { name: "Trợ lý Demo", description: "Xem thử cách trợ lý tiếp nhận và trả lời hội thoại." },
  starter: { name: "Trợ lý Cơ bản", description: "Bot trả lời FAQ và hỗ trợ các câu hỏi thường gặp." },
  growth: { name: "Trợ lý Nâng cao", description: "Bot tư vấn theo kho tri thức, sản phẩm và chuyển nhân viên." },
  scale: { name: "Trợ lý Scale", description: "Bot tư vấn cho shop vận hành nhiều kênh và quy trình hơn." },
  pro: { name: "Trợ lý Toàn diện", description: "Bot được cài đặt, theo dõi và tối ưu riêng cho shop." },
});
const publicServicePlans = ref([]);
const activeServicePlans = computed(() => {
  const returnedPlans = publicServicePlans.value;
  const returnedCodes = new Set(returnedPlans.map((plan) => plan.code));
  // A running API can still have an older seeded catalogue. Keep the
  // required public tiers visible until that service is restarted and seeds
  // the missing plan, without replacing any server-managed price or limit.
  const catalogue = returnedPlans.length
    ? [...returnedPlans.filter((plan) => SERVICE_PLAN_CODES.has(plan.code)), ...FALLBACK_SERVICE_PLANS.filter((plan) => !returnedCodes.has(plan.code))]
    : FALLBACK_SERVICE_PLANS;
  return catalogue
    .filter((plan) => !plan.status || plan.status === "active")
    .sort((left, right) => Number(left.max_channels || 0) - Number(right.max_channels || 0))
    .map((plan) => {
      const isChatbot = serviceMode.value === "chatbot";
      const chatbotCopy = CHATBOT_PLAN_COPY[plan.code] || CHATBOT_PLAN_COPY.starter;
      return {
        ...plan,
        name: isChatbot ? chatbotCopy.name : plan.name,
        description: isChatbot ? chatbotCopy.description : plan.description,
        price: formatPlanPrice(isChatbot ? chatbotRentalPrice(plan) : plan.price, plan.billing_cycle),
      };
    });
});
const selectedServicePlan = computed(() => (
  activeServicePlans.value.find((plan) => plan.code === serviceRequestForm.value.plan_code) || null
));
const serviceChannelLimit = computed(() => {
  const selectedLimit = Number(selectedServicePlan.value?.max_channels);
  if (Number.isFinite(selectedLimit)) return Math.max(0, selectedLimit);
  return Math.max(0, Number(SERVICE_CHANNEL_LIMITS[serviceRequestForm.value.plan_code] || 0));
});
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
const learningSummary = ref({ period_days: 30, inbound_messages: 0, conversations_sampled: 0, topics: [], response_feedback: {}, method: "" });
const learningSummaryLoading = ref(false);
const learningSummaryError = ref("");
const messageFeedback = ref({});

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
const tiktokBridgeSecret = ref("");
const tiktokBridgeEndpoint = ref("");
const tiktokBridgeBackendUrl = ref("");
const tiktokBridgeShopSlug = ref("");
const tiktokBridgeDownloadUrl = ref("");
const tiktokBridgeLoading = ref(false);
const tiktokBridgeError = ref("");
const tiktokBridgeNotice = ref("");
const notificationError = ref("");
const activeBotConnections = computed(() => botConnections.value.filter((item) => ["connected", "active"].includes(String(item.status || "").toLowerCase())));
const activeTikTokConnection = computed(() => activeBotConnections.value.find((item) => item.channel_type === "tiktok"));
const channelCapacity = computed(() => channelCapacityState(quotaSnapshot.value));
const demoChannelsLocked = computed(() => channelCapacity.value.blocked);


/* META OAUTH */
async function fetchMetaStatus() {
  if (!tenantReady.value) return;
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
  if (demoChannelsLocked.value) {
    metaNotice.value = channelCapacity.value.reason;
    return;
  }
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
  zalo: "https://docs.zaloplatforms.com/docs/BOT/create_bot",
});

function botGuideUrl(channelType) {
  return botGuideUrls[channelType] || botGuideUrls.telegram;
}

function botQrUrl(channelType) {
  const target = botGuideUrl(channelType);
  return `https://quickchart.io/qr?size=160&margin=2&text=${encodeURIComponent(target)}`;
}

function botChannelLabel(channelType) {
  return channelType === "zalo" ? "Zalo Bot" : "Telegram BotFather";
}

function botConnectionStateLabel(state) {
  return connectionStateMeta(state).label;
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
  if (!tenantReady.value) {
    botConnections.value = [];
    botConnectionError.value = "";
    botConnectionLoading.value = false;
    return;
  }
  botConnectionLoading.value = true;
  botConnectionError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/channels`);
    const detail = await response.json().catch(() => []);
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    botConnections.value = Array.isArray(detail)
      ? detail.filter((item) => ["telegram", "zalo", "tiktok"].includes(item.channel_type))
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
  if (demoChannelsLocked.value) {
    botConnectionError.value = channelCapacity.value.reason;
    return;
  }
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
        // Zalo tokens are sent to the official Bot API as entered.  The
        // explicit `personal:` prefix remains available for the local bridge.
        access_token: token,
      }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    botConnectionForm.value.access_token = "";
    botTokenVisible.value = false;
    botConnectionNotice.value = `${botChannelLabel(botConnectionForm.value.channel_type)} đã kết nối và nhận tin đang hoạt động.`;
    await fetchBotConnections();
  } catch (err) {
    // ProviderConnectionError responses are already sanitized by the API and
    // contain the actionable reason (for example an invalid token or webhook
    // URL). Do not hide that message behind the generic network fallback.
    const providerMessage = botConnectionErrorMessage(err?.payload, "");
    botConnectionError.value = err?.status === 429 && err?.payload?.detail?.code === "quota_exceeded"
      ? "Gói hiện tại đã hết số lượng kênh được phép. Hãy nâng cấp gói dịch vụ để kết nối thêm."
      : providerMessage
      || friendlyErrorMessage(err, "Chưa thể kiểm tra và kết nối bot. Hãy kiểm tra lại mã bot rồi thử lại.");
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
  if (!tenantReady.value) return;
  currentTab.value = "channels";
  if (!authUser.value) return;
  void fetchMetaStatus();
  void fetchBotConnections();
  void fetchQuotaUsage();
}

function openChannelModal(tab = "meta") {
  if (!tenantReady.value) return;
  // Keep each provider in its own focused dialog.  The old `bots` tab is
  // accepted for bookmarks/tests, but immediately resolves to Telegram so a
  // shop never submits a token for the wrong provider.
  const normalized = tab === "bots" ? "telegram" : tab;
  channelModalTab.value = ["meta", "facebook", "instagram", "telegram", "zalo", "tiktok"].includes(normalized) ? normalized : "meta";
  if (["telegram", "zalo"].includes(channelModalTab.value)) {
    botConnectionForm.value.channel_type = channelModalTab.value;
    botConnectionForm.value.access_token = "";
    botTokenVisible.value = false;
    botConnectionNotice.value = "";
    botConnectionError.value = "";
  }
  if (channelModalTab.value === "tiktok") {
    tiktokBridgeError.value = "";
    tiktokBridgeNotice.value = "";
  }
  channelModalOpen.value = true;
  if (authUser.value) void fetchQuotaUsage();
}

function closeChannelModal() {
  channelModalOpen.value = false;
}

function openServicePageFromChannelLimit() {
  closeChannelModal();
  openServicePage();
}

function openWebhooks() {
  if (!tenantReady.value) return;
  currentTab.value = "webhooks";
  if (!authUser.value) return;
  void fetchMetaStatus();
  void fetchBotConnections();
}

async function refreshWebhookStatus() {
  if (!tenantReady.value) return;
  await Promise.all([fetchMetaStatus(), fetchBotConnections()]);
}

function openSettings() {
  if (!tenantReady.value && !mfaVerifyPending.value) return;
  currentTab.value = "settings";
  if (!authUser.value) return;
  void fetchSecuritySettings();
  void fetchWorkspaceConfig();
  if (!tenantReady.value) return;
  void fetchTeam();
  void fetchAuditLogs();
  void fetchChatbotRuntime();
  void fetchFollowups();
  void fetchCsat();
  void fetchLearningSummary();
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

function handleBusinessLogoChange(event) {
  const input = event?.target;
  const file = input?.files?.[0];
  if (!file) return;
  if (!String(file.type || "").startsWith("image/")) {
    businessProfileNotice.value = "Vui lòng chọn một tệp hình ảnh.";
    if (input) input.value = "";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    businessProfileNotice.value = "Ảnh logo tối đa 5 MB. Vui lòng chọn ảnh nhỏ hơn.";
    if (input) input.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = String(reader.result || "");
    if (!dataUrl) return;
    businessProfile.value = { ...businessProfile.value, logo_url: dataUrl };
    businessProfileNotice.value = "Đã chọn logo. Nhấn “Lưu thông tin shop” để áp dụng.";
  };
  reader.onerror = () => {
    businessProfileNotice.value = "Chưa thể đọc ảnh logo. Vui lòng thử lại.";
  };
  reader.readAsDataURL(file);
}

function removeBusinessLogo() {
  businessProfile.value = { ...businessProfile.value, logo_url: "" };
  businessProfileNotice.value = "Đã gỡ ảnh logo. Nhấn “Lưu thông tin shop” để áp dụng.";
}

function saveLearningPreferences() {
  try {
    localStorage.setItem(`crm-learning-preferences-${authUser.value?.business_id || "shop"}`, JSON.stringify({ messageLearningEnabled: messageLearningEnabled.value, reinforcementLearningEnabled: reinforcementLearningEnabled.value }));
    learningNotice.value = "Đã lưu tùy chọn thu thập dữ liệu trên thiết bị này.";
  } catch {
    learningNotice.value = "Chưa thể lưu lựa chọn trên thiết bị này. Vui lòng thử lại sau.";
  }
}

async function fetchLearningSummary() {
  if (!tenantReady.value) return;
  learningSummaryLoading.value = true;
  learningSummaryError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/learning/summary?days=30`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    learningSummary.value = await response.json();
  } catch (err) {
    learningSummaryError.value = friendlyErrorMessage(err, "Chưa thể phân tích nhu cầu từ hội thoại. Vui lòng thử lại sau.");
  } finally {
    learningSummaryLoading.value = false;
  }
}

async function rateBotMessage(message, rating) {
  if (!message?.message_id || messageFeedback.value[message.message_id]) return;
  messageFeedback.value = { ...messageFeedback.value, [message.message_id]: { rating, loading: true } };
  try {
    const response = await apiFetch(`${API_BASE}/chatbot/messages/${message.message_id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rating,
        idempotency_key: `message-feedback-${authUser.value?.business_id || 'shop'}-${message.message_id}-${authUser.value?.id || 'staff'}`,
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    messageFeedback.value = { ...messageFeedback.value, [message.message_id]: { rating, loading: false } };
    learningNotice.value = "Đã ghi nhận đánh giá để shop theo dõi chất lượng. Đánh giá chưa tự thay đổi cách trợ lý trả lời.";
    void fetchLearningSummary();
  } catch (err) {
    const next = { ...messageFeedback.value };
    delete next[message.message_id];
    messageFeedback.value = next;
    error.value = friendlyErrorMessage(err, "Chưa thể ghi nhận đánh giá câu trả lời.");
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
  const specialDates = {};
  for (const item of specialBusinessDates.value) {
    const date = String(item?.date || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      businessHoursNotice.value = "Mỗi ngày đặc biệt cần có ngày hợp lệ.";
      return;
    }
    if (!item.closed && (!item.start || !item.end || item.start >= item.end)) {
      businessHoursNotice.value = "Khung giờ đặc biệt phải có giờ mở cửa sớm hơn giờ đóng cửa.";
      return;
    }
    specialDates[date] = item.closed
      ? { closed: true, windows: [] }
      : { closed: false, windows: [[item.start, item.end]] };
  }
  const hours = { timezone: businessHoursForm.value.timezone || "Asia/Ho_Chi_Minh", special_dates: specialDates };
  businessHourDayLabels.forEach(([key]) => { hours[key] = businessHoursDays.value[key] ? range : []; });
  businessHoursJson.value = JSON.stringify(hours);
  businessHoursNotice.value = "Đã cập nhật giờ làm việc và các ngày đặc biệt. Trợ lý sẽ áp dụng khi khách gửi tin nhắn.";
  void saveChatbotRuntime();
}

function addSpecialBusinessDate() {
  specialBusinessDates.value = [...specialBusinessDates.value, { date: "", closed: true, start: "08:00", end: "17:30" }];
}

function removeSpecialBusinessDate(index) {
  specialBusinessDates.value = specialBusinessDates.value.filter((_, itemIndex) => itemIndex !== index);
}

function saveSlaRules() {
  slaRulesNotice.value = `Đã lưu quy tắc: phản hồi trong ${slaRulesForm.value.firstResponseHours} giờ, xử lý trong ${slaRulesForm.value.resolutionHours} giờ.`;
}

function numericPlanPrice(value) {
  const amount = Number(value);
  return Number.isFinite(amount) && amount >= 0 ? amount : 0;
}

function chatbotRentalPrice(plan) {
  return numericPlanPrice(
    plan?.features?.chatbot_rental_price
    ?? plan?.chatbot_rental_price
    ?? plan?.price,
  );
}

function formatPlanPrice(value, billingCycle = "monthly") {
  const cycle = billingCycle === "yearly" ? "năm" : billingCycle === "one_time" ? "lần" : "tháng";
  return `${formatMoney(numericPlanPrice(value))} / ${t(cycle)}`;
}

function preferredServicePlanCode() {
  return activeServicePlans.value.find((plan) => plan.code === "growth")?.code
    || activeServicePlans.value[0]?.code
    || "growth";
}

function ensureServicePlanSelection() {
  if (!activeServicePlans.value.some((plan) => plan.code === serviceRequestForm.value.plan_code)) {
    serviceRequestForm.value.plan_code = preferredServicePlanCode();
    normalizeServiceChannels(false);
  }
}

async function fetchPublicServicePlans() {
  try {
    const response = await fetch(`${API_BASE}/onboarding/plans`);
    if (!response.ok) return;
    const plans = await response.json();
    if (!Array.isArray(plans)) return;
    publicServicePlans.value = plans;
    ensureServicePlanSelection();
  } catch {
    // The public fallback catalogue keeps the service page usable offline.
  }
}

function resetServiceRequestForm() {
  const planCode = preferredServicePlanCode();
  serviceRequestForm.value = {
    contact_name: authUser.value?.full_name || "",
    email: authUser.value?.email || "",
    phone: "",
    shop_name: authUser.value?.business?.name || authUser.value?.business_name || "",
    plan_code: planCode,
    channels: [],
    notes: "",
  };
  serviceRequestSubmitted.value = false;
  serviceRequestReference.value = "";
  serviceRequestError.value = "";
  serviceRequestNotice.value = "";
  servicePurchaseNotice.value = "";
  servicePurchaseError.value = "";
  servicePurchaseStatus.value = "";
}

function normalizeServiceChannels(fillToLimit = false) {
  if (serviceMode.value === "chatbot") {
    serviceRequestForm.value.channels = [];
    return;
  }
  const limit = serviceChannelLimit.value;
  const selected = new Set(serviceRequestForm.value.channels || []);
  const normalized = SERVICE_CHANNELS.filter((channel) => selected.has(channel)).slice(0, limit);
  if (fillToLimit) {
    SERVICE_CHANNELS.forEach((channel) => {
      if (normalized.length < limit && !normalized.includes(channel)) normalized.push(channel);
    });
  }
  serviceRequestForm.value.channels = normalized;
}

function selectServicePlan(planCode) {
  serviceRequestForm.value.plan_code = planCode;
  normalizeServiceChannels(false);
  serviceRequestSubmitted.value = false;
  serviceRequestError.value = "";
  servicePurchaseNotice.value = "";
  servicePurchaseError.value = "";
  servicePurchaseStatus.value = "";
}

function selectServiceMode(mode) {
  serviceMode.value = mode === "chatbot" ? "chatbot" : "package";
  serviceRequestForm.value.plan_code = preferredServicePlanCode();
  normalizeServiceChannels(false);
  serviceRequestSubmitted.value = false;
  serviceRequestReference.value = "";
  serviceRequestError.value = "";
  serviceRequestNotice.value = "";
  servicePurchaseNotice.value = "";
  servicePurchaseError.value = "";
  servicePurchaseStatus.value = "";
}

function openServicePage() {
  serviceLandingOpen.value = false;
  currentTab.value = "service";
  void fetchPublicServicePlans();
  if (!serviceRequestForm.value.contact_name && authUser.value) resetServiceRequestForm();
  if (authUser.value) {
    void fetchQuotaUsage();
    void fetchServiceAccountSummary();
  }
}

function openPublicServicePage() {
  serviceLandingOpen.value = true;
  currentTab.value = "service";
  void fetchPublicServicePlans();
  resetServiceRequestForm();
}

function closePublicServicePage() {
  serviceLandingOpen.value = false;
  currentTab.value = "inbox";
}

function toggleServiceChannel(channel) {
  const selectedChannels = new Set(serviceRequestForm.value.channels || []);
  if (selectedChannels.has(channel)) selectedChannels.delete(channel);
  else if (selectedChannels.size < serviceChannelLimit.value) selectedChannels.add(channel);
  serviceRequestForm.value.channels = SERVICE_CHANNELS.filter((item) => selectedChannels.has(item));
}

async function submitServiceRequest() {
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
  if (!authUser.value?.business_id) {
    serviceRequestError.value = "Hãy đăng nhập vào tài khoản shop để gửi yêu cầu cho quản trị viên duyệt.";
    return;
  }

  serviceRequestError.value = "";
  const detail = await purchaseServicePlan();
  if (!detail) return;

  serviceRequestReference.value = `SMH-${detail.id}`;
  serviceRequestSubmitted.value = true;
  serviceRequestNotice.value = detail.status === "pending"
    ? "Yêu cầu đã được chuyển tới quản trị viên nền tảng để duyệt."
    : "Gói Demo đã được kích hoạt cho shop.";
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

function subscriptionStatusLabel(status) {
  if (status === "active") return t("Đang hoạt động");
  if (status === "pending") return t("Đang chờ quản trị viên duyệt");
  if (status === "cancelled") return t("Yêu cầu đã bị từ chối hoặc hủy");
  if (status === "expired") return t("Đã hết hiệu lực");
  return t("Chưa kích hoạt");
}

async function purchaseServicePlan() {
  if (!authUser.value?.business_id) {
    servicePurchaseError.value = "Hãy đăng nhập vào shop trước khi gửi yêu cầu gói.";
    return null;
  }
  if (servicePurchaseLoading.value) return null;
  const planCode = servicePlanCodeForPurchase(serviceRequestForm.value.plan_code);
  servicePurchaseLoading.value = true;
  servicePurchaseError.value = "";
  servicePurchaseNotice.value = "";
  servicePurchaseStatus.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/subscription/purchase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_code: planCode,
        service_type: serviceMode.value,
        contact_name: String(serviceRequestForm.value.contact_name || "").trim(),
        contact_email: String(serviceRequestForm.value.email || "").trim().toLowerCase(),
        contact_phone: String(serviceRequestForm.value.phone || "").trim() || null,
        shop_name: String(serviceRequestForm.value.shop_name || "").trim(),
        channels: [...serviceRequestForm.value.channels],
        notes: String(serviceRequestForm.value.notes || "").trim() || null,
      }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    servicePurchaseStatus.value = String(detail.status || "");
    if (detail.status === "pending") {
      servicePurchaseNotice.value = serviceMode.value === "chatbot"
        ? `Đã gửi yêu cầu thuê trợ lý ${detail.plan_name || planCode}. Shop sẽ mở không gian làm việc sau khi quản trị viên duyệt và dữ liệu được chuẩn bị.`
        : `Đã gửi yêu cầu thuê gói ${detail.plan_name || planCode}. Yêu cầu đang chờ quản trị viên duyệt và không gian làm việc sẽ mở sau khi dữ liệu riêng được chuẩn bị.`;
      await Promise.all([fetchServiceAccountSummary(), fetchTenantProvisioning()]);
    } else {
      servicePurchaseNotice.value = `Đã kích hoạt gói ${detail.plan_name || planCode}. Shop có thể kết nối kênh và thêm nhân viên theo hạn mức.`;
      await Promise.all([fetchQuotaUsage(), fetchServiceAccountSummary(), fetchTenantProvisioning()]);
    }
    return detail;
  } catch (err) {
    servicePurchaseError.value = friendlyErrorMessage(err, "Chưa thể gửi yêu cầu gói lúc này. Vui lòng thử lại sau.");
    return null;
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
  if (authUser.value && !tenantReady.value) return;
  quickActionOpen.value = true;
  quickActionQuery.value = "";
  nextTick(() => quickActionInput.value?.focus());
}

function closeQuickActions() {
  quickActionOpen.value = false;
  quickActionQuery.value = "";
}

async function runQuickAction(actionId) {
  if (authUser.value && !tenantReady.value) {
    closeQuickActions();
    return;
  }
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
  if (authUser.value && !tenantReady.value) {
    if (event.key === "Escape" && quickActionOpen.value) closeQuickActions();
    return;
  }
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
  if (authUser.value && !tenantReady.value) return;
  currentTab.value = "inbox";
  nextTick(() => document.querySelector(".search-box input")?.focus());
}

async function fetchOperationalNotifications() {
  if (!tenantReady.value) {
    operationalNotifications.value = [];
    notificationError.value = "";
    return;
  }
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
  if (!tenantReady.value) {
    notificationsOpen.value = false;
    return;
  }
  notificationsOpen.value = !notificationsOpen.value;
  if (notificationsOpen.value) await fetchOperationalNotifications();
}

async function activateNotification(notification) {
  if (!tenantReady.value) return;
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
  currentTab.value = destination.tab === "appointments" && !workspaceModuleEnabled("appointments")
    ? "settings"
    : destination.tab;
  if (destination.tab === "orders") {
    await Promise.all([fetchOrderCustomers(), fetchProducts(), fetchOrders()]);
  } else if (destination.tab === "inbox") {
    await loadConversations(false);
    if (destination.conversationId) await selectConversation(destination.conversationId);
  } else if (destination.tab === "appointments") {
    // The appointments pane loads the shop calendar when mounted.
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
  docUploadNotice.value = "";
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
    docUploadNotice.value = "Đã nhận tài liệu. Hệ thống đang xử lý ở nền; bạn có thể tiếp tục làm việc.";
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
const selectedHasAiActivity = computed(() => Boolean(selected.value && (
  selectedBotMode.value === "human"
  || selected.value.resolution_outcome
  || messages.value.some((message) => message.direction === "outbound" && message.sender_type === "bot")
)));

// The inbox stays visible to every employee in the shop. Assignment is about
// accountability for customer-facing replies: once a conversation has an
// owner, other staff can read it but cannot send on that person's behalf.
const selectedAssignedUserId = computed(() => {
  const value = selected.value?.assigned_user_id;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
});

const canReplyToSelectedConversation = computed(() => {
  if (!selected.value) return false;
  return selectedAssignedUserId.value === null
    || Number(authUser.value?.id) === selectedAssignedUserId.value;
});

const selectedAssigneeName = computed(() => {
  if (selectedAssignedUserId.value === null) return "";
  return teamUsers.value.find((member) => Number(member.id) === selectedAssignedUserId.value)?.full_name || "nhân viên phụ trách";
});

const replyAccessNotice = computed(() => (
  selectedAssignedUserId.value === null
    ? "Chưa phân công: mọi nhân viên có thể phản hồi khách hàng."
    : canReplyToSelectedConversation.value
      ? "Bạn đang phụ trách hội thoại này."
      : `Bạn đang ở chế độ chỉ xem. ${selectedAssigneeName.value} là người phụ trách phản hồi.`
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

const criticalConversationNotificationCount = computed(() => (
  criticalConversationNotificationCounts(operationalNotifications.value)
));

function conversationUrgentCount(item) {
  // A pending order stays red until its real lifecycle state changes, even if
  // the staff member has already opened the notification bell.
  return Math.max(
    Number(item?.pending_order_confirmation_count || 0),
    Number(criticalConversationNotificationCount.value[item?.conversation_id] || 0),
  );
}

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
    pending_confirmation: "Chờ nhân viên xác nhận",
    confirmed: "Đã xác nhận",
    processing: "Đang đóng gói",
    shipped: "Đang giao",
    delivered: "Đã giao",
    completed: "Hoàn thành",
    refunded: "Đã hoàn tiền",
    cancelled: "Đã hủy",
  };
  return t(labels[status] || status || "Chưa rõ");
}

function leadStageLabel(stage) {
  return crmConfig.value.pipeline_stages.find((item) => item.key === stage)?.label || stage || "Chưa rõ";
}

function ticketStatusLabel(status) {
  const labels = {
    open: "Đang mở",
    pending: "Đang chờ",
    resolved: "Đã xử lý",
    closed: "Đã đóng",
  };
  return t(labels[status] || status || "Chưa rõ");
}

function ticketPriorityLabel(priority) {
  const labels = { low: "Thấp", normal: "Bình thường", high: "Cao", urgent: "Khẩn cấp" };
  return t(labels[priority] || priority || "Bình thường");
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
  return t(labels[status] || status || "Chưa rõ");
}

function paymentStatusLabel(status) {
  const labels = { unpaid: "Chưa thanh toán", partially_paid: "Thanh toán một phần", paid: "Đã thanh toán", refunded: "Đã hoàn tiền" };
  return t(labels[status] || status || "Chưa rõ");
}

function shippingStatusLabel(status) {
  const labels = {
    pending: "Chưa bàn giao",
    in_transit: "Đang vận chuyển",
    delivered: "Đã giao",
    failed: "Giao thất bại",
    returned: "Đã hoàn",
  };
  return t(labels[status] || status || "Chưa rõ");
}

function modelStatusLabel(status) {
  const labels = { draft: "Bản nháp", training: "Đang huấn luyện", ready: "Sẵn sàng", failed: "Lỗi" };
  return t(labels[status] || status || "Chưa rõ");
}

function experimentStatusLabel(status) {
  const labels = { draft: "Bản nháp", running: "Đang chạy", paused: "Tạm dừng", completed: "Đã hoàn tất", archived: "Đã lưu trữ" };
  return t(labels[status] || status || "Chưa rõ");
}

function policyStatusLabel(status) {
  const labels = { active: "Đang dùng", paused: "Tạm dừng", archived: "Đã lưu trữ" };
  return t(labels[status] || status || "Chưa rõ");
}

function documentEmbeddingStatusLabel(status) {
  const labels = { pending: "Chờ xử lý", processing: "Đang xử lý", ready: "Sẵn sàng", completed: "Đã hoàn tất", failed: "Lỗi", lexical_only: "Đã sẵn sàng" };
  return t(labels[status] || status || "Chưa rõ");
}

function ragRunStatusLabel(status) {
  const labels = { queued: "Đang chuẩn bị", processing: "Đang xử lý", completed: "Đã hoàn tất", failed: "Chưa xử lý được" };
  return t(labels[status] || status || "Chưa rõ");
}

function ragRunPhaseLabel(phase) {
  const labels = { load: "đọc tài liệu", chunk: "phân tích nội dung", embed: "xử lý nội dung", store: "hoàn thiện", complete: "hoàn tất" };
  return t(labels[phase] || phase || "đang xử lý");
}

function workflowEventLabel(event) {
  const labels = {
    "message.created": "Tin nhắn mới",
    "ticket.created": "Tạo phiếu hỗ trợ",
    "ticket.status_changed": "Phiếu đổi trạng thái",
    "lead.stage_changed": "Cơ hội đổi giai đoạn",
    "order.created": "Tạo đơn hàng",
    "appointment.created": "Tạo lịch hẹn",
    "appointment.status_changed": "Lịch hẹn đổi trạng thái",
    "quote.created": "Tạo báo giá",
    "quote.status_changed": "Báo giá đổi trạng thái",
    "project.created": "Tạo dự án",
    "project.status_changed": "Dự án đổi trạng thái",
    "invoice.created": "Tạo hóa đơn",
    "invoice.status_changed": "Hóa đơn đổi trạng thái",
    "invoice.payment_recorded": "Ghi nhận thanh toán hóa đơn",
  };
  return t(labels[event] || "Sự kiện mới");
}

function workflowActionLabel(action) {
  const labels = { create_ticket: "Tạo phiếu hỗ trợ", add_tag: "Gắn nhãn", assign_user: "Chuyển người hỗ trợ + gửi email" };
  return t(labels[action] || action || "Chưa rõ");
}

function workflowRunStatusLabel(status) {
  const labels = { queued: "Đang chờ", running: "Đang chạy", succeeded: "Đã hoàn tất", failed: "Lỗi", skipped: "Đã bỏ qua" };
  return t(labels[status] || status || "Chưa rõ");
}

function leadActivityTypeLabel(type) {
  const labels = { note: "Ghi chú", call: "Cuộc gọi", email: "Email", meeting: "Lịch hẹn", task: "Công việc" };
  return t(labels[type] || "Hoạt động");
}

function ticketHistoryEventLabel(type) {
  const labels = {
    created: "Tạo phiếu",
    status_changed: "Đổi trạng thái",
    assigned: "Phân công",
    comment_added: "Thêm ghi chú",
    priority_changed: "Đổi mức ưu tiên",
  };
  return t(labels[type] || "Cập nhật phiếu");
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
  return t(labels[type] || "Mục dữ liệu");
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
  return t(labels[role] || role || "Chưa rõ");
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
  return t(labels[resource] || resource || "Tài nguyên");
}

function schemaStateLabel(state) {
  const labels = { ready: "Sẵn sàng", disabled: "Đã tắt", pending: "Đang chờ", failed: "Lỗi" };
  return t(labels[state] || state || "Chưa rõ");
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
  return phone || customer?.channel || t("Khách hàng");
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
  const phoneQuery = String(inboxPersonalFilters.value.phone || "").replace(/\D/g, "");
  const emailQuery = String(inboxPersonalFilters.value.email || "").trim().toLowerCase();

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

      const linkedCustomerOk = !linkedCustomerOnly.value
        || Number(item.customer_id) === Number(selected.value?.customer_id);

      const phoneOk = !phoneQuery
        || String(item.customer_phone || "").replace(/\D/g, "").includes(phoneQuery);
      const emailOk = !emailQuery
        || String(item.customer_email || "").trim().toLowerCase().includes(emailQuery);

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
        && linkedCustomerOk
        && phoneOk
        && emailOk
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

const allVisibleConversationsSelected = computed(() =>
  filtered.value.length > 0
  && filtered.value.every((item) => bulkSelectedConversationIds.value.has(Number(item.conversation_id)))
);

watch(
  () => [
    search.value,
    activeFilter.value,
    inboxQuickFilter.value,
    inboxPersonalFilters.value.phone,
    inboxPersonalFilters.value.email,
    [...tagFilters.value].sort().join("\u0000"),
    tagFilterMode.value,
    selectedSegmentId.value,
  ],
  () => {
    if (!applyingSavedInboxView.value) selectedSavedInboxViewId.value = "";
  },
  { flush: "sync" },
);

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

  // The API stores legacy timestamps as naive UTC datetimes while provider
  // events and optimistic messages use ISO values with an explicit offset.
  // Treat only the naive form as UTC; otherwise browsers in different local
  // timezones show the same chat message at different times.
  const raw = typeof value === "string" ? value.trim() : value;
  const normalized = typeof raw === "string"
    && raw
    && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
    ? `${raw}Z`
    : raw;
  const date = new Date(normalized);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return "";
  }

  return new Intl.DateTimeFormat(
    uiLocale.value === "en" ? "en-US" : "vi-VN",
    {
      timeZone: "Asia/Ho_Chi_Minh",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
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
  void fetchOperationalNotifications();

}


function connectRealtime() {

  if (!tenantWorkspaceActive.value || !authUser.value || !tenantReady.value) {
    return;
  }

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

  const apiUrl = new URL(API_BASE, window.location.origin);
  const wsProtocol = apiUrl.protocol === "https:" ? "wss:" : "ws:";
  const accessToken = String(authToken.value || "").trim();
  if (!accessToken) return;
  const wsUrl = `${wsProtocol}//${apiUrl.host}/ws/conversations?access_token=${encodeURIComponent(accessToken)}`;

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
    if (!tenantWorkspaceActive.value || !authUser.value || !tenantReady.value) {
      return;
    }
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

  if (!selectedId.value || !canReplyToSelectedConversation.value) {

    error.value =
      selectedId.value
        ? "Hội thoại này đang có nhân viên phụ trách; bạn chỉ có thể xem nội dung."
        : "Hãy chọn một cuộc hội thoại trước.";

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
  if (!file || !canReplyToSelectedConversation.value) return;

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
  if (!selectedId.value || sending.value || composerMode.value === "internal" || !canReplyToSelectedConversation.value) return;
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
      ? "Bạn chưa cấp quyền microphone cho hệ thống."
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
  if (composerMode.value === "internal" || !canReplyToSelectedConversation.value) return;

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

function inboxSavedViewsStorageKey() {
  const businessId = authUser.value?.business_id || authUser.value?.business?.id || "shop";
  const userId = authUser.value?.id || authUser.value?.email || "staff";
  return `crm-inbox-saved-views-${businessId}-${userId}`;
}

function loadSavedInboxViews() {
  try {
    savedInboxViews.value = normalizeSavedInboxViews(JSON.parse(localStorage.getItem(inboxSavedViewsStorageKey()) || "[]"));
  } catch {
    savedInboxViews.value = [];
  }
}

function persistSavedInboxViews() {
  try {
    localStorage.setItem(inboxSavedViewsStorageKey(), JSON.stringify(savedInboxViews.value));
    return true;
  } catch {
    savedInboxViewError.value = "Không thể lưu chế độ xem trên thiết bị này.";
    return false;
  }
}

function currentInboxViewFilters() {
  return normalizeInboxViewFilters({
    search: search.value,
    channel: activeFilter.value,
    quickFilter: inboxQuickFilter.value,
    phone: inboxPersonalFilters.value.phone,
    email: inboxPersonalFilters.value.email,
    tags: tagFilters.value,
    tagFilterMode: tagFilterMode.value,
    segmentId: selectedSegmentId.value,
  });
}

function saveCurrentInboxView() {
  const name = savedInboxViewName.value.trim().slice(0, 48);
  if (!name) {
    savedInboxViewError.value = "Nhập tên chế độ xem trước khi lưu.";
    return;
  }
  const existing = savedInboxViews.value.find((view) => view.name.toLocaleLowerCase() === name.toLocaleLowerCase());
  if (!existing && savedInboxViews.value.length >= MAX_SAVED_INBOX_VIEWS) {
    savedInboxViewError.value = "Chỉ lưu tối đa 12 chế độ xem.";
    return;
  }
  const id = existing?.id || globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const view = { id, name, filters: currentInboxViewFilters() };
  savedInboxViews.value = existing
    ? savedInboxViews.value.map((item) => item.id === existing.id ? view : item)
    : [...savedInboxViews.value, view];
  savedInboxViewError.value = "";
  savedInboxViewNotice.value = "Đã lưu chế độ xem trên trình duyệt này.";
  savedInboxViewName.value = "";
  selectedSavedInboxViewId.value = id;
  persistSavedInboxViews();
}

function applySavedInboxView() {
  const view = savedInboxViews.value.find((item) => item.id === selectedSavedInboxViewId.value);
  if (!view) return;
  const filters = normalizeInboxViewFilters(view.filters);
  applyingSavedInboxView.value = true;
  search.value = filters.search;
  activeFilter.value = filters.channel;
  inboxQuickFilter.value = filters.quickFilter;
  inboxPersonalFilters.value = { phone: filters.phone, email: filters.email };
  tagFilters.value = filters.tags;
  tagFilterMode.value = filters.tagFilterMode;
  selectedSegmentId.value = filters.segmentId;
  applyingSavedInboxView.value = false;
  savedInboxViewError.value = "";
  savedInboxViewNotice.value = "Đã áp dụng chế độ xem.";
  void loadSegmentMembers();
}

function deleteSelectedInboxView() {
  const id = selectedSavedInboxViewId.value;
  if (!id) return;
  savedInboxViews.value = savedInboxViews.value.filter((view) => view.id !== id);
  selectedSavedInboxViewId.value = "";
  savedInboxViewNotice.value = "Đã xóa chế độ xem trên thiết bị này.";
  savedInboxViewError.value = "";
  persistSavedInboxViews();
}

function clearInboxPersonalFilters() {
  inboxPersonalFilters.value = { phone: "", email: "" };
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
    lead_stage: "Lịch sử cơ hội",
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
    lead_activity: "Hoạt động cơ hội",
    appointment: "Lịch hẹn",
    quote: "Báo giá",
    project: "Dự án",
    invoice: "Hóa đơn",
    invoice_payment: "Thanh toán hóa đơn",
  };
  return t(labels[event?.event_type] || channelLabel(event?.channel) || "Sự kiện CRM");
}

function orderEventLabel(event) {
  const labels = {
    status_changed: "Đổi trạng thái đơn",
    payment_created: "Ghi nhận thanh toán",
    refund_created: "Hoàn tiền",
    order_created: "Tạo đơn hàng",
    logistics_updated: "Cập nhật vận chuyển",
  };
  return t(labels[event?.event_type] || "Sự kiện đơn hàng");
}

function orderEventSummary(event) {
  if (event?.event_type === "status_changed") {
    return `${salesOrderStatusLabel(event.from_status)} → ${salesOrderStatusLabel(event.to_status)}`;
  }
  if (event?.event_type === "order_created") {
    return t("Khởi tạo đơn ở trạng thái draft");
  }
  if (event?.event_type === "logistics_updated") {
    const metadata = event?.metadata || event?.metadata_ || {};
    const provider = metadata.shipping_provider || "Chưa có đơn vị vận chuyển";
    const status = metadata.shipping_status || "pending";
    return `${provider} · ${shippingStatusLabel(status)}`;
  }
  const metadata = event?.metadata || event?.metadata_ || {};
  const amount = Number(metadata.amount || 0);
  if (amount > 0) return formatMoney(amount);
  return t("Không có chi tiết");
}

function chronologicalOrderEvents(events) {
  return [...(events || [])].sort((left, right) => {
    const leftTime = Date.parse(left?.created_at || "") || 0;
    const rightTime = Date.parse(right?.created_at || "") || 0;
    return leftTime - rightTime || Number(left?.id || 0) - Number(right?.id || 0);
  });
}

async function loadConversations(showLoading = true, {
  append = false,
  customerId = inboxCustomerFilterId.value,
} = {}) {

  if (showLoading && !append) {
    loading.value = true;
  }
  if (append) inboxLoadingMore.value = true;

  try {

    error.value = "";

    const offset = append ? conversations.value.length : 0;
    // Refreshes retain the number of rows that the operator has already
    // loaded, while a first visit deliberately starts with a short list.
    const limit = append
      ? INBOX_PAGE_SIZE
      : Math.min(50, Math.max(INBOX_PAGE_SIZE, conversations.value.length || 0));
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (customerId) params.set("customer_id", String(customerId));

    const response = await apiFetch(
      `${API_BASE}/conversations?${params}`
    );


    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw apiResponseError(
        response,
        data,
        `HTTP ${response.status}`,
      );
    }

    const page = Array.isArray(data) ? data : data.items || [];
    const supportsServerPaging = !Array.isArray(data)
      && Object.prototype.hasOwnProperty.call(data, "has_more");
    if (!supportsServerPaging) {
      inboxUsesLocalPaging.value = true;
      if (!append) {
        // Older deployments may not understand customer_id yet. Keep this
        // client-side guard so the linked-account view is still exact.
        inboxLegacyPageCache.value = customerId
          ? page.filter((item) => Number(item.customer_id) === Number(customerId))
          : page;
      }
      const cache = inboxLegacyPageCache.value;
      conversations.value = cache.slice(0, offset + (append ? INBOX_PAGE_SIZE : limit));
      inboxConversationTotal.value = cache.length;
      inboxHasMore.value = conversations.value.length < cache.length;
      return;
    }

    inboxUsesLocalPaging.value = false;
    if (append) {
      const knownIds = new Set(conversations.value.map((item) => Number(item.conversation_id)));
      conversations.value = [...conversations.value, ...page.filter((item) => !knownIds.has(Number(item.conversation_id)))];
    } else {
      conversations.value = page;
    }
    inboxConversationTotal.value = Number(data?.total ?? conversations.value.length);
    inboxHasMore.value = Boolean(data?.has_more);


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

    if (showLoading && !append) {
      loading.value = false;
    }
    if (append) inboxLoadingMore.value = false;

  }

}

function loadMoreConversations() {
  if (!inboxHasMore.value || inboxLoadingMore.value || loading.value) return;
  if (inboxUsesLocalPaging.value) {
    conversations.value = inboxLegacyPageCache.value.slice(0, conversations.value.length + INBOX_PAGE_SIZE);
    inboxHasMore.value = conversations.value.length < inboxLegacyPageCache.value.length;
    return;
  }
  return loadConversations(false, { append: true });
}

function handleInboxConversationScroll(event) {
  const target = event?.currentTarget;
  if (!target || target.scrollTop + target.clientHeight < target.scrollHeight - 96) return;
  void loadMoreConversations();
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


function handleAttachmentError(event) {
  const image = event?.target;
  if (!image) return;
  image.classList.add("media-load-failed");
  const link = image.closest?.(".message-media-link");
  if (link) {
    link.removeAttribute("href");
    link.setAttribute("aria-label", "Nội dung media không còn khả dụng");
  }
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
    const restocked = Number(detail.restocked ?? detail.updated ?? 0);
    const restockedQuantity = Number(detail.restocked_quantity || 0);
    const skipped = Number(detail.skipped || 0);
    const messages = [];
    if (imported) messages.push(`tạo ${imported} sản phẩm mới`);
    if (restocked) messages.push(`cộng thêm ${restockedQuantity} tồn kho cho ${restocked} mã đã có`);
    if (skipped) messages.push(`bỏ qua ${skipped} dòng`);
    productUploadNotice.value = messages.length
      ? `Đã ${messages.join(", ")}.`
      : "Không có thay đổi nào trong tệp.";
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

function productStatusLabel(status) {
  return t(status === "archived" ? "Lưu trữ" : "Đang bán");
}

async function changeProductStatus(product, status) {
  const nextStatus = String(status || "").trim();
  if (!product?.id || !["active", "archived"].includes(nextStatus) || product.status === nextStatus) return;

  const previousStatus = product.status || "active";
  productStatusSaving.value = { ...productStatusSaving.value, [product.id]: true };
  productError.value = "";
  productStatusNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/products/${product.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: nextStatus }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    product.status = detail.status || nextStatus;
    productStatusNotice.value = `Đã cập nhật trạng thái “${product.name}” thành ${productStatusLabel(product.status)}.`;
  } catch (err) {
    // The select is one-way bound so assigning the old value here also resets
    // the visible option when the API rejects the change.
    product.status = previousStatus;
    productError.value = friendlyErrorMessage(err, "Chưa thể cập nhật trạng thái sản phẩm. Vui lòng thử lại sau.");
  } finally {
    const nextSaving = { ...productStatusSaving.value };
    delete nextSaving[product.id];
    productStatusSaving.value = nextSaving;
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
    return true;
  } catch (err) {
    orderError.value = friendlyErrorMessage(err, "Chưa thể cập nhật đơn bán. Vui lòng thử lại sau.");
    await fetchOrders();
    return false;
  } finally {
    const nextSaving = { ...orderTransitionSaving.value };
    delete nextSaving[orderId];
    orderTransitionSaving.value = nextSaving;
  }
}

async function confirmCustomerOrder(order) {
  if (!order || String(order.status) !== "pending_confirmation") return;
  const approved = await requestConfirmation(
    `Xác nhận đơn ${order.order_number || `#${order.id}`} cho khách? Đơn sẽ chuyển sang trạng thái “Đã xác nhận”.`,
    { title: "Xác nhận đơn hàng", confirmLabel: "Đồng ý đơn", tone: "primary" },
  );
  if (!approved) return;
  customerOrderApprovalNotice.value = "";
  const confirmed = await transitionSalesOrder(order, "confirmed");
  await Promise.all([loadCustomerOrderHistory(order.customer_id), loadConversations(false), fetchOperationalNotifications()]);
  if (confirmed) customerOrderApprovalNotice.value = `Đã xác nhận ${order.order_number || `đơn #${order.id}`}.`;
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
      ? { idempotency_key: `ui-refund-${order.id}-${Date.now()}`, amount, reason: "Thao tác từ hệ thống" }
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
  return t(labels[event?.event_type] || "Cập nhật phiếu nhập");
}

function purchaseOrderEventSummary(event) {
  const metadata = event?.metadata || {};
  if (event?.event_type === "status_changed") return `${metadata.from_status || "—"} → ${metadata.to_status || "—"}`;
  if (metadata.amount !== undefined) return formatMoney(metadata.amount);
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
      body: JSON.stringify({ idempotency_key: `ui-receipt-${order.id}-${Date.now()}`, items, note: "Nhận hàng từ hệ thống" }),
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
  if (!tenantReady.value) {
    quotaSnapshot.value = null;
    quotaError.value = "";
    quotaLoading.value = false;
    return;
  }
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

function openSignup() {
  authView.value = "signup";
  signupStep.value = "details";
  signupLoading.value = false;
  signupError.value = "";
  signupNotice.value = "";
  signupForm.value = { owner_name: "", email: "", shop_name: "", password: "", otp: "" };
}

function openLogin() {
  authView.value = "login";
  signupLoading.value = false;
  signupError.value = "";
  signupNotice.value = "";
}

function invalidateSignupOtp() {
  if (signupStep.value !== "otp") return;
  signupStep.value = "details";
  signupForm.value.otp = "";
  signupNotice.value = "";
}

async function requestSignupOtp() {
  signupLoading.value = true;
  signupError.value = "";
  signupNotice.value = "";
  try {
    const payload = {
      owner_name: signupForm.value.owner_name.trim(),
      email: signupForm.value.email.trim().toLowerCase(),
      shop_name: signupForm.value.shop_name.trim(),
      password: signupForm.value.password,
    };
    const response = await fetch(`${API_BASE}/onboarding/signup/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof detail.detail === "string" ? detail.detail : detail.detail?.message || `HTTP ${response.status}`);
    signupForm.value.email = payload.email;
    signupStep.value = "otp";
    signupNotice.value = "Mã OTP đã được gửi tới email công việc. Mã có hiệu lực trong 10 phút.";
  } catch (err) {
    signupError.value = friendlyErrorMessage(err, "Chưa thể gửi mã xác minh. Vui lòng thử lại sau.");
  } finally {
    signupLoading.value = false;
  }
}

async function handleSignupSubmit() {
  if (signupStep.value === "otp") {
    await verifySignupOtp();
    return;
  }
  await requestSignupOtp();
}

async function verifySignupOtp() {
  signupLoading.value = true;
  signupError.value = "";
  signupNotice.value = "";
  try {
    const response = await fetch(`${API_BASE}/onboarding/signup/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: signupForm.value.email.trim().toLowerCase(), otp: signupForm.value.otp.trim() }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof detail.detail === "string" ? detail.detail : detail.detail?.message || `HTTP ${response.status}`);
    storeAuthToken(detail.access_token);
    authToken.value = detail.access_token;
    authUser.value = { business_id: detail.business_id, full_name: signupForm.value.owner_name, email: detail.owner_email, role: "owner", business: { name: detail.shop_name }, business_name: detail.shop_name };
    loginForm.value.email = detail.owner_email;
    loginForm.value.password = "";
    signupForm.value.password = "";
    signupForm.value.otp = "";
    signupNotice.value = "Đã tạo không gian shop. Bạn có thể chọn gói dịch vụ và kết nối kênh ngay bây giờ.";
    authView.value = "login";
    serviceLandingOpen.value = false;
    currentTab.value = "service";
    resetServiceRequestForm();
    loadBusinessProfile();
    loadThemePreference();
    loadSavedInboxViews();
    await fetchSecuritySettings();
    await fetchQuotaUsage();
    await fetchPlatformAdmin();
    await fetchTenantProvisioning();
    if (tenantReady.value) {
      await initializeTenantWorkspace();
    } else {
      currentTab.value = "service";
      signupNotice.value = "Đã tạo shop. Không gian dữ liệu riêng đang được chuẩn bị; hãy kiểm tra lại khi quá trình hoàn tất.";
    }
  } catch (err) {
    signupError.value = friendlyErrorMessage(err, "Mã OTP chưa đúng hoặc đã hết hạn. Vui lòng thử lại.");
  } finally {
    signupLoading.value = false;
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
    if (platformAdmin.value && !mfaVerifyPending.value) {
      // Platform admins operate the control plane (shops, plans and tenant
      // isolation), not a single shop's CRM inbox.
      currentTab.value = "platform_admin";
      return;
    }
    loadSavedInboxViews();
    if (!mfaVerifyPending.value) {
      await fetchTenantProvisioning();
      if (tenantReady.value) {
        currentTab.value = "inbox";
        await initializeTenantWorkspace();
      } else {
        currentTab.value = "service";
      }
    } else {
      currentTab.value = "settings";
    }
  } catch (err) {
    authError.value = friendlyErrorMessage(err, "Chưa thể đăng nhập lúc này. Vui lòng thử lại sau.");
  } finally {
    authLoading.value = false;
  }
}

async function logout() {
  try { if (authToken.value) await apiFetch(`${API_BASE}/auth/logout`, { method: "POST" }); } catch { /* session may already be expired */ }
  stopTenantProvisioningPolling();
  stopTenantWorkspace();
  clearAuthToken();
  authToken.value = "";
  authUser.value = null;
  tenantProvisioning.value = { state: "unknown", feature_enabled: false, subscription_active: false, subscription_status: null };
  tenantProvisioningError.value = "";
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
  const completingLoginMfa = Boolean(authUser.value?.mfa_required);
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
    if (completingLoginMfa) {
      await fetchTenantProvisioning();
      if (tenantReady.value) {
        currentTab.value = "inbox";
        await initializeTenantWorkspace();
      } else {
        currentTab.value = "service";
      }
    }
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
  if (!tenantReady.value) return;
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
  platformShopNotice.value = "";
  try {
    if (!authUser.value) {
      platformAdmin.value = false;
      platformShops.value = [];
      platformShopDetails.value = {};
      platformPlans.value = [];
      platformSchemas.value = [];
      platformAuditLogs.value = [];
      platformProviderErrors.value = [];
      platformPendingRequests.value = [];
      return;
    }
    const shopsResponse = await apiFetch(`${API_BASE}/platform/shops`);
    if (!shopsResponse.ok) {
      platformAdmin.value = false;
      platformShops.value = [];
      platformShopDetails.value = {};
      platformPlans.value = [];
      platformSchemas.value = [];
      platformAuditLogs.value = [];
      platformProviderErrors.value = [];
      platformPendingRequests.value = [];
      return;
    }
    const shopsPayload = await shopsResponse.json();
    platformAdmin.value = true;
    platformShops.value = shopsPayload.items || [];
    const availableShopIds = new Set(platformShops.value.map((shop) => String(shop.id)));
    platformShopDetails.value = Object.fromEntries(
      Object.entries(platformShopDetails.value).filter(([shopId]) => availableShopIds.has(shopId)),
    );
    const plansResponse = await apiFetch(`${API_BASE}/platform/plans`);
    platformPlans.value = plansResponse.ok ? await plansResponse.json() : [];
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
    const pendingRequestsResponse = await apiFetch(`${API_BASE}/platform/subscription-requests`);
    if (pendingRequestsResponse.ok) {
      const pendingPayload = await pendingRequestsResponse.json();
      platformPendingRequests.value = pendingPayload.items || [];
    } else {
      platformPendingRequests.value = [];
    }
  } catch (err) {
    platformAdmin.value = false;
    platformPlans.value = [];
    platformPendingRequests.value = [];
    platformAuditLogs.value = [];
    platformProviderErrors.value = [];
    platformError.value = friendlyErrorMessage(err, "Chưa tải được thông tin quản trị. Vui lòng thử lại sau.");
  } finally {
    platformLoading.value = false;
  }
}

function changePlatformShopIdState(stateRef, shopId, enabled) {
  const next = new Set(stateRef.value);
  if (enabled) next.add(String(shopId));
  else next.delete(String(shopId));
  stateRef.value = next;
}

function platformShopDetail(shopId) {
  return platformShopDetails.value[String(shopId)] || { open: false, loaded: false };
}

function platformShopQuota(shop) {
  return platformShopDetail(shop.id)?.usage?.quota || shop?.quota || {};
}

function platformShopLatestPayment(shop) {
  return latestPayment(platformShopDetail(shop.id)?.payments || []);
}

async function loadPlatformShopDetails(shop) {
  if (!shop?.id || platformShopDetailLoadingIds.value.has(String(shop.id))) return;
  changePlatformShopIdState(platformShopDetailLoadingIds, shop.id, true);
  const previous = platformShopDetail(shop.id);
  platformShopDetails.value = {
    ...platformShopDetails.value,
    [shop.id]: { ...previous, open: true, loading: true, error: "" },
  };

  try {
    const [subscriptionResponse, paymentsResponse, usageResponse] = await Promise.all([
      apiFetch(`${API_BASE}/platform/shops/${shop.id}/subscription`),
      apiFetch(`${API_BASE}/platform/shops/${shop.id}/payments`),
      apiFetch(`${API_BASE}/platform/shops/${shop.id}/usage`),
    ]);
    const subscription = subscriptionResponse.ok ? await subscriptionResponse.json() : null;
    const paymentsPayload = paymentsResponse.ok ? await paymentsResponse.json() : [];
    const usage = usageResponse.ok ? await usageResponse.json() : null;
    const payments = Array.isArray(paymentsPayload) ? paymentsPayload : paymentsPayload.items || [];
    // A shop without a package is a valid state, not a failed detail load.
    // The subscription endpoint returns 404 for that empty state.
    const subscriptionMissing = subscriptionResponse.status === 404;
    platformShopDetails.value = {
      ...platformShopDetails.value,
      [shop.id]: {
        ...platformShopDetail(shop.id),
        open: true,
        loading: false,
        loaded: true,
        subscription,
        payments,
        usage,
        error: (subscriptionResponse.ok || subscriptionMissing) && paymentsResponse.ok && usageResponse.ok
          ? ""
          : "Một phần thông tin chi tiết chưa tải được. Hãy thử lại.",
      },
    };
  } catch (err) {
    platformShopDetails.value = {
      ...platformShopDetails.value,
      [shop.id]: {
        ...platformShopDetail(shop.id),
        open: true,
        loading: false,
        loaded: false,
        error: friendlyErrorMessage(err, "Chưa tải được chi tiết tenant. Vui lòng thử lại."),
      },
    };
  } finally {
    changePlatformShopIdState(platformShopDetailLoadingIds, shop.id, false);
  }
}

function togglePlatformShopDetails(shop) {
  const detail = platformShopDetail(shop.id);
  if (detail.open) {
    platformShopDetails.value = {
      ...platformShopDetails.value,
      [shop.id]: { ...detail, open: false },
    };
    return;
  }
  if (detail.loaded) {
    platformShopDetails.value = {
      ...platformShopDetails.value,
      [shop.id]: { ...detail, open: true },
    };
    return;
  }
  void loadPlatformShopDetails(shop);
}

async function refreshPlatformSubscriptionRequests() {
  if (!authUser.value || !platformAdmin.value || platformLoading.value || platformRequestRefreshInFlight) return;
  platformRequestRefreshInFlight = true;
  try {
    const response = await apiFetch(`${API_BASE}/platform/subscription-requests`);
    if (!response.ok) return;
    const payload = await response.json();
    platformPendingRequests.value = Array.isArray(payload.items) ? payload.items : [];
  } catch (err) {
    console.warn("Could not refresh pending platform approvals.", err);
  } finally {
    platformRequestRefreshInFlight = false;
  }
}

function platformServiceLabel(serviceType) {
  return t(serviceType === "chatbot" ? "Thuê trợ lý chatbot" : "Gói quản lý shop");
}

function formatPlatformRequestDate(value) {
  if (!value) return t("Vừa gửi");
  const timestamp = typeof value === "string" && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? `${value}Z`
    : value;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? t("Vừa gửi") : formatDateTime(date);
}

async function approvePlatformSubscriptionRequest(request) {
  if (!request?.subscription_id || platformApprovalLoadingId.value) return;
  platformApprovalLoadingId.value = request.subscription_id;
  platformError.value = "";
  platformApprovalNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/platform/subscription-requests/${request.subscription_id}/approve`, {
      method: "POST",
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = detail.detail?.message || detail.detail || `HTTP ${response.status}`;
      throw new Error(typeof message === "string" ? message : "Chưa thể duyệt yêu cầu gói.");
    }
    const ready = detail.provisioning?.state === "active" && detail.provisioning?.feature_enabled;
    platformApprovalNotice.value = ready
      ? `Đã duyệt ${request.shop_name}. Không gian dữ liệu của shop đã sẵn sàng.`
      : `Đã duyệt ${request.shop_name}. Hệ thống đang chuẩn bị không gian dữ liệu cho shop.`;
    await fetchPlatformAdmin();
  } catch (err) {
    platformError.value = friendlyErrorMessage(err, "Chưa thể duyệt yêu cầu gói. Vui lòng thử lại sau.");
  } finally {
    platformApprovalLoadingId.value = null;
  }
}

async function rejectPlatformSubscriptionRequest(request) {
  if (!request?.subscription_id || platformApprovalLoadingId.value) return;
  const confirmed = await requestConfirmation(
    `Từ chối yêu cầu ${request.plan_name} của ${request.shop_name}? Shop sẽ chưa được mở quyền sử dụng hệ thống.`,
    { title: "Từ chối yêu cầu thuê gói", confirmLabel: "Từ chối yêu cầu", tone: "danger" },
  );
  if (!confirmed) return;

  platformApprovalLoadingId.value = request.subscription_id;
  platformError.value = "";
  platformApprovalNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/platform/subscription-requests/${request.subscription_id}/reject`, {
      method: "POST",
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = detail.detail?.message || detail.detail || `HTTP ${response.status}`;
      throw new Error(typeof message === "string" ? message : "Chưa thể từ chối yêu cầu gói.");
    }
    platformApprovalNotice.value = `Đã từ chối yêu cầu của ${request.shop_name}.`;
    await fetchPlatformAdmin();
  } catch (err) {
    platformError.value = friendlyErrorMessage(err, "Chưa thể từ chối yêu cầu gói. Vui lòng thử lại sau.");
  } finally {
    platformApprovalLoadingId.value = null;
  }
}

function platformPlanDraft(plan = null) {
  return {
    code: plan?.code || "",
    name: plan?.name || "",
    description: plan?.description || "",
    price: numericPlanPrice(plan?.price),
    chatbot_rental_price: chatbotRentalPrice(plan),
    billing_cycle: plan?.billing_cycle || "monthly",
    max_users: Number(plan?.max_users ?? 5),
    max_channels: Number(plan?.max_channels ?? 2),
    max_documents: Number(plan?.max_documents ?? 20),
    max_rag_chunks: Number(plan?.max_rag_chunks ?? 500),
    max_ai_calls: Number(plan?.max_ai_calls ?? 1000),
    max_ai_cost: numericPlanPrice(plan?.max_ai_cost ?? 100),
    features: { ...(plan?.features || {}) },
    status: plan?.status || "active",
  };
}

function resetPlatformPlanForm() {
  platformPlanEditingId.value = null;
  platformPlanForm.value = platformPlanDraft();
  platformPlanNotice.value = "";
}

function editPlatformPlan(plan) {
  platformPlanEditingId.value = plan.id;
  platformPlanForm.value = platformPlanDraft(plan);
  platformPlanNotice.value = "";
}

async function savePlatformPlan() {
  const form = platformPlanForm.value;
  const code = String(form.code || "").trim().toLowerCase();
  const name = String(form.name || "").trim();
  if (!code || !name) {
    platformPlanNotice.value = "Hãy nhập mã và tên gói trước khi lưu.";
    return;
  }

  const payload = {
    code,
    name,
    description: String(form.description || "").trim() || null,
    price: numericPlanPrice(form.price),
    billing_cycle: form.billing_cycle || "monthly",
    max_users: Math.max(0, Number(form.max_users) || 0),
    max_channels: Math.max(0, Number(form.max_channels) || 0),
    max_documents: Math.max(0, Number(form.max_documents) || 0),
    max_rag_chunks: Math.max(0, Number(form.max_rag_chunks) || 0),
    max_ai_calls: Math.max(0, Number(form.max_ai_calls) || 0),
    max_ai_cost: numericPlanPrice(form.max_ai_cost),
    features: {
      ...(form.features || {}),
      chatbot_rental_price: numericPlanPrice(form.chatbot_rental_price),
    },
    status: form.status === "archived" ? "archived" : "active",
  };

  platformPlanSaving.value = true;
  platformPlanNotice.value = "";
  try {
    const isEditing = Boolean(platformPlanEditingId.value);
    const endpoint = isEditing
      ? `${API_BASE}/platform/plans/${platformPlanEditingId.value}`
      : `${API_BASE}/platform/plans`;
    const response = await apiFetch(endpoint, {
      method: isEditing ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    platformPlans.value = isEditing
      ? platformPlans.value.map((plan) => plan.id === detail.id ? detail : plan)
      : [...platformPlans.value, detail];
    platformPlanEditingId.value = null;
    platformPlanForm.value = platformPlanDraft();
    platformPlanNotice.value = "Đã lưu giá gói quản lý khách hàng và giá thuê trợ lý chatbot.";
    void fetchPublicServicePlans();
  } catch (err) {
    platformPlanNotice.value = friendlyErrorMessage(err, "Chưa thể lưu gói dịch vụ. Vui lòng thử lại sau.");
  } finally {
    platformPlanSaving.value = false;
  }
}

async function deletePlatformPlan(plan) {
  if (!plan?.id || platformPlanDeletingId.value) return;
  const confirmed = await requestConfirmation(
    `Xóa gói “${plan.name}”? Chỉ gói chưa từng được đăng ký mới có thể xóa.`,
    { title: "Xóa gói dịch vụ", confirmLabel: "Xóa gói", tone: "danger" },
  );
  if (!confirmed) return;
  platformPlanDeletingId.value = plan.id;
  platformPlanNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/platform/plans/${plan.id}`, { method: "DELETE" });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || `HTTP ${response.status}`);
    platformPlans.value = platformPlans.value.filter((item) => item.id !== plan.id);
    if (platformPlanEditingId.value === plan.id) resetPlatformPlanForm();
    platformPlanNotice.value = `Đã xóa gói ${plan.name}.`;
  } catch (err) {
    platformPlanNotice.value = friendlyErrorMessage(err, "Chưa thể xóa gói dịch vụ. Nếu gói đã có đăng ký, hãy chuyển sang Lưu trữ.");
  } finally {
    platformPlanDeletingId.value = null;
  }
}

async function togglePlatformShop(shop) {
  if (!shop?.id || platformShopMutatingIds.value.has(String(shop.id))) return;
  platformError.value = "";
  platformShopNotice.value = "";
  const status = shop.status === "suspended" ? "active" : "suspended";
  const action = status === "active" ? "mở lại" : "khóa";
  const confirmed = await requestConfirmation(
    `Bạn có chắc muốn ${action} shop “${shop.name}”? Người dùng của shop sẽ ${status === "active" ? "có thể truy cập hệ thống trở lại" : "tạm thời không thể truy cập hệ thống"}.`,
    { title: `${status === "active" ? "Mở" : "Khóa"} shop`, confirmLabel: `${status === "active" ? "Mở shop" : "Khóa shop"}`, tone: status === "active" ? "default" : "danger" },
  );
  if (!confirmed) return;
  changePlatformShopIdState(platformShopMutatingIds, shop.id, true);
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
    platformShopNotice.value = updated.status === "suspended"
      ? `Đã khóa ${shop.name}. Shop sẽ không thể truy cập hệ thống cho đến khi được mở lại.`
      : `Đã mở lại ${shop.name}. Người dùng có thể truy cập hệ thống theo gói hiện tại.`;
  } catch (err) {
    platformError.value = friendlyErrorMessage(err, "Chưa thể cập nhật trạng thái shop. Vui lòng thử lại sau.");
  } finally {
    changePlatformShopIdState(platformShopMutatingIds, shop.id, false);
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
    if (!crmConfig.value.pipeline_stages.some((item) => item.key === leadForm.value.stage)) {
      leadForm.value.stage = crmConfig.value.pipeline_stages[0]?.key || "new";
    }
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

function toggleBulkConversationSelection(conversationId, checked) {
  const next = new Set(bulkSelectedConversationIds.value);
  if (checked && next.size >= 100 && !next.has(Number(conversationId))) {
    bulkAssignmentError.value = "Chỉ có thể phân công tối đa 100 hội thoại cùng lúc.";
    return;
  }
  if (checked) next.add(Number(conversationId));
  else next.delete(Number(conversationId));
  bulkAssignmentError.value = "";
  bulkSelectedConversationIds.value = next;
}

function toggleVisibleConversationSelection(checked) {
  const next = new Set(bulkSelectedConversationIds.value);
  for (const conversation of filtered.value) {
    if (checked) next.add(Number(conversation.conversation_id));
    else next.delete(Number(conversation.conversation_id));
  }
  if (next.size > 100) {
    bulkAssignmentError.value = "Chỉ có thể phân công tối đa 100 hội thoại cùng lúc.";
    return;
  }
  bulkAssignmentError.value = "";
  bulkSelectedConversationIds.value = next;
}

async function bulkReassignConversations() {
  const conversationIds = [...bulkSelectedConversationIds.value];
  if (!conversationIds.length || !bulkAssignmentTarget.value || bulkAssignmentSaving.value) return;
  const assignedUserId = bulkAssignmentTarget.value === "unassigned" ? null : Number(bulkAssignmentTarget.value);
  const confirmed = await requestConfirmation(
    "Phân công các hội thoại đã chọn cho nhân viên này?",
    { title: t("Xác nhận phân công"), confirmLabel: t("Phân công") },
  );
  if (!confirmed) return;

  bulkAssignmentSaving.value = true;
  bulkAssignmentError.value = "";
  bulkAssignmentNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/conversations/bulk-assignment`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_ids: conversationIds, assigned_user_id: assignedUserId }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    const assignments = new Map((result.items || []).map((item) => [Number(item.conversation_id), item.assigned_user_id]));
    conversations.value = conversations.value.map((item) => assignments.has(Number(item.conversation_id))
      ? { ...item, assigned_user_id: assignments.get(Number(item.conversation_id)) }
      : item);
    if (selected.value && assignments.has(Number(selected.value.conversation_id))) {
      void loadCustomer360(selected.value.customer_id);
    }
    bulkAssignmentNotice.value = t("Phân công hàng loạt hoàn tất.");
    bulkSelectedConversationIds.value = new Set();
    bulkAssignmentTarget.value = "";
    bulkSelectionMode.value = false;
  } catch (err) {
    bulkAssignmentError.value = friendlyErrorMessage(err, "Chưa thể phân công hàng loạt. Vui lòng thử lại sau.");
  } finally {
    bulkAssignmentSaving.value = false;
  }
}

function closeBulkSelectionMode() {
  bulkSelectionMode.value = false;
  bulkSelectedConversationIds.value = new Set();
  bulkAssignmentTarget.value = "";
  bulkAssignmentError.value = "";
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
  return t({ pending: "Chờ duyệt", accepted: "Đã duyệt", rejected: "Từ chối" }[status] || status || "—");
}

function ruleActionLabel(action = {}) {
  if (action.type === "add_tag") return `${t("Gắn nhãn")}: ${action.tag || "—"}`;
  if (action.type === "create_ticket") return `${t("Tạo phiếu hỗ trợ")}: ${action.title || t("Nhắc chăm sóc")}`;
  if (action.type === "assign_user") return `${t("Phân công")}: #${action.user_id || "—"}`;
  return action.type || t("Chưa xác định");
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
  teamForm.value = { full_name: "", email: "", role: "agent", password: "", otp: "" };
  teamOtpSent.value = false;
  teamNotice.value = "";
}

function invalidateTeamOtp() {
  teamOtpSent.value = false;
  teamForm.value.otp = "";
  teamNotice.value = "";
}

function teamPasswordIsStrong(password) {
  const value = String(password || "");
  const groups = [/[a-z]/.test(value), /[A-Z]/.test(value), /\d/.test(value), /[^A-Za-z0-9\s]/.test(value)];
  return value.length >= 12 && groups.filter(Boolean).length >= 3;
}

async function requestTeamOtp() {
  const form = teamForm.value;
  if (!form.full_name.trim() || !form.email.trim()) {
    teamError.value = "Nhập họ tên và email công việc trước khi gửi mã OTP.";
    return;
  }
  if (!teamPasswordIsStrong(form.password)) {
    teamError.value = "Mật khẩu cần ít nhất 12 ký tự và 3 nhóm: chữ thường, chữ hoa, số, ký tự đặc biệt.";
    return;
  }
  teamOtpSending.value = true;
  teamError.value = "";
  teamNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/team/otp/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: form.full_name.trim(),
        email: form.email.trim().toLowerCase(),
        role: form.role,
        password: form.password,
      }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = typeof detail.detail === "string"
        ? detail.detail
        : detail.detail?.[0]?.msg || `HTTP ${response.status}`;
      throw new Error(message);
    }
    teamForm.value.email = String(detail.email || form.email).trim().toLowerCase();
    teamForm.value.otp = "";
    teamOtpSent.value = true;
    teamNotice.value = "Mã OTP đã được gửi tới email công việc. Mã có hiệu lực trong 10 phút.";
  } catch (err) {
    teamError.value = friendlyErrorMessage(err, "Chưa thể gửi mã OTP. Vui lòng thử lại sau.");
  } finally {
    teamOtpSending.value = false;
  }
}

async function saveTeamMember() {
  const form = teamForm.value;
  if (!form.full_name.trim() || !form.email.trim() || !teamPasswordIsStrong(form.password)) {
    teamError.value = "Họ tên, email và mật khẩu cần đủ tiêu chuẩn an toàn.";
    return;
  }
  if (!teamOtpSent.value || !/^\d{6}$/.test(String(form.otp || "").trim())) {
    teamError.value = "Hãy gửi và nhập mã OTP 6 chữ số trước khi thêm nhân viên.";
    return;
  }
  teamSaving.value = true;
  teamError.value = "";
  teamNotice.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/team/otp/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: form.email.trim(),
        otp: form.otp.trim(),
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    resetTeamForm();
    teamNotice.value = "Đã xác minh email và thêm nhân viên vào đúng shop.";
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

async function connectTikTokBridge() {
  if (demoChannelsLocked.value) {
    tiktokBridgeError.value = channelCapacity.value.reason;
    return;
  }
  tiktokBridgeLoading.value = true;
  tiktokBridgeError.value = "";
  tiktokBridgeNotice.value = "";
  tiktokBridgeDownloadUrl.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/onboarding/shops/${requireBusinessId(authUser.value)}/channels/tiktok/bridge`, { method: "POST" });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw apiResponseError(response, detail, `HTTP ${response.status}`);
    tiktokBridgeSecret.value = String(detail.bridge_secret || "");
    tiktokBridgeEndpoint.value = String(detail.webhook_url || `${window.location.origin}${API_BASE}/channels/tiktok/incoming`);
    tiktokBridgeBackendUrl.value = new URL(tiktokBridgeEndpoint.value, window.location.origin).origin;
    tiktokBridgeShopSlug.value = String(detail.shop_slug || "");
    const downloadResponse = await apiFetch(`${API_BASE}/channels/tiktok/bot-file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        business_id: requireBusinessId(authUser.value),
        shop_slug: tiktokBridgeShopSlug.value,
        bridge_secret: tiktokBridgeSecret.value,
        backend_url: tiktokBridgeBackendUrl.value,
        format: "exe",
        delivery: "url",
      }),
    });
    const downloadDetail = await downloadResponse.json().catch(() => ({}));
    if (!downloadResponse.ok) throw new Error(downloadDetail.detail || `HTTP ${downloadResponse.status}`);
    const downloadUrl = String(downloadDetail.download_url || "").trim();
    if (!downloadUrl) throw new Error("Chưa tạo được liên kết tải file ZIP TikTok");
    const parsedDownloadUrl = new URL(downloadUrl, window.location.origin);
    if (parsedDownloadUrl.origin !== window.location.origin) throw new Error("Liên kết tải file ZIP TikTok không hợp lệ");
    tiktokBridgeDownloadUrl.value = parsedDownloadUrl.toString();
    tiktokBridgeNotice.value = "Đã tạo cấu hình TikTok. Bây giờ hãy bấm tải ZIP để nhận file.";
    await fetchBotConnections();
    return detail;
  } catch (err) {
    tiktokBridgeError.value = botConnectionErrorMessage(err?.payload, "Chưa thể tạo kết nối TikTok bridge. Vui lòng thử lại sau.");
  } finally {
    tiktokBridgeLoading.value = false;
  }
}

async function deleteTeamMember(member) {
  if (member.role === "owner") {
    teamError.value = "Không thể xóa tài khoản chủ shop.";
    return;
  }
  if (!window.confirm(`Xóa tài khoản ${member.full_name} khỏi shop? Dữ liệu hội thoại và đơn hàng sẽ được giữ lại.`)) return;
  teamDeletingId.value = member.id;
  teamError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/team/${member.id}`, { method: "DELETE" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchTeam();
  } catch (err) {
    teamError.value = friendlyErrorMessage(err, "Chưa thể xóa tài khoản. Vui lòng thử lại sau.");
  } finally {
    teamDeletingId.value = null;
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

function customerTimelineRequestUrl(customerId, offset = 0) {
  const params = new URLSearchParams({
    limit: "20",
    offset: String(offset),
  });
  const filters = customerTimelineFilters.value;
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.staff_id) params.set("staff_id", String(filters.staff_id));
  return `${API_BASE}/customers/${customerId}/timeline?${params.toString()}`;
}

function resetCustomerMessageSearch() {
  if (customerMessageSearchTimer) {
    clearTimeout(customerMessageSearchTimer);
    customerMessageSearchTimer = null;
  }
  customerMessageSearchQuery.value = "";
  customerMessageSearchItems.value = [];
  customerMessageSearchTotal.value = 0;
  customerMessageSearchOffset.value = 0;
  customerMessageSearchHasMore.value = false;
  customerMessageSearchLoading.value = false;
  customerMessageSearchError.value = "";
  customerMessageSearchJumpingId.value = null;
}

async function openCustomerMessageSearch() {
  if (!customer360.value?.id) return;
  customerMessageSearchOpen.value = true;
  await nextTick();
  document.querySelector("[data-customer-message-search-input]")?.focus();
}

function closeCustomerMessageSearch() {
  customerMessageSearchOpen.value = false;
  resetCustomerMessageSearch();
}

function queueCustomerMessageSearch() {
  if (customerMessageSearchTimer) clearTimeout(customerMessageSearchTimer);
  const query = customerMessageSearchQuery.value.trim();
  if (query.length < 2) {
    customerMessageSearchItems.value = [];
    customerMessageSearchTotal.value = 0;
    customerMessageSearchOffset.value = 0;
    customerMessageSearchHasMore.value = false;
    customerMessageSearchError.value = "";
    return;
  }
  customerMessageSearchTimer = setTimeout(() => {
    customerMessageSearchTimer = null;
    void searchCustomerMessages();
  }, 260);
}

async function searchCustomerMessages(append = false) {
  const customerId = customer360.value?.id;
  const query = customerMessageSearchQuery.value.trim();
  if (!customerId || query.length < 2 || customerMessageSearchLoading.value) return;

  const offset = append ? customerMessageSearchOffset.value : 0;
  customerMessageSearchLoading.value = true;
  customerMessageSearchError.value = "";
  try {
    const params = new URLSearchParams({ q: query, limit: "10", offset: String(offset) });
    const response = await apiFetch(`${API_BASE}/customers/${customerId}/message-search?${params.toString()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const page = await response.json();
    // Ignore a late response for text the user has already replaced.
    if (query !== customerMessageSearchQuery.value.trim()) return;
    const incoming = page.items || [];
    const knownIds = new Set(append ? customerMessageSearchItems.value.map((item) => item.message_id) : []);
    const uniqueIncoming = incoming.filter((item) => !knownIds.has(item.message_id));
    customerMessageSearchItems.value = append
      ? [...customerMessageSearchItems.value, ...uniqueIncoming]
      : uniqueIncoming;
    customerMessageSearchTotal.value = page.total || 0;
    customerMessageSearchOffset.value = page.next_offset ?? (offset + incoming.length);
    customerMessageSearchHasMore.value = Boolean(page.has_more);
  } catch (err) {
    customerMessageSearchError.value = "Không thể tìm trong hội thoại. Vui lòng thử lại.";
  } finally {
    customerMessageSearchLoading.value = false;
  }
}

function handleCustomerMessageSearchScroll(event) {
  const element = event.currentTarget;
  if (
    customerMessageSearchHasMore.value
    && !customerMessageSearchLoading.value
    && element.scrollHeight - element.scrollTop - element.clientHeight < 64
  ) {
    void searchCustomerMessages(true);
  }
}

function customerMessageSearchActor(item) {
  if (item.direction === "inbound") return "Khách hàng";
  if (item.sender_type === "staff") return "Nhân viên";
  if (item.sender_type === "bot") return "Chatbot";
  return "Phản hồi";
}

function customerMessageSearchPreview(item) {
  const text = String(item?.content || "").replace(/\s+/g, " ").trim();
  return text.length > 110 ? `${text.slice(0, 107).trimEnd()}...` : text || "Tin nhắn không có nội dung văn bản";
}

async function jumpToCustomerSearchMessage(item) {
  if (!item?.conversation_id || !item?.message_id) return;
  customerMessageSearchJumpingId.value = item.message_id;
  customerMessageSearchError.value = "";
  try {
    if (!conversations.value.some((conversation) => Number(conversation.conversation_id) === Number(item.conversation_id))) {
      await loadConversations(false);
    }
    if (!conversations.value.some((conversation) => Number(conversation.conversation_id) === Number(item.conversation_id))) {
      throw new Error("Conversation unavailable");
    }
    await selectConversation(Number(item.conversation_id));
    closeCustomerMessageSearch();
    await nextTick();
    const messageElement = document.querySelector(`[data-message-id="${item.message_id}"]`);
    if (!messageElement) throw new Error("Message unavailable");
    messageElement.scrollIntoView({ behavior: "smooth", block: "center" });
    messageElement.classList.add("search-jump-highlight");
    window.setTimeout(() => messageElement.classList.remove("search-jump-highlight"), 2200);
  } catch (err) {
    customerMessageSearchError.value = "Không thể mở đúng tin nhắn này. Vui lòng thử lại.";
  } finally {
    customerMessageSearchJumpingId.value = null;
  }
}

function customerTimelineContent(event) {
  const content = String(event?.content || "").replace(/\s+/g, " ").trim();
  if (!content) return "Sự kiện không có nội dung.";
  // The full chat transcript belongs in the conversation pane. Customer 360
  // only keeps a small audit preview so a long message cannot dominate a profile.
  return content.length > 160 ? `${content.slice(0, 157).trimEnd()}...` : content;
}

async function loadCustomerOrderHistory(customerId) {
  if (!customerId) {
    customerOrderHistory.value = [];
    customerOrderHistoryExpanded.value = false;
    return;
  }
  customerOrderHistoryLoading.value = true;
  try {
    const response = await apiFetch(`${API_BASE}/orders?customer_id=${encodeURIComponent(customerId)}&limit=50&offset=0`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    customerOrderHistory.value = data.items || [];
  } catch (err) {
    console.error("Customer order history loading error:", err);
    customerOrderHistory.value = [];
  } finally {
    customerOrderHistoryLoading.value = false;
  }
}

async function loadCustomer360(customerId) {
  if (!customerId) {
    customer360.value = null;
    customer360Error.value = "";
    customerMessageSearchOpen.value = false;
    resetCustomerMessageSearch();
    return;
  }

  const numericCustomerId = Number(customerId);
  if (customerTimelineFilterCustomerId.value !== numericCustomerId) {
    customerTimelineFilterCustomerId.value = numericCustomerId;
    customerTimelineFilters.value = { start_date: "", end_date: "", staff_id: "" };
    customerTimelineFilterApplied.value = false;
    customerTimelineDetailsOpen.value = false;
    customerOrderHistoryExpanded.value = false;
    customerTimelineError.value = "";
  }
  if (customerMessageSearchCustomerId.value !== numericCustomerId) {
    customerMessageSearchCustomerId.value = numericCustomerId;
    customerMessageSearchOpen.value = false;
    resetCustomerMessageSearch();
  }
  customer360Loading.value = true;
  customer360Error.value = "";
  try {
    const [profileResponse, historyResponse, duplicateResponse] = await Promise.all([
      apiFetch(`${API_BASE}/customers/${customerId}`),
      apiFetch(`${API_BASE}/customers/${customerId}/merge-history`),
      apiFetch(`${API_BASE}/customers/duplicates?customer_id=${customerId}`),
    ]);
    if (!profileResponse.ok || !historyResponse.ok || !duplicateResponse.ok) {
      throw new Error(
        `Customer 360 HTTP ${profileResponse.status}/${historyResponse.status}/${duplicateResponse.status}`
      );
    }
    const profile = await profileResponse.json();
    const history = await historyResponse.json();
    const duplicates = await duplicateResponse.json();
    if (!orderCustomers.value.length) {
      const customerResponse = await apiFetch(`${API_BASE}/customers?limit=200`);
      if (customerResponse.ok) orderCustomers.value = (await customerResponse.json()).items || [];
    }
    customer360.value = {
      ...profile,
      timeline: [],
      timelineSummary: null,
      timelineTotal: 0,
      timelineOffset: 0,
      timelineHasMore: false,
    };
    customerCustomFieldsDraft.value = { ...(profile.custom_fields || {}) };
    customerCustomFieldsError.value = "";
    customerCustomFieldsNotice.value = "";
    customer360OverflowOpen.value = false;
    customer360Error.value = "";
    customerTimelineError.value = "";
    customerMergeHistory.value = history.items || [];
    duplicateSuggestions.value = duplicates.items || [];
    void loadCustomerOrderHistory(customerId);
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

async function applyCustomerTimelineFilters() {
  const customerId = customer360.value?.id;
  const { start_date: startDate, end_date: endDate } = customerTimelineFilters.value;
  if (!customerId) return;
  if (!customerTimelineHasFilters.value) {
    customerTimelineError.value = "Chọn ít nhất một khoảng ngày hoặc một nhân viên để tra cứu lịch sử.";
    return;
  }
  if (startDate && endDate && startDate > endDate) {
    customerTimelineError.value = "Ngày bắt đầu không được sau ngày kết thúc.";
    return;
  }
  customerTimelineFilterLoading.value = true;
  customerTimelineError.value = "";
  try {
    const response = await apiFetch(customerTimelineRequestUrl(customerId, 0));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const page = await response.json();
    customer360.value = {
      ...customer360.value,
      timeline: page.items || [],
      timelineSummary: page.summary || null,
      timelineTotal: page.total ?? (page.items || []).length,
      timelineOffset: page.next_offset ?? (page.items || []).length,
      timelineHasMore: Boolean(page.has_more),
    };
    customerTimelineFilterApplied.value = true;
    customerTimelineDetailsOpen.value = false;
  } catch (err) {
    customerTimelineError.value = "Không thể lọc lịch sử tương tác. Vui lòng thử lại.";
  } finally {
    customerTimelineFilterLoading.value = false;
  }
}

function clearCustomerTimelineFilters() {
  customerTimelineFilters.value = { start_date: "", end_date: "", staff_id: "" };
  customerTimelineFilterApplied.value = false;
  customerTimelineDetailsOpen.value = false;
  customerTimelineError.value = "";
  if (customer360.value) {
    customer360.value = {
      ...customer360.value,
      timeline: [],
      timelineSummary: null,
      timelineTotal: 0,
      timelineOffset: 0,
      timelineHasMore: false,
    };
  }
}

async function loadMoreCustomerTimeline() {
  const customerId = customer360.value?.id;
  if (!customerId || !customer360.value?.timelineHasMore || customerTimelineLoading.value) return;
  customerTimelineLoading.value = true;
  customerTimelineError.value = "";
  try {
    const offset = Number(customer360.value.timelineOffset || customer360.value.timeline.length || 0);
    const response = await apiFetch(customerTimelineRequestUrl(customerId, offset));
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
      timelineSummary: page.summary || customer360.value.timelineSummary || null,
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
  if (docRetryingIds.value.has(doc.id)) return;
  docRetryingIds.value = new Set([...docRetryingIds.value, doc.id]);
  try {
    const response = await apiFetch(`${API_BASE}/documents/runs/${run.id}/retry`, { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${response.status}`);
    }
    await fetchDocuments();
  } catch (err) {
    docUploadError.value = friendlyErrorMessage(err, "Chưa thể xử lý lại tài liệu. Vui lòng thử lại sau.");
  } finally {
    const next = new Set(docRetryingIds.value);
    next.delete(doc.id);
    docRetryingIds.value = next;
  }
}


/* =========================================================
   CHAT ACTIONS
========================================================= */

function toggleConversationActions() {
  conversationActionsOpen.value = !conversationActionsOpen.value;
}

async function toggleLinkedCustomerInbox() {
  const customerId = Number(selected.value?.customer_id);
  if (!Number.isFinite(customerId) || customerId <= 0) return;

  linkedCustomerOnly.value = !linkedCustomerOnly.value;
  inboxCustomerFilterId.value = linkedCustomerOnly.value ? customerId : null;
  await loadConversations(false, { customerId: inboxCustomerFilterId.value });
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
  if (!canReplyToSelectedConversation.value) return;
  draft.value = `${draft.value}${draft.value ? " " : ""}🙂`;
  focusComposer();
}

function insertReplyTemplate() {
  if (!canReplyToSelectedConversation.value) return;
  if (!draft.value.trim()) {
    draft.value = "Xin chào, mình có thể hỗ trợ gì cho bạn?";
  } else {
    draft.value = `${draft.value.trim()} Xin chào, mình có thể hỗ trợ gì cho bạn?`;
  }
  focusComposer();
}

async function sendComposerContent() {
  if (composerMode.value !== "internal") {
    if (!canReplyToSelectedConversation.value) {
      error.value = "Hội thoại này đang có nhân viên phụ trách; bạn chỉ có thể xem nội dung.";
      return;
    }
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

function stopTenantWorkspace() {
  tenantWorkspaceActive.value = false;
  tenantWorkspaceInitialized.value = false;
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (socket) {
    const activeSocket = socket;
    socket = null;
    activeSocket.close();
  }
}

function shouldPollTenantProvisioning() {
  const state = tenantProvisioning.value?.state;
  return Boolean(
    authUser.value
    && !platformAdmin.value
    && !tenantReady.value
    && (state === "awaiting_approval" || state === "provisioning"),
  );
}

function stopTenantProvisioningPolling() {
  if (tenantProvisioningPollingTimer) {
    clearInterval(tenantProvisioningPollingTimer);
    tenantProvisioningPollingTimer = null;
  }
}

async function pollTenantProvisioning() {
  if (!shouldPollTenantProvisioning()) {
    stopTenantProvisioningPolling();
    return;
  }
  await fetchTenantProvisioning();
  if (!tenantReady.value) return;

  stopTenantProvisioningPolling();
  currentTab.value = "inbox";
  await initializeTenantWorkspace();
}

function startTenantProvisioningPolling() {
  if (!shouldPollTenantProvisioning() || tenantProvisioningPollingTimer) return;
  tenantProvisioningPollingTimer = window.setInterval(() => {
    if (!document.hidden) void pollTenantProvisioning();
  }, 5000);
}

function handleTenantProvisioningVisibilityChange() {
  if (!document.hidden) void pollTenantProvisioning();
}

async function fetchTenantProvisioning({ retry = false } = {}) {
  if (!authUser.value?.business_id) {
    tenantProvisioning.value = { state: "unknown", feature_enabled: false, subscription_active: false, subscription_status: null };
    return null;
  }
  if (tenantProvisioningLoading.value) return tenantProvisioning.value;
  tenantProvisioningLoading.value = true;
  tenantProvisioningError.value = "";
  try {
    const businessId = requireBusinessId(authUser.value);
    const response = await apiFetch(
      `${API_BASE}/onboarding/shops/${businessId}/provision${retry ? "/retry" : ""}`,
      retry ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idempotency_key: `ui-tenant-retry-${businessId}-${Date.now()}` }),
      } : undefined,
    );
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    tenantProvisioning.value = {
      state: detail.state || "provisioning",
      feature_enabled: Boolean(detail.feature_enabled),
      subscription_active: Boolean(detail.subscription_active),
      subscription_status: detail.subscription_status || null,
      tenant_revision: detail.tenant_revision || null,
    };
    if (tenantReady.value) {
      stopTenantProvisioningPolling();
    } else {
      stopTenantWorkspace();
      startTenantProvisioningPolling();
    }
    return tenantProvisioning.value;
  } catch (err) {
    tenantProvisioning.value = { state: "provision_failed", feature_enabled: false, subscription_active: false, subscription_status: null };
    tenantProvisioningError.value = friendlyErrorMessage(err, "Chưa thể chuẩn bị không gian dữ liệu của shop. Vui lòng thử lại.");
    stopTenantProvisioningPolling();
    stopTenantWorkspace();
    return null;
  } finally {
    tenantProvisioningLoading.value = false;
  }
}

async function refreshTenantProvisioning() {
  const shouldRetry = tenantProvisioning.value?.state === "provision_failed";
  await fetchTenantProvisioning({ retry: shouldRetry });
  if (tenantReady.value) {
    currentTab.value = "inbox";
    await initializeTenantWorkspace();
  }
}

async function initializeTenantWorkspace() {
  if (!authUser.value || !tenantReady.value || tenantWorkspaceInitialized.value) return;
  tenantWorkspaceInitialized.value = true;
  tenantWorkspaceActive.value = true;

  try {
    await fetchWorkspaceConfig();
    await fetchCrmConfig();
    void fetchQuotaUsage();
    await loadConversations(true);
    await fetchOrderCustomers();
    if (workspaceModuleEnabled("retail")) {
      await fetchProducts();
      resetOrderForm();
      resetPurchaseOrderForm();
    }
    fetchTagCatalog();
    fetchSavedSegments();

    connectRealtime();
    fetchDocuments();
    if (workspaceModuleEnabled("retail")) {
      fetchOrders();
      fetchSuppliers();
    }
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
    fetchLearningSummary();
    fetchMetaStatus();

    const metaResult = new URLSearchParams(window.location.search).get("meta");
    if (metaResult === "connected") {
      metaNotice.value = "Kết nối Facebook/Instagram thành công.";
      fetchMetaStatus();
    } else if (metaResult === "error") {
      metaNotice.value = "Kết nối Facebook/Instagram thất bại. Hãy kiểm tra cấu hình rồi thử lại.";
    }

    if (!pollingTimer) {
      pollingTimer = setInterval(async () => {
        await loadConversations(false);
        if (selectedId.value) await loadMessages(selectedId.value, false, true);
        void fetchOperationalNotifications();
      // WebSocket is the primary realtime path.  Keep a short fallback so a
      // reconnecting browser does not hide a bot reply for 25 seconds.
      }, 5000);
    }
  } catch (err) {
    tenantWorkspaceInitialized.value = false;
    tenantWorkspaceActive.value = false;
    tenantProvisioningError.value = friendlyErrorMessage(err, "Không thể tải dữ liệu shop ngay lúc này. Vui lòng thử lại.");
  }
}

onMounted(async () => {

  window.addEventListener("keydown", handleGlobalKeydown);
  window.addEventListener("visibilitychange", handleTenantProvisioningVisibilityChange);
  if (!platformRequestPollingTimer) {
    platformRequestPollingTimer = window.setInterval(() => {
      if (currentTab.value === "platform_admin" && !document.hidden) {
        void refreshPlatformSubscriptionRequests();
      }
    }, 10000);
  }

  void fetchPublicServicePlans();
  try {
    await loadAuthSession();
    await fetchPlatformAdmin();
    // Tenant data is only loaded after the platform session identifies an
    // active shop. Anonymous mode exposes the login gate only.
    if (!authUser.value) {
      currentTab.value = "settings";
      return;
    }

    loadBusinessProfile();
    loadThemePreference();
    if (platformAdmin.value) {
      // Keep a restored platform-admin session in the control plane as well;
      // it must not fall through to the tenant CRM workspace on refresh.
      currentTab.value = "platform_admin";
      return;
    }
    loadSavedInboxViews();
    await fetchTenantProvisioning();
    if (!tenantReady.value) {
      currentTab.value = "service";
      return;
    }
    await initializeTenantWorkspace();
  } finally {
    // Do not briefly render the tenant CRM before the platform role is known.
    sessionBootstrapLoading.value = false;
  }

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
      const configuredSpecialDates = configuredHours.special_dates || {};
      specialBusinessDates.value = Object.entries(configuredSpecialDates).map(([date, rule]) => ({
        date,
        closed: Boolean(rule?.closed),
        start: rule?.windows?.[0]?.[0] || "08:00",
        end: rule?.windows?.[0]?.[1] || "17:30",
      })).sort((left, right) => left.date.localeCompare(right.date));
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
      body: JSON.stringify({ reason: mode === "pause" ? "Nhân viên tiếp quản từ hệ thống" : "Nhân viên trả lại cho bot" }),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
    botModes.value = { ...botModes.value, [selected.value.conversation_id]: (await response.json()).bot_mode };
    await loadCustomer360(customerId);
  } catch (err) {
    error.value = friendlyErrorMessage(err, "Chưa thể đổi cách trả lời. Vui lòng thử lại sau.");
  }
}

async function saveSelectedConversationOutcome(value) {
  const conversation = selected.value;
  if (!conversation?.conversation_id || conversationOutcomeSaving.value) return;
  conversationOutcomeSaving.value = true;
  conversationOutcomeError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/conversations/${conversation.conversation_id}/outcome`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outcome: value || null }),
    });
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail?.message || detail.detail || `HTTP ${response.status}`);
    conversations.value = conversations.value.map((item) => Number(item.conversation_id) === Number(conversation.conversation_id)
      ? { ...item, resolution_outcome: detail.resolution_outcome }
      : item);
  } catch (err) {
    conversationOutcomeError.value = friendlyErrorMessage(err, "Chưa lưu được kết quả hội thoại. Vui lòng thử lại.");
  } finally {
    conversationOutcomeSaving.value = false;
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
  window.removeEventListener("visibilitychange", handleTenantProvisioningVisibilityChange);
  stopTenantProvisioningPolling();
  stopTenantWorkspace();

  if (platformRequestPollingTimer) {
    clearInterval(platformRequestPollingTimer);
    platformRequestPollingTimer = null;
  }

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

async function openPlatformAdmin() {
  currentTab.value = "platform_admin";
  await fetchPlatformAdmin();
  if (!platformAdmin.value) currentTab.value = tenantReady.value ? "settings" : "service";
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

  <div class="crm-app" :class="{ 'sidebar-collapsed': sidebarCollapsed, 'auth-locked': !authUser, 'crm-dark': darkMode, 'platform-admin-workspace': inPlatformAdminWorkspace, 'session-bootstrap-active': sessionBootstrapLoading }">


    <!-- =====================================================
         SIDEBAR
    ====================================================== -->

    <aside v-if="authUser && !inPlatformAdminWorkspace && !sessionBootstrapLoading" class="side" :class="{ 'tenant-pending': !tenantReady }">

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
          <small>{{ t("Không gian quản lý shop") }}</small>
        </div>
      </div>


      <nav class="menu">

        <div class="menu-group menu-group-customer">
          <button
            class="menu-item"
            :class="{ active: currentTab === 'inbox' }"
            :disabled="!tenantReady"
            :title="t('Hộp thư & Khách hàng 360')"
            @click="currentTab = 'inbox'"
          >
            <svg class="nav-icon nav-icon-inbox" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5a7.6 7.6 0 0 1-8 7.5 8.8 8.8 0 0 1-3.6-.8L4 20l1.4-3.5A7.1 7.1 0 0 1 4 12a7.6 7.6 0 0 1 8-7.5 7.6 7.6 0 0 1 8 7Z" /></svg>
            <b>{{ t("Hộp thư & Khách hàng 360") }}</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'leads' }" :disabled="!tenantReady" :title="t('Luồng bán hàng')" @click="currentTab = 'leads'; fetchOrderCustomers(); fetchLeads()">
            <svg class="nav-icon nav-icon-pipeline" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16l-6.2 7v5.5l-3.6 2V12Z" /></svg><b>{{ t("Luồng bán hàng") }}</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'tickets' }" :disabled="!tenantReady" :title="t('Phiếu hỗ trợ & thời hạn')" @click="currentTab = 'tickets'; fetchOrderCustomers(); fetchTickets()">
            <svg class="nav-icon nav-icon-tickets" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="m8.3 12.3 2.3 2.3 5-5" /></svg><b>{{ t("Phiếu hỗ trợ & thời hạn") }}</b>
          </button>
        </div>

        <div class="menu-group menu-group-operations">
          <span class="menu-group-label">{{ t("Vận hành") }}</span>
          <button v-if="workspaceModuleEnabled('retail')" class="menu-item" :class="{ active: currentTab === 'products' }" :disabled="!tenantReady" :title="t('Sản phẩm')" @click="currentTab = 'products'; fetchProducts()">
            <svg class="nav-icon nav-icon-products" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></svg><b>{{ t('Sản phẩm') }}</b>
          </button>
          <button v-if="workspaceModuleEnabled('retail')" class="menu-item" :class="{ active: currentTab === 'orders' }" :disabled="!tenantReady" :title="t('Đơn bán')" @click="currentTab = 'orders'; loadConversations(false); fetchOrderCustomers(); fetchProducts(); fetchOrders()">
            <svg class="nav-icon nav-icon-orders" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l3 3v15H6Z" /><path d="M15 3v4h4M9 11h6M9 15h6M9 19h4" /></svg><b>{{ t('Đơn bán') }}</b>
          </button>
          <button v-if="workspaceModuleEnabled('appointments')" class="menu-item" :class="{ active: currentTab === 'appointments' }" :disabled="!tenantReady" title="Lịch hẹn" @click="currentTab = 'appointments'">
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="16" rx="2" /><path d="M8 3v4m8-4v4M4 10h16M8 14h3m-3 3h6" /></svg><b>Lịch hẹn</b>
          </button>
          <button v-if="workspaceModuleEnabled('projects')" class="menu-item" :class="{ active: currentTab === 'commercial' }" :disabled="!tenantReady" title="Báo giá, dự án & hóa đơn" @click="currentTab = 'commercial'">
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h10l4 4V21H5Z" /><path d="M15 3.5V8h4M8 12h8m-8 4h8m-8 3h5" /></svg><b>Báo giá &amp; dự án</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'business_hours' }" :disabled="!tenantReady" :title="t('Giờ làm việc')" @click="currentTab = 'business_hours'; fetchChatbotRuntime()">
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3.5 2" /></svg><b>{{ t('Giờ làm việc') }}</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'sla_rules' }" :disabled="!tenantReady" :title="t('Quy tắc thời hạn')" @click="currentTab = 'sla_rules'">
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14M5 12h9M5 18h14" /><circle cx="17" cy="12" r="2" /></svg><b>{{ t('Quy tắc thời hạn') }}</b>
          </button>
          <!-- Nhập hàng được xử lý nội bộ, không hiển thị trong workspace CSKH. -->
        </div>

        <div class="menu-group menu-group-ai">
          <span class="menu-group-label">{{ t("Kiến thức & tự động hóa") }}</span>
          <div class="ai-submenu">
            <button class="menu-item" :class="{ active: currentTab === 'documents' }" :disabled="!tenantReady" :title="t('Kho kiến thức')" @click="currentTab = 'documents'; fetchDocuments()">
              <svg class="nav-icon nav-icon-knowledge" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5c2.8-1 5.4-.6 8 1v12c-2.6-1.6-5.2-2-8-1Zm16 0c-2.8-1-5.4-.6-8 1v12c2.6-1.6 5.2-2-8-1Z" /><path d="M12 6.5v12" /></svg><b>{{ t('Kho kiến thức') }}</b>
            </button>
            <!-- Trợ lý chat được dùng trong Inbox, không cần shortcut riêng. -->
            <button class="menu-item" :class="{ active: currentTab === 'workflows' }" :disabled="!tenantReady" :title="t('Quy trình')" @click="currentTab = 'workflows'; fetchWorkflows(); fetchTeam()">
              <svg class="nav-icon nav-icon-workflow" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4" width="5" height="5" rx="1" /><rect x="15.5" y="4" width="5" height="5" rx="1" /><rect x="9.5" y="15" width="5" height="5" rx="1" /><path d="M8.5 6.5h7M12 9v6" /></svg><b>{{ t('Quy trình') }}</b>
            </button>
            <!-- Rule Lab giữ ở tầng quản trị, không hiển thị cho nhân viên vận hành. -->
          </div>
        </div>

        <div class="menu-group menu-group-insights">
          <span class="menu-group-label">{{ t("Phân tích") }}</span>
          <button class="menu-item" :class="{ active: currentTab === 'reports' }" :disabled="!tenantReady" :title="t('Báo cáo')" @click="currentTab = 'reports'; fetchReports()">
            <svg class="nav-icon nav-icon-reports" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V10m5 10V4m5 16v-7m5 7V7" /></svg><b>{{ t('Báo cáo') }}</b>
          </button>
        </div>

        <div class="menu-group menu-group-channels">
          <span class="menu-group-label">{{ t("Kênh liên kết") }}</span>
          <button class="menu-item" :class="{ active: currentTab === 'channels' }" :disabled="!tenantReady" :title="t('Kết nối mạng xã hội')" @click="openChannels">
            <svg class="nav-icon nav-icon-channels" viewBox="0 0 24 24" aria-hidden="true"><circle cx="7" cy="12" r="3" /><circle cx="17" cy="7" r="3" /><circle cx="17" cy="17" r="3" /><path d="m9.5 10.8 4.8-2.6M9.5 13.2l4.8 2.6" /></svg><b>{{ t('Kết nối mạng xã hội') }}</b>
          </button>
          <button class="menu-item" :class="{ active: currentTab === 'webhooks' }" :disabled="!tenantReady" :title="t('Nhận sự kiện')" @click="openWebhooks">
            <svg class="nav-icon nav-icon-webhooks" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4v5m10-5v5M4 9h16M6 14h5m2 0h5M6 18h5m2 0h5" /><rect x="4" y="3" width="16" height="18" rx="2" /></svg><b>{{ t('Nhận sự kiện') }}</b>
          </button>
        </div>

        <div class="menu-group menu-group-system">
          <span class="menu-group-label">{{ t("Hệ thống") }}</span>
          <button class="menu-item menu-item-service" :class="{ active: currentTab === 'service' }" :title="t('Chọn gói dịch vụ')" @click="openServicePage">
            <svg class="nav-icon nav-icon-service" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 14.1 9l5.9.4-4.5 3.8 1.5 5.7-5-3.1-5 3.1 1.5-5.7L4 9.4l5.9-.4Z" /><path d="M12 14v6.5M8.5 20.5h7" /></svg><b>{{ t('Chọn gói dịch vụ') }}</b>
          </button>
          <button class="menu-item menu-item-settings" :class="{ active: currentTab === 'settings' }" :disabled="!tenantReady && !mfaVerifyPending" :title="t('Cài đặt')" @click="openSettings">
            <svg class="nav-icon nav-icon-settings" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M19 13.5v-3l-2.1-.7a5.3 5.3 0 0 0-.5-1.1l1-2-2.1-2.1-2 1a5.3 5.3 0 0 0-1.1-.5L11.5 3h-3l-.7 2.1a5.3 5.3 0 0 0-1.1.5l-2-1L2.6 6.7l1 2a5.3 5.3 0 0 0-.5 1.1l-2.1.7v3l2.1.7a5.3 5.3 0 0 0 .5 1.1l-1 2 2.1 2.1 2-1a5.3 5.3 0 0 0 1.1.5l.7 2.1h3l.7-2.1a5.3 5.3 0 0 0 1.1-.5l2 1 2.1-2.1-1-2a5.3 5.3 0 0 0 .5-1.1Z" /></svg><b>{{ t('Cài đặt') }}</b>
          </button>
        </div>

        <div v-if="platformAdmin" class="menu-group menu-group-platform-admin">
          <span class="menu-group-label">{{ t("Quản trị nền tảng") }}</span>
          <button class="menu-item" :class="{ active: currentTab === 'platform_admin' }" title="Quản trị nền tảng" @click="openPlatformAdmin">
            <svg class="nav-icon nav-icon-platform-admin" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6.5h16v13H4z" /><path d="M8 6.5V4h8v2.5M8 11h8M8 15h5" /><circle cx="17" cy="16" r="2.5" /></svg><b>{{ t("Quản trị nền tảng") }}</b>
          </button>
        </div>

      </nav>



      <div class="side-card">
          <span class="side-card-kicker">{{ t('TRẠNG THÁI HỆ THỐNG') }}</span>
        <strong>{{ t(tenantReady ? 'CRM đang hoạt động' : 'Đang chuẩn bị CRM') }}</strong>
        <small>{{ t(tenantReady ? 'Dữ liệu hội thoại và vận hành được đồng bộ theo business.' : 'Dữ liệu riêng của shop sẽ sẵn sàng sau khi chuẩn bị xong.') }}</small>
        <span class="status-dot"><i></i> {{ t(tenantReady ? 'Đang hoạt động' : 'Đang chờ') }}</span>
      </div>


      <button
        type="button"
        class="collapse"
        :aria-expanded="String(!sidebarCollapsed)"
        :aria-label="t(sidebarCollapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng')"
        :title="t(sidebarCollapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng')"
        @click="toggleSidebar"
      >
        <span class="collapse-icon" aria-hidden="true">‹</span>
        <span>{{ t(sidebarCollapsed ? 'Mở rộng' : 'Thu gọn') }}</span>
      </button>

    </aside>


    <!-- =====================================================
         MAIN
    ====================================================== -->

    <!-- Authenticated CRM shell uses <main v-if="authUser" class="main">; the public service request keeps the same frame. -->
    <main v-if="(authUser && !sessionBootstrapLoading) || serviceLandingOpen" class="main" :class="{ 'public-service-main': serviceLandingOpen, 'platform-admin-main': inPlatformAdminWorkspace }">

      <section v-if="authUser && !tenantReady && !inPlatformAdminWorkspace" class="tenant-provisioning-banner" role="status" aria-live="polite">
        <div>
          <strong>{{ tenantProvisioning.state === 'awaiting_approval' ? 'Yêu cầu gói đang chờ quản trị viên duyệt' : tenantProvisioning.state === 'subscription_inactive' ? 'Gói dịch vụ chưa được kích hoạt' : 'Không gian dữ liệu của shop đang được chuẩn bị' }}</strong>
          <span v-if="tenantProvisioning.state === 'awaiting_approval'">Yêu cầu đã được ghi nhận. CRM sẽ mở sau khi quản trị viên nền tảng duyệt gói và hệ thống chuẩn bị xong không gian dữ liệu riêng.</span>
          <span v-else-if="tenantProvisioning.state === 'subscription_inactive'">Yêu cầu trước đó chưa được chấp thuận hoặc gói đã hết hiệu lực. Hãy chọn lại gói dịch vụ nếu cần.</span>
          <span v-else>{{ tenantProvisioning.state === 'provision_failed' ? 'Việc tạo database riêng chưa hoàn tất. Dữ liệu CRM tạm dừng để tránh cảnh báo sai.' : 'Khi database riêng sẵn sàng, CRM sẽ tự mở. Bạn cũng có thể kiểm tra lại ngay.' }}</span>
          <small v-if="tenantProvisioningError">{{ tenantProvisioningError }}</small>
        </div>
        <button type="button" class="settings-refresh" :disabled="tenantProvisioningLoading" @click="refreshTenantProvisioning">{{ tenantProvisioningLoading ? 'Đang kiểm tra...' : tenantProvisioning.state === 'provision_failed' ? 'Thử chuẩn bị lại' : tenantProvisioning.state === 'awaiting_approval' ? 'Làm mới trạng thái' : 'Kiểm tra lại' }}</button>
      </section>

      <!-- TOP -->

      <header v-if="authUser && !inPlatformAdminWorkspace" class="top">

        <div class="welcome">

          <strong>
            {{ t(workspaceGreeting) }} <span aria-hidden="true">👋</span>
          </strong>

          <span>
            {{ t('Theo dõi khách hàng, hội thoại và vận hành trong một không gian.') }}
          </span>

        </div>


        <div class="top-actions">

          <label class="top-search" role="search">
            <input
              class="top-search-input"
              v-model="search"
              type="search"
              :placeholder="t('Tìm kiếm khách hàng, tin nhắn, đơn hàng...')"
              :aria-label="t('Tìm kiếm khách hàng, tin nhắn, đơn hàng')"
              :disabled="!tenantReady"
              @keydown.enter="runGlobalSearch"
            />
            <svg class="top-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="5.8" /><path d="m15.2 15.2 4 4" /></svg>
          </label>

          <button
            type="button"
            class="quick-action-trigger"
            :aria-label="t('Mở thao tác nhanh')"
            :title="`${t('Thao tác nhanh')} (Ctrl+K)`"
            :disabled="!tenantReady"
            @click="openQuickActions"
          >
            <span>{{ t('Thao tác nhanh') }}</span><kbd>Ctrl K</kbd>
          </button>


          <div class="notification-menu">
            <button
              type="button"
              class="bell"
              :aria-label="t('Mở thông báo')"
            :title="t('Mở thông báo')"
            :aria-expanded="String(notificationsOpen)"
            :disabled="!tenantReady"
            @click="openNotifications"
            >
              <svg class="top-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M18 10a6 6 0 0 0-12 0c0 6-2.5 6.5-2.5 8h17C20.5 16.5 18 16 18 10Z" /><path d="M10 21h4" /></svg>
              <i v-if="unreadOperationalNotificationCount">{{ unreadOperationalNotificationCount }}</i>
            </button>
              <div v-if="notificationsOpen" class="notification-popover" role="dialog" :aria-label="t('Thông báo hệ thống')">
              <div class="notification-popover-head">
                <strong>{{ t('Thông báo') }}</strong>
                <span>{{ unreadOperationalNotificationCount }} {{ t('chưa đọc') }}</span>
              </div>
              <p v-if="notificationError" class="notification-empty notification-error" role="alert">{{ notificationError }}</p>
              <p v-else-if="!operationalNotifications.length" class="notification-empty">{{ t('Chưa có thông báo mới.') }}</p>
              <button
                v-for="notification in operationalNotifications"
                :key="notification.id"
                type="button"
                class="notification-item"
                :class="{ unread: !notification.is_read }"
                @click="activateNotification(notification)"
              >
                <strong>{{ notification.title }}</strong>
              </button>
            </div>
          </div>

          <button
            type="button"
            class="dark-mode-toggle"
            :aria-pressed="darkMode"
            :aria-label="t(darkMode ? 'Tắt chế độ tối' : 'Bật chế độ tối')"
            :title="t(darkMode ? 'Tắt chế độ tối' : 'Bật chế độ tối')"
            @click="toggleDarkMode"
          >
            <span class="help" aria-hidden="true"></span>
            <span aria-hidden="true">{{ darkMode ? '☀' : '☾' }}</span>
          </button>

          <label class="ui-language-control">
            <span class="visually-hidden">{{ t('Ngôn ngữ giao diện') }}</span>
            <select :value="uiLocale" :aria-label="t('Ngôn ngữ giao diện')" @change="setUiLocale($event.target.value)">
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
            </select>
          </label>


          <button
            type="button"
            class="team"
            :aria-label="t('Mở Cài đặt')"
            :title="t('Mở Cài đặt')"
            :disabled="!tenantReady && !mfaVerifyPending"
            @click="openSettings"
          >

            <div class="team-avatar">
              SM
            </div>

            <div>

              <b>
                {{ t('Không gian quản lý shop') }}
              </b>

              <small>
                {{ t('Quản trị viên') }}
              </small>

            </div>

          </button>

          <button
            type="button"
            class="top-logout"
            :aria-label="t('Đăng xuất')"
            :title="t('Đăng xuất')"
            @click="logout"
          >
            <svg class="top-logout-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 17l5-5-5-5M15 12H3" /><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6" /></svg>
            <span>{{ t('Đăng xuất') }}</span>
          </button>

        </div>

      </header>


      <!-- ERROR -->

      <div
        v-if="error && !inPlatformAdminWorkspace"
        class="error"
      >
        <span>{{ error }}</span>
        <button type="button" class="error-retry-btn" :disabled="loading || !tenantReady" @click="loadConversations()">{{ loading ? 'Đang tải...' : 'Thử lại' }}</button>
      </div>

      <div v-if="quickActionOpen && !inPlatformAdminWorkspace" class="quick-action-backdrop" @click.self="closeQuickActions">
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

      <IndustryModules v-if="currentTab === 'appointments'" module="appointments" :api-base="API_BASE" />
      <IndustryModules v-else-if="currentTab === 'commercial'" module="projects" :api-base="API_BASE" />

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
              <div class="filter-panel-heading">
                <span>Thông tin cá nhân</span>
                <button
                  v-if="inboxPersonalFilters.phone || inboxPersonalFilters.email"
                  type="button"
                  @click="clearInboxPersonalFilters"
                >Xóa lọc</button>
              </div>
              <div class="personal-filter-grid">
                <label>
                  <span>Số điện thoại</span>
                  <input
                    v-model="inboxPersonalFilters.phone"
                    inputmode="tel"
                    autocomplete="off"
                    aria-label="Lọc khách hàng theo số điện thoại"
                    placeholder="Nhập số điện thoại"
                  />
                </label>
                <label>
                  <span>Gmail / email</span>
                  <input
                    v-model="inboxPersonalFilters.email"
                    type="search"
                    autocomplete="off"
                    aria-label="Lọc khách hàng theo Gmail hoặc email"
                    placeholder="Nhập Gmail hoặc email"
                    @keydown.escape="clearInboxPersonalFilters"
                  />
                </label>
              </div>
              <p class="personal-filter-note">Lọc theo thông tin đã được khách hàng cung cấp.</p>

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
            <div class="segment-control inbox-saved-views">
              <div class="filter-panel-heading"><span>{{ $t('Chế độ xem đã lưu') }}</span><small>{{ savedInboxViews.length }}/{{ MAX_SAVED_INBOX_VIEWS }}</small></div>
              <select v-model="selectedSavedInboxViewId" :aria-label="$t('Chọn chế độ xem')" @change="applySavedInboxView">
                <option value="">{{ $t('Chọn chế độ xem') }}</option>
                <option v-for="view in savedInboxViews" :key="view.id" :value="view.id">{{ view.name }}</option>
              </select>
              <div class="inbox-saved-view-actions">
                <input v-model="savedInboxViewName" maxlength="48" :placeholder="$t('Tên chế độ xem')" :aria-label="$t('Tên chế độ xem')" @keydown.enter.prevent="saveCurrentInboxView" />
                <button type="button" @click="saveCurrentInboxView">{{ $t('Lưu bộ lọc') }}</button>
                <button v-if="selectedSavedInboxViewId" type="button" class="inbox-saved-view-delete" @click="deleteSelectedInboxView">{{ $t('Xóa') }}</button>
              </div>
              <small class="inbox-saved-view-scope">{{ $t('Chỉ lưu trên trình duyệt này.') }}</small>
              <p v-if="savedInboxViewError" class="inbox-saved-view-error" role="alert">{{ $t(savedInboxViewError) }}</p>
              <p v-else-if="savedInboxViewNotice" class="inbox-saved-view-notice" role="status">{{ $t(savedInboxViewNotice) }}</p>
            </div>
          </details>
          </div>

          <div class="inbox-bulk-toolbar">
            <button v-if="!bulkSelectionMode" type="button" class="inbox-bulk-toggle" :disabled="!filtered.length" @click="bulkSelectionMode = true; bulkAssignmentNotice = ''">Chọn nhiều</button>
            <template v-else>
              <label class="inbox-select-visible"><input type="checkbox" :checked="allVisibleConversationsSelected" :disabled="!filtered.length" @change="toggleVisibleConversationSelection($event.target.checked)" /> {{ t('Chọn') }} {{ filtered.length }} {{ t('đang hiển thị') }}</label>
              <span class="inbox-bulk-count">{{ t('Đã chọn') }} {{ bulkSelectedConversationIds.size }}</span>
              <label class="visually-hidden" for="inbox-bulk-assignee">Giao hội thoại đã chọn</label>
              <select id="inbox-bulk-assignee" v-model="bulkAssignmentTarget" :disabled="bulkAssignmentSaving">
                <option value="">Chọn nhân viên...</option>
                <option value="unassigned">Bỏ phân công</option>
                <option v-for="member in activeTeamUsers" :key="member.id" :value="String(member.id)">{{ member.full_name }}</option>
              </select>
              <button type="button" class="inbox-bulk-submit" :disabled="!bulkSelectedConversationIds.size || !bulkAssignmentTarget || bulkAssignmentSaving" @click="bulkReassignConversations">{{ bulkAssignmentSaving ? 'Đang phân công...' : 'Phân công' }}</button>
              <button type="button" class="inbox-bulk-cancel" :disabled="bulkAssignmentSaving" @click="closeBulkSelectionMode">Hủy</button>
            </template>
            <p v-if="bulkAssignmentError" class="inbox-bulk-error" role="alert">{{ $t(bulkAssignmentError) }}</p>
            <p v-else-if="bulkAssignmentNotice" class="inbox-bulk-notice" role="status">{{ $t(bulkAssignmentNotice) }}</p>
          </div>


          <div
            ref="inboxConversationScroll"
            class="conversation-scroll"
            aria-label="Danh sách hội thoại, cuộn để tải thêm"
            @scroll.passive="handleInboxConversationScroll"
          >

            <div v-if="!filtered.length" class="inbox-empty-state">
              <span class="inbox-empty-state-icon" aria-hidden="true">✦</span>
              <strong>{{ conversations.length ? "Không có hội thoại phù hợp" : "Hộp thư đang chờ tin nhắn đầu tiên" }}</strong>
              <p>{{ conversations.length ? "Thử thay đổi từ khóa hoặc bộ lọc để xem lại." : "Hội thoại từ Facebook, Instagram, Telegram, Zalo và TikTok sẽ xuất hiện tại đây." }}</p>
            </div>

            <div v-for="item in filtered" :key="item.conversation_id" class="conversation-row">
              <label v-if="bulkSelectionMode" class="conversation-select-checkbox">
                <input
                  type="checkbox"
                  :checked="bulkSelectedConversationIds.has(Number(item.conversation_id))"
                  :aria-label="`Chọn hội thoại ${nameOf(item)}`"
                  @change="toggleBulkConversationSelection(item.conversation_id, $event.target.checked)"
                />
              </label>
              <button
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
                    <span
                      v-if="conversationUrgentCount(item)"
                      class="conversation-unread urgent"
                      title="Cần xử lý: khách xác nhận đơn hoặc AI cần nhân viên hỗ trợ"
                    >{{ conversationUrgentCount(item) }}</span>
                    <span v-else-if="item.unread_count" class="conversation-unread">{{ item.unread_count }}</span>
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
                      v-else-if="item.channel === 'tiktok'"
                      class="tiktok-mini-logo"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <path class="tiktok-logo-cyan" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
                      <path class="tiktok-logo-red" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
                      <path class="tiktok-logo-main" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
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

            <div v-if="inboxLoadingMore" class="conversation-load-state" role="status">
              Đang tải thêm hội thoại...
            </div>
            <div v-else-if="inboxHasMore" class="conversation-load-state conversation-load-hint">
              Cuộn xuống để tải thêm
            </div>
            <div v-else-if="conversations.length" class="conversation-load-state conversation-load-end">
              Đã tải hết hội thoại
            </div>

          </div>


          <div class="conversation-footer">

            Đã tải {{ conversations.length }}/{{ inboxConversationTotal || conversations.length }} hội thoại
            <span v-if="inboxHasMore"> · cuộn để xem thêm</span>

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
                        v-else-if="selected.channel === 'tiktok'"
                        class="tiktok-mini-logo"
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <path class="tiktok-logo-cyan" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
                        <path class="tiktok-logo-red" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
                        <path class="tiktok-logo-main" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
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
                  type="button"
                  class="linked-customer-toggle"
                  :class="{ active: linkedCustomerOnly }"
                  :aria-pressed="linkedCustomerOnly"
                  :title="linkedCustomerOnly ? 'Hiện toàn bộ hộp thư' : 'Chỉ hiện các tài khoản liên kết của khách hàng này'"
                  :aria-label="linkedCustomerOnly ? 'Hiện toàn bộ hộp thư' : 'Chỉ hiện các tài khoản liên kết của khách hàng này'"
                  @click="toggleLinkedCustomerInbox"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M10.6 13.4a4.2 4.2 0 0 0 5.9.1l2-2a4.2 4.2 0 0 0-5.9-5.9l-1.1 1.1" />
                    <path d="M13.4 10.6a4.2 4.2 0 0 0-5.9-.1l-2 2a4.2 4.2 0 1 0 5.9 5.9l1.1-1.1" />
                    <path d="m9 15 6-6" />
                  </svg>
                </button>

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

                <label v-if="selectedHasAiActivity" class="conversation-assignment conversation-outcome-control" title="Xác nhận kết quả chatbot">
                  <span>Kết quả chatbot</span>
                  <select
                    :value="selected.resolution_outcome || ''"
                    :disabled="conversationOutcomeSaving"
                    @change="saveSelectedConversationOutcome($event.target.value)"
                  >
                    <option value="">Chưa xác nhận</option>
                    <option value="resolved">Đã giải quyết</option>
                    <option value="needs_human">Cần nhân viên hỗ trợ</option>
                    <option value="customer_unanswered">Khách chưa phản hồi</option>
                  </select>
                  <small v-if="conversationOutcomeError" class="conversation-outcome-error" role="alert">{{ $t(conversationOutcomeError) }}</small>
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

                :data-message-id="message.message_id"

                class="msg-line"

                :class="
                  [message.direction, { 'search-jump-highlight': Number(message.message_id) === Number(customerMessageSearchJumpingId) }]
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
                          @error="handleAttachmentError"
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

                  <span
                    v-if="message.direction === 'outbound' && message.sender_type === 'bot' && message.status !== 'sending' && message.status !== 'failed'"
                    class="bot-response-feedback"
                    aria-label="Đánh giá câu trả lời của trợ lý"
                  >
                    <span v-if="messageFeedback[message.message_id]" class="bot-response-feedback-done">{{ messageFeedback[message.message_id].rating > 0 ? 'Đã ghi nhận hữu ích' : 'Đã ghi nhận cần cải thiện' }}</span>
                    <template v-else>
                      <span>Trợ lý trả lời ổn?</span>
                      <button type="button" title="Câu trả lời hữu ích" @click="rateBotMessage(message, 1)">Hữu ích</button>
                      <button type="button" title="Cần cải thiện" @click="rateBotMessage(message, -1)">Cần cải thiện</button>
                    </template>
                  </span>

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
                  :disabled="!canReplyToSelectedConversation"
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

              <p
                v-if="composerMode === 'reply'"
                class="composer-access-notice"
                :class="{ 'is-read-only': !canReplyToSelectedConversation }"
                role="status"
              >
                {{ replyAccessNotice }}
              </p>

              <textarea
                v-model="draft"

                :disabled="composerMode === 'reply' && !canReplyToSelectedConversation"
                :placeholder="composerMode === 'internal' ? 'Ghi chú nội bộ...' : (canReplyToSelectedConversation ? 'Nhập tin nhắn...' : 'Chỉ xem hội thoại do nhân viên khác phụ trách')"

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
                    :disabled="composerMode === 'reply' && !canReplyToSelectedConversation"
                    @click="insertComposerEmoji"
                  >
                    ☺
                  </button>


                  <!-- IMAGE BUTTON -->

                  <button
                    type="button"

                    title="Chọn ảnh, audio, video hoặc file"
                    :disabled="composerMode === 'reply' && !canReplyToSelectedConversation"

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
                    :disabled="composerMode === 'internal' || sending || !canReplyToSelectedConversation"
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
                    :disabled="composerMode === 'reply' && !canReplyToSelectedConversation"
                    @click="insertReplyTemplate"
                  >
                    Mẫu trả lời
                  </button>

                  <select
                    v-if="cannedResponses.length"
                    v-model="selectedCannedId"
                    class="canned-response-select"
                    :disabled="composerMode === 'reply' && !canReplyToSelectedConversation"
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
                      ||
                      (composerMode === 'reply' && !canReplyToSelectedConversation)
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

            <div class="customer-title-actions">
              <button
                ref="mobileCustomerClose"
                type="button"
                class="mobile-panel-close"
                aria-label="Đóng hồ sơ khách hàng 360"
                @click="closeMobileCustomer"
              >×</button>

              <button
                v-if="selected"
                type="button"
                class="customer-message-search-trigger"
                :aria-expanded="customerMessageSearchOpen"
                aria-label="Tìm trong hội thoại của khách hàng"
                title="Tìm trong hội thoại"
                @click="customerMessageSearchOpen ? closeCustomerMessageSearch() : openCustomerMessageSearch()"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="5.7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m15.2 15.2 4 4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2"/></svg>
              </button>

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

          </div>

          <section v-if="customerMessageSearchOpen" class="customer-message-search" role="dialog" aria-label="Tìm kiếm hội thoại khách hàng">
            <div class="customer-message-search-head">
              <div class="customer-message-search-input-wrap">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="5.7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m15.2 15.2 4 4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2"/></svg>
                <input
                  data-customer-message-search-input
                  v-model="customerMessageSearchQuery"
                  type="search"
                  autocomplete="off"
                  placeholder="Tìm trong hội thoại..."
                  aria-label="Nhập nội dung cần tìm trong hội thoại"
                  @input="queueCustomerMessageSearch"
                  @keydown.esc="closeCustomerMessageSearch"
                />
                <button v-if="customerMessageSearchQuery" type="button" aria-label="Xóa từ khóa tìm kiếm" @click="customerMessageSearchQuery = ''; queueCustomerMessageSearch()">×</button>
              </div>
              <button type="button" class="customer-message-search-close" aria-label="Đóng tìm kiếm hội thoại" @click="closeCustomerMessageSearch">×</button>
            </div>
            <p class="customer-message-search-note">
              <template v-if="customerMessageSearchQuery.trim().length < 2">Nhập ít nhất 2 ký tự để tìm tin nhắn của khách hàng này.</template>
              <template v-else-if="customerMessageSearchLoading && !customerMessageSearchItems.length">Đang tìm tin nhắn liên quan...</template>
              <template v-else>{{ customerMessageSearchTotal }} kết quả · bấm một kết quả để mở đúng tin nhắn.</template>
            </p>
            <div class="customer-message-search-results" @scroll.passive="handleCustomerMessageSearchScroll">
              <button
                v-for="item in customerMessageSearchItems"
                :key="`customer-message-search-${item.message_id}`"
                type="button"
                class="customer-message-search-result"
                :disabled="customerMessageSearchJumpingId === item.message_id"
                @click="jumpToCustomerSearchMessage(item)"
              >
                <span class="customer-message-search-result-head">
                  <strong>{{ customerMessageSearchActor(item) }}</strong>
                  <time>{{ item.occurred_at ? new Date(item.occurred_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : 'Không rõ thời gian' }}</time>
                </span>
                <span>{{ customerMessageSearchPreview(item) }}</span>
              </button>
              <p v-if="customerMessageSearchQuery.trim().length >= 2 && !customerMessageSearchLoading && !customerMessageSearchItems.length && !customerMessageSearchError" class="customer-message-search-empty">Không tìm thấy tin nhắn phù hợp.</p>
              <p v-if="customerMessageSearchLoading && customerMessageSearchItems.length" class="customer-message-search-loading">Đang tải thêm kết quả...</p>
              <p v-if="customerMessageSearchError" class="customer-message-search-error">{{ customerMessageSearchError }}</p>
            </div>
            <div v-if="customerMessageSearchHasMore" class="customer-message-search-footer">Cuộn xuống để tải thêm kết quả</div>
          </section>

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
                      v-else-if="selected.channel === 'tiktok'"
                      class="tiktok-mini-logo"

                      viewBox="
                        0 0 24 24
                      "
                    >

                      <path class="tiktok-logo-cyan" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
                      <path class="tiktok-logo-red" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>
                      <path class="tiktok-logo-main" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/>

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

              <div v-if="crmConfig.customer_fields.length" class="section customer-custom-fields-section">
                <div class="section-head"><h4>Thông tin riêng của shop</h4><span>{{ crmConfig.customer_fields.length }}</span></div>
                <div class="customer-profile-fields customer-custom-fields-grid">
                  <label v-for="field in crmConfig.customer_fields" :key="field.key" class="customer-custom-field">
                    <span>{{ field.label }}</span>
                    <select v-if="field.type === 'select'" v-model="customerCustomFieldsDraft[field.key]">
                      <option value="">Chưa chọn</option><option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
                    </select>
                    <input v-else-if="field.type === 'number'" v-model.number="customerCustomFieldsDraft[field.key]" type="number" />
                    <input v-else-if="field.type === 'date'" v-model="customerCustomFieldsDraft[field.key]" type="date" />
                    <input v-else-if="field.type === 'boolean'" v-model="customerCustomFieldsDraft[field.key]" type="checkbox" />
                    <textarea v-else v-model="customerCustomFieldsDraft[field.key]" maxlength="2000" rows="2" />
                  </label>
                </div>
                <div v-if="customerCustomFieldsError" class="facts-error" role="alert">{{ customerCustomFieldsError }}</div>
                <div v-if="customerCustomFieldsNotice" class="settings-notice" role="status">{{ customerCustomFieldsNotice }}</div>
                <button type="button" class="table-action-btn" :disabled="customerCustomFieldsSaving" @click="saveCustomerCustomFields">{{ customerCustomFieldsSaving ? 'Đang lưu...' : 'Lưu thông tin' }}</button>
              </div>

              <div class="section customer-timeline-section">
                <div class="section-head">
                  <h4>Lịch sử tương tác</h4>
                  <span v-if="customerTimelineFilterApplied">{{ customer360.timeline.length }} / {{ customer360.timelineTotal }}</span>
                </div>
                <p class="customer-section-hint">
                  Chỉ tra cứu hoạt động khi cần; toàn bộ nội dung tin nhắn vẫn được xem trong khung hội thoại chính.
                </p>
                <div class="customer-timeline-filters" role="group" aria-label="Bộ lọc lịch sử tương tác">
                  <label>
                    Từ ngày
                    <input v-model="customerTimelineFilters.start_date" type="date" aria-label="Lịch sử từ ngày" />
                  </label>
                  <label>
                    Đến ngày
                    <input v-model="customerTimelineFilters.end_date" type="date" aria-label="Lịch sử đến ngày" />
                  </label>
                  <label>
                    Nhân viên
                    <select v-model="customerTimelineFilters.staff_id" aria-label="Lọc lịch sử theo nhân viên">
                      <option value="">Tất cả nhân viên</option>
                      <option v-for="member in teamUsers" :key="`timeline-staff-${member.id}`" :value="String(member.id)">
                        {{ member.full_name || member.email }}
                      </option>
                    </select>
                  </label>
                  <div class="customer-timeline-filter-actions">
                    <button
                      type="button"
                      class="table-action-btn"
                      :disabled="customerTimelineFilterLoading || !customerTimelineHasFilters"
                      @click="applyCustomerTimelineFilters"
                    >
                      {{ customerTimelineFilterLoading ? 'Đang lọc...' : 'Áp dụng bộ lọc' }}
                    </button>
                    <button
                      v-if="customerTimelineHasFilters || customerTimelineFilterApplied"
                      type="button"
                      class="table-action-btn secondary"
                      @click="clearCustomerTimelineFilters"
                    >Xóa lọc</button>
                  </div>
                </div>
                <p class="customer-filter-note">
                  {{ customerTimelineFilters.staff_id && (customerTimelineFilters.start_date || customerTimelineFilters.end_date)
                    ? 'Chỉ giữ hoạt động do nhân viên đã chọn thực hiện trong khoảng ngày đã chọn.'
                    : (customerTimelineFilters.staff_id
                      ? 'Chỉ hiển thị hoạt động do nhân viên đã chọn thực hiện.'
                      : 'Ngày được tính theo giờ Việt Nam. Để xem toàn bộ hoạt động trong ngày, giữ “Tất cả nhân viên”.') }}
                </p>
                <div v-if="!customerTimelineFilterApplied" class="customer-timeline-placeholder">
                  Chọn ngày hoặc nhân viên rồi bấm “Áp dụng bộ lọc”. Hồ sơ chỉ hiển thị phần tổng hợp để không lặp lại đoạn chat dài.
                </div>
                <div v-else-if="!customer360.timeline.length" class="customer-timeline-placeholder">
                  Không có hoạt động nào khớp với bộ lọc hiện tại.
                </div>
                <template v-else>
                  <div class="customer-timeline-summary" aria-label="Tổng hợp lịch sử đã lọc">
                    <article v-for="card in customerTimelineSummaryCards" :key="card.key" class="customer-timeline-summary-card">
                      <strong>{{ card.value }}</strong>
                      <span>{{ card.label }}</span>
                      <small>{{ card.note }}</small>
                    </article>
                  </div>
                  <div class="customer-timeline-detail-toggle">
                    <button type="button" class="table-action-btn secondary" @click="customerTimelineDetailsOpen = !customerTimelineDetailsOpen">
                      {{ customerTimelineDetailsOpen ? 'Ẩn chi tiết' : `Xem chi tiết (${customer360.timeline.length} hoạt động gần nhất)` }}
                    </button>
                    <span>Chi tiết chỉ là bản xem trước; nội dung chat đầy đủ ở giữa màn hình.</span>
                  </div>
                  <div v-if="customerTimelineDetailsOpen" class="customer-timeline">
                    <div
                      v-for="event in customer360.timeline"
                      :key="`${event.event_type}-${event.event_id}`"
                      class="customer-timeline-row"
                    >
                      <span class="timeline-dot" :class="event.event_type"></span>
                      <div>
                        <small>{{ timelineLabel(event) }}<span v-if="event.channel"> · {{ channelLabel(event.channel) }}</span></small>
                        <p>{{ customerTimelineContent(event) }}</p>
                        <small v-if="timelineExplainability(event)" class="timeline-explainability">{{ timelineExplainability(event) }}</small>
                        <small class="customer-timeline-meta">
                          {{ event.occurred_at ? new Date(event.occurred_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : 'Không rõ thời gian' }}
                          <span
                            class="timeline-actor"
                            :class="`timeline-actor-${timelineActor(event).kind}`"
                            :title="event.created_by ? `ID nhân viên: ${event.created_by}` : timelineActor(event).label"
                          >{{ timelineActor(event).label }}</span>
                        </small>
                      </div>
                    </div>
                  </div>
                </template>
                <div v-if="customerTimelineError" class="facts-error">{{ customerTimelineError }}</div>
                <button
                  v-if="customerTimelineFilterApplied && customerTimelineDetailsOpen && customer360.timelineHasMore"
                  type="button"
                  class="timeline-load-more"
                  :disabled="customerTimelineLoading"
                  @click="loadMoreCustomerTimeline"
                >
                  {{ customerTimelineLoading ? 'Đang tải...' : 'Tải thêm lịch sử' }}
                </button>
              </div>

              <div class="section customer-orders-section">
                <div class="section-head">
                  <h4>Đơn hàng &amp; sản phẩm đã mua</h4>
                  <span>{{ customerOrderHistory.length }}</span>
                </div>
                <p class="customer-section-hint">Hóa đơn trước đây và các sản phẩm khách đã mua.</p>
                <div v-if="customerPendingApprovalOrders.length" class="customer-order-approval" role="status">
                  <div class="customer-order-approval-head"><strong>{{ customerPendingApprovalOrders.length }} đơn chờ xác nhận</strong><span>Khách đã duyệt hóa đơn</span></div>
                  <article v-for="order in customerPendingApprovalOrders" :key="`customer-order-approval-${order.id}`" class="customer-order-approval-card">
                    <div><strong>{{ order.order_number || `Đơn #${order.id}` }}</strong><small>{{ order.items?.map((item) => `${item.product_name || item.name || 'Sản phẩm'} ×${item.quantity || 1}`).join(', ') || 'Chưa có sản phẩm' }}</small><small>{{ Number(order.total_amount || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ · {{ order.shipping_phone || 'Chưa có SĐT giao hàng' }}</small></div>
                    <button type="button" class="table-action-btn customer-order-approve-btn" :disabled="orderTransitionSaving[order.id]" @click="confirmCustomerOrder(order)">{{ orderTransitionSaving[order.id] ? 'Đang xác nhận...' : 'Đồng ý đơn' }}</button>
                  </article>
                </div>
                <p v-if="customerOrderApprovalNotice" class="customer-order-approval-notice" role="status">{{ customerOrderApprovalNotice }}</p>
                <div v-if="customerOrderHistoryLoading" class="customer-timeline-placeholder">Đang tải lịch sử đơn hàng...</div>
                <div v-else-if="!customerOrderHistory.length" class="customer-timeline-placeholder">Khách hàng chưa có đơn hàng.</div>
                <div v-else class="customer-order-history">
                  <article v-for="order in customerVisibleOrderHistory" :key="`customer-order-${order.id}`" class="customer-order-card">
                    <div>
                      <strong>{{ order.order_number || `Đơn #${order.id}` }}</strong>
                      <small>{{ order.created_at ? formatDate(order.created_at) : t('Chưa rõ ngày đặt') }}</small>
                      <small v-if="order.items?.length" class="customer-order-items">
                        {{ order.items.map((item) => `${item.name || item.sku || 'Sản phẩm'} ×${item.quantity || 1}`).join(', ') }}
                      </small>
                    </div>
                    <div class="customer-order-card-meta">
                      <span>{{ salesOrderStatusLabel(order.status) }}</span>
                      <strong>{{ Number(order.total_amount || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong>
                    </div>
                  </article>
                </div>
                <div v-if="customerOrderHistory.length > 5" class="customer-timeline-detail-toggle">
                  <button type="button" class="table-action-btn secondary" @click="customerOrderHistoryExpanded = !customerOrderHistoryExpanded">
                    {{ customerOrderHistoryExpanded ? 'Thu gọn đơn hàng' : `Xem thêm ${customerOrderHistory.length - 5} đơn hàng` }}
                  </button>
                </div>
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


                <div>

                  <span>
                    Đơn đã chốt
                  </span>

                  <b>
                    {{ customerConfirmedOrderCount }}
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
           PLATFORM ADMINISTRATION (CONTROL PLANE)
      ==================================================== -->
      <section v-if="currentTab === 'platform_admin' && platformAdmin" class="platform-admin-layout">
        <header class="platform-workspace-header">
          <div class="platform-workspace-identity">
            <div class="platform-workspace-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M4 6.5h16v13H4z" /><path d="M8 6.5V4h8v2.5M8 11h8M8 15h5" /><circle cx="17" cy="16" r="2.5" /></svg>
            </div>
            <div><strong>Smart Merchant Hub</strong><span>{{ t('Quản trị hệ thống') }}</span></div>
          </div>
          <div class="platform-workspace-actions">
            <span class="platform-workspace-role">{{ t('Admin nền tảng') }}</span>
            <label class="ui-language-control">
              <span class="visually-hidden">{{ t('Ngôn ngữ giao diện') }}</span>
              <select :value="uiLocale" :aria-label="t('Ngôn ngữ giao diện')" @change="setUiLocale($event.target.value)">
                <option value="vi">Tiếng Việt</option><option value="en">English</option>
              </select>
            </label>
            <button type="button" class="dark-mode-toggle" :aria-pressed="darkMode" :aria-label="t(darkMode ? 'Tắt chế độ tối' : 'Bật chế độ tối')" :title="t(darkMode ? 'Tắt chế độ tối' : 'Bật chế độ tối')" @click="toggleDarkMode"><span class="help" aria-hidden="true"></span><span aria-hidden="true">{{ darkMode ? '☀' : '☾' }}</span></button>
            <button type="button" class="platform-logout" @click="logout">{{ t('Đăng xuất') }}</button>
          </div>
        </header>
        <div class="products-header platform-admin-hero">
          <div>
            <span class="card-eyebrow">CONTROL PLANE</span>
            <h2>Quản trị nền tảng</h2>
            <p>Quản lý tenant, gói dịch vụ, module, kết nối và sức khỏe toàn bộ hệ thống.</p>
          </div>
          <button type="button" class="settings-refresh" :disabled="platformLoading" @click="fetchPlatformAdmin">{{ platformLoading ? 'Đang tải...' : 'Làm mới dữ liệu' }}</button>
        </div>

        <div v-if="platformError" class="settings-notice team-error" role="alert">{{ platformError }}</div>
        <div v-if="platformApprovalNotice" class="settings-notice platform-approval-notice" role="status">{{ platformApprovalNotice }}</div>

        <div class="platform-admin-metrics">
          <article class="platform-admin-metric"><span>Tenant</span><strong>{{ platformShops.length }}</strong><small>Đang được quản lý</small></article>
          <article class="platform-admin-metric"><span>Đang hoạt động</span><strong>{{ platformShops.filter((shop) => shop.status !== 'suspended').length }}</strong><small>Tenant có thể truy cập</small></article>
          <article class="platform-admin-metric platform-admin-metric-alert"><span>Yêu cầu chờ duyệt</span><strong>{{ platformPendingRequests.length }}</strong><small>Chưa mở quyền CRM</small></article>
          <article class="platform-admin-metric platform-admin-metric-alert"><span>Cảnh báo kênh</span><strong>{{ platformProviderErrors.length }}</strong><small>Lỗi đã được ẩn thông tin nhạy cảm</small></article>
        </div>

        <section class="platform-admin-panel platform-approval-panel">
          <div class="platform-admin-panel-heading">
            <div><span class="card-eyebrow">SERVICE APPROVALS</span><h3>Yêu cầu chờ duyệt</h3><p>Duyệt gói để kích hoạt quyền sử dụng và bắt đầu chuẩn bị không gian dữ liệu riêng của shop.</p><small class="platform-admin-refresh-hint">Danh sách tự cập nhật mỗi 10 giây khi trang này đang mở.</small></div>
            <span class="platform-admin-count">{{ platformPendingRequests.length }} yêu cầu</span>
          </div>
          <p v-if="!platformPendingRequests.length" class="settings-empty">Không có yêu cầu gói nào đang chờ duyệt.</p>
          <div v-else class="platform-approval-list">
            <article v-for="request in platformPendingRequests" :key="request.subscription_id" class="platform-approval-item">
              <div class="platform-approval-shop"><strong>{{ request.shop_name }}</strong><small>{{ request.shop_slug }} · #{{ request.business_id }}</small></div>
              <div class="platform-approval-detail"><span>Liên hệ đăng ký</span><strong>{{ request.contact_name || request.requester_name || request.owner_name || 'Chưa cập nhật' }}</strong><small>{{ request.contact_email || request.requester_email || request.owner_email || 'Chưa có email' }}</small><small v-if="request.contact_phone">{{ request.contact_phone }}</small><small v-if="request.contact_name && request.requester_name && request.contact_name !== request.requester_name">Tài khoản gửi: {{ request.requester_name }}</small></div>
              <div class="platform-approval-detail"><span>Dịch vụ yêu cầu</span><strong>{{ request.plan_name }}</strong><small>{{ platformServiceLabel(request.service_type) }}</small></div>
              <div class="platform-approval-detail"><span>Thời điểm gửi</span><strong>{{ formatPlatformRequestDate(request.requested_at || request.created_at) }}</strong><small>Chờ xác nhận của quản trị viên</small></div>
              <div class="platform-approval-actions">
                <button type="button" class="primary-btn" :disabled="Boolean(platformApprovalLoadingId)" @click="approvePlatformSubscriptionRequest(request)">{{ platformApprovalLoadingId === request.subscription_id ? 'Đang duyệt...' : 'Duyệt & mở CRM' }}</button>
                <button type="button" class="history-btn platform-approval-reject" :disabled="Boolean(platformApprovalLoadingId)" @click="rejectPlatformSubscriptionRequest(request)">Từ chối</button>
              </div>
              <div v-if="request.requested_shop_name || request.requested_channels.length || request.request_notes" class="platform-approval-request-details">
                <div v-if="request.requested_shop_name"><span>Tên shop liên hệ</span><strong>{{ request.requested_shop_name }}</strong></div>
                <div v-if="request.requested_channels.length"><span>Kênh mong muốn</span><strong>{{ request.requested_channels.join(' · ') }}</strong></div>
                <p v-if="request.request_notes"><strong>Ghi chú:</strong> {{ request.request_notes }}</p>
              </div>
            </article>
          </div>
        </section>

        <div class="platform-admin-grid">
          <section class="platform-admin-panel platform-admin-tenant-panel">
            <div class="platform-admin-panel-heading"><div><span class="card-eyebrow">TENANTS</span><h3>Danh sách tenant</h3><p>Quản lý trạng thái và hạn mức; dữ liệu vận hành vẫn nằm trong workspace riêng.</p></div><span class="platform-admin-count">{{ platformShops.length }} tenant</span></div>
            <p v-if="platformShopNotice" class="settings-notice platform-shop-notice" role="status">{{ platformShopNotice }}</p>
            <div v-if="!platformShops.length" class="settings-empty">Chưa có tenant trên nền tảng.</div>
            <div v-else class="platform-admin-tenant-list">
              <article v-for="shop in platformShops" :key="shop.id" class="platform-admin-tenant-card" :class="{ suspended: shop.status === 'suspended' }">
                <div class="platform-tenant-card-header">
                  <div><strong>{{ shop.name }}</strong><small>{{ shop.slug }} · #{{ shop.id }}</small></div>
                  <span class="team-status" :class="{ inactive: shop.status === 'suspended' }">{{ shop.status === 'suspended' ? 'Đã khóa' : 'Đang hoạt động' }}</span>
                </div>
                <dl class="platform-tenant-summary">
                  <div><dt>Gói đang dùng</dt><dd><span class="platform-plan-chip">{{ platformShopDetail(shop.id).subscription?.plan_name || shop.plan_name || 'Chưa cấp gói' }}</span></dd></div>
                  <div><dt>Trạng thái thanh toán</dt><dd><span class="platform-status-chip" :class="paymentStatusMeta(platformShopLatestPayment(shop)?.status).tone">{{ paymentStatusMeta(platformShopLatestPayment(shop)?.status).label }}</span></dd></div>
                  <div><dt>Nhân viên</dt><dd>{{ platformQuotaCards(platformShopQuota(shop)).find((item) => item.key === 'staff_users')?.used ?? 0 }}{{ platformQuotaCards(platformShopQuota(shop)).find((item) => item.key === 'staff_users')?.limit === null ? '' : ` / ${platformQuotaCards(platformShopQuota(shop)).find((item) => item.key === 'staff_users')?.limit ?? 0}` }}</dd></div>
                  <div><dt>Kênh kết nối</dt><dd>{{ platformQuotaCards(platformShopQuota(shop)).find((item) => item.key === 'connected_channels')?.used ?? 0 }}{{ platformQuotaCards(platformShopQuota(shop)).find((item) => item.key === 'connected_channels')?.limit === null ? '' : ` / ${platformQuotaCards(platformShopQuota(shop)).find((item) => item.key === 'connected_channels')?.limit ?? 0}` }}</dd></div>
                </dl>
                <div class="platform-tenant-actions">
                  <button type="button" class="settings-refresh" :aria-expanded="platformShopDetail(shop.id).open" :aria-controls="`platform-shop-detail-${shop.id}`" @click="togglePlatformShopDetails(shop)">{{ platformShopDetail(shop.id).open ? 'Ẩn chi tiết' : 'Xem chi tiết' }}</button>
                  <button type="button" class="team-toggle" :class="{ danger: shop.status !== 'suspended' }" :disabled="platformShopMutatingIds.has(String(shop.id))" @click="togglePlatformShop(shop)">{{ platformShopMutatingIds.has(String(shop.id)) ? 'Đang cập nhật...' : shop.status === 'suspended' ? 'Mở shop' : 'Khóa shop' }}</button>
                </div>
                <section v-if="platformShopDetail(shop.id).open" :id="`platform-shop-detail-${shop.id}`" class="platform-tenant-detail">
                  <p v-if="platformShopDetail(shop.id).loading" class="settings-empty" role="status">Đang tải gói, thanh toán và hạn mức của shop...</p>
                  <template v-else>
                    <p v-if="platformShopDetail(shop.id).error" class="settings-notice team-error" role="alert">{{ platformShopDetail(shop.id).error }}</p>
                    <div class="platform-tenant-detail-grid">
                      <div><span>Gói đang dùng</span><strong>{{ platformShopDetail(shop.id).subscription?.plan_name || shop.plan_name || 'Chưa cấp gói' }}</strong><small>{{ subscriptionStatusMeta(platformShopDetail(shop.id).subscription?.status).label }}</small></div>
                      <div><span>Trạng thái thanh toán</span><strong>{{ paymentStatusMeta(platformShopLatestPayment(shop)?.status).label }}</strong><small v-if="platformShopLatestPayment(shop)?.paid_at">{{ new Date(platformShopLatestPayment(shop).paid_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}</small><small v-else>Chưa có giao dịch gần đây</small></div>
                    </div>
                    <div class="platform-quota-card-grid" aria-label="Hạn mức tenant: Kênh kết nối, Nhân viên, Tài liệu và Dung lượng tra cứu">
                      <div v-for="item in platformQuotaCards(platformShopQuota(shop))" :key="item.key" class="platform-quota-card" :class="{ warning: item.nearLimit, exceeded: item.exceeded }">
                        <span>{{ item.label }}</span><strong>{{ item.limit === null ? `${item.used} đã dùng` : `${item.used} / ${item.limit}` }}</strong>
                        <div class="quota-track" aria-hidden="true"><span :style="{ width: `${Math.min(100, item.percent)}%` }"></span></div>
                        <small v-if="item.exceeded">Đã vượt hạn mức</small><small v-else-if="item.nearLimit">Sắp chạm hạn mức</small><small v-else>Trong giới hạn</small>
                      </div>
                    </div>
                  </template>
                </section>
              </article>
            </div>
          </section>

          <section class="platform-admin-panel">
            <div class="platform-admin-panel-heading"><div><span class="card-eyebrow">SERVICE PLANS</span><h3>Gói dịch vụ</h3><p>Gói quyết định hạn mức và các module được cấp cho từng tenant.</p></div><div class="platform-plan-heading-actions"><span class="platform-admin-count">{{ platformPlans.length }} gói</span><button type="button" class="settings-refresh" @click="resetPlatformPlanForm">Thêm gói</button></div></div>
            <p v-if="platformPlanNotice" class="settings-notice platform-plan-notice" role="status">{{ platformPlanNotice }}</p>
            <form class="platform-plan-form" @submit.prevent="savePlatformPlan">
              <label>Mã gói<input v-model.trim="platformPlanForm.code" required maxlength="50" :disabled="Boolean(platformPlanEditingId)" placeholder="chatbot-pro" /></label>
              <label>Tên gói<input v-model.trim="platformPlanForm.name" required maxlength="120" placeholder="Gói Trợ lý Pro" /></label>
              <label>Giá gói CRM<input v-model.number="platformPlanForm.price" required min="0" step="1000" type="number" /></label>
              <label>Giá thuê trợ lý chatbot<input v-model.number="platformPlanForm.chatbot_rental_price" required min="0" step="1000" type="number" /></label>
              <label>Chu kỳ<select v-model="platformPlanForm.billing_cycle"><option value="monthly">Theo tháng</option><option value="yearly">Theo năm</option><option value="one_time">Một lần</option></select></label>
              <label>Trạng thái<select v-model="platformPlanForm.status"><option value="active">Đang bán</option><option value="archived">Lưu trữ</option></select></label>
              <label class="platform-plan-description">Mô tả<textarea v-model.trim="platformPlanForm.description" rows="2" maxlength="2000" placeholder="Mô tả ngắn cho gói dịch vụ"></textarea></label>
              <div class="platform-plan-form-actions"><button type="submit" class="primary-btn" :disabled="platformPlanSaving">{{ platformPlanSaving ? 'Đang lưu...' : platformPlanEditingId ? 'Lưu thay đổi' : 'Tạo gói' }}</button><button v-if="platformPlanEditingId" type="button" class="settings-refresh" :disabled="platformPlanSaving" @click="resetPlatformPlanForm">Hủy</button></div>
            </form>
            <div v-if="!platformPlans.length" class="settings-empty">Chưa có gói dịch vụ.</div>
            <div v-else class="platform-plan-list">
              <article v-for="plan in platformPlans" :key="plan.id" class="platform-plan-item">
                <div><strong>{{ plan.name }}</strong><span>Gói CRM: {{ formatPlanPrice(plan.price, plan.billing_cycle) }}</span><small>Trợ lý chatbot: {{ formatPlanPrice(chatbotRentalPrice(plan), plan.billing_cycle) }}</small></div>
                <span class="team-status" :class="{ inactive: plan.status !== 'active' }">{{ plan.status === 'active' ? 'Đang bán' : 'Lưu trữ' }}</span>
                <div class="platform-plan-actions"><button type="button" class="settings-refresh platform-plan-edit" :disabled="Boolean(platformPlanDeletingId)" @click="editPlatformPlan(plan)">Sửa giá</button><button type="button" class="platform-plan-delete" :disabled="Boolean(platformPlanDeletingId)" @click="deletePlatformPlan(plan)">{{ platformPlanDeletingId === plan.id ? 'Đang xóa...' : 'Xóa' }}</button></div>
                <small v-if="plan.features && Object.keys(plan.features).length">{{ Object.keys(plan.features).slice(0, 3).join(' · ') }}</small>
              </article>
            </div>
          </section>
        </div>

        <div class="platform-admin-grid">
          <section class="platform-admin-panel">
            <div class="platform-admin-panel-heading"><div><span class="card-eyebrow">TENANT ISOLATION</span><h3>Tách kho dữ liệu theo shop</h3><p>Quản lý tách kho dữ liệu theo shop, điều khiển trạng thái thử nghiệm mà không mở dữ liệu CRM sang tenant khác.</p></div></div>
            <div v-if="!platformSchemas.length" class="settings-empty">Chưa đăng ký tenant thử nghiệm.</div>
            <ul v-else class="permission-list platform-schema-list">
              <li v-for="schema in platformSchemas" :key="schema.id">
                <div><strong>Tenant #{{ schema.business_id }} · {{ schema.schema_name }}</strong><span>{{ schema.feature_enabled ? 'Đang bật thử nghiệm' : `Trạng thái: ${schemaStateLabel(schema.state)}` }}</span></div>
                <button type="button" class="history-btn" @click="stagePlatformSchema(schema)">{{ schema.state === 'ready' ? 'Tắt thử nghiệm' : 'Bật thử nghiệm' }}</button>
              </li>
            </ul>
            <div v-if="platformShops.some((shop) => !platformSchemas.some((schema) => schema.business_id === shop.id))" class="platform-schema-actions">
              <button v-for="shop in platformShops.filter((item) => !platformSchemas.some((schema) => schema.business_id === item.id))" :key="shop.id" type="button" class="settings-refresh" @click="registerPlatformSchema(shop.id)">Đăng ký tách dữ liệu cho {{ shop.name }}</button>
            </div>
          </section>

          <section class="platform-admin-panel">
            <div class="platform-admin-panel-heading"><div><span class="card-eyebrow">CHANNEL HEALTH</span><h3>Kết nối &amp; cảnh báo</h3><p>Theo dõi lỗi Facebook, Instagram, Telegram, Zalo và các kênh sẽ bổ sung như TikTok, Shopee.</p></div></div>
            <p v-if="!platformProviderErrors.length" class="settings-empty">Chưa có cảnh báo kết nối.</p>
            <ul v-else class="audit-list platform-alert-list">
              <li v-for="errorItem in platformProviderErrors.slice(0, 10)" :key="errorItem.id"><strong>{{ channelLabel(errorItem.channel_type) }}</strong><span> · {{ workflowEventLabel(errorItem.event_type) }} · {{ errorItem.error_type || 'Lỗi kết nối' }}</span><small>{{ errorItem.received_at ? new Date(errorItem.received_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '' }}</small></li>
            </ul>
          </section>
        </div>

        <section class="platform-admin-panel platform-admin-audit-panel">
          <div class="platform-admin-panel-heading"><div><span class="card-eyebrow">AUDIT</span><h3>Nhật ký nền tảng</h3><p>Ghi lại thao tác quản trị tenant, gói dịch vụ, thanh toán và tách dữ liệu.</p></div><span class="platform-admin-count">{{ platformAuditLogs.length }} sự kiện</span></div>
          <p v-if="!platformAuditLogs.length" class="settings-empty">Chưa có nhật ký nền tảng.</p>
          <ul v-else class="audit-list platform-alert-list">
            <li v-for="log in platformAuditLogs.slice(0, 12)" :key="log.id"><strong>{{ log.action }}</strong><span> · {{ resourceLabel(log.resource_type) }}{{ log.resource_id ? ` #${log.resource_id}` : '' }}</span><small>{{ log.created_at ? new Date(log.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '' }}</small></li>
          </ul>
        </section>
      </section>

      <!-- ===================================================
           SẢN PHẨM (PRODUCT CATALOG)
      ==================================================== -->
      <section v-if="currentTab === 'products' && workspaceModuleEnabled('retail')" class="products-layout">
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
            <small>CSV hoặc TXT · Tối đa 20MB · Cột cần có: Mã sản phẩm, Tên sản phẩm, Giá, Tồn kho · SKU trùng sẽ cộng thêm tồn</small>
            <button type="button" class="secondary-btn import-choice" @click.stop="openProductFilePicker">Nhập tệp</button>
          </div>
          <div v-else class="dropzone-content" role="status" aria-live="polite">
            <span class="spinner-icon" aria-hidden="true">...</span>
            <strong>Đang nhập danh mục sản phẩm...</strong>
          </div>
        </div>

        <div v-if="productUploadNotice" class="product-import-notice" role="status">{{ productUploadNotice }}</div>
        <div v-if="productError" class="product-error">{{ productError }}</div>
        <div v-if="productStatusNotice" class="product-import-notice product-status-notice" role="status">{{ productStatusNotice }}</div>

        <div class="operation-mode-banner" data-testid="products-processing-only">
          <strong>Chế độ xử lý sản phẩm</strong>
          <span>Danh mục sản phẩm được đồng bộ từ nguồn dữ liệu shop. Tại đây chỉ xử lý tồn kho, trạng thái và lưu trữ.</span>
        </div>

        <div v-if="productsLoading" class="products-empty">Đang tải sản phẩm...</div>
        <div v-else-if="!products.length" class="products-empty">Chưa có sản phẩm nào.</div>
        <div v-else class="products-table-wrap">
          <table class="products-table">
            <thead><tr><th>Mã sản phẩm</th><th>Sản phẩm</th><th>Giá</th><th>Tồn kho</th><th>Điều chỉnh tồn</th><th>Trạng thái</th></tr></thead>
            <tbody>
              <template v-for="product in products" :key="product.id">
                <tr>
                  <td><strong>{{ product.sku }}</strong></td>
                  <td><div>{{ product.name }}</div><small>{{ product.description || 'Không có mô tả' }}</small></td>
                  <td>{{ Number(product.price).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</td>
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
                  <td class="product-status-cell">
                    <select
                      class="product-status-select"
                      :class="product.status"
                      :value="product.status"
                      :disabled="productStatusSaving[product.id]"
                      :aria-label="`Trạng thái ${product.name}`"
                      title="Chọn để đổi trạng thái sản phẩm"
                      @change="changeProductStatus(product, $event.target.value)"
                    >
                      <option value="active">Đang bán</option>
                      <option value="archived">Lưu trữ</option>
                    </select>
                    <small v-if="productStatusSaving[product.id]" class="product-status-saving">Đang lưu...</small>
                  </td>
                </tr>
                <tr v-if="inventoryAdjustmentOpen === product.id" class="inventory-adjustment-row">
                  <td colspan="6">
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
          <div v-for="stage in crmConfig.pipeline_stages" :key="stage.key" class="pipeline-card">
            <span>{{ stage.label }}</span>
            <strong>{{ (pipelineSummary.find(item => item.stage === stage.key) || {}).lead_count || 0 }}</strong>
            <small>{{ Number((pipelineSummary.find(item => item.stage === stage.key) || {}).value || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</small>
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
            <label>Giai đoạn<select v-model="leadForm.stage"><option v-for="stage in crmConfig.pipeline_stages" :key="stage.key" :value="stage.key">{{ stage.label }}</option></select></label>
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
                <td><select class="inline-stage" :value="lead.stage" @change="changeLeadStage(lead, $event.target.value)"><option v-for="stage in crmConfig.pipeline_stages" :key="stage.key" :value="stage.key">{{ stage.label }}</option></select></td>
                <td>{{ Number(lead.value || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</td>
                <td>{{ lead.probability }}%</td>
                <td>{{ formatDate(lead.updated_at) }}</td>
                <td class="lead-actions"><button type="button" class="table-link" @click="toggleLeadActivities(lead)">{{ leadActivityVisible[lead.id] ? 'Ẩn hoạt động' : 'Hoạt động' }}</button></td>
              </tr>
              <tr v-if="leadActivityVisible[lead.id]" class="lead-detail-row">
                <td colspan="8">
                  <div class="lead-detail">
                    <div class="lead-detail-header"><strong>Hoạt động & chuyển đổi</strong><span v-if="leadActivityLoading[lead.id]">Đang tải...</span></div>
                    <div class="lead-activity-list" v-if="(leadActivities[lead.id] || []).length">
                      <div v-for="activity in leadActivities[lead.id]" :key="activity.id" class="lead-activity"><b>{{ activity.subject }}</b><small>{{ leadActivityTypeLabel(activity.activity_type) }} · {{ activity.occurred_at ? new Date(activity.occurred_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}</small></div>
                    </div>
                    <div v-else class="settings-empty">Chưa có hoạt động.</div>
                    <form class="lead-activity-form" @submit.prevent="addLeadActivity(lead)">
                      <input :value="leadActivityDrafts[lead.id] || ''" @input="setLeadActivityDraft(lead.id, $event.target.value)" placeholder="Ghi chú cuộc gọi, email, hẹn gặp..." maxlength="255" />
                      <button class="table-link" type="submit">Ghi hoạt động</button>
                    </form>
                    <div v-if="lead.stage !== 'won'" class="lead-conversion-form">
                      <select v-model="leadConversionOrders[lead.id]">
                        <option value="">Chọn đơn để chuyển đổi</option>
                        <option v-for="order in orders.filter(item => item.customer_id === lead.customer_id)" :key="order.id" :value="order.id">{{ order.order_number || `Đơn #${order.id}` }} · {{ Number(order.total_amount || order.total || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</option>
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
                <td>{{ ticket.sla_due_at ? new Date(ticket.sla_due_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}</td>
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
                      {{ ticketHistoryEventLabel(event.event_type) }} · {{ event.created_at ? new Date(event.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}
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
      <section v-if="currentTab === 'orders'" v-show="workspaceModuleEnabled('retail')" class="products-layout orders-layout">
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
            <strong>{{ Number(revenueByChannel.reduce((sum, item) => sum + Number(item.revenue || 0), 0)).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong>
          </div>
          <div v-for="item in revenueByChannel" :key="item.channel" class="revenue-card">
            <span>{{ item.channel === 'unknown' ? 'Không gắn kênh' : item.channel }}</span>
            <strong>{{ Number(item.revenue || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong>
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
                  <small>{{ Number(order.paid_amount || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ / {{ Number(order.total_amount || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</small>
                  <div class="order-payment-actions">
                    <input v-model.number="orderPaymentDrafts[order.id]" type="number" min="0.01" step="0.01" placeholder="Số tiền" />
                    <button type="button" :disabled="orderPaymentSaving[order.id]" aria-label="Ghi nhận thanh toán" title="Ghi nhận thanh toán" @click="recordSalesPayment(order)">Thu</button>
                    <button type="button" :disabled="orderPaymentSaving[order.id]" aria-label="Ghi nhận hoàn tiền" title="Ghi nhận hoàn tiền" @click="recordSalesPayment(order, 'refund')">Hoàn</button>
                  </div>
                </td>
                <td><strong>{{ Number(order.total_amount || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></td>
                <td>{{ order.created_at ? new Date(order.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}</td>
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
            <div class="order-logistics-actions"><span v-if="selectedOrderEvents.order.shipping_updated_at" class="field-hint">Cập nhật: {{ new Date(selectedOrderEvents.order.shipping_updated_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}</span><button class="table-action-btn" type="submit" :disabled="orderLogisticsSaving">{{ orderLogisticsSaving ? 'Đang lưu...' : 'Lưu vận chuyển' }}</button></div>
          </form>
          <div v-if="orderEventsLoading" class="products-empty">Đang tải lịch sử...</div>
              <div v-else-if="!selectedOrderEvents.items?.length" class="products-empty">Chưa có sự kiện nào.</div>
          <ol v-else class="order-events-list"><li v-for="event in chronologicalOrderEvents(selectedOrderEvents.items)" :key="event.id"><strong>{{ orderEventLabel(event) }}</strong><span>{{ orderEventSummary(event) }}</span><small>{{ event.created_at ? new Date(event.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}</small></li></ol>
        </div>
      </section>

      <!-- ===================================================
           PURCHASE ORDERS (SUPPLIER / SHOP PROCUREMENT)
      ==================================================== -->
      <section v-if="currentTab === 'purchase-orders'" v-show="workspaceModuleEnabled('retail')" class="products-layout orders-layout purchase-orders-layout">
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
                <td class="order-payment-cell"><span class="product-status" :class="purchase.payment_status">{{ paymentStatusLabel(purchase.payment_status || 'unpaid') }}</span><small>{{ Number(purchase.paid_amount || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ / {{ Number(purchase.total_spend || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</small><div class="order-payment-actions"><input v-model.number="purchasePaymentDrafts[purchase.id]" type="number" min="0.01" step="0.01" placeholder="Số tiền" /><button type="button" :disabled="purchasePaymentSaving[purchase.id]" @click="recordPurchasePayment(purchase)">Thanh toán công nợ</button></div></td>
                <td><strong>{{ Number(purchase.total_spend || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></td>
                <td>{{ purchase.updated_at ? new Date(purchase.updated_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}</td>
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
              <small>{{ event.created_at ? new Date(event.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }}</small>
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
            <label>Sự kiện<select v-model="workflowForm.event_type"><option value="message.created">Tin nhắn mới</option><option value="ticket.created">Phiếu hỗ trợ được tạo</option><option value="ticket.status_changed">Phiếu hỗ trợ đổi trạng thái</option><option value="lead.stage_changed">Cơ hội đổi giai đoạn</option><option value="order.created">Đơn hàng được tạo</option><option value="appointment.created">Tạo lịch hẹn</option><option value="appointment.status_changed">Lịch hẹn đổi trạng thái</option><option value="quote.created">Tạo báo giá</option><option value="quote.status_changed">Báo giá đổi trạng thái</option><option value="project.created">Tạo dự án</option><option value="project.status_changed">Dự án đổi trạng thái</option><option value="invoice.created">Tạo hóa đơn</option><option value="invoice.status_changed">Hóa đơn đổi trạng thái</option><option value="invoice.payment_recorded">Ghi nhận thanh toán hóa đơn</option></select></label>
          <label>Điều kiện kênh<select v-model="workflowForm.condition_channel"><option value="">Mọi kênh</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="telegram">Telegram</option><option value="zalo">Zalo</option><option value="tiktok">TikTok</option></select></label>
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
          <div class="ai-readiness-notice" role="note">
            <strong>Khu vực thử nghiệm nội bộ</strong>
            <span>Đề xuất, phiên bản dự đoán và A/B tại đây chưa tự thay đổi câu trả lời đang gửi cho khách. Quản trị viên vẫn phải duyệt và triển khai riêng.</span>
          </div>
          <div class="ai-readiness-grid" aria-label="Mức độ sẵn sàng của các chức năng AI">
            <div><span class="ai-readiness-badge ready">Đang dùng</span><strong>Kho kiến thức</strong><small>RAG dùng để tra cứu kho kiến thức đã lập chỉ mục khi hỗ trợ trả lời.</small></div>
            <div><span class="ai-readiness-badge limited">Hỗ trợ phân tích</span><strong>Nhóm nhu cầu</strong><small>Tổng hợp theo quy tắc, chưa phải học không giám sát hoàn chỉnh.</small></div>
            <div><span class="ai-readiness-badge experimental">Thử nghiệm</span><strong>A/B và dự đoán</strong><small>A/B đang thử nghiệm, chưa tự thay đổi bot hoặc áp dụng vào hội thoại thật.</small></div>
          </div>
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
              <div class="ai-stat-card"><span>Doanh thu cứu lại</span><strong>{{ Number(aiEvaluationDashboard.commerce?.recovered_revenue || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong><small>{{ aiEvaluationDashboard.commerce?.recovered_orders || 0 }} đơn sau nhắc chăm sóc</small></div>
              <div class="ai-stat-card"><span>Bot phản hồi, chưa bàn giao</span><strong>{{ ((aiEvaluationDashboard.ai?.handoff?.bot_only_rate || 0) * 100).toFixed(1) }}%</strong><small>{{ aiEvaluationDashboard.ai?.handoff?.bot_only_count || 0 }} / {{ aiEvaluationDashboard.ai?.handoff?.inbound_conversation_count || 0 }} hội thoại có bot trả lời và chưa ghi nhận bàn giao</small></div>
            </div>
            <div class="ai-outcome-summary">
              <h4>Kết quả được nhân viên xác nhận</h4>
              <p>Chỉ tính hội thoại có chatbot trả lời hoặc đã chuyển nhân viên. Hội thoại chưa được gắn kết quả sẽ không bị suy đoán.</p>
              <div class="ai-lab-summary ai-quality-grid">
                <div class="ai-stat-card"><span>Đã xác nhận giải quyết</span><strong>{{ aiEvaluationDashboard.ai?.confirmed_outcomes?.resolved || 0 }}</strong><small>Nhân viên xác nhận đã xử lý xong</small></div>
                <div class="ai-stat-card"><span>Cần nhân viên hỗ trợ</span><strong>{{ aiEvaluationDashboard.ai?.confirmed_outcomes?.needs_human || 0 }}</strong><small>Kết quả được xác nhận cần hỗ trợ người thật</small></div>
                <div class="ai-stat-card"><span>Khách chưa phản hồi</span><strong>{{ aiEvaluationDashboard.ai?.confirmed_outcomes?.customer_unanswered || 0 }}</strong><small>Nhân viên xác nhận đang chờ khách</small></div>
                <div class="ai-stat-card"><span>Chưa ghi nhận</span><strong>{{ aiEvaluationDashboard.ai?.confirmed_outcomes?.unclassified || 0 }}</strong><small>Trong {{ aiEvaluationDashboard.ai?.confirmed_outcomes?.tracked_conversation_count || 0 }} hội thoại có AI tham gia</small></div>
              </div>
              <h4>Ước tính theo trạng thái CRM</h4>
              <p>Các số liệu dưới đây được suy ra từ trạng thái hội thoại/phiếu và thời gian phản hồi, không phải xác nhận của nhân viên.</p>
              <div class="ai-lab-summary ai-quality-grid">
                <div class="ai-stat-card"><span>Đã giải quyết</span><strong>{{ aiEvaluationDashboard.ai?.outcomes?.resolved || 0 }}</strong><small>Hội thoại đã đóng hoặc phiếu mới nhất đã xử lý</small></div>
                <div class="ai-stat-card"><span>Cần người hỗ trợ</span><strong>{{ aiEvaluationDashboard.ai?.outcomes?.needs_human || 0 }}</strong><small>Đang tiếp quản hoặc phiếu mới nhất còn mở</small></div>
                <div class="ai-stat-card"><span>Khách chưa phản hồi</span><strong>{{ aiEvaluationDashboard.ai?.outcomes?.customer_unanswered || 0 }}</strong><small>Shop đã trả lời nhưng khách chưa phản hồi trong 24 giờ</small></div>
                <div class="ai-stat-card"><span>Đang tiếp tục</span><strong>{{ aiEvaluationDashboard.ai?.outcomes?.in_progress || 0 }}</strong><small>{{ aiEvaluationDashboard.ai?.outcomes?.inbound_conversation_count || 0 }} hội thoại có tin đến trong kỳ</small></div>
              </div>
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
              <div class="ai-card-heading"><div><span class="card-eyebrow">THỬ NGHIỆM NỘI BỘ</span><h3>Tạo thử nghiệm A/B</h3></div><span class="ai-card-icon ai-card-icon-alt">A/B</span></div>
              <p class="ai-card-help">Khai báo các biến thể để ghi nhận và so sánh kết quả. Việc tạo thử nghiệm chưa tự đưa biến thể vào câu trả lời đang gửi cho khách.</p>
              <label class="ai-field">Tên thử nghiệm<input v-model="experimentForm.name" required maxlength="160" placeholder="Ví dụ: Mẫu trả lời giá" /></label>
              <label class="ai-field">Các biến thể<textarea v-model="experimentForm.variants" required rows="4" placeholder="A\nB"></textarea></label>
              <label class="ai-field">Trạng thái ban đầu<select v-model="experimentForm.status"><option value="draft">Bản nháp</option><option value="running">Đang chạy</option><option value="paused">Tạm dừng</option></select></label>
              <div class="ai-field-grid"><label class="ai-field">Mẫu tối thiểu / cách thử<input v-model.number="experimentForm.min_sample_size" min="0" type="number" /></label><label class="ai-field">Dừng khi tỷ lệ chuyển đổi đạt<input v-model.number="experimentForm.target_conversion_rate" min="0" max="1" step="0.01" type="number" placeholder="VD: 0.15" /></label></div>
              <div class="ai-form-actions"><button type="button" class="secondary-btn" @click="resetExperimentForm">Xóa biểu mẫu</button><button class="primary-btn" type="submit" :disabled="experimentSaving">{{ experimentSaving ? 'Đang tạo...' : 'Tạo thử nghiệm' }}</button></div>
            </form>

            <form class="ai-compose-card" @submit.prevent="createModelVersion">
              <div class="ai-card-heading"><div><span class="card-eyebrow">BẢN ĐÁNH GIÁ KỸ THUẬT</span><h3>Phiên bản dự đoán thử nghiệm</h3></div><span class="ai-card-icon">ML</span></div>
              <p class="ai-card-help">Lưu một phiên bản dữ liệu để chạy đánh giá nền. Kết quả chưa phải mô hình tự học và không tự thay đổi trợ lý đang phục vụ khách.</p>
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
            <div class="ai-board-header"><div><span class="card-eyebrow">KHO PHIÊN BẢN THỬ NGHIỆM</span><h3>Phiên bản &amp; đánh giá nền</h3><p>Trạng thái “sẵn sàng” chỉ cho biết lần đánh giá đã hoàn tất, không có nghĩa phiên bản đang được dùng để trả lời khách.</p></div><span class="count-badge">{{ modelVersions.length }}</span></div>
            <div v-if="!modelVersions.length" class="ai-empty-state"><strong>Chưa có phiên bản trợ lý</strong><span>Tạo phiên bản đầu tiên để quản lý lịch sử cập nhật.</span></div>
            <div v-else class="ai-experiment-list"><article v-for="model in modelVersions" :key="model.id" class="ai-experiment-card"><div><strong>{{ model.name }} · {{ model.version }}</strong><span>Dữ liệu {{ model.feature_version }} → {{ model.target }}</span></div><span class="ai-status-pill" :class="`status-${model.status}`">{{ modelStatusLabel(model.status) }}</span><small v-if="model.artifact?.metrics">Độ lệch kiểm tra {{ model.artifact.metrics.mae ?? '—' }} · số mẫu kiểm tra {{ model.artifact.metrics.holdout_count ?? '—' }}</small><button v-if="model.status !== 'ready'" type="button" class="settings-refresh" @click="trainModel(model)">Chạy đánh giá mẫu</button></article></div>
          </div>

          <div class="ai-board-card">
            <div class="ai-board-header"><div><span class="card-eyebrow">THỬ NGHIỆM NỘI BỘ</span><h3>Thử nghiệm đang theo dõi</h3><p>So sánh dữ liệu đã ghi nhận để hỗ trợ quyết định; hệ thống chưa tự phân phối cách trả lời cho khách.</p></div><span class="count-badge">{{ experiments.length }}</span></div>
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
            <h2>Kho kiến thức</h2>
            <p>Nạp tài liệu sản phẩm, câu hỏi thường gặp và chính sách để trợ lý tra cứu kho kiến thức khi trả lời khách. Tài liệu được lập chỉ mục, không dùng để tự huấn luyện mô hình.</p>
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
             <strong>Đang tải tệp lên...</strong>
          </div>
        </div>

        <div v-if="docUploadError" class="error-banner">
          {{ docUploadError }}
        </div>
        <div v-if="docUploadNotice" class="settings-notice" role="status" aria-live="polite">
          {{ docUploadNotice }}
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
            📭 Chưa có tài liệu nào trong Kho kiến thức. Hãy nhập tệp hoặc dán văn bản ở trên!
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
                   <small v-if="doc.error_message" class="doc-embedding-state doc-error-detail">{{ doc.error_message }}</small>
                   <small v-if="documentRuns[doc.id]" class="doc-embedding-state">
                    Lần xử lý: {{ ragRunStatusLabel(documentRuns[doc.id].status) }} · lần {{ documentRuns[doc.id].attempts || 0 }}
                    <template v-if="documentRuns[doc.id].status === 'processing'">
                      · {{ ragRunPhaseLabel(documentRuns[doc.id].phase) }} · {{ documentRuns[doc.id].progress_percent || 0 }}%
                    </template>
                  </small>
                  <progress
                    v-if="documentRuns[doc.id]?.status === 'processing'"
                    class="doc-progress"
                    :value="documentRuns[doc.id].progress_percent"
                    max="100"
                    :aria-label="`Tiến độ xử lý ${doc.filename}`"
                  ></progress>
                </td>
                <td class="text-sm text-gray">{{ formatTime(doc.uploaded_at) }}</td>
                <td>
                  <button class="btn-delete" @click="deleteDoc(doc.id)" title="Xóa tài liệu">
                    Xóa
                  </button>
                  <button class="btn-refresh" @click="reindexDocument(doc)" title="Lập chỉ mục lại">
                    🔁 Xử lý lại tài liệu
                  </button>
                  <button
                    v-if="documentRuns[doc.id]?.status === 'failed'"
                    class="btn-refresh"
                    :disabled="docRetryingIds.has(doc.id)"
                    @click="retryDocumentRun(doc, documentRuns[doc.id])"
                    title="Thử lại xử lý"
                  >
                    {{ docRetryingIds.has(doc.id) ? 'Đang xếp hàng...' : 'Thử lại xử lý' }}
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
            <p class="setting-desc">Trợ lý tự chọn thông tin phù hợp trong Kho kiến thức của shop. Các thiết lập kỹ thuật được hệ thống tối ưu sẵn.</p>
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
          <label>Kênh<select v-model="reportFilters.channel"><option value="">Tất cả kênh</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="telegram">Telegram</option><option value="zalo">Zalo</option><option value="tiktok">TikTok</option></select></label>
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
            <div class="report-card"><span>Doanh thu</span><strong>{{ Number(crmOverview.total_revenue || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></div>
            <div class="report-card"><span>Tỷ lệ chốt cơ hội</span><strong>{{ crmOverview.conversion_rate }}%</strong><small>{{ crmOverview.won_lead_count }}/{{ crmOverview.lead_count }} cơ hội</small></div>
            <div class="report-card"><span>Đơn / hội thoại</span><strong>{{ crmOverview.conversation_to_order_rate }}%</strong></div>
            <div class="report-card"><span>Phiếu đang mở</span><strong>{{ crmOverview.open_ticket_count }}</strong><small>{{ crmOverview.ticket_count }} phiếu tổng</small></div>
            <div class="report-card"><span>Đơn nhập hàng</span><strong>{{ crmOverview.purchase_order_count || 0 }}</strong><small>Chi {{ Number(crmOverview.purchase_spend || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</small></div>
          </div>
          <div class="report-panel quality-ops-panel">
            <div class="report-panel-header">
              <div><h3>Vận hành nền tảng</h3><span>Lượt dùng, kênh kết nối, chi phí trợ lý và thời hạn trong {{ qualityDashboard.period_days || 30 }} ngày gần nhất</span></div>
              <span class="quality-health-pill" :class="{ warning: (qualityDashboard.provider?.failed_events || 0) > 0 || (qualityDashboard.sla?.overdue_tickets || 0) > 0 || Object.values(qualityDashboard.provider?.circuits || {}).some(circuit => circuit.state === 'open') }">{{ (qualityDashboard.provider?.failed_events || 0) > 0 || (qualityDashboard.sla?.overdue_tickets || 0) > 0 || Object.values(qualityDashboard.provider?.circuits || {}).some(circuit => circuit.state === 'open') ? 'Cần xử lý' : 'Ổn định' }}</span>
            </div>
            <div class="report-cards quality-ops-cards">
              <div class="report-card"><span>Kênh lỗi</span><strong>{{ qualityDashboard.provider?.failed_events || 0 }}</strong><small>{{ qualityDashboard.provider?.retrying_events || 0 }} đang thử lại</small></div>
              <div class="report-card"><span>Lượt trợ lý</span><strong>{{ qualityDashboard.ai?.calls || 0 }}</strong><small>{{ qualityDashboard.ai?.tool_errors || 0 }} lỗi công cụ</small></div>
              <div class="report-card"><span>Chi phí trợ lý</span><strong>{{ Number(qualityDashboard.ai?.cost || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}</strong><small>theo hạn mức kỳ hiện tại</small></div>
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
              <div class="report-card accent"><span>Doanh thu được gán</span><strong>{{ Number(revenueAttribution.total_attributed || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></div>
              <div class="report-card"><span>Điểm tương tác</span><strong>{{ revenueAttribution.items?.length || 0 }}</strong></div>
            </div>
            <div v-if="!revenueAttribution.items?.length" class="products-empty">Chưa có dữ liệu điểm tương tác. Doanh thu sẽ xuất hiện sau khi gắn nguồn hội thoại/chiến dịch.</div>
            <div v-else class="products-table-wrap">
              <table class="products-table reports-table">
                <thead><tr><th>Kênh</th><th>Nguồn</th><th>Campaign</th><th>Doanh thu gán</th></tr></thead>
                <tbody><tr v-for="item in revenueAttribution.items" :key="`${item.channel}-${item.source}-${item.campaign || ''}`"><td>{{ item.channel || '—' }}</td><td>{{ item.source }}</td><td>{{ item.campaign || '—' }}</td><td><strong>{{ Number(item.attributed_revenue || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></td></tr></tbody>
              </table>
            </div>
          </div>
          <div class="report-panel">
            <div class="report-panel-header"><div><h3>Luồng bán hàng & chuyển đổi</h3><span>Cơ hội theo giai đoạn trong phạm vi lọc</span></div><strong>{{ pipelineSummary.reduce((total, item) => total + Number(item.lead_count || 0), 0) }} cơ hội</strong></div>
            <div v-if="!pipelineSummary.length" class="products-empty">Chưa có cơ hội phù hợp với bộ lọc.</div>
            <div v-else class="pipeline-summary"><div v-for="item in pipelineSummary" :key="item.stage" class="pipeline-card"><span>{{ leadStageLabel(item.stage) }}</span><strong>{{ item.lead_count }}</strong><small>{{ Number(item.value || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</small></div></div>
          </div>
          <div class="report-panel">
            <div class="report-panel-header"><div><h3>Phiếu hỗ trợ & thời hạn</h3><span>Phiếu theo trạng thái trong phạm vi lọc</span></div><strong>{{ ticketReport.overdue_tickets || 0 }} quá hạn</strong></div>
            <div v-if="!ticketReport.items?.length" class="products-empty">Chưa có phiếu phù hợp với bộ lọc.</div>
            <div v-else class="ticket-summary"><div class="ticket-stat"><span>Tổng phiếu</span><strong>{{ ticketReport.total_tickets || 0 }}</strong></div><div v-for="item in ticketReport.items" :key="item.status" class="ticket-stat"><span>{{ ticketStatusLabel(item.status) }}</span><strong>{{ item.ticket_count }}</strong></div></div>
          </div>
          <div v-if="crmOverview.time_series?.length" class="report-panel">
            <div class="report-panel-header"><h3>Xu hướng theo ngày</h3><span>Hội thoại · đơn bán · doanh thu</span></div>
            <div class="report-series"><div v-for="point in crmOverview.time_series.slice(-14)" :key="point.date" class="report-series-row"><span>{{ point.date }}</span><b>{{ point.conversations }} hội thoại · {{ point.orders }} đơn · {{ Number(point.revenue || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</b></div></div>
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
            <div class="report-panel-header"><h3>Chi phí nhập đã nhận</h3><strong>{{ Number(purchaseCostReport.total_received_cost || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></div>
            <div v-if="!purchaseCostReport.items?.length" class="products-empty">Chưa có phiếu nhập trong khoảng thời gian này.</div>
            <div v-else class="products-table-wrap"><table class="products-table reports-table"><thead><tr><th>Nhà cung cấp</th><th>Số phiếu</th><th>Số lượng</th><th>Chi phí nhận</th></tr></thead><tbody><tr v-for="item in purchaseCostReport.items" :key="item.supplier_name"><td>{{ item.supplier_name }}</td><td>{{ item.receipt_count }}</td><td>{{ item.received_quantity }}</td><td><strong>{{ Number(item.received_cost || 0).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}đ</strong></td></tr></tbody></table></div>
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
          <fieldset class="special-business-dates"><legend>Giờ đặc biệt</legend><p>Ngày đặc biệt sẽ ghi đè lịch hằng tuần. Khi khách nhắn vào ngày/giờ đóng cửa, trợ lý gửi phản hồi ngoài giờ; hệ thống không tự nhắn hàng loạt chỉ vì bạn đổi lịch.</p><div v-if="!specialBusinessDates.length" class="settings-empty">Chưa có ngày đặc biệt.</div><div v-for="(item, index) in specialBusinessDates" :key="`${item.date}-${index}`" class="special-business-date-row"><input v-model="item.date" type="date" aria-label="Ngày đặc biệt" /><label><input v-model="item.closed" type="checkbox" /> Nghỉ cả ngày</label><template v-if="!item.closed"><input v-model="item.start" type="time" aria-label="Giờ mở đặc biệt" /><span>đến</span><input v-model="item.end" type="time" aria-label="Giờ đóng đặc biệt" /></template><button type="button" class="history-btn" @click="removeSpecialBusinessDate(index)">Xóa</button></div><button type="button" class="table-action-btn secondary" @click="addSpecialBusinessDate">+ Thêm ngày đặc biệt</button></fieldset>
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
              <p>Quản lý Facebook, Instagram, Telegram, Zalo, TikTok và Shopee riêng cho shop này.</p>
            </div>
            <span class="connection-badge" :class="{ connected: metaStatus.connected || activeBotConnections.length }">
              {{ (metaStatus.connected || activeBotConnections.length) ? 'ĐANG HOẠT ĐỘNG' : 'CHƯA KẾT NỐI' }}
            </span>
          </div>
          <p class="settings-muted">Mỗi shop chỉ nhìn thấy mã kết nối, nhận sự kiện và lịch sử của chính shop đó. Dữ liệu không dùng chung giữa các không gian.</p>
          <div v-if="quotaSnapshot?.resources?.connected_channels" class="channel-quota-note">Kênh đang dùng: <strong>{{ channelCapacity.limit === null ? `${channelCapacity.used} / ∞` : `${channelCapacity.used} / ${channelCapacity.limit}` }}</strong> theo gói {{ quotaSnapshot.plan_name || 'hiện tại' }}.</div>
          <div v-if="channelCapacity.blocked" class="channel-capacity-alert" role="status"><span>{{ channelCapacity.reason }}</span><button type="button" class="settings-refresh" @click="openServicePage">Nâng cấp gói</button></div>
        </div>

        <div v-if="authUser" class="channel-summary-grid channel-summary-grid-six">
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2 class="channel-title-with-logo"><span class="channel-card-icon facebook-channel-icon" aria-hidden="true">f</span><span>Facebook</span></h2><p>Trang bán hàng và tin nhắn Messenger.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected }">{{ metaStatus.connected ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Cấp quyền một lần để nhận tin từ Trang Facebook.</p>
            <div class="channel-summary-actions"><button type="button" class="primary-btn" @click="openChannelModal('facebook')">{{ metaStatus.connected ? 'Xem Facebook' : 'Kết nối Facebook' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2 class="channel-title-with-logo"><span class="channel-card-icon instagram-channel-icon" aria-hidden="true">◎</span><span>Instagram</span></h2><p>Tài khoản chuyên nghiệp và tin nhắn Instagram.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected && metaStatus.instagram_account_id }">{{ metaStatus.connected && metaStatus.instagram_account_id ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Dùng chung lần cấp quyền Facebook nhưng theo dõi riêng.</p>
            <div class="channel-summary-actions"><button type="button" class="secondary-btn" @click="openChannelModal('instagram')">{{ metaStatus.connected && metaStatus.instagram_account_id ? 'Xem Instagram' : 'Kết nối Instagram' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2 class="channel-title-with-logo"><span class="channel-card-icon telegram-channel-icon" aria-hidden="true">✈</span><span>Telegram</span></h2><p>Bot Telegram riêng của shop.</p></div><span class="connection-badge" :class="{ connected: activeBotConnections.some((item) => item.channel_type === 'telegram') }">{{ activeBotConnections.some((item) => item.channel_type === 'telegram') ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Dán mã bot, CRM kiểm tra và nhận tin tự động.</p>
            <div class="channel-summary-actions"><button type="button" class="primary-btn" @click="openChannelModal('telegram')">{{ activeBotConnections.some((item) => item.channel_type === 'telegram') ? 'Quản lý Telegram' : 'Kết nối Telegram' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2 class="channel-title-with-logo"><span class="channel-card-icon zalo-channel-icon" aria-hidden="true">Z</span><span>Zalo Bot</span></h2><p>Kết nối Zalo Bot Creator chính thức của shop.</p></div><span class="connection-badge" :class="{ connected: activeBotConnections.some((item) => item.channel_type === 'zalo') }">{{ activeBotConnections.some((item) => item.channel_type === 'zalo') ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
            <p class="settings-muted">Dùng Bot Token để nhận tin qua webhook riêng của shop. Nếu cần bridge cá nhân, nhập mã bắt đầu bằng <code>personal:</code>.</p>
            <div class="channel-summary-actions"><button type="button" class="secondary-btn" @click="openChannelModal('zalo')">{{ activeBotConnections.some((item) => item.channel_type === 'zalo') ? 'Quản lý Zalo' : 'Kết nối Zalo' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card">
            <div class="settings-card-header"><div><h2 class="channel-title-with-logo"><span class="channel-card-icon tiktok-channel-icon" aria-hidden="true"><svg class="tiktok-logo" viewBox="0 0 24 24"><path class="tiktok-logo-cyan" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/><path class="tiktok-logo-red" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/><path class="tiktok-logo-main" d="M19.59 6.69a4.83 4.83 0 1 0-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/></svg></span><span>TikTok</span></h2><p>Kết nối bằng TikTok bridge trên máy của shop.</p></div><span class="connection-badge" :class="{ connected: activeTikTokConnection }">{{ activeTikTokConnection ? 'ĐÃ BẬT BRIDGE' : 'CHƯA CẤU HÌNH' }}</span></div>
            <p class="settings-muted">Tải file ZIP TikTok đã cấu hình sẵn để nhận tin vào đúng không gian shop.</p>
            <div class="channel-summary-actions"><button type="button" class="secondary-btn" @click="openChannelModal('tiktok')">{{ activeTikTokConnection ? 'Quản lý TikTok' : 'Thiết lập TikTok' }}</button></div>
          </article>
          <article class="settings-card channel-summary-card channel-summary-card-planned">
            <div class="settings-card-header"><div><h2 class="channel-title-with-logo"><span class="channel-card-icon shopee-channel-icon" aria-hidden="true">S</span><span>Shopee</span></h2><p>Kênh đơn hàng và chăm sóc khách hàng Shopee.</p></div><span class="connection-badge channel-status-planned">ĐANG HOÀN THIỆN</span></div>
            <p class="settings-muted">Shopee đã nằm trong hạn mức gói CRM. Kết nối Open Platform sẽ được bật sau khi kiểm thử webhook và quyền chat.</p>
            <div class="channel-summary-actions"><button type="button" class="secondary-btn" disabled>Sắp ra mắt</button></div>
          </article>
        </div>
        <div v-if="authUser" class="settings-card channel-connect-card" aria-hidden="true"></div>

        <div v-if="channelModalOpen" class="app-dialog-backdrop channel-modal-backdrop" @click.self="closeChannelModal">
          <section class="channel-modal app-dialog" role="dialog" aria-modal="true" aria-label="Kết nối kênh bán hàng" tabindex="-1" @keydown.esc="closeChannelModal">
            <div class="settings-card-header"><div><span class="card-eyebrow">KÊNH CỦA SHOP</span><h2>{{ ['meta', 'facebook', 'instagram'].includes(channelModalTab) ? 'Kết nối Facebook & Instagram' : `Kết nối ${channelModalTab === 'zalo' ? 'Zalo' : channelModalTab === 'tiktok' ? 'TikTok' : 'Telegram'}` }}</h2><p>Mã kết nối chỉ dùng cho shop này và không chia sẻ giữa các không gian.</p></div><button type="button" class="quick-action-close" aria-label="Đóng" @click="closeChannelModal">×</button></div>
            <span class="visually-hidden">Kết nối Telegram/Zalo · Quét QR để tạo bot · BotFather · Zalo Bot Manager</span>
            <template v-if="['meta', 'facebook', 'instagram'].includes(channelModalTab)">
              <div v-if="metaNotice" class="settings-notice team-error">{{ metaNotice }}</div>
              <div v-if="demoChannelsLocked" class="settings-notice channel-plan-locked"><span>{{ channelCapacity.reason }}</span><button type="button" class="settings-refresh" @click="openServicePageFromChannelLimit">Nâng cấp gói</button></div>
              <div class="meta-channel-grid">
                <article class="meta-channel-card meta-facebook" :class="{ active: channelModalTab === 'facebook' }"><div><span class="channel-card-icon">f</span><h3>Facebook</h3><p>Trang bán hàng và tin nhắn Messenger.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected }">{{ metaStatus.connected ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span><div v-if="metaStatus.connected" class="meta-connection-details"><div><strong>Trang:</strong> {{ metaStatus.facebook_page_name || 'Đã kết nối' }}</div><div><strong>Mã trang:</strong> {{ metaStatus.facebook_page_id || '—' }}</div></div><button v-if="!metaStatus.connected" class="btn-meta-connect" type="button" :disabled="metaLoading || demoChannelsLocked" @click="connectMeta">{{ demoChannelsLocked ? 'Không thể kết nối thêm' : metaLoading ? 'Đang kết nối...' : 'Kết nối Facebook' }}</button></article>
                <article class="meta-channel-card meta-instagram" :class="{ active: channelModalTab === 'instagram' }"><div><span class="channel-card-icon">◎</span><h3>Instagram</h3><p>Tài khoản chuyên nghiệp và tin nhắn Instagram.</p></div><span class="connection-badge" :class="{ connected: metaStatus.connected && metaStatus.instagram_account_id }">{{ metaStatus.connected && metaStatus.instagram_account_id ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span><div v-if="metaStatus.connected" class="meta-connection-details"><div><strong>Tài khoản:</strong> {{ metaStatus.instagram_account_id || 'Chưa liên kết' }}</div><div><strong>Nhận tin:</strong> {{ metaStatus.subscription_status || 'Chưa kiểm tra' }}</div></div><button v-if="!metaStatus.connected" class="btn-meta-connect" type="button" :disabled="metaLoading || demoChannelsLocked" @click="connectMeta">{{ demoChannelsLocked ? 'Không thể kết nối thêm' : metaLoading ? 'Đang kết nối...' : 'Kết nối Instagram' }}</button></article>
              </div>
              <p class="settings-muted meta-oauth-note">Facebook và Instagram dùng chung một lần cấp quyền; CRM vẫn tách riêng dữ liệu và trạng thái hiển thị cho từng kênh.</p>
              <div v-if="metaStatus.connected" class="settings-actions"><button class="btn-meta-disconnect" type="button" :disabled="metaLoading" @click="disconnectMeta">Ngắt kết nối Facebook/Instagram</button></div>
            </template>
            <template v-else-if="channelModalTab === 'tiktok'">
              <div v-if="tiktokBridgeError" class="settings-notice team-error">{{ tiktokBridgeError }}</div>
              <div v-if="tiktokBridgeNotice" class="settings-notice">{{ tiktokBridgeNotice }}</div>
              <div class="bot-provider-heading"><span class="channel-card-icon tiktok-channel-icon"><svg class="tiktok-logo" viewBox="0 0 24 24" aria-hidden="true"><path class="tiktok-logo-cyan" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/><path class="tiktok-logo-red" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/><path class="tiktok-logo-main" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/></svg></span><div><h3>TikTok Bridge</h3><p>Nhận tin TikTok qua tệp bridge đang chạy trên máy của shop.</p></div><span class="connection-badge" :class="{ connected: activeTikTokConnection }">{{ activeTikTokConnection ? 'ĐÃ BẬT BRIDGE' : 'CHƯA CẤU HÌNH' }}</span></div>
              <div class="bot-connect-guide-single"><div class="bot-guide-qr-wrap channel-card-icon tiktok-channel-icon"><svg class="tiktok-logo" viewBox="0 0 24 24" aria-hidden="true"><path class="tiktok-logo-cyan" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/><path class="tiktok-logo-red" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/><path class="tiktok-logo-main" d="M19.59 6.69a4.83 4.83 0 1 0-3.77-3.77V2h-3.32v13.11a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.04.87.13V9.03a6.24 6.24 0 1 0 5.34 6.08V8.38a8.17 8.17 0 0 0 4.77 1.53V6.69Z"/></svg></div><div><ol><li>Tải file ZIP TikTok đã cấu hình sẵn cho shop.</li><li>Giải nén rồi mở <code>SmartMerchantTikTok.exe</code>.</li><li>Ứng dụng tự lấy phiên TikTok và chuyển tin về CRM.</li></ol><p class="bot-connect-note">Cookie chỉ được đọc trên máy chạy ứng dụng và không gửi lên CRM. Không cần sao chép mã kết nối.</p></div></div>
              <div class="tiktok-bridge-actions"><a v-if="tiktokBridgeDownloadUrl && !demoChannelsLocked" class="primary-btn bot-connect-submit" :href="tiktokBridgeDownloadUrl" download="SmartMerchantTikTok.zip">Tải file ZIP TikTok</a><button v-else class="primary-btn bot-connect-submit" type="button" :disabled="true">{{ demoChannelsLocked ? 'Không thể kết nối thêm' : 'Tạo cấu hình trước' }}</button><button class="secondary-btn" type="button" :disabled="tiktokBridgeLoading || demoChannelsLocked" @click="connectTikTokBridge">{{ demoChannelsLocked ? 'Không thể kết nối thêm' : tiktokBridgeLoading ? 'Đang tạo...' : activeTikTokConnection ? 'Cấp lại cấu hình' : 'Tạo cấu hình' }}</button></div>
              <div v-if="tiktokBridgeSecret" class="settings-notice tiktok-bridge-secret"><strong>Cấu hình TikTok đã sẵn sàng.</strong><small>File ZIP đã gắn sẵn cấu hình; bridge chỉ bắt đầu hoạt động sau khi bạn giải nén và mở SmartMerchantTikTok.exe.</small></div>
              <div v-if="botConnectionLoading" class="settings-empty">Đang tải trạng thái kết nối...</div><ul v-else-if="botConnections.filter((item) => item.channel_type === 'tiktok').length" class="bot-connection-list"><li v-for="connection in botConnections.filter((item) => item.channel_type === 'tiktok')" :key="connection.id"><div><strong>{{ connection.name }}</strong><small>TikTok bridge · {{ botConnectionStateLabel(connection.status) }}</small></div><button type="button" class="team-toggle" @click="disconnectBotChannel(connection)">Ngắt kết nối</button></li></ul>
              <div v-else class="settings-empty">Chưa có TikTok bridge nào.</div>
            </template>
            <template v-else>
              <span class="visually-hidden">Sao chép token · Zalo Bot Manager</span>
              <div v-if="botConnectionError" class="settings-notice team-error bot-connection-alert"><span>{{ botConnectionError }}</span><button type="button" class="settings-refresh" :disabled="botConnectionLoading" @click="fetchBotConnections">{{ botConnectionLoading ? 'Đang tải...' : 'Thử lại' }}</button></div><div v-if="botConnectionNotice" class="settings-notice">{{ botConnectionNotice }}</div>
              <div class="bot-provider-heading"><span class="channel-card-icon">{{ channelModalTab === 'zalo' ? 'Z' : '✈' }}</span><div><h3>{{ channelModalTab === 'zalo' ? 'Zalo Bot Creator' : 'Telegram BotFather' }}</h3><p>{{ channelModalTab === 'zalo' ? 'Kết nối Zalo Bot chính thức của shop.' : 'Kết nối kênh Telegram chính thức của shop.' }}</p></div><span class="connection-badge" :class="{ connected: activeBotConnections.some((item) => item.channel_type === channelModalTab) }">{{ activeBotConnections.some((item) => item.channel_type === channelModalTab) ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}</span></div>
              <div class="bot-connect-guide-single"><div class="bot-guide-qr-wrap"><img :src="botQrUrl(channelModalTab)" :alt="`Mã QR mở ${channelModalTab === 'zalo' ? 'Zalo Bot Creator' : 'Telegram BotFather'}`" loading="lazy" /></div><div><ol v-if="channelModalTab === 'telegram'"><li>Mở BotFather.</li><li>Gõ <code>/newbot</code> và tạo bot.</li><li>Sao chép mã bot gửi cho bạn.</li></ol><ol v-else><li>Mở Zalo Bot Manager và chọn Tạo bot.</li><li>Sao chép Bot Token được cấp sau khi tạo.</li><li>Dán Bot Token vào đây để CRM đăng ký webhook.</li></ol><a class="bot-guide-link" :href="botGuideUrl(channelModalTab)" target="_blank" rel="noreferrer">{{ channelModalTab === 'zalo' ? 'Mở hướng dẫn Zalo Bot' : 'Mở Telegram BotFather' }}</a></div></div>
              <div v-if="demoChannelsLocked" class="settings-notice channel-plan-locked"><span>{{ channelCapacity.reason }}</span><button type="button" class="settings-refresh" @click="openServicePageFromChannelLimit">Nâng cấp gói</button></div>
              <form class="bot-connect-form" @submit.prevent="connectBotChannel"><input type="hidden" v-model="botConnectionForm.channel_type" /><label class="bot-token-field">{{ channelModalTab === 'zalo' ? 'Bot Token Zalo' : 'Mã bot' }}<div class="bot-token-input-wrap"><input v-model="botConnectionForm.access_token" :type="botTokenVisible ? 'text' : 'password'" autocomplete="off" required :disabled="demoChannelsLocked" :placeholder="demoChannelsLocked ? 'Nâng cấp gói để mở kết nối' : channelModalTab === 'zalo' ? 'Dán Bot Token Zalo tại đây' : 'Dán mã bot tại đây'" /><button type="button" class="token-visibility-btn" :disabled="demoChannelsLocked" @click="botTokenVisible = !botTokenVisible">{{ botTokenVisible ? 'Ẩn' : 'Hiện' }}</button></div></label><button class="primary-btn bot-connect-submit" type="submit" :disabled="botConnectionSaving || demoChannelsLocked">{{ demoChannelsLocked ? 'Không thể kết nối thêm' : botConnectionSaving ? 'Đang kiểm tra...' : 'Kiểm tra và kết nối' }}</button></form>
              <p class="bot-connect-note">{{ channelModalTab === 'zalo' ? 'Bot Token được mã hóa khi lưu. Chỉ dùng tiền tố personal: nếu shop thực sự dùng bridge cá nhân.' : 'Mã kết nối chỉ dùng cho shop này và được lưu an toàn.' }}</p><div v-if="botConnectionLoading" class="settings-empty">Đang tải trạng thái kết nối...</div><ul v-else-if="botConnections.filter((item) => item.channel_type === channelModalTab).length" class="bot-connection-list"><li v-for="connection in botConnections.filter((item) => item.channel_type === channelModalTab)" :key="connection.id"><div><strong>{{ connection.name }}</strong><small>{{ channelModalTab === 'zalo' ? 'Zalo Bot' : 'Telegram' }} · {{ botConnectionStateLabel(connection.status) }} · Nhận tin {{ connection.webhook_status === 'connected' ? 'hoạt động' : connection.webhook_status === 'disconnected' ? 'đã ngắt' : 'cần kiểm tra' }}</small></div><button v-if="['connected', 'active', 'verifying', 'reconnect_required', 'error'].includes(String(connection.status || '').toLowerCase())" type="button" class="team-toggle" @click="disconnectBotChannel(connection)">Ngắt kết nối</button></li></ul><div v-else class="settings-empty">Chưa có kết nối {{ channelModalTab === 'zalo' ? 'Zalo Bot' : 'Telegram' }} nào.</div>
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
            <div><h2>Nhận sự kiện</h2><p>Kiểm tra trạng thái nhận tin nhắn từ Facebook, Instagram, Telegram, Zalo, TikTok và Shopee.</p></div>
            <button type="button" class="settings-refresh" :disabled="botConnectionLoading || metaLoading" @click="refreshWebhookStatus">{{ botConnectionLoading || metaLoading ? 'Đang kiểm tra...' : 'Làm mới' }}</button>
          </div>
          <div v-if="botConnectionError || metaNotice" class="settings-notice team-error">{{ botConnectionError || metaNotice }}</div>
          <div class="webhook-grid">
            <article class="webhook-item"><div><strong>Facebook</strong><span class="webhook-status" :class="{ connected: metaStatus.connected && metaStatus.subscription_status }">{{ metaStatus.connected ? (metaStatus.subscription_status || 'Đã kết nối') : 'Chưa kết nối' }}</span></div><small>Nhận tin tự động từ Trang Facebook của shop.</small></article>
            <article class="webhook-item"><div><strong>Instagram</strong><span class="webhook-status" :class="{ connected: metaStatus.connected && metaStatus.instagram_account_id }">{{ metaStatus.instagram_account_id ? 'Đã kết nối' : 'Chưa kết nối' }}</span></div><small>Nhận tin Instagram riêng, dùng cùng lần cấp quyền Facebook.</small></article>
            <article v-for="connection in botConnections" :key="`webhook-${connection.id}`" class="webhook-item"><div><strong>{{ connection.channel_type === 'zalo' ? 'Zalo' : connection.channel_type === 'tiktok' ? 'TikTok' : 'Telegram' }}</strong><span class="webhook-status" :class="{ connected: connection.webhook_status === 'connected' }">{{ connection.webhook_status === 'connected' ? 'Đang hoạt động' : connection.webhook_status === 'disconnected' ? 'Đã ngắt' : 'Cần kiểm tra' }}</span></div><small>{{ connection.name }} · nhận tin riêng cho shop.</small></article>
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
              <h2>Tài khoản &amp; phiên đăng nhập</h2>
              <p>Phiên đăng nhập áp dụng đúng vai trò và lưu nhật ký thao tác.</p>
            </div>
            <span class="connection-badge" :class="{ connected: authUser }">{{ authUser ? 'ĐÃ ĐĂNG NHẬP' : 'CẦN ĐĂNG NHẬP' }}</span>
          </div>
          <form v-if="!authUser" class="team-form" @submit.prevent="login">
            <input v-model="loginForm.email" required type="email" maxlength="255" autocomplete="username" placeholder="admin@gmail.com" />
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

        <div v-if="authUser" class="settings-card workspace-config-card">
          <div class="settings-card-header">
            <div><span class="card-eyebrow">CÀI ĐẶT SHOP</span><h2>Loại hình kinh doanh &amp; tính năng</h2><p>Các chức năng chính dùng chung cho mọi loại hình. Có thể bật thêm công cụ phù hợp; khi tắt, công cụ bị ẩn nhưng dữ liệu vẫn được giữ.</p></div>
            <button type="button" class="settings-refresh" :disabled="workspaceConfigLoading" @click="fetchWorkspaceConfig">{{ workspaceConfigLoading ? 'Đang tải...' : 'Làm mới' }}</button>
          </div>
          <div v-if="workspaceConfigError" class="settings-notice team-error" role="alert">{{ $t(workspaceConfigError) }}</div>
          <div class="workspace-profile-grid" role="radiogroup" aria-label="Mô hình kinh doanh">
            <label v-for="profile in [
              { id: 'retail', name: 'Bán lẻ', desc: 'Sản phẩm, đơn bán và tồn kho.' },
              { id: 'services', name: 'Dịch vụ theo lịch', desc: 'Khách hàng, cuộc trò chuyện, công việc và chăm sóc.' },
              { id: 'b2b', name: 'Dự án / Khách doanh nghiệp', desc: 'Doanh nghiệp, khách tiềm năng và quy trình bán hàng.' },
              { id: 'mixed', name: 'Đa dịch vụ', desc: 'Kết hợp nhiều mô hình trong cùng shop.' },
            ]" :key="profile.id" class="workspace-profile-option" :class="{ selected: workspaceConfig.business_type === profile.id }">
              <input v-model="workspaceConfig.business_type" type="radio" name="workspace-business-type" :value="profile.id" :disabled="!canManageWorkspace" />
              <span><strong>{{ $t(profile.name) }}</strong><small>{{ $t(profile.desc) }}</small></span>
            </label>
          </div>
          <div class="workspace-module-row">
            <div><strong>Chức năng chính <span class="connection-badge connected">LUÔN BẬT</span></strong><small>Khách hàng, doanh nghiệp, cuộc trò chuyện, công việc, quy trình bán hàng, phân quyền, tự động hóa và báo cáo.</small></div>
          </div>
          <label class="workspace-module-row workspace-module-toggle" :class="{ disabled: !canManageWorkspace }">
            <input v-model="workspaceConfig.enabled_modules" type="checkbox" value="retail" :disabled="!canManageWorkspace" />
            <span><strong>Bộ bán lẻ</strong><small>Sản phẩm, đơn bán, nhà cung cấp, nhập hàng và tồn kho.</small></span>
            <span class="connection-badge" :class="{ connected: workspaceModuleEnabled('retail') }">{{ workspaceModuleEnabled('retail') ? 'ĐANG BẬT' : 'ĐANG TẮT' }}</span>
          </label>
          <label class="workspace-module-row workspace-module-toggle" :class="{ disabled: !canManageWorkspace }">
            <input v-model="workspaceConfig.enabled_modules" type="checkbox" value="appointments" :disabled="!canManageWorkspace" />
            <span><strong>Dịch vụ theo lịch</strong><small>Danh mục dịch vụ, lịch hẹn, nhân viên phụ trách và nhắc lịch gắn với hồ sơ khách hàng.</small></span>
            <span class="connection-badge" :class="{ connected: workspaceModuleEnabled('appointments') }">{{ workspaceModuleEnabled('appointments') ? 'ĐANG BẬT' : 'ĐANG TẮT' }}</span>
          </label>
          <label class="workspace-module-row workspace-module-toggle" :class="{ disabled: !canManageWorkspace }">
            <input v-model="workspaceConfig.enabled_modules" type="checkbox" value="projects" :disabled="!canManageWorkspace" />
            <span><strong>Báo giá &amp; dự án</strong><small>Báo giá có tính thuế, theo dõi dự án, hóa đơn và thanh toán một phần/toàn phần.</small></span>
            <span class="connection-badge" :class="{ connected: workspaceModuleEnabled('projects') }">{{ workspaceModuleEnabled('projects') ? 'ĐANG BẬT' : 'ĐANG TẮT' }}</span>
          </label>
          <div v-if="workspaceConfigNotice" class="settings-notice" role="status">{{ $t(workspaceConfigNotice) }}</div>
          <button v-if="canManageWorkspace" type="button" class="primary-btn" :disabled="workspaceConfigSaving || workspaceConfigLoading" @click="saveWorkspaceConfig">{{ workspaceConfigSaving ? 'Đang lưu...' : 'Lưu mô hình' }}</button>
          <p v-else class="settings-muted">Chỉ chủ shop hoặc quản trị viên được thay đổi cấu hình này.</p>
        </div>

        <div v-if="authUser" class="settings-card crm-config-card">
          <div class="settings-card-header">
            <div><span class="card-eyebrow">TÙY CHỈNH QUY TRÌNH</span><h2>Thông tin khách hàng &amp; quy trình bán hàng</h2><p>Thiết lập riêng cho shop; không thể xóa bước đang có khách tiềm năng để tránh mất liên kết dữ liệu.</p></div>
            <button type="button" class="settings-refresh" :disabled="crmConfigLoading" @click="fetchCrmConfig">{{ crmConfigLoading ? 'Đang tải...' : 'Làm mới' }}</button>
          </div>
          <div v-if="crmConfigError" class="settings-notice team-error" role="alert">{{ crmConfigError }}</div>
          <div v-if="crmConfigNotice" class="settings-notice" role="status">{{ crmConfigNotice }}</div>
          <div class="crm-config-editor-grid">
            <section>
              <h3>Trường hồ sơ khách hàng</h3>
              <div v-if="!crmConfig.customer_fields.length" class="settings-empty">Chưa có trường bổ sung.</div>
              <div v-for="(field, index) in crmConfig.customer_fields" :key="field.key" class="crm-config-row">
                <label>Tên<input v-model="field.label" maxlength="80" :disabled="!canManageWorkspace" /></label>
                <label>Mã<input :value="field.key" disabled /></label>
                <label>Kiểu<select v-model="field.type" :disabled="!canManageWorkspace"><option value="text">Văn bản</option><option value="number">Số</option><option value="date">Ngày</option><option value="select">Danh sách</option><option value="boolean">Đúng / sai</option></select></label>
                <label v-if="field.type === 'select'">Lựa chọn<input :value="(field.options || []).join(', ')" :disabled="!canManageWorkspace" placeholder="Mới, Đang chăm sóc, VIP" @input="field.options = $event.target.value.split(',').map(value => value.trim()).filter(Boolean)" /></label>
                <button v-if="canManageWorkspace" type="button" class="team-toggle danger" :aria-label="`Xóa trường ${field.label}`" @click="crmConfig.customer_fields.splice(index, 1)">Xóa</button>
              </div>
              <div v-if="canManageWorkspace" class="crm-config-add-row">
                <input v-model="crmFieldDraft.label" placeholder="Tên trường" maxlength="80" />
                <input v-model="crmFieldDraft.key" placeholder="Mã, ví dụ: loai_khach" maxlength="40" />
                <select v-model="crmFieldDraft.type"><option value="text">Văn bản</option><option value="number">Số</option><option value="date">Ngày</option><option value="select">Danh sách</option><option value="boolean">Đúng / sai</option></select>
                <input v-if="crmFieldDraft.type === 'select'" v-model="crmFieldDraft.options" placeholder="Các lựa chọn, ngăn cách dấu phẩy" />
                <button type="button" class="settings-refresh" @click="addCrmCustomerField">Thêm trường</button>
              </div>
            </section>
            <section>
              <h3>Các giai đoạn cơ hội</h3>
              <div v-for="(stage, index) in crmConfig.pipeline_stages" :key="stage.key" class="crm-config-stage-row">
                <code>{{ stage.key }}</code><input v-model="stage.label" maxlength="60" :disabled="!canManageWorkspace" />
                <button v-if="canManageWorkspace && !['new', 'won', 'lost'].includes(stage.key)" type="button" class="team-toggle danger" :aria-label="`Xóa giai đoạn ${stage.label}`" @click="crmConfig.pipeline_stages.splice(index, 1)">Xóa</button>
                <span v-else class="settings-muted">Bắt buộc</span>
              </div>
              <div v-if="canManageWorkspace" class="crm-config-add-row"><input v-model="crmStageDraft" placeholder="Tên giai đoạn mới" maxlength="60" @keydown.enter.prevent="addCrmPipelineStage" /><button type="button" class="settings-refresh" :disabled="crmConfig.pipeline_stages.length >= 20" @click="addCrmPipelineStage">Thêm giai đoạn</button></div>
            </section>
          </div>
          <button v-if="canManageWorkspace" type="button" class="primary-btn" :disabled="crmConfigSaving || crmConfigLoading" @click="saveCrmConfig">{{ crmConfigSaving ? 'Đang lưu...' : 'Lưu cấu hình' }}</button>
          <p v-else class="settings-muted">Chỉ chủ shop hoặc quản trị viên được thay đổi cấu hình.</p>
        </div>

        <div v-if="authUser" class="settings-card business-profile-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">THÔNG TIN SHOP</span><h2>Tên, logo &amp; lời chào</h2><p>Những thông tin này được dùng khi trợ lý giới thiệu shop với khách.</p></div></div>
          <div class="business-profile-grid">
            <label>Tên doanh nghiệp<input v-model="businessProfile.name" maxlength="160" placeholder="Tên shop" /></label>
            <div class="business-logo-field">
              <span>Logo shop</span>
              <div class="business-logo-picker">
                <div v-if="businessProfile.logo_url" class="business-logo-preview">
                  <img :src="businessProfile.logo_url" alt="Logo shop" />
                  <button type="button" class="business-logo-remove" @click="removeBusinessLogo">Gỡ ảnh</button>
                </div>
                <label class="business-logo-select">
                  <span>{{ businessProfile.logo_url ? 'Đổi ảnh' : 'Chọn ảnh từ thiết bị' }}</span>
                  <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" @change="handleBusinessLogoChange" />
                </label>
              </div>
              <small class="field-hint">PNG, JPG, WEBP hoặc GIF · tối đa 5 MB</small>
            </div>
            <label class="business-profile-wide">Mô tả shop<textarea v-model="businessProfile.description" rows="3" maxlength="1000" placeholder="Shop bán gì, điểm nổi bật..." /></label>
            <label class="business-profile-wide">Tin nhắn chào mừng<textarea v-model="businessProfile.welcome_message" rows="3" maxlength="1000" placeholder="Xin chào, shop có thể giúp gì cho bạn?" /></label>
            <label>Giọng văn<select v-model="businessProfile.tone"><option>Thân thiện</option><option>Ngắn gọn</option><option>Chuyên nghiệp</option></select></label>
            <label>Ngôn ngữ<select v-model="businessProfile.language"><option>Tiếng Việt</option><option>Tiếng Anh</option><option>Song ngữ</option></select></label>
          </div>
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
                <span><strong>{{ session.device_label || 'Thiết bị không đặt tên' }}</strong><small>Tạo {{ session.created_at ? new Date(session.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '—' }} · {{ session.mfa_verified ? 'Đã xác minh 2 bước' : 'Chưa xác minh 2 bước' }}</small></span>
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
              <div><strong>{{ followupProductLabel(item) }}</strong><small>{{ new Date(item.run_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}</small></div>
              <span>{{ item.message }}<small v-if="followupRecommendationLabel(item)" class="followup-recommendation">Gợi ý mua thêm: {{ followupRecommendationLabel(item) }}</small></span>
              <button type="button" class="history-btn" @click="cancelFollowup(item)">Hủy</button>
            </li>
          </ul>
        </div>

        <div v-if="authUser" class="settings-card learning-card">
          <div class="settings-card-header"><div><span class="card-eyebrow">DỮ LIỆU CẢI THIỆN TRỢ LÝ</span><h2>Thu thập mẫu và phản hồi</h2><p>Lưu những tín hiệu shop đã chọn để theo dõi chất lượng và chuẩn bị dữ liệu đánh giá.</p></div><span class="connection-badge">CHƯA TỰ HỌC</span></div>
          <div class="learning-options"><label class="checkbox-field"><input v-model="messageLearningEnabled" type="checkbox" /> Cho phép lưu tin nhắn đã chọn làm mẫu tham khảo</label><label class="checkbox-field"><input v-model="reinforcementLearningEnabled" type="checkbox" /> Cho phép ghi nhận đánh giá hữu ích / cần cải thiện</label></div>
          <p class="settings-muted">Các lựa chọn này được lưu trên thiết bị hiện tại. Phản hồi chỉ dùng để thống kê và chưa tự thay đổi câu trả lời của trợ lý. Dữ liệu trên máy chủ vẫn tách riêng theo từng shop.</p><div v-if="learningNotice" class="settings-notice" role="status">{{ learningNotice }}</div><button type="button" class="primary-btn" @click="saveLearningPreferences">Lưu tùy chọn trên thiết bị</button>
          <div class="learning-insights">
            <div class="settings-card-header"><div><h3>Chủ đề khách thường hỏi</h3><p>Tổng hợp 30 ngày gần nhất theo các nhóm quy tắc có sẵn để gợi ý nội dung cần bổ sung. Đây chưa phải học không giám sát hoàn chỉnh.</p></div><button type="button" class="settings-refresh" :disabled="learningSummaryLoading" @click="fetchLearningSummary">{{ learningSummaryLoading ? 'Đang tổng hợp...' : 'Làm mới' }}</button></div>
            <div v-if="learningSummaryError" class="settings-notice team-error" role="alert">{{ learningSummaryError }}</div>
            <div v-if="learningSummary.topics?.length" class="learning-topic-grid">
              <div v-for="topic in learningSummary.topics.slice(0, 4)" :key="topic.key" class="learning-topic">
                <strong>{{ topic.label }}</strong><span>{{ topic.message_count }} tin · {{ topic.conversation_count }} hội thoại</span><small v-if="topic.examples?.[0]">“{{ topic.examples[0] }}”</small>
              </div>
            </div>
            <div v-else-if="!learningSummaryLoading" class="settings-empty">Chưa có đủ hội thoại để tổng hợp chủ đề.</div>
            <p class="settings-muted learning-signal-summary">Phản hồi câu trả lời: {{ learningSummary.response_feedback?.positive || 0 }} hữu ích · {{ learningSummary.response_feedback?.negative || 0 }} cần cải thiện · {{ Math.round(Number(learningSummary.response_feedback?.positive_rate || 0) * 100) }}% tích cực.</p>
            <small class="learning-method-note">Số liệu dùng để quản trị viên đánh giá chất lượng; chưa được dùng để tự huấn luyện hoặc tự điều chỉnh trợ lý.</small>
          </div>
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
            <div><strong>{{ Math.round(csatSummary.bot_resolution_rate * 100) }}%</strong><span>Khảo sát gửi khi bot đang bật</span></div>
          </div>
          <div v-if="!csatLoading && !csatFeedback.length" class="settings-empty">Chưa có phản hồi đánh giá.</div>
          <ul v-else class="csat-feedback-list">
            <li v-for="item in csatFeedback.slice(0, 5)" :key="item.id">
              <div><strong>{{ item.rating ? `${item.rating}/5 sao` : 'Chờ đánh giá' }}</strong><small>{{ new Date(item.requested_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') }}</small></div>
              <span>{{ item.comment || (item.status === 'sent' ? 'Đã gửi khảo sát, đang chờ khách trả lời.' : 'Đang chờ gửi khảo sát.') }}</span>
            </li>
          </ul>
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
          <div v-if="teamNotice" class="settings-notice" role="status">{{ teamNotice }}</div>

          <form class="team-form" @submit.prevent="saveTeamMember">
            <input v-model="teamForm.full_name" @input="invalidateTeamOtp" required maxlength="255" placeholder="Họ và tên" />
            <div class="team-email-field">
              <input v-model="teamForm.email" @input="invalidateTeamOtp" required type="email" maxlength="255" autocomplete="email" placeholder="Email công việc" />
              <button type="button" class="team-otp-button" :disabled="teamOtpSending" @click="requestTeamOtp">
                {{ teamOtpSending ? 'Đang gửi...' : teamOtpSent ? 'Gửi lại OTP' : 'Gửi mã OTP' }}
              </button>
            </div>
            <input v-model="teamForm.otp" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="Mã OTP 6 số" :disabled="!teamOtpSent" />
            <div class="team-password-field">
              <input v-model="teamForm.password" @input="invalidateTeamOtp" required type="password" minlength="12" maxlength="256" autocomplete="new-password" placeholder="Mật khẩu (≥ 12 ký tự)" />
              <small>Ít nhất 12 ký tự, gồm 3 nhóm: chữ thường, chữ hoa, số, ký tự đặc biệt.</small>
            </div>
            <select v-model="teamForm.role" @change="invalidateTeamOtp" aria-label="Vai trò nhân viên">
              <option value="admin">Quản trị viên</option>
              <option value="agent">Nhân viên</option>
              <option value="viewer">Chỉ xem</option>
            </select>
            <button class="primary-btn" type="submit" :disabled="teamSaving">
              {{ teamSaving ? 'Đang xác minh...' : 'Thêm nhân viên' }}
            </button>
          </form>

          <div v-if="teamLoading" class="settings-empty">Đang tải đội ngũ...</div>
          <div v-else-if="!teamUsers.length" class="settings-empty">Chưa có nhân viên nào.</div>
          <div v-else class="team-table-wrap">
            <table class="team-table">
              <thead><tr><th>Nhân viên</th><th>Vai trò</th><th>Trạng thái</th><th class="team-actions-heading">Thao tác</th></tr></thead>
              <tbody>
                <tr v-for="member in teamUsers" :key="member.id">
                  <td><strong>{{ member.full_name }}</strong><small>{{ member.email }}</small></td>
                  <td><span class="team-role">{{ roleLabel(member.role) }}</span></td>
                  <td><span class="team-status" :class="{ inactive: !member.is_active }">{{ member.is_active ? 'Đang hoạt động' : 'Đã vô hiệu hóa' }}</span></td>
                  <td class="team-actions">
                    <button type="button" class="team-toggle" @click="toggleTeamMember(member)">{{ member.is_active ? 'Vô hiệu hóa' : 'Kích hoạt' }}</button>
                    <button v-if="member.role !== 'owner'" type="button" class="team-toggle team-delete" :disabled="teamDeletingId === member.id" @click="deleteTeamMember(member)">{{ teamDeletingId === member.id ? 'Đang xóa...' : 'Xóa tài khoản' }}</button>
                  </td>
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
              <li v-for="log in auditLogs.slice(0, 10)" :key="log.id"><strong>{{ log.action }}</strong> · {{ resourceLabel(log.resource_type) }} {{ log.resource_id ? `#${log.resource_id}` : '' }} · {{ log.created_at ? new Date(log.created_at).toLocaleString(uiLocale.value === 'en' ? 'en-US' : 'vi-VN') : '' }}</li>
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
              <h2>{{ servicePurchaseStatus === 'pending' ? 'Yêu cầu đang chờ quản trị viên duyệt' : 'Gói Demo đã được kích hoạt' }}</h2>
              <p v-if="servicePurchaseStatus === 'pending'">Mã yêu cầu <strong>{{ serviceRequestReference }}</strong>. Khi admin duyệt, hệ thống tự chuẩn bị không gian dữ liệu và mở các màn hình CRM cho shop.</p>
              <p v-else>Mã yêu cầu <strong>{{ serviceRequestReference }}</strong>. Hệ thống đang kiểm tra không gian dữ liệu để mở CRM cho shop.</p>
              <div class="service-success-actions">
                <button v-if="servicePurchaseStatus === 'active'" type="button" class="secondary-btn" @click="refreshTenantProvisioning">Kiểm tra &amp; mở CRM</button>
                <button v-else type="button" class="secondary-btn" @click="fetchServiceAccountSummary">Làm mới trạng thái</button>
                <button type="button" class="history-btn" @click="resetServiceRequestForm">Chọn gói khác</button>
              </div>
            </div>
            <form v-else class="service-request-form" @submit.prevent="submitServiceRequest">
              <div class="service-request-heading"><div><span class="service-page-kicker">CHỌN GÓI</span><h2>{{ serviceMode === 'chatbot' ? 'Thuê riêng trợ lý chatbot' : 'Mua gói dịch vụ cho shop' }}</h2></div><span class="service-request-badge">{{ servicePlanCodeForPurchase(serviceRequestForm.plan_code) === 'demo' ? 'Dùng thử ngay' : 'Admin duyệt' }}</span></div>
              <p class="service-request-intro">{{ serviceMode === 'chatbot' ? 'Thuê riêng trợ lý AI theo mức hỗ trợ. Dịch vụ này độc lập với gói CRM và không làm thay đổi hạn mức kênh.' : `Gói đã chọn cho phép kết nối tối đa ${serviceChannelLimit} nền tảng. Việc kết nối thực tế được thực hiện duy nhất tại mục Kết nối mạng xã hội.` }}</p>
              <div v-if="serviceRequestError" class="service-request-error" role="alert">{{ serviceRequestError }}</div>
              <div class="service-request-fields">
                <label>Người liên hệ<input v-model="serviceRequestForm.contact_name" required maxlength="120" placeholder="Nguyễn Văn A" /></label>
                <label>Email nhận tư vấn<input v-model="serviceRequestForm.email" required type="email" maxlength="255" placeholder="banhang@shop.vn" /></label>
                <label>Số điện thoại <span>(không bắt buộc)</span><input v-model="serviceRequestForm.phone" type="tel" maxlength="30" placeholder="0901 234 567" /></label>
                <label>Tên shop<input v-model="serviceRequestForm.shop_name" required maxlength="160" placeholder="Shop của bạn" /></label>
              </div>
              <fieldset class="service-plan-picker"><legend>{{ serviceMode === 'chatbot' ? 'Chọn mức hỗ trợ' : 'Chọn gói quản lý shop' }}</legend><div class="service-plan-options"><label v-for="plan in activeServicePlans" :key="plan.code" class="service-plan-option" :class="{ selected: serviceRequestForm.plan_code === plan.code }"><input :checked="serviceRequestForm.plan_code === plan.code" type="radio" name="service-plan" :value="plan.code" @change="selectServicePlan(plan.code)" /><span><strong>{{ $t(plan.name) }}</strong><small>{{ $t(plan.description) }}</small><small v-if="serviceMode !== 'chatbot'">{{ plan.max_channels }} nền tảng kết nối</small><small v-else>Thuê riêng, không trừ hạn mức kênh CRM</small><em>{{ plan.price }}</em></span></label></div></fieldset>
              <div v-if="authUser" class="service-purchase-box">
                <div v-if="servicePlanCodeForPurchase(serviceRequestForm.plan_code) === 'demo'"><strong>Gói Demo được mở ngay</strong><small>Sau khi gửi đăng ký, shop có thể dùng thử ngay khi không gian dữ liệu sẵn sàng.</small></div>
                <div v-else><strong>Gói trả phí cần admin xác nhận</strong><small>Yêu cầu được chuyển vào hàng chờ duyệt. CRM chỉ mở sau khi admin duyệt và hệ thống chuẩn bị xong dữ liệu riêng.</small></div>
              </div>
              <div v-if="servicePurchaseError" class="service-request-error" role="alert">{{ servicePurchaseError }}</div>
              <div v-if="servicePurchaseNotice" class="service-purchase-notice" role="status">
                <span>{{ servicePurchaseNotice }}</span>
                <div v-if="servicePurchaseStatus === 'active'" class="service-purchase-actions">
                  <button type="button" class="secondary-btn" @click="openChannels">Mở kết nối kênh</button>
                  <button type="button" class="history-btn" @click="openSettings">Quản lý nhân viên</button>
                </div>
              </div>
              <div v-if="serviceMode === 'package'" class="service-channel-summary"><strong>Hạn mức nền tảng: {{ serviceChannelLimit }}</strong><span>Không chọn nền tảng tại đây để tránh lệch dữ liệu. Sau khi gói được duyệt, vào <b>Kết nối mạng xã hội</b> để kết nối đúng các nền tảng shop đang dùng.</span></div>
              <div v-else class="service-channel-summary chatbot-service-summary"><strong>Trợ lý AI là dịch vụ thuê riêng</strong><span>Trợ lý không chiếm số kênh của gói CRM. Shop vẫn kết nối Facebook, Instagram, Telegram, Zalo, TikTok và Shopee theo gói CRM đang dùng.</span></div>
              <p v-if="authUser" class="service-upgrade-note">Nâng cấp không cần hủy gói hiện tại: gói cũ vẫn hoạt động trong khi yêu cầu chờ duyệt; khi duyệt, hệ thống thay thế bằng gói mới.</p>
              <label class="service-request-notes">Ghi chú thêm <span>(không bắt buộc)</span><textarea v-model="serviceRequestForm.notes" rows="3" maxlength="1000" placeholder="Ví dụ: shop cần bot trả lời ngoài giờ hoặc hỗ trợ nhiều nhân viên..."></textarea></label>
              <button type="submit" class="primary-btn service-submit" :disabled="servicePurchaseLoading">{{ servicePurchaseLoading ? 'Đang gửi yêu cầu...' : servicePlanCodeForPurchase(serviceRequestForm.plan_code) === 'demo' ? 'Kích hoạt gói Demo' : serviceMode === 'chatbot' ? 'Gửi yêu cầu thuê trợ lý' : 'Gửi yêu cầu thuê gói' }} <span aria-hidden="true">→</span></button>
              <small class="service-form-footnote">Gói trả phí chỉ được mở sau khi quản trị viên nền tảng xác nhận yêu cầu.</small>
            </form>
          </article>
        </div>
      </section>


    </main>

    <section v-else-if="sessionBootstrapLoading" class="session-bootstrap" role="status" aria-live="polite">
      <div class="session-bootstrap-card">
        <div class="platform-workspace-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 6.5h16v13H4z" /><path d="M8 6.5V4h8v2.5M8 11h8M8 15h5" /><circle cx="17" cy="16" r="2.5" /></svg>
        </div>
        <strong>Smart Merchant Hub</strong>
        <span>Đang mở đúng không gian làm việc...</span>
      </div>
    </section>

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
            <div><strong>Smart Merchant Hub</strong><span>{{ t('Không gian quản lý shop') }}</span></div>
          </div>
          <span class="login-eyebrow">{{ t('CỔNG VẬN HÀNH SHOP') }}</span>
          <h1>{{ t('Chăm khách gọn hơn,') }}<br /><em>{{ t('bán hàng chắc hơn.') }}</em></h1>
          <p class="login-showcase-copy">{{ t('Một nơi để đội ngũ xử lý hội thoại, đơn bán và các công việc cần người thật — rõ ràng theo từng shop.') }}</p>
          <div class="login-feature-list">
            <div><span class="login-feature-icon">✓</span><span><strong>{{ t('Hộp thư hợp nhất') }}</strong><small>{{ t('Không bỏ sót khách từ mọi kênh.') }}</small></span></div>
            <div><span class="login-feature-icon">✓</span><span><strong>{{ t('Quy trình có kiểm soát') }}</strong><small>{{ t('Trạng thái, thời hạn và nhật ký rõ ràng.') }}</small></span></div>
            <div><span class="login-feature-icon">✓</span><span><strong>{{ t('Dữ liệu riêng từng shop') }}</strong><small>{{ t('Phân quyền theo không gian của bạn.') }}</small></span></div>
          </div>
        </div>

        <div v-if="authView === 'login'" class="login-card">
          <div class="login-card-topline">
            <span class="login-card-kicker">{{ t('CHÀO MỪNG TRỞ LẠI') }}</span>
            <span class="login-security-pill"><i></i> {{ t('Kết nối bảo mật') }}</span>
            <label class="ui-language-control">
              <span class="visually-hidden">{{ t('Ngôn ngữ giao diện') }}</span>
              <select :value="uiLocale" :aria-label="t('Ngôn ngữ giao diện')" @change="setUiLocale($event.target.value)">
                <option value="vi">Tiếng Việt</option><option value="en">English</option>
              </select>
            </label>
          </div>
          <div class="login-card-heading">
            <h2>{{ t('Đăng nhập CRM') }}</h2>
            <p>{{ t('Sử dụng tài khoản đã được cấp để tiếp tục xử lý không gian của shop.') }}</p>
          </div>
          <form class="login-form" @submit.prevent="login">
            <label>{{ t('Email đăng nhập') }}<input v-model="loginForm.email" required type="email" maxlength="255" autocomplete="username" placeholder="admin@gmail.com" /></label>
            <label>{{ t('Mật khẩu') }}<input v-model="loginForm.password" required type="password" autocomplete="current-password" :placeholder="t('Nhập mật khẩu')" /></label>
            <label>{{ t('Mã shop') }} <span>{{ t('(không bắt buộc)') }}</span><input v-model="loginForm.shop_slug" type="text" maxlength="120" autocomplete="organization" placeholder="shop-cua-ban" /></label>
            <button class="login-submit" type="submit" :disabled="authLoading || authRateLimitSeconds > 0">
              <span>{{ t(authLoading ? 'Đang xác thực...' : authRateLimitSeconds > 0 ? 'Tạm khóa đăng nhập' : 'Đăng nhập') }}</span>
              <span class="login-submit-arrow" aria-hidden="true">→</span>
            </button>
          </form>
          <div v-if="authError" class="login-alert" role="alert">{{ authError }}</div>
          <div v-if="authRateLimitSeconds > 0" class="login-rate-limit" role="status">
            <span class="login-rate-limit-icon" aria-hidden="true">⏱</span>
            <span>{{ t('Quá nhiều lần thử. Thử lại sau') }} <strong>{{ formatRateLimitDuration(authRateLimitSeconds) }}</strong>.</span>
          </div>
          <small class="login-footer-note">{{ t('Phiên làm việc được ghi lại đầy đủ và áp dụng đúng quyền của bạn.') }}</small>
          <button type="button" class="login-service-link" @click="openPublicServicePage">{{ t('Xem gói dịch vụ và thuê chatbot →') }}</button>
          <button type="button" class="login-service-link" @click="openSignup">{{ t('Đăng ký shop mới →') }}</button>
        </div>

        <div v-else class="login-card signup-card">
          <div class="login-card-topline">
            <span class="login-card-kicker">{{ t('BẮT ĐẦU VỚI SHOP CỦA BẠN') }}</span>
            <span class="login-security-pill"><i></i> {{ t('Xác minh email') }}</span>
            <label class="ui-language-control">
              <span class="visually-hidden">{{ t('Ngôn ngữ giao diện') }}</span>
              <select :value="uiLocale" :aria-label="t('Ngôn ngữ giao diện')" @change="setUiLocale($event.target.value)">
                <option value="vi">Tiếng Việt</option><option value="en">English</option>
              </select>
            </label>
          </div>
          <div class="login-card-heading">
            <h2>{{ t('Tạo không gian shop') }}</h2>
            <p>{{ t('Nhập email công việc để nhận mã OTP. Shop chỉ được tạo sau khi xác minh thành công.') }}</p>
          </div>
          <ol class="signup-stepper" :aria-label="t('Tiến trình tạo shop')">
            <li :class="{ active: signupStep === 'details', complete: signupStep === 'otp' }"><span>1</span><div><strong>{{ t('Thông tin shop') }}</strong><small>{{ t('Người đại diện, email và mật khẩu') }}</small></div></li>
            <li :class="{ active: signupStep === 'otp' }"><span>2</span><div><strong>{{ t('Xác minh OTP') }}</strong><small>{{ t('Xác nhận email công việc') }}</small></div></li>
            <li><span>3</span><div><strong>{{ t('Chọn gói') }}</strong><small>{{ t('Chọn dịch vụ sau khi shop được tạo') }}</small></div></li>
          </ol>
          <form class="login-form" @submit.prevent="handleSignupSubmit">
            <label>{{ t('Người đại diện') }}<input v-model="signupForm.owner_name" @input="invalidateSignupOtp" required minlength="2" maxlength="255" autocomplete="name" placeholder="Nguyễn Văn A" /></label>
            <label>{{ t('Email công việc') }}
              <div class="signup-email-control">
                <input v-model="signupForm.email" @input="invalidateSignupOtp" required type="email" maxlength="255" autocomplete="email" placeholder="banhang@shop.vn" />
                <button class="signup-otp-button" type="button" :disabled="signupLoading" @click="requestSignupOtp">{{ t(signupStep === 'otp' ? 'Gửi lại OTP' : 'Gửi mã OTP') }}</button>
              </div>
            </label>
            <div v-if="signupStep === 'otp'" class="signup-otp-note">{{ t('Mã xác minh đã gửi tới') }} <strong>{{ signupForm.email }}</strong>. {{ t('Kiểm tra cả mục Spam nếu chưa thấy email.') }}</div>
            <label>{{ t('Mã OTP') }}
              <input v-model="signupForm.otp" class="signup-otp-input" :disabled="signupStep !== 'otp'" :required="signupStep === 'otp'" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="Nhập mã OTP 6 số" />
            </label>
            <label>{{ t('Tên shop') }}<input v-model="signupForm.shop_name" @input="invalidateSignupOtp" required minlength="2" maxlength="255" autocomplete="organization" :placeholder="t('Shop của bạn')" /></label>
            <label>{{ t('Mật khẩu') }}<input v-model="signupForm.password" @input="invalidateSignupOtp" required minlength="12" type="password" autocomplete="new-password" :placeholder="t('Tối thiểu 12 ký tự, gồm 3 nhóm ký tự')" /><small class="signup-password-hint">{{ t('Dùng ít nhất 3 nhóm: chữ thường, chữ hoa, số, ký tự đặc biệt.') }}</small></label>
            <button class="login-submit" type="submit" :disabled="signupLoading"><span>{{ t(signupLoading ? (signupStep === 'otp' ? 'Đang tạo shop...' : 'Đang gửi mã...') : (signupStep === 'otp' ? 'Xác minh và đăng ký' : 'Đăng ký')) }}</span><span class="login-submit-arrow" aria-hidden="true">→</span></button>
          </form>
          <div v-if="signupError" class="login-alert" role="alert">{{ signupError }}</div>
          <div v-if="signupNotice" class="login-notice" role="status">{{ signupNotice }}</div>
          <small class="login-footer-note">{{ t('Sau khi tạo, shop bắt đầu với Gói Demo 0 đồng. Gói Demo chưa mở kết nối mạng xã hội.') }}</small>
          <button type="button" class="login-service-link" @click="openLogin">{{ t('← Quay lại đăng nhập') }}</button>
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

.ui-language-control { display: inline-flex; align-items: center; flex: 0 0 auto; }
.ui-language-control select {
  min-height: 34px;
  padding: 0 8px;
  color: var(--leader-sidebar-ink, #263746);
  background: var(--leader-sidebar-surface, #fff);
  border: 1px solid var(--leader-sidebar-border, #d5e1ec);
  border-radius: 9px;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}
.ui-language-control select:focus-visible { outline: 2px solid var(--leader-sidebar-accent, #137d82); outline-offset: 2px; }

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

.bot-response-feedback {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  color: #71809a;
  font-size: 10px;
}

.bot-response-feedback button {
  padding: 3px 7px;
  border: 1px solid #b9dfe0;
  border-radius: 999px;
  color: #147d82;
  background: #f2fbfb;
  cursor: pointer;
  font-size: 10px;
  font-weight: 700;
}

.bot-response-feedback button:hover { background: #def4f4; }
.bot-response-feedback-done { color: #147d82; font-weight: 700; }

.learning-insights {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--owly-border, #e4e8ed);
}

.learning-topic-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.learning-topic {
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--owly-border, #e4e8ed);
  border-radius: 10px;
  background: rgba(255, 255, 255, .45);
}

.learning-topic strong { color: var(--owly-ink, #17315c); font-size: 12px; }
.learning-topic span, .learning-topic small, .learning-method-note { color: var(--owly-muted, #71809a); font-size: 11px; }
.learning-topic small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.learning-signal-summary { margin: 10px 0 3px; }

@media (max-width: 720px) {
  .learning-topic-grid { grid-template-columns: 1fr; }
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
.doc-embedding-state { display: block; margin-top: 4px; color: #71809a; font-size: 11px; line-height: 1.35; }
.doc-error-detail { color: #b42318; }
.doc-progress { display: block; width: min(220px, 100%); height: 8px; margin-top: 7px; accent-color: #3182ce; }
.btn-refresh:disabled { cursor: wait; opacity: 0.65; }

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

.team-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.team-toggle.team-delete {
  color: #a1261d;
  background: #ffe1dc;
}

.team-toggle:disabled {
  cursor: wait;
  opacity: 0.65;
}

.team-form {
  display: grid;
  grid-template-columns: 1.05fr 1.45fr 0.8fr 1.55fr 0.85fr auto;
  gap: 10px;
  margin: 22px 0;
  align-items: start;
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

.team-email-field,
.team-password-field {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.team-email-field {
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px;
}

.team-email-field input {
  min-width: 0;
}

.team-otp-button {
  border: 1px solid #e6aaa0;
  border-radius: 10px;
  padding: 10px 12px;
  color: #8d271d;
  background: #fff0ea;
  cursor: pointer;
  font-weight: 700;
  white-space: nowrap;
}

.team-otp-button:disabled {
  cursor: wait;
  opacity: .65;
}

.team-password-field small {
  color: #9c7470;
  font-size: 11px;
  line-height: 1.35;
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
  .followup-list li,
  .team-form {
    grid-template-columns: 1fr;
  }

  .team-email-field {
    grid-template-columns: minmax(0, 1fr) auto;
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
.channel-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; width: min(100%, 1120px); margin-inline: auto; }
.channel-summary-card { width: 100%; max-width: none !important; margin: 0 !important; box-sizing: border-box; }
.channel-summary-card + .channel-summary-card { margin-top: 0 !important; }
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
.workspace-profile-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.crm-config-editor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin: 14px 0; }
.crm-config-editor-grid section { min-width: 0; padding: 14px; border: 1px solid var(--owly-border); border-radius: 12px; }
.crm-config-editor-grid h3 { margin: 0 0 12px; }
.crm-config-row, .crm-config-add-row, .crm-config-stage-row { display: flex; align-items: end; gap: 8px; margin: 8px 0; }
.crm-config-row label { display: grid; flex: 1 1 120px; gap: 5px; min-width: 80px; font-size: .82rem; }
.crm-config-row input, .crm-config-row select, .crm-config-add-row input, .crm-config-add-row select, .crm-config-stage-row input { width: 100%; min-width: 0; border: 1px solid var(--owly-border); border-radius: 8px; padding: 8px; background: var(--owly-surface); color: var(--owly-ink); }
.crm-config-add-row { flex-wrap: wrap; }
.crm-config-add-row > input, .crm-config-add-row > select { flex: 1 1 140px; }
.crm-config-stage-row code { flex: 0 0 110px; color: var(--owly-muted); }
.crm-config-stage-row input { flex: 1; }
.customer-custom-fields-grid { gap: 10px; }
.customer-custom-field { display: grid; gap: 5px; min-width: 0; }
.customer-custom-field input:not([type="checkbox"]), .customer-custom-field select, .customer-custom-field textarea { width: 100%; min-width: 0; border: 1px solid var(--owly-border); border-radius: 8px; padding: 8px; background: var(--owly-surface); color: var(--owly-ink); }
.customer-custom-field input[type="checkbox"] { justify-self: start; accent-color: var(--salon-accent); }
.workspace-profile-option, .workspace-module-row { display: flex; align-items: flex-start; gap: 10px; padding: 12px; border: 1px solid var(--owly-border); border-radius: 10px; background: var(--owly-surface); }
.workspace-profile-option { cursor: pointer; }
.workspace-profile-option.selected { border-color: var(--salon-accent); background: var(--salon-accent-soft); }
.workspace-profile-option input, .workspace-module-toggle input { flex: 0 0 auto; margin-top: 3px; accent-color: var(--salon-accent); }
.workspace-profile-option span, .workspace-module-row > div, .workspace-module-toggle > span:nth-child(2) { display: grid; gap: 4px; min-width: 0; }
.workspace-profile-option small, .workspace-module-row small { color: var(--owly-muted); font-size: .84rem; line-height: 1.4; }
.workspace-module-row { align-items: center; justify-content: space-between; margin: 8px 0; }
.workspace-module-toggle { cursor: pointer; }
.workspace-module-row .connection-badge { flex: 0 0 auto; margin-left: auto; }
.workspace-config-card > .primary-btn { min-width: 170px; }
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
.tiktok-bridge-secret { display: grid; gap: 7px; }
.tiktok-bridge-secret code { overflow-wrap: anywhere; }
.tiktok-bridge-secret pre { margin: 4px 0 0; padding: 10px; border-radius: 8px; overflow: auto; background: rgba(0,0,0,.08); font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }
.channel-summary-grid { align-items: stretch; }
.channels-layout > .channel-page-header,
.channels-layout > .channel-summary-grid {
  width: 100%;
  max-width: none;
  margin-inline: 0;
}
.channel-summary-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.channel-summary-card { display: flex; flex-direction: column; min-height: 226px; padding: 22px 24px; }
.channel-summary-card .settings-card-header { align-items: center; gap: 12px; min-height: 62px; margin-bottom: 12px; }
.channel-summary-card .settings-card-header > div { min-width: 0; }
.channel-summary-card .settings-card-header h2 { font-size: 1.22rem; line-height: 1.2; }
.channel-summary-card .settings-card-header p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-height: 1.45; }
.channel-summary-card .connection-badge { flex: 0 0 auto; white-space: nowrap; }
.channel-summary-card .settings-muted { flex: 1; min-height: 52px; line-height: 1.5; }
.channel-summary-card-planned { border-style: dashed; }
.channel-summary-card-planned .secondary-btn:disabled { cursor: not-allowed; opacity: .68; }
.shopee-channel-icon { background: #ee4d2d !important; color: #fff !important; font-size: .95rem; }
.channel-status-planned { color: #995b00 !important; background: #fff1cc !important; }
.channel-summary-actions { display: block; margin-top: auto; }
.channel-summary-actions .primary-btn,
.channel-summary-actions .secondary-btn { width: 100%; max-width: 250px; margin-top: 0; min-height: 42px; }
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
.channel-title-with-logo { display: flex; align-items: center; gap: 8px; }
.channel-summary-card .channel-card-icon { flex: 0 0 34px; }
.facebook-channel-icon { background: #1877f2 !important; color: #fff !important; font-family: Arial, sans-serif; font-size: 1.35rem; line-height: 1; }
.instagram-channel-icon { background: linear-gradient(135deg, #833ab4, #fd1d1d 52%, #fcb045) !important; color: #fff !important; font-size: 1.45rem; line-height: 1; }
.telegram-channel-icon { background: #229ed9 !important; color: #fff !important; font-size: 1.05rem; line-height: 1; transform: rotate(-18deg); }
.zalo-channel-icon { background: #0068ff !important; color: #fff !important; font-size: 1.1rem; line-height: 1; }
.tiktok-logo { display: block; width: 22px; height: 22px; overflow: visible; }
.tiktok-logo path { fill: currentColor; }
.tiktok-logo-cyan { color: #25f4ee; transform: translate(-.7px, .5px); }
.tiktok-logo-red { color: #fe2c55; transform: translate(.7px, -.5px); }
.tiktok-logo-main { color: #fff; }
.tiktok-channel-icon { background: #101114 !important; color: #fff !important; }
.tiktok-channel-icon .tiktok-logo { width: 21px; height: 21px; }
.crm-dark .channel-summary-card .facebook-channel-icon { background: #1877f2 !important; color: #fff !important; }
.crm-dark .channel-summary-card .instagram-channel-icon { background: linear-gradient(135deg, #833ab4, #fd1d1d 52%, #fcb045) !important; color: #fff !important; }
.crm-dark .channel-summary-card .telegram-channel-icon { background: #229ed9 !important; color: #fff !important; }
.crm-dark .channel-summary-card .zalo-channel-icon { background: #0068ff !important; color: #fff !important; }
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
.tiktok-bridge-actions { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; margin-top: 12px; }
.tiktok-bridge-actions button, .tiktok-bridge-actions a { width: 100%; margin-top: 0; }
.tiktok-bridge-actions a { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }
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
.crm-dark .workspace-profile-option, .crm-dark .workspace-module-row { border-color: #414c50; background: #20272a; }
.crm-dark .workspace-profile-option.selected { border-color: #37b4af; background: #173e41; }
.crm-dark .workspace-profile-option small, .crm-dark .workspace-module-row small { color: #b6c0c5; }
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
.crm-dark .team-otp-button { color: #d8ffff !important; background: #173f43 !important; border-color: #3c777a !important; }
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
.crm-dark .channel-status-planned { color: #ffd786 !important; background: #493719 !important; }
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
  .tiktok-bridge-actions { grid-template-columns: 1fr; }
  .business-day-options { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .dark-mode-toggle { width: 38px; height: 38px; }
}

@media (max-width: 1100px) {
  .channel-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* Team management: keep dense controls readable without changing behavior. */
.team-card {
  max-width: 1120px;
  padding: clamp(20px, 2.4vw, 30px);
}
.team-card > .settings-card-header {
  align-items: center;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--owly-border);
}
.team-card > .settings-card-header h2 {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 5px;
}
.team-form {
  grid-template-columns: minmax(140px, 1.05fr) minmax(240px, 1.45fr) minmax(130px, .8fr) minmax(220px, 1.55fr) minmax(130px, .85fr) auto;
  gap: 12px;
  margin: 20px 0 22px;
  padding: 14px;
  border: 1px solid var(--owly-border);
  border-radius: 14px;
  background: var(--owly-surface);
}
.team-form input,
.team-form select {
  min-height: 42px;
  border-color: var(--owly-border);
  border-radius: 10px;
  background: var(--owly-surface);
  color: var(--owly-ink);
}
.team-otp-button {
  min-height: 42px;
  border-color: var(--salon-accent);
  color: #fff;
  background: linear-gradient(135deg, var(--salon-accent), #257c9b);
  box-shadow: 0 6px 14px rgba(37, 124, 155, .16);
}
.team-otp-button:hover:not(:disabled) {
  background: linear-gradient(135deg, #238a8b, #216e8d);
}
.team-password-field small {
  color: var(--owly-muted);
}
.team-table-wrap {
  margin-top: 4px;
  border: 1px solid var(--owly-border);
  border-radius: 15px;
  background: var(--owly-surface);
}
.team-table {
  table-layout: fixed;
}
.team-table th,
.team-table td {
  padding: 14px 12px;
}
.team-table th:first-child { width: 34%; }
.team-table th:nth-child(2) { width: 15%; }
.team-table th:nth-child(3) { width: 20%; }
.team-table th:last-child { width: 31%; text-align: right; }
.team-table td:last-child { text-align: right; }
.team-actions {
  justify-content: flex-end;
  gap: 8px;
}
.team-actions-heading {
  white-space: nowrap;
}
.permission-panel {
  margin-top: 22px;
  padding: 16px 18px 18px;
  border: 1px solid var(--owly-border);
  border-radius: 15px;
  background: var(--owly-surface);
}
.permission-panel .settings-card-header {
  margin-bottom: 0;
  padding-bottom: 2px;
}
.permission-panel .settings-card-header h3 {
  margin-bottom: 3px;
}
.permission-panel .settings-card-header p {
  margin: 0;
  font-size: 13px;
}
.permission-form {
  grid-template-columns: repeat(5, minmax(0, 1fr)) minmax(132px, .9fr);
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--owly-border);
}
.permission-form label {
  min-width: 0;
  gap: 5px;
  font-size: 11px;
}
.permission-form select {
  min-width: 0;
  min-height: 40px;
  border-color: var(--owly-border);
  background: var(--owly-surface);
  color: var(--owly-ink);
}
.permission-form > button {
  width: 100%;
  min-height: 40px;
  padding-inline: 12px;
}
.permission-list {
  gap: 6px;
  margin-top: 12px;
}
.permission-list li {
  border-color: var(--owly-border);
  background: var(--owly-surface);
  padding: 9px 11px;
  align-items: center;
}

@media (max-width: 1050px) {
  .team-form {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .permission-form {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .team-email-field,
  .team-password-field {
    grid-column: span 2;
  }
  .team-form > button {
    min-height: 42px;
  }
}

@media (max-width: 760px) {
  .channel-summary-grid, .business-hours-grid, .sla-rules-grid, .business-profile-grid, .service-plan-grid { grid-template-columns: 1fr; }
  .crm-config-editor-grid { grid-template-columns: 1fr; }
  .crm-config-row, .crm-config-add-row { align-items: stretch; flex-direction: column; }
  .workspace-profile-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .business-profile-wide { grid-column: auto; }
  .team-form,
  .permission-form { grid-template-columns: 1fr; }
  .team-email-field,
  .team-password-field,
  .permission-form > button { grid-column: auto; }
  .team-table { min-width: 680px; }
  .team-table-wrap { overflow-x: auto; }
}

</style>
