<script setup>
import { onMounted, ref, watch } from 'vue';
import { formatDateTime, t } from './i18n.js';
const props = defineProps({ request: Function, baseUrl: String, active: Boolean, adminId: Number });
const emit = defineEmits(['count']);
const items = ref([]), total = ref(0), offset = ref(0), loading = ref(false), saving = ref(null), error = ref(''), notice = ref(''), drafts = ref({});
const labels = { open: 'Mới gửi', in_progress: 'Đang xử lý', resolved: 'Đã xử lý', closed: 'Đã đóng' };
const transitions = { open: ['in_progress'], in_progress: ['resolved'], resolved: ['in_progress', 'closed'], closed: [] };
async function load() {
  if (loading.value) return;
  loading.value = true; error.value = '';
  try {
    const result = await props.request(`${props.baseUrl}/platform/support-requests?limit=20&offset=${offset.value}`);
    if (!result.ok) throw new Error();
    const data = await result.json(); items.value = data.items; total.value = data.total; emit('count', data.total);
  } catch { error.value = 'Không tải được yêu cầu hỗ trợ. Vui lòng thử lại.'; }
  finally { loading.value = false; }
}
async function update(item, status) {
  if (saving.value !== null) return;
  const response = (drafts.value[item.id] || '').trim();
  if (!status && !response) return;
  saving.value = item.id; error.value = ''; notice.value = '';
  try {
    const payload = {};
    if (status) payload.status = status;
    if (status === 'in_progress' && props.adminId) payload.assigned_admin_id = props.adminId;
    if (response) payload.response = response;
    const result = await props.request(`${props.baseUrl}/platform/support-requests/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!result.ok) throw new Error();
    const updated = await result.json(); items.value = items.value.map(row => row.id === updated.id ? updated : row);
    drafts.value[item.id] = ''; notice.value = 'Đã cập nhật yêu cầu hỗ trợ.';
  } catch { error.value = 'Chưa cập nhật được. Hãy làm mới và kiểm tra phản hồi không chứa link, mật khẩu hay mã truy cập.'; }
  finally { saving.value = null; }
}
async function page(delta) { offset.value += delta; await load(); }
watch(() => props.active, active => { if (active) load(); }, { immediate: true });
onMounted(load);
</script>

<template>
  <section class="platform-admin-panel platform-support">
    <div class="platform-admin-panel-heading"><div><h3>{{ t('Yêu cầu hỗ trợ') }}</h3><p>{{ total }} {{ t('yêu cầu') }}</p></div><button class="settings-refresh" :disabled="loading || saving !== null" @click="load">{{ t('Làm mới') }}</button></div>
    <p v-if="error" class="settings-notice team-error" role="alert">{{ t(error) }}</p>
    <p v-if="notice" class="settings-notice" role="status">{{ t(notice) }}</p>
    <p v-if="loading" role="status">{{ t('Đang tải...') }}</p>
    <p v-else-if="!items.length">{{ t('Chưa có yêu cầu hỗ trợ.') }}</p>
    <details v-for="item in items" :key="item.id" class="support-admin-ticket">
      <summary class="support-ticket-summary">
        <span class="support-ticket-overview"><strong>#{{ item.id }} · Shop #{{ item.business_id }}</strong><span>{{ (item.providers || [item.provider]).join(' · ') }} · {{ formatDateTime(item.created_at) }}</span><span class="support-ticket-preview">{{ item.description }}</span></span>
        <span class="support-ticket-status">{{ t(labels[item.status]) }}</span>
      </summary>
      <div class="support-ticket-body">
      <p class="support-admin-description">{{ item.description }}</p>
      <p v-if="item.assigned_admin_id">{{ t('Admin phụ trách') }} #{{ item.assigned_admin_id }}</p>
      <p v-if="item.response"><strong>{{ t('Phản hồi') }}:</strong> {{ item.response }}</p>
      <label v-if="item.status !== 'closed'">{{ t('Phản hồi cho shop') }}<textarea v-model="drafts[item.id]" rows="3" maxlength="2000" :disabled="saving !== null"></textarea></label>
      <div class="support-admin-actions">
        <button v-if="item.status !== 'closed'" class="settings-refresh" :disabled="saving !== null || !drafts[item.id]?.trim()" @click="update(item)">{{ t('Gửi phản hồi') }}</button>
        <button v-for="status in transitions[item.status]" :key="status" class="primary-btn" :disabled="saving !== null" @click="update(item, status)">{{ t(status === 'in_progress' ? 'Nhận xử lý' : labels[status]) }}</button>
      </div>
      <details v-if="item.history?.length"><summary>{{ t('Lịch sử xử lý') }}</summary><p v-for="event in item.history" :key="event.id">{{ formatDateTime(event.created_at) }} · {{ t(labels[event.to_status]) }} · Admin #{{ event.actor_user_id }}<span v-if="event.response"> · {{ event.response }}</span></p></details>
      </div>
    </details>
    <div class="support-admin-actions"><button class="settings-refresh" :disabled="offset === 0 || loading || saving !== null" @click="page(-20)">{{ t('Trang trước') }}</button><span>{{ offset + (items.length ? 1 : 0) }}–{{ offset + items.length }} / {{ total }}</span><button class="settings-refresh" :disabled="offset + 20 >= total || loading || saving !== null" @click="page(20)">{{ t('Trang sau') }}</button></div>
  </section>
</template>

<style scoped>
.support-admin-ticket { border: 1px solid var(--owly-border, #d4e3e7); border-radius: 12px; margin-bottom: 10px; }
.support-ticket-summary { display: flex; align-items: center; gap: 12px; padding: 14px 16px; list-style: none; }
.support-ticket-summary::-webkit-details-marker { display: none; }
.support-ticket-summary::after { content: '›'; font-size: 22px; flex: 0 0 16px; text-align: center; }
.support-admin-ticket[open] > summary::after { transform: rotate(90deg); }
.support-ticket-summary:focus-visible { outline: 2px solid #279c9e; outline-offset: 2px; border-radius: 12px; }
.support-ticket-overview { display: grid; gap: 4px; flex: 1; min-width: 0; }
.support-ticket-overview > span { font-size: 13px; overflow-wrap: anywhere; }
.support-ticket-preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.support-ticket-status { color: var(--owly-primary, #279c9e); font-size: 13px; font-weight: 700; flex-shrink: 0; }
.support-ticket-body { padding: 0 16px 16px; border-top: 1px solid var(--owly-border, #d4e3e7); }
.support-admin-ticket header, .support-admin-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.support-admin-ticket header span { color: #17888c; font-weight: 700; }
.support-admin-ticket p { font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.support-admin-description { white-space: pre-wrap; }
.support-admin-ticket label { display: grid; gap: 8px; font-size: 14px; }
.support-admin-ticket textarea { width: 100%; box-sizing: border-box; padding: 12px; border: 1px solid var(--owly-border, #d4e3e7); border-radius: 8px; background: var(--owly-surface, #fff); color: inherit; font: inherit; resize: vertical; }
.support-admin-actions { justify-content: flex-end; margin-top: 14px; }
.support-admin-ticket details { margin-top: 16px; }
.support-admin-ticket summary { cursor: pointer; }
</style>
