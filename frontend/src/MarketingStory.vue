<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { locale } from './i18n.js';
const props = defineProps({ paused: Boolean });
const index = ref(0);
const focused = ref(false);
const visible = ref(false);
const section = ref(null);
let timer, observer, preference;
const english = computed(() => locale.value === 'en');
const slides = computed(() => english.value ? [
  { tag: 'MADE FOR EVERYDAY SHOP WORK', title: 'Behind every growing shop', accent: 'is a team that cares.', body: 'Keep conversations clear, hand work to the right person, and carry customer context into the next interaction.' },
  { tag: 'KNOWLEDGE THAT SUPPORTS YOUR TEAM', title: 'Answers start with', accent: 'knowing your shop.', body: 'Organize product guides and shop policies in one place. Help staff find the right information and review sources before replying.' },
  { tag: 'CUSTOMER CARE, WITH CONTEXT', title: 'Every return visit', accent: 'feels more familiar.', body: 'Bring conversation history, recorded preferences and follow-up work together. Your team can pick up where the last conversation ended.' },
] : [
  { tag: 'DÀNH CHO CÔNG VIỆC MỖI NGÀY', title: 'Phía sau một shop phát triển', accent: 'là một đội ngũ tận tâm.', body: 'Giữ hội thoại rõ ràng, giao việc đúng người và mang theo ngữ cảnh khi khách quay lại. Một ngày bận rộn không nên đi cùng tin nhắn bị bỏ lỡ.' },
  { tag: 'KIẾN THỨC ĐỒNG HÀNH CÙNG ĐỘI NGŨ', title: 'Muốn trả lời đúng,', accent: 'hãy hiểu shop của mình.', body: 'Tài liệu sản phẩm và chính sách được tổ chức ở một nơi. Đội ngũ dễ tra cứu, kiểm tra nguồn và tiếp quản khi khách cần hỗ trợ trực tiếp.' },
  { tag: 'CHĂM KHÁCH CÓ NGỮ CẢNH', title: 'Mỗi lần khách quay lại,', accent: 'thêm một lần gần gũi.', body: 'Lịch sử trò chuyện, sở thích đã ghi nhận và việc cần theo dõi cùng ở bên nhân viên. Tiếp nối câu chuyện thay vì bắt khách kể lại từ đầu.' },
]);
const slide = computed(() => slides.value[index.value]);
const ui = computed(() => ({ label0: english.value ? "Discover Smart Merchant Hub" : "Khám phá Smart Merchant Hub", label1: english.value ? "Shop team preparing orders together" : "Đội ngũ shop cùng chuẩn bị đơn hàng", label2: english.value ? "YOUR SHOP KNOWLEDGE" : "KHO KIẾN THỨC CỦA SHOP", label3: english.value ? "Illustrative product preview · Review sources before replying" : "Minh họa sản phẩm · Kiểm tra nguồn trước khi trả lời", label4: english.value ? "CUSTOMER 360" : "HỒ SƠ KHÁCH HÀNG 360", label5: english.value ? "Returning customer" : "Khách quay lại", label6: english.value ? "Continue the conversation" : "Tiếp nối cuộc trò chuyện", label7: english.value ? "Follow up at the right time" : "Chăm sóc đúng thời điểm", label8: english.value ? "Illustrative customer profile" : "Hồ sơ khách hàng minh họa", label9: english.value ? "Previous introduction" : "Giới thiệu trước", label10: english.value ? "Introduction " : "Giới thiệu ", label11: english.value ? "Next introduction" : "Giới thiệu tiếp theo" }));
const labels = computed(() => english.value ? ['Product guide', 'Delivery & returns', 'Customer care notes'] : ['Hướng dẫn sản phẩm', 'Giao hàng & đổi trả', 'Ghi chú chăm sóc khách']);
function select(next) { index.value = (next + 3) % 3; }
function trackFocus(event) { focused.value = event.target.matches(':focus-visible'); }
function stopForFocus(event) { focused.value = section.value.contains(event.relatedTarget); }
onMounted(() => {
  preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver(([entry]) => { visible.value = entry.isIntersecting; }, { threshold: .2 });
    observer.observe(section.value);
  } else visible.value = true;
  timer = window.setInterval(() => {
    if (!props.paused && !focused.value && visible.value && !document.hidden && !preference.matches) index.value = (index.value + 1) % 3;
  }, 7000);
});
onUnmounted(() => { window.clearInterval(timer); observer?.disconnect(); });
</script>

<template>
  <section ref="section" class="smh-story smh-container smh-story-carousel" :aria-label="ui.label0" aria-roledescription="carousel" @focusin="trackFocus" @focusout="stopForFocus">
    <div class="smh-story-stage">
      <Transition name="smh-story-fade" mode="out-in">
        <div :key="index" class="smh-story-art">
          <div v-if="index === 0" class="smh-story-photo"><img src="/images/merchant-team.png" width="1536" height="1024" loading="lazy" :alt="ui.label1"/><span class="smh-photo-label">Smart Merchant Hub</span></div>
          <div v-else-if="index === 1" class="smh-story-illustration smh-story-library">
            <span class="smh-story-art-label">{{ ui.label2 }}</span>
            <div class="smh-story-book" aria-hidden="true"><svg><use href="#smh-book"/></svg></div>
            <div v-for="(label, n) in labels" :key="label" class="smh-story-document"><span>0{{ n + 1 }}</span><strong>{{ label }}</strong><svg aria-hidden="true"><use href="#smh-check"/></svg></div>
            <small>{{ ui.label3 }}</small>
          </div>
          <div v-else class="smh-story-illustration smh-story-customer">
            <span class="smh-story-art-label">{{ ui.label4 }}</span>
            <div class="smh-story-person">MA</div><h3>Minh Anh</h3>
            <p>{{ ui.label5 }}</p>
            <div class="smh-story-history"><svg aria-hidden="true"><use href="#smh-chat"/></svg>{{ ui.label6 }}</div>
            <div class="smh-story-history"><svg aria-hidden="true"><use href="#smh-calendar"/></svg>{{ ui.label7 }}</div>
            <small>{{ ui.label8 }}</small>
          </div>
        </div>
      </Transition>
    </div>
    <div class="smh-story-copy">
      <div class="smh-story-text" aria-live="off" aria-atomic="true">
        <Transition name="smh-story-fade" mode="out-in"><div :key="index"><p class="smh-eyebrow">{{ slide.tag }}</p><h2>{{ slide.title }}<br/><em>{{ slide.accent }}</em></h2><p class="smh-story-description">{{ slide.body }}</p></div></Transition>
      </div>
      <div class="smh-story-controls">
        <button type="button" :aria-label="ui.label9" @click="select(index - 1)">‹</button>
        <button v-for="(item, n) in slides" :key="n" class="smh-story-dot" type="button" :aria-label="(ui.label10) + (n + 1)" :aria-current="index === n ? 'true' : undefined" @click="select(n)"><span/></button>
        <button type="button" :aria-label="ui.label11" @click="select(index + 1)">›</button>
      </div>
    </div>
  </section>
</template>

<style>
.smh-story-carousel{min-height:650px}.smh-story-stage{min-width:0}.smh-story-art{width:100%}.smh-story-text{min-height:285px}.smh-story-description{margin:23px 0;color:var(--smh-muted);font-size:16px;line-height:1.75}.smh-story-illustration{aspect-ratio:1.28;border-radius:12px;padding:32px;display:flex;flex-direction:column;justify-content:center;gap:16px;background:#e3ede8;overflow:hidden}.smh-story-art-label{font-size:12px;letter-spacing:.12em;font-weight:750;color:#176b67}.smh-story-book{display:grid;place-items:center;align-self:center;width:86px;height:86px;background:#047f79;color:white;border-radius:16px;transform:rotate(-8deg);margin-bottom:8px}.smh-story-book svg{width:42px!important;height:42px!important}.smh-story-document{display:flex;align-items:center;gap:16px;padding:16px;background:#fff;border-radius:8px;font-size:15px}.smh-story-document>span{color:#6a8c83;font-size:13px}.smh-story-document svg{margin-left:auto;color:#00847e}.smh-story-illustration small{font-size:12px;color:#50706a;line-height:1.6}.smh-story-customer{background:#eee9df;align-items:center;text-align:center}.smh-story-person{width:80px;height:80px;background:#cee6e0;border:6px solid white;border-radius:50%;display:grid;place-items:center;font-size:24px;color:#066f69}.smh-story-customer h3,.smh-story-customer p{margin:0}.smh-story-history{display:flex;align-items:center;gap:14px;background:#fff;padding:15px 20px;border-radius:8px;width:100%;font-size:15px;text-align:left}.smh-story-controls{display:flex;align-items:center;gap:6px}.smh-story-controls button{border:0;background:transparent;min-width:44px;min-height:44px;color:#076f6a;cursor:pointer;font-size:24px;border-radius:8px}.smh-story-controls button:hover{background:#e0efea}.smh-story-controls button:focus-visible{outline:2px solid #00847e;outline-offset:3px}.smh-story-dot span{display:block;width:22px;height:4px;border-radius:4px;background:#bdd3c8;margin:auto}.smh-story-dot[aria-current] span{background:#00847e}.smh-story-fade-enter-active{transition:opacity .35s ease,transform .35s ease}.smh-story-fade-leave-active{transition:opacity .18s ease}.smh-story-fade-enter-from{opacity:0;transform:translateY(10px)}.smh-story-fade-leave-to{opacity:0}@media(max-width:900px){.smh-story-text{min-height:335px}.smh-story-illustration{padding:22px}}@media(max-width:680px){.smh-story-carousel{min-height:0}.smh-story-text{min-height:280px}.smh-story-illustration{aspect-ratio:auto;min-height:365px}.smh-story-controls{gap:2px}}@media(prefers-reduced-motion:reduce){.smh-story-fade-enter-active,.smh-story-fade-leave-active{transition:none}}
.smh-story-illustration { color:#243b3a; }
.smh-story-art-label { color:#075e5a; font-size:13px; }
.smh-story-document { color:#263c3a; font-size:16px; }
.smh-story-document strong { color:#263c3a; }
.smh-story-document > span { color:#456d66; font-size:14px; }
.smh-story-illustration small { color:#405b55; font-size:13px; }
.smh-story-customer h3 { color:#263c3a; font-size:19px; }
.smh-story-customer p { color:#405b55; font-size:16px; }
.smh-story-history { color:#29433f; font-size:16px; }
.crm-app.public-home.crm-dark .smh-story-illustration { color:#e6efeb; background:#20292a; }
.crm-app.public-home.crm-dark .smh-story-art-label { color:#7dd9c6; }
.crm-app.public-home.crm-dark .smh-story-document,.crm-app.public-home.crm-dark .smh-story-history { color:#e1ebe6; background:#293435; }
.crm-app.public-home.crm-dark .smh-story-document strong { color:#e1ebe6; }
.crm-app.public-home.crm-dark .smh-story-document > span,.crm-app.public-home.crm-dark .smh-story-illustration small,.crm-app.public-home.crm-dark .smh-story-customer p { color:#b7cac2; }
.crm-app.public-home.crm-dark .smh-story-customer h3 { color:#e1ebe6; }
.crm-app.public-home.crm-dark .smh-story-person { color:#9fe5d7; background:#294340; border-color:#20292a; }
.crm-app.public-home.crm-dark .smh-story-controls button:hover { background:#263334; }
</style>
