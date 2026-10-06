<script setup>
import { computed } from "vue";
import { locale, t } from "./i18n.js";

const props = defineProps({
  plan: { type: Object, default: null },
  currentPlan: { type: Object, default: null },
  mode: { type: String, default: "package" },
  changeKind: { type: String, default: "new" },
  buyer: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
  submitted: { type: Boolean, default: false },
  status: { type: String, default: "" },
  notice: { type: String, default: "" },
  requestReference: { type: String, default: "" },
});

const emit = defineEmits(["back", "submit", "refresh"]);

function isDowngrade() {
  return props.changeKind === "downgrade";
}

const copy = computed(() => locale.value === "en" ? {
  pageLabel: "Plan checkout",
  back: "← Back to plans",
  title: "Plan payment",
  downgradeTitle: "Confirm plan downgrade",
  subtitle: "Review the selected plan and price before submitting your request.",
  order: "Plan change details",
  downgrade: "Downgrade",
  upgrade: "Upgrade",
  newPlan: "New plan",
  currentPlan: "CURRENT PLAN",
  start: "START",
  noActivePlan: "No active plan",
  selectedPlan: "NEW PLAN",
  serviceType: "Service type",
  chatbot: "Dedicated chatbot",
  management: "Shop management plan",
  channelLimit: "Channel limit",
  channels: "platforms",
  shop: "Shop",
  registrant: "Account holder",
  email: "Contact email",
  requestRecorded: "Request recorded",
  activated: "Plan activated",
  requestCode: "Request reference:",
  summary: "SUMMARY",
  afterDowngrade: "Plan after downgrade",
  chosenPlan: "Selected plan",
  newPlanPrice: "NEW PLAN PRICE",
  planPrice: "PLAN PRICE",
  downgradePolicyTitle: "Downgrade only · no refund",
  downgradePolicy: "This request changes only the plan and its limits. It does not create a refund or return the price difference. Your current plan stays active until the change is confirmed.",
  approvalTitle: "Confirmation process",
  approval: "Submit the request for administrator confirmation. This step does not charge you online; payment instructions follow the current confirmation process.",
  submitDowngrade: "Submit downgrade request",
  submitPayment: "Submit payment request",
  activateDemo: "Activate Demo plan",
  sent: "Request submitted",
  sending: "Submitting request…",
  accountNote: "The request is linked to the shop account currently signed in.",
  refresh: "Refresh status",
  genericPlan: "Service plan",
  noCurrentPlan: "No active plan",
  contactPrice: "Contact us for pricing",
}: {
  pageLabel: "Thanh toán gói dịch vụ",
  back: "← Quay lại các gói",
  title: "Thanh toán gói dịch vụ",
  downgradeTitle: "Xác nhận hạ gói",
  subtitle: "Kiểm tra gói và chi phí trước khi gửi yêu cầu.",
  order: "Thông tin chuyển gói",
  downgrade: "Hạ gói",
  upgrade: "Nâng cấp",
  newPlan: "Gói mới",
  currentPlan: "GÓI HIỆN TẠI",
  start: "BẮT ĐẦU",
  noActivePlan: "Chưa có gói đang hoạt động",
  selectedPlan: "GÓI MỚI",
  serviceType: "Loại dịch vụ",
  chatbot: "Trợ lý chatbot riêng",
  management: "Gói quản lý shop",
  channelLimit: "Hạn mức kênh",
  channels: "nền tảng",
  shop: "Shop",
  registrant: "Người đăng ký",
  email: "Email nhận thông tin",
  requestRecorded: "Đã ghi nhận yêu cầu",
  activated: "Gói đã được kích hoạt",
  requestCode: "Mã yêu cầu:",
  summary: "TÓM TẮT",
  afterDowngrade: "Gói sau khi hạ",
  chosenPlan: "Gói được chọn",
  newPlanPrice: "MỨC PHÍ GÓI MỚI",
  planPrice: "GIÁ GÓI",
  downgradePolicyTitle: "Hạ gói, không hoàn tiền",
  downgradePolicy: "Yêu cầu chỉ thay đổi gói và hạn mức. Không tạo yêu cầu hoàn tiền hoặc hoàn phần chênh lệch. Gói hiện tại giữ nguyên đến khi yêu cầu được xác nhận.",
  approvalTitle: "Quy trình xác nhận",
  approval: "Gửi yêu cầu để quản trị viên xác nhận. Bước này chưa thu tiền trực tuyến; hướng dẫn thanh toán sẽ theo quy trình xác nhận hiện tại.",
  submitDowngrade: "Gửi yêu cầu hạ gói",
  submitPayment: "Gửi yêu cầu thanh toán",
  activateDemo: "Kích hoạt gói Demo",
  sent: "Đã gửi yêu cầu",
  sending: "Đang gửi yêu cầu…",
  accountNote: "Yêu cầu được gắn với đúng tài khoản shop đang đăng nhập.",
  refresh: "Làm mới trạng thái",
  genericPlan: "Gói dịch vụ",
  noCurrentPlan: "Chưa có gói đang hoạt động",
  contactPrice: "Liên hệ để biết giá",
});

function planName(plan, fallback) {
  return plan?.name ? t(plan.name) : fallback;
}
</script>

<template>
  <section class="service-checkout-page" :aria-label="copy.pageLabel">
    <header class="service-checkout-header">
      <button type="button" class="checkout-back" @click="emit('back')">{{ copy.back }}</button>
      <span class="service-page-kicker">CHECKOUT · SMART MERCHANT HUB</span>
      <h1>{{ isDowngrade() ? copy.downgradeTitle : copy.title }}</h1>
      <p>{{ copy.subtitle }}</p>
    </header>

    <div class="service-checkout-grid">
      <section class="checkout-card checkout-order-card" aria-labelledby="checkout-order-title">
        <div class="checkout-card-heading">
          <div><span class="checkout-step">01</span><h2 id="checkout-order-title">{{ copy.order }}</h2></div>
          <span class="checkout-kind-pill" :class="`is-${changeKind}`">{{ isDowngrade() ? copy.downgrade : changeKind === 'upgrade' ? copy.upgrade : copy.newPlan }}</span>
        </div>

        <div class="checkout-plan-flow">
          <div class="checkout-plan-block" :class="{ muted: !currentPlan }">
            <small>{{ currentPlan ? copy.currentPlan : copy.start }}</small>
            <strong>{{ planName(currentPlan, copy.noCurrentPlan) }}</strong>
            <span v-if="currentPlan">{{ currentPlan.price }}</span>
          </div>
          <span class="checkout-flow-arrow" aria-hidden="true">→</span>
          <div class="checkout-plan-block target">
            <small>{{ copy.selectedPlan }}</small>
            <strong>{{ planName(plan, copy.genericPlan) }}</strong>
            <span>{{ plan?.price || copy.contactPrice }}</span>
          </div>
        </div>

        <dl class="checkout-details">
          <div><dt>{{ copy.serviceType }}</dt><dd>{{ mode === 'chatbot' ? copy.chatbot : copy.management }}</dd></div>
          <div v-if="mode !== 'chatbot'"><dt>{{ copy.channelLimit }}</dt><dd>{{ plan?.max_channels ?? '—' }} {{ copy.channels }}</dd></div>
          <div v-if="buyer?.shop_name"><dt>{{ copy.shop }}</dt><dd>{{ buyer.shop_name }}</dd></div>
          <div v-if="buyer?.name"><dt>{{ copy.registrant }}</dt><dd>{{ buyer.name }}</dd></div>
          <div v-if="buyer?.email"><dt>{{ copy.email }}</dt><dd>{{ buyer.email }}</dd></div>
        </dl>

        <div v-if="error" class="checkout-error" role="alert">{{ error }}</div>
        <div v-if="submitted" class="checkout-confirmation" role="status">
          <span class="checkout-confirmation-icon" aria-hidden="true">✓</span>
          <div>
            <strong>{{ status === 'pending' ? copy.requestRecorded : copy.activated }}</strong>
            <p>{{ notice }}</p>
            <small v-if="requestReference">{{ copy.requestCode }} <b>{{ requestReference }}</b></small>
          </div>
          <button type="button" class="checkout-refresh" @click="emit('refresh')">{{ copy.refresh }}</button>
        </div>
      </section>

      <aside class="checkout-card checkout-total-card" :aria-label="copy.summary">
        <span class="checkout-total-kicker">{{ copy.summary }}</span>
        <div class="checkout-total-line"><span>{{ isDowngrade() ? copy.afterDowngrade : copy.chosenPlan }}</span><strong>{{ planName(plan, '—') }}</strong></div>
        <div class="checkout-total-price"><small>{{ isDowngrade() ? copy.newPlanPrice : copy.planPrice }}</small><strong>{{ plan?.price || '—' }}</strong></div>

        <div v-if="isDowngrade()" class="checkout-policy is-downgrade">
          <strong>{{ copy.downgradePolicyTitle }}</strong>
          <p>{{ copy.downgradePolicy }}</p>
        </div>
        <div v-else class="checkout-policy">
          <strong>{{ copy.approvalTitle }}</strong>
          <p>{{ copy.approval }}</p>
        </div>

        <button type="button" class="checkout-submit" :disabled="loading || submitted || !plan" @click="emit('submit')">
          {{ loading ? copy.sending : submitted ? copy.sent : isDowngrade() ? copy.submitDowngrade : plan?.code === 'demo' ? copy.activateDemo : copy.submitPayment }}
          <span v-if="!loading && !submitted" aria-hidden="true">→</span>
        </button>
        <small class="checkout-secure-note">{{ copy.accountNote }}</small>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.service-checkout-page { --checkout-ink:#edf5f4; --checkout-muted:#afc2c1; --checkout-panel:#20282b; --checkout-line:#39484b; --checkout-accent:#1fa3a0; width:min(1180px,100%); margin:0 auto; padding:clamp(22px,4vw,48px); color:var(--checkout-ink); }
.service-checkout-header { margin-bottom:24px; }
.checkout-back { display:inline-flex; align-items:center; min-height:38px; margin:0 0 22px; padding:0 13px; border:1px solid var(--checkout-line); border-radius:10px; background:transparent; color:var(--checkout-ink); font:inherit; font-size:13px; font-weight:700; cursor:pointer; }
.checkout-back:hover { border-color:#55c1bc; background:#183f40; }
.service-checkout-header .service-page-kicker { display:block; margin-bottom:8px; color:#45c5bd; font-size:11px; letter-spacing:.13em; font-weight:850; }
.service-checkout-header h1 { margin:0; font-size:clamp(28px,4vw,40px); letter-spacing:-.035em; }
.service-checkout-header p { margin:9px 0 0; color:var(--checkout-muted); }
.service-checkout-grid { display:grid; grid-template-columns:minmax(0,1.6fr) minmax(280px,.8fr); gap:18px; align-items:start; }
.checkout-card { padding:clamp(18px,3vw,28px); border:1px solid var(--checkout-line); border-radius:20px; background:var(--checkout-panel); box-shadow:0 16px 50px #0002; }
.checkout-card-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:24px; }
.checkout-card-heading > div { display:flex; align-items:center; gap:12px; }
.checkout-step { display:grid; width:34px; height:34px; place-items:center; border-radius:11px; background:#164a4d; color:#85e2db; font-size:11px; font-weight:900; }
.checkout-card h2 { margin:0; font-size:19px; }
.checkout-kind-pill { padding:6px 10px; border:1px solid #3a6663; border-radius:999px; color:#a1dfd4; background:#183936; font-size:11px; font-weight:800; }
.checkout-kind-pill.is-downgrade { border-color:#79603a; color:#ffdda1; background:#3a3021; }
.checkout-plan-flow { display:grid; grid-template-columns:minmax(0,1fr) 36px minmax(0,1fr); gap:12px; align-items:center; }
.checkout-plan-block { display:grid; align-content:start; gap:8px; min-height:128px; padding:17px; border:1px solid var(--checkout-line); border-radius:15px; background:#1a2022; }
.checkout-plan-block.target { border-color:#277f7d; background:linear-gradient(145deg,#153b3e,#202b2e 70%); }
.checkout-plan-block.muted { opacity:.7; }
.checkout-plan-block small,.checkout-total-kicker { color:#68c9c4; font-size:10px; letter-spacing:.12em; font-weight:850; }
.checkout-plan-block strong { font-size:17px; overflow-wrap:anywhere; }
.checkout-plan-block span { color:var(--checkout-muted); font-size:13px; }
.checkout-flow-arrow { color:#65cbc6; text-align:center; font-size:24px; }
.checkout-details { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 24px; margin:20px 0 0; }
.checkout-details > div { display:flex; justify-content:space-between; gap:12px; padding:13px 0; border-bottom:1px solid #344043; }
.checkout-details dt { color:var(--checkout-muted); font-size:12px; }
.checkout-details dd { margin:0; text-align:right; font-size:12px; font-weight:750; overflow-wrap:anywhere; }
.checkout-total-card { position:sticky; top:18px; }
.checkout-total-line { display:grid; gap:7px; padding:18px 0; border-bottom:1px solid var(--checkout-line); }
.checkout-total-line span { color:var(--checkout-muted); font-size:12px; }
.checkout-total-line strong { font-size:17px; }
.checkout-total-price { display:grid; gap:8px; padding:21px 0; }
.checkout-total-price small { color:var(--checkout-muted); font-size:10px; letter-spacing:.1em; font-weight:850; }
.checkout-total-price strong { font-size:28px; color:#8ee0dc; letter-spacing:-.03em; }
.checkout-policy { margin:0 0 18px; padding:14px; border:1px solid #344f53; border-radius:13px; background:#1a3032; }
.checkout-policy.is-downgrade { border-color:#65543c; background:#332d22; }
.checkout-policy strong { font-size:12px; }
.checkout-policy p { margin:7px 0 0; color:var(--checkout-muted); font-size:12px; line-height:1.6; }
.checkout-submit { display:flex; width:100%; min-height:50px; align-items:center; justify-content:center; gap:10px; border:0; border-radius:12px; background:linear-gradient(110deg,#159f9e,#187d88); color:white; font:inherit; font-size:14px; font-weight:850; cursor:pointer; box-shadow:0 10px 22px #087d7933; }
.checkout-submit:hover:not(:disabled) { filter:brightness(1.1); transform:translateY(-1px); }
.checkout-submit:disabled { opacity:.58; cursor:not-allowed; }
.checkout-secure-note { display:block; margin-top:12px; color:var(--checkout-muted); text-align:center; font-size:10px; line-height:1.5; }
.checkout-error { margin-top:18px; padding:12px 14px; border:1px solid #864946; border-radius:11px; background:#3b2425; color:#ffd8d5; font-size:13px; }
.checkout-confirmation { display:flex; align-items:flex-start; gap:12px; margin-top:20px; padding:15px; border:1px solid #397568; border-radius:14px; background:#193630; }
.checkout-confirmation-icon { display:grid; flex:0 0 26px; height:26px; place-items:center; border-radius:50%; background:#24785e; color:white; font-weight:900; }
.checkout-confirmation strong { display:block; font-size:14px; }
.checkout-confirmation p { margin:5px 0; color:#c1d3cd; font-size:12px; line-height:1.5; }
.checkout-confirmation small { color:#a5c5ba; font-size:11px; }
.checkout-refresh { flex:0 0 auto; margin-left:auto; padding:7px 10px; border:1px solid #436b62; border-radius:9px; background:transparent; color:inherit; font:inherit; font-size:11px; cursor:pointer; }
@media(max-width:760px) { .service-checkout-page { padding:20px 14px; }.service-checkout-grid { grid-template-columns:1fr; }.checkout-total-card { position:static; }.checkout-plan-flow { grid-template-columns:minmax(0,1fr) 26px minmax(0,1fr); gap:6px; }.checkout-plan-block { min-height:120px; padding:13px; }.checkout-details { grid-template-columns:1fr; }.checkout-confirmation { flex-wrap:wrap; }.checkout-refresh { margin-left:38px; } }
@media(prefers-reduced-motion:reduce) { .checkout-submit:hover:not(:disabled) { transform:none; } }
</style>
