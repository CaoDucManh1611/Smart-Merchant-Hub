<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { CHANNEL_LABELS } from './channel-utils.js';

const props = defineProps({
  request: { type: Function, required: true },
  baseUrl: { type: String, default: '/api' },
  channel: { type: String, default: '' },
  error: { type: [String, Object], default: '' },
});
const emit = defineEmits(['created']);
const providers = ref(Object.hasOwn(CHANNEL_LABELS, props.channel) ? [props.channel] : []);
const channelLimit = ref(0);
const channelMenu = ref(null);
function closeChannelMenu(event) {
  if (channelMenu.value && !channelMenu.value.contains(event.target)) channelMenu.value.open = false;
}
function escapeChannelMenu() {
  channelMenu.value.open = false;
  channelMenu.value.querySelector('summary').focus();
}
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
  if (!saving.value && channelLimit.value > 0 && Object.hasOwn(CHANNEL_LABELS, channel)) providers.value = [channel];
});

async function refresh(nextOffset = offset.value) {
  if (loading.value) return;
  loading.value = true;
  listError.value = '';
  try {
    const response = await props.request(`${endpoint.value}?limit=${limit}&offset=${nextOffset}`);
    if (!response.ok) throw new Error('list');
    const data = await response.json();
    channelLimit.value = Math.max(0, Math.min(6, Number(data.channel_limit) || 0));
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
  if (!providers.value.length || providers.value.length > channelLimit.value) {
    formError.value = `Chọn từ 1 đến ${channelLimit.value} kênh theo gói đang sử dụng.`;
    return;
  }
  if (!summary || summary.length > 2000) {
    formError.value = 'Vui lòng mô tả vấn đề trong 1–2000 ký tự.';
    return;
  }
  saving.value = true;
  try {
    const selected = [...providers.value].sort();
    const signature = JSON.stringify([selected, summary]);
    if (pending?.signature !== signature) {
      pending = { signature, key: globalThis.crypto.randomUUID() };
    }
    const response = await props.request(endpoint.value, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ providers: selected, description: summary, idempotency_key: pending.key }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (data.detail?.code === 'support_channel_limit') {
        channelLimit.value = data.detail.limit;
        formError.value = `Gói hiện tại cho phép tối đa ${channelLimit.value} kênh trong một yêu cầu. Hãy bỏ bớt kênh đã chọn.`;
        return;
      }
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
onMounted(() => {
  refresh(0);
  document.addEventListener('pointerdown', closeChannelMenu);
});
onUnmounted(() => document.removeEventListener('pointerdown', closeChannelMenu));
</script>

<template>
  <details class="connection-support" aria-label="Hỗ trợ kết nối kênh">
    <summary class="support-trigger">
      <span class="support-trigger-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 13v-1a8 8 0 0 1 16 0v1M4 12H3v6h4v-6H4Zm16 0h1v6h-4v-6h3Zm0 6c0 3-3 3-6 3" /></svg></span>
      <span class="support-trigger-copy"><strong>Hỗ trợ kết nối kênh</strong><small>Gửi vấn đề và theo dõi phản hồi từ đội hỗ trợ</small></span>
      <span class="support-count" v-if="total">{{ total }} yêu cầu</span>
      <span class="support-trigger-action"><span class="support-open-label">Mở hỗ trợ</span><span class="support-close-label">Thu gọn</span><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg></span>
    </summary>
    <div class="support-content">
    <section class="support-form-panel" aria-label="Gửi yêu cầu hỗ trợ">
    <h3>Bạn đang gặp vấn đề gì?</h3>
    <p v-if="error" role="status">Kết nối chưa thành công. Bạn có thể gửi yêu cầu để đội hỗ trợ kiểm tra.</p>
    <p>Yêu cầu được gửi đến đội hỗ trợ nền tảng và gắn với cửa hàng đang đăng nhập.</p>
    <form @submit.prevent="submit" :aria-busy="saving">
      <fieldset class="support-channels" aria-describedby="support-channel-limit">
        <legend>Kênh cần hỗ trợ</legend>
        <p id="support-channel-limit" role="status">Đã chọn {{ providers.length }} / {{ channelLimit }} kênh · Chung một yêu cầu hỗ trợ</p>
        <details ref="channelMenu" class="support-channel-select" @keydown.esc.stop.prevent="escapeChannelMenu"
          @focusout="!$event.currentTarget.contains($event.relatedTarget) && ($event.currentTarget.open = false)">
          <summary aria-label="Chọn nền tảng cần hỗ trợ">
            <span>{{ providers.length ? providers.map(key => CHANNEL_LABELS[key]).join(', ') : 'Chọn nền tảng cần hỗ trợ' }}</span>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg>
          </summary>
        <div class="support-channel-options">
          <label v-for="(label, key) in CHANNEL_LABELS" :key="key" :class="{ selected: providers.includes(key) }">
            <input type="checkbox" v-model="providers" :value="key"
              :disabled="saving || loading || (!providers.includes(key) && providers.length >= channelLimit)" />
            <span>{{ label }}</span>
          </label>
        </div>
        </details>
        <p v-if="!loading && !channelLimit">Gói hiện tại chưa có quyền kết nối kênh.</p>
      </fieldset>
      <label>Mô tả vấn đề
        <textarea v-model="description" rows="4" maxlength="2000" required :disabled="saving"
          :aria-describedby="formError ? 'connection-support-hint connection-support-error' : 'connection-support-hint'" :aria-invalid="!!formError" />
      </label>
      <p id="connection-support-hint">Mô tả thao tác và điều bạn gặp phải. Không gửi mật khẩu, mã truy cập, đường dẫn hay nội dung lỗi kỹ thuật.</p>
      <p v-if="formError" id="connection-support-error" role="alert" class="support-error">{{ formError }}</p>
      <p v-if="success" role="status" class="support-success">{{ success }}</p>
      <button type="submit" :disabled="saving || loading || !providers.length || providers.length > channelLimit">{{ saving ? 'Đang gửi…' : 'Gửi yêu cầu hỗ trợ' }}</button>
    </form>
    </section>
    <section class="support-history-panel" aria-label="Theo dõi yêu cầu">
    <div class="support-list-heading">
      <h3>Yêu cầu của cửa hàng</h3>
      <button type="button" @click="refresh()" :disabled="saving || loading">{{ loading ? 'Đang tải…' : 'Làm mới' }}</button>
    </div>
    <p v-if="listError" role="alert" class="support-error">{{ listError }}</p>
    <div v-else-if="!loading && !items.length" class="support-empty"><strong>Chưa có yêu cầu hỗ trợ</strong><p>Khi bạn gửi yêu cầu, trạng thái và phản hồi sẽ xuất hiện tại đây.</p></div>
    <ul :aria-busy="loading">
      <li v-for="ticket in items" :key="ticket.id">
        <div><strong>#{{ ticket.id }} · {{ (ticket.providers || [ticket.provider]).map(key => CHANNEL_LABELS[key]).join(' · ') }}</strong> <span>{{ statusLabels[ticket.status] }}</span></div>
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
    </div>
  </details>
</template>

<style scoped>
.connection-support { --support-bg: var(--owly-surface, #fff); --support-text: var(--owly-text, #172033); --support-border: var(--owly-border, #d4e3e7); --support-error: #a51d24; --support-success: #17633d; border: 1px solid var(--support-border); border-radius: 14px; background: var(--support-bg); color: var(--support-text); width: 100%; grid-column: 1 / -1; box-sizing: border-box; min-width: 0; overflow-wrap: anywhere; }
.support-trigger { display: flex; align-items: center; gap: 12px; padding: 14px 18px; list-style: none; }
.connection-support { border-color: var(--owly-border, #d4e3e7); }
.support-trigger::-webkit-details-marker { display: none; }
.support-trigger-icon { display: grid; place-items: center; width: 38px; height: 38px; flex-shrink: 0; border-radius: 10px; background: #e8f7f5; color: #087f80; }
.support-trigger-icon svg { width: 22px; height: 22px; }
.support-trigger-copy { display: grid; gap: 3px; min-width: 0; }
.support-trigger-copy strong { font-size: 15px; }
.support-trigger-copy small { font-size: 12px; opacity: .8; }
.support-trigger-action { margin-left: auto; display: flex; align-items: center; gap: 8px; color: #087f80; font-size: 13px; font-weight: 600; white-space: nowrap; }
.support-trigger-action svg { width: 18px; height: 18px; transition: transform 180ms ease; }
.support-count { border: 1px solid var(--support-border); border-radius: 20px; padding: 4px 10px; font-size: 12px; white-space: nowrap; }
.support-close-label { display: none; }
.connection-support[open] .support-close-label { display: inline; }
.connection-support[open] .support-open-label { display: none; }
.connection-support[open] .support-trigger-action svg { transform: rotate(180deg); }
.support-content { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; padding: 22px; border-top: 1px solid var(--support-border); }
.support-content > section { min-width: 0; }
.support-content h3 { font-size: 15px; margin: 0 0 12px; }
.support-history-panel { border-left: 1px solid var(--support-border); padding-left: 24px; }
.support-history-panel .support-list-heading { margin-top: 0; }
.support-content p { font-size: 13px; }
.support-empty { border: 1px dashed var(--support-border); border-radius: 12px; padding: 28px 20px; text-align: center; margin-top: 18px; }
.support-empty strong { font-size: 14px; }
.support-content button[type='submit'] { background: #087f80; color: #fff; border-color: #087f80; font-weight: 600; }
.support-content label { font-size: 13px; font-weight: 600; }
.support-channels { border: 0; padding: 0; margin: 0; min-width: 0; }
.support-channels legend { font-size: 13px; font-weight: 600; }
.support-channel-select { position: relative; }
.support-channel-select > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; padding: 8px 12px; box-sizing: border-box; border: 1px solid var(--support-border); border-radius: 8px; list-style: none; font-size: 13px; }
.support-channel-select > summary::-webkit-details-marker { display: none; }
.support-channel-select > summary span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.support-channel-select > summary svg { width: 18px; height: 18px; flex-shrink: 0; }
.support-channel-select[open] > summary { border-color: #087f80; }
.support-channel-select[open] > summary svg { transform: rotate(180deg); }
.support-channel-options { position: absolute; z-index: 20; top: calc(100% + 6px); left: 0; right: 0; display: grid; gap: 2px; max-height: 260px; overflow-y: auto; padding: 6px; background: var(--support-bg); border: 1px solid var(--support-border); border-radius: 10px; box-shadow: 0 10px 24px #17203320; }
.support-channel-options label { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 0 10px; border-radius: 6px; cursor: pointer; }
.support-channel-options label.selected, .support-channel-options label:hover { background: color-mix(in srgb, #087f80 10%, var(--support-bg)); }
.support-channel-options input { width: 16px; height: 16px; flex-shrink: 0; accent-color: #087f80; }
.support-channel-options label:has(input:disabled) { opacity: .6; cursor: not-allowed; }
.support-channel-options input:focus-visible { outline: 3px solid #3980e8; outline-offset: 3px; }
.support-content select { width: 100%; box-sizing: border-box; }
.support-history-panel > ul { max-height: 440px; overflow: auto; }
.connection-support[open] .support-content { animation: support-reveal 160ms ease-out; }
@keyframes support-reveal { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .connection-support[open] .support-content { animation: none; } .support-trigger-action svg { transition: none; } }
@media (max-width: 800px) { .support-content { grid-template-columns: 1fr; padding: 16px; } .support-history-panel { border-left: 0; border-top: 1px solid var(--support-border); padding: 20px 0 0; } .support-trigger-copy small { display: none; } }
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
summary { cursor: pointer; }
p { line-height: 1.6; white-space: pre-wrap; }
:global([data-theme='dark'] .connection-support), :global(.dark .connection-support), :global(.crm-dark .connection-support) { --support-bg: #182235; --support-text: #edf2fa; --support-border: #8594ac; --support-error: #ffb5b8; --support-success: #92e1b4; }
@media (prefers-color-scheme: dark) { .connection-support { --support-bg: #182235; --support-text: #edf2fa; --support-border: #8594ac; --support-error: #ffb5b8; --support-success: #92e1b4; } :global([data-theme='light'] .connection-support), :global(.crm-app:not(.crm-dark) .connection-support) { --support-bg: #fff; --support-text: #172033; --support-border: #718096; --support-error: #a51d24; --support-success: #17633d; } }
@media (max-width: 480px) { .support-trigger { padding: 12px; gap: 8px; } .support-count { display: none; } .support-trigger-action > span { display: none !important; } }
</style>
