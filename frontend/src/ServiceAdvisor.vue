<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue';
import { locale, formatMoney } from './i18n.js';

const props = defineProps({ apiBase: { type: String, default: '/api' }, darkMode: Boolean });
const emit = defineEmits(['plans']);
const open = ref(false), messages = ref([]), question = ref(''), sending = ref(false), error = ref('');
const input = ref(null), log = ref(null), launcher = ref(null);
const plans = ref([]);
const launcherPosition = ref(null);
let drag = null, dragged = false;
function clampPosition(x, y) {
  const size = launcher.value?.getBoundingClientRect();
  return { x: Math.max(8, Math.min(x, window.innerWidth - (size?.width || 62) - 8)), y: Math.max(8, Math.min(y, window.innerHeight - (size?.height || 62) - 8)) };
}
function startDrag(event) {
  if (open.value || !event.isPrimary || event.button !== 0) return;
  const box = launcher.value.getBoundingClientRect();
  dragged = false;
  drag = { id:event.pointerId, x:event.clientX, y:event.clientY, left:box.left, top:box.top };
  event.currentTarget.setPointerCapture(event.pointerId);
}
function moveDrag(event) {
  if (!drag || event.pointerId !== drag.id) return;
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  if (!dragged && Math.hypot(dx, dy) < 6) return;
  dragged = true;
  dismissGreeting();
  launcherPosition.value = clampPosition(drag.left + dx, drag.top + dy);
}
function endDrag() { drag = null; }
function clickLauncher(event) { if (dragged && event.detail !== 0) { dragged = false; return; } toggle(); }
function resizeLauncher() { if (launcherPosition.value) launcherPosition.value = clampPosition(launcherPosition.value.x, launcherPosition.value.y); }
onMounted(() => window.addEventListener('resize', resizeLauncher));
const greetingDismissed = ref((() => { try { return sessionStorage.getItem('smh-advisor-greeting-dismissed') === '1'; } catch { return false; } })());
function dismissGreeting() {
  greetingDismissed.value = true;
  try { sessionStorage.setItem('smh-advisor-greeting-dismissed', '1'); } catch { /* Keep session state in memory when storage is blocked. */ }
}
let controller;
const en = computed(() => locale.value === 'en');
const copy = (vi, english) => en.value ? english : vi;
async function scrollToLatest() { await nextTick(); if (log.value) log.value.scrollTop = log.value.scrollHeight; }
async function toggle() {
  dismissGreeting();
  open.value = !open.value;
  await nextTick();
  (open.value ? input.value : launcher.value)?.focus();
  if (open.value) scrollToLatest();
}
async function send(suggestion) {
  const text = (typeof suggestion === 'string' ? suggestion : question.value).trim();
  if (!text || sending.value) return;
  sending.value = true; error.value = '';
  const history = messages.value.slice(-6).map(item => ({ role: item.role, content: item.content.slice(0, 1500) }));
  messages.value.push({ role: 'user', content: text }); question.value = '';
  scrollToLatest();
  controller = new AbortController();
  const timeout = setTimeout(() => controller?.abort(), 90000);
  try {
    const response = await fetch(`${props.apiBase}/services/advisor/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal, body: JSON.stringify({ question: text, history, locale: locale.value }) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : copy('Chưa thể tư vấn lúc này. Vui lòng thử lại.', 'Advice is unavailable right now. Please retry.'));
    messages.value.push({ role: 'assistant', content: body.answer, sources: [...new Set((body.sources || []).map(source => source.filename))], fallback: body.mode === 'fallback' });
    plans.value = body.plans || [];
  } catch (failure) {
    messages.value.pop(); question.value = text;
    error.value = failure.name === 'AbortError' ? copy('Phản hồi đang mất nhiều thời gian. Bạn thử lại nhé.', 'The response is taking too long. Please retry.') : failure.message;
  } finally { clearTimeout(timeout); sending.value = false; controller = null; scrollToLatest(); }
}
function openPlans() { emit('plans'); toggle(); }
onBeforeUnmount(() => { controller?.abort(); window.removeEventListener('resize', resizeLauncher); });
</script>

<template>
  <div class="service-advisor" :class="{ 'advisor-dark': darkMode }">
    <section v-if="open" id="service-advisor-panel" class="advisor-panel" role="dialog" aria-modal="false" aria-labelledby="advisor-heading" @keydown.esc.stop="toggle">
      <header><span class="advisor-avatar" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M16 5V2M13 2h6M6 12H3v9h3m20-9h3v9h-3"/><rect x="6" y="7" width="20" height="20" rx="7"/><circle cx="12" cy="15" r="1"/><circle cx="20" cy="15" r="1"/><path d="M12 21q4 3 8 0"/></svg></span><div><h2 id="advisor-heading">{{ copy('Tư vấn gói dịch vụ', 'Service plan advisor') }}</h2><p>{{ copy('Chọn gói phù hợp với shop của bạn', 'Find a plan that fits your shop') }}</p></div><button type="button" :aria-label="copy('Đóng tư vấn', 'Close advisor')" @click="toggle">×</button></header>
      <div ref="log" class="advisor-messages" role="log" aria-live="polite" :aria-busy="sending">
        <div v-if="!messages.length" class="advisor-welcome"><p>{{ copy('Bạn cần quản lý bao nhiêu kênh? Có muốn chatbot tự trả lời khách không? Tôi sẽ giúp bạn đối chiếu các gói đang bán.', 'How many channels do you manage? Do you need automatic replies? I can help compare the current plans.') }}</p><div class="advisor-suggestions"><button v-for="prompt in [copy('Shop mới nên chọn gói nào?', 'Which plan suits a new shop?'), copy('Giá thuê chatbot là bao nhiêu?', 'How much does the chatbot cost?')]" :key="prompt" type="button" @click="send(prompt)">{{ prompt }}</button></div></div>
        <article v-for="(message, index) in messages" :key="index" :class="['advisor-message', message.role]">
          <strong>{{ message.role === 'user' ? copy('Bạn', 'You') : copy('Tư vấn dịch vụ', 'Service advisor') }}</strong><p>{{ message.content }}</p>
          <small v-if="message.sources?.length">{{ copy('Nguồn: ', 'Sources: ') }}{{ message.sources.join(', ') }}</small>
        </article>
        <p v-if="sending" role="status">{{ copy('Đang đối chiếu thông tin gói…', 'Checking service information…') }}</p>
        <details v-if="plans.length" class="advisor-plans"><summary>{{ copy('Các gói hiện hành', 'Current service plans') }}</summary><div v-for="plan in plans" :key="plan.code"><strong>{{ plan.name }}</strong><p>{{ copy('Quản lý shop: ', 'Shop management: ') }}{{ formatMoney(plan.price) }} · {{ plan.billing_cycle === 'monthly' ? copy('mỗi tháng', 'per month') : plan.billing_cycle }}</p><p>{{ copy('Thuê chatbot: ', 'Chatbot rental: ') }}{{ formatMoney(plan.chatbot_price) }}</p><p>{{ plan.max_channels }} {{ copy('kênh kết nối', 'channels') }} · {{ plan.max_users }} {{ copy('nhân viên', 'users') }}</p></div></details>
      </div>
      <p v-if="error" role="alert" class="advisor-error">{{ error }}</p>
      <form @submit.prevent="send"><label for="advisor-question">{{ copy('Câu hỏi về gói dịch vụ', 'Your question about service plans') }}</label><div class="advisor-composer"><textarea id="advisor-question" ref="input" v-model="question" rows="2" maxlength="1000" :disabled="sending" :placeholder="copy('Mô tả nhu cầu của shop…', 'Tell us what your shop needs…')" @keydown.enter.exact.prevent="send" /><button type="submit" :disabled="sending || !question.trim()">{{ copy('Gửi', 'Send') }}</button></div></form>
      <footer><button type="button" @click="openPlans">{{ copy('Xem bảng giá và đăng ký', 'View pricing and sign up') }}</button><small>{{ copy('Giá và hạn mức trong bảng gói là thông tin hiện hành. Không gửi mật khẩu hoặc mã xác minh.', 'Plan cards show current prices and limits. Do not send passwords or verification codes.') }}</small></footer>
    </section>
    <aside v-if="!open && !greetingDismissed" class="advisor-greeting" :aria-label="copy('Lời chào tư vấn', 'Advisor welcome')">
      <span class="advisor-greeting-avatar advisor-avatar" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M16 5V2M13 2h6M6 12H3v9h3m20-9h3v9h-3"/><rect x="6" y="7" width="20" height="20" rx="7"/><circle cx="12" cy="15" r="1"/><circle cx="20" cy="15" r="1"/><path d="M12 21q4 3 8 0"/></svg></span>
      <button type="button" class="advisor-greeting-close" :aria-label="copy('Ẩn lời chào', 'Dismiss welcome')" @click="dismissGreeting"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button>
      <button type="button" class="advisor-greeting-message" @click="toggle"><strong>{{ copy('Chào bạn, mình có thể giúp gì?', 'Hi, how can I help?') }}</strong><span>{{ copy('Bạn đang tìm gói phù hợp cho shop? Cùng mình chọn nhé.', 'Looking for the right plan for your shop? Let’s find it together.') }}</span></button>
    </aside>
    <button ref="launcher" type="button" class="advisor-launcher" :style="!open && launcherPosition ? { position:'fixed', left:launcherPosition.x + 'px', top:launcherPosition.y + 'px' } : undefined" :aria-label="copy(open ? 'Đóng tư vấn' : 'Tư vấn chọn gói', open ? 'Close advisor' : 'Help choosing a plan')" :aria-expanded="open" aria-controls="service-advisor-panel" @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="endDrag" @lostpointercapture="endDrag" @click="clickLauncher"><svg viewBox="0 0 24 24" aria-hidden="true"><path v-if="open" d="m6 6 12 12M6 18 18 6"/><path v-else d="M4 4h16v12H9l-5 4zM8 8h8M8 12h5" /></svg></button>
  </div>
</template>

<style scoped>
.service-advisor { --advisor-bg:#fff; --advisor-soft:#edf5f3; --advisor-ink:#183b39; --advisor-muted:#536d69; --advisor-line:#ceded9; --advisor-accent:#087d76; position:fixed; right:24px; bottom:22px; z-index:1100; font-family:inherit; color:var(--advisor-ink); }
.advisor-dark { --advisor-bg:#202b2e; --advisor-soft:#293c3d; --advisor-ink:#edf5f3; --advisor-muted:#bbceca; --advisor-line:#49615e; --advisor-accent:#8bdfd4; }
button,textarea { font:inherit; }
button { cursor:pointer; min-height:44px; }
button:disabled { opacity:.55; cursor:wait; }
.advisor-launcher { display:grid; place-items:center; width:62px; height:62px; margin-left:auto; border:1px solid var(--advisor-line); border-radius:50%; padding:0; background:var(--advisor-accent); color:var(--advisor-bg); box-shadow:0 6px 22px #0003; }
.advisor-launcher { touch-action:none; user-select:none; }
.advisor-launcher svg { width:27px; height:27px; fill:none; stroke:currentColor; stroke-width:1.6; }
.advisor-panel { display:flex; flex-direction:column; width:min(420px,calc(100vw - 32px)); height:min(660px,calc(100dvh - 110px)); margin-bottom:12px; overflow:hidden; border:1px solid var(--advisor-line); border-radius:20px; background:var(--advisor-bg); box-shadow:0 12px 50px #0003; font-size:14px; line-height:1.6; }
header { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:16px; background:var(--advisor-soft); border-bottom:1px solid var(--advisor-line); }
header>div { flex:1; min-width:0; }
header h2 { font-size:17px; margin:0; color:var(--advisor-ink); }
header p { margin:3px 0 0; font-size:12px; color:var(--advisor-muted); }
header button { background:transparent; color:var(--advisor-ink); border:0; width:44px; font-size:26px; }
.advisor-messages { flex:1; min-height:0; overflow:auto; overscroll-behavior:contain; padding:16px; }
.advisor-message { padding:12px; margin:0 0 12px; border-radius:12px; background:var(--advisor-soft); overflow-wrap:anywhere; }
.advisor-message.user { margin-left:30px; border:1px solid var(--advisor-line); background:var(--advisor-bg); }
.advisor-message p { margin:5px 0 0; white-space:pre-wrap; }
.advisor-message strong,.advisor-message small { font-size:12px; }
.advisor-message small { display:block; margin-top:8px; color:var(--advisor-muted); }
.advisor-suggestions { display:grid; gap:8px; }
.advisor-suggestions button,.advisor-plans { border:1px solid var(--advisor-line); border-radius:9px; padding:10px; background:var(--advisor-bg); color:var(--advisor-ink); text-align:left; }
.advisor-plans summary { cursor:pointer; padding:4px; }
.advisor-plans>div { border-top:1px solid var(--advisor-line); margin-top:10px; padding-top:10px; }
.advisor-plans p { margin:3px 0; font-size:12px; }
form { padding:10px 16px; border-top:1px solid var(--advisor-line); }
form label { display:block; font-size:12px; margin-bottom:5px; }
.advisor-composer { display:flex; gap:8px; }
textarea { resize:none; min-width:0; width:100%; padding:10px; border:1px solid var(--advisor-line); border-radius:9px; color:var(--advisor-ink); background:var(--advisor-bg); }
.advisor-composer button { padding:8px 14px; border:1px solid var(--advisor-line); border-radius:9px; color:var(--advisor-ink); background:var(--advisor-soft); }
footer { padding:0 16px 12px; }
footer button { display:block; border:0; padding:4px 0; color:var(--advisor-accent); background:transparent; text-decoration:underline; }
footer small { display:block; color:var(--advisor-muted); font-size:11px; }
.advisor-error { margin:0; padding:10px 16px; color:var(--advisor-ink); background:var(--advisor-soft); }
:is(button,textarea,summary):focus-visible { outline:2px solid var(--advisor-accent); outline-offset:2px; }
@media(max-width:600px) { .service-advisor { right:12px; bottom:12px; } .advisor-panel { width:calc(100vw - 24px); } }
.advisor-avatar { display:grid; place-items:center; flex-shrink:0; width:44px; height:44px; border-radius:50%; background:var(--advisor-accent); color:var(--advisor-bg); }
.advisor-avatar svg { width:31px; height:31px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; }
.advisor-greeting { position:relative; box-sizing:border-box; width:min(290px,calc(100vw - 32px)); margin:0 0 18px auto; padding:26px 16px 16px; border:1px solid var(--advisor-line); border-radius:16px; background:var(--advisor-bg); color:var(--advisor-ink); box-shadow:0 8px 30px #0002; }
.advisor-greeting::after { content:''; position:absolute; bottom:-7px; right:22px; width:12px; height:12px; transform:rotate(45deg); border-right:1px solid var(--advisor-line); border-bottom:1px solid var(--advisor-line); background:var(--advisor-bg); }
.advisor-greeting-avatar { position:absolute; top:-24px; left:calc(50% - 24px); width:48px; height:48px; box-shadow:0 0 0 5px var(--advisor-bg); }
.advisor-greeting-close { display:grid; place-items:center; position:absolute; right:1px; top:0; width:40px; min-height:40px; border:0; background:transparent; color:var(--advisor-muted); }
.advisor-greeting-close svg { width:16px; height:16px; fill:none; stroke:currentColor; stroke-width:1.5; }
.advisor-greeting-message { display:grid; gap:7px; width:100%; border:0; padding:5px 0 0; background:transparent; color:inherit; text-align:left; line-height:1.65; }
.advisor-greeting-message strong { font-size:14px; font-weight:650; }
.advisor-greeting-message span { font-size:13px; color:var(--advisor-muted); }
@media(max-width:600px) { .advisor-launcher { width:58px; height:58px; } }
@media(max-width:480px) { .advisor-greeting { display:none; } .advisor-launcher { width:48px; height:48px; } .advisor-launcher svg { width:23px; height:23px; } }
</style>
