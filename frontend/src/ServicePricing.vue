<script setup>
import { computed } from 'vue';
import { locale, t } from './i18n';
import { planChangeKind } from './checkout-utils.js';
const props = defineProps({ plans: { type:Array, default:()=>[] }, mode:String, selected:String, currentPlan:String, authenticated:Boolean });
defineEmits(['select','signup','login']);
const en = computed(()=>locale.value === 'en');
const copy = computed(()=>en.value ? {
  title:props.mode === 'chatbot' ? 'One full-service chatbot plan' : 'A plan for the way your shop works', subtitle:props.mode === 'chatbot' ? 'Setup, channel connection, knowledge preparation, and ongoing support in one plan.' : 'Compare your options. Start small, then grow with your team.',
  choose:'Choose', chooseChatbot:'Choose', selected:'Selected plan', selectedChatbot:'Selected bot', current:'Current plan', currentChatbot:'Current bot', upgrade:'Upgrade to', upgradeChatbot:'Upgrade to', downgradeUnavailable:props.mode === 'chatbot' ? 'Assistant downgrade unavailable' : 'Plan downgrade unavailable', signup:'Get started with', login:'Already have an account? Sign in',
  demo:'Explore the workspace', channels:'connected platforms', preview:'Explore customer workflows', separate:'Separate assistant service',
  knowledgeLimit:'Maximum knowledge items', knowledgeItemUnit:'items', knowledgeNotIncluded:'Not included',
  knowledge:'Support based on shop knowledge', review:'Staff review and handoff', data:'Shop-scoped customer data', approval:'Activation follows the existing approval process.',
  fullName:'Full-service chatbot', fullDescription:'Our team helps set up the chatbot, connect channels, prepare shop knowledge, and monitor it after launch.', installChannels:'Setup and connect up to', channelUnit:'channels', prepareKnowledge:'Add product information, FAQs, policies, and test answers.', monitorBot:'Monitor, update, and improve chatbot answers regularly.', staffHandoff:'Your staff can take over conversations when needed.',
  managedKicker:'SETUP AND ONGOING SUPPORT', managedTitle:'Support from initial setup through day-to-day operation', managedIntro:'Initial setup is included in the Full-Service Chatbot plan.', managedFee:'No separate setup fee', managedQuote:'The plan includes setup, channel connection, knowledge preparation, and ongoing chatbot support.', managedSetup:'Setup', managedSetupText:'Configure the chatbot for your shop and its customer service workflow.', managedConnect:'Connect', managedConnectText:'Help connect the shop’s supported messaging channels.', managedKnowledge:'Prepare knowledge', managedKnowledgeText:'Add products, FAQs, policies, and test the answers before launch.', managedOperate:'Monitor', managedOperateText:'Review operation and help keep the chatbot knowledge and answers current.', managedDetails:'How rollout works', managedDetailsText:'We agree on the channels and shop materials first, then configure and test the chatbot with your team before it goes live.',
  note:props.mode === 'chatbot' ? 'Monthly chatbot service. Channel connection depends on each platform’s access requirements.' : 'Prices and limits follow the current service catalogue. Connections require platform setup.'
} : {
  title:props.mode === 'chatbot' ? 'Một gói Trợ lý Toàn diện' : 'Chọn gói phù hợp với shop của bạn', subtitle:props.mode === 'chatbot' ? 'Cài đặt, kết nối, nạp kiến thức và hỗ trợ vận hành trong cùng một gói.' : 'So sánh rõ ràng. Bắt đầu vừa đủ, mở rộng cùng đội ngũ.',
  choose:'Chọn', chooseChatbot:'Chọn', selected:'Gói đang chọn', selectedChatbot:'Bot đang chọn', current:'Gói hiện tại', currentChatbot:'Bot hiện tại', upgrade:'Nâng cấp lên', upgradeChatbot:'Nâng cấp lên', downgradeUnavailable:props.mode === 'chatbot' ? 'Không hỗ trợ hạ trợ lý' : 'Không hỗ trợ hạ gói', signup:'Bắt đầu với', login:'Đã có tài khoản? Đăng nhập',
  demo:'Khám phá không gian làm việc', channels:'nền tảng kết nối', preview:'Trải nghiệm quy trình chăm khách', separate:'Dịch vụ trợ lý thuê riêng',
  knowledgeLimit:'Mục kiến thức tối đa', knowledgeItemUnit:'mục', knowledgeNotIncluded:'Không bao gồm',
  knowledge:'Hỗ trợ theo kiến thức của shop', review:'Nhân viên xem lại và tiếp quản', data:'Dữ liệu khách riêng theo shop', approval:'Kích hoạt theo quy trình duyệt hiện có.',
  fullName:'Trợ lý Toàn diện', fullDescription:'Đội ngũ hỗ trợ cài đặt chatbot, kết nối kênh, chuẩn bị kiến thức shop và theo dõi sau khi vận hành.', installChannels:'Cài đặt và kết nối tối đa', channelUnit:'kênh', prepareKnowledge:'Nạp thông tin sản phẩm, FAQ, chính sách và kiểm thử câu trả lời.', monitorBot:'Theo dõi, cập nhật kiến thức và tối ưu câu trả lời định kỳ.', staffHandoff:'Nhân viên shop có thể tiếp quản hội thoại khi cần.',
  managedKicker:'CÀI ĐẶT VÀ HỖ TRỢ VẬN HÀNH', managedTitle:'Đồng hành từ lúc cài đặt đến khi chatbot hoạt động', managedIntro:'Cài đặt ban đầu đã nằm trong gói Trợ lý Toàn diện.', managedFee:'Không thu phí cài đặt riêng', managedQuote:'Gói bao gồm thiết lập, kết nối kênh, nạp kiến thức và hỗ trợ chatbot sau khi đưa vào hoạt động.', managedSetup:'Cài đặt', managedSetupText:'Cấu hình chatbot theo shop và quy trình chăm sóc khách.', managedConnect:'Kết nối', managedConnectText:'Hỗ trợ kết nối các kênh nhắn tin shop đang sử dụng.', managedKnowledge:'Nạp kiến thức', managedKnowledgeText:'Thêm sản phẩm, FAQ, chính sách và kiểm thử trước khi chạy.', managedOperate:'Theo dõi', managedOperateText:'Rà soát hoạt động và hỗ trợ cập nhật kiến thức, câu trả lời.', managedDetails:'Quy trình triển khai', managedDetailsText:'Hai bên thống nhất kênh và tài liệu của shop, sau đó cấu hình và kiểm thử chatbot cùng đội ngũ trước khi đưa vào sử dụng.',
  note:props.mode === 'chatbot' ? 'Gói chatbot tính theo tháng; việc kết nối phụ thuộc quyền truy cập của từng nền tảng.' : 'Giá và hạn mức theo danh mục dịch vụ hiện tại. Kết nối cần thiết lập theo từng nền tảng.'
});
function features(plan) {
  if(props.mode === 'chatbot' && plan.code === 'pro') return [
    `${copy.value.installChannels} ${Number(plan.max_channels) || 0} ${copy.value.channelUnit}`,
    copy.value.prepareKnowledge,
    copy.value.monitorBot,
    copy.value.staffHandoff,
  ];
  if(props.mode === 'chatbot') return [copy.value.separate, t(plan.description), copy.value.review];
  return [Number(plan.max_channels) ? `${plan.max_channels} ${copy.value.channels}` : copy.value.demo, copy.value.preview, copy.value.data];
}
const displayedPlans = computed(() => props.mode === 'chatbot'
  ? props.plans.filter(plan => plan.code === 'pro').slice(0, 1)
  : props.plans);
function planName(plan) {
  return props.mode === 'chatbot' && plan.code === 'pro' ? copy.value.fullName : t(plan.name);
}
function knowledgeLimit(plan) {
  const limit = Math.max(0, Number(plan?.max_rag_chunks) || 0);
  return limit ? `${limit.toLocaleString(en.value ? 'en-US' : 'vi-VN')} ${copy.value.knowledgeItemUnit}` : copy.value.knowledgeNotIncluded;
}
function description(plan) {
  if (props.mode === 'chatbot' && plan.code === 'pro') return copy.value.fullDescription;
  return props.mode !== 'chatbot' && plan.code === 'pro' && Number(plan.max_channels) !== 6
    ? (en.value ? 'For shops operating across multiple platforms.' : 'Gói dành cho shop vận hành nhiều kênh.')
    : t(plan.description);
}
function isDowngrade(plan) {
  if (!props.authenticated || !props.currentPlan) return false;
  const current = props.plans.find(item => item.code === props.currentPlan);
  return Boolean(current && planChangeKind(current, plan) === 'downgrade');
}
function planAction(plan) {
  const name = planName(plan);
  const isChatbot = props.mode === 'chatbot';
  const targetName = isChatbot && plan.code !== 'pro' ? name.replace(en.value ? /^Assistant\s+|\s+Assistant$/i : /^Trợ lý\s+/i, '') : name;
  if (!props.authenticated) return `${copy.value.signup} ${name}`;
  if (isDowngrade(plan)) return copy.value.downgradeUnavailable;
  if (isChatbot && props.selected === plan.code) return copy.value.selectedChatbot;
  if (isChatbot) {
    const current = props.plans.find(item => item.code === props.currentPlan);
    if (!current) return `${copy.value.chooseChatbot} ${targetName}`;
    if (plan.code === current.code) return copy.value.currentChatbot;
    return `${copy.value.upgradeChatbot} ${targetName}`;
  }
  if (props.currentPlan) {
    const current = props.plans.find(item => item.code === props.currentPlan);
    if (current?.code === plan.code) return copy.value.current;
    if (current) return `${copy.value.upgrade} ${name}`;
  }
  return props.selected === plan.code ? copy.value.selected : `${copy.value.choose} ${name}`;
}
const currentLabel = computed(()=>props.mode === 'chatbot' ? copy.value.currentChatbot : copy.value.current);
const selectedLabel = computed(()=>props.mode === 'chatbot' ? copy.value.selectedChatbot : copy.value.selected);
</script>
<template>
  <section class="smh-pricing" :class="{ 'is-chatbot': mode === 'chatbot' }" :aria-label="copy.title">
    <header><h2>{{ copy.title }}</h2><p>{{ copy.subtitle }}</p></header>
    <div class="smh-pricing-content" :class="{ 'is-chatbot-package': mode === 'chatbot' }">
    <div class="smh-pricing-grid">
      <article v-for="plan in displayedPlans" :key="plan.code" class="smh-price-card" :class="{ 'is-selected': authenticated && selected === plan.code, 'is-current': authenticated && currentPlan === plan.code }">
        <div class="smh-price-top"><h3>{{ planName(plan) }}</h3><span v-if="authenticated && selected === plan.code">{{ selectedLabel }}</span><span v-else-if="authenticated && currentPlan === plan.code" class="current-plan-label">{{ currentLabel }}</span></div>
        <p class="smh-price-description">{{ description(plan) }}</p>
        <p class="smh-price-amount"><strong>{{ plan.price.split('/')[0].trim() }}</strong><span v-if="plan.price.includes('/')">/ {{ plan.price.split('/').slice(1).join('/').trim() }}</span></p>
        <button type="button" :class="{ 'is-downgrade': isDowngrade(plan) }" :disabled="authenticated && (currentPlan === plan.code || isDowngrade(plan))" :aria-pressed="authenticated ? selected === plan.code : undefined" @click="$emit('select', plan.code); !authenticated && $emit('signup')">{{ planAction(plan) }}</button>
        <ul><li v-for="feature in features(plan)" :key="feature"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg><span>{{ feature }}</span></li></ul>
        <dl v-if="mode !== 'chatbot'" class="smh-price-quota"><div><span class="smh-price-quota-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4.75A2.25 2.25 0 0 1 7.25 2.5H19v16H7.25A2.25 2.25 0 0 0 5 20.75v-16Z"/><path d="M5 5v15.75M8.5 6.5h7M8.5 10h7M8.5 13.5h4"/></svg></span><dt>{{ copy.knowledgeLimit }}</dt><dd>{{ knowledgeLimit(plan) }}</dd></div></dl>
        <small>{{ copy.approval }}</small>
      </article>
    </div>
    <section v-if="mode === 'chatbot'" class="smh-managed-service" :aria-label="copy.managedKicker">
      <div class="smh-managed-heading">
        <span>{{ copy.managedKicker }}</span>
        <h3>{{ copy.managedTitle }}</h3>
        <p>{{ copy.managedIntro }}</p>
      </div>
      <div class="smh-managed-price">
        <strong>{{ copy.managedFee }}</strong>
        <span>{{ copy.managedQuote }}</span>
      </div>
      <ol>
        <li><strong>{{ copy.managedSetup }}</strong><span>{{ copy.managedSetupText }}</span></li>
        <li><strong>{{ copy.managedConnect }}</strong><span>{{ copy.managedConnectText }}</span></li>
        <li><strong>{{ copy.managedKnowledge }}</strong><span>{{ copy.managedKnowledgeText }}</span></li>
        <li><strong>{{ copy.managedOperate }}</strong><span>{{ copy.managedOperateText }}</span></li>
      </ol>
      <details><summary>{{ copy.managedDetails }}</summary><p>{{ copy.managedDetailsText }}</p></details>
    </section>
    <p class="smh-pricing-note">{{ copy.note }}</p>
    </div>
    <button v-if="!authenticated" type="button" class="smh-pricing-login" @click="$emit('login')">{{ copy.login }}</button>
  </section>
</template>
<style>
.smh-pricing { --price-ink:#183b3a; --price-muted:#536963; color:var(--price-ink); margin:28px auto 40px; width:100%; }
.smh-pricing > header { text-align:center; margin-bottom:30px; }.smh-pricing h2 { font-size:34px;letter-spacing:-.035em;line-height:1.2;margin:0 0 12px; }.smh-pricing > header p { color:var(--price-muted);margin:0;font-size:16px;line-height:1.55; }
.smh-pricing.is-chatbot .smh-pricing-content { display:grid;gap:20px;padding:26px;border:1px solid #d5dfda;border-radius:24px;background:linear-gradient(135deg,#f2f8f5,#fff); }
.smh-pricing-grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;align-items:stretch; }
.smh-pricing.is-chatbot { max-width:1080px; }
.smh-pricing.is-chatbot > header { margin-bottom:26px; }
.smh-pricing.is-chatbot .smh-pricing-grid { grid-template-columns:minmax(0,1fr); }
.smh-price-card { display:flex;flex-direction:column;min-height:620px;padding:25px 21px;border:1px solid #d5dfda;border-radius:18px;background:#fff;min-width:0;transition:background-color .2s,border-color .2s,box-shadow .2s; }
.smh-pricing.is-chatbot .smh-price-card { display:grid;grid-template-columns:minmax(0,.82fr) minmax(0,1.18fr);grid-template-areas:"top benefits" "description benefits" "amount benefits" "action benefits" "approval approval";column-gap:44px;row-gap:0;align-items:start;min-height:0;padding:8px 4px 24px;border:0;border-bottom:1px solid #dce7e3;border-radius:0;background:transparent;box-shadow:none;transition:none; }
.smh-pricing.is-chatbot .smh-price-card:hover,.smh-pricing.is-chatbot .smh-price-card:focus-within { background:transparent;border-color:#dce7e3;box-shadow:none; }
.smh-pricing.is-chatbot .smh-price-card.is-selected { background:transparent;border-color:#dce7e3;box-shadow:none; }
.smh-price-card:hover,.smh-price-card:focus-within { background:#eaf5ee;border-color:#087e77;box-shadow:0 0 0 3px #087e7714,0 8px 24px #087e7710; }
.smh-price-top { display:flex;gap:8px;align-items:center;justify-content:space-between;min-height:27px; }.smh-price-top h3 { margin:0;font-size:20px;line-height:1.3; }.smh-price-top > span { font-size:11px;color:#086b62;font-weight:750; }
.smh-price-top > .current-plan-label { color:#48645b; }
.smh-price-description { min-height:96px;font-size:14px;line-height:1.65;color:var(--price-muted);margin:16px 0 18px; }.smh-price-amount { font-size:26px;line-height:1.4;font-weight:650;letter-spacing:-.035em;margin:0 0 21px;overflow-wrap:anywhere; }
.smh-price-card > button { border:1px solid #bccdc3;border-radius:999px;background:transparent;color:var(--price-ink);font:inherit;font-size:14px;font-weight:700;min-height:46px;padding:10px 12px;cursor:pointer;transition:background-color .2s,color .2s,border-color .2s; }.smh-price-card:hover > button:not(:disabled),.smh-price-card:focus-within > button:not(:disabled),.smh-price-card.is-selected > button:not(:disabled) { background:#087e77;color:white;border-color:#087e77; }.smh-price-card > button:focus-visible,.smh-pricing-login:focus-visible { outline:3px solid #087e77;outline-offset:4px; }
.smh-price-card > button:disabled { cursor:default;opacity:.82; }
.smh-price-card > button.is-downgrade:disabled { color:var(--price-muted);background:transparent;border-style:dashed;cursor:not-allowed;opacity:.65; }
.smh-price-card.is-selected { border-color:#168c82;background:#f0f8f4;box-shadow:0 0 0 2px rgba(8,126,119,.12),0 12px 30px rgba(8,126,119,.08); }
.smh-price-card.is-current:not(.is-selected) { border-color:#8da99d; }
.smh-price-card ul { list-style:none;padding:0;margin:24px 0 21px;display:grid;gap:14px; }.smh-price-card li { display:flex;gap:9px;font-size:14px;line-height:1.55; }.smh-price-card li svg { width:18px;height:21px;flex-shrink:0;stroke:#087e77;stroke-width:1.8;fill:none; }.smh-price-card > small { margin-top:auto;color:var(--price-muted);font-size:12px;line-height:1.6; }
.smh-pricing.is-chatbot .smh-price-top { grid-area:top;align-self:end; }
.smh-pricing.is-chatbot .smh-price-description { grid-area:description;min-height:0;max-width:560px;margin:12px 0 22px; }
.smh-pricing.is-chatbot .smh-price-amount { grid-area:amount;min-height:0;margin:0 0 22px;font-size:32px; }
.smh-pricing.is-chatbot .smh-price-card > button { grid-area:action;width:100%;min-height:50px;border-radius:13px; }
.smh-pricing.is-chatbot .smh-price-card ul { grid-area:benefits;align-self:stretch;align-content:center;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0;padding:0 0 0 28px;border-left:1px solid #dce7e3; }
.smh-pricing.is-chatbot .smh-price-card li { min-height:86px;align-items:flex-start;padding:15px;border:1px solid #dce7e3;border-radius:14px;background:#f3f8f6; }
.smh-pricing.is-chatbot .smh-price-card > small { grid-area:approval;margin-top:22px;padding-top:16px;border-top:1px solid #dce7e3; }
.smh-pricing.is-chatbot .smh-price-amount strong { color:#087e77;font-size:36px; }
.smh-price-quota { margin:0 0 18px;padding:13px;border:1px solid #d5e5de;border-radius:14px;background:linear-gradient(120deg,#f1f8f4,#f7faf8); }.smh-price-quota > div { display:grid;grid-template-columns:38px minmax(0,1fr);grid-template-rows:auto auto;align-items:center;column-gap:11px;min-width:0; }.smh-price-quota dt { grid-column:2;color:var(--price-muted);font-size:11px;font-weight:650;line-height:1.35; }.smh-price-quota-icon { display:grid;place-items:center;grid-column:1;grid-row:1 / 3;width:38px;height:38px;border-radius:11px;background:#dcefeb;color:#087e77; }.smh-price-quota-icon svg { width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round; }.smh-price-quota dd { grid-column:2;margin:3px 0 0;color:var(--price-ink);font-size:15px;font-weight:800;line-height:1.3;white-space:nowrap; }
.smh-pricing-note { text-align:center;font-size:13px;line-height:1.65;color:var(--price-muted);margin:24px auto 0;max-width:720px; }.smh-pricing-login { display:block;margin:16px auto 0;border:0;background:transparent;text-decoration:underline;color:#146c63;padding:12px;cursor:pointer;font:inherit;font-size:14px; }
.smh-pricing.is-chatbot .smh-pricing-note { max-width:none;margin:0 auto;padding-top:16px;border-top:1px solid #dce7e3; }
.smh-price-amount { min-height:72px; }.smh-price-amount strong { display:block;font-weight:650;white-space:nowrap; }.smh-price-amount > span { display:block;font-size:13px;letter-spacing:0;font-weight:400;color:var(--price-muted); }
.smh-managed-service { display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);gap:22px 30px;margin-top:0;padding:24px;border:1px solid #d5dfda;border-radius:18px;background:linear-gradient(125deg,#f2f8f5,#fff); }
.smh-managed-heading > span { color:#087e77;font-size:11px;font-weight:800;letter-spacing:.12em; }.smh-managed-heading h3 { margin:7px 0;font-size:22px;line-height:1.3; }.smh-managed-heading p,.smh-managed-price span { margin:0;color:var(--price-muted);font-size:14px;line-height:1.55; }
.smh-managed-price { align-self:center;display:grid;gap:7px;padding:16px;border:1px solid #d5e5de;border-radius:14px;background:#fff; }.smh-managed-price strong { font-size:16px;line-height:1.4; }
.smh-managed-service ol { grid-column:1 / -1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;list-style:none;padding:0;margin:0;counter-reset:rollout-step; }.smh-managed-service li { display:grid;align-content:start;gap:6px;min-height:126px;padding:17px;border:1px solid transparent;border-radius:15px;background:#eaf3ef;font-size:14px;line-height:1.5; }.smh-managed-service li::before { counter-increment:rollout-step;content:counter(rollout-step,decimal-leading-zero);color:#087e77;font-size:11px;font-weight:850;letter-spacing:.08em; }.smh-managed-service li span { color:var(--price-muted); }
.smh-managed-service details { grid-column:1 / -1;border-top:1px solid #d5dfda;padding-top:13px;color:var(--price-muted);font-size:13px;line-height:1.6; }.smh-managed-service summary { width:max-content;max-width:100%;color:#087e77;font-weight:700;cursor:pointer; }.smh-managed-service details p { margin:8px 0 0; }
body.crm-dark .smh-pricing { --price-ink:#f3f5f6;--price-muted:#b6c0c5; }
body.crm-dark .smh-pricing.is-chatbot .smh-pricing-content { background:linear-gradient(135deg,#20292c,#202427);border-color:#3c4c4d; }
body.crm-dark .smh-price-card { background:#202427;border-color:#394145; }
body.crm-dark .smh-price-card:hover,body.crm-dark .smh-price-card:focus-within { background:#252a2d;border-color:#4a555a; }
body.crm-dark .smh-price-card.is-selected { background:#173f43;border-color:#3c777a;box-shadow:0 0 0 2px rgba(60,119,122,.22),0 12px 30px rgba(0,0,0,.24); }
body.crm-dark .smh-price-card.is-current:not(.is-selected) { border-color:#526b67; }
body.crm-dark .smh-pricing.is-chatbot .smh-price-card,body.crm-dark .smh-pricing.is-chatbot .smh-price-card:hover,body.crm-dark .smh-pricing.is-chatbot .smh-price-card:focus-within,body.crm-dark .smh-pricing.is-chatbot .smh-price-card.is-selected { background:transparent;border-color:#3c4c4d;box-shadow:none; }
body.crm-dark .smh-pricing.is-chatbot .smh-price-card li { background:#263336;border-color:#35494a; }
body.crm-dark .smh-pricing.is-chatbot .smh-price-card > small { border-color:#3c4c4d; }
body.crm-dark .smh-pricing.is-chatbot .smh-price-amount strong { color:#71d8d0; }
body.crm-dark .smh-pricing.is-chatbot .smh-price-card ul { border-color:#3c4c4d; }
body.crm-dark .smh-price-quota { background:linear-gradient(120deg,#202f30,#242a2d);border-color:#3a4c4b; }
body.crm-dark .smh-price-quota-icon { background:#164b4b;color:#8bd8d7; }
body.crm-dark .smh-managed-service { background:linear-gradient(125deg,#202f30,#202427);border-color:#3a4c4b; }
body.crm-dark .smh-managed-heading > span,body.crm-dark .smh-managed-service summary { color:#8bd8d7; }
body.crm-dark .smh-managed-price { background:#202427;border-color:#3a4c4b; }
body.crm-dark .smh-managed-service li { background:#263436;border-color:#35494a; }
body.crm-dark .smh-managed-service li::before { color:#71d8d0; }
body.crm-dark .smh-managed-service details { border-color:#3a4c4b; }
body.crm-dark .smh-pricing.is-chatbot .smh-pricing-note { border-color:#3c4c4d; }
body.crm-dark .smh-price-top > .current-plan-label { color:#c7d6cf; }
body.crm-dark .smh-price-card > button { color:#f3f5f6;border-color:#4a555a; }
body.crm-dark .smh-price-card:hover > button:not(:disabled),body.crm-dark .smh-price-card:focus-within > button:not(:disabled),body.crm-dark .smh-price-card.is-selected > button:not(:disabled) { background:#238b92;border-color:#39a7ad; }
body.crm-dark .smh-price-card > button.is-downgrade:disabled { color:var(--price-muted);background:transparent;border-color:#4a555a; }
body.crm-dark .smh-price-card > button:focus-visible,body.crm-dark .smh-pricing-login:focus-visible { outline-color:#39a7ad; }
body.crm-dark .smh-price-card li svg { stroke:#39a7ad; }
body.crm-dark .smh-price-top > span,body.crm-dark .smh-pricing-login { color:#8bd8d7; }
@media(max-width:900px) { .smh-pricing.is-chatbot .smh-pricing-content { padding:22px; }.smh-pricing.is-chatbot .smh-price-card { grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);column-gap:26px;padding:8px 4px 22px; }.smh-pricing.is-chatbot .smh-price-card ul { padding-left:20px; }.smh-managed-service ol { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:700px) { .smh-pricing.is-chatbot .smh-pricing-content { padding:18px; }.smh-pricing.is-chatbot .smh-price-card { grid-template-columns:1fr;grid-template-areas:"top" "description" "amount" "action" "benefits" "approval";padding:8px 2px 20px; }.smh-pricing.is-chatbot .smh-price-card ul { grid-template-columns:repeat(2,minmax(0,1fr));margin-top:24px;padding:20px 0 0;border-left:0;border-top:1px solid #dce7e3; }.smh-pricing.is-chatbot .smh-price-card > small { margin-top:18px; }.smh-managed-service { grid-template-columns:1fr;padding:20px; } }
@media(max-width:600px) { .smh-pricing-grid { grid-template-columns:1fr; }.smh-price-description { min-height:0; }.smh-pricing h2 { font-size:28px; }.smh-price-card { min-height:0;padding:22px; }.smh-pricing.is-chatbot .smh-price-card { padding:22px; }.smh-pricing.is-chatbot .smh-price-card ul,.smh-managed-service ol { grid-template-columns:1fr; }.smh-managed-service { padding:20px; }.smh-managed-service li { min-height:0; } }
@media(max-width:480px) {
  .smh-pricing { margin-block:18px 24px; }
  .smh-pricing > header { margin-bottom:18px; }
  .smh-price-card { padding:16px; border-radius:14px; }
  .smh-price-description { margin:8px 0 12px; line-height:1.5; }
  .smh-price-amount { min-height:0; margin-bottom:14px; font-size:24px; }
  .smh-price-amount strong,.smh-price-amount > span { display:inline; }
  .smh-price-amount > span { margin-left:6px; }
  .smh-price-card ul { margin:16px 0; gap:8px; }
  .smh-price-quota { padding:9px; margin-bottom:12px; }
  .smh-pricing.is-chatbot .smh-price-card { padding:12px 0 16px; }
  .smh-pricing.is-chatbot .smh-price-card li { min-height:0; padding:10px; }
  .smh-pricing.is-chatbot .smh-price-card ul { margin-top:16px; padding-top:16px; gap:8px; }
}
@media(prefers-reduced-motion:reduce) { .smh-price-card,.smh-price-card > button { transition:none; } }
</style>
