<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { apiFetch } from "./api-client.js";
import { formatDateTime, formatMoney, t } from "./i18n.js";
import { channelLabel } from "./channel-utils.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
const PAGE_SIZE = 50;
const ORDER_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 100;
const ORDER_STATUSES = ["draft", "pending_confirmation", "confirmed", "processing", "shipped", "delivered", "completed", "refunded", "cancelled"];

const customers = ref([]);
const total = ref(0);
const query = ref("");
const appliedQuery = ref("");
const channel = ref("");
const selectedId = ref(null);
const profile = ref(null);
const customerOrders = ref([]);
const customerOrderTotal = ref(0);
const orderSummary = ref(null);
const orderStatus = ref("");
const failedAvatarIds = ref(new Set());
const profileAvatarFailed = ref(false);
const loading = ref(false);
const loadingMore = ref(false);
const profileLoading = ref(false);
const ordersLoading = ref(false);
const ordersLoadingMore = ref(false);
const error = ref("");
const profileError = ref("");
const ordersError = ref("");
let listRequestId = 0;
let profileRequestId = 0;
let ordersRequestId = 0;
let searchTimer = null;

const channels = ["facebook", "instagram", "telegram", "zalo", "tiktok", "shopee"];
const hasMore = computed(() => customers.value.length < total.value);
const hasMoreOrders = computed(() => customerOrders.value.length < customerOrderTotal.value);
const customerInitials = computed(() => {
  const name = String(profile.value?.name || "?").trim();
  return name.split(/\s+/).slice(-2).map(part => part.charAt(0)).join("").toUpperCase() || "?";
});

function avatarSrc(value) {
  if (!value) return "";
  try {
    const url = new URL(value, window.location.origin);
    if (!url.pathname.startsWith("/api/customers/")) return value;
    const apiOrigin = new URL(API_BASE, window.location.origin).origin;
    return `${apiOrigin}${url.pathname}${url.search}`;
  } catch {
    return value;
  }
}

function markAvatarFailed(customerId) {
  failedAvatarIds.value.add(customerId);
}

function queryUrl(offset) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (appliedQuery.value) params.set("q", appliedQuery.value);
  if (channel.value) params.set("channel", channel.value);
  return `${API_BASE}/customers?${params.toString()}`;
}

async function loadProfile(customerId) {
  const requestId = ++profileRequestId;
  profileAvatarFailed.value = false;
  if (!customerId) {
    profile.value = null;
    profileLoading.value = false;
    return;
  }
  profileLoading.value = true;
  profileError.value = "";
  try {
    const response = await apiFetch(`${API_BASE}/customers/${encodeURIComponent(customerId)}`);
    if (!response.ok) throw new Error("profile");
    const result = await response.json();
    if (requestId === profileRequestId && selectedId.value === customerId) profile.value = result;
  } catch {
    if (requestId === profileRequestId) {
      profile.value = null;
      profileError.value = t("Không thể tải hồ sơ khách hàng.");
    }
  } finally {
    if (requestId === profileRequestId) profileLoading.value = false;
  }
}

async function loadCustomerOrders(customerId = selectedId.value, { append = false } = {}) {
  const requestId = ++ordersRequestId;
  ordersError.value = "";
  if (!customerId) {
    customerOrders.value = [];
    customerOrderTotal.value = 0;
    orderSummary.value = null;
    ordersLoading.value = false;
    ordersLoadingMore.value = false;
    return;
  }
  if (append) ordersLoadingMore.value = true;
  else {
    ordersLoading.value = true;
    customerOrders.value = [];
    customerOrderTotal.value = 0;
    orderSummary.value = null;
  }
  const params = new URLSearchParams({
    limit: String(ORDER_PAGE_SIZE),
    offset: String(append ? customerOrders.value.length : 0),
  });
  if (orderStatus.value) params.set("status", orderStatus.value);
  try {
    const response = await apiFetch(`${API_BASE}/customers/${encodeURIComponent(customerId)}/orders?${params}`);
    if (!response.ok) {
      const failure = new Error("customer-orders");
      failure.status = response.status;
      throw failure;
    }
    const result = await response.json();
    if (requestId !== ordersRequestId || selectedId.value !== customerId) return;
    customerOrderTotal.value = Number(result.total) || 0;
    customerOrders.value = append
      ? [...customerOrders.value, ...(result.items || [])]
      : (result.items || []);
    orderSummary.value = {
      total_orders: Number(result.total_orders) || 0,
      completed_orders: Number(result.completed_orders) || 0,
      open_orders: Number(result.open_orders) || 0,
      total_spent: Number(result.total_spent) || 0,
      average_order_value: Number(result.average_order_value) || 0,
      total_refunded: Number(result.total_refunded) || 0,
      last_purchase_at: result.last_purchase_at || null,
    };
  } catch (failure) {
    if (requestId !== ordersRequestId || selectedId.value !== customerId) return;
    const status = Number(failure?.status);
    if (status === 401) ordersError.value = t("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại để xem đơn hàng.");
    else if (status === 403) ordersError.value = t("Tài khoản hiện tại không có quyền xem đơn hàng của khách này.");
    else if (status === 404) ordersError.value = t("Máy chủ trả HTTP 404: không tìm thấy khách hàng hoặc API lịch sử đơn hàng chưa được cập nhật.");
    else if (status >= 500) ordersError.value = t("Máy chủ gặp lỗi khi tải lịch sử đơn hàng (HTTP {status}). Kiểm tra API/database rồi thử lại.").replace("{status}", String(status));
    else if (failure instanceof TypeError) ordersError.value = t("Không kết nối được máy chủ để tải lịch sử đơn hàng. Kiểm tra kết nối rồi thử lại.");
    else if (failure instanceof SyntaxError) ordersError.value = t("Máy chủ trả dữ liệu lịch sử đơn hàng sai định dạng. Kiểm tra API rồi thử lại.");
    else ordersError.value = t("Không thể tải lịch sử đơn hàng (HTTP {status}). Hãy thử lại.").replace("{status}", String(status || "?"));
  } finally {
    if (requestId === ordersRequestId) {
      ordersLoading.value = false;
      ordersLoadingMore.value = false;
    }
  }
}

function orderStatusLabel(status) {
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

function paymentStatusLabel(status) {
  const labels = {
    unpaid: "Chưa thanh toán",
    pending: "Đang chờ thanh toán",
    partial: "Thanh toán một phần",
    partially_paid: "Thanh toán một phần",
    paid: "Đã thanh toán",
    refunded: "Đã hoàn tiền",
    failed: "Thanh toán thất bại",
    cancelled: "Đã hủy",
  };
  return t(labels[status] || status || "Chưa rõ");
}

function changeOrderStatus(event) {
  orderStatus.value = event.target.value;
  void loadCustomerOrders();
}

async function loadCustomers({ append = false } = {}) {
  const requestId = ++listRequestId;
  error.value = "";
  if (append) loadingMore.value = true;
  else loading.value = true;
  try {
    const offset = append ? customers.value.length : 0;
    const response = await apiFetch(queryUrl(offset));
    if (!response.ok) throw new Error("customers");
    const result = await response.json();
    if (requestId !== listRequestId) return;
    total.value = Number(result.total) || 0;
    customers.value = append ? [...customers.value, ...(result.items || [])] : (result.items || []);
    if (!customers.value.some(item => item.id === selectedId.value)) {
      selectedId.value = customers.value[0]?.id ?? null;
      orderStatus.value = "";
      void loadProfile(selectedId.value);
      void loadCustomerOrders(selectedId.value);
    }
  } catch {
    if (requestId === listRequestId) error.value = t("Không thể tải danh sách khách hàng.");
  } finally {
    if (requestId === listRequestId) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

function searchCustomers() {
  clearTimeout(searchTimer);
  appliedQuery.value = query.value.trim();
  void loadCustomers();
}

function changeChannel() {
  void loadCustomers();
}

function selectCustomer(customer) {
  selectedId.value = customer.id;
  void loadProfile(customer.id);
  orderStatus.value = "";
  void loadCustomerOrders(customer.id);
}

onMounted(() => void loadCustomers());
onUnmounted(() => clearTimeout(searchTimer));

watch(query, () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    appliedQuery.value = query.value.trim();
    void loadCustomers();
  }, SEARCH_DEBOUNCE_MS);
});
</script>

<template>
  <main class="customer-management" aria-labelledby="customer-page-title">
    <header class="customer-page-header">
      <div>
        <span class="customer-eyebrow">{{ t("HỒ SƠ KHÁCH HÀNG") }}</span>
        <h1 id="customer-page-title">{{ t("Danh sách khách hàng") }}</h1>
        <p>{{ t("Tìm kiếm hồ sơ, thông tin liên hệ và các tài khoản đã liên kết với shop.") }}</p>
      </div>
      <div class="customer-total" aria-live="polite">
        <strong>{{ total.toLocaleString() }}</strong>
        <span>{{ t("Khách hàng") }}</span>
      </div>
    </header>

    <form class="customer-toolbar" role="search" @submit.prevent="searchCustomers">
      <label class="customer-search">
        <span aria-hidden="true">⌕</span>
        <input v-model="query" type="search" :placeholder="t('Tìm theo tên, email, số điện thoại hoặc tài khoản kênh')" />
      </label>
      <label class="customer-channel-filter">
        <span class="sr-only">{{ t("Lọc theo kênh") }}</span>
        <select v-model="channel" @change="changeChannel">
          <option value="">{{ t("Tất cả kênh") }}</option>
          <option v-for="item in channels" :key="item" :value="item">{{ channelLabel(item) }}</option>
        </select>
      </label>
      <button class="customer-action-button customer-search-button" type="submit">{{ t("Tìm kiếm") }}</button>
      <button class="customer-action-button customer-refresh-button" type="button" :disabled="loading" @click="loadCustomers()">
        {{ loading ? t("Đang tải...") : t("Làm mới") }}
      </button>
    </form>

    <p v-if="error" class="customer-alert" role="alert">{{ error }}</p>

    <div class="customer-workspace">
      <section class="customer-list-panel" :aria-label="t('Danh sách khách hàng')">
        <div class="customer-list-heading">
          <strong>{{ t("Khách hàng") }}</strong>
          <span>{{ customers.length }} / {{ total }}</span>
        </div>
        <div v-if="loading && !customers.length" class="customer-state" role="status">{{ t("Đang tải khách hàng...") }}</div>
        <div v-else-if="!customers.length" class="customer-state">
          <strong>{{ t("Chưa có khách hàng phù hợp.") }}</strong>
          <span>{{ t("Thử đổi từ khóa hoặc bộ lọc kênh.") }}</span>
        </div>
        <div v-else class="customer-list" role="listbox" :aria-label="t('Danh sách khách hàng')">
          <button
            v-for="customer in customers"
            :key="customer.id"
            class="customer-row"
            :class="{ selected: selectedId === customer.id }"
            type="button"
            role="option"
            :aria-selected="selectedId === customer.id"
            @click="selectCustomer(customer)"
          >
            <img
              v-if="customer.avatar_url && !failedAvatarIds.has(customer.id)"
              class="customer-avatar-image"
              :src="avatarSrc(customer.avatar_url)"
              :alt="customer.name || t('Ảnh đại diện khách hàng')"
              loading="lazy"
              @error="markAvatarFailed(customer.id)"
            />
            <span v-else class="customer-avatar" aria-hidden="true">{{ String(customer.name || "?").trim().slice(0, 1).toUpperCase() }}</span>
            <span class="customer-row-copy">
              <strong>{{ customer.name || `${t('Khách hàng')} #${customer.id}` }}</strong>
              <span v-if="customer.email || customer.phone">{{ customer.email || customer.phone }}</span>
              <small>{{ channelLabel(customer.channel) }} · {{ customer.conversation_count || 0 }} {{ t("cuộc trò chuyện") }}</small>
            </span>
          </button>
          <button v-if="hasMore" class="customer-load-more" type="button" :disabled="loadingMore" @click="loadCustomers({ append: true })">
            {{ loadingMore ? t("Đang tải...") : t("Tải thêm khách hàng") }}
          </button>
        </div>
      </section>

      <section class="customer-profile-panel" :aria-label="t('Hồ sơ khách hàng')">
        <div v-if="profileLoading" class="customer-state" role="status">{{ t("Đang tải hồ sơ khách hàng...") }}</div>
        <div v-else-if="profileError" class="customer-state customer-state-error" role="alert">{{ profileError }}</div>
        <div v-else-if="!profile" class="customer-state">{{ t("Chọn khách hàng để xem hồ sơ.") }}</div>
        <template v-else>
          <header class="profile-heading">
            <img
              v-if="profile.avatar_url && !profileAvatarFailed"
              class="profile-avatar-image"
              :src="avatarSrc(profile.avatar_url)"
              :alt="profile.name || t('Ảnh đại diện khách hàng')"
              @error="profileAvatarFailed = true"
            />
            <div v-else class="profile-avatar" aria-hidden="true">{{ customerInitials }}</div>
            <div class="profile-title">
              <span class="customer-eyebrow">{{ t("HỒ SƠ 360") }} · #{{ profile.id }}</span>
              <h2>{{ profile.name || `${t('Khách hàng')} #${profile.id}` }}</h2>
              <span class="profile-updated">{{ t("Cập nhật") }} · {{ formatDateTime(profile.updated_at) }}</span>
            </div>
          </header>

          <section class="profile-section">
            <h3>{{ t("Thông tin liên hệ") }}</h3>
            <dl class="profile-contact-grid">
              <div><dt>{{ t("Email") }}</dt><dd>{{ profile.email || "—" }}</dd></div>
              <div><dt>{{ t("Số điện thoại") }}</dt><dd>{{ profile.phone || "—" }}</dd></div>
              <div class="profile-address"><dt>{{ t("Địa chỉ") }}</dt><dd>{{ profile.address || "—" }}</dd></div>
            </dl>
          </section>

          <section class="profile-section profile-orders-section" :aria-busy="ordersLoading || ordersLoadingMore">
            <div class="profile-section-title customer-orders-heading">
              <div>
                <h3>{{ t("Đơn hàng & sản phẩm đã mua") }}</h3>
                <span v-if="ordersLoading && !orderSummary">{{ t("Đang tải...") }}</span>
                <span v-else-if="ordersError && !orderSummary">{{ t("Chưa có số liệu") }}</span>
                <span v-else>{{ customerOrderTotal }} / {{ orderSummary?.total_orders || 0 }} {{ t("đơn hàng") }}</span>
              </div>
              <label class="customer-order-filter">
                <span class="sr-only">{{ t("Lọc theo trạng thái") }}</span>
                <select :value="orderStatus" @change="changeOrderStatus">
                  <option value="">{{ t("Tất cả trạng thái") }}</option>
                  <option v-for="status in ORDER_STATUSES" :key="status" :value="status">{{ orderStatusLabel(status) }}</option>
                </select>
              </label>
            </div>

            <p v-if="ordersLoading && !orderSummary" class="customer-order-loading" role="status">{{ t("Đang tải lịch sử đơn hàng...") }}</p>
            <div v-else-if="ordersError && !orderSummary" class="customer-order-error" role="alert">
              <p>{{ ordersError }}</p>
              <button class="customer-order-retry" type="button" :disabled="ordersLoading" @click="loadCustomerOrders()">
                {{ ordersLoading ? t("Đang tải...") : t("Thử lại") }}
              </button>
            </div>
            <template v-else-if="orderSummary">
              <p v-if="ordersError" class="customer-order-error" role="alert">{{ ordersError }}</p>
              <div class="customer-order-stats">
                <article class="customer-order-spend">
                  <span>{{ t("Tổng tiền đã mua") }}</span>
                  <strong>{{ formatMoney(orderSummary.total_spent) }}</strong>
                  <small>{{ t("Đơn hoàn tất, đã trừ hoàn tiền") }}</small>
                </article>
                <article><span>{{ t("Đơn hoàn tất") }}</span><strong>{{ orderSummary.completed_orders }}</strong></article>
                <article><span>{{ t("Tổng số đơn") }}</span><strong>{{ orderSummary.total_orders }}</strong></article>
                <article><span>{{ t("Giá trị trung bình") }}</span><strong>{{ formatMoney(orderSummary.average_order_value) }}</strong></article>
              </div>
              <div class="customer-order-summary-meta">
                <span>{{ t("Đơn đang xử lý") }} <strong>{{ orderSummary.open_orders }}</strong></span>
                <span>{{ t("Tổng tiền hoàn") }} <strong>{{ formatMoney(orderSummary.total_refunded) }}</strong></span>
                <span>{{ t("Lần mua gần nhất") }} <strong>{{ formatDateTime(orderSummary.last_purchase_at) }}</strong></span>
              </div>

              <ol v-if="customerOrders.length" class="customer-order-list">
                <li v-for="order in customerOrders" :key="order.id">
                  <article class="customer-order-card">
                    <header>
                      <div class="customer-order-title">
                        <strong>{{ order.order_number || `#${order.id}` }}</strong>
                        <time v-if="order.created_at" :datetime="order.created_at">{{ formatDateTime(order.created_at) }}</time>
                      </div>
                      <div class="customer-order-badges">
                        <span class="customer-order-badge" :data-status="order.status">{{ orderStatusLabel(order.status) }}</span>
                        <span class="customer-order-badge payment" :data-status="order.payment_status">{{ paymentStatusLabel(order.payment_status) }}</span>
                      </div>
                    </header>
                    <ul v-if="order.items?.length" class="customer-order-items">
                      <li v-for="item in order.items" :key="item.id">
                        <span>{{ item.product_name }}<small v-if="item.sku">{{ t("SKU") }} · {{ item.sku }}</small></span>
                        <strong>×{{ item.quantity }} · {{ formatMoney(item.line_total) }}</strong>
                      </li>
                    </ul>
                    <p v-else class="profile-empty">{{ t("Không có sản phẩm trong đơn này.") }}</p>
                    <footer class="customer-order-totals">
                      <span>{{ t("Tổng đơn") }} <strong>{{ formatMoney(order.total_amount) }}</strong></span>
                      <span>{{ t("Đã trả") }} <strong>{{ formatMoney(order.paid_amount) }}</strong></span>
                      <span v-if="order.refunded_amount > 0">{{ t("Đã hoàn") }} <strong>{{ formatMoney(order.refunded_amount) }}</strong></span>
                      <span class="customer-order-net">{{ t("Giá trị ròng") }} <strong>{{ formatMoney(order.net_amount) }}</strong></span>
                    </footer>
                  </article>
                </li>
              </ol>
              <p v-else class="profile-empty customer-orders-empty">
                {{ orderStatus ? t("Không có đơn hàng phù hợp trạng thái này.") : t("Khách hàng chưa có đơn hàng.") }}
              </p>
              <button
                v-if="hasMoreOrders"
                class="customer-load-more customer-order-load-more"
                type="button"
                :disabled="ordersLoadingMore"
                @click="loadCustomerOrders(selectedId, { append: true })"
              >{{ ordersLoadingMore ? t("Đang tải...") : t("Tải thêm đơn hàng") }}</button>
            </template>
          </section>

          <section class="profile-section">
            <div class="profile-section-title"><h3>{{ t("Tài khoản đã liên kết") }}</h3><span>{{ profile.identities?.length || 0 }}</span></div>
            <ul v-if="profile.identities?.length" class="profile-identity-list">
              <li v-for="identity in profile.identities" :key="identity.id">
                <span class="identity-channel">{{ channelLabel(identity.channel) }}</span>
                <span>{{ identity.display_name || identity.username || identity.external_user_id }}</span>
                <time v-if="identity.last_seen_at" :datetime="identity.last_seen_at">{{ formatDateTime(identity.last_seen_at) }}</time>
              </li>
            </ul>
            <p v-else class="profile-empty">{{ t("Chưa liên kết tài khoản kênh.") }}</p>
          </section>

          <section class="profile-section">
            <div class="profile-section-title"><h3>{{ t("Nhãn khách hàng") }}</h3><span>{{ profile.tags?.length || 0 }}</span></div>
            <div v-if="profile.tags?.length" class="profile-tags"><span v-for="tag in profile.tags" :key="tag">{{ tag }}</span></div>
            <p v-else class="profile-empty">{{ t("Chưa có nhãn.") }}</p>
          </section>

          <section class="profile-section">
            <div class="profile-section-title"><h3>{{ t("Cuộc trò chuyện gần đây") }}</h3><span>{{ profile.conversation_count || 0 }}</span></div>
            <ul v-if="profile.conversations?.length" class="profile-conversation-list">
              <li v-for="conversation in profile.conversations.slice(0, 5)" :key="conversation.id">
                <span><strong>{{ channelLabel(conversation.channel) }}</strong><small>{{ conversation.status }} · {{ conversation.priority }}</small></span>
                <time v-if="conversation.last_message_at" :datetime="conversation.last_message_at">{{ formatDateTime(conversation.last_message_at) }}</time>
              </li>
            </ul>
            <p v-else class="profile-empty">{{ t("Chưa có cuộc trò chuyện.") }}</p>
          </section>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.customer-management {
  --customer-ink: var(--crm-ink, #172033);
  --customer-muted: var(--crm-muted, #65758a);
  --customer-border: var(--crm-border, #dfe5ec);
  --customer-surface: var(--crm-surface, #fff);
  --customer-canvas: var(--crm-canvas, #f4f7fb);
  --customer-accent: var(--crm-accent, #168b8d);
  display: grid;
  gap: 16px;
  min-width: 0;
  color: var(--customer-ink);
}
.customer-page-header, .customer-toolbar, .customer-list-panel, .customer-profile-panel {
  background: var(--customer-surface);
  border: 1px solid var(--customer-border);
  border-radius: 14px;
}
.customer-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 24px;
}
.customer-eyebrow { color: var(--customer-accent); font-size: 11px; font-weight: 800; letter-spacing: .1em; }
.customer-page-header h1 { margin: 5px 0; font-size: clamp(22px, 2vw, 28px); line-height: 1.2; }
.customer-page-header p { margin: 0; color: var(--customer-muted); font-size: 14px; }
.customer-total { display: grid; justify-items: end; gap: 2px; flex: 0 0 auto; }
.customer-total strong { font-size: 24px; }
.customer-total span { color: var(--customer-muted); font-size: 12px; }
.customer-toolbar { display: flex; align-items: center; gap: 10px; padding: 12px; }
.customer-search { display: flex; align-items: center; gap: 8px; flex: 1 1 auto; min-width: 180px; }
.customer-search > span { color: var(--customer-accent); font-size: 22px; line-height: 1; }
.customer-search input, .customer-channel-filter select {
  width: 100%; min-height: 42px; padding: 0 12px; color: inherit;
  background: var(--customer-canvas); border: 1px solid var(--customer-border); border-radius: 9px; font: inherit;
}
.customer-channel-filter { flex: 0 1 190px; }
.customer-action-button { min-height: 42px; padding: 0 15px; border: 1px solid var(--customer-border); border-radius: 9px; background: var(--customer-surface); color: inherit; font: inherit; font-weight: 700; cursor: pointer; }
.customer-search-button { background: var(--customer-accent); border-color: var(--customer-accent); color: #fff; }
.customer-action-button:disabled, .customer-load-more:disabled { opacity: .6; cursor: wait; }
.customer-action-button:focus-visible, .customer-row:focus-visible, .customer-load-more:focus-visible, .customer-order-retry:focus-visible, .customer-search input:focus-visible, .customer-channel-filter select:focus-visible, .customer-order-filter select:focus-visible { outline: 3px solid color-mix(in srgb, var(--customer-accent) 45%, transparent); outline-offset: 2px; }
.customer-alert { margin: 0; padding: 12px 14px; color: #a02938; background: #fff0f1; border: 1px solid #f1c3c8; border-radius: 10px; }
.customer-workspace { display: grid; grid-template-columns: minmax(250px, 320px) minmax(0, 1fr); align-items: start; gap: 16px; min-width: 0; }
.customer-list-panel, .customer-profile-panel { min-width: 0; overflow: hidden; }
.customer-list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 14px; border-bottom: 1px solid var(--customer-border); }
.customer-list-heading span, .profile-section-title > span { color: var(--customer-muted); font-size: 12px; }
.customer-list { display: grid; gap: 2px; max-height: min(70vh, 780px); overflow: auto; padding: 5px; }
.customer-row { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; gap: 7px; width: 100%; padding: 6px 7px; border: 1px solid transparent; border-radius: 9px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.customer-row:hover { background: var(--customer-canvas); }
.customer-row.selected { border-color: color-mix(in srgb, var(--customer-accent) 35%, var(--customer-border)); background: color-mix(in srgb, var(--customer-accent) 11%, var(--customer-surface)); }
.customer-avatar, .profile-avatar { display: grid; place-items: center; border-radius: 50%; color: var(--customer-accent); background: color-mix(in srgb, var(--customer-accent) 14%, var(--customer-surface)); font-weight: 800; }
.customer-avatar { width: 32px; height: 32px; font-size: 13px; }
.customer-avatar-image, .profile-avatar-image { display: block; flex: 0 0 auto; object-fit: cover; border-radius: 50%; border: 1px solid var(--customer-border); background: var(--customer-canvas); }
.customer-avatar-image { width: 32px; height: 32px; }
.profile-avatar-image { width: 56px; height: 56px; }
.customer-row-copy { display: grid; min-width: 0; gap: 1px; }
.customer-row-copy strong, .customer-row-copy > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.customer-row-copy strong { font-size: 12.5px; }
.customer-row-copy > span { color: var(--customer-muted); font-size: 11px; }
.customer-row-copy small { color: var(--customer-accent); font-size: 10px; font-weight: 700; }
.customer-load-more { min-height: 40px; border: 1px solid var(--customer-border); border-radius: 9px; background: var(--customer-surface); color: inherit; font: inherit; font-weight: 700; cursor: pointer; }
.customer-profile-panel { padding: 18px 20px; }
.profile-heading { display: flex; align-items: center; gap: 14px; padding-bottom: 18px; border-bottom: 1px solid var(--customer-border); }
.profile-avatar { width: 56px; height: 56px; flex: 0 0 auto; font-size: 20px; }
.profile-title { min-width: 0; }
.profile-title h2 { margin: 3px 0; font-size: 21px; overflow-wrap: anywhere; }
.profile-updated { color: var(--customer-muted); font-size: 12px; }
.profile-section { padding: 16px 0; border-bottom: 1px solid var(--customer-border); }
.profile-section:last-child { border-bottom: 0; padding-bottom: 2px; }
.profile-section h3 { margin: 0; font-size: 14px; }
.customer-orders-heading { align-items: flex-start; }
.customer-orders-heading > div { display: grid; gap: 3px; }
.customer-orders-heading > div > span { color: var(--customer-muted); font-size: 11px; }
.customer-order-filter { flex: 0 1 190px; min-width: 145px; }
.customer-order-filter select { width: 100%; min-height: 38px; padding: 0 10px; border: 1px solid var(--customer-border); border-radius: 8px; color: inherit; background: var(--customer-canvas); font: inherit; font-size: 12px; }
.customer-order-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.customer-order-stats article { display: grid; align-content: start; gap: 5px; min-width: 0; padding: 10px 11px; border: 1px solid var(--customer-border); border-radius: 9px; background: var(--customer-canvas); }
.customer-order-stats article > span, .customer-order-spend small { color: var(--customer-muted); font-size: 11px; }
.customer-order-stats article > strong { overflow-wrap: anywhere; font-size: 15px; }
.customer-order-stats .customer-order-spend { border-color: color-mix(in srgb, var(--customer-accent) 35%, var(--customer-border)); background: color-mix(in srgb, var(--customer-accent) 10%, var(--customer-surface)); }
.customer-order-stats .customer-order-spend > strong { color: var(--customer-accent); font-size: 17px; }
.customer-order-summary-meta { display: flex; flex-wrap: wrap; gap: 7px 16px; padding: 10px 2px 2px; color: var(--customer-muted); font-size: 11px; }
.customer-order-summary-meta strong { color: var(--customer-ink); }
.customer-order-list { display: grid; gap: 9px; margin: 12px 0 0; padding: 0; list-style: none; }
.customer-order-card { min-width: 0; padding: 11px 12px; border: 1px solid var(--customer-border); border-radius: 10px; background: var(--customer-surface); }
.customer-order-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.customer-order-title { display: grid; gap: 3px; min-width: 0; }
.customer-order-title strong { overflow-wrap: anywhere; font-size: 13px; }
.customer-order-title time { color: var(--customer-muted); font-size: 11px; }
.customer-order-badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 5px; }
.customer-order-badge { padding: 4px 7px; border-radius: 999px; color: var(--customer-accent); background: color-mix(in srgb, var(--customer-accent) 12%, var(--customer-surface)); font-size: 10px; font-weight: 700; }
.customer-order-badge.payment { color: var(--customer-muted); background: var(--customer-canvas); }
.customer-order-items { display: grid; gap: 6px; margin: 10px 0; padding: 0; list-style: none; }
.customer-order-items li { display: flex; justify-content: space-between; gap: 10px; min-width: 0; font-size: 12px; }
.customer-order-items li > span { min-width: 0; overflow-wrap: anywhere; }
.customer-order-items small { display: block; margin-top: 2px; color: var(--customer-muted); font-size: 10px; }
.customer-order-items li > strong { flex: 0 0 auto; font-size: 11px; }
.customer-order-totals { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px 14px; padding-top: 9px; border-top: 1px solid var(--customer-border); color: var(--customer-muted); font-size: 10.5px; }
.customer-order-totals strong { color: var(--customer-ink); }
.customer-order-totals .customer-order-net strong { color: var(--customer-accent); }
.customer-order-loading, .customer-order-error { margin: 12px 0; color: var(--customer-muted); font-size: 12px; }
.customer-order-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0; padding: 10px 12px; border: 1px solid color-mix(in srgb, #dc4656 40%, var(--customer-border)); border-radius: 9px; color: var(--customer-ink); background: color-mix(in srgb, #dc4656 11%, var(--customer-surface)); font-size: 12px; }
.customer-order-error p { margin: 0; }
.customer-order-retry { min-height: 34px; flex: 0 0 auto; padding: 0 11px; border: 1px solid var(--customer-border); border-radius: 8px; color: inherit; background: var(--customer-surface); font: inherit; font-weight: 700; cursor: pointer; }
.customer-order-retry:disabled { opacity: .6; cursor: wait; }
.customer-orders-empty { padding: 14px 0 4px; }
.customer-order-load-more { width: 100%; margin-top: 10px; }
.profile-contact-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px 20px; margin: 12px 0 0; }
.profile-contact-grid > div { min-width: 0; }
.profile-contact-grid dt { margin-bottom: 3px; color: var(--customer-muted); font-size: 11px; }
.profile-contact-grid dd { margin: 0; overflow-wrap: anywhere; font-size: 13px; }
.profile-address { grid-column: 1 / -1; }
.profile-section-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.profile-identity-list, .profile-conversation-list { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.profile-identity-list li, .profile-conversation-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 9px 10px; border-radius: 8px; background: var(--customer-canvas); font-size: 12px; }
.profile-identity-list li > span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-identity-list time, .profile-conversation-list time { flex: 0 0 auto; color: var(--customer-muted); font-size: 11px; }
.identity-channel { color: var(--customer-accent); font-weight: 800; }
.profile-tags { display: flex; flex-wrap: wrap; gap: 7px; }
.profile-tags span { padding: 5px 9px; border-radius: 999px; background: color-mix(in srgb, var(--customer-accent) 12%, var(--customer-surface)); color: var(--customer-accent); font-size: 12px; font-weight: 700; }
.profile-conversation-list li > span { display: grid; gap: 3px; }
.profile-conversation-list small, .profile-empty { color: var(--customer-muted); font-size: 12px; }
.profile-empty { margin: 0; }
.customer-state { display: grid; justify-items: center; align-content: center; gap: 8px; min-height: 180px; padding: 24px; color: var(--customer-muted); text-align: center; }
.customer-state strong { color: var(--customer-ink); }
.customer-state-error { color: #a02938; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 900px) { .customer-workspace { grid-template-columns: minmax(230px, 270px) minmax(0, 1fr); } }
@media (max-width: 700px) {
  .customer-page-header { align-items: flex-start; padding: 17px; }
  .customer-toolbar { flex-wrap: wrap; }
  .customer-search { flex-basis: 100%; }
  .customer-channel-filter { flex: 1 1 150px; }
  .customer-workspace { grid-template-columns: minmax(0, 1fr); }
  .customer-list { max-height: 48vh; }
  .customer-profile-panel { padding: 15px; }
  .customer-order-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .customer-orders-heading { flex-wrap: wrap; }
  .customer-order-filter { flex: 1 1 100%; }
  .customer-order-card > header { flex-direction: column; }
  .customer-order-badges { justify-content: flex-start; }
  .customer-order-error { align-items: flex-start; flex-direction: column; }
}
</style>
