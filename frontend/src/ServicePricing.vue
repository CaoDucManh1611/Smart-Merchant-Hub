<script setup>
import { computed } from 'vue';
import { locale, t } from './i18n';
const props = defineProps({ plans: { type:Array, default:()=>[] }, mode:String, selected:String, authenticated:Boolean });
defineEmits(['select','signup','login']);
const en = computed(()=>locale.value === 'en');
const copy = computed(()=>en.value ? {
  title:'A plan for the way your shop works', subtitle:'Compare your options. Start small, then grow with your team.',
  choose:'Choose this plan', selected:'Selected plan', signup:'Get started', login:'Already have an account? Sign in',
  demo:'Explore the workspace', channels:'connected platforms', preview:'Explore customer workflows', separate:'Separate assistant service',
  knowledge:'Support based on shop knowledge', review:'Staff review and handoff', data:'Shop-scoped customer data', approval:'Activation follows the existing approval process.',
  note:'Prices and limits follow the current service catalogue. Connections require platform setup.'
} : {
  title:'Chọn gói phù hợp với shop của bạn', subtitle:'So sánh rõ ràng. Bắt đầu vừa đủ, mở rộng cùng đội ngũ.',
  choose:'Chọn gói này', selected:'Gói đang chọn', signup:'Bắt đầu với gói này', login:'Đã có tài khoản? Đăng nhập',
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
</script>
<template>
  <section class="smh-pricing" :aria-label="copy.title">
    <header><h2>{{ copy.title }}</h2><p>{{ copy.subtitle }}</p></header>
    <div class="smh-pricing-grid">
      <article v-for="plan in plans" :key="plan.code" class="smh-price-card" :class="{ 'is-selected': authenticated && selected === plan.code }">
        <div class="smh-price-top"><h3>{{ t(plan.name) }}</h3><span v-if="authenticated && selected === plan.code">{{ copy.selected }}</span></div>
        <p class="smh-price-description">{{ description(plan) }}</p>
        <p class="smh-price-amount"><strong>{{ plan.price.split('/')[0].trim() }}</strong><span v-if="plan.price.includes('/')">/ {{ plan.price.split('/').slice(1).join('/').trim() }}</span></p>
        <button type="button" :aria-pressed="authenticated ? selected === plan.code : undefined" @click="$emit('select', plan.code); !authenticated && $emit('signup')">{{ authenticated ? (selected === plan.code ? copy.selected : copy.choose) : copy.signup }}</button>
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
.smh-pricing > header { text-align:center; margin-bottom:30px; }.smh-pricing h2 { font-size:30px;letter-spacing:-.035em;line-height:1.25;margin:0 0 12px; }.smh-pricing > header p { color:var(--price-muted);margin:0;font-size:14px; }
.smh-pricing-grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;align-items:stretch; }
.smh-price-card { display:flex;flex-direction:column;padding:25px 21px;border:1px solid #d5dfda;border-radius:20px;background:#fff;min-width:0;transition:background-color .2s,border-color .2s,box-shadow .2s; }
.smh-price-card:hover,.smh-price-card:focus-within { background:#eaf5ee;border-color:#087e77;box-shadow:0 0 0 3px #087e7714,0 8px 24px #087e7710; }
.smh-price-top { display:flex;gap:8px;align-items:center;justify-content:space-between;min-height:27px; }.smh-price-top h3 { margin:0;font-size:18px; }.smh-price-top > span { font-size:10px;color:#086b62;font-weight:700; }
.smh-price-description { min-height:88px;font-size:13px;line-height:1.7;color:var(--price-muted);margin:18px 0 20px; }.smh-price-amount { font-size:23px;line-height:1.5;font-weight:650;letter-spacing:-.035em;margin:0 0 24px;overflow-wrap:anywhere; }
.smh-price-card > button { border:1px solid #bccdc3;border-radius:999px;background:transparent;color:var(--price-ink);font:inherit;font-size:13px;font-weight:650;min-height:44px;padding:10px 12px;cursor:pointer;transition:background-color .2s,color .2s,border-color .2s; }.smh-price-card:hover > button,.smh-price-card:focus-within > button { background:#087e77;color:white;border-color:#087e77; }.smh-price-card > button:focus-visible,.smh-pricing-login:focus-visible { outline:3px solid #087e77;outline-offset:4px; }
.smh-price-card ul { list-style:none;padding:0;margin:27px 0 24px;display:grid;gap:17px; }.smh-price-card li { display:flex;gap:9px;font-size:12px;line-height:1.6; }.smh-price-card li svg { width:17px;height:20px;flex-shrink:0;stroke:#087e77;stroke-width:1.8;fill:none; }.smh-price-card > small { margin-top:auto;color:var(--price-muted);font-size:10px;line-height:1.7; }
.smh-pricing-note { text-align:center;font-size:11px;line-height:1.8;color:var(--price-muted);margin:24px auto 0;max-width:640px; }.smh-pricing-login { display:block;margin:16px auto 0;border:0;background:transparent;text-decoration:underline;color:#146c63;padding:12px;cursor:pointer;font:inherit;font-size:12px; }
.smh-price-amount { min-height:70px; }.smh-price-amount strong { display:block;font-weight:650;white-space:nowrap; }.smh-price-amount > span { display:block;font-size:12px;letter-spacing:0;font-weight:400;color:var(--price-muted); }
body.crm-dark .smh-pricing { --price-ink:#e6f1ec;--price-muted:#b8cbc1; }body.crm-dark .smh-price-card { background:#202c29;border-color:#4a6156; }body.crm-dark .smh-price-card:hover,body.crm-dark .smh-price-card:focus-within { background:#24463c;border-color:#649684; }body.crm-dark .smh-price-top > span,body.crm-dark .smh-pricing-login { color:#8fd9c3; }
@media(max-width:600px) { .smh-pricing-grid { grid-template-columns:1fr; }.smh-price-description { min-height:0; }.smh-pricing h2 { font-size:25px; }.smh-price-card { padding:24px; } }
@media(prefers-reduced-motion:reduce) { .smh-price-card,.smh-price-card > button { transition:none; } }
</style>
