<script setup>
import { computed } from 'vue';
import { locale, t } from './i18n';
const props = defineProps({ plans: { type:Array, default:()=>[] }, mode:String, selected:String, currentPlan:String, authenticated:Boolean });
defineEmits(['select','signup','login']);
const en = computed(()=>locale.value === 'en');
const copy = computed(()=>en.value ? {
  title:props.mode === 'chatbot' ? 'Choose a chatbot plan' : 'A plan for the way your shop works', subtitle:props.mode === 'chatbot' ? 'Compare chatbot plans and choose the right assistant for your shop.' : 'Compare your options. Start small, then grow with your team.',
  choose:'Choose', chooseChatbot:'Choose assistant', selected:'Selected plan', selectedChatbot:'Selected bot', current:'Current plan', currentChatbot:'Current bot', upgrade:'Upgrade to', upgradeChatbot:'Upgrade assistant to', downgrade:'Downgrade to', downgradeChatbot:'Downgrade assistant to', switchChatbot:'Switch assistant to', signup:'Get started with', login:'Already have an account? Sign in',
  demo:'Explore the workspace', channels:'connected platforms', preview:'Explore customer workflows', separate:'Separate assistant service',
  knowledge:'Support based on shop knowledge', review:'Staff review and handoff', data:'Shop-scoped customer data', approval:'Activation follows the existing approval process.',
  note:'Prices and limits follow the current service catalogue. Connections require platform setup.'
} : {
  title:props.mode === 'chatbot' ? 'Chọn chatbot phù hợp' : 'Chọn gói phù hợp với shop của bạn', subtitle:props.mode === 'chatbot' ? 'So sánh các gói trợ lý chatbot và chọn phương án phù hợp với shop của bạn.' : 'So sánh rõ ràng. Bắt đầu vừa đủ, mở rộng cùng đội ngũ.',
  choose:'Chọn', chooseChatbot:'Chọn trợ lý', selected:'Gói đang chọn', selectedChatbot:'Bot đang chọn', current:'Gói hiện tại', currentChatbot:'Bot hiện tại', upgrade:'Nâng cấp lên', upgradeChatbot:'Nâng cấp trợ lý', downgrade:'Hạ gói xuống', downgradeChatbot:'Hạ trợ lý xuống', switchChatbot:'Chuyển sang trợ lý', signup:'Bắt đầu với', login:'Đã có tài khoản? Đăng nhập',
  demo:'Khám phá không gian làm việc', channels:'nền tảng kết nối', preview:'Trải nghiệm quy trình chăm khách', separate:'Dịch vụ trợ lý thuê riêng',
  knowledge:'Hỗ trợ theo kiến thức của shop', review:'Nhân viên xem lại và tiếp quản', data:'Dữ liệu khách riêng theo shop', approval:'Kích hoạt theo quy trình duyệt hiện có.',
  note:'Giá và hạn mức theo danh mục dịch vụ hiện tại. Kết nối cần thiết lập theo từng nền tảng.'
});
function features(plan) {
  if(props.mode === 'chatbot') return [copy.value.separate, t(plan.description), copy.value.review];
  return [Number(plan.max_channels) ? `${plan.max_channels} ${copy.value.channels}` : copy.value.demo, copy.value.preview, copy.value.data];
}
function description(plan) {
  return props.mode !== 'chatbot' && plan.code === 'pro' && Number(plan.max_channels) !== 6
    ? (en.value ? 'For shops operating across multiple platforms.' : 'Gói dành cho shop vận hành nhiều kênh.')
    : t(plan.description);
}
function planAction(plan) {
  const name = t(plan.name);
  const isChatbot = props.mode === 'chatbot';
  const targetName = isChatbot ? name.replace(en.value ? /^Assistant\s+|\s+Assistant$/i : /^Trợ lý\s+/i, '') : name;
  if (!props.authenticated) return `${copy.value.signup} ${name}`;
  if (isChatbot && props.selected === plan.code) return copy.value.selectedChatbot;
  if (isChatbot) {
    const referenceCode = props.currentPlan || props.selected;
    const referenceIndex = props.plans.findIndex(item => item.code === referenceCode);
    const targetIndex = props.plans.findIndex(item => item.code === plan.code);
    if (referenceIndex < 0) return `${copy.value.chooseChatbot} ${targetName}`;
    if (targetIndex === referenceIndex) return copy.value.currentChatbot;
    return `${targetIndex > referenceIndex ? copy.value.upgradeChatbot : copy.value.downgradeChatbot} ${targetName}`;
  }
  if (props.currentPlan) {
    const currentIndex = props.plans.findIndex(item => item.code === props.currentPlan);
    const targetIndex = props.plans.findIndex(item => item.code === plan.code);
    if (targetIndex === currentIndex) return copy.value.current;
    if (currentIndex >= 0) {
      const isUpgrade = targetIndex > currentIndex;
      return `${isUpgrade ? copy.value.upgrade : copy.value.downgrade} ${name}`;
    }
  }
  return props.selected === plan.code ? copy.value.selected : `${copy.value.choose} ${name}`;
}
const currentLabel = computed(()=>props.mode === 'chatbot' ? copy.value.currentChatbot : copy.value.current);
const selectedLabel = computed(()=>props.mode === 'chatbot' ? copy.value.selectedChatbot : copy.value.selected);
</script>
<template>
  <section class="smh-pricing" :aria-label="copy.title">
    <header><h2>{{ copy.title }}</h2><p>{{ copy.subtitle }}</p></header>
    <div class="smh-pricing-grid">
      <article v-for="plan in plans" :key="plan.code" class="smh-price-card" :class="{ 'is-selected': authenticated && selected === plan.code, 'is-current': authenticated && currentPlan === plan.code }">
        <div class="smh-price-top"><h3>{{ t(plan.name) }}</h3><span v-if="authenticated && selected === plan.code">{{ selectedLabel }}</span><span v-else-if="authenticated && currentPlan === plan.code" class="current-plan-label">{{ currentLabel }}</span></div>
        <p class="smh-price-description">{{ description(plan) }}</p>
        <p class="smh-price-amount"><strong>{{ plan.price.split('/')[0].trim() }}</strong><span v-if="plan.price.includes('/')">/ {{ plan.price.split('/').slice(1).join('/').trim() }}</span></p>
        <button type="button" :disabled="authenticated && currentPlan === plan.code" :aria-pressed="authenticated ? selected === plan.code : undefined" @click="$emit('select', plan.code); !authenticated && $emit('signup')">{{ planAction(plan) }}</button>
        <ul><li v-for="feature in features(plan)" :key="feature"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg><span>{{ feature }}</span></li></ul>
        <small>{{ copy.approval }}</small>
      </article>
    </div>
    <p class="smh-pricing-note">{{ copy.note }}</p>
    <button v-if="!authenticated" type="button" class="smh-pricing-login" @click="$emit('login')">{{ copy.login }}</button>
  </section>
</template>
<style>
.smh-pricing { --price-ink:#183b3a; --price-muted:#536963; color:var(--price-ink); margin:28px auto 40px; width:100%; }
.smh-pricing > header { text-align:center; margin-bottom:30px; }.smh-pricing h2 { font-size:34px;letter-spacing:-.035em;line-height:1.2;margin:0 0 12px; }.smh-pricing > header p { color:var(--price-muted);margin:0;font-size:16px;line-height:1.55; }
.smh-pricing-grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;align-items:stretch; }
.smh-price-card { display:flex;flex-direction:column;min-height:620px;padding:25px 21px;border:1px solid #d5dfda;border-radius:18px;background:#fff;min-width:0;transition:background-color .2s,border-color .2s,box-shadow .2s; }
.smh-price-card:hover,.smh-price-card:focus-within { background:#eaf5ee;border-color:#087e77;box-shadow:0 0 0 3px #087e7714,0 8px 24px #087e7710; }
.smh-price-top { display:flex;gap:8px;align-items:center;justify-content:space-between;min-height:27px; }.smh-price-top h3 { margin:0;font-size:20px;line-height:1.3; }.smh-price-top > span { font-size:11px;color:#086b62;font-weight:750; }
.smh-price-top > .current-plan-label { color:#48645b; }
.smh-price-description { min-height:96px;font-size:14px;line-height:1.65;color:var(--price-muted);margin:16px 0 18px; }.smh-price-amount { font-size:26px;line-height:1.4;font-weight:650;letter-spacing:-.035em;margin:0 0 21px;overflow-wrap:anywhere; }
.smh-price-card > button { border:1px solid #bccdc3;border-radius:999px;background:transparent;color:var(--price-ink);font:inherit;font-size:14px;font-weight:700;min-height:46px;padding:10px 12px;cursor:pointer;transition:background-color .2s,color .2s,border-color .2s; }.smh-price-card:hover > button,.smh-price-card:focus-within > button,.smh-price-card.is-selected > button { background:#087e77;color:white;border-color:#087e77; }.smh-price-card > button:focus-visible,.smh-pricing-login:focus-visible { outline:3px solid #087e77;outline-offset:4px; }
.smh-price-card > button:disabled { cursor:default;opacity:.82; }
.smh-price-card.is-selected { border-color:#168c82;background:#f0f8f4;box-shadow:0 0 0 2px rgba(8,126,119,.12),0 12px 30px rgba(8,126,119,.08); }
.smh-price-card.is-current:not(.is-selected) { border-color:#8da99d; }
.smh-price-card ul { list-style:none;padding:0;margin:24px 0 21px;display:grid;gap:14px; }.smh-price-card li { display:flex;gap:9px;font-size:14px;line-height:1.55; }.smh-price-card li svg { width:18px;height:21px;flex-shrink:0;stroke:#087e77;stroke-width:1.8;fill:none; }.smh-price-card > small { margin-top:auto;color:var(--price-muted);font-size:12px;line-height:1.6; }
.smh-pricing-note { text-align:center;font-size:13px;line-height:1.65;color:var(--price-muted);margin:24px auto 0;max-width:720px; }.smh-pricing-login { display:block;margin:16px auto 0;border:0;background:transparent;text-decoration:underline;color:#146c63;padding:12px;cursor:pointer;font:inherit;font-size:14px; }
.smh-price-amount { min-height:72px; }.smh-price-amount strong { display:block;font-weight:650;white-space:nowrap; }.smh-price-amount > span { display:block;font-size:13px;letter-spacing:0;font-weight:400;color:var(--price-muted); }
body.crm-dark .smh-pricing { --price-ink:#f3f5f6;--price-muted:#b6c0c5; }
body.crm-dark .smh-price-card { background:#202427;border-color:#394145; }
body.crm-dark .smh-price-card:hover,body.crm-dark .smh-price-card:focus-within { background:#252a2d;border-color:#4a555a; }
body.crm-dark .smh-price-card.is-selected { background:#173f43;border-color:#3c777a;box-shadow:0 0 0 2px rgba(60,119,122,.22),0 12px 30px rgba(0,0,0,.24); }
body.crm-dark .smh-price-card.is-current:not(.is-selected) { border-color:#526b67; }
body.crm-dark .smh-price-top > .current-plan-label { color:#c7d6cf; }
body.crm-dark .smh-price-card > button { color:#f3f5f6;border-color:#4a555a; }
body.crm-dark .smh-price-card:hover > button,body.crm-dark .smh-price-card:focus-within > button,body.crm-dark .smh-price-card.is-selected > button { background:#238b92;border-color:#39a7ad; }
body.crm-dark .smh-price-card > button:focus-visible,body.crm-dark .smh-pricing-login:focus-visible { outline-color:#39a7ad; }
body.crm-dark .smh-price-card li svg { stroke:#39a7ad; }
body.crm-dark .smh-price-top > span,body.crm-dark .smh-pricing-login { color:#8bd8d7; }
@media(max-width:600px) { .smh-pricing-grid { grid-template-columns:1fr; }.smh-price-description { min-height:0; }.smh-pricing h2 { font-size:28px; }.smh-price-card { min-height:0;padding:22px; } }
@media(prefers-reduced-motion:reduce) { .smh-price-card,.smh-price-card > button { transition:none; } }
</style>
