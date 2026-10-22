<script setup>
import { computed, ref } from "vue";
import { apiFetch } from "./api-client.js";
import { locale, formatMoney } from "./i18n.js";

const props = defineProps({ apiBase: { type: String, default: "/api" } });
const query = ref("bình nước màu hồng, ngân sách 300k");
const recency = ref(14);
const frequency = ref(5);
const monetary = ref(1470000);
const result = ref(null);
const busy = ref(false);
const error = ref("");
const copy = computed(() => locale.value === "en" ? {
  title: "Try the trained models", intro: "Rank three candidates from the supplied synthetic catalog and test purchase-based groups.",
  query: "Product request", recency: "Days since last purchase", frequency: "Completed orders",
  monetary: "Completed-order spend (VND)", run: "Run preview", running: "Running preview…",
  error: "The preview is unavailable. Check that the trained models have been installed.",
  ranking: "Product ranking", empty: "No in-stock products match this request. Try another budget or color.",
  baseline: "Original position", score: "Ranking score", available: "Available",
  segment: "Purchase-based group", new: "New customer · no completed orders",
  group: "Group", note: "Group numbers are identifiers, not VIP levels.", customers: "Customers in training group",
  medianRecency: "Median days since last order", medianFrequency: "Median completed orders",
  medianMonetary: "Median completed-order spend",
  metrics: "Held-out synthetic test", hit: "Chosen item ranked first", baseHit: "Original first-position baseline",
  scope: "Preview only · no customer message is sent", sample: "Products come from the supplied synthetic dataset.",
} : {
  title: "Thử mô hình đã huấn luyện", intro: "Xếp hạng ba ứng viên từ danh mục tổng hợp bạn đã gửi và thử phân nhóm theo lịch sử mua.",
  query: "Yêu cầu sản phẩm", recency: "Số ngày từ lần mua cuối", frequency: "Số đơn hoàn tất",
  monetary: "Chi tiêu từ đơn hoàn tất (đồng)", run: "Chạy thử", running: "Đang chạy thử…",
  error: "Chưa thể chạy thử. Hãy kiểm tra bộ mô hình đã được cài vào hệ thống.",
  ranking: "Xếp hạng sản phẩm", empty: "Không có sản phẩm còn hàng phù hợp. Thử đổi ngân sách hoặc màu sắc.",
  baseline: "Vị trí ban đầu", score: "Điểm xếp hạng", available: "Còn hàng",
  segment: "Nhóm theo lịch sử mua", new: "Khách mới · chưa có đơn hoàn tất",
  group: "Nhóm", note: "Số nhóm là mã nhận diện, không phải mức VIP.", customers: "Số khách trong nhóm huấn luyện",
  medianRecency: "Số ngày từ đơn gần nhất (trung vị)", medianFrequency: "Số đơn hoàn tất (trung vị)",
  medianMonetary: "Chi tiêu đơn hoàn tất (trung vị)",
  metrics: "Kiểm thử trên phần dữ liệu tổng hợp chưa dùng để huấn luyện", hit: "Sản phẩm được chọn đứng đầu",
  baseHit: "So với chọn vị trí đầu ban đầu", scope: "Chỉ xem thử · không gửi tin cho khách",
  sample: "Sản phẩm lấy từ bộ dữ liệu tổng hợp bạn đã gửi.",
});

async function runPreview() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const response = await apiFetch(props.apiBase + "/recommendations/demo/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query.value, recency_days: Number(recency.value),
        frequency: Number(frequency.value), monetary: Number(monetary.value) }),
    });
    if (!response.ok) throw new Error("preview_unavailable");
    result.value = await response.json();
  } catch {
    error.value = copy.value.error;
    result.value = null;
  } finally { busy.value = false; }
}
</script>

<template>
  <section class="settings-card model-preview" aria-labelledby="model-preview-title">
    <header>
      <div><h3 id="model-preview-title">{{ copy.title }}</h3><p>{{ copy.intro }}</p></div>
      <span class="count-badge">{{ copy.scope }}</span>
    </header>
    <form @submit.prevent="runPreview" :aria-busy="busy">
      <label class="model-query">{{ copy.query }}
        <input v-model="query" maxlength="1000" />
      </label>
      <div class="model-fields">
        <label>{{ copy.recency }}<input v-model.number="recency" type="number" min="0" max="36500" required /></label>
        <label>{{ copy.frequency }}<input v-model.number="frequency" type="number" min="0" max="100000" required /></label>
        <label>{{ copy.monetary }}<input v-model.number="monetary" type="number" min="0" max="1000000000000" step="any" required /></label>
      </div>
      <button class="primary-btn" type="submit" :disabled="busy">{{ busy ? copy.running : copy.run }}</button>
      <p v-if="error" class="product-error" role="alert">{{ error }}</p>
    </form>
    <div v-if="result" class="model-results" aria-live="polite">
      <div>
        <h4>{{ copy.ranking }}</h4><p>{{ copy.sample }}</p>
        <ol v-if="result.ranked.length" class="model-ranking">
          <li v-for="item in result.ranked" :key="item.product_id">
            <strong>{{ item.name }}</strong>
            <span>{{ item.sku }} · {{ formatMoney(item.price) }} · {{ copy.available }}: {{ item.available }}</span>
            <small>{{ copy.baseline }}: {{ item.baseline_position }} · {{ copy.score }}: {{ item.model_score.toFixed(3) }}</small>
          </li>
        </ol>
        <p v-else>{{ copy.empty }}</p>
      </div>
      <div class="model-segment">
        <h4>{{ copy.segment }}</h4>
        <strong>{{ result.rfm.cluster_id === null ? copy.new : copy.group + " " + (result.rfm.cluster_id + 1) }}</strong>
        <p>{{ copy.note }}</p>
        <dl v-if="result.rfm.training_cluster_summary" class="model-rfm-summary">
          <div><dt>{{ copy.customers }}</dt><dd>{{ result.rfm.training_cluster_summary.customers }}</dd></div>
          <div><dt>{{ copy.medianRecency }}</dt><dd>{{ result.rfm.training_cluster_summary.median_recency_days }}</dd></div>
          <div><dt>{{ copy.medianFrequency }}</dt><dd>{{ result.rfm.training_cluster_summary.median_frequency }}</dd></div>
          <div><dt>{{ copy.medianMonetary }}</dt><dd>{{ formatMoney(result.rfm.training_cluster_summary.median_monetary) }}</dd></div>
        </dl>
        <h4>{{ copy.metrics }}</h4>
        <p>{{ copy.hit }}: <strong>{{ (result.held_out_metrics.hit_at_1 * 100).toFixed(1) }}%</strong></p>
        <p>{{ copy.baseHit }}: {{ (result.held_out_metrics.position_1_baseline_hit_at_1 * 100).toFixed(1) }}%</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.model-preview { min-width: 0; }
.model-preview header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 16px; align-items: start; }
.model-preview p { line-height: 1.6; overflow-wrap: anywhere; }
.model-preview form { display: grid; gap: 16px; margin-top: 20px; }
.model-fields, .model-results { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.model-results { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); margin-top: 24px; }
.model-preview label { display: grid; gap: 8px; font-weight: 600; min-width: 0; }
.model-preview input { width: 100%; min-height: 44px; box-sizing: border-box; font: inherit; }
.model-preview button { justify-self: start; min-height: 44px; }
.model-ranking { padding-left: 24px; }
.model-ranking li { padding: 12px 0; line-height: 1.6; overflow-wrap: anywhere; }
.model-ranking span, .model-ranking small { display: block; }
.model-segment { min-width: 0; }
.model-rfm-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; }
.model-rfm-summary div { min-width: 0; }
.model-rfm-summary dt { font-size: .82em; opacity: .75; }
.model-rfm-summary dd { margin: 4px 0 0; font-weight: 650; overflow-wrap: anywhere; }
@media (max-width: 700px) {
  .model-fields, .model-results { grid-template-columns: 1fr; }
  .model-rfm-summary { grid-template-columns: 1fr; }
  .model-preview button { justify-self: stretch; }
}
</style>

