<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { CHANNEL_LABELS } from './channel-utils.js';

const props = defineProps({
  request: { type: Function, required: true },
  baseUrl: { type: String, default: '/api' },
  channel: { type: String, default: '' },
  error: { type: [String, Object], default: '' },
});
const emit = defineEmits(['created']);
const provider = ref(Object.hasOwn(CHANNEL_LABELS, props.channel) ? props.channel : 'facebook');
const description = ref('');
const saving = ref(false);
const loading = ref(false);
const formError = ref('');
const listError = ref('');
const success = ref('');
const items = ref([]);
const total = ref(0);
const offset = ref(0);
const limit = 20;
let pending = null;
const statusLabels = { open: 'Đã tiếp nhận', in_progress: 'Đang xử lý', resolved: 'Đã giải quyết', closed: 'Đã đóng' };
const endpoint = computed(() => `${props.baseUrl.replace(/\/$/, '')}/support/requests`);
watch(() => props.channel, (channel) => {
  if (!saving.value && Object.hasOwn(CHANNEL_LABELS, channel)) provider.value = channel;
});

async function refresh(nextOffset = offset.value) {
  if (loading.value) return;
  loading.value = true;
  listError.value = '';
  try {
    const response = await props.request(`${endpoint.value}?limit=${limit}&offset=${nextOffset}`);
    if (!response.ok) throw new Error('list');
    const data = await response.json();
    items.value = data.items;
    total.value = data.total;
    offset.value = nextOffset;
  } catch {
    listError.value = 'Chưa thể tải yêu cầu hỗ trợ. Vui lòng thử làm mới.';
  } finally {
    loading.value = false;
  }
}

async function submit() {
  if (saving.value) return;
  formError.value = '';
  success.value = '';
  const summary = description.value.trim();
  if (!summary || summary.length > 2000) {
    formError.value = 'Vui lòng mô tả vấn đề trong 1–2000 ký tự.';
    return;
  }
  saving.value = true;
  try {
    const signature = JSON.stringify([provider.value, summary]);
    if (pending?.signature !== signature) {
      pending = { signature, key: globalThis.crypto.randomUUID() };
    }
    const response = await props.request(endpoint.value, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: provider.value, description: summary, idempotency_key: pending.key }),
    });
    if (!response.ok) {
      formError.value = response.status === 422
        ? 'Hãy dùng mô tả ngắn, không kèm đường dẫn, mã truy cập hoặc nội dung lỗi kỹ thuật.'
        : response.status === 409
          ? 'Yêu cầu đang trùng hoặc đã thay đổi. Vui lòng kiểm tra danh sách và thử lại.'
          : response.status === 401
            ? 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
            : 'Chưa thể gửi yêu cầu. Vui lòng thử lại; nội dung đã được giữ lại.';
      return;
    }
    const ticket = await response.json();
    pending = null;
    description.value = '';
    success.value = `Đã tiếp nhận yêu cầu #${ticket.id}. Bạn có thể theo dõi bên dưới.`;
    emit('created', ticket);
    await refresh(0);
  } catch {
    formError.value = 'Chưa thể gửi yêu cầu. Vui lòng thử lại; nội dung đã được giữ lại.';
  } finally {
    saving.value = false;
  }
}
onMounted(() => refresh(0));
</script>

<template>
  <section class="connection-support" aria-label="Hỗ trợ kết nối kênh">
    <h2>Hỗ trợ kết nối kênh</h2>
    <p v-if="error" role="status">Kết nối chưa thành công. Bạn có thể gửi yêu cầu để đội hỗ trợ kiểm tra.</p>
    <p>Yêu cầu được gửi đến đội hỗ trợ nền tảng và gắn với cửa hàng đang đăng nhập.</p>
    <form @submit.prevent="submit" :aria-busy="saving">
      <label>Kênh cần hỗ trợ
        <select v-model="provider" :disabled="saving" required>
          <option v-for="(label, key) in CHANNEL_LABELS" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <label>Mô tả vấn đề
        <textarea v-model="description" rows="4" maxlength="2000" required :disabled="saving"
          :aria-describedby="formError ? 'connection-support-hint connection-support-error' : 'connection-support-hint'" :aria-invalid="!!formError" />
      </label>
      <p id="connection-support-hint">Mô tả thao tác và điều bạn gặp phải. Không gửi mật khẩu, mã truy cập, đường dẫn hay nội dung lỗi kỹ thuật.</p>
      <p v-if="formError" id="connection-support-error" role="alert" class="support-error">{{ formError }}</p>
      <p v-if="success" role="status" class="support-success">{{ success }}</p>
      <button type="submit" :disabled="saving || loading">{{ saving ? 'Đang gửi…' : 'Gửi yêu cầu hỗ trợ' }}</button>
    </form>
    <div class="support-list-heading">
      <h3>Yêu cầu của cửa hàng</h3>
      <button type="button" @click="refresh()" :disabled="saving || loading">{{ loading ? 'Đang tải…' : 'Làm mới' }}</button>
    </div>
    <p v-if="listError" role="alert" class="support-error">{{ listError }}</p>
    <p v-else-if="!loading && !items.length">Chưa có yêu cầu hỗ trợ.</p>
    <ul :aria-busy="loading">
      <li v-for="ticket in items" :key="ticket.id">
        <div><strong>#{{ ticket.id }} · {{ CHANNEL_LABELS[ticket.provider] }}</strong> <span>{{ statusLabels[ticket.status] }}</span></div>
        <p>{{ ticket.description }}</p>
        <p v-if="ticket.response"><strong>Phản hồi:</strong> {{ ticket.response }}</p>
        <details>
          <summary>Lịch sử xử lý</summary>
          <ol>
            <li v-for="entry in ticket.history" :key="entry.id">
              {{ statusLabels[entry.to_status] }} · {{ new Date(entry.created_at + (entry.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString('vi-VN') }}
              <p v-if="entry.response">{{ entry.response }}</p>
            </li>
          </ol>
        </details>
      </li>
    </ul>
    <nav v-if="total > limit" aria-label="Trang yêu cầu hỗ trợ">
      <button type="button" :disabled="saving || loading || offset === 0" @click="refresh(Math.max(0, offset - limit))">Trước</button>
      <span>{{ offset + 1 }}–{{ Math.min(offset + limit, total) }} / {{ total }}</span>
      <button type="button" :disabled="saving || loading || offset + limit >= total" @click="refresh(offset + limit)">Sau</button>
    </nav>
  </section>
</template>

<style scoped>
.connection-support { --support-bg: #fff; --support-text: #172033; --support-border: #718096; --support-error: #a51d24; --support-success: #17633d; padding: 24px; border: 1px solid var(--support-border); border-radius: 16px; background: var(--support-bg); color: var(--support-text); max-width: 760px; overflow-wrap: anywhere; }
form, label { display: grid; gap: 8px; }
form { gap: 16px; }
select, textarea, button { font: inherit; color: inherit; min-height: 44px; border: 1px solid var(--support-border); border-radius: 8px; padding: 10px 12px; background: var(--support-bg); }
textarea { width: 100%; box-sizing: border-box; resize: vertical; }
button { cursor: pointer; }
button:disabled { cursor: wait; opacity: .65; }
:is(button, select, textarea, summary):focus-visible { outline: 3px solid #3980e8; outline-offset: 3px; }
.support-error { color: var(--support-error); }
.support-success { color: var(--support-success); }
.support-list-heading, nav { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-top: 24px; }
ul { list-style: none; padding: 0; }
ul > li { border-top: 1px solid var(--support-border); padding: 16px 0; }
li > div { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
summary { cursor: pointer; padding: 8px 0; }
p { line-height: 1.6; white-space: pre-wrap; }
:global([data-theme='dark'] .connection-support), :global(.dark .connection-support), :global(.crm-dark .connection-support) { --support-bg: #182235; --support-text: #edf2fa; --support-border: #8594ac; --support-error: #ffb5b8; --support-success: #92e1b4; }
@media (prefers-color-scheme: dark) { .connection-support { --support-bg: #182235; --support-text: #edf2fa; --support-border: #8594ac; --support-error: #ffb5b8; --support-success: #92e1b4; } :global([data-theme='light'] .connection-support), :global(.crm-app:not(.crm-dark) .connection-support) { --support-bg: #fff; --support-text: #172033; --support-border: #718096; --support-error: #a51d24; --support-success: #17633d; } }
@media (max-width: 480px) { .connection-support { padding: 16px; } }
</style>
