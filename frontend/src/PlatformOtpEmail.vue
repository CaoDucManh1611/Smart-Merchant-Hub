<script setup>
import { onMounted, ref } from "vue";
import { apiFetch } from "./api-client.js";

const props = defineProps({ apiBase: { type: String, default: "/api" } });
const config = ref({ enabled: false, username: "", from_email: "", from_name: "Smart Merchant Hub", password_configured: false });
const password = ref("");
const recipient = ref("");
const busy = ref(false);
const loaded = ref(false);
const error = ref("");
const notice = ref("");

async function request(method, suffix = "", body) {
  const response = await apiFetch(`${props.apiBase}/platform/otp-email${suffix}`, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Chưa thể hoàn tất. Vui lòng kiểm tra cấu hình và thử lại.");
  return result;
}

async function load() {
  busy.value = true;
  error.value = "";
  try { config.value = await request("GET"); loaded.value = true; }
  catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}

async function save() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    config.value = await request("PUT", "", { ...config.value, password: password.value });
    notice.value = "Đã lưu cấu hình. Hãy gửi email thử trước khi cho khách đăng ký.";
  } catch (e) { error.value = e.message; }
  finally { password.value = ""; busy.value = false; }
}

async function sendTest() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await request("POST", "/test", { email: recipient.value });
    notice.value = "Đã gửi email thử. Kiểm tra hộp thư đến và thư rác của email nhận.";
  } catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}

onMounted(load);
</script>

<template>
  <article id="admin-otp-email" class="platform-admin-panel otp-email-panel">
    <div class="platform-admin-panel-heading">
      <div><span class="card-eyebrow">EMAIL HỆ THỐNG</span><h3>Email gửi OTP</h3><p>Cấu hình một lần. Mã xác minh được tự động gửi đến email mà khách nhập khi đăng ký.</p></div>
      <button type="button" class="settings-refresh" :disabled="busy" @click="load">{{ busy ? 'Đang xử lý…' : 'Tải lại' }}</button>
    </div>
    <p v-if="error" role="alert" class="settings-notice team-error">{{ error }}</p>
    <p v-if="notice" role="status" class="settings-notice">{{ notice }}</p>
    <template v-if="loaded">
      <form @submit.prevent="save">
        <fieldset :disabled="busy">
          <label class="otp-email-toggle"><input v-model="config.enabled" type="checkbox" /> Bật Gmail gửi OTP chung cho hệ thống</label>
          <div class="otp-email-fields">
            <label>Gmail gửi<input v-model.trim="config.username" type="email" autocomplete="off" :required="config.enabled" placeholder="email-he-thong@gmail.com" /></label>
            <label>Email người gửi<input v-model.trim="config.from_email" type="email" autocomplete="off" :required="config.enabled" placeholder="Cùng địa chỉ Gmail gửi" /></label>
            <label>Tên người gửi<input v-model.trim="config.from_name" maxlength="120" :required="config.enabled" /></label>
            <label>Mật khẩu ứng dụng Gmail<input v-model="password" type="password" autocomplete="new-password" :required="config.enabled && !config.password_configured" :placeholder="config.password_configured ? 'Đã lưu — để trống để giữ nguyên' : 'Nhập mật khẩu ứng dụng Gmail'" aria-describedby="otp-password-help" /></label>
          </div>
          <p id="otp-password-help">Dùng mật khẩu ứng dụng, không dùng mật khẩu đăng nhập Gmail. Mật khẩu được mã hóa và không hiển thị lại.</p>
          <p>Máy chủ Gmail: smtp.gmail.com · Cổng 587 · STARTTLS. Bật xác minh 2 bước trong Google, sau đó tạo <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">mật khẩu ứng dụng</a>.</p>
          <button class="primary-btn" type="submit">{{ busy ? 'Đang xử lý…' : 'Lưu cấu hình email' }}</button>
        </fieldset>
      </form>
      <form class="otp-email-test" @submit.prevent="sendTest">
        <label>Email nhận thử<input v-model.trim="recipient" type="email" required placeholder="Email của bạn để kiểm tra" :disabled="busy" /></label>
        <button class="settings-refresh" type="submit" :disabled="busy || !config.enabled || !config.password_configured">Gửi email thử</button>
        <small>Email thử dùng cấu hình đã lưu. Khách không cần nhập mật khẩu Gmail.</small>
      </form>
    </template>
  </article>
</template>

<style scoped>
.otp-email-panel { padding: 24px; }
.otp-email-panel fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.otp-email-toggle { display: flex; align-items: center; gap: 10px; margin: 16px 0; }
.otp-email-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.otp-email-fields label, .otp-email-test label { display: grid; gap: 8px; font-weight: 600; }
.otp-email-panel input:not([type="checkbox"]) { width: 100%; min-width: 0; box-sizing: border-box; padding: 12px; border: 1px solid var(--border, #cbdde0); border-radius: 10px; color: inherit; background: var(--surface, transparent); }
.otp-email-panel input:focus-visible { outline: 2px solid #00857e; outline-offset: 2px; }
.otp-email-panel p, .otp-email-panel small { line-height: 1.6; }
.otp-email-panel a { color: inherit; text-decoration: underline; }
.otp-email-test { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border, #cbdde0); display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
.otp-email-test label { flex: 1 1 240px; }
.otp-email-test small { flex-basis: 100%; }
@media (max-width: 640px) { .otp-email-fields { grid-template-columns: 1fr; } .otp-email-panel { padding: 16px; } }
</style>
