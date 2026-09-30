<script setup>
import { computed, onMounted, ref } from "vue";
import { apiFetch } from "./api-client.js";
import { formatDate, formatDateTime, t } from "./i18n.js";
import { workQueueItems } from "./work-queue-utils.js";

const props = defineProps({ apiBase: { type: String, default: "/api" }, modules: { type: Object, default: () => ({}) } });
const emit = defineEmits(["open"]);
const sections = [
  { key: "overdue", title: "Phiếu quá hạn" },
  { key: "unassigned", title: "Hội thoại chưa phân công" },
  { key: "appointments", title: "Lịch hẹn sắp tới" },
  { key: "quotes", title: "Báo giá cần theo dõi" },
  { key: "documents", title: "Tài liệu nạp lỗi" },
];
const data = ref({ tickets: [], conversations: [], appointments: [], quotes: [], documents: [], runs: {} });
const errors = ref({});
const loading = ref(false);
const items = computed(() => workQueueItems(data.value));
const enabled = (key) => !((key === "appointments" && props.modules.appointments === false)
  || (key === "quotes" && props.modules.projects === false));

async function get(path) {
  const response = await apiFetch(`${props.apiBase}${path}`);
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function getAll(path, limit) {
  const all = [];
  for (let offset = 0; ; offset += limit) {
    const separator = path.includes("?") ? "&" : "?";
    const response = await get(`${path}${separator}limit=${limit}&offset=${offset}`);
    const page = Array.isArray(response) ? response : response.items || [];
    all.push(...page);
    if (page.length < limit || (!Array.isArray(response) && response.has_more === false)) break;
  }
  return all;
}

async function load() {
  loading.value = true;
  errors.value = {};
  const loaders = {
    overdue: () => getAll("/tickets", 500),
    unassigned: () => getAll("/conversations", 50),
    appointments: () => getAll("/appointments", 500),
    quotes: () => getAll("/commercial/quotes", 500),
    documents: async () => {
      const result = await get("/documents");
      const docs = result.documents || [];
      const runs = {};
      await Promise.all(docs.map(async (doc) => {
        try { runs[doc.id] = (await get(`/documents/${doc.id}/runs`)).items?.[0] || null; }
        catch { runs[doc.id] = null; }
      }));
      return { docs, runs };
    },
  };
  const results = await Promise.all(sections.filter((section) => enabled(section.key)).map(async (section) => {
    try { return [section.key, await loaders[section.key]()]; }
    catch (error) { return [section.key, error]; }
  }));
  for (const [key, result] of results) {
    if (result instanceof Error) {
      errors.value[key] = result.status === 403 ? "Không đủ quyền xem dữ liệu này." : "Chưa tải được dữ liệu. Hãy thử lại.";
      continue;
    }
    if (key === "documents") {
      data.value.documents = result.docs;
      data.value.runs = result.runs;
    } else {
      data.value[{ overdue: "tickets", unassigned: "conversations", appointments: "appointments", quotes: "quotes" }[key]] = result;
    }
  }
  loading.value = false;
}

onMounted(load);
</script>

<template>
  <section class="work-queue" aria-labelledby="work-queue-title">
    <header class="work-queue-header">
      <div><h2 id="work-queue-title">{{ t("Việc cần xử lý") }}</h2><p>{{ t("Các việc cần chú ý từ dữ liệu hiện có của shop.") }}</p></div>
      <button type="button" :disabled="loading" @click="load">{{ t(loading ? "Đang tải..." : "Làm mới") }}</button>
    </header>
    <div class="work-queue-grid">
      <section v-for="section in sections.filter((entry) => enabled(entry.key))" :key="section.key" class="work-queue-card" :aria-labelledby="`work-${section.key}`">
        <h3 :id="`work-${section.key}`">{{ t(section.title) }} <span v-if="!loading && !errors[section.key]">{{ items[section.key].length }}</span></h3>
        <p v-if="loading" role="status">{{ t("Đang tải...") }}</p>
        <div v-else-if="errors[section.key]" class="work-queue-error" role="alert"><p>{{ t(errors[section.key]) }}</p><button type="button" @click="load">{{ t("Thử lại") }}</button></div>
        <p v-else-if="!items[section.key].length" class="work-queue-empty">{{ t("Không có việc cần xử lý trong mục này.") }}</p>
        <ul v-else>
          <li v-for="item in items[section.key]" :key="`${item.kind}-${item.id}`">
            <button type="button" @click="emit('open', item)"><strong>{{ item.title }}</strong><small v-if="item.time">{{ item.kind === 'quote' ? formatDate(item.time) : formatDateTime(item.time) }}</small><span aria-hidden="true">›</span></button>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>

<style scoped>
.work-queue { padding: 18px; width: min(100%, 1380px); margin: auto; }
.work-queue-header { display: flex; align-items: start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.work-queue-header h2 { margin: 0 0 6px; }
.work-queue-header p { margin: 0; color: var(--owly-muted, #687d8d); }
.work-queue-header button, .work-queue-error button { padding: 9px 14px; border: 1px solid var(--owly-border, #d8e2e9); border-radius: 8px; background: var(--owly-surface, white); color: inherit; cursor: pointer; }
.work-queue-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 350px), 1fr)); gap: 16px; }
.work-queue-card { min-width: 0; padding: 18px; border: 1px solid var(--owly-border, #d8e2e9); border-radius: 12px; background: var(--owly-surface, white); }
.work-queue-card h3 { display: flex; justify-content: space-between; gap: 10px; margin: 0 0 14px; font-size: 1.08rem; }
.work-queue-card h3 span { color: var(--owly-muted, #687d8d); }
.work-queue-card ul { margin: 0; padding: 0; list-style: none; max-height: 450px; overflow: auto; }
.work-queue-card li + li { border-top: 1px solid var(--owly-border, #d8e2e9); }
.work-queue-card li button { display: grid; grid-template-columns: minmax(0, 1fr) auto; width: 100%; gap: 4px 10px; padding: 12px 2px; border: 0; background: none; color: inherit; text-align: left; cursor: pointer; }
.work-queue-card li strong { overflow-wrap: anywhere; }
.work-queue-card li small { grid-column: 1; color: var(--owly-muted, #687d8d); }
.work-queue-card li span { grid-column: 2; grid-row: 1 / 3; align-self: center; font-size: 1.5rem; }
.work-queue-card li button:focus-visible, .work-queue-header button:focus-visible, .work-queue-error button:focus-visible { outline: 2px solid #17888c; outline-offset: 2px; }
.work-queue-error { color: #b53c34; }
.work-queue-empty { color: var(--owly-muted, #687d8d); }
@media (max-width: 620px) { .work-queue { padding: 12px; } .work-queue-header { align-items: stretch; flex-direction: column; } .work-queue-header button { align-self: flex-start; } }
</style>
