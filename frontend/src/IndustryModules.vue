<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { apiFetch } from "./api-client.js";
import { appointmentsToIcs } from "./calendar-utils.js";
import { formatDate, formatDateTime, formatMoney, t } from "./i18n.js";

const props = defineProps({ module: { type: String, required: true }, apiBase: { type: String, default: "/api" } });
const api = (path) => `${props.apiBase}${path}`;
const busy = ref(false);
const error = ref("");
const notice = ref("");
const customers = ref([]);
const staff = ref([]);
const services = ref([]);
const appointments = ref([]);
const quotes = ref([]);
const projects = ref([]);
const invoices = ref([]);
const activeTab = ref(props.module === "appointments" ? "appointments" : "quotes");
const appointmentPeriod = ref("upcoming");
const editingServiceId = ref(null);
const editingAppointmentId = ref(null);
const editingQuoteId = ref(null);
const editingProjectId = ref(null);
const paymentAmounts = reactive({});
const paymentMethods = reactive({});
const showPaymentHistoryId = ref(null);
const paymentSavingId = ref(null);
const serviceForm = reactive({ name: "", description: "", duration_minutes: 60, price: 0 });
const appointmentForm = reactive({ customer_id: "", service_id: "", starts_at: "", assigned_user_id: "", reminder_minutes_before: 60, send_customer_reminder: false, notes: "" });
const quoteForm = reactive({ customer_id: "", title: "", tax_rate: 0, valid_until: "", notes: "", items: [{ name: "", quantity: 1, unit_price: 0 }] });
const projectForm = reactive({ customer_id: "", title: "", budget: 0, starts_on: "", due_on: "", assigned_user_id: "", description: "" });
const invoiceForm = reactive({ customer_id: "", project_id: "", quote_id: "", description: "", total_amount: 0, status: "draft", issued_on: "", due_on: "", notes: "" });
const quoteSubtotal = computed(() => quoteForm.items.reduce((sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.unit_price) || 0), 0));
const quoteTotal = computed(() => quoteSubtotal.value * (1 + (Number(quoteForm.tax_rate) || 0) / 100));

const money = formatMoney;
const dateTimeInput = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const showTime = formatDateTime;
const showDate = formatDate;
const customerName = (id) => customers.value.find((customer) => Number(customer.id) === Number(id))?.name || t("Khách hàng");
const staffName = (id) => staff.value.find((member) => Number(member.id) === Number(id))?.full_name || t("Chưa phân công");
const statusLabels = {
  scheduled: "Đã đặt", confirmed: "Đã xác nhận", completed: "Hoàn tất", cancelled: "Đã hủy", no_show: "Không đến",
  draft: "Bản nháp", sent: "Đã gửi", accepted: "Đã chấp thuận", rejected: "Từ chối", expired: "Hết hạn",
  planned: "Lên kế hoạch", active: "Đang thực hiện", on_hold: "Tạm dừng", completed_project: "Hoàn tất", cancelled_project: "Đã hủy",
  issued: "Đã phát hành", paid: "Đã thanh toán", overdue: "Quá hạn", void: "Đã hủy",
};
const statusLabel = (value) => t(statusLabels[value] || value || "Chưa rõ");
const projectStatusLabel = (value) => t(({ completed: "Hoàn tất", cancelled: "Đã hủy" })[value] || statusLabels[value] || value || "Chưa rõ");
const paymentMethodLabel = (value) => t(({ bank_transfer: "Chuyển khoản", cash: "Tiền mặt", card: "Thẻ", other: "Khác" })[value] || value || "Khác");

async function request(path, options) {
  const response = await apiFetch(api(path), options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail?.message || body.detail || `Lỗi HTTP ${response.status}`);
  return body;
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [customerData, staffData] = await Promise.all([
      request("/customers?limit=200"),
      request("/team?active_only=true"),
    ]);
    customers.value = customerData.items || [];
    staff.value = staffData.items || [];
    if (props.module === "appointments") {
      const now = new Date();
      const params = new URLSearchParams({ limit: "500" });
      if (appointmentPeriod.value !== "all") {
        const from = new Date(now);
        const to = new Date(now);
        if (appointmentPeriod.value === "today") {
          from.setHours(0, 0, 0, 0);
          to.setHours(24, 0, 0, 0);
        } else if (appointmentPeriod.value === "week") {
          from.setHours(0, 0, 0, 0);
          to.setDate(to.getDate() + 7);
          to.setHours(0, 0, 0, 0);
        }
        params.set("starts_from", from.toISOString());
        if (appointmentPeriod.value !== "upcoming") params.set("starts_to", to.toISOString());
      }
      const [serviceData, appointmentData] = await Promise.all([
        request("/appointments/services"), request(`/appointments?${params.toString()}`),
      ]);
      services.value = serviceData.items || [];
      appointments.value = appointmentData.items || [];
    } else {
      const [quoteData, projectData, invoiceData] = await Promise.all([
        request("/commercial/quotes?limit=200"), request("/commercial/projects?limit=200"), request("/commercial/invoices?limit=200"),
      ]);
      quotes.value = quoteData.items || [];
      projects.value = projectData.items || [];
      invoices.value = invoiceData.items || [];
    }
  } catch (err) {
    error.value = err.message || "Chưa tải được dữ liệu. Hãy thử lại.";
  } finally {
    busy.value = false;
  }
}

async function run(action, success) {
  error.value = "";
  notice.value = "";
  try {
    await action();
    notice.value = success;
    await load();
  } catch (err) {
    error.value = err.message || "Không thể lưu thay đổi.";
  }
}

function resetService() { editingServiceId.value = null; Object.assign(serviceForm, { name: "", description: "", duration_minutes: 60, price: 0 }); }
async function saveService() {
  const editing = editingServiceId.value;
  const path = editing ? `/appointments/services/${editing}` : "/appointments/services";
  await run(() => request(path, { method: editing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(serviceForm) }), editing ? "Đã cập nhật dịch vụ." : "Đã thêm dịch vụ.");
  resetService();
}
function editService(service) { editingServiceId.value = service.id; Object.assign(serviceForm, { name: service.name, description: service.description || "", duration_minutes: service.duration_minutes, price: service.price }); }
async function toggleService(service) {
  await run(() => request(`/appointments/services/${service.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !service.is_active }) }), service.is_active ? "Đã tạm ngừng nhận lịch dịch vụ." : "Đã mở lại dịch vụ.");
}
function resetAppointment() { editingAppointmentId.value = null; Object.assign(appointmentForm, { customer_id: "", service_id: "", starts_at: "", assigned_user_id: "", reminder_minutes_before: 60, send_customer_reminder: false, notes: "" }); }
async function saveAppointment() {
  const editing = editingAppointmentId.value;
  const startsAt = new Date(appointmentForm.starts_at);
  if (Number.isNaN(startsAt.getTime())) { error.value = "Chọn ngày và giờ hợp lệ."; return; }
  const payload = { ...appointmentForm, customer_id: Number(appointmentForm.customer_id), service_id: Number(appointmentForm.service_id), assigned_user_id: appointmentForm.assigned_user_id ? Number(appointmentForm.assigned_user_id) : null, starts_at: startsAt.toISOString(), reminder_minutes_before: Number(appointmentForm.reminder_minutes_before) };
  const path = editing ? `/appointments/${editing}` : "/appointments";
  await run(() => request(path, { method: editing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }), editing ? "Đã cập nhật lịch hẹn và lịch nhắc." : "Đã tạo lịch hẹn.");
  resetAppointment();
}
function editAppointment(item) {
  editingAppointmentId.value = item.id;
  Object.assign(appointmentForm, { customer_id: String(item.customer_id), service_id: String(item.service_id), starts_at: dateTimeInput(item.starts_at), assigned_user_id: item.assigned_user_id ? String(item.assigned_user_id) : "", reminder_minutes_before: item.reminder_minutes_before, send_customer_reminder: Boolean(item.send_customer_reminder), notes: item.notes || "" });
}
async function setAppointmentStatus(item, status) {
  await run(() => request(`/appointments/${item.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }), "Đã cập nhật trạng thái lịch hẹn.");
}
async function setProjectStatus(project, status) {
  await run(() => request(`/commercial/projects/${project.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }), "Đã cập nhật trạng thái dự án.");
}

function resetQuote() { editingQuoteId.value = null; Object.assign(quoteForm, { customer_id: "", title: "", tax_rate: 0, valid_until: "", notes: "", items: [{ name: "", quantity: 1, unit_price: 0 }] }); }
async function saveQuote() {
  const editing = editingQuoteId.value;
  const payload = { ...quoteForm, customer_id: Number(quoteForm.customer_id), tax_rate: Number(quoteForm.tax_rate), valid_until: quoteForm.valid_until || null, items: quoteForm.items.map((line) => ({ ...line, quantity: Number(line.quantity), unit_price: Number(line.unit_price) })) };
  await run(() => request(editing ? `/commercial/quotes/${editing}` : "/commercial/quotes", { method: editing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }), editing ? "Đã cập nhật báo giá." : "Đã tạo báo giá.");
  resetQuote();
}
function editQuote(quote) {
  editingQuoteId.value = quote.id;
  Object.assign(quoteForm, { customer_id: String(quote.customer_id), title: quote.title, tax_rate: Number(quote.tax_rate), valid_until: quote.valid_until || "", notes: quote.notes || "", items: (quote.items || []).map(({ name, quantity, unit_price }) => ({ name, quantity: Number(quantity), unit_price: Number(unit_price) })) });
}
async function setQuoteStatus(quote, status) {
  await run(() => request(`/commercial/quotes/${quote.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }), "Đã cập nhật trạng thái báo giá.");
}
async function convertQuote(quote) {
  await run(() => request(`/commercial/quotes/${quote.id}/project`, { method: "POST" }), "Đã chuyển báo giá thành dự án.");
  activeTab.value = "projects";
}

function resetProject() { editingProjectId.value = null; Object.assign(projectForm, { customer_id: "", title: "", budget: 0, starts_on: "", due_on: "", assigned_user_id: "", description: "" }); }
async function saveProject() {
  const editing = editingProjectId.value;
  const payload = { ...projectForm, customer_id: Number(projectForm.customer_id), budget: Number(projectForm.budget), assigned_user_id: projectForm.assigned_user_id ? Number(projectForm.assigned_user_id) : null, starts_on: projectForm.starts_on || null, due_on: projectForm.due_on || null };
  await run(() => request(editing ? `/commercial/projects/${editing}` : "/commercial/projects", { method: editing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }), editing ? "Đã cập nhật dự án." : "Đã tạo dự án.");
  resetProject();
}
function editProject(item) { editingProjectId.value = item.id; Object.assign(projectForm, { customer_id: String(item.customer_id), title: item.title, budget: item.budget, starts_on: item.starts_on || "", due_on: item.due_on || "", assigned_user_id: item.assigned_user_id ? String(item.assigned_user_id) : "", description: item.description || "" }); }
function createInvoiceForProject(project) {
  activeTab.value = "invoices";
  Object.assign(invoiceForm, { customer_id: String(project.customer_id), project_id: String(project.id), quote_id: project.quote_id ? String(project.quote_id) : "", description: `Dịch vụ dự án: ${project.title}`, total_amount: Number(project.budget), status: "draft", issued_on: new Date().toISOString().slice(0, 10), due_on: "", notes: "" });
}

async function saveInvoice() {
  const payload = { ...invoiceForm, customer_id: Number(invoiceForm.customer_id), project_id: invoiceForm.project_id ? Number(invoiceForm.project_id) : null, quote_id: invoiceForm.quote_id ? Number(invoiceForm.quote_id) : null, total_amount: Number(invoiceForm.total_amount), issued_on: invoiceForm.issued_on || null, due_on: invoiceForm.due_on || null };
  await run(() => request("/commercial/invoices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }), "Đã tạo hóa đơn.");
  Object.assign(invoiceForm, { customer_id: "", project_id: "", quote_id: "", description: "", total_amount: 0, status: "draft", issued_on: "", due_on: "", notes: "" });
}
async function updateInvoice(invoice, changes) {
  await run(() => request(`/commercial/invoices/${invoice.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }), "Đã cập nhật hóa đơn.");
}
async function emailQuote(quote) {
  await run(() => request(`/commercial/quotes/${quote.id}/send-email`, { method: "POST" }), "Đã gửi báo giá qua email khách hàng.");
}
async function emailInvoice(invoice) {
  await run(() => request(`/commercial/invoices/${invoice.id}/send-email`, { method: "POST" }), "Đã gửi hóa đơn qua email khách hàng.");
}
function exportCalendar() {
  const content = appointmentsToIcs(appointments.value);
  if (!content.includes("BEGIN:VEVENT")) { error.value = "Không có lịch hợp lệ để xuất."; return; }
  const url = URL.createObjectURL(new Blob([content], { type: "text/calendar;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "smart-merchant-appointments.ics";
  link.click();
  URL.revokeObjectURL(url);
  notice.value = "Đã tải lịch .ics. Nhập tệp này vào Google Calendar hoặc Outlook.";
}
async function recordPayment(invoice) {
  if (paymentSavingId.value === invoice.id) return;
  const amount = Number(paymentAmounts[invoice.id] ?? invoice.balance_due);
  if (!(amount > 0) || amount > Number(invoice.balance_due)) { error.value = "Khoản thu phải lớn hơn 0 và không vượt số dư."; return; }
  paymentSavingId.value = invoice.id;
  try {
    await run(() => request(`/commercial/invoices/${invoice.id}/payments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount, method: paymentMethods[invoice.id] || "bank_transfer" }) }), "Đã ghi nhận khoản thanh toán.");
  } finally {
    paymentSavingId.value = null;
  }
}

onMounted(load);
watch(() => props.module, () => {
  activeTab.value = props.module === "appointments" ? "appointments" : "quotes";
  load();
});
</script>

<template>
  <section class="industry-workspace">
    <header class="industry-heading">
      <div>
        <span class="industry-eyebrow">KHÔNG GIAN NGHIỆP VỤ</span>
        <h1>{{ module === "appointments" ? "Lịch hẹn & dịch vụ" : "Báo giá, dự án & hóa đơn" }}</h1>
        <p>{{ module === "appointments" ? "Quản lý dịch vụ, lịch khách và nhắc nhân viên đúng giờ." : "Theo dõi báo giá đến dự án, lập hóa đơn và ghi nhận công nợ." }}</p>
      </div>
      <button type="button" class="industry-refresh" :disabled="busy" @click="load">{{ busy ? "Đang tải…" : "Làm mới" }}</button>
    </header>
    <p v-if="error" class="industry-alert error" role="alert">{{ error }}</p>
    <p v-if="notice" class="industry-alert success" role="status">{{ notice }}</p>
    <div v-if="busy && !customers.length" class="industry-empty">Đang tải dữ liệu shop…</div>

    <template v-else-if="module === 'appointments'">
      <nav class="industry-tabs" aria-label="Quản lý dịch vụ">
        <button :class="{ selected: activeTab === 'appointments' }" @click="activeTab = 'appointments'">Lịch hẹn <span>{{ appointments.length }}</span></button>
        <button :class="{ selected: activeTab === 'services' }" @click="activeTab = 'services'">Dịch vụ <span>{{ services.length }}</span></button>
      </nav>
      <div v-if="activeTab === 'services'" class="industry-columns">
        <form class="industry-card industry-form" @submit.prevent="saveService">
          <h2>{{ editingServiceId ? "Sửa dịch vụ" : "Thêm dịch vụ" }}</h2>
          <label>Tên dịch vụ<input v-model="serviceForm.name" required maxlength="160" placeholder="Ví dụ: Tư vấn 1:1" /></label>
          <div class="industry-form-row"><label>Thời lượng (phút)<input v-model.number="serviceForm.duration_minutes" type="number" min="5" max="1440" required /></label><label>Giá (đ)<input v-model.number="serviceForm.price" type="number" min="0" step="1000" required /></label></div>
          <label>Mô tả<textarea v-model="serviceForm.description" rows="3" maxlength="2000" /></label>
          <div class="industry-actions"><button class="industry-primary">{{ editingServiceId ? "Lưu dịch vụ" : "Thêm dịch vụ" }}</button><button v-if="editingServiceId" type="button" class="industry-secondary" @click="resetService">Hủy sửa</button></div>
        </form>
        <div class="industry-card">
          <h2>Danh mục dịch vụ</h2>
          <p v-if="!services.length" class="industry-empty">Chưa có dịch vụ. Thêm dịch vụ trước khi tạo lịch hẹn.</p>
          <article v-for="service in services" :key="service.id" class="industry-row">
            <div><strong>{{ service.name }}</strong><small>{{ service.duration_minutes }} phút · {{ money(service.price) }} · {{ service.description || "Không có mô tả" }}</small></div>
            <div class="industry-actions"><span class="industry-pill" :class="{ muted: !service.is_active }">{{ service.is_active ? "Đang nhận lịch" : "Đã tạm ngừng" }}</span><button class="industry-secondary" @click="editService(service)">Sửa</button><button class="industry-secondary" @click="toggleService(service)">{{ service.is_active ? "Tạm ngừng" : "Mở lại" }}</button></div>
          </article>
        </div>
      </div>
      <div v-else class="industry-columns">
        <form class="industry-card industry-form" @submit.prevent="saveAppointment">
          <h2>{{ editingAppointmentId ? "Chỉnh sửa lịch" : "Đặt lịch mới" }}</h2>
          <label>Khách hàng<select v-model="appointmentForm.customer_id" required><option value="" disabled>Chọn khách hàng</option><option v-for="customer in customers" :key="customer.id" :value="String(customer.id)">{{ customer.name || customer.email || customer.phone || `Khách hàng #${customer.id}` }}</option></select></label>
          <label>Dịch vụ<select v-model="appointmentForm.service_id" required><option value="" disabled>Chọn dịch vụ</option><option v-for="service in services.filter((item) => item.is_active)" :key="service.id" :value="String(service.id)">{{ service.name }} · {{ service.duration_minutes }} phút</option></select></label>
          <label>Ngày, giờ<input v-model="appointmentForm.starts_at" type="datetime-local" required /></label>
          <div class="industry-form-row"><label>Nhân viên<select v-model="appointmentForm.assigned_user_id"><option value="">Chưa phân công</option><option v-for="member in staff" :key="member.id" :value="String(member.id)">{{ member.full_name }}</option></select></label><label>Nhắc trước (phút)<input v-model.number="appointmentForm.reminder_minutes_before" type="number" min="0" max="10080" /></label></div>
          <label class="industry-checkbox"><input v-model="appointmentForm.send_customer_reminder" type="checkbox" /> Gửi email nhắc lịch cho khách (cần có email)</label>
          <label>Ghi chú<textarea v-model="appointmentForm.notes" rows="3" maxlength="4000" /></label>
          <div class="industry-actions"><button class="industry-primary">{{ editingAppointmentId ? "Lưu lịch hẹn" : "Tạo lịch hẹn" }}</button><button v-if="editingAppointmentId" type="button" class="industry-secondary" @click="resetAppointment">Hủy sửa</button></div>
        </form>
        <div class="industry-card">
          <div class="industry-card-head"><h2>Lịch hẹn</h2><div class="industry-actions"><select v-model="appointmentPeriod" aria-label="Khoảng thời gian lịch hẹn" @change="load"><option value="upcoming">Sắp tới</option><option value="today">Hôm nay</option><option value="week">7 ngày tới</option><option value="all">Tất cả</option></select><span>{{ appointments.length }} lịch</span><button type="button" class="industry-secondary" @click="exportCalendar">Xuất .ics</button></div></div>
          <p v-if="!appointments.length" class="industry-empty">Chưa có lịch hẹn nào.</p>
          <article v-for="item in appointments" :key="item.id" class="industry-row industry-record">
            <div class="industry-record-main"><strong>{{ item.customer_name || customerName(item.customer_id) }} <span class="industry-pill">{{ item.service_name }}</span></strong><small>{{ showTime(item.starts_at) }} – {{ showTime(item.ends_at) }} · {{ staffName(item.assigned_user_id) }}</small><small v-if="item.notes">{{ item.notes }}</small><small>{{ item.reminder_sent_at ? (item.send_customer_reminder ? "Đã gửi nhắc qua email" : "Đã tạo thông báo nhắc") : item.reminder_at ? `Nhắc trước ${item.reminder_minutes_before} phút` : "Không đặt nhắc" }}</small></div>
            <div class="industry-actions"><select :value="item.status" :aria-label="`Trạng thái lịch ${item.id}`" @change="setAppointmentStatus(item, $event.target.value)"><option value="scheduled">Đã đặt</option><option value="confirmed">Đã xác nhận</option><option value="completed">Hoàn tất</option><option value="cancelled">Đã hủy</option><option value="no_show">Không đến</option></select><button class="industry-secondary" @click="editAppointment(item)">Sửa lịch</button></div>
          </article>
        </div>
      </div>
    </template>

    <template v-else>
      <nav class="industry-tabs" aria-label="Quản lý khách hàng doanh nghiệp">
        <button :class="{ selected: activeTab === 'quotes' }" @click="activeTab = 'quotes'">Báo giá <span>{{ quotes.length }}</span></button>
        <button :class="{ selected: activeTab === 'projects' }" @click="activeTab = 'projects'">Dự án <span>{{ projects.length }}</span></button>
        <button :class="{ selected: activeTab === 'invoices' }" @click="activeTab = 'invoices'">Hóa đơn <span>{{ invoices.length }}</span></button>
      </nav>
      <div v-if="activeTab === 'quotes'" class="industry-columns">
        <form class="industry-card industry-form" @submit.prevent="saveQuote">
          <h2>{{ editingQuoteId ? "Sửa báo giá" : "Tạo báo giá" }}</h2>
          <label>Khách hàng<select v-model="quoteForm.customer_id" required><option value="" disabled>Chọn khách hàng</option><option v-for="customer in customers" :key="customer.id" :value="String(customer.id)">{{ customer.name || customer.email || customer.phone || `Khách hàng #${customer.id}` }}</option></select></label>
          <label>Tiêu đề<input v-model="quoteForm.title" required maxlength="200" placeholder="Tên gói công việc / dịch vụ" /></label>
          <div class="industry-line-items"><div class="industry-card-head"><strong>Hạng mục</strong><button type="button" class="industry-secondary" @click="quoteForm.items.push({ name: '', quantity: 1, unit_price: 0 })">+ Thêm dòng</button></div><div v-for="(line, index) in quoteForm.items" :key="index" class="industry-quote-line"><label>Mô tả<input v-model="line.name" required maxlength="200" /></label><label>SL<input v-model.number="line.quantity" type="number" min="0.01" step="0.01" required /></label><label>Đơn giá<input v-model.number="line.unit_price" type="number" min="0" step="1000" required /></label><button v-if="quoteForm.items.length > 1" type="button" class="industry-icon-button" :aria-label="`Xóa dòng ${index + 1}`" @click="quoteForm.items.splice(index, 1)">×</button></div></div>
          <div class="industry-form-row"><label>Thuế (%)<input v-model.number="quoteForm.tax_rate" type="number" min="0" max="100" step="0.1" /></label><label>Hiệu lực đến<input v-model="quoteForm.valid_until" type="date" /></label></div>
          <div class="industry-total"><span>Tạm tính {{ money(quoteSubtotal) }} · Thuế {{ money(quoteTotal - quoteSubtotal) }}</span><strong>{{ money(quoteTotal) }}</strong></div>
          <label>Ghi chú<textarea v-model="quoteForm.notes" rows="2" maxlength="4000" /></label>
          <div class="industry-actions"><button class="industry-primary">{{ editingQuoteId ? "Lưu báo giá" : "Tạo báo giá" }}</button><button v-if="editingQuoteId" type="button" class="industry-secondary" @click="resetQuote">Hủy sửa</button></div>
        </form>
        <div class="industry-card"><div class="industry-card-head"><h2>Báo giá</h2><span>{{ quotes.length }} báo giá</span></div><p v-if="!quotes.length" class="industry-empty">Tạo báo giá đầu tiên cho khách hàng.</p>
          <article v-for="quote in quotes" :key="quote.id" class="industry-row industry-record"><div class="industry-record-main"><strong>{{ quote.quote_number }} · {{ quote.title }}</strong><small>{{ quote.customer_name }} · {{ quote.items?.length || 0 }} hạng mục · {{ quote.valid_until ? `Hạn ${showDate(quote.valid_until)}` : "Không đặt hạn" }}</small><b class="industry-amount">{{ money(quote.total_amount) }}</b><small v-if="quote.email_sent_at">Đã gửi email lúc {{ showTime(quote.email_sent_at) }}</small></div><div class="industry-actions"><select :value="quote.status" :aria-label="`Trạng thái báo giá ${quote.quote_number}`" @change="setQuoteStatus(quote, $event.target.value)"><option v-for="state in ['draft','sent','accepted','rejected','expired']" :key="state" :value="state">{{ statusLabel(state) }}</option></select><button class="industry-secondary" @click="editQuote(quote)">Sửa</button><button v-if="['draft','sent'].includes(quote.status) && !quote.email_sent_at" class="industry-secondary" :disabled="busy" @click="emailQuote(quote)">Gửi email</button><button v-if="quote.status === 'accepted'" class="industry-primary" @click="convertQuote(quote)">Tạo dự án</button></div></article>
        </div>
      </div>
      <div v-else-if="activeTab === 'projects'" class="industry-columns">
        <form class="industry-card industry-form" @submit.prevent="saveProject"><h2>{{ editingProjectId ? "Sửa dự án" : "Tạo dự án" }}</h2>
          <label>Khách hàng<select v-model="projectForm.customer_id" required><option value="" disabled>Chọn khách hàng</option><option v-for="customer in customers" :key="customer.id" :value="String(customer.id)">{{ customer.name || customer.email || `Khách hàng #${customer.id}` }}</option></select></label>
          <label>Tên dự án<input v-model="projectForm.title" required maxlength="200" /></label><label>Ngân sách (đ)<input v-model.number="projectForm.budget" type="number" min="0" step="1000" /></label>
          <div class="industry-form-row"><label>Bắt đầu<input v-model="projectForm.starts_on" type="date" /></label><label>Hạn hoàn thành<input v-model="projectForm.due_on" type="date" /></label></div>
          <label>Phụ trách<select v-model="projectForm.assigned_user_id"><option value="">Chưa phân công</option><option v-for="member in staff" :key="member.id" :value="String(member.id)">{{ member.full_name }}</option></select></label><label>Mô tả<textarea v-model="projectForm.description" rows="3" maxlength="4000" /></label>
          <div class="industry-actions"><button class="industry-primary">{{ editingProjectId ? "Lưu dự án" : "Tạo dự án" }}</button><button v-if="editingProjectId" type="button" class="industry-secondary" @click="resetProject">Hủy sửa</button></div>
        </form>
        <div class="industry-card"><div class="industry-card-head"><h2>Dự án</h2><span>{{ projects.length }} dự án</span></div><p v-if="!projects.length" class="industry-empty">Duyệt một báo giá hoặc tạo dự án trực tiếp.</p>
          <article v-for="project in projects" :key="project.id" class="industry-row industry-record"><div class="industry-record-main"><strong>{{ project.title }}</strong><small>{{ project.customer_name }} · {{ project.starts_on ? showDate(project.starts_on) : "Chưa bắt đầu" }} → {{ showDate(project.due_on) }} · {{ staffName(project.assigned_user_id) }}</small><b class="industry-amount">Ngân sách {{ money(project.budget) }}</b></div><div class="industry-actions"><select :value="project.status" :aria-label="`Trạng thái dự án ${project.title}`" @change="setProjectStatus(project, $event.target.value)"><option value="planned">Lên kế hoạch</option><option value="active">Đang thực hiện</option><option value="on_hold">Tạm dừng</option><option value="completed">Hoàn tất</option><option value="cancelled">Đã hủy</option></select><button class="industry-secondary" @click="editProject(project)">Sửa</button><button class="industry-primary" @click="createInvoiceForProject(project)">Lập hóa đơn</button></div></article>
        </div>
      </div>
      <div v-else class="industry-columns">
        <form class="industry-card industry-form" @submit.prevent="saveInvoice"><h2>Tạo hóa đơn</h2>
          <label>Khách hàng<select v-model="invoiceForm.customer_id" required><option value="" disabled>Chọn khách hàng</option><option v-for="customer in customers" :key="customer.id" :value="String(customer.id)">{{ customer.name || customer.email || `Khách hàng #${customer.id}` }}</option></select></label>
          <label>Dự án<select v-model="invoiceForm.project_id"><option value="">Không gắn dự án</option><option v-for="project in projects.filter((item) => Number(item.customer_id) === Number(invoiceForm.customer_id))" :key="project.id" :value="String(project.id)">{{ project.title }}</option></select></label>
          <label>Mô tả<input v-model="invoiceForm.description" required maxlength="240" /></label><label>Tổng tiền (đ)<input v-model.number="invoiceForm.total_amount" type="number" min="1" step="1000" required /></label>
          <div class="industry-form-row"><label>Ngày phát hành<input v-model="invoiceForm.issued_on" type="date" /></label><label>Hạn thanh toán<input v-model="invoiceForm.due_on" type="date" /></label></div><label>Ghi chú<textarea v-model="invoiceForm.notes" rows="2" maxlength="4000" /></label>
          <button class="industry-primary">Tạo hóa đơn</button>
        </form>
        <div class="industry-card"><div class="industry-card-head"><h2>Hóa đơn &amp; công nợ</h2><span>{{ invoices.length }} hóa đơn</span></div><p v-if="!invoices.length" class="industry-empty">Chưa có hóa đơn.</p>
          <article v-for="invoice in invoices" :key="invoice.id" class="industry-row industry-record"><div class="industry-record-main"><strong>{{ invoice.invoice_number }} · {{ invoice.description }}</strong><small>{{ invoice.customer_name }} · Hạn {{ showDate(invoice.due_on) }}</small><b class="industry-amount">Còn {{ money(invoice.balance_due) }} / {{ money(invoice.total_amount) }}</b><small v-if="invoice.email_sent_at">Đã gửi email lúc {{ showTime(invoice.email_sent_at) }}</small><button type="button" class="industry-link" @click="showPaymentHistoryId = showPaymentHistoryId === invoice.id ? null : invoice.id">{{ showPaymentHistoryId === invoice.id ? "Ẩn lịch sử" : `Lịch sử thu (${invoice.payments?.length || 0})` }}</button><div v-if="showPaymentHistoryId === invoice.id" class="industry-payment-history"><small v-for="payment in invoice.payments || []" :key="payment.id">{{ showDate(payment.paid_on) }} · {{ money(payment.amount) }} · {{ paymentMethodLabel(payment.method) }}{{ payment.reference ? ` · ${payment.reference}` : "" }}</small><small v-if="!invoice.payments?.length">Chưa ghi nhận khoản thu nào.</small></div></div><div class="industry-actions"><span class="industry-pill" :class="{ warning: invoice.status === 'overdue', muted: invoice.status === 'void' }">{{ statusLabel(invoice.status) }}</span><label v-if="['issued','overdue'].includes(invoice.status) && Number(invoice.balance_due) > 0" class="industry-paid-field">Ghi khoản thu<input :value="paymentAmounts[invoice.id] ?? invoice.balance_due" type="number" min="0.01" :max="invoice.balance_due" step="1000" :aria-label="`Khoản thanh toán ${invoice.invoice_number}`" @input="paymentAmounts[invoice.id] = $event.target.value" /></label><select v-if="['issued','overdue'].includes(invoice.status) && Number(invoice.balance_due) > 0" class="industry-method" :value="paymentMethods[invoice.id] || 'bank_transfer'" :aria-label="`Phương thức thanh toán ${invoice.invoice_number}`" @change="paymentMethods[invoice.id] = $event.target.value"><option value="bank_transfer">Chuyển khoản</option><option value="cash">Tiền mặt</option><option value="card">Thẻ</option><option value="other">Khác</option></select><button v-if="['issued','overdue'].includes(invoice.status) && Number(invoice.balance_due) > 0" class="industry-primary" :disabled="paymentSavingId === invoice.id" @click="recordPayment(invoice)">{{ paymentSavingId === invoice.id ? "Đang lưu…" : "Ghi nhận thu" }}</button><button v-if="['issued','overdue'].includes(invoice.status) && !invoice.email_sent_at" class="industry-secondary" :disabled="busy" @click="emailInvoice(invoice)">Gửi email</button><button v-if="invoice.status === 'draft'" class="industry-secondary" @click="updateInvoice(invoice, { status: 'issued', issued_on: invoice.issued_on || new Date().toISOString().slice(0, 10) })">Phát hành</button><button v-if="invoice.status !== 'void' && invoice.status !== 'paid' && Number(invoice.paid_amount) === 0" class="industry-danger" @click="updateInvoice(invoice, { status: 'void' })">Hủy</button></div></article>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.industry-workspace { display: grid; gap: 16px; color: var(--owly-ink, #17334a); padding: 4px 0 24px; }
.industry-heading, .industry-card-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.industry-heading { padding: 4px 2px 14px; border-bottom: 1px solid var(--owly-border, #d8e2e9); }
.industry-heading h1 { margin: 3px 0 4px; font-size: clamp(1.5rem, 2vw, 2rem); }
.industry-heading p, .industry-card p { margin: 0; color: var(--owly-muted, #687d8d); }
.industry-eyebrow { color: #168d91; font-size: .72rem; font-weight: 800; letter-spacing: .12em; }
.industry-card { min-width: 0; padding: 18px; border: 1px solid var(--owly-border, #d8e2e9); border-radius: 14px; background: var(--owly-surface, #fff); box-shadow: 0 8px 24px #1834490a; }
.industry-columns { display: grid; grid-template-columns: minmax(300px, .82fr) minmax(0, 1.5fr); align-items: start; gap: 16px; }
.industry-card h2 { margin: 0; font-size: 1.12rem; }
.industry-form { display: grid; gap: 13px; }
.industry-form label, .industry-paid-field { display: grid; gap: 5px; min-width: 0; color: var(--owly-ink, #17334a); font-size: .86rem; font-weight: 700; }
.industry-form input, .industry-form select, .industry-form textarea, .industry-actions select, .industry-paid-field input { width: 100%; min-width: 0; border: 1px solid var(--owly-border, #d8e2e9); border-radius: 8px; padding: 9px 10px; color: inherit; background: var(--owly-surface, #fff); font: inherit; }
.industry-form textarea { resize: vertical; }
.industry-checkbox { display: flex !important; grid-template-columns: 18px minmax(0, 1fr); align-items: center; gap: 9px !important; font-weight: 600 !important; }
.industry-checkbox input { width: 16px !important; min-width: 16px; margin: 0; accent-color: #198f91; }
.industry-form-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.industry-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 7px; }
.industry-primary, .industry-secondary, .industry-danger, .industry-refresh, .industry-tabs button, .industry-icon-button { border: 1px solid var(--owly-border, #d8e2e9); border-radius: 8px; padding: 8px 11px; background: var(--owly-surface, #fff); color: #147e85; font: inherit; font-weight: 750; cursor: pointer; }
.industry-primary { color: #fff; background: linear-gradient(120deg, #28a4a0, #247f9b); border-color: transparent; }
.industry-danger { color: #b53c34; }
.industry-refresh:disabled { opacity: .6; cursor: wait; }
.industry-tabs { display: flex; gap: 8px; border-bottom: 1px solid var(--owly-border, #d8e2e9); }
.industry-tabs button { border: 0; border-radius: 9px 9px 0 0; color: var(--owly-muted, #687d8d); }
.industry-tabs button.selected { color: #087d82; background: #e8f8f7; box-shadow: inset 0 -2px #1ba19b; }
.industry-tabs span { margin-left: 5px; font-size: .76rem; }
.industry-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 0; border-bottom: 1px solid var(--owly-border, #d8e2e9); }
.industry-row:last-child { border-bottom: 0; }
.industry-record-main { display: grid; gap: 5px; min-width: 0; }
.industry-record-main strong { line-height: 1.35; }
.industry-record-main small, .industry-row small { color: var(--owly-muted, #687d8d); line-height: 1.4; }
.industry-pill { display: inline-flex; width: fit-content; align-items: center; border-radius: 999px; padding: 4px 8px; color: #087c68; background: #e6f6f0; font-size: .74rem; font-weight: 750; }
.industry-pill.muted { color: #697883; background: #eef1f3; }
.industry-pill.warning { color: #9c5a00; background: #fff1d5; }
.industry-amount { color: #087e83; }
.industry-card-head { margin-bottom: 9px; }
.industry-card-head span { color: var(--owly-muted, #687d8d); font-size: .86rem; }
.industry-empty { padding: 16px 4px; color: var(--owly-muted, #687d8d); }
.industry-alert { padding: 11px 14px; border-radius: 9px; margin: 0; }
.industry-alert.error { color: #a52b2b; background: #fff0ef; }
.industry-alert.success { color: #087c68; background: #e6f6f0; }
.industry-line-items { display: grid; gap: 8px; }
.industry-quote-line { display: grid; grid-template-columns: minmax(100px, 1fr) 64px minmax(95px, .8fr) 30px; align-items: end; gap: 6px; }
.industry-quote-line label { font-size: .78rem; }
.industry-icon-button { padding: 7px; color: #a52b2b; }
.industry-total { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 9px; color: #087e83; background: #e8f8f7; }
.industry-total span { font-size: .82rem; }
.industry-paid-field { width: 132px; font-size: .73rem; }
.industry-paid-field input { padding: 6px 8px; }
.industry-link { width: fit-content; border: 0; padding: 0; color: #14838a; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.industry-payment-history { display: grid; gap: 4px; padding: 8px 10px; border-radius: 8px; background: #f0f7f8; }
.industry-method { border: 1px solid var(--owly-border, #d8e2e9); border-radius: 8px; padding: 7px; background: var(--owly-surface, #fff); color: inherit; }
.crm-dark .industry-workspace { color: #eff6f7; }
.crm-dark .industry-heading { border-color: #39464b; }
.crm-dark .industry-card { background: #20272a; border-color: #39464b; }
.crm-dark .industry-form label, .crm-dark .industry-paid-field { color: #eaf0f2; }
.crm-dark .industry-form input, .crm-dark .industry-form select, .crm-dark .industry-form textarea, .crm-dark .industry-actions select, .crm-dark .industry-paid-field input { color: #eff6f7; background: #171d20; border-color: #465258; }
.crm-dark .industry-tabs { border-color: #39464b; }
.crm-dark .industry-tabs button.selected, .crm-dark .industry-total { background: #173f41; color: #9be5df; }
.crm-dark .industry-row { border-color: #39464b; }
.crm-dark .industry-payment-history { background: #182d30; }
.crm-dark .industry-primary, .crm-dark .industry-secondary, .crm-dark .industry-danger, .crm-dark .industry-refresh, .crm-dark .industry-icon-button { background-color: #20272a; }
@media (max-width: 980px) { .industry-columns { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .industry-row { align-items: flex-start; flex-direction: column; } .industry-actions { justify-content: flex-start; } .industry-form-row { grid-template-columns: 1fr; } .industry-quote-line { grid-template-columns: minmax(0, 1fr) 54px 90px 28px; } .industry-paid-field { width: 100%; } }
</style>
