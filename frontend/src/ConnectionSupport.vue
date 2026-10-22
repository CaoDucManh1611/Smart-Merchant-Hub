<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { CHANNEL_LABELS } from './channel-utils.js';
import { formatDateTime } from './i18n.js';

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
const channelMenuOpen = ref(false);
function closeChannelMenu(event) {
  if (channelMenu.value && !channelMenu.value.contains(event.target)) channelMenuOpen.value = false;
}
function escapeChannelMenu() {
  channelMenuOpen.value = false;
  channelMenu.value?.querySelector('button')?.focus();
}
function channelDisabled(key) {
  return saving.value || loading.value || (!providers.value.includes(key) && providers.value.length >= channelLimit.value);
}
function toggleChannel(key) {
  if (channelDisabled(key)) return;
  providers.value = providers.value.includes(key)
    ? providers.value.filter(provider => provider !== key)
    : [...providers.value, key];
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
    <section class="support-form-panel" aria-labelledby="support-form-title">
    <h3 id="support-form-title">Bạn đang gặp vấn đề gì?</h3>
    <p v-if="error" role="status">Kết nối chưa thành công. Bạn có thể gửi yêu cầu để đội hỗ trợ kiểm tra.</p>
    <p>Yêu cầu được gửi đến đội hỗ trợ nền tảng và gắn với cửa hàng đang đăng nhập.</p>
    <form @submit.prevent="submit" :aria-busy="saving">
      <fieldset class="support-channels" aria-describedby="support-channel-limit">
        <legend>Kênh cần hỗ trợ</legend>
        <p id="support-channel-limit" role="status">Đã chọn {{ providers.length }} / {{ channelLimit }} kênh · Chung một yêu cầu hỗ trợ</p>
        <div ref="channelMenu" class="support-channel-select" :class="{ open: channelMenuOpen }" @keydown.esc.stop.prevent="escapeChannelMenu"
          @focusout="!$event.currentTarget.contains($event.relatedTarget) && (channelMenuOpen = false)">
          <button type="button" class="support-channel-trigger" aria-label="Chọn nền tảng cần hỗ trợ"
            aria-controls="support-channel-options" :aria-expanded="channelMenuOpen" @click="channelMenuOpen = !channelMenuOpen">
            <span>{{ providers.length ? providers.map(key => CHANNEL_LABELS[key]).join(', ') : 'Chọn nền tảng cần hỗ trợ' }}</span>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg>
          </button>
        <div v-if="channelMenuOpen" id="support-channel-options" class="support-channel-options" role="group" aria-label="Nền tảng hỗ trợ">
          <button v-for="(label, key) in CHANNEL_LABELS" :key="key" type="button" class="support-channel-option"
            role="checkbox" :aria-checked="providers.includes(key)" :disabled="channelDisabled(key)"
            :class="{ selected: providers.includes(key) }" @click="toggleChannel(key)">
            <span class="support-channel-check" aria-hidden="true"><svg v-if="providers.includes(key)" viewBox="0 0 16 16"><path d="m3 8 3.2 3.2L13 4.5" /></svg></span>
            <span>{{ label }}</span>
          </button>
        </div>
        </div>
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
    <section class="support-history-panel" aria-labelledby="support-history-title">
    <div class="support-list-heading">
      <div class="support-history-title"><h3 id="support-history-title">Yêu cầu của cửa hàng</h3><span>{{ total }} yêu cầu</span></div>
      <button type="button" class="support-refresh" @click="refresh()" :disabled="saving || loading">{{ loading ? 'Đang tải…' : 'Làm mới' }}</button>
    </div>
    <p v-if="listError" role="alert" class="support-error">{{ listError }}</p>
    <div v-else-if="!loading && !items.length" class="support-empty"><strong>Chưa có yêu cầu hỗ trợ</strong><p>Khi bạn gửi yêu cầu, trạng thái và phản hồi sẽ xuất hiện tại đây.</p></div>
    <ul class="support-ticket-list" :aria-busy="loading">
      <li v-for="ticket in items" :key="ticket.id" class="support-ticket-item">
        <article>
          <header class="support-ticket-heading">
            <div class="support-ticket-meta"><strong>#{{ ticket.id }}</strong><time :datetime="ticket.created_at">{{ formatDateTime(ticket.created_at) }}</time></div>
            <span class="support-status" :class="`is-${ticket.status}`">{{ statusLabels[ticket.status] }}</span>
          </header>
          <div class="support-ticket-platforms" aria-label="Kênh được hỗ trợ">
            <span v-for="provider in (ticket.providers || [ticket.provider])" :key="provider">{{ CHANNEL_LABELS[provider] || provider }}</span>
          </div>
          <p class="support-ticket-description">{{ ticket.description }}</p>
          <div v-if="ticket.response" class="support-ticket-response"><strong>Phản hồi từ đội hỗ trợ</strong><p>{{ ticket.response }}</p></div>
        <details v-if="ticket.history?.length" class="support-ticket-history">
          <summary>Lịch sử xử lý <span>({{ ticket.history.length }})</span></summary>
          <ol>
            <li v-for="entry in ticket.history" :key="entry.id">
              <time :datetime="entry.created_at">{{ formatDateTime(entry.created_at) }}</time><strong>{{ statusLabels[entry.to_status] }}</strong>
              <p v-if="entry.response">{{ entry.response }}</p>
            </li>
          </ol>
        </details>
        </article>
      </li>
    </ul>
    <nav v-if="total > limit" class="support-pagination" aria-label="Trang yêu cầu hỗ trợ">
      <button type="button" :disabled="saving || loading || offset === 0" @click="refresh(Math.max(0, offset - limit))">Trước</button>
      <span>{{ offset + 1 }}–{{ Math.min(offset + limit, total) }} / {{ total }}</span>
      <button type="button" :disabled="saving || loading || offset + limit >= total" @click="refresh(offset + limit)">Sau</button>
    </nav>
    </section>
    </div>
  </details>
</template>

<style scoped>
.connection-support {
  --support-bg: var(--owly-surface, #fff);
  --support-panel: #eaf4f3;
  --support-card: #fff;
  --support-text: var(--owly-ink, #20364a);
  --support-muted: var(--owly-muted, #6a8093);
  --support-border: var(--owly-border, #d8e6ef);
  --support-accent: #248f8d;
  --support-accent-soft: #e2f2ef;
  --support-error: #a53b46;
  --support-error-soft: #fff0f0;
  --support-success: #24734b;
  --support-success-soft: #eaf6ee;
  --support-warning: #825b19;
  --support-warning-soft: #fbf3df;
  --support-focus: #248f8d;
  width: 100%;
  min-width: 0;
  grid-column: 1 / -1;
  margin-bottom: 12px;
  box-sizing: border-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  border: 1px solid var(--support-border);
  border-radius: 16px;
  background: var(--support-bg);
  color: var(--support-text);
}
.support-trigger { display:flex; align-items:center; gap:12px; min-height:68px; padding:14px 18px; border-radius:inherit; background:var(--support-panel); color:var(--support-text); list-style:none; cursor:pointer; }
.connection-support { border-color:var(--owly-border, #d4e3e7); }
.support-trigger::-webkit-details-marker { display:none; }
.support-trigger-icon { display:grid; place-items:center; width:40px; height:40px; flex-shrink:0; border-radius:12px; background:var(--support-accent-soft); color:var(--support-accent); }
.support-trigger-icon svg { width:22px; height:22px; }
.support-trigger-copy { display:grid; gap:3px; min-width:0; }
.support-trigger-copy strong { font-size:15px; }
.support-trigger-copy small { color:var(--support-muted); font-size:12px; }
.support-trigger-action { display:flex; align-items:center; gap:8px; margin-left:auto; color:var(--support-accent); font-size:13px; font-weight:650; white-space:nowrap; }
.support-trigger-action svg { width:18px; height:18px; transition:transform 180ms ease; }
.support-count { padding:5px 10px; border:1px solid var(--support-border); border-radius:999px; background:var(--support-card); font-size:12px; font-weight:600; white-space:nowrap; }
.support-close-label { display:none; }
.connection-support[open] > .support-trigger { border-bottom:1px solid var(--support-border); border-radius:15px 15px 0 0; }
.connection-support[open] .support-close-label { display:inline; }
.connection-support[open] .support-open-label { display:none; }
.connection-support[open] .support-trigger-action svg { transform:rotate(180deg); }
.support-content { display:grid; grid-template-columns:minmax(0, .92fr) minmax(0, 1.08fr); align-items:stretch; gap:28px; padding:22px; }
.support-content > section { min-width:0; }
.support-content h3 { margin:0; font-size:16px; line-height:1.4; }
.support-form-panel { padding:20px; border:1px solid var(--support-border); border-radius:14px; background:var(--support-panel); }
.support-form-panel > p { margin:10px 0 16px; color:var(--support-muted); font-size:13px; }
.support-content p { line-height:1.55; white-space:pre-wrap; }
.support-content form { display:grid; gap:14px; margin-top:18px; }
.support-content label { display:grid; gap:8px; font-size:13px; font-weight:650; }
.support-channels { min-width:0; margin:0; padding:0; border:0; }
.support-channels legend { margin-bottom:8px; font-size:13px; font-weight:650; }
.support-channel-limit { margin:0 0 10px; color:var(--support-muted); font-size:12px; }
.support-channel-select { position:relative; }
.support-channel-trigger { display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%; min-height:46px; padding:9px 12px; border:1px solid var(--support-border); border-radius:9px; background:var(--support-card); color:inherit; text-align:left; font:inherit; cursor:pointer; }
.support-channel-trigger span { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.support-channel-trigger svg { width:18px; height:18px; flex-shrink:0; transition:transform 160ms ease; }
.support-channel-select.open .support-channel-trigger { border-color:var(--support-accent); }
.support-channel-select.open .support-channel-trigger svg { transform:rotate(180deg); }
.support-channel-options { position:absolute; z-index:20; top:calc(100% + 6px); right:0; left:0; display:grid; gap:2px; max-height:260px; overflow-y:auto; padding:6px; border:1px solid var(--support-border); border-radius:10px; background:var(--support-card); box-shadow:0 12px 28px #10182830; }
.support-channel-option { display:flex; align-items:center; gap:10px; width:100%; min-height:42px; padding:0 10px; border:0; border-radius:7px; background:transparent; color:inherit; text-align:left; font:inherit; cursor:pointer; }
.support-channel-option.selected, .support-channel-option:hover:not(:disabled) { background:var(--support-accent-soft); }
.support-channel-check { display:grid; place-items:center; flex:0 0 17px; width:17px; height:17px; box-sizing:border-box; border:1px solid #8290a2; border-radius:4px; background:var(--support-card); color:#fff; }
.support-channel-check svg { width:14px; height:14px; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
.support-channel-option[aria-checked='true'] .support-channel-check { border-color:var(--support-accent); background:var(--support-accent); }
.support-content .support-channel-option:disabled { cursor:not-allowed; opacity:.6; }
.support-channel-option:focus-visible { outline:3px solid var(--support-focus); outline-offset:2px; }
.support-content textarea { width:100%; min-height:112px; box-sizing:border-box; padding:11px 12px; border:1px solid var(--support-border); border-radius:9px; background:var(--support-card); color:inherit; font:inherit; resize:vertical; }
.support-content textarea:focus { border-color:var(--support-accent); }
.support-content button[type='submit'] { width:100%; min-height:46px; border:1px solid var(--support-accent); border-radius:9px; background:var(--support-accent); color:#fff; font:inherit; font-weight:700; cursor:pointer; transition:filter 150ms ease, transform 150ms ease; }
.support-content button[type='submit']:hover:not(:disabled) { filter:brightness(1.08); transform:translateY(-1px); }
.support-content button:disabled { cursor:not-allowed; opacity:.65; }
.support-content :is(button, textarea, summary):focus-visible, .support-trigger:focus-visible { outline:3px solid var(--support-focus); outline-offset:3px; }
.support-error, .support-success { padding:10px 12px; border-radius:9px; font-size:13px; }
.support-error { background:var(--support-error-soft); color:var(--support-error); }
.support-success { background:var(--support-success-soft); color:var(--support-success); }
.support-history-panel { min-width:0; padding:4px 0 0 26px; border-left:1px solid var(--support-border); }
.support-list-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; }
.support-history-title { display:flex; align-items:center; flex-wrap:wrap; gap:10px; }
.support-history-title > span { padding:4px 9px; border-radius:999px; background:var(--support-accent-soft); color:var(--support-accent); font-size:11px; font-weight:650; }
.support-refresh, .support-pagination button { min-height:40px; padding:8px 12px; border:1px solid var(--support-border); border-radius:9px; background:var(--support-card); color:inherit; font:inherit; font-size:12px; font-weight:600; cursor:pointer; }
.support-refresh:hover:not(:disabled), .support-pagination button:hover:not(:disabled) { border-color:var(--support-accent); color:var(--support-accent); }
.support-empty { display:grid; place-content:center; min-height:160px; padding:24px; border:1px dashed var(--support-border); border-radius:12px; background:var(--support-panel); text-align:center; }
.support-empty strong { font-size:14px; }
.support-empty p { max-width:38ch; margin:8px auto 0; color:var(--support-muted); font-size:13px; }
.support-ticket-list { display:grid; gap:12px; max-height:480px; overflow:auto; margin:0; padding:0 4px 0 0; list-style:none; }
.support-ticket-item { margin:0; padding:0; border:1px solid var(--support-border); border-radius:12px; background:var(--support-card); }
.support-ticket-item article { padding:15px 16px; }
.support-ticket-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.support-ticket-meta { display:flex; align-items:center; flex-wrap:wrap; gap:9px; }
.support-ticket-meta > strong { font-size:13px; }
.support-ticket-meta time, .support-ticket-history time { color:var(--support-muted); font-size:12px; }
.support-status { flex-shrink:0; padding:5px 9px; border-radius:999px; background:var(--support-accent-soft); color:var(--support-accent); font-size:11px; font-weight:700; }
.support-status.is-in_progress { background:var(--support-warning-soft); color:var(--support-warning); }
.support-status.is-resolved { background:var(--support-success-soft); color:var(--support-success); }
.support-status.is-closed { background:var(--support-panel); color:var(--support-muted); }
.support-ticket-platforms { display:flex; flex-wrap:wrap; gap:6px; margin-top:11px; }
.support-ticket-platforms > span { padding:4px 8px; border:1px solid var(--support-border); border-radius:6px; color:var(--support-muted); font-size:11px; font-weight:600; }
.support-ticket-description { margin:12px 0 0; font-size:13px; }
.support-ticket-response { margin-top:12px; padding:10px 12px; border-left:3px solid var(--support-accent); border-radius:0 8px 8px 0; background:var(--support-panel); }
.support-ticket-response > strong { font-size:12px; }
.support-ticket-response p { margin:5px 0 0; font-size:13px; }
.support-ticket-history { margin-top:12px; padding-top:10px; border-top:1px solid var(--support-border); }
.support-ticket-history summary { width:fit-content; color:var(--support-accent); font-size:12px; font-weight:650; cursor:pointer; }
.support-ticket-history summary span { color:var(--support-muted); font-weight:500; }
.support-ticket-history ol { display:grid; gap:8px; margin:10px 0 0; padding-left:20px; }
.support-ticket-history ol li { padding-left:3px; font-size:12px; }
.support-ticket-history ol li strong { margin-left:8px; }
.support-ticket-history ol p { margin:5px 0 0; color:var(--support-muted); }
.support-pagination { display:flex; align-items:center; justify-content:flex-end; gap:10px; margin-top:14px; }
.support-pagination span { color:var(--support-muted); font-size:12px; }
.connection-support[open] .support-content { animation:support-reveal 160ms ease-out; }
@keyframes support-reveal { from { opacity:0; } to { opacity:1; } }
@media (prefers-reduced-motion: reduce) { .connection-support[open] .support-content { animation:none; } .support-trigger-action svg, .support-channel-trigger svg, .support-content button[type='submit'] { transition:none; } }
@media (max-width:900px) { .support-content { grid-template-columns:1fr; padding:16px; } .support-history-panel { padding:20px 0 0; border-top:1px solid var(--support-border); border-left:0; } }
@media (max-width:480px) { .support-trigger { gap:8px; padding:12px; } .support-trigger-copy small, .support-count, .support-open-label, .support-close-label { display:none!important; } .support-content { padding:12px; } .support-form-panel { padding:14px; } .support-ticket-item article { padding:12px; } }
:global(body.crm-dark .connection-support), :global([data-theme='dark'] .connection-support), :global(.dark .connection-support), :global(.crm-dark .connection-support) {
  --support-bg: var(--owly-surface, #202427);
  --support-panel: #233537;
  --support-card: #1b2023;
  --support-text: var(--owly-ink, #f3f5f6);
  --support-muted: var(--owly-muted, #b6c0c5);
  --support-border: #424c50;
  --support-accent: #62c5bc;
  --support-accent-soft: #1d4140;
  --support-error: #f0a3aa;
  --support-error-soft: #3b292c;
  --support-success: #9bd4ad;
  --support-success-soft: #24382d;
  --support-warning: #e2c17d;
  --support-warning-soft: #3b3426;
  --support-focus: #62c5bc;
}
</style>
