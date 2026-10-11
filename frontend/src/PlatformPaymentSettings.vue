<script setup>
import { onMounted, ref } from 'vue';
import { apiFetch } from './api-client.js';
const props = defineProps({ apiBase: { type: String, default: '/api' } });
const config = ref({ enabled: false, account_number: '', bank_bin: '', account_name: '', bank_options: [] });
const busy = ref(false);
const loaded = ref(false);
const error = ref('');
const notice = ref('');
async function request(method, suffix = '', body) {
  const response = await apiFetch(`${props.apiBase}/platform/payment-settings${suffix}`, {
    method, headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error('configuration');
  return result;
}
async function load() {
  if (busy.value) return;
  busy.value = true; error.value = ''; notice.value = '';
  try { config.value = await request('GET'); loaded.value = true; }
  catch { error.value = 'Chưa thể tải cấu hình thanh toán. Vui lòng thử lại.'; }
  finally { busy.value = false; }
}
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const { enabled, account_number, bank_bin, account_name } = config.value;
    config.value = await request('PUT', '', { enabled, bank_bin, account_number, account_name });
    notice.value = 'Đã lưu cấu hình thanh toán.';
  } catch { error.value = 'Chưa thể lưu cấu hình thanh toán. Vui lòng kiểm tra và thử lại.'; }
  finally { busy.value = false; }
}
async function checkConfiguration() {
  if (busy.value) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const result = await request('POST', '/test', {});
    if (result.status !== 'configured') throw new Error('configuration');
    notice.value = 'Cấu hình đã lưu hợp lệ. Kết quả này không xác minh ngân hàng hoặc thanh toán thực tế.';
  } catch { error.value = 'Chưa xác nhận được cấu hình đã lưu. Vui lòng kiểm tra và thử lại.'; }
  finally { busy.value = false; }
}
onMounted(load);
</script>

<template>
  <article id="admin-payments" class="platform-admin-panel payment-settings-panel">
    <div class="platform-admin-panel-heading">
      <div><h3>Cấu hình thanh toán</h3><p>Chọn ngân hàng và tài khoản chính nhận phí nền tảng bằng VietQR.</p></div>
      <button type="button" class="settings-refresh" :disabled="busy" @click="load">{{ busy ? 'Đang xử lý…' : 'Tải lại' }}</button>
    </div>
    <p v-if="error" role="alert" class="settings-notice team-error">{{ error }}</p>
    <p v-if="notice" role="status" class="settings-notice">{{ notice }}</p>
    <template v-if="loaded">
      <form @submit.prevent="save" :aria-busy="busy">
        <fieldset :disabled="busy">
          <label class="payment-settings-toggle"><input v-model="config.enabled" type="checkbox" /> Bật thanh toán chung cho nền tảng</label>
          <div class="payment-settings-fields">
            <label>Ngân hàng nhận phí<select v-model="config.bank_bin" :required="config.enabled">
              <option value="">{{ 'Chọn ngân hàng' }}</option>
              <option v-if="config.bank_bin && !(config.bank_options || []).some(bank => bank.bin === config.bank_bin)" :value="config.bank_bin">{{ config.bank_name || config.bank_bin }}</option>
              <option v-for="bank in config.bank_options || []" :key="bank.bin" :value="bank.bin">{{ bank.name }}</option>
            </select></label>
            <label>Số tài khoản<input v-model.trim="config.account_number" inputmode="numeric" :required="config.enabled" /></label>
            <label>Tên chủ tài khoản<input v-model.trim="config.account_name" :required="config.enabled" /></label>
          </div>
          <p>Chỉ dùng một tài khoản nhận phí nền tảng. Thay đổi áp dụng cho QR mới; QR đã tạo giữ nguyên ngân hàng, tài khoản, số tiền và nội dung chuyển khoản.</p>
          <button type="submit" class="primary-btn">{{ busy ? 'Đang xử lý…' : 'Lưu cấu hình thanh toán' }}</button>
        </fieldset>
      </form>
      <div class="payment-settings-check">
        <button type="button" class="settings-refresh" :disabled="busy" @click="checkConfiguration">Kiểm tra cấu hình</button>
        <p>VietQR chỉ tạo mã chuyển khoản. Kiểm tra cấu hình chỉ kiểm tra dữ liệu đã lưu tại hệ thống, không xác minh tài khoản ngân hàng hoặc giao dịch. Admin xác nhận thực nhận tiền trước khi ghi nhận thanh toán.</p>
      </div>
    </template>
  </article>
</template>

<style scoped>
.payment-settings-panel fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.payment-settings-toggle { display: flex; align-items: center; gap: 10px; margin: 16px 0; }
.payment-settings-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.payment-settings-fields label { display: grid; gap: 8px; font-weight: 600; }
.payment-settings-panel :is(input:not([type='checkbox']), select) { width: 100%; min-width: 0; box-sizing: border-box; padding: 12px; border: 1px solid var(--admin-line); color: var(--admin-ink); background: var(--admin-surface); }
.payment-settings-panel input:focus-visible { outline: 2px solid var(--admin-accent); outline-offset: 2px; }
.payment-settings-panel p { line-height: 1.6; overflow-wrap: anywhere; }
.payment-settings-check { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--admin-line); }
@media (max-width: 640px) { .payment-settings-fields { grid-template-columns: 1fr; } }
</style>
